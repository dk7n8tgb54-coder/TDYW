"""
资源兜底与限流容错风险验证测试

对应 CRUD系统可靠性指南.md 2.2 节，验证以下风险点：
  R1: 外部 HTTP 请求未设 timeout（requests.get/post 无 timeout 参数）
  R4: 导出操作同步阻塞 worker（非异步 Celery）
  R5: 部分列表接口无分页（返回全量数据）
  R7: Gunicorn timeout 配置验证
  R8: Celery 队列隔离验证

  注：原 R2/R3/R6 针对 exec/transfer.py 的测试已随该死代码文件一并删除。

运行方式：
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python manage.py test apps.resource_resilience_tests --noinput -v2
"""
import ast
import inspect
import textwrap
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from unittest import mock

from django.test import TestCase, RequestFactory, override_settings

# ============================================================
# R1: 外部 HTTP 请求未设 timeout
# ============================================================

class R1ExternalHTTPNoTimeoutTests(TestCase):
    """验证外部 HTTP 调用是否设置了 timeout 参数。

    风险：requests.get/post 不带 timeout 时，远端慢响应或网络不通
    会导致 gevent worker 被无限阻塞，最终打满所有 worker。
    """

    def _get_calls_without_timeout(self, source_path):
        """用 AST 解析源码，找到 requests.get/post 调用中缺少 timeout 的位置"""
        import os
        full_path = os.path.join(os.path.dirname(__file__), source_path)
        with open(full_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=source_path)

        missing = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if (isinstance(func, ast.Attribute) and
                        func.attr in ('get', 'post', 'put', 'delete', 'head', 'patch') and
                        isinstance(func.value, ast.Name) and
                        func.value.id == 'requests'):
                    has_timeout = any(
                        kw.arg == 'timeout' for kw in node.keywords
                    )
                    if not has_timeout:
                        missing.append(func.attr)
        return missing

    def test_push_has_timeout(self):
        """R1.1+R1.2: libs/push.py 所有 requests 调用必须设置 timeout"""
        missing = self._get_calls_without_timeout('../libs/push.py')
        self.assertEqual(missing, [], f"libs/push.py 中 requests 调用缺少 timeout: {missing}")

    def test_helper_has_timeout(self):
        """R1.3+R1.4: libs/helper.py 所有 requests 调用必须设置 timeout"""
        missing = self._get_calls_without_timeout('../libs/helper.py')
        self.assertEqual(missing, [], f"libs/helper.py 中 requests 调用缺少 timeout: {missing}")

    def test_account_update_command_has_timeout(self):
        """R1.5: account/management/commands/update.py 必须设置 timeout"""
        missing = self._get_calls_without_timeout(
            'account/management/commands/update.py')
        self.assertEqual(missing, [],
                         f"account/management/commands/update.py 中 requests 调用缺少 timeout: {missing}")

    def test_get_balance_blocks_indefinitely_without_timeout(self):
        """R1.6: 行为验证 - get_balance 无 timeout 时对慢服务器会阻塞

        用 mock 模拟一个永远不返回的 requests.get，验证调用会挂起
        （证明风险真实存在）。
        """
        from libs.push import get_balance

        call_completed = threading.Event()

        def slow_get(*args, **kwargs):
            timeout = kwargs.get('timeout')
            if timeout:
                raise Exception(f'Connection timed out after {timeout}s')
            call_completed.wait(timeout=5)
            raise Exception('Blocked indefinitely (no timeout set)')

        with mock.patch('libs.push.requests.get', side_effect=slow_get):
            result_holder = {}
            def call():
                try:
                    get_balance('fake_token')
                    result_holder['result'] = 'returned'
                except Exception as e:
                    result_holder['result'] = 'exception'
                    result_holder['msg'] = str(e)

            t = threading.Thread(target=call, daemon=True)
            t.start()
            t.join(timeout=3)

            if t.is_alive():
                call_completed.set()
                self.fail(
                    "get_balance() 无 timeout 参数，对慢服务器会无限阻塞 gevent worker"
                )

            self.assertEqual(result_holder.get('result'), 'exception')


# ============================================================
# R4: 导出操作同步阻塞 worker
# ============================================================

class R4ExportSyncBlockingTests(TestCase):
    """验证导出操作是否有上限保护和异步化。

    风险：导出操作同步执行，大数据量导出（即使有 10000 行上限）
    会阻塞 gevent worker，影响其他请求的响应时间。
    """

    def test_export_limit_constant_exists(self):
        """R4.1: 导出上限常量必须存在"""
        from libs.export_utils import DEFAULT_EXPORT_LIMIT
        self.assertIsNotNone(DEFAULT_EXPORT_LIMIT)
        self.assertGreater(DEFAULT_EXPORT_LIMIT, 0)
        self.assertLessEqual(DEFAULT_EXPORT_LIMIT, 10000,
                             "导出上限不应超过 10000 行")

    def test_check_export_limit_enforces(self):
        """R4.2: check_export_limit 在超限时必须返回错误响应"""
        from libs.export_utils import check_export_limit, DEFAULT_EXPORT_LIMIT
        from django.db.models.query import QuerySet

        mock_qs = mock.MagicMock(spec=QuerySet)
        mock_qs.count.return_value = DEFAULT_EXPORT_LIMIT + 1

        count, error_resp = check_export_limit(mock_qs)
        self.assertEqual(count, DEFAULT_EXPORT_LIMIT + 1)
        self.assertIsNotNone(error_resp, "超过上限时必须返回错误响应")
        self.assertEqual(error_resp.status_code, 400)

    def test_check_export_limit_allows_within_limit(self):
        """R4.3: check_export_limit 在未超限时放行"""
        from libs.export_utils import check_export_limit
        from django.db.models.query import QuerySet

        mock_qs = mock.MagicMock(spec=QuerySet)
        mock_qs.count.return_value = 100

        count, error_resp = check_export_limit(mock_qs)
        self.assertEqual(count, 100)
        self.assertIsNone(error_resp)

    def test_excel_export_loads_all_rows_into_memory(self):
        """R4.4: build_excel_response 全量加载行到内存（风险确认）

        验证方式：传入大量行，检查内存中确实保存了全部行。
        这确认了导出是同步全量加载模式，而非流式。
        """
        from libs.export_utils import build_excel_response

        columns = [('name', '名称'), ('value', '值')]
        rows = [{'name': f'item_{i}', 'value': i} for i in range(5000)]

        response = build_excel_response('test.xlsx', 'Sheet1', columns, rows)
        self.assertEqual(response.status_code, 200)

        content = response.content
        self.assertGreater(len(content), 1000,
                           "导出 5000 行应产生大于 1KB 的 Excel 文件")

    def test_all_export_endpoints_have_limit_check(self):
        """R4.5: 所有模块的导出端点必须调用 check_export_limit"""
        import os
        export_files = [
            'fault/exporters.py',
            'device/exporters.py',
            'interference/exporters.py',
            'runlog/exporters.py',
            'upgrade/exporters.py',
            'duty/views.py',
            'logs/views.py',
        ]

        for rel_path in export_files:
            full_path = os.path.join(os.path.dirname(__file__), rel_path)
            if not os.path.exists(full_path):
                continue

            with open(full_path, 'r', encoding='utf-8') as f:
                source = f.read()

            has_limit = ('check_export_limit' in source or
                         'EXPORT_LIMIT' in source or
                         'export_limit' in source or
                         'PDF_EXPORT_LIMIT' in source)
            self.assertTrue(has_limit,
                            f"{rel_path} 导出端点缺少上限检查 (check_export_limit)")


# ============================================================
# R5: 列表接口无分页
# ============================================================

class R5ListNoPaginationTests(TestCase):
    """验证部分列表接口是否有分页保护。

    风险：无分页的列表接口在数据量增长后会返回全量数据，
    导致内存激增和响应变慢。
    """

    def test_navigation_list_no_pagination(self):
        """R5.3: home/navigation.py NavView.get 返回全量数据无分页"""
        import os
        source_path = os.path.join(os.path.dirname(__file__), 'home', 'navigation.py')
        if not os.path.exists(source_path):
            self.skipTest("home/navigation.py 不存在")

        with open(source_path, 'r', encoding='utf-8') as f:
            source = f.read()

        tree = ast.parse(source)
        found_unbounded = False

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == 'NavView':
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == 'get':
                        func_source = ast.get_source_segment(source, item)
                        has_pagination = ('page' in func_source.lower() or
                                          'paginate' in func_source.lower() or
                                          '[:' in func_source)
                        if not has_pagination:
                            found_unbounded = True

        self.assertFalse(found_unbounded,
                         "NavView.get 返回全量数据无分页")


# ============================================================
# R7: Gunicorn timeout 配置验证
# ============================================================

class R7GunicornConfigTests(TestCase):
    """验证 Gunicorn 超时配置是否合理。"""

    def test_gunicorn_timeout_configured(self):
        """R7.1: Gunicorn 必须配置 timeout"""
        import os
        conf_path = os.path.join(os.path.dirname(__file__), '..', 'gunicorn.conf.py')
        with open(conf_path, 'r', encoding='utf-8') as f:
            source = f.read()

        self.assertIn('timeout', source,
                       "gunicorn.conf.py 必须配置 timeout")

        tree = ast.parse(source)
        timeout_value = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == 'timeout':
                        if isinstance(node.value, ast.Constant):
                            timeout_value = node.value.value

        self.assertIsNotNone(timeout_value, "无法解析 gunicorn timeout 值")
        self.assertGreater(timeout_value, 0, "timeout 必须大于 0")
        self.assertLessEqual(timeout_value, 300,
                             f"timeout={timeout_value} 过大，慢请求会长时间占用 worker")


# ============================================================
# R8: Celery 队列隔离验证
# ============================================================

class R8CeleryQueueIsolationTests(TestCase):
    """验证 Celery 队列是否对重操作做了隔离。"""

    def test_celery_queue_routing_exists(self):
        """R8.1: Celery 应配置队列路由（task_routes）"""
        import os
        settings_path = os.path.join(os.path.dirname(__file__), '..', 'spug', 'settings.py')
        with open(settings_path, 'r', encoding='utf-8') as f:
            source = f.read()

        has_routing = ('CELERY_TASK_ROUTES' in source or
                       'task_routes' in source or
                       'CELERY_QUEUES' in source)
        self.assertTrue(has_routing,
                        "settings.py 应配置 CELERY_TASK_ROUTES 实现队列隔离")

    def test_merge_task_uses_dedicated_queue(self):
        """R8.2: 文档合并任务应使用独立队列 document.merge"""
        import os
        merge_path = os.path.join(os.path.dirname(__file__), 'document', 'tasks', 'merge.py')
        if not os.path.exists(merge_path):
            self.skipTest("document/tasks/merge.py 不存在")

        with open(merge_path, 'r', encoding='utf-8') as f:
            source = f.read()

        has_queue = ("queue=" in source or
                     "queue =" in source)
        self.assertTrue(has_queue,
                        "document/tasks/merge.py 中的 @shared_task 应指定 queue 参数")

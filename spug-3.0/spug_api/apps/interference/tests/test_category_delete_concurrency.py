"""选项删除与事件写入的并发锁序契约测试（独立模块，最后执行）。

TransactionTestCase 结束时会截断本应用数据表（含迁移播种的选项），
因此本模块与业务回归分开运行：先跑 TestCase 套件，最后单独跑本模块；
跑完后如需再跑其他测试，请先重新播种（见汇报说明）。

场景：事件写入线程在真实事务内调用 lock_event_options（与视图同路径）
持有选项行锁；删除线程调用真实删除视图。验证删除在持锁期间被阻塞、
写入提交后因引用存在被拒绝，不会留下无法显示名称的事件。
"""
import json
import threading
import time
from datetime import datetime

from django.db import connection, transaction
from django.test import RequestFactory, TransactionTestCase

from apps.interference import category_services
from apps.interference.category_views import CategoryDetailView
from apps.interference.models import (
    InterferenceCategoryOption,
    InterferenceEvent,
)
from apps.utils.test_helpers import make_user, setup_test_env

EVENT_PERMS = [
    'interference.interference.view',
    'interference.interference.add',
    'interference.interference.edit',
    'interference.interference.del',
]

class CategoryDeleteConcurrencyTest(TransactionTestCase):
    """并发锁序契约：事件写入持选项行锁时，删除阻塞且引用落库后被拒。

    事件写入线程在真实事务内调用 lock_event_options（与视图同路径），
    删除线程调用真实视图；验证删除线程在写入持锁期间无法完成，
    写入提交后删除因引用存在被拒绝，不会留下无法显示名称的事件。
    """

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('inter_del_conc', EVENT_PERMS)
        self.supper = make_user('inter_del_conc_supper', is_supper=True)
        # TransactionTestCase 结束时会清库，测试自建所需选项
        self.option = InterferenceCategoryOption.objects.create(
            group='interference_kind', code='concurrent_kind',
            name='并发类型', sort_id=999)
        for group in ('affected_system', 'source_type'):
            InterferenceCategoryOption.objects.get_or_create(
                group=group, code='unknown', defaults={'name': '未知/待查'})

    def test_delete_blocked_until_event_commit_then_rejected(self):
        results = {}
        writer_locked = threading.Event()
        writer_done = threading.Event()
        delete_done = threading.Event()
        values = {
            'scene_code': 'ground',
            'interference_kind_code': 'concurrent_kind',
            'affected_system_code': 'unknown',
            'source_type_code': 'unknown',
        }

        def run_writer():
            try:
                with transaction.atomic():
                    error = category_services.lock_event_options(values, None)
                    if error:
                        results['writer_error'] = error
                        return
                    writer_locked.set()
                    # 持锁窗口：让删除线程先尝试加锁并被阻塞
                    time.sleep(1.5)
                    InterferenceEvent.objects.create(
                        tenant_id=self.user.tenant_id,
                        datetime=datetime(2026, 10, 22, 9, 0),
                        scene_code='ground',
                        interference_kind_code='concurrent_kind',
                        affected_system_code='unknown',
                        source_type_code='unknown',
                        phenomenon='并发写入', created_by=self.user)
            except Exception as exc:
                results['writer_exception'] = repr(exc)
            finally:
                writer_done.set()
                connection.close()

        def run_delete():
            try:
                factory = RequestFactory()
                request = factory.delete(
                    f'/interference/categories/{self.option.id}/')
                request.user = self.supper
                response = CategoryDetailView().delete(request, self.option.id)
                results['delete'] = json.loads(response.content)
            except Exception as exc:
                results['delete_exception'] = repr(exc)
            finally:
                delete_done.set()
                connection.close()

        writer = threading.Thread(target=run_writer)
        writer.start()
        self.assertTrue(writer_locked.wait(5), '写入线程未能在 5 秒内取得选项行锁')
        deleter = threading.Thread(target=run_delete)
        deleter.start()
        # 写入持锁期间（1.5 秒窗口）删除不得完成
        self.assertFalse(delete_done.wait(1.0), '删除未被事件写入的行锁阻塞')
        self.assertTrue(writer_done.wait(10), '写入线程未按时提交')
        self.assertTrue(delete_done.wait(10), '删除线程未按时返回')
        self.assertNotIn('writer_error', results, results)
        self.assertNotIn('writer_exception', results, results)
        self.assertNotIn('delete_exception', results, results)
        self.assertIn('引用', results['delete'].get('error', ''), results)
        self.assertIn('停用', results['delete'].get('error', ''), results)
        # 选项仍在，事件可正常按名称显示
        self.assertTrue(
            InterferenceCategoryOption.objects.filter(pk=self.option.id).exists())
        event = InterferenceEvent.objects.get(
            interference_kind_code='concurrent_kind')
        self.assertEqual(event.to_view()['interference_kind_text'], '并发类型')
        writer.join(1)
        deleter.join(1)

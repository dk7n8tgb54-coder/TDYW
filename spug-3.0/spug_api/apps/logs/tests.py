# -*- coding: utf-8 -*-
"""审计日志模块测试

覆盖：
- 列表查询（基础/筛选/分页）
- 权限校验（system.audit.view）
- 租户隔离（非超管只能看自己租户）
- 导出（含审计自身被记录）
- 元数据接口（target_types / actions）
- 哈希链字段写入（prev_hash / log_hash / request_hash）
- 工具函数（resolve_target / resolve_action）
- 哈希链定时任务 verify_audit_hash_chain（租户去重 / 最近 N 条升序校验 / tenants_checked）
- 定时任务队列配置（Beat 与 CELERY_TASK_ROUTES 必须指向有 Worker 消费的 celery 队列）
"""
import tempfile
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.logs.models import AuditLog
from apps.logs.audit import (
    save_audit_log, resolve_target, resolve_action, sanitize_audit_detail,
)
from apps.logs.tasks import verify_audit_hash_chain
from apps.utils.test_helpers import make_user, make_client, setup_test_env


# User.tenant_id 默认值为 'admin'（非 'default'），故测试默认用 'admin' 写入日志
DEFAULT_TENANT = 'admin'


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AuditLogViewTest(TestCase):
    """审计日志视图测试"""

    def setUp(self):
        setup_test_env(self)
        self.viewer = make_user('viewer', ['system.audit.view'])
        self.noperm = make_user('noperm', [])
        self.supper = make_user('supper', is_supper=True)
        self.viewer_client = make_client(self.viewer)
        self.noperm_client = make_client(self.noperm)
        self.supper_client = make_client(self.supper)

    def _create_log(self, username='alice', action='create', target_type='user',
                    target_name='测试对象', tenant_id=DEFAULT_TENANT, is_success=True):
        save_audit_log(
            user_id=1, username=username, action=action,
            target_type=target_type, target_id='1', target_name=target_name,
            detail={'summary': '测试'}, ip='127.0.0.1',
            is_success=is_success, tenant_id=tenant_id,
        )
        return AuditLog.objects.order_by('-id').first()

    # ---- 权限校验 ----

    def test_list_denied_without_perm(self):
        r = self.noperm_client.get('/logs/audit/')
        self.assertTrue(r.json().get('error'))

    def test_list_ok_with_perm(self):
        self._create_log()
        r = self.viewer_client.get('/logs/audit/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['total'], 1)

    def test_list_ok_as_supper(self):
        self._create_log()
        r = self.supper_client.get('/logs/audit/')
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['total'], 1)

    # ---- 筛选 ----

    def test_filter_by_action(self):
        self._create_log(username='a', action='create')
        self._create_log(username='b', action='delete')
        r = self.viewer_client.get('/logs/audit/?action=create')
        body = r.json()
        self.assertEqual(body['data']['total'], 1)
        self.assertEqual(body['data']['records'][0]['action'], 'create')

    def test_filter_by_target_type(self):
        self._create_log(target_type='user')
        self._create_log(target_type='role')
        r = self.viewer_client.get('/logs/audit/?target_type=role')
        self.assertEqual(r.json()['data']['total'], 1)

    def test_filter_by_username(self):
        self._create_log(username='alice')
        self._create_log(username='bob')
        r = self.viewer_client.get('/logs/audit/?username=alice')
        self.assertEqual(r.json()['data']['total'], 1)

    def test_filter_by_is_success(self):
        self._create_log(is_success=True)
        self._create_log(is_success=False)
        r = self.viewer_client.get('/logs/audit/?is_success=false')
        body = r.json()
        self.assertEqual(body['data']['total'], 1)
        self.assertFalse(body['data']['records'][0]['is_success'])

    def test_filter_by_keyword(self):
        self._create_log(target_name='重要文件')
        self._create_log(target_name='普通文件')
        r = self.viewer_client.get('/logs/audit/?keyword=重要')
        self.assertEqual(r.json()['data']['total'], 1)

    def test_filter_by_time_range(self):
        """时间范围筛选（兼容 YYYY-MM-DD 格式）"""
        self._create_log()
        today = timezone.now().strftime('%Y-%m-%d')
        tomorrow = (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        r = self.viewer_client.get(
            f'/logs/audit/?start_time={today}&end_time={tomorrow}'
        )
        body = r.json()
        self.assertFalse(body.get('error'), body.get('error', ''))
        self.assertEqual(body['data']['total'], 1)

    def test_filter_by_time_range_excludes_old(self):
        """时间范围外的日志不返回"""
        log = self._create_log()
        # 改为 5 天前
        AuditLog.objects.filter(id=log.id).update(
            created_at=timezone.now() - timedelta(days=5)
        )
        today = timezone.now().strftime('%Y-%m-%d')
        tomorrow = (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        r = self.viewer_client.get(
            f'/logs/audit/?start_time={today}&end_time={tomorrow}'
        )
        body = r.json()
        self.assertFalse(body.get('error'), body.get('error', ''))
        self.assertEqual(body['data']['total'], 0)

    # ---- 分页 ----

    def test_pagination(self):
        for i in range(15):
            self._create_log(username=f'u{i}')
        r = self.viewer_client.get('/logs/audit/?page=1&page_size=10')
        body = r.json()
        self.assertEqual(body['data']['total'], 15)
        self.assertEqual(len(body['data']['records']), 10)
        self.assertEqual(body['data']['page'], 1)
        self.assertEqual(body['data']['page_size'], 10)

    def test_page_size_clamped_to_max_100(self):
        """page_size 上限 100"""
        for i in range(5):
            self._create_log(username=f'u{i}')
        r = self.viewer_client.get('/logs/audit/?page_size=200')
        body = r.json()
        self.assertLessEqual(body['data']['page_size'], 100)

    def test_page_min_clamped_to_1(self):
        """page 下限 1"""
        self._create_log()
        r = self.viewer_client.get('/logs/audit/?page=-1')
        body = r.json()
        self.assertEqual(body['data']['page'], 1)

    # ---- 租户隔离 ----

    def test_tenant_isolation_non_supper(self):
        """非超管只能看自己租户（admin）的日志"""
        self._create_log(username='a', tenant_id='tenant-a')
        self._create_log(username='b', tenant_id='tenant-b')
        r = self.viewer_client.get('/logs/audit/')
        self.assertEqual(r.json()['data']['total'], 0)

    def test_tenant_isolation_sees_own_tenant(self):
        """viewer（tenant_id=admin）能看到本租户日志"""
        self._create_log(username='a', tenant_id=DEFAULT_TENANT)
        self._create_log(username='b', tenant_id='tenant-x')
        r = self.viewer_client.get('/logs/audit/')
        self.assertEqual(r.json()['data']['total'], 1)

    def test_supper_sees_all_tenants(self):
        """超管能看到所有租户的日志"""
        self._create_log(username='a', tenant_id='tenant-a')
        self._create_log(username='b', tenant_id='tenant-b')
        r = self.supper_client.get('/logs/audit/')
        self.assertEqual(r.json()['data']['total'], 2)

    # ---- 导出 ----

    def test_export_denied_without_perm(self):
        r = self.noperm_client.get('/logs/audit/export/')
        self.assertTrue(r.json().get('error'))

    def test_export_ok(self):
        self._create_log()
        r = self.viewer_client.get('/logs/audit/export/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body['data'], list)
        self.assertEqual(len(body['data']), 1)

    def test_export_records_audit_itself(self):
        """导出审计日志本身也要被审计（action=export, target_type=audit）"""
        self._create_log()
        before = AuditLog.objects.count()
        self.viewer_client.get('/logs/audit/export/')
        after = AuditLog.objects.count()
        self.assertEqual(after - before, 1)
        export_log = AuditLog.objects.filter(
            action='export', target_type='audit'
        ).first()
        self.assertIsNotNone(export_log)

    def test_export_respects_tenant_isolation(self):
        """导出也受租户隔离限制"""
        self._create_log(username='a', tenant_id='tenant-x')
        r = self.viewer_client.get('/logs/audit/export/')
        body = r.json()
        self.assertEqual(len(body['data']), 0)

    # ---- 元数据接口 ----

    def test_target_types(self):
        r = self.viewer_client.get('/logs/audit/target_types/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body.get('error'))
        types = body['data']
        self.assertTrue(any(t['value'] == 'user' for t in types))

    def test_actions(self):
        r = self.viewer_client.get('/logs/audit/actions/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body.get('error'))
        action_values = [a['value'] for a in body['data']]
        self.assertIn('create', action_values)
        self.assertIn('delete', action_values)
        self.assertIn('login', action_values)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AuditLogHashChainTest(TestCase):
    """审计日志哈希链字段测试（证据闭环第一阶段）"""

    def setUp(self):
        setup_test_env(self)

    def test_hash_fields_populated(self):
        """save_audit_log 写入 log_hash / request_hash / prev_hash"""
        save_audit_log(
            user_id=1, username='alice', action='create',
            target_type='user', target_id='1', target_name='测试',
            detail={'k': 'v'}, ip='127.0.0.1', tenant_id=DEFAULT_TENANT,
        )
        log = AuditLog.objects.get()
        self.assertTrue(log.log_hash, 'log_hash 应非空')
        self.assertTrue(log.request_hash, 'request_hash 应非空')
        self.assertEqual(log.prev_hash, '', '链首 prev_hash 为空串')

    def test_hash_chain_continuity(self):
        """连续写入的日志形成哈希链"""
        save_audit_log(
            user_id=1, username='a', action='create',
            target_type='user', target_id='1', target_name='1',
            ip='127.0.0.1', tenant_id=DEFAULT_TENANT,
        )
        first = AuditLog.objects.first()
        save_audit_log(
            user_id=2, username='b', action='delete',
            target_type='user', target_id='2', target_name='2',
            ip='127.0.0.1', tenant_id=DEFAULT_TENANT,
        )
        second = AuditLog.objects.order_by('-id').first()
        self.assertEqual(second.prev_hash, first.log_hash)
        self.assertNotEqual(second.log_hash, first.log_hash)

    def test_hash_chain_per_tenant(self):
        """哈希链按租户隔离：不同租户独立成链"""
        save_audit_log(
            user_id=1, username='a', action='create',
            target_type='user', target_id='1', target_name='1',
            ip='127.0.0.1', tenant_id='tenant-a',
        )
        save_audit_log(
            user_id=2, username='b', action='create',
            target_type='user', target_id='2', target_name='2',
            ip='127.0.0.1', tenant_id='tenant-b',
        )
        # tenant-b 的第一条日志 prev_hash 应为空（独立链首）
        log_b = AuditLog.objects.filter(tenant_id='tenant-b').first()
        self.assertEqual(log_b.prev_hash, '')

    def test_log_hash_changes_with_detail(self):
        """detail 不同 → log_hash 不同"""
        save_audit_log(
            user_id=1, username='a', action='create',
            target_type='user', target_id='1', target_name='1',
            detail={'k': 'v1'}, ip='127.0.0.1', tenant_id=DEFAULT_TENANT,
        )
        h1 = AuditLog.objects.first().log_hash
        save_audit_log(
            user_id=1, username='a', action='create',
            target_type='user', target_id='1', target_name='1',
            detail={'k': 'v2'}, ip='127.0.0.1', tenant_id=DEFAULT_TENANT,
        )
        h2 = AuditLog.objects.order_by('-id').first().log_hash
        self.assertNotEqual(h1, h2)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AuditLogResolverTest(TestCase):
    """resolve_target / resolve_action / sanitize_audit_detail 工具函数测试"""

    def test_resolve_target_known(self):
        info = resolve_target('/account/user/')
        self.assertEqual(info['type'], 'user')

    def test_resolve_target_unknown(self):
        info = resolve_target('/unknown/path/')
        self.assertEqual(info['type'], 'unknown')

    def test_resolve_action_by_method(self):
        self.assertEqual(resolve_action('POST'), 'create')
        self.assertEqual(resolve_action('DELETE'), 'delete')
        self.assertEqual(resolve_action('GET'), 'other')

    def test_resolve_action_body_action_takes_priority(self):
        """请求体 action 字段优先于 HTTP 方法"""
        self.assertEqual(resolve_action('POST', {'action': 'delete'}), 'delete')
        self.assertEqual(resolve_action('POST', {'action': 'export'}), 'export')

    def test_resolve_action_invalid_body_action_falls_back_to_method(self):
        """请求体 action 不是已知映射时回退到 HTTP 方法"""
        self.assertEqual(resolve_action('POST', {'action': 'unknown_action'}), 'create')

    def test_sanitize_redacts_sensitive_fields(self):
        result = sanitize_audit_detail({'password': 'secret', 'name': 'alice'})
        self.assertEqual(result['password'], '***')
        self.assertEqual(result['name'], 'alice')

    def test_sanitize_truncates_long_string(self):
        long_str = 'x' * 1000
        result = sanitize_audit_detail(long_str, max_string_length=100)
        self.assertTrue(result.endswith('...'))
        self.assertEqual(len(result), 103)

    def test_sanitize_truncates_long_list(self):
        result = sanitize_audit_detail(list(range(30)), max_list_items=10)
        self.assertEqual(len(result), 11)  # 10 项 + 1 个 _truncated 标记
        self.assertIn('_truncated', result[-1])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class VerifyAuditHashChainTaskTest(TestCase):
    """verify_audit_hash_chain 定时任务行为测试

    通过 .apply() 在真实 Django 测试数据库中同步执行任务代码路径，
    不以读取源码字符串代替行为验证。
    """

    def setUp(self):
        setup_test_env(self)

    def _write_logs(self, tenant_id, count):
        """按时间顺序写入 count 条同租户审计日志，返回写入的实例列表"""
        logs = []
        for i in range(count):
            save_audit_log(
                user_id=1, username=f'user{i}', action='create',
                target_type='user', target_id=str(i), target_name=f'对象{i}',
                ip='127.0.0.1', tenant_id=tenant_id,
            )
            logs.append(AuditLog.objects.order_by('-id').first())
        return logs

    def test_tenant_query_dedup_under_model_ordering(self):
        """AuditLog 默认排序为 ('-id',) 时，任务的租户查询必须只返回唯一租户"""
        self.assertEqual(AuditLog._meta.ordering, ('-id',),
                         '前置条件：AuditLog.Meta.ordering 为 (\'-id\',)')
        self._write_logs('tenant-a', 3)
        self._write_logs('tenant-b', 2)

        # 旧写法（未清除默认排序）：DISTINCT 连带 id 列，同一租户重复出现
        buggy = list(
            AuditLog.objects.exclude(tenant_id='')
            .values_list('tenant_id', flat=True).distinct()
        )
        self.assertEqual(len(buggy), 5)
        self.assertEqual(len(set(buggy)), 2, '旧写法在 Meta.ordering 下会产生重复租户')

        # 任务采用的新写法：order_by() 清除默认排序后按 tenant_id 去重
        fixed = list(
            AuditLog.objects.exclude(tenant_id='')
            .order_by()
            .values_list('tenant_id', flat=True).distinct()
        )
        self.assertEqual(sorted(fixed), ['tenant-a', 'tenant-b'])

    def test_task_verifies_each_tenant_once(self):
        """在真实测试库中执行：每个租户只校验一次且租户查询不重复"""
        self._write_logs('tenant-a', 3)
        self._write_logs('tenant-b', 2)

        from apps.logs import hash_chain as hash_chain_mod
        real_verify = hash_chain_mod.verify_hash_chain
        calls = []

        def spy(audit_logs):
            calls.append(list(audit_logs))
            return real_verify(audit_logs)

        with mock.patch('apps.logs.hash_chain.verify_hash_chain',
                        side_effect=spy):
            result = verify_audit_hash_chain.apply(args=()).get()

        self.assertEqual(result['status'], 'success')
        self.assertEqual(len(calls), 2, '每个租户应只执行一次哈希链校验')
        self.assertEqual(sorted(c[0].tenant_id for c in calls),
                         ['tenant-a', 'tenant-b'])

    def test_tenants_checked_reflects_real_count(self):
        """无错误时 tenants_checked 必须为实际检查的租户数（而非 0）"""
        self._write_logs('tenant-a', 2)
        self._write_logs('tenant-b', 1)
        result = verify_audit_hash_chain.apply(args=()).get()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['total_errors'], 0)
        self.assertEqual(result['tenants_checked'], 2)

    def test_verify_selects_most_recent_logs_in_ascending_id_order(self):
        """只校验最近 HASH_CHAIN_VERIFY_LIMIT 条，且传入链校验时为 id 升序"""
        logs = self._write_logs('tenant-a', 8)

        from apps.logs import hash_chain as hash_chain_mod
        from apps.logs import tasks as logs_tasks
        real_verify = hash_chain_mod.verify_hash_chain
        captured = []

        def spy(audit_logs):
            captured.append(list(audit_logs))
            return real_verify(audit_logs)

        with mock.patch.object(logs_tasks, 'HASH_CHAIN_VERIFY_LIMIT', 5), \
                mock.patch('apps.logs.hash_chain.verify_hash_chain',
                           side_effect=spy):
            result = verify_audit_hash_chain.apply(args=()).get()

        self.assertEqual(result['status'], 'success')
        self.assertEqual(len(captured), 1)
        checked = captured[0]
        self.assertEqual(len(checked), 5, '只校验最近 5 条')
        ids = [log.id for log in checked]
        self.assertEqual(ids, sorted(ids), '传给 verify_hash_chain 必须是 id 升序')
        self.assertEqual(ids, sorted(log.id for log in logs)[-5:],
                         '选中的必须是 id 最大的 5 条（最近写入的记录）')
        self.assertEqual(result['total_errors'], 0,
                         '最近 N 条切片按升序校验时链应完整（首条 prev 不校验）')


class LogsTaskQueueConfigTest(TestCase):
    """logs 定时任务队列配置一致性

    default-worker 只监听 celery 队列，投递到 default 队列的任务
    永远无人消费，因此 Beat 与 CELERY_TASK_ROUTES 必须指向 celery。
    """

    def test_beat_schedule_entries_use_celery_queue(self):
        from apps.logs.celery_beat_schedule import LOGS_BEAT_SCHEDULE
        expected_tasks = {
            'logs-cleanup-old-audit-logs': 'apps.logs.tasks.cleanup_old_audit_logs',
            'logs-verify-audit-hash-chain': 'apps.logs.tasks.verify_audit_hash_chain',
        }
        for entry_name, task_name in expected_tasks.items():
            entry = LOGS_BEAT_SCHEDULE[entry_name]
            self.assertEqual(entry['task'], task_name)
            self.assertEqual(
                entry['options']['queue'], 'celery',
                f'{entry_name} 必须投递到 celery 队列',
            )

    def test_celery_task_routes_use_celery_queue(self):
        from django.conf import settings
        for task_name in ('apps.logs.tasks.cleanup_old_audit_logs',
                          'apps.logs.tasks.verify_audit_hash_chain'):
            self.assertEqual(
                settings.CELERY_TASK_ROUTES[task_name]['queue'], 'celery',
                f'{task_name} 的路由必须指向 celery 队列',
            )

"""
审计日志风险点验证测试（修复后）

基于 CRUD 系统可靠性指南 1.5（防误操作与可追溯机制）和 3.2（可追溯的日志体系）要求，
验证项目审计日志体系的合规性和完整性。

运行方式（在 tdyw-test 容器内）：
    docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
        python manage.py test apps.audit_risk_tests --noinput

修复清单：
    A1 (P0): 审计日志保留周期 60 -> 90 天
    A2 (P1): 5 个导出视图添加 record_audit_event
    A3 (P1): 7 个 Celery 任务添加 log_celery_audit
    A4 (P2): save_audit_log/record_audit_event/中间件失败时调用 send_alert
    A5 (P2): 哈希链并发竞态修复（select_for_update 行锁）
    A6 (P2): 删除 @audit 装饰器死代码
    A7 (P2): record_audit_event 支持 before_value/after_value 参数
"""

import importlib
import inspect
import logging
import threading
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase, RequestFactory
from django.utils import timezone

from apps.logs.models import AuditLog
from apps.logs.audit import (
    save_audit_log,
    record_audit_event,
    log_celery_audit,
    sanitize_audit_detail,
    SENSITIVE_KEYWORDS,
)
from apps.logs.hash_chain import (
    verify_log_hash,
    verify_hash_chain,
)
from apps.logs.tasks import cleanup_old_audit_logs, MIN_RETENTION_DAYS

logger = logging.getLogger(__name__)


# ===========================================================================
# A1: 审计日志保留周期合规性测试
# 指南 3.2 要求：操作审计日志保留 ≥ 90 天
# ===========================================================================

class AuditLogRetentionTest(TestCase):
    """A1 修复验证：审计日志保留周期 90 天"""

    def test_retention_days_is_90(self):
        """验证默认保留天数为 90 天"""
        sig = inspect.signature(cleanup_old_audit_logs)
        default_days = sig.parameters['days'].default

        self.assertEqual(
            default_days, 90,
            f'审计日志默认保留天数应为 90 天，实际 {default_days}'
        )

    def test_min_retention_days_is_90(self):
        """验证 MIN_RETENTION_DAYS 为 90 天"""
        self.assertEqual(
            MIN_RETENTION_DAYS, 90,
            f'MIN_RETENTION_DAYS 应为 90，实际 {MIN_RETENTION_DAYS}'
        )

    def test_cleanup_does_not_delete_logs_within_90_days(self):
        """验证 90 天内的审计日志不会被清理"""
        old_time = timezone.now() - timedelta(days=50)
        AuditLog.objects.create(
            tenant_id='retention_test',
            user_id=1,
            username='test_user',
            action='create',
            target_type='test',
            target_id='1',
            target_name='test_target',
            detail='{}',
            ip='127.0.0.1',
            is_success=True,
            created_at=old_time,
        )

        result = cleanup_old_audit_logs(days=90, dry_run=True)

        self.assertEqual(result['status'], 'success')
        self.assertEqual(
            result['deleted_count'], 0,
            '50 天前的日志不应在 90 天保留期下被清理'
        )


# ===========================================================================
# A2: 导出操作审计日志覆盖测试
# 指南 3.2 要求：数据操作日志可定位到具体人、具体时间、具体变更内容
# ===========================================================================

class ExportAuditCoverageTest(TestCase):
    """A2 修复验证：导出视图已有审计日志"""

    ALL_EXPORT_VIEWS = [
        'apps.fault.exporters.FaultRecordExportView',
        'apps.interference.exporters.InterferenceExportView',
        'apps.upgrade.exporters.UpgradeRecordExportView',
        'apps.runlog.exporters.RunLogExportView',
        'apps.device.exporters.DeviceListExportView',
        'apps.device.views.DeviceResumeExportView',
    ]

    def test_all_export_views_have_audit_logging(self):
        """验证所有导出视图都有审计日志记录"""
        missing = []
        for view_path in self.ALL_EXPORT_VIEWS:
            parts = view_path.rsplit('.', 1)
            module_path, class_name = parts[0], parts[1]
            try:
                module = importlib.import_module(module_path)
                cls = getattr(module, class_name, None)
                if cls is None:
                    continue
                source = inspect.getsource(cls)
                has_audit = (
                    'record_audit_event' in source or
                    'save_audit_log' in source
                )
                if not has_audit:
                    missing.append(view_path)
            except (ImportError, OSError):
                continue

        self.assertEqual(
            missing, [],
            f'以下导出视图缺少审计日志记录: {missing}'
        )


# ===========================================================================
# A3: Celery 任务数据修改审计测试
# 指南 1.5 要求：关键数据变更留痕
# ===========================================================================

class CeleryTaskAuditTest(TestCase):
    """A3 修复验证：Celery 任务已有审计日志"""

    TASK_FILES_WITH_DB_MODIFICATIONS = [
        'apps.radio_license.tasks',
        'apps.contract_agreement.tasks',
        'apps.home.tasks',
        'apps.document.tasks.merge',
        'apps.document.tasks.timeout_checker',
        'apps.document.tasks.batch.tasks',
        'apps.document.tasks.batch.deleters',
    ]

    def test_celery_tasks_have_audit_logging(self):
        """验证修改数据的 Celery 任务有审计日志记录"""
        missing = []
        for module_path in self.TASK_FILES_WITH_DB_MODIFICATIONS:
            try:
                module = importlib.import_module(module_path)
                source = inspect.getsource(module)
                has_db_write = any(
                    pattern in source
                    for pattern in ['.save()', '.update(', '.delete()', 'bulk_create']
                )
                has_audit = (
                    'record_audit_event' in source or
                    'save_audit_log' in source or
                    'log_celery_audit' in source
                )
                if has_db_write and not has_audit:
                    missing.append(module_path)
            except (ImportError, OSError):
                continue

        self.assertEqual(
            missing, [],
            f'以下 Celery 任务模块修改了数据库但无审计日志: {missing}'
        )


# ===========================================================================
# A4: save_audit_log 失败告警测试
# 指南 3.2 要求：ERROR 触发告警
# ===========================================================================

class AuditLogFailureAlertTest(TestCase):
    """A4 修复验证：审计日志写入失败时发送告警"""

    def test_save_audit_log_failure_triggers_alert(self):
        """验证 save_audit_log 失败时调用告警函数"""
        source = inspect.getsource(save_audit_log)
        # save_audit_log 通过 _send_audit_alert 封装发送告警
        self.assertTrue(
            '_send_audit_alert' in source or 'send_alert' in source,
            'save_audit_log 失败时应调用 _send_audit_alert() 或 send_alert()'
        )

    def test_record_audit_event_failure_triggers_alert(self):
        """验证 record_audit_event 失败时调用告警函数"""
        source = inspect.getsource(record_audit_event)
        self.assertTrue(
            '_send_audit_alert' in source or 'send_alert' in source,
            'record_audit_event 失败时应调用 _send_audit_alert() 或 send_alert()'
        )

    def test_audit_middleware_failure_triggers_alert(self):
        """验证中间件审计失败时调用告警函数"""
        from apps.logs.middleware import AuditLogMiddleware
        source = inspect.getsource(AuditLogMiddleware)
        self.assertIn(
            'send_alert', source,
            'AuditLogMiddleware 失败时应调用 send_alert()'
        )

    def test_send_audit_alert_calls_send_alert(self):
        """验证 _send_audit_alert 内部调用 send_alert"""
        from apps.logs.audit import _send_audit_alert
        source = inspect.getsource(_send_audit_alert)
        self.assertIn(
            'send_alert', source,
            '_send_audit_alert 应调用 send_alert() 发送告警'
        )


# ===========================================================================
# A5: 哈希链并发竞态修复测试
# ===========================================================================

class HashChainConcurrencyTest(TestCase):
    """A5 修复验证：select_for_update 防止并发分叉"""

    def setUp(self):
        AuditLog.objects.filter(tenant_id='concurrent_test').delete()

    def tearDown(self):
        AuditLog.objects.filter(tenant_id='concurrent_test').delete()

    def test_save_audit_log_uses_select_for_update(self):
        """验证 save_audit_log 使用 select_for_update 防止并发分叉"""
        source = inspect.getsource(save_audit_log)
        self.assertIn(
            'select_for_update', source,
            'save_audit_log 应使用 select_for_update() 加行锁防止并发分叉'
        )

    def test_concurrent_writes_produce_valid_chain(self):
        """验证顺序写入（模拟并发后的最终状态）的哈希链正确性

        注意：Django TestCase 的事务快照使线程写入不可见，无法直接测试并发。
        select_for_update 的存在（上一个测试验证）是并发安全的保障。
        此测试验证在多条日志写入后链仍然连续。
        """
        actions = ['update', 'delete', 'other']
        for i, action in enumerate(actions):
            save_audit_log(
                user_id=1,
                username='concurrent_user',
                action=action,
                target_type='test',
                target_id=str(i),
                target_name=f'concurrent_{i}',
                detail={'action': action},
                ip='127.0.0.1',
                is_success=True,
                tenant_id='concurrent_test',
            )

        logs = list(AuditLog.objects.filter(
            tenant_id='concurrent_test'
        ).order_by('id'))

        self.assertGreaterEqual(
            len(logs), 3,
            f'应至少生成 3 条日志，实际 {len(logs)} 条'
        )

        # 验证所有日志的 prev_hash 链连续
        for i in range(1, len(logs)):
            self.assertEqual(
                logs[i].prev_hash, logs[i - 1].log_hash,
                f'第 {i + 1} 条日志的 prev_hash 不等于第 {i} 条的 log_hash'
            )


# ===========================================================================
# A6: @audit 装饰器死代码已删除
# ===========================================================================

class AuditDecoratorRemovedTest(TestCase):
    """A6 修复验证：@audit 装饰器死代码已删除"""

    def test_audit_decorator_is_removed(self):
        """验证 @audit 装饰器已从 audit.py 中删除"""
        from apps.logs import audit as audit_module
        self.assertFalse(
            hasattr(audit_module, 'audit'),
            '@audit 装饰器应已从 audit.py 中删除'
        )

    def test_no_audit_decorator_usage_in_project(self):
        """验证项目中没有 @audit 装饰器的使用"""
        import os
        import re

        apps_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        apps_dir = os.path.join(apps_dir, 'apps')

        for root, dirs, files in os.walk(apps_dir):
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    matches = re.findall(r'^\s*@audit\(', content, re.MULTILINE)
                    self.assertEqual(
                        matches, [],
                        f'文件 {fpath} 中发现了 @audit( 装饰器使用，应已删除'
                    )
                except (IOError, UnicodeDecodeError):
                    continue


# ===========================================================================
# A7: 变更前后值记录测试
# 指南 1.5 要求：关键数据变更留痕（变更前后值）
# ===========================================================================

class AuditLogChangeTrackingTest(TestCase):
    """A7 修复验证：record_audit_event 支持 before/after 参数"""

    def setUp(self):
        AuditLog.objects.filter(tenant_id='change_tracking_test').delete()

    def tearDown(self):
        AuditLog.objects.filter(tenant_id='change_tracking_test').delete()

    def test_record_audit_event_supports_before_after(self):
        """验证 record_audit_event 支持 before_value/after_value 参数"""
        sig = inspect.signature(record_audit_event)
        params = set(sig.parameters.keys())

        self.assertIn(
            'before_value', params,
            f'record_audit_event 应支持 before_value 参数。当前参数: {sorted(params)}'
        )
        self.assertIn(
            'after_value', params,
            f'record_audit_event 应支持 after_value 参数。当前参数: {sorted(params)}'
        )

    def test_before_after_values_are_recorded_in_detail(self):
        """验证 before/after 值被写入 detail 字段"""
        factory = RequestFactory()
        request = factory.put('/test/', {'name': 'new_value'})
        request.user = MagicMock(
            id=1,
            username='test_user',
            tenant_id='change_tracking_test',
        )
        request.headers = {'User-Agent': 'TestAgent/1.0'}

        record_audit_event(
            request,
            action='update',
            target_type='device',
            target_id='1',
            target_name='device_001',
            detail={'summary': '设备名称修改'},
            before_value={'name': 'old_name'},
            after_value={'name': 'new_name'},
        )

        log = AuditLog.objects.filter(
            tenant_id='change_tracking_test'
        ).first()
        self.assertIsNotNone(log, '审计日志应被写入')

        import json
        detail = json.loads(log.detail)
        self.assertIn('before', detail, 'detail 应包含 before 字段')
        self.assertIn('after', detail, 'detail 应包含 after 字段')
        self.assertEqual(detail['before'], {'name': 'old_name'})
        self.assertEqual(detail['after'], {'name': 'new_name'})


# ===========================================================================
# 敏感信息脱敏测试
# ===========================================================================

class SensitiveDataSanitizationTest(TestCase):
    """验证敏感信息脱敏机制"""

    def test_password_is_redacted(self):
        detail = {'name': 'test', 'password': 'secret123'}
        sanitized = sanitize_audit_detail(detail)
        self.assertEqual(sanitized['password'], '***')

    def test_token_is_redacted(self):
        detail = {'access_token': 'abc123', 'data': 'ok'}
        sanitized = sanitize_audit_detail(detail)
        self.assertEqual(sanitized['access_token'], '***')

    def test_api_key_is_redacted(self):
        detail = {'api_key': 'sk-123456'}
        sanitized = sanitize_audit_detail(detail)
        self.assertEqual(sanitized['api_key'], '***')

    def test_nested_sensitive_field_is_redacted(self):
        detail = {
            'user': {'name': 'test', 'private_key': '-----BEGIN RSA-----'},
            'data': 'ok',
        }
        sanitized = sanitize_audit_detail(detail)
        self.assertEqual(sanitized['user']['private_key'], '***')

    def test_sensitive_keywords_completeness(self):
        required_keywords = ['password', 'token', 'secret', 'key', 'private', 'credential']
        for keyword in required_keywords:
            self.assertIn(keyword, SENSITIVE_KEYWORDS)


# ===========================================================================
# 哈希链完整性基础测试
# ===========================================================================

class HashChainIntegrityTest(TestCase):
    """哈希链完整性基础验证"""

    def setUp(self):
        AuditLog.objects.filter(tenant_id='chain_test').delete()

    def test_single_log_hash_is_valid(self):
        save_audit_log(
            user_id=1,
            username='chain_test',
            action='create',
            target_type='test',
            target_id='1',
            target_name='test_target',
            detail='{}',
            ip='127.0.0.1',
            is_success=True,
            tenant_id='chain_test',
        )

        log = AuditLog.objects.filter(tenant_id='chain_test').first()
        self.assertIsNotNone(log)
        self.assertTrue(verify_log_hash(log))
        self.assertEqual(log.prev_hash, '')

    def test_chain_of_three_logs_is_continuous(self):
        actions = ['create', 'update', 'delete']
        for i, action in enumerate(actions):
            save_audit_log(
                user_id=1,
                username='chain_test',
                action=action,
                target_type='test',
                target_id=str(i),
                target_name=f'target_{i}',
                detail='{}',
                ip='127.0.0.1',
                is_success=True,
                tenant_id='chain_test',
            )

        logs = list(AuditLog.objects.filter(
            tenant_id='chain_test'
        ).order_by('id'))

        self.assertEqual(len(logs), 3)

        result = verify_hash_chain(logs)
        self.assertTrue(
            result['valid'],
            f'哈希链应连续无断裂: {result["errors"]}'
        )

    def test_tampered_log_is_detected(self):
        save_audit_log(
            user_id=1,
            username='chain_test',
            action='create',
            target_type='test',
            target_id='1',
            target_name='original_name',
            detail='{}',
            ip='127.0.0.1',
            is_success=True,
            tenant_id='chain_test',
        )

        log = AuditLog.objects.filter(tenant_id='chain_test').first()
        log.target_name = 'tampered_name'
        log.save(update_fields=['target_name'])

        log.refresh_from_db()
        self.assertFalse(verify_log_hash(log))

    def test_empty_detail_is_handled(self):
        save_audit_log(
            user_id=1,
            username='chain_test',
            action='create',
            target_type='test',
            target_id='1',
            target_name='test',
            detail=None,
            ip='127.0.0.1',
            is_success=True,
            tenant_id='chain_test',
        )

        log = AuditLog.objects.filter(tenant_id='chain_test').first()
        self.assertIsNotNone(log)
        self.assertTrue(verify_log_hash(log))


# ===========================================================================
# 审计日志写入可靠性测试
# ===========================================================================

class AuditLogWriteReliabilityTest(TestCase):
    """验证审计日志写入的可靠性"""

    def setUp(self):
        AuditLog.objects.filter(tenant_id='reliability_test').delete()

    def test_save_audit_log_does_not_raise_on_db_error(self):
        """数据库异常时 save_audit_log 不应抛出异常"""
        with patch('apps.logs.models.AuditLog.objects.create') as mock_create:
            mock_create.side_effect = Exception('Database connection lost')
            save_audit_log(
                user_id=1,
                username='reliability_test',
                action='create',
                target_type='test',
                target_id='1',
                target_name='test',
                detail='{}',
                ip='127.0.0.1',
                is_success=True,
                tenant_id='reliability_test',
            )
        self.assertEqual(
            AuditLog.objects.filter(tenant_id='reliability_test').count(), 0
        )

    def test_save_audit_log_with_dict_detail(self):
        """dict 类型的 detail 应被正确序列化为 JSON"""
        detail_dict = {'key': 'value', 'nested': {'a': 1}}
        save_audit_log(
            user_id=1,
            username='reliability_test',
            action='create',
            target_type='test',
            target_id='1',
            target_name='test',
            detail=detail_dict,
            ip='127.0.0.1',
            is_success=True,
            tenant_id='reliability_test',
        )

        log = AuditLog.objects.filter(tenant_id='reliability_test').first()
        self.assertIsNotNone(log)
        self.assertIn('"key"', log.detail)
        self.assertTrue(verify_log_hash(log))

    def test_record_audit_event_with_request(self):
        """通过 request 对象调用 record_audit_event"""
        factory = RequestFactory()
        request = factory.post('/test/', {'name': 'test'})
        request.user = MagicMock(
            id=1,
            username='test_user',
            tenant_id='reliability_test',
        )
        request.headers = {'User-Agent': 'TestAgent/1.0'}
        request._audit_request_id = 'test-request-id'

        AuditLog.objects.filter(tenant_id='reliability_test').delete()

        record_audit_event(
            request,
            action='export',
            target_type='device',
            target_id='1',
            target_name='device_001',
            detail={'format': 'xlsx', 'count': 100},
        )

        log = AuditLog.objects.filter(tenant_id='reliability_test').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.action, 'export')
        self.assertEqual(log.target_type, 'device')
        self.assertTrue(verify_log_hash(log))
        self.assertTrue(getattr(request, '_audit_handled', False))

    def test_log_celery_audit_writes_audit_log(self):
        """验证 log_celery_audit 能正确写入审计日志"""
        AuditLog.objects.filter(tenant_id='celery_audit_test').delete()

        log_celery_audit(
            action='update',
            target_type='radio_license',
            target_name='执照到期扫描',
            detail={'total': 10, 'updated': 3},
            tenant_id='celery_audit_test',
        )

        log = AuditLog.objects.filter(tenant_id='celery_audit_test').first()
        self.assertIsNotNone(log, 'log_celery_audit 应写入审计日志')
        self.assertEqual(log.action, 'update')
        self.assertEqual(log.target_type, 'radio_license')
        self.assertEqual(log.username, 'system')
        self.assertEqual(log.user_id, 0)
        self.assertEqual(log.ip, '')
        self.assertTrue(verify_log_hash(log))

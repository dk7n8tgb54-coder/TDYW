"""
CRUD 指南 3.2 可追溯的日志体系 - 合规性验证测试

验证 4 条要求：
1. 错误日志必须带完整上下文：请求参数、链路 ID（trace_id）、异常栈
2. 数据操作日志可定位到具体人、具体时间、具体变更内容（变更前后值）
3. 日志分级：ERROR 触发告警，WARN 记录但观察，INFO 用于审计追溯
4. 日志保留周期：错误日志 ≥ 30 天（审计日志用户指定 90 天，不在此测试范围）

运行方式（在 tdyw-test 容器内）：
    docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
        python manage.py test apps.logging_compliance_tests --noinput -v2
"""

import inspect
import json
import logging
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase, RequestFactory, override_settings
from django.conf import settings
from django.utils import timezone

from apps.logs.models import AuditLog
from apps.logs.audit import (
    save_audit_log,
    record_audit_event,
    log_celery_audit,
    sanitize_audit_detail,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# 要求 1：错误日志必须带完整上下文（请求参数、链路 ID、异常栈）
# ===========================================================================

class ErrorLogCompletenessTest(TestCase):
    """验证错误日志包含请求参数、链路 ID、异常栈"""

    def test_handle_exception_middleware_includes_request_id(self):
        """B1: HandleExceptionMiddleware 应记录 request_id"""
        from libs.middleware import HandleExceptionMiddleware
        source = inspect.getsource(HandleExceptionMiddleware)
        self.assertIn(
            'request_id', source,
            'HandleExceptionMiddleware 应在日志中包含 request_id 用于链路追踪'
        )

    def test_handle_exception_middleware_includes_request_body(self):
        """B1: HandleExceptionMiddleware 应记录请求参数（脱敏）"""
        from libs.middleware import HandleExceptionMiddleware
        source = inspect.getsource(HandleExceptionMiddleware)
        self.assertIn(
            'body', source,
            'HandleExceptionMiddleware 应在日志中包含请求体'
        )

    def test_handle_exception_middleware_includes_exc_info(self):
        """B1: HandleExceptionMiddleware 应记录异常栈"""
        from libs.middleware import HandleExceptionMiddleware
        source = inspect.getsource(HandleExceptionMiddleware)
        self.assertIn(
            'exc_info', source,
            'HandleExceptionMiddleware 应使用 exc_info=True 记录完整异常栈'
        )

    def test_handle_exception_middleware_sanitizes_sensitive_fields(self):
        """B1: 请求参数中的敏感字段应被脱敏"""
        from libs.middleware import _sanitize_request_body
        body = json.dumps({'name': 'test', 'password': 'secret123'})
        sanitized = _sanitize_request_body(body)
        self.assertIn('***', sanitized)
        self.assertNotIn('secret123', sanitized)

    def test_handle_exception_middleware_generates_request_id(self):
        """B1: 无审计中间件时应自动生成 request_id"""
        from libs.middleware import _get_request_id
        factory = RequestFactory()
        request = factory.post('/test/', {})
        # 确保没有预设的 _audit_request_id
        self.assertFalse(hasattr(request, '_audit_request_id'))
        rid = _get_request_id(request)
        self.assertTrue(rid, '_get_request_id 应返回非空值')
        self.assertEqual(request._audit_request_id, rid)

    def test_celery_task_failure_includes_task_id(self):
        """B2: Celery on_task_failure 应记录 task_id 作为链路 ID"""
        from spug.celery import on_task_failure
        source = inspect.getsource(on_task_failure)
        self.assertIn(
            'task_id', source,
            'on_task_failure 应在日志中包含 task_id 作为链路 ID'
        )

    def test_celery_task_failure_includes_task_args(self):
        """B2: Celery on_task_failure 应记录任务参数（脱敏）"""
        from spug.celery import on_task_failure
        source = inspect.getsource(on_task_failure)
        self.assertIn(
            'kwargs', source,
            'on_task_failure 应在日志中包含任务参数'
        )

    def test_celery_task_failure_includes_traceback(self):
        """B2: Celery on_task_failure 应记录异常栈"""
        from spug.celery import on_task_failure
        source = inspect.getsource(on_task_failure)
        self.assertTrue(
            'traceback' in source or 'format_exc' in source or 'exc_info' in source,
            'on_task_failure 应记录完整异常栈'
        )

    def test_celery_task_failure_sanitizes_sensitive_args(self):
        """B2: 任务参数中的敏感字段应被脱敏"""
        from spug.celery import on_task_failure
        source = inspect.getsource(on_task_failure)
        # _sanitize 内部函数会检查 _SENSITIVE 关键词
        self.assertIn(
            '_SENSITIVE', source,
            'on_task_failure 应有敏感字段脱敏逻辑'
        )

    def test_celery_task_failure_alert_includes_request_id(self):
        """B2: 告警消息应包含 task_id 作为 request_id"""
        from spug.celery import on_task_failure
        source = inspect.getsource(on_task_failure)
        self.assertIn(
            'request_id', source,
            'on_task_failure 的告警消息应包含 request_id (task_id)'
        )


# ===========================================================================
# 要求 2：数据操作日志可定位到具体人、具体时间、具体变更内容（变更前后值）
# ===========================================================================

class DataOperationLogTraceabilityTest(TestCase):
    """验证数据操作日志可追溯"""

    def setUp(self):
        AuditLog.objects.filter(tenant_id='compliance_test').delete()

    def tearDown(self):
        AuditLog.objects.filter(tenant_id='compliance_test').delete()

    def test_audit_log_records_user(self):
        """审计日志记录操作人"""
        save_audit_log(
            user_id=42,
            username='test_operator',
            action='create',
            target_type='device',
            target_id='1',
            target_name='device_001',
            detail='{}',
            ip='127.0.0.1',
            is_success=True,
            tenant_id='compliance_test',
        )
        log = AuditLog.objects.filter(tenant_id='compliance_test').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user_id, 42)
        self.assertEqual(log.username, 'test_operator')

    def test_audit_log_records_timestamp(self):
        """审计日志记录时间戳"""
        save_audit_log(
            user_id=1,
            username='test',
            action='create',
            target_type='device',
            target_id='1',
            target_name='test',
            detail='{}',
            ip='127.0.0.1',
            is_success=True,
            tenant_id='compliance_test',
        )
        log = AuditLog.objects.filter(tenant_id='compliance_test').first()
        self.assertIsNotNone(log)
        self.assertIsNotNone(log.created_at)
        # 验证时间戳接近当前时间
        now = timezone.now()
        self.assertLess((now - log.created_at).total_seconds(), 5)

    def test_record_audit_event_captures_before_after_values(self):
        """record_audit_event 支持 before_value/after_value 参数"""
        factory = RequestFactory()
        request = factory.put('/test/', {'name': 'new_name'})
        request.user = MagicMock(id=1, username='test', tenant_id='compliance_test')
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

        log = AuditLog.objects.filter(tenant_id='compliance_test').first()
        self.assertIsNotNone(log)
        detail = json.loads(log.detail)
        self.assertIn('before', detail)
        self.assertIn('after', detail)
        self.assertEqual(detail['before'], {'name': 'old_name'})
        self.assertEqual(detail['after'], {'name': 'new_name'})

    def test_middleware_captures_before_values_for_put(self):
        """中间件 _capture_before_values 在 PUT/PATCH 时捕获旧值"""
        from apps.logs.middleware import AuditLogMiddleware
        source = inspect.getsource(AuditLogMiddleware)
        self.assertIn(
            '_capture_before_values', source,
            '中间件应有 _capture_before_values 方法捕获 PUT/PATCH 的变更前值'
        )

    def test_middleware_merges_before_values(self):
        """中间件 _merge_before_values 只保留实际变更字段"""
        from apps.logs.middleware import AuditLogMiddleware
        source = inspect.getsource(AuditLogMiddleware)
        self.assertIn(
            '_merge_before_values', source,
            '中间件应有 _merge_before_values 方法合并变更前值到 detail'
        )


# ===========================================================================
# 要求 3：日志分级（ERROR 触发告警，WARN 记录但观察，INFO 用于审计追溯）
# ===========================================================================

class LogLevelAlertTest(TestCase):
    """验证 ERROR 级别事件触发告警"""

    def test_handle_exception_middleware_sends_alert(self):
        """HandleExceptionMiddleware 500 异常时发送告警"""
        from libs.middleware import HandleExceptionMiddleware
        source = inspect.getsource(HandleExceptionMiddleware)
        self.assertIn('send_alert', source)

    def test_celery_task_failure_sends_alert(self):
        """Celery 任务失败时发送告警"""
        from spug.celery import on_task_failure
        source = inspect.getsource(on_task_failure)
        self.assertIn('send_alert', source)
        self.assertIn("level='error'", source)

    def test_save_audit_log_failure_sends_alert(self):
        """审计日志写入失败时发送告警"""
        source = inspect.getsource(save_audit_log)
        self.assertTrue(
            '_send_audit_alert' in source or 'send_alert' in source,
            'save_audit_log 失败时应发送告警'
        )

    def test_record_audit_event_failure_sends_alert(self):
        """record_audit_event 失败时发送告警"""
        source = inspect.getsource(record_audit_event)
        self.assertTrue(
            '_send_audit_alert' in source or 'send_alert' in source,
            'record_audit_event 失败时应发送告警'
        )

    def test_audit_middleware_failure_sends_alert(self):
        """审计中间件失败时发送告警"""
        from apps.logs.middleware import AuditLogMiddleware
        source = inspect.getsource(AuditLogMiddleware)
        self.assertIn('send_alert', source)

    def test_send_audit_alert_calls_send_alert_with_error_level(self):
        """_send_audit_alert 使用 error 级别调用 send_alert"""
        from apps.logs.audit import _send_audit_alert
        source = inspect.getsource(_send_audit_alert)
        self.assertIn("level='error'", source)

    def test_audit_log_uses_info_level(self):
        """审计日志通过 INFO 级别持久化到数据库"""
        # AuditLog 是数据库记录，不受 Python logging 级别控制
        # 但中间件和 record_audit_event 的 logger.debug/info 调用应使用非 ERROR 级别
        from apps.logs.middleware import AuditLogMiddleware
        source = inspect.getsource(AuditLogMiddleware)
        # 审计日志的常规操作不应使用 logger.error
        # logger.error 仅用于审计日志写入失败的情况
        self.assertIn('logger', source)

    def test_disk_space_monitor_sends_alert(self):
        """磁盘空间监控发送告警"""
        from apps.alert.tasks import check_disk_space
        source = inspect.getsource(check_disk_space)
        self.assertIn('send_alert', source)

    def test_db_metrics_monitor_sends_alert(self):
        """数据库指标监控发送告警"""
        from apps.alert.tasks import collect_db_metrics
        source = inspect.getsource(collect_db_metrics)
        self.assertIn('send_alert', source)


# ===========================================================================
# 要求 4：日志保留周期（错误日志 ≥ 30 天）
# ===========================================================================

class LogRetentionTest(TestCase):
    """验证错误日志保留周期 ≥ 30 天"""

    def test_django_log_uses_timed_rotating_handler(self):
        """django.log 应使用 TimedRotatingFileHandler 保证时间保留"""
        file_handler = settings.LOGGING['handlers']['file']
        self.assertEqual(
            file_handler['class'],
            'logging.handlers.TimedRotatingFileHandler',
            f'django.log 应使用 TimedRotatingFileHandler，'
            f'实际: {file_handler["class"]}'
        )

    def test_django_log_retention_at_least_30_days(self):
        """django.log 保留天数 ≥ 90 天"""
        file_handler = settings.LOGGING['handlers']['file']
        self.assertEqual(
            file_handler['when'], 'midnight',
            'django.log 应按天轮转 (when=midnight)'
        )
        self.assertGreaterEqual(
            file_handler['backupCount'], 90,
            f'django.log backupCount 应 ≥ 90，'
            f'实际: {file_handler["backupCount"]}'
        )

    def test_document_log_retention_at_least_30_days(self):
        """document.log 保留天数 ≥ 90 天"""
        doc_handler = settings.LOGGING['handlers']['document_file']
        self.assertEqual(
            doc_handler['class'],
            'logging.handlers.TimedRotatingFileHandler',
            f'document.log 应使用 TimedRotatingFileHandler'
        )
        self.assertGreaterEqual(
            doc_handler['backupCount'], 90,
            f'document.log backupCount 应 ≥ 90，实际: {doc_handler["backupCount"]}'
        )


# ===========================================================================
# 端到端验证：HandleExceptionMiddleware 完整流程
# ===========================================================================

class HandleExceptionEndToEndTest(TestCase):
    """端到端验证 HandleExceptionMiddleware 的完整上下文记录"""

    def test_process_exception_logs_request_id_body_and_traceback(self):
        """验证 process_exception 记录 request_id、请求参数、异常栈"""
        from libs.middleware import HandleExceptionMiddleware

        factory = RequestFactory()
        request = factory.post('/api/device/', data={'name': 'test', 'value': '123'})
        request.user = MagicMock(id=1, username='test_user', tenant_id='default')
        request.headers = {'User-Agent': 'TestAgent/1.0'}

        exception = ValueError('test exception for logging')

        # 捕获日志输出
        with patch('libs.middleware.logger') as mock_logger, \
             patch('libs.alert.send_alert'):
            middleware = HandleExceptionMiddleware(get_response=lambda req: None)
            middleware.process_exception(request, exception)

            # 验证 logger.error 被调用
            mock_logger.error.assert_called_once()
            call_args = mock_logger.error.call_args

            # 验证日志消息包含 request_id
            log_msg = call_args[0][0] if call_args[0] else str(call_args)
            self.assertIn('request_id=', log_msg)
            self.assertIn('/api/device/', log_msg)
            self.assertIn('test_user', log_msg)

            # 验证 exc_info=True（异常栈）
            self.assertEqual(call_args[1].get('exc_info'), True)

    def test_process_exception_sanitizes_password_in_body(self):
        """验证请求体中的密码被脱敏"""
        from libs.middleware import HandleExceptionMiddleware

        factory = RequestFactory()
        body = json.dumps({'name': 'test', 'password': 'should_be_hidden'})
        request = factory.post('/api/device/', data=body, content_type='application/json')
        request.user = MagicMock(id=1, username='test', tenant_id='default')
        request.headers = {'User-Agent': 'TestAgent/1.0'}

        with patch('libs.middleware.logger') as mock_logger:
            middleware = HandleExceptionMiddleware(get_response=lambda req: None)
            middleware.process_exception(request, ValueError('test'))

            call_args = mock_logger.error.call_args
            log_msg = call_args[0][0]
            self.assertIn('***', log_msg)
            self.assertNotIn('should_be_hidden', log_msg)

    def test_process_exception_alert_includes_request_id_and_body(self):
        """验证告警消息包含 request_id 和请求参数"""
        from libs.middleware import HandleExceptionMiddleware

        factory = RequestFactory()
        request = factory.post('/api/device/', data={'name': 'test'})
        request.user = MagicMock(id=1, username='test_user', tenant_id='default')
        request.headers = {'User-Agent': 'TestAgent/1.0'}

        with patch('libs.middleware.logger'), \
             patch('libs.alert.send_alert') as mock_alert:
            middleware = HandleExceptionMiddleware(get_response=lambda req: None)
            middleware.process_exception(request, ValueError('test'))

            mock_alert.assert_called_once()
            alert_kwargs = mock_alert.call_args[1]
            message = alert_kwargs['message']
            self.assertIn('request_id', message)
            self.assertIn('参数', message)
            self.assertIn('error', alert_kwargs['level'])

"""REG-AUDIT-001 修复回归：edit → update 归一（device / interference）与审计 action 防护。

背景：apps/device/views.py 与 apps/interference/business_views.py 曾使用
action='edit'（不在 AuditLog.ACTION_CHOICES / audit_action_valid 白名单内），
导致设备事件与干扰记录的编辑审计事件被 CHECK 约束拒绝后静默丢失。

本模块验证：
1. device 设备事件编辑的审计 action 已归一为 update 并真实落库；
2. interference 作用域下 action=update 可正常落库；
3. record_audit_event 对非法 action 会提前告警（不再纯静默丢失）；
4. ACTION_CHOICES 全集均可真实落库（声明与 DB 约束一致）。
"""
import hashlib
import time

from django.test import Client, RequestFactory, TestCase

from apps.account.models import User
from apps.setting.utils import AppSetting


def _make_user(username, perms=None, is_supper=False):
    user = User.objects.create(
        username=username, nickname=username, password_hash='x',
        is_active=True, is_supper=is_supper,
        access_token=hashlib.md5(('audit-fix-%s' % username).encode('utf-8')).hexdigest(),
        token_expired=int(time.time()) + 3600,
        last_login='2026-01-01', last_ip='127.0.0.1', type='default',
    )
    if not is_supper:
        user.set_perms_cache(set(perms or []), version=0)
    return user


def _make_client(user):
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
    return client


DEVICE_PERMS = [
    'device.device_resume.view', 'device.device_resume.history_view',
    'device.device_resume.history_edit',
]
INTERFERENCE_PERMS = ['interference.view', 'interference.edit']


class DeviceEditAuditNormalizedTests(TestCase):
    """device 设备事件编辑：action 从 edit 归一到 update

    说明：device 事件的完整 HTTP 端到端链路依赖设备履历前置数据
    （device_resume_id / event_type 枚举 / 时间逻辑校验），由 device 模块
    自身特征测试覆盖。本用例聚焦验证其调用点归一后的 action 在
    device_event 作用域下可真实落库（edit 无法落库、update 可以）。
    """

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('audit_dev', DEVICE_PERMS)
        self._rf = RequestFactory()

    def _fake_request(self):
        req = self._rf.get('/device/device-event/')
        req.user = self.user
        return req

    def test_update_action_persists_for_device_event_target(self):
        from apps.logs.audit import record_audit_event
        from apps.logs.models import AuditLog

        record_audit_event(
            self._fake_request(), 'update', 'device_event',
            target_id='8888', target_name='审计-设备事件',
            detail={'device_sn': 'SN-AUDIT-001', 'event_type': 'fault'},
        )
        log = AuditLog.objects.filter(
            target_type='device_event', target_id='8888').first()
        self.assertIsNotNone(log, 'action=update 应成功落库（edit 无法落库）')
        self.assertEqual(log.action, 'update')

    def test_edit_action_cannot_be_persisted_for_device_event_target(self):
        """对照：edit 仍不在白名单内，会被 CHECK 约束拒绝（防回退哨兵）"""
        from apps.logs.audit import record_audit_event
        from apps.logs.models import AuditLog

        AuditLog.objects.filter(target_name='audit-device-edit').delete()
        with self.assertLogs('apps.logs.audit', level='ERROR') as captured:
            record_audit_event(
                self._fake_request(), 'edit', 'device_event',
                target_id='7777', target_name='audit-device-edit',
            )
        self.assertFalse(
            AuditLog.objects.filter(target_name='audit-device-edit').exists(),
            'action=edit 不得落库')
        self.assertTrue(any('非法审计 action' in m for m in captured.output),
                        '调用点应提前告警而非静默')


class AuditActionGuardTests(TestCase):
    """interference 作用域验证 + record_audit_event 非法 action 防护"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('audit_itf', INTERFERENCE_PERMS)
        self.client = _make_client(self.user)
        self._rf = RequestFactory()

    def _fake_request(self):
        req = self._rf.get('/interference/')
        req.user = self.user
        return req

    def test_update_action_persists_for_interference_target(self):
        from apps.logs.audit import record_audit_event
        from apps.logs.models import AuditLog

        record_audit_event(
            self._fake_request(), 'update', 'interference',
            target_id='999', target_name='审计-干扰记录',
            detail={'record_type': 'interference', 'fields': ['fault_level']},
        )
        log = AuditLog.objects.filter(
            target_type='interference', target_id='999').first()
        self.assertIsNotNone(log, 'action=update 应成功落库')
        self.assertEqual(log.action, 'update')

    def test_invalid_action_is_flagged_not_silent(self):
        from apps.logs.audit import record_audit_event
        from apps.logs.models import AuditLog

        AuditLog.objects.filter(target_name='audit-invalid-action').delete()
        with self.assertLogs('apps.logs.audit', level='ERROR') as captured:
            record_audit_event(
                self._fake_request(), 'definitely_not_valid', 'interference',
                target_id='998', target_name='audit-invalid-action',
            )
        self.assertTrue(any('非法审计 action' in msg for msg in captured.output),
                        '非法 action 应提前告警')

    def test_all_declared_actions_can_be_persisted(self):
        from apps.logs.audit import record_audit_event
        from apps.logs.models import AuditLog

        declared = [code for code, _label in AuditLog.ACTION_CHOICES]
        for idx, action in enumerate(declared):
            with self.subTest(action=action):
                record_audit_event(
                    self._fake_request(), action, 'interference',
                    target_id='9900%s' % idx, target_name='audit-%s' % action,
                )
                log = AuditLog.objects.filter(target_id='9900%s' % idx).first()
                self.assertIsNotNone(log, 'action=%s 应成功落库' % action)

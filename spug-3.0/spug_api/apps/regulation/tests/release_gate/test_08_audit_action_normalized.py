"""REG-AUDIT-001 修复回归：edit → update 归一与审计 action 防护。

背景：apps/device/views.py（已随设备管理模块于 2026-09 整体移除）与
apps/interference/business_views.py 曾使用 action='edit'（不在
AuditLog.ACTION_CHOICES / audit_action_valid 白名单内），导致编辑审计
事件被 CHECK 约束拒绝后静默丢失。

本模块以 interference 作用域验证（与作用域无关，约束仅作用于 action）：
1. action=update 可正常落库；
2. record_audit_event 对非法 action 会提前告警（不再纯静默丢失），
   edit 作为非法 action 的对照哨兵保留；
3. ACTION_CHOICES 全集均可真实落库（声明与 DB 约束一致）。
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


INTERFERENCE_PERMS = ['interference.view', 'interference.edit']


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

    def test_edit_action_cannot_be_persisted(self):
        """对照：edit 仍不在白名单内，会被 CHECK 约束拒绝（防回退哨兵）"""
        from apps.logs.audit import record_audit_event
        from apps.logs.models import AuditLog

        AuditLog.objects.filter(target_name='audit-edit-guard').delete()
        with self.assertLogs('apps.logs.audit', level='ERROR') as captured:
            record_audit_event(
                self._fake_request(), 'edit', 'interference',
                target_id='997', target_name='audit-edit-guard',
            )
        self.assertFalse(
            AuditLog.objects.filter(target_name='audit-edit-guard').exists(),
            'action=edit 不得落库')
        self.assertTrue(any('非法审计 action' in m for m in captured.output),
                        '调用点应提前告警而非静默')

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

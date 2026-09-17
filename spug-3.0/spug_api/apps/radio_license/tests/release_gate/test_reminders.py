# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""上线门禁 D 组：提醒、徽标和确认（仅执照；批复提醒已于 2026-09 移除）。

覆盖：执照 popup 只返回本人负责的 expiring/expired、normal 不提醒、
badge 与 popup 口径一致、确认后本周期不重复提醒、同周期确认幂等、
续期后旧 ack 失效重新提醒、更换责任人后的提醒归属、
非责任人确认/normal 确认/跨租户确认必须失败、批复提醒端点已下线。
"""
import json
from datetime import date, timedelta

from django.test import TestCase

from apps.radio_license.models import (
    RadioLicense, LicenseReminderAck,
)
from apps.radio_license.tests.release_gate import (
    _make_user, _grant_perms, _make_client,
    TENANT_A, TENANT_B, FULL_LICENSE_PERMS, FULL_APPROVAL_PERMS,
    rg_make_license, rg_make_approval,
)


class LicenseReminderPopupBadgeTests(TestCase):
    """执照 popup 与 badge 口径。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.owner = _make_user('rg_rem_owner', tenant_id=TENANT_A)
        _grant_perms(self.owner, FULL_LICENSE_PERMS)
        self.client = _make_client(self.owner)
        self.today = date.today()

    def test_popup_returns_only_own_expiring_expired(self):
        rg_make_license(self.owner, station_name='RG-REM-到期',
                        valid_to=self.today + timedelta(days=10))
        rg_make_license(self.owner, station_name='RG-REM-过期',
                        valid_to=self.today - timedelta(days=3))
        # normal 记录不提醒
        rg_make_license(self.owner, station_name='RG-REM-正常',
                        valid_to=self.today + timedelta(days=300))
        # 他人负责的记录不提醒
        other = _make_user('rg_rem_other_owner', tenant_id=TENANT_A)
        rg_make_license(other, station_name='RG-REM-他人负责',
                        responsible_user_id=other.id,
                        responsible_user_name=other.nickname,
                        valid_to=self.today + timedelta(days=10))
        body = self.client.get('/radio-license/reminders/popup/').json()
        names = [r['station_name'] for r in body['data']['records']]
        self.assertIn('RG-REM-到期', names)
        self.assertIn('RG-REM-过期', names)
        self.assertNotIn('RG-REM-正常', names)
        self.assertNotIn('RG-REM-他人负责', names)
        for rec in body['data']['records']:
            self.assertIn(rec['remind_type'], ('expiring_daily', 'expired'))

    def test_badge_count_matches_popup(self):
        rg_make_license(self.owner, station_name='RG-BDG-到期',
                        valid_to=self.today + timedelta(days=10))
        rg_make_license(self.owner, station_name='RG-BDG-过期',
                        valid_to=self.today - timedelta(days=3))
        popup = self.client.get('/radio-license/reminders/popup/').json()
        badge = self.client.get('/radio-license/badge/').json()['data']
        self.assertEqual(badge['count'], len(popup['data']['records']))
        self.assertEqual(badge['count'], 2)
        self.assertEqual(badge['expiring_count'], 1)
        self.assertEqual(badge['expired_count'], 1)

    def test_ack_excludes_from_popup_and_badge_in_current_cycle(self):
        lic = rg_make_license(self.owner, station_name='RG-ACK-周期',
                              valid_to=self.today + timedelta(days=10))
        self.assertEqual(self.client.get('/radio-license/badge/').json()['data']['count'], 1)
        resp = self.client.post(
            '/radio-license/reminders/ack/',
            data=json.dumps({'license_id': lic.id}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        popup = self.client.get('/radio-license/reminders/popup/').json()
        self.assertEqual(len(popup['data']['records']), 0)
        badge = self.client.get('/radio-license/badge/').json()['data']
        self.assertEqual(badge['count'], 0)

    def test_ack_idempotent_same_cycle(self):
        lic = rg_make_license(self.owner, station_name='RG-ACK-幂等',
                              valid_to=self.today + timedelta(days=10))
        for _ in range(3):
            resp = self.client.post(
                '/radio-license/reminders/ack/',
                data=json.dumps({'license_id': lic.id}),
                content_type='application/json')
            self.assertFalse(resp.json().get('error'))
        self.assertEqual(
            LicenseReminderAck.objects.filter(license=lic).count(), 1)

    def test_ack_invalidated_after_valid_to_renewal(self):
        """valid_to 续期后旧 ack 失效并重新提醒。"""
        lic = rg_make_license(self.owner, station_name='RG-ACK-续期',
                              valid_to=self.today + timedelta(days=10))
        self.client.post(
            '/radio-license/reminders/ack/',
            data=json.dumps({'license_id': lic.id}),
            content_type='application/json')
        # 续期到新的到期日（仍在 expiring 窗口）
        lic.valid_to = self.today + timedelta(days=30)
        lic.save()
        popup = self.client.get('/radio-license/reminders/popup/').json()
        names = [r['station_name'] for r in popup['data']['records']]
        self.assertIn('RG-ACK-续期', names)
        self.assertEqual(self.client.get('/radio-license/badge/').json()['data']['count'], 1)

    def test_responsible_change_shifts_reminder(self):
        """更换责任人后新责任人收到提醒，原责任人不再收到。"""
        new_owner = _make_user('rg_rem_new_owner', tenant_id=TENANT_A)
        _grant_perms(new_owner, FULL_LICENSE_PERMS)
        lic = rg_make_license(self.owner, station_name='RG-REM-换人',
                              valid_to=self.today + timedelta(days=10))
        # 原责任人先确认
        self.client.post(
            '/radio-license/reminders/ack/',
            data=json.dumps({'license_id': lic.id}),
            content_type='application/json')
        # 更换责任人
        lic.responsible_user_id = new_owner.id
        lic.responsible_user_name = new_owner.nickname
        lic.save()
        new_popup = _make_client(new_owner).get(
            '/radio-license/reminders/popup/').json()
        self.assertEqual(len(new_popup['data']['records']), 1)
        old_popup = self.client.get('/radio-license/reminders/popup/').json()
        self.assertEqual(len(old_popup['data']['records']), 0)


class LicenseAckAuthorizationTests(TestCase):
    """执照 ack 授权：非责任人 / normal 记录 / 跨租户确认必须失败。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.owner = _make_user('rg_ack_owner', tenant_id=TENANT_A)
        _grant_perms(self.owner, FULL_LICENSE_PERMS)
        self.today = date.today()

    def _ack(self, client, license_id):
        return client.post(
            '/radio-license/reminders/ack/',
            data=json.dumps({'license_id': license_id}),
            content_type='application/json').json()

    def test_non_responsible_user_cannot_ack(self):
        """同租户非责任人确认他人执照提醒应失败（与批复侧规则一致）。"""
        lic = rg_make_license(self.owner, station_name='RG-ACKAUTH-他人',
                              valid_to=self.today + timedelta(days=10))
        viewer = _make_user('rg_ack_viewer', tenant_id=TENANT_A)
        _grant_perms(viewer, FULL_LICENSE_PERMS)
        body = self._ack(_make_client(viewer), lic.id)
        self.assertTrue(body.get('error'),
                        '非责任人确认执照提醒应被拒绝，实际返回: %s' % body)
        self.assertEqual(
            LicenseReminderAck.objects.filter(license=lic).count(), 0)

    def test_ack_normal_license_rejected(self):
        """normal 状态执照确认应失败（无提醒可确认）。"""
        lic = rg_make_license(self.owner, station_name='RG-ACKAUTH-正常',
                              valid_to=self.today + timedelta(days=300))
        body = self._ack(_make_client(self.owner), lic.id)
        self.assertTrue(body.get('error'),
                        'normal 执照确认应被拒绝，实际返回: %s' % body)
        self.assertEqual(
            LicenseReminderAck.objects.filter(license=lic).count(), 0)

    def test_cross_tenant_ack_rejected(self):
        lic = rg_make_license(self.owner, station_name='RG-ACKAUTH-跨租户',
                              valid_to=self.today + timedelta(days=10))
        tenant_b_user = _make_user('rg_ack_tenantb', tenant_id=TENANT_B)
        _grant_perms(tenant_b_user, FULL_LICENSE_PERMS)
        body = self._ack(_make_client(tenant_b_user), lic.id)
        self.assertTrue(body.get('error'))
        self.assertEqual(
            LicenseReminderAck.objects.filter(license=lic).count(), 0)

    def test_ack_nonexistent_license_rejected(self):
        body = self._ack(_make_client(self.owner), 999999)
        self.assertTrue(body.get('error'))


class LicensePopupIsolationTests(TestCase):
    """执照 popup 只返回执照记录（批复提醒已于 2026-09 移除）。"""

    def test_license_popup_returns_only_license_records(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        owner = _make_user('rg_mix_owner', tenant_id=TENANT_A)
        _grant_perms(owner, FULL_LICENSE_PERMS + FULL_APPROVAL_PERMS)
        client = _make_client(owner)
        today = date.today()
        rg_make_license(owner, station_name='RG-MIX-执照',
                        valid_to=today + timedelta(days=10))
        rg_make_approval(owner, doc_no='RG-MIX-批复',
                         valid_to=today + timedelta(days=10))
        lic_popup = client.get('/radio-license/reminders/popup/').json()
        lic_ids = [r.get('license_id') for r in lic_popup['data']['records']]
        self.assertEqual(lic_ids, [RadioLicense.objects.get(
            station_name='RG-MIX-执照').id])
        # 批复提醒端点已下线
        self.assertEqual(
            client.get('/radio-license/approvals/reminders/popup/').status_code, 404)
        self.assertEqual(
            client.get('/radio-license/approvals/badge/').status_code, 404)

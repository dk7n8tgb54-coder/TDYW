# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""台站频率批复菜单红点（badge）全局统计行为测试（2026-09 第二轮恢复）。

业务规则：
- GET /radio-license/approvals/badge/ 为全局只读统计：不按租户/账户/责任人
  过滤，所有拥有 radio_license.approval.view 的账户看到相同数字；
- 按 valid_to 实时统计（expiring: today <= valid_to <= today+60；
  expired: valid_to < today；count = expiring + expired），
  不依赖缓存 status 字段或 Celery 扫描；
- 接口无数据库副作用：不创建 ACK、审计日志或证据事件；
- 无 approval.view 权限的账户由后端拒绝。
"""
from datetime import date, timedelta
import json

from django.test import TestCase

from apps.evidence.models import EvidenceEvent
from apps.logs.models import AuditLog
from apps.radio_license.models import LicenseReminderAck, StationFrequencyApproval
from apps.radio_license.tests.release_gate import (
    _make_user, _grant_perms, _make_client,
    TENANT_A, TENANT_B, FULL_APPROVAL_PERMS, rg_make_approval,
)

BADGE_URL = '/radio-license/approvals/badge/'


class ApprovalBadgeGlobalStatsTests(TestCase):
    """批复 badge 全局统计口径与权限。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.today = date.today()
        # 租户 A：全权限属主
        self.owner_a = _make_user('rg_bd_owner_a', tenant_id=TENANT_A)
        _grant_perms(self.owner_a, FULL_APPROVAL_PERMS)
        self.client_a = _make_client(self.owner_a)
        # 租户 B：仅 view
        self.viewer_b = _make_user('rg_bd_viewer_b', tenant_id=TENANT_B)
        _grant_perms(self.viewer_b, [('radio_license', 'approval', ['view'])])
        self.client_viewer_b = _make_client(self.viewer_b)
        # 无任何权限
        self.no_perm = _make_user('rg_bd_noperm', tenant_id=TENANT_B)
        self.client_no_perm = _make_client(self.no_perm)

    def _badge(self, client):
        body = client.get(BADGE_URL).json()
        # json_response 成功时 error 为空串（falsy），失败时为文案
        self.assertFalse(body.get('error'), body)
        return body['data']

    def test_permitted_users_across_tenants_see_identical_global_stats(self):
        """不同租户且具有 approval.view 的账户获得完全相同的全局统计。"""
        # 租户 A 两条到期记录 + 一条正常记录；租户 B 一条到期记录
        rg_make_approval(self.owner_a, doc_no='RG-BD-A1', tenant_id=TENANT_A,
                         valid_to=self.today + timedelta(days=10))
        rg_make_approval(self.owner_a, doc_no='RG-BD-A2', tenant_id=TENANT_A,
                         valid_to=self.today - timedelta(days=5))
        rg_make_approval(self.owner_a, doc_no='RG-BD-A3', tenant_id=TENANT_A,
                         valid_to=self.today + timedelta(days=200))
        rg_make_approval(self.viewer_b, doc_no='RG-BD-B1', tenant_id=TENANT_B,
                         valid_to=self.today + timedelta(days=60))

        data_a = self._badge(self.client_a)
        data_b = self._badge(self.client_viewer_b)
        self.assertEqual(data_a, {'count': 3, 'expiring_count': 2, 'expired_count': 1})
        self.assertEqual(data_a, data_b)

    def test_no_view_perm_rejected(self):
        """无 approval.view 权限的账户访问 badge 接口被后端拒绝。"""
        body = self.client_no_perm.get(BADGE_URL).json()
        self.assertEqual(body.get('error'), '权限拒绝')

    def test_normal_beyond_threshold_not_counted(self):
        """超过 60 天到期阈值的正常批复不计入任何统计。"""
        rg_make_approval(self.owner_a, doc_no='RG-BD-NORMAL', tenant_id=TENANT_A,
                         valid_to=self.today + timedelta(days=61))
        rg_make_approval(self.owner_a, doc_no='RG-BD-FAR', tenant_id=TENANT_A,
                         valid_to=self.today + timedelta(days=1000))
        data = self._badge(self.client_a)
        self.assertEqual(data, {'count': 0, 'expiring_count': 0, 'expired_count': 0})

    def test_exactly_60_days_counts_as_expiring(self):
        """距到期恰好 60 天（阈值边界）计入 expiring。"""
        rg_make_approval(self.owner_a, doc_no='RG-BD-60', tenant_id=TENANT_A,
                         valid_to=self.today + timedelta(days=60))
        data = self._badge(self.client_a)
        self.assertEqual(data['expiring_count'], 1)
        self.assertEqual(data['expired_count'], 0)
        self.assertEqual(data['count'], 1)

    def test_today_expiry_counts_as_expiring(self):
        """当天到期（valid_to == today）计入 expiring 而非 expired。"""
        rg_make_approval(self.owner_a, doc_no='RG-BD-TODAY', tenant_id=TENANT_A,
                         valid_to=self.today)
        data = self._badge(self.client_a)
        self.assertEqual(data['expiring_count'], 1)
        self.assertEqual(data['expired_count'], 0)

    def test_yesterday_expiry_counts_as_expired(self):
        """昨日到期（valid_to == today - 1）计入 expired。"""
        rg_make_approval(self.owner_a, doc_no='RG-BD-YESTERDAY', tenant_id=TENANT_A,
                         valid_to=self.today - timedelta(days=1))
        data = self._badge(self.client_a)
        self.assertEqual(data['expiring_count'], 0)
        self.assertEqual(data['expired_count'], 1)

    def test_count_equals_expiring_plus_expired(self):
        """count 恒等于 expiring_count + expired_count。"""
        rg_make_approval(self.owner_a, doc_no='RG-BD-C1', tenant_id=TENANT_A,
                         valid_to=self.today + timedelta(days=30))
        rg_make_approval(self.owner_a, doc_no='RG-BD-C2', tenant_id=TENANT_A,
                         valid_to=self.today + timedelta(days=59))
        rg_make_approval(self.owner_a, doc_no='RG-BD-C3', tenant_id=TENANT_A,
                         valid_to=self.today - timedelta(days=90))
        data = self._badge(self.client_a)
        self.assertEqual(data['count'], data['expiring_count'] + data['expired_count'])
        self.assertEqual(data['count'], 3)

    def test_edit_valid_to_reflects_immediately_without_cache(self):
        """修改 valid_to 后接口立即返回新统计，不依赖缓存 status 或 Celery 扫描。"""
        approval = rg_make_approval(self.owner_a, doc_no='RG-BD-EDIT', tenant_id=TENANT_A,
                                    valid_to=self.today + timedelta(days=100))
        self.assertEqual(self._badge(self.client_a)['count'], 0)

        # 通过真实编辑接口把 valid_to 改到 30 天后（仍缓存 status=normal）
        resp = self.client_a.post('/radio-license/approvals/', data=json.dumps({
            'id': approval.id,
            'name': 'RG-BD-EDIT',
            'doc_no': 'RG-BD-EDIT',
            'frequency_text': '100MHz',
            'valid_from': str(self.today - timedelta(days=10)),
            'valid_to': str(self.today + timedelta(days=30)),
        }), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(self._badge(self.client_a)['expiring_count'], 1)

        # 再把 valid_to 改到昨天 → 立即转为 expired
        resp = self.client_a.post('/radio-license/approvals/', data=json.dumps({
            'id': approval.id,
            'valid_to': str(self.today - timedelta(days=1)),
        }), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        data = self._badge(self.client_a)
        self.assertEqual(data['expired_count'], 1)
        self.assertEqual(data['expiring_count'], 0)
        self.assertEqual(data['count'], 1)

    def test_badge_request_creates_no_database_side_effects(self):
        """接口调用不创建 ACK、提醒日志、审计日志或证据事件等任何数据库记录。"""
        rg_make_approval(self.owner_a, doc_no='RG-BD-SIDE', tenant_id=TENANT_A,
                         valid_to=self.today + timedelta(days=7))

        def snapshot():
            return {
                'ack': LicenseReminderAck.objects.count(),
                'audit': AuditLog.objects.count(),
                'evidence_event': EvidenceEvent.objects.count(),
                'approvals': StationFrequencyApproval.objects.count(),
            }

        before = snapshot()
        for _ in range(2):
            self._badge(self.client_a)
            self._badge(self.client_viewer_b)
        self.assertEqual(snapshot(), before)


class ApprovalBadgeGlobalVisibilityRegressionTests(TestCase):
    """批复全局共享既有行为回归：badge 与列表口径一致，软删批复不计入。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.today = date.today()
        self.owner_a = _make_user('rg_bd_reg_a', tenant_id=TENANT_A)
        _grant_perms(self.owner_a, FULL_APPROVAL_PERMS)
        self.client_a = _make_client(self.owner_a)

    def test_physically_deleted_approval_not_counted(self):
        """删除批复（物理删除）后 badge 立即减一。"""
        approval = rg_make_approval(self.owner_a, doc_no='RG-BD-DEL', tenant_id=TENANT_A,
                                    valid_to=self.today + timedelta(days=3))
        body = self.client_a.get(BADGE_URL).json()
        self.assertEqual(body['data']['count'], 1)

        resp = self.client_a.delete(f'/radio-license/approvals/?id={approval.id}')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertFalse(
            StationFrequencyApproval.objects.filter(pk=approval.id).exists())
        body = self.client_a.get(BADGE_URL).json()
        self.assertEqual(body['data']['count'], 0)

    def test_badge_count_matches_expiring_plus_expired_list_filter(self):
        """badge 统计与列表 expiring/expired 实时筛选口径一致。"""
        rg_make_approval(self.owner_a, doc_no='RG-BD-L1', tenant_id=TENANT_A,
                         valid_to=self.today + timedelta(days=15))
        rg_make_approval(self.owner_a, doc_no='RG-BD-L2', tenant_id=TENANT_A,
                         valid_to=self.today - timedelta(days=2))
        body = self.client_a.get(BADGE_URL).json()
        data = body['data']

        expiring_list = self.client_a.get(
            '/radio-license/approvals/?status=expiring').json()['data']
        expired_list = self.client_a.get(
            '/radio-license/approvals/?status=expired').json()['data']
        self.assertEqual(data['expiring_count'], expiring_list['total'])
        self.assertEqual(data['expired_count'], expired_list['total'])

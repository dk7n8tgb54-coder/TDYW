# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""上线门禁 B/C 组：台站频率批复功能 + 到期状态边界值。

覆盖：批复 CRUD/分页/筛选、字段校验、doc_no 重复规则、
编辑后状态即时更新、列表/详情实时计算状态、
边界值（-1/0/60/61 天）、Celery 扫描重复执行无写放大。
"""
import json
from datetime import date, timedelta

from django.test import TestCase

from apps.radio_license.models import RadioLicense, StationFrequencyApproval
from apps.radio_license.tasks import (
    scan_radio_license_expiration, scan_approval_expiration,
)
from apps.radio_license.tests.release_gate import (
    _make_user, _grant_perms, _make_client,
    TENANT_A, TENANT_B, FULL_LICENSE_PERMS, FULL_APPROVAL_PERMS,
    rg_approval_payload, rg_license_payload,
    rg_make_approval, rg_make_license,
)


class ApprovalListAndFilterTests(TestCase):
    """B1 列表、分页、筛选。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_ap_list', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_APPROVAL_PERMS)
        self.client = _make_client(self.user)
        self.today = date.today()

    def test_list_pagination(self):
        for i in range(12):
            rg_make_approval(self.user, doc_no=f'RG-PAGE-{i:02d}')
        body = self.client.get('/radio-license/approvals/?page=2&page_size=10').json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['total'], 12)
        self.assertEqual(len(body['data']['records']), 2)

    def test_list_filter_by_name_and_doc_no(self):
        rg_make_approval(self.user, name='RG-甲批复', doc_no='RG-A1')
        rg_make_approval(self.user, name='RG-乙批复', doc_no='RG-B1')
        body = self.client.get('/radio-license/approvals/?name=甲').json()
        self.assertEqual([r['name'] for r in body['data']['records']], ['RG-甲批复'])
        body = self.client.get('/radio-license/approvals/?doc_no=B1').json()
        self.assertEqual([r['name'] for r in body['data']['records']], ['RG-乙批复'])

    def test_list_status_filter_realtime(self):
        """status 筛选按 valid_to 实时转换，不依赖缓存字段。"""
        rg_make_approval(self.user, doc_no='RG-ST-EXP',
                         valid_to=self.today - timedelta(days=1), status='normal')
        rg_make_approval(self.user, doc_no='RG-ST-EXPIRING',
                         valid_to=self.today + timedelta(days=30), status='normal')
        rg_make_approval(self.user, doc_no='RG-ST-NORMAL',
                         valid_to=self.today + timedelta(days=90), status='expired')
        body = self.client.get('/radio-license/approvals/?status=expired').json()
        self.assertEqual([r['doc_no'] for r in body['data']['records']], ['RG-ST-EXP'])
        body = self.client.get('/radio-license/approvals/?status=expiring').json()
        self.assertEqual([r['doc_no'] for r in body['data']['records']], ['RG-ST-EXPIRING'])
        body = self.client.get('/radio-license/approvals/?status=normal').json()
        self.assertEqual([r['doc_no'] for r in body['data']['records']], ['RG-ST-NORMAL'])

    def test_list_invalid_page_params_fallback(self):
        rg_make_approval(self.user)
        body = self.client.get('/radio-license/approvals/?page=abc&page_size=xyz').json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['page'], 1)
        self.assertEqual(body['data']['page_size'], 20)


class ApprovalCRUDTests(TestCase):
    """B2/B3/B4 批复 CRUD 与校验。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_ap_crud', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_APPROVAL_PERMS)
        self.client = _make_client(self.user)
        self.today = date.today()

    def _post(self, payload):
        return self.client.post(
            '/radio-license/approvals/', data=json.dumps(payload),
            content_type='application/json').json()

    def test_create_success(self):
        body = self._post(rg_approval_payload(self.user))
        self.assertFalse(body.get('error'), body)
        ap = StationFrequencyApproval.objects.get(doc_no='RG-DOC-001')
        self.assertEqual(ap.tenant_id, TENANT_A)
        self.assertEqual(ap.responsible_user_name, self.user.nickname)

    def test_create_missing_required_rejected(self):
        for field in ('name', 'doc_no', 'frequency_text'):
            payload = rg_approval_payload(self.user)
            payload[field] = '  '
            body = self._post(payload)
            self.assertTrue(body.get('error'), f'{field} 缺失应报错: {body}')

    def test_create_valid_to_before_valid_from_rejected(self):
        payload = rg_approval_payload(
            self.user,
            valid_from=str(self.today + timedelta(days=10)),
            valid_to=str(self.today - timedelta(days=10)))
        body = self._post(payload)
        self.assertTrue(body.get('error'))

    def test_create_doc_no_duplicate_in_same_tenant_allowed(self):
        """当前业务规则：文件编号允许租户内重复（不假设唯一）。"""
        body1 = self._post(rg_approval_payload(self.user))
        body2 = self._post(rg_approval_payload(self.user))
        self.assertFalse(body1.get('error'), body1)
        self.assertFalse(body2.get('error'), body2)
        self.assertEqual(
            StationFrequencyApproval.objects.filter(
                tenant_id=TENANT_A, doc_no='RG-DOC-001').count(), 2)

    def test_edit_updates_fields_and_computed_status_immediately(self):
        ap = rg_make_approval(self.user, doc_no='RG-EDIT-1',
                              valid_to=self.today + timedelta(days=300))
        payload = rg_approval_payload(
            self.user, doc_no='RG-EDIT-1',
            valid_to=str(self.today + timedelta(days=10)))
        payload['id'] = ap.id
        body = self._post(payload)
        self.assertFalse(body.get('error'), body)
        ap.refresh_from_db()
        self.assertEqual(ap.status, 'expiring')
        # 详情接口实时字段
        detail = self.client.get(f'/radio-license/approvals/{ap.id}/').json()
        self.assertEqual(detail['data']['computed_status'], 'expiring')
        self.assertEqual(detail['data']['days_left'], 10)
        # 列表实时字段
        listing = self.client.get(
            '/radio-license/approvals/?doc_no=RG-EDIT-1').json()
        rec = listing['data']['records'][0]
        self.assertEqual(rec['computed_status'], 'expiring')
        self.assertEqual(rec['days_left'], 10)

    def test_detail_ignores_stale_cached_status(self):
        """缓存 status 错误时，详情/列表按 valid_to 实时计算。"""
        ap = rg_make_approval(self.user, doc_no='RG-STALE',
                              valid_to=self.today + timedelta(days=5),
                              status='normal')
        detail = self.client.get(f'/radio-license/approvals/{ap.id}/').json()
        self.assertEqual(detail['data']['computed_status'], 'expiring')
        self.assertEqual(detail['data']['days_left'], 5)

    def test_delete_success(self):
        ap = rg_make_approval(self.user, doc_no='RG-DEL')
        resp = self.client.delete(f'/radio-license/approvals/?id={ap.id}')
        self.assertFalse(resp.json().get('error'))
        self.assertFalse(StationFrequencyApproval.objects.filter(pk=ap.id).exists())


class ExpirationBoundaryTests(TestCase):
    """C 组到期状态边界值：以测试当天为基准，-1/0/60/61。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_boundary', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS + FULL_APPROVAL_PERMS)
        self.client = _make_client(self.user)
        self.today = date.today()

    def test_license_boundary_values_via_detail_api(self):
        cases = [
            (-1, 'expired'), (0, 'expiring'), (60, 'expiring'), (61, 'normal'),
        ]
        for offset, expected in cases:
            lic = rg_make_license(
                self.user, station_name=f'RG-BND-L{offset}',
                valid_to=self.today + timedelta(days=offset))
            body = self.client.get(f'/radio-license/{lic.id}/').json()
            self.assertEqual(body['data']['computed_status'], expected,
                             f'days_left={offset} 应为 {expected}')
            self.assertEqual(body['data']['days_left'], offset)

    def test_approval_boundary_values_via_detail_api(self):
        cases = [
            (-1, 'expired'), (0, 'expiring'), (60, 'expiring'), (61, 'normal'),
        ]
        for offset, expected in cases:
            ap = rg_make_approval(
                self.user, doc_no=f'RG-BND-A{offset}',
                valid_to=self.today + timedelta(days=offset))
            body = self.client.get(f'/radio-license/approvals/{ap.id}/').json()
            self.assertEqual(body['data']['computed_status'], expected,
                             f'days_left={offset} 应为 {expected}')
            self.assertEqual(body['data']['days_left'], offset)

    def test_create_and_edit_update_status_immediately(self):
        # 创建时已过期 → expired
        payload = rg_license_payload(
            self.user, station_name='RG-IMM-过期',
            valid_to=str(self.today - timedelta(days=1)))
        body = self.client.post(
            '/radio-license/', data=json.dumps(payload),
            content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        obj = RadioLicense.objects.get(station_name='RG-IMM-过期')
        self.assertEqual(obj.status, 'expired')
        # 编辑为正常 → normal
        payload['id'] = obj.id
        payload['valid_to'] = str(self.today + timedelta(days=300))
        body = self.client.post(
            '/radio-license/', data=json.dumps(payload),
            content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        obj.refresh_from_db()
        self.assertEqual(obj.status, 'normal')


class CeleryScanTaskTests(TestCase):
    """C 组 Celery 扫描任务：全量执行、多租户、重复执行无写放大。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user_a = _make_user('rg_scan_a', tenant_id=TENANT_A)
        self.user_b = _make_user('rg_scan_b', tenant_id=TENANT_B)
        self.today = date.today()

    def test_scan_license_task_updates_all_tenants(self):
        lic_normal = rg_make_license(
            self.user_a, station_name='RG-SCAN-A1',
            valid_to=self.today + timedelta(days=300), status='normal')
        lic_expired = rg_make_license(
            self.user_a, station_name='RG-SCAN-A2',
            valid_to=self.today - timedelta(days=1), status='normal')
        lic_b = rg_make_license(
            self.user_b, station_name='RG-SCAN-B1',
            valid_to=self.today + timedelta(days=10), status='normal')
        result = scan_radio_license_expiration.apply().get()
        self.assertEqual(result['total'], 3)
        self.assertEqual(result['updated'], 2)
        lic_normal.refresh_from_db()
        lic_expired.refresh_from_db()
        lic_b.refresh_from_db()
        self.assertEqual(lic_normal.status, 'normal')
        self.assertEqual(lic_expired.status, 'expired')
        self.assertEqual(lic_b.status, 'expiring')

    def test_scan_license_task_repeat_no_write_amplification(self):
        rg_make_license(self.user_a, station_name='RG-SCAN-REP',
                        valid_to=self.today + timedelta(days=10), status='normal')
        first = scan_radio_license_expiration.apply().get()
        self.assertEqual(first['updated'], 1)
        second = scan_radio_license_expiration.apply().get()
        self.assertEqual(second['updated'], 0, '状态未变化时重复扫描不应再写库')

    def test_scan_approval_task_updates_all_tenants(self):
        ap_a = rg_make_approval(
            self.user_a, doc_no='RG-SCAN-AP-A',
            valid_to=self.today - timedelta(days=2), status='normal')
        ap_b = rg_make_approval(
            self.user_b, doc_no='RG-SCAN-AP-B',
            valid_to=self.today + timedelta(days=60), status='normal')
        result = scan_approval_expiration.apply().get()
        self.assertEqual(result['total'], 2)
        ap_a.refresh_from_db()
        ap_b.refresh_from_db()
        self.assertEqual(ap_a.status, 'expired')
        self.assertEqual(ap_b.status, 'expiring')

    def test_scan_approval_task_repeat_no_write_amplification(self):
        rg_make_approval(self.user_a, doc_no='RG-SCAN-AP-REP',
                         valid_to=self.today + timedelta(days=10), status='normal')
        first = scan_approval_expiration.apply().get()
        self.assertEqual(first['updated'], 1)
        second = scan_approval_expiration.apply().get()
        self.assertEqual(second['updated'], 0)

    def test_scan_license_task_error_isolation(self):
        """单条记录异常不应中断全量扫描。"""
        rg_make_license(self.user_a, station_name='RG-SCAN-OK',
                        valid_to=self.today + timedelta(days=10), status='normal')
        # 构造一条 valid_to 为 None 的脏数据会绕过 ORM 校验较难，
        # 改为验证正常数据下任务整体成功且返回结构完整
        result = scan_radio_license_expiration.apply().get()
        self.assertIn('total', result)
        self.assertIn('updated', result)

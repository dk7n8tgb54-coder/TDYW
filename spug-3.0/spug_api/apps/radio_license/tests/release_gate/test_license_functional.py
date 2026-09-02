# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""上线门禁 A 组：无线电台执照功能测试。

覆盖：列表查询/分页/排序/筛选、新增/详情/编辑/删除、必填与日期顺序校验、
频率明细校验（数值>0、sort_order 非负、非法输入不破坏旧数据）、
重复提交幂等、分页参数健壮性。
"""
import json
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from apps.radio_license.models import RadioLicense, RadioLicenseFrequency
from apps.radio_license.tests.release_gate import (
    _make_user, _grant_perms, _make_client,
    TENANT_A, FULL_LICENSE_PERMS, rg_license_payload, rg_make_license,
)


class LicenseListTests(TestCase):
    """A1 列表查询、分页、排序、筛选。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_list_admin', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS)
        self.client = _make_client(self.user)
        self.today = date.today()

    def _seed(self, n=5):
        for i in range(n):
            rg_make_license(
                self.user, station_name=f'RG-LIST-{i:02d}',
                valid_to=self.today + timedelta(days=100 + i),
            )

    def test_list_pagination_and_total(self):
        self._seed(25)
        resp = self.client.get('/radio-license/?page=2&page_size=10')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['total'], 25)
        self.assertEqual(len(body['data']['records']), 10)
        self.assertEqual(body['data']['page'], 2)
        # 最后一页数量正确
        resp = self.client.get('/radio-license/?page=3&page_size=10')
        self.assertEqual(len(resp.json()['data']['records']), 5)

    def test_list_default_ordering_newest_first(self):
        self._seed(3)
        resp = self.client.get('/radio-license/')
        records = resp.json()['data']['records']
        names = [r['station_name'] for r in records]
        # Meta.ordering = (-created_at, -id)，后创建的在前
        self.assertEqual(names, sorted(names, key=lambda n: -int(n.split('-')[-1])))

    def test_list_filter_by_station_and_purpose(self):
        rg_make_license(self.user, station_name='RG-FILT-机场台', purpose='RG-航空通信')
        rg_make_license(self.user, station_name='RG-FILT-港口台', purpose='RG-海事通信')
        body = self.client.get('/radio-license/?station_name=机场').json()
        names = [r['station_name'] for r in body['data']['records']]
        self.assertEqual(names, ['RG-FILT-机场台'])
        body = self.client.get('/radio-license/?purpose=海事').json()
        names = [r['station_name'] for r in body['data']['records']]
        self.assertEqual(names, ['RG-FILT-港口台'])

    def test_list_filter_by_valid_to_range(self):
        rg_make_license(self.user, station_name='RG-RNG-近', valid_to=self.today + timedelta(days=10))
        rg_make_license(self.user, station_name='RG-RNG-远', valid_to=self.today + timedelta(days=500))
        body = self.client.get(
            '/radio-license/?valid_to_start=%s&valid_to_end=%s'
            % (self.today + timedelta(days=1), self.today + timedelta(days=30))
        ).json()
        names = [r['station_name'] for r in body['data']['records']]
        self.assertEqual(names, ['RG-RNG-近'])

    def test_list_filter_by_status_realtime(self):
        """status 筛选应与 valid_to 实时口径一致（不盲信缓存字段）。

        构造一条缓存 status='normal' 但实际已过期的记录（模拟
        定时扫描未执行窗口内的数据），按 expired 筛选应能命中。
        """
        rg_make_license(self.user, station_name='RG-STALE-过期',
                        valid_to=self.today - timedelta(days=5), status='normal')
        rg_make_license(self.user, station_name='RG-STALE-正常',
                        valid_to=self.today + timedelta(days=300), status='normal')
        body = self.client.get('/radio-license/?status=expired').json()
        names = [r['station_name'] for r in body['data']['records']]
        self.assertEqual(names, ['RG-STALE-过期'])

    def test_list_computed_status_matches_days_left(self):
        rg_make_license(self.user, station_name='RG-CMP-过期',
                        valid_to=self.today - timedelta(days=1))
        rg_make_license(self.user, station_name='RG-CMP-到期',
                        valid_to=self.today + timedelta(days=60))
        rg_make_license(self.user, station_name='RG-CMP-正常',
                        valid_to=self.today + timedelta(days=61))
        body = self.client.get('/radio-license/').json()
        status_map = {r['station_name']: r['computed_status'] for r in body['data']['records']}
        self.assertEqual(status_map['RG-CMP-过期'], 'expired')
        self.assertEqual(status_map['RG-CMP-到期'], 'expiring')
        self.assertEqual(status_map['RG-CMP-正常'], 'normal')

    def test_list_invalid_page_param_returns_business_error_not_crash(self):
        """page 非数字时不应触发未处理异常（与批复侧行为对齐）。"""
        self._seed(3)
        resp = self.client.get('/radio-license/?page=abc')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['page'], 1)


class LicenseCRUDTests(TestCase):
    """A2/A3/A5 新增、详情、编辑、删除与字段校验。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_crud_admin', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS)
        self.client = _make_client(self.user)
        self.today = date.today()

    def _post(self, payload):
        return self.client.post(
            '/radio-license/', data=json.dumps(payload),
            content_type='application/json').json()

    def test_create_success_with_frequencies(self):
        body = self._post(rg_license_payload(self.user))
        self.assertFalse(body.get('error'), body)
        lic = RadioLicense.objects.get(station_name='RG-门禁台站')
        self.assertEqual(lic.tenant_id, TENANT_A)
        self.assertEqual(lic.created_by_id, self.user.id)
        freqs = list(RadioLicenseFrequency.objects.filter(license=lic).order_by('sort_order'))
        self.assertEqual(len(freqs), 2)
        self.assertEqual(freqs[0].frequency_value, Decimal('100.5'))
        self.assertEqual(freqs[1].frequency_text, '备用')

    def test_create_missing_required_fields_rejected(self):
        for field in ('station_name', 'purpose', 'valid_from', 'valid_to', 'responsible_user_id'):
            payload = rg_license_payload(self.user)
            payload[field] = ''
            body = self._post(payload)
            self.assertTrue(body.get('error'), f'{field} 为空应报错: {body}')
            self.assertFalse(RadioLicense.objects.filter(station_name='RG-门禁台站').exists())

    def test_create_valid_to_before_valid_from_rejected(self):
        payload = rg_license_payload(
            self.user,
            valid_from=str(self.today + timedelta(days=10)),
            valid_to=str(self.today - timedelta(days=10)))
        body = self._post(payload)
        self.assertTrue(body.get('error'))
        self.assertEqual(RadioLicense.objects.count(), 0)

    def test_create_invalid_date_format_rejected(self):
        payload = rg_license_payload(self.user, valid_to='2026/01/01')
        body = self._post(payload)
        # 非法日期应被拒绝或清洗，不能落库成错误数据
        self.assertTrue(body.get('error') or RadioLicense.objects.count() == 0, body)

    def test_detail_returns_frequencies_and_computed_fields(self):
        lic = rg_make_license(self.user, station_name='RG-DETAIL台站',
                              valid_to=self.today + timedelta(days=30))
        resp = self.client.get(f'/radio-license/{lic.id}/')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['computed_status'], 'expiring')
        self.assertEqual(body['data']['days_left'], 30)
        self.assertIn('frequencies', body['data'])
        self.assertIn('attachment_count', body['data'])

    def test_detail_not_found(self):
        resp = self.client.get('/radio-license/999999/')
        self.assertTrue(resp.json().get('error'))

    def test_edit_updates_fields_and_frequencies_rebuilt(self):
        body = self._post(rg_license_payload(self.user))
        self.assertFalse(body.get('error'), body)
        lic = RadioLicense.objects.get(station_name='RG-门禁台站')
        payload = rg_license_payload(
            self.user, station_name='RG-门禁台站-改',
            frequencies=[
                {'frequency_value': 88.0, 'frequency_unit': 'MHz', 'frequency_text': 'fm'},
            ])
        payload['id'] = lic.id
        body = self._post(payload)
        self.assertFalse(body.get('error'), body)
        lic.refresh_from_db()
        self.assertEqual(lic.station_name, 'RG-门禁台站-改')
        freqs = RadioLicenseFrequency.objects.filter(license=lic)
        self.assertEqual(freqs.count(), 1)
        self.assertEqual(freqs.first().frequency_value, Decimal('88.0'))

    def test_delete_removes_license_and_cascades(self):
        lic = rg_make_license(self.user, station_name='RG-DEL台站')
        resp = self.client.delete(f'/radio-license/?id={lic.id}')
        self.assertFalse(resp.json().get('error'))
        self.assertFalse(RadioLicense.objects.filter(pk=lic.id).exists())

    def test_delete_nonexistent_returns_error(self):
        resp = self.client.delete('/radio-license/?id=999999')
        self.assertTrue(resp.json().get('error'))


class LicenseFrequencyValidationTests(TestCase):
    """A5 频率明细校验。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_freq_admin', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS)
        self.client = _make_client(self.user)
        self.today = date.today()
        # 先创建一条合法执照并带两条频率
        body = self.client.post(
            '/radio-license/', data=json.dumps(rg_license_payload(self.user)),
            content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        self.lic = RadioLicense.objects.get(station_name='RG-门禁台站')
        self.assertEqual(RadioLicenseFrequency.objects.filter(license=self.lic).count(), 2)

    def _edit(self, frequencies):
        payload = rg_license_payload(self.user, frequencies=frequencies)
        payload['id'] = self.lic.id
        return self.client.post(
            '/radio-license/', data=json.dumps(payload),
            content_type='application/json').json()

    def test_edit_invalid_frequency_value_rejected_and_old_data_kept(self):
        body = self._edit([
            {'frequency_value': -1, 'frequency_unit': 'MHz', 'sort_order': 0}])
        self.assertTrue(body.get('error'), body)
        self.assertEqual(RadioLicenseFrequency.objects.filter(license=self.lic).count(), 2)

    def test_edit_zero_frequency_value_rejected(self):
        body = self._edit([
            {'frequency_value': 0, 'frequency_unit': 'MHz', 'sort_order': 0}])
        self.assertTrue(body.get('error'), body)
        self.assertEqual(RadioLicenseFrequency.objects.filter(license=self.lic).count(), 2)

    def test_edit_non_numeric_frequency_rejected(self):
        body = self._edit([
            {'frequency_value': 'abc', 'frequency_unit': 'MHz', 'sort_order': 0}])
        self.assertTrue(body.get('error'), body)
        self.assertEqual(RadioLicenseFrequency.objects.filter(license=self.lic).count(), 2)

    def test_edit_negative_sort_order_rejected(self):
        body = self._edit([
            {'frequency_value': 1.0, 'frequency_unit': 'MHz', 'sort_order': -1}])
        self.assertTrue(body.get('error'), body)
        self.assertEqual(RadioLicenseFrequency.objects.filter(license=self.lic).count(), 2)

    def test_edit_bool_sort_order_rejected(self):
        body = self._edit([
            {'frequency_value': 1.0, 'frequency_unit': 'MHz', 'sort_order': True}])
        self.assertTrue(body.get('error'), body)
        self.assertEqual(RadioLicenseFrequency.objects.filter(license=self.lic).count(), 2)

    def test_create_invalid_frequency_rejected(self):
        payload = rg_license_payload(
            self.user, station_name='RG-FREQ-非法',
            frequencies=[{'frequency_value': 'x', 'frequency_unit': 'MHz'}])
        body = self.client.post(
            '/radio-license/', data=json.dumps(payload),
            content_type='application/json').json()
        self.assertTrue(body.get('error'), body)
        self.assertFalse(RadioLicense.objects.filter(station_name='RG-FREQ-非法').exists())


class LicenseDuplicateSubmitTests(TestCase):
    """A6 重复点击提交：后端幂等拦截。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_dup_admin', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS)
        self.client = _make_client(self.user)

    def test_sequential_duplicate_create_rejected(self):
        payload = rg_license_payload(self.user)
        body1 = self.client.post(
            '/radio-license/', data=json.dumps(payload),
            content_type='application/json').json()
        self.assertFalse(body1.get('error'), body1)
        body2 = self.client.post(
            '/radio-license/', data=json.dumps(payload),
            content_type='application/json').json()
        self.assertEqual(body2.get('error'), '提交过于频繁，请勿重复提交')
        self.assertEqual(
            RadioLicense.objects.filter(station_name='RG-门禁台站').count(), 1)

    def test_duplicate_edit_is_idempotent(self):
        lic = rg_make_license(self.user)
        payload = rg_license_payload(self.user)
        payload['id'] = lic.id
        for _ in range(2):
            body = self.client.post(
                '/radio-license/', data=json.dumps(payload),
                content_type='application/json').json()
            self.assertFalse(body.get('error'), body)
        self.assertEqual(RadioLicense.objects.filter(pk=lic.id).count(), 1)

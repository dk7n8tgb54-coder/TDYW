# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""部门值班日志模块异常测试

覆盖创建/编辑/签署/日期列表/列表筛选各入口的参数校验与业务错误分支：
- 值班日期（缺失/空白/非字符串/非法格式/未来日期）
- 天气（缺失/空白/非字符串/超长，边界 50 字）
- 值班记录（缺失/空白/超长，边界 10000 字）、备注（非字符串/超长，边界 2000 字）
- 编辑版本号（缺失/非整数/小于 1）
- 签署请求（缺版本号/未确认/伪造受保护字段/非法 JSON）
- 日期列表参数（缺参/非整数/month 越界/year 越界）
- 列表筛选（非法日期/结束早于开始/非法状态/关键字与姓名超长/未来日期边界）
- 校验失败一律不产生数据库写入
"""
import json
from datetime import date, timedelta

from django.test import TestCase

from apps.setting.utils import AppSetting
from apps.department_duty_log.models import DepartmentDutyLog

from apps.department_duty_log.tests.test_comprehensive import (
    _make_user, _make_client, _grant_perms, _make_record,
)


class CreatePayloadValidationTests(TestCase):
    """创建草稿：日期 / 天气 / 值班记录 / 备注 / 受保护字段校验"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_val_creator', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log',
             ['view', 'add', 'edit', 'del', 'sign']),
        ])
        self.client = _make_client(self.user)

    def _post(self, payload):
        return self.client.post(
            '/department-duty-log/records/', data=json.dumps(payload),
            content_type='application/json')

    def _payload(self, duty_record='异常测试默认记录'):
        return {
            'duty_date': str(date.today()),
            'weather': '晴',
            'duty_record': duty_record,
            'remark': '',
        }

    def test_date_missing_blank_and_non_string_rejected(self):
        """值班日期缺失/空白/非字符串均被拒绝且不落库"""
        for mutate in (
                lambda p: p.pop('duty_date'),
                lambda p: p.update(duty_date=''),
                lambda p: p.update(duty_date=20260830),
                lambda p: p.update(duty_date={'year': 2026}),
                lambda p: p.update(duty_date=['2026-08-30']),
        ):
            payload = self._payload()
            mutate(payload)
            body = self._post(payload).json()
            self.assertIn('值班日期', body.get('error', ''), payload)
        self.assertEqual(DepartmentDutyLog.objects.count(), 0)

    def test_date_bad_format_rejected(self):
        """值班日期非 YYYY-MM-DD 格式被拒绝"""
        for bad in ('2026/08/30', '2026年08月30日', '2026-08', 'not-a-date', '2026-08-30T10:00'):
            payload = self._payload()
            payload['duty_date'] = bad
            body = self._post(payload).json()
            self.assertIn('值班日期', body.get('error', ''), bad)
        self.assertEqual(DepartmentDutyLog.objects.count(), 0)

    def test_date_future_rejected_today_accepted(self):
        """未来日期被拒绝，当天为合法边界"""
        payload = self._payload()
        payload['duty_date'] = str(date.today() + timedelta(days=1))
        self.assertIn('不能晚于当前日期', self._post(payload).json().get('error', ''))
        body = self._post(self._payload()).json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(DepartmentDutyLog.objects.count(), 1)

    def test_date_input_trimmed(self):
        """值班日期两端空白被容忍"""
        payload = self._payload()
        payload['duty_date'] = f'  {date.today().isoformat()}  '
        body = self._post(payload).json()
        self.assertFalse(body.get('error'), body)

    def test_weather_missing_blank_non_string_rejected(self):
        """天气缺失/空白/非字符串均被拒绝且不落库"""
        for mutate in (
                lambda p: p.pop('weather'),
                lambda p: p.update(weather='   '),
                lambda p: p.update(weather=123),
                lambda p: p.update(weather=None),
        ):
            payload = self._payload()
            mutate(payload)
            body = self._post(payload).json()
            self.assertIn('天气情况', body.get('error', ''), payload)
        self.assertEqual(DepartmentDutyLog.objects.count(), 0)

    def test_weather_length_boundary(self):
        """天气 50 字为合法边界，51 字被拒绝"""
        payload = self._payload()
        payload['weather'] = '晴' * 50
        body = self._post(payload).json()
        self.assertFalse(body.get('error'), body)
        payload = self._payload(duty_record='异常测试天气超长')
        payload['weather'] = '晴' * 51
        body = self._post(payload).json()
        self.assertIn('超过最大长度 50', body.get('error', ''))

    def test_duty_record_missing_blank_rejected(self):
        """值班记录缺失/空白被拒绝"""
        for mutate in (
                lambda p: p.pop('duty_record'),
                lambda p: p.update(duty_record=''),
                lambda p: p.update(duty_record='  \n  '),
        ):
            payload = self._payload()
            mutate(payload)
            body = self._post(payload).json()
            self.assertIn('值班记录', body.get('error', ''), payload)
        self.assertEqual(DepartmentDutyLog.objects.count(), 0)

    def test_duty_record_length_boundary(self):
        """值班记录 10000 字为合法边界，10001 字被拒绝"""
        payload = self._payload(duty_record='记' * 10000)
        body = self._post(payload).json()
        self.assertFalse(body.get('error'), body)
        payload = self._payload(duty_record='记' * 10001)
        body = self._post(payload).json()
        self.assertIn('超过最大长度 10000', body.get('error', ''))

    def test_remark_non_string_and_overlong_rejected(self):
        """备注非字符串与超长（2001 字）被拒绝，2000 字为合法边界"""
        for mutate in (
                lambda p: p.update(remark={'x': 1}),
                lambda p: p.update(remark=['备注']),
        ):
            payload = self._payload()
            mutate(payload)
            body = self._post(payload).json()
            self.assertIn('备注', body.get('error', ''), payload)
        payload = self._payload()
        payload['remark'] = '注' * 2001
        body = self._post(payload).json()
        self.assertIn('超过最大长度 2000', body.get('error', ''))
        payload = self._payload(duty_record='异常测试备注边界')
        payload['remark'] = '注' * 2000
        body = self._post(payload).json()
        self.assertFalse(body.get('error'), body)

    def test_protected_fields_rejected_on_create(self):
        """创建请求携带受保护字段一律被拒绝且不落库"""
        cases = [
            ('duty_person_id', 99999),
            ('duty_person', 99999),
            ('signed_by_id', 999),
            ('signed_by_name', '伪造'),
            ('status', 'signed'),
            ('id', 999),
            ('tenant_id', 'tenant_b'),
            ('created_at', '2020-01-01 00:00:00'),
            ('deleted_at', '2020-01-01 00:00:00'),
            ('signature_usage_id', 123),
            ('signature_sha256', 'a' * 64),
            ('business_snapshot_hash', 'b' * 64),
        ]
        for field, value in cases:
            payload = self._payload()
            payload[field] = value
            body = self._post(payload).json()
            self.assertIn('不允许提交的字段', body.get('error', ''), field)
        self.assertEqual(DepartmentDutyLog.objects.count(), 0)

    def test_input_strings_trimmed(self):
        """天气/值班记录/备注两端空白被去除后保存"""
        payload = self._payload(duty_record='  带空白的值班记录  ')
        payload['weather'] = '  多云  '
        payload['remark'] = '  无异常  '
        body = self._post(payload).json()
        self.assertFalse(body.get('error'), body)
        record = DepartmentDutyLog.objects.get(pk=body['data']['id'])
        self.assertEqual(record.weather, '多云')
        self.assertEqual(record.duty_record, '带空白的值班记录')
        self.assertEqual(record.remark, '无异常')


class EditPayloadValidationTests(TestCase):
    """编辑草稿：版本号 / 受保护字段 / 非法字段值"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_val_editor', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log',
             ['view', 'add', 'edit', 'del', 'sign']),
        ])
        self.client = _make_client(self.user)
        self.record = _make_record(self.user)

    def _put(self, payload, record_id=None):
        return self.client.put(
            f'/department-duty-log/records/{record_id or self.record.id}/',
            data=json.dumps(payload), content_type='application/json')

    def _payload(self, duty_record='编辑后的记录'):
        return {
            'duty_date': str(date.today()),
            'weather': '晴',
            'duty_record': duty_record,
            'remark': '',
            'version': 1,
        }

    def test_version_missing_rejected(self):
        payload = self._payload()
        del payload['version']
        body = self._put(payload).json()
        self.assertIn('缺少版本号', body.get('error', ''))

    def test_version_non_integer_rejected(self):
        for bad in ('abc', '1.5', {'v': 1}, [1]):
            payload = self._payload()
            payload['version'] = bad
            body = self._put(payload).json()
            self.assertIn('版本号', body.get('error', ''), bad)

    def test_version_below_one_rejected(self):
        for bad in (0, -1, -100):
            payload = self._payload()
            payload['version'] = bad
            body = self._put(payload).json()
            self.assertIn('版本号不正确', body.get('error', ''), bad)

    def test_edit_with_protected_field_rejected(self):
        """编辑请求携带 status / signed_at 等受保护字段被拒绝且记录不变"""
        for field, value in (
                ('status', 'signed'),
                ('signed_at', '2020-01-01 00:00:00'),
                ('signature_usage_id', 123),
                ('duty_person_id', 99999),
        ):
            payload = self._payload()
            payload[field] = value
            body = self._put(payload).json()
            self.assertIn('不允许提交的字段', body.get('error', ''), field)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'draft')
        self.assertIsNone(self.record.signature_usage_id)
        self.assertEqual(self.record.duty_record, '值班正常')

    def test_edit_invalid_date_rejected_record_unchanged(self):
        payload = self._payload()
        payload['duty_date'] = 'not-a-date'
        body = self._put(payload).json()
        self.assertTrue(body.get('error'))
        self.record.refresh_from_db()
        self.assertEqual(self.record.duty_record, '值班正常')
        self.assertEqual(self.record.version, 1)

    def test_edit_valid_payload_accepted(self):
        """对照：合法编辑负载成功且版本号 +1"""
        body = self._put(self._payload()).json()
        self.assertFalse(body.get('error'), body)
        self.record.refresh_from_db()
        self.assertEqual(self.record.duty_record, '编辑后的记录')
        self.assertEqual(self.record.version, 2)


class SignPayloadValidationTests(TestCase):
    """签署请求：版本号 / 确认项 / 受保护字段 / 非法请求体"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_val_signer', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log',
             ['view', 'add', 'edit', 'del', 'sign']),
        ])
        self.client = _make_client(self.user)
        self.record = _make_record(self.user)

    def _sign(self, payload, record_id=None, raw=None):
        url = f'/department-duty-log/records/{record_id or self.record.id}/sign/'
        if raw is not None:
            return self.client.post(url, data=raw, content_type='application/json')
        return self.client.post(url, data=json.dumps(payload),
                                content_type='application/json')

    def test_version_missing_rejected(self):
        body = self._sign({'confirm': True, 'request_id': 'v-001'}).json()
        self.assertIn('版本号', body.get('error', ''))

    def test_version_non_integer_rejected(self):
        for bad in ('abc', '1.5'):
            body = self._sign({'version': bad, 'confirm': True}).json()
            self.assertIn('版本号', body.get('error', ''), bad)

    def test_confirm_missing_rejected(self):
        """未确认签署被拒绝且记录保持草稿"""
        body = self._sign({'version': 1, 'request_id': 'c-001'}).json()
        self.assertIn('请确认签署', body.get('error', ''))
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'draft')

    def test_version_mismatch_rejected(self):
        body = self._sign({'version': 99, 'confirm': True, 'request_id': 'm-001'}).json()
        self.assertIn('版本不一致', body.get('error', ''))
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'draft')

    def test_sign_protected_fields_rejected(self):
        """签署请求携带受保护字段被拒绝且记录不变"""
        for field, value in (
                ('signed_by_id', 999),
                ('signature_usage_id', 123),
                ('status', 'signed'),
                ('signed_at', '2020-01-01 00:00:00'),
        ):
            payload = {'version': 1, 'confirm': True, 'request_id': f'f-{field}'}
            payload[field] = value
            body = self._sign(payload).json()
            self.assertIn('不允许提交的字段', body.get('error', ''), field)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'draft')

    def test_sign_malformed_and_empty_body(self):
        """非法 JSON 与空请求体均得到明确错误而非服务器内部错误"""
        body = self._sign(None, raw='{invalid-json').json()
        self.assertIn('请求体格式不正确', body.get('error', ''))
        body = self._sign(None, raw='').json()
        self.assertTrue(body.get('error'))
        self.assertNotEqual(body.get('error'), '服务器内部错误，请联系管理员')
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'draft')


class DutyDatesParamValidationTests(TestCase):
    """已有值班日期接口：参数校验"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_val_dates', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view']),
        ])
        self.client = _make_client(self.user)

    def _get(self, query=''):
        return self.client.get(f'/department-duty-log/records/duty_dates/{query}')

    def test_year_and_month_required(self):
        for query in ('', '?year=2026', '?month=8'):
            body = self._get(query).json()
            self.assertTrue(body.get('error'), query)

    def test_non_integer_year_month_rejected(self):
        for query in ('?year=abc&month=8', '?year=2026&month=abc',
                      '?year=2026.5&month=8'):
            body = self._get(query).json()
            self.assertTrue(body.get('error'), query)
            self.assertNotEqual(body.get('error'), '服务器内部错误，请联系管理员')

    def test_month_out_of_range_rejected(self):
        for month in (0, 13, -1, 99):
            body = self._get(f'?year=2026&month={month}').json()
            self.assertIn('month 必须在 1-12 之间', body.get('error', ''), month)

    def test_year_out_of_range_rejected(self):
        for year in (1899, 10000, -2026):
            body = self._get(f'?year={year}&month=8').json()
            self.assertIn('year 取值范围', body.get('error', ''), year)

    def test_valid_params_accepted(self):
        body = self._get('?year=2026&month=8').json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['dates'], [])
        # 补零字符串月份同样合法
        body = self._get('?year=2026&month=08').json()
        self.assertFalse(body.get('error'), body)


class ListParamValidationTests(TestCase):
    """列表筛选参数校验"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_val_list', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'add']),
        ])
        self.client = _make_client(self.user)
        self.record = _make_record(self.user)

    def test_invalid_filter_dates_rejected(self):
        for query in ('?start_date=bad', '?end_date=2026-13-99',
                      '?start_date=2026-08-30&end_date=2026-08-01'):
            body = self.client.get(
                f'/department-duty-log/records/{query}').json()
            self.assertTrue(body.get('error'), query)

    def test_invalid_status_rejected(self):
        body = self.client.get(
            '/department-duty-log/records/?status=closed').json()
        self.assertIn('状态值不正确', body.get('error', ''))

    def test_overlong_keyword_and_name_rejected(self):
        body = self.client.get(
            f'/department-duty-log/records/?keyword={"关" * 101}').json()
        self.assertIn('关键字过长', body.get('error', ''))
        body = self.client.get(
            f'/department-duty-log/records/?duty_person_name={"名" * 101}').json()
        self.assertIn('值班人员姓名过长', body.get('error', ''))

    def test_future_end_date_accepted_as_filter_bound(self):
        """回归修复：筛选边界不是业务日期，未来结束日期应放行（前端 RangePicker 可选未来日期）"""
        resp = self.client.get(
            f'/department-duty-log/records/?start_date={date.today()}'
            f'&end_date={date.today() + timedelta(days=7)}')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        ids = [r['id'] for r in body['data']['records']]
        self.assertIn(self.record.id, ids)

    def test_future_start_date_accepted_as_filter_bound(self):
        """未来开始日期放行（结果为空属于正常筛选语义）"""
        future = date.today() + timedelta(days=7)
        body = self.client.get(
            f'/department-duty-log/records/?start_date={future.isoformat()}').json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['records'], [])

    def test_valid_filters_accepted(self):
        body = self.client.get(
            f'/department-duty-log/records/?start_date={date.today()}'
            f'&end_date={date.today()}&duty_person_name=val&status=draft').json()
        self.assertFalse(body.get('error'), body)

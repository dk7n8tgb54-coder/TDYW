# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""部门值班日志模块容错测试

覆盖异常输入与异常状态下的健壮性，全部走真实 HTTP 路径并校验数据库副作用：
- 列表查询：越界/非法分页参数、特殊关键字不产生服务器内部错误
- 已有值班日期：year=9999&month=12 上界边界不崩溃、1900-01 下界
- 创建：同参数重复提交幂等拒绝、1900 年以前日期干净拒绝（不落库层报错）
- 记录操作：不存在对象、重复删除、签署幂等重试、已签记录重签、退回状态机
- PDF 导出：非法请求体、非法筛选类型、空结果
"""
import json
from datetime import date, timedelta
from urllib.parse import quote

from django.test import TestCase

from apps.setting.utils import AppSetting
from apps.signature.models import SignatureUsage
from apps.department_duty_log.models import DepartmentDutyLog, STATUS_SIGNED

from apps.department_duty_log.tests.test_comprehensive import (
    _make_user, _make_client, _grant_perms, _make_record,
)
from apps.department_duty_log.tests.test_department_duty_log_regression import (
    SignatureFlowBase,
)


class ListQueryFaultTests(TestCase):
    """列表查询：越界分页与特殊关键字不产生服务器内部错误"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_ft_list', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view']),
        ])
        self.client = _make_client(self.user)
        self.record = _make_record(self.user)

    def _get(self, query):
        return self.client.get(f'/department-duty-log/records/{query}').json()

    def test_non_numeric_page_and_page_size(self):
        body = self._get('?page=abc&page_size=abc')
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['page'], 1)
        self.assertEqual(body['data']['page_size'], 20)
        self.assertEqual(body['data']['total'], 1)

    def test_non_positive_page_and_page_size(self):
        for query in ('?page=0', '?page=-1'):
            body = self._get(query)
            self.assertFalse(body.get('error'), body)
            self.assertEqual(body['data']['page'], 1)
        for query in ('?page_size=0', '?page_size=-5'):
            body = self._get(query)
            self.assertFalse(body.get('error'), body)
            self.assertEqual(body['data']['page_size'], 20)

    def test_oversize_page_size_capped(self):
        body = self._get('?page_size=1000')
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['page_size'], 100)

    def test_huge_page_returns_empty_not_error(self):
        body = self._get('?page=99999999')
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['records'], [])
        self.assertEqual(body['data']['total'], 1)

    def test_special_char_keywords_no_error(self):
        """通配符/反斜杠等特殊关键字不产生服务器内部错误"""
        for keyword in ('%_%', '\\', "值% '--", '【】{}""'):
            body = self._get(f'?keyword={quote(keyword)}')
            self.assertFalse(body.get('error'), (keyword, body))

    def test_combined_filters_no_error(self):
        body = self._get(
            '?start_date=2000-01-01&end_date=2099-12-31'
            '&duty_person_name=不存在&status=signed&keyword=无')
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['records'], [])


class DutyDatesFaultTests(TestCase):
    """已有值班日期：极端入参不产生服务器内部错误"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_ft_dates', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view']),
        ])
        self.client = _make_client(self.user)
        _make_record(self.user, status=STATUS_SIGNED, duty_date=date(2026, 6, 15))

    def _get(self, query):
        return self.client.get(
            f'/department-duty-log/records/duty_dates/{query}').json()

    def test_year_9999_month_12_no_server_error(self):
        """回归修复：9999-12 是合法入参，构造次月上界不得越界崩溃"""
        body = self._get('?year=9999&month=12')
        self.assertNotEqual(
            body.get('error'), '服务器内部错误，请联系管理员', body)
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['dates'], [])

    def test_year_1900_month_1_boundary(self):
        body = self._get('?year=1900&month=1')
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['dates'], [])

    def test_signed_date_in_month_listed(self):
        body = self._get('?year=2026&month=6')
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['dates'], ['2026-06-15'])


class CreateIdempotencyFaultTests(TestCase):
    """创建幂等：30 秒窗口内相同 用户+日期+正文 拒绝重复提交"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_ft_idem', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'add']),
        ])
        self.client = _make_client(self.user)

    def _post(self, duty_record, duty_date=None):
        return self.client.post(
            '/department-duty-log/records/', data=json.dumps({
                'duty_date': str(duty_date or date.today()),
                'weather': '晴',
                'duty_record': duty_record,
                'remark': '',
            }), content_type='application/json').json()

    def test_duplicate_create_rejected(self):
        body = self._post('重复提交容错测试')
        self.assertFalse(body.get('error'), body)
        body = self._post('重复提交容错测试')
        self.assertIn('提交过于频繁', body.get('error', ''), body)
        self.assertEqual(DepartmentDutyLog.objects.count(), 1)

    def test_same_date_different_record_allowed(self):
        body = self._post('内容甲')
        self.assertFalse(body.get('error'), body)
        body = self._post('内容乙')
        self.assertFalse(body.get('error'), body)
        self.assertEqual(DepartmentDutyLog.objects.count(), 2)

    def test_same_record_different_date_allowed(self):
        yesterday = date.today() - timedelta(days=1)
        body = self._post('跨日同文', duty_date=yesterday)
        self.assertFalse(body.get('error'), body)
        body = self._post('跨日同文')
        self.assertFalse(body.get('error'), body)
        self.assertEqual(DepartmentDutyLog.objects.count(), 2)


class EarlyDateFaultTests(TestCase):
    """超早日期：应在业务校验层干净拒绝，不得落到数据库层报错"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_ft_early', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'export']),
        ])
        self.client = _make_client(self.user)

    def test_create_pre_1900_date_rejected_cleanly(self):
        """1900 年以前的值班日期应被业务校验拒绝而非触发服务器内部错误"""
        resp = self.client.post(
            '/department-duty-log/records/', data=json.dumps({
                'duty_date': '0001-01-01',
                'weather': '晴',
                'duty_record': '超早日期容错测试',
                'remark': '',
            }), content_type='application/json')
        body = resp.json()
        self.assertTrue(body.get('error'), body)
        self.assertNotEqual(
            body.get('error'), '服务器内部错误，请联系管理员', body)
        self.assertEqual(DepartmentDutyLog.objects.count(), 0)

    def test_list_filter_pre_1900_start_date_no_server_error(self):
        body = self.client.get(
            '/department-duty-log/records/?start_date=0001-01-01').json()
        self.assertNotEqual(
            body.get('error'), '服务器内部错误，请联系管理员', body)

    def test_export_filter_pre_1900_date_no_server_error(self):
        resp = self.client.post(
            '/department-duty-log/export/pdf/',
            data=json.dumps({'start_date': '0001-01-01', 'end_date': '0001-01-02'}),
            content_type='application/json')
        body = resp.json()
        self.assertNotEqual(
            body.get('error'), '服务器内部错误，请联系管理员', body)


class RecordOperationFaultTests(SignatureFlowBase):
    """记录操作：不存在对象 / 重复删除 / 签署重试 / 退回状态机"""

    def test_operations_on_nonexistent_record(self):
        url = '/department-duty-log/records/999999/'
        resp = self.signer_client.get(url).json()
        self.assertIn('记录不存在', resp.get('error', ''))
        resp = self.signer_client.put(
            url, data=json.dumps({
                'duty_date': str(date.today()), 'weather': '晴',
                'duty_record': 'x', 'remark': '', 'version': 1,
            }), content_type='application/json').json()
        self.assertIn('记录不存在', resp.get('error', ''))
        resp = self.signer_client.delete(url).json()
        self.assertIn('记录不存在', resp.get('error', ''))
        resp = self.signer_client.post(
            f'/department-duty-log/records/999999/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': 'ft-none'}),
            content_type='application/json').json()
        self.assertIn('记录不存在', resp.get('error', ''))
        # 退回需要独立 return 权限，使用退回人账号探测
        returner = _make_user('ddl_ft_none_returner', tenant_id='tenant_a')
        _grant_perms(returner, [
            ('department_duty_log', 'department_duty_log', ['view', 'return']),
        ])
        resp = _make_client(returner).post(
            '/department-duty-log/records/999999/return/',
            data=json.dumps({}), content_type='application/json').json()
        self.assertIn('记录不存在', resp.get('error', ''))

    def test_delete_draft_twice(self):
        record = self._create_draft()
        resp = self.signer_client.delete(
            f'/department-duty-log/records/{record.id}/').json()
        self.assertFalse(resp.get('error'), resp)
        resp = self.signer_client.delete(
            f'/department-duty-log/records/{record.id}/').json()
        self.assertIn('记录不存在', resp.get('error', ''))

    def test_sign_idempotent_retry_same_request_id(self):
        """响应丢失后携同 request_id 重试返回既有结果，不产生第二条签署"""
        record = self._create_draft()
        resp = self._sign(record, 'ft-retry-1', version=1)
        self.assertFalse(resp.json().get('error'), resp.json())
        record.refresh_from_db()
        resp = self._sign(record, 'ft-retry-1', version=record.version)
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(
            SignatureUsage.objects.filter(request_id='ft-retry-1').count(), 1)
        record.refresh_from_db()
        self.assertEqual(record.status, STATUS_SIGNED)

    def test_sign_again_with_different_request_id_rejected(self):
        record = self._create_draft()
        resp = self._sign(record, 'ft-again-1', version=1)
        self.assertFalse(resp.json().get('error'), resp.json())
        record.refresh_from_db()
        resp = self._sign(record, 'ft-again-2', version=record.version)
        self.assertIn('当前记录状态不可签署', resp.json().get('error', ''))
        self.assertEqual(
            SignatureUsage.objects.filter(module='department_duty_log').count(), 1)

    def test_return_draft_rejected(self):
        record = self._create_draft()
        returner = _make_user('ddl_ft_returner', tenant_id='tenant_a')
        _grant_perms(returner, [
            ('department_duty_log', 'department_duty_log', ['view', 'return']),
        ])
        resp = _make_client(returner).post(
            f'/department-duty-log/records/{record.id}/return/',
            data=json.dumps({}), content_type='application/json').json()
        self.assertIn('只能退回已签署记录', resp.get('error', ''))

    def test_return_twice_rejected(self):
        record = self._create_draft()
        self._sign(record, 'ft-return-1', version=1)
        returner = _make_user('ddl_ft_returner2', tenant_id='tenant_a')
        _grant_perms(returner, [
            ('department_duty_log', 'department_duty_log', ['view', 'return']),
        ])
        client = _make_client(returner)
        resp = client.post(
            f'/department-duty-log/records/{record.id}/return/',
            data=json.dumps({}), content_type='application/json').json()
        self.assertFalse(resp.get('error'), resp)
        resp = client.post(
            f'/department-duty-log/records/{record.id}/return/',
            data=json.dumps({}), content_type='application/json').json()
        self.assertIn('只能退回已签署记录', resp.get('error', ''))

    def test_edit_with_huge_version_no_error(self):
        """极端大版本号按版本冲突处理，不产生服务器内部错误"""
        record = self._create_draft()
        resp = self.signer_client.put(
            f'/department-duty-log/records/{record.id}/',
            data=json.dumps({
                'duty_date': str(date.today()), 'weather': '晴',
                'duty_record': 'x', 'remark': '', 'version': 10 ** 18,
            }), content_type='application/json').json()
        self.assertIn('版本冲突', resp.get('error', ''))
        record.refresh_from_db()
        self.assertEqual(record.version, 1)


class PdfExportFilterFaultTests(TestCase):
    """PDF 导出筛选容错（空库即可验证，无需签署环境）"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_ft_export', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log', ['view', 'export']),
        ])
        self.client = _make_client(self.user)

    def _export(self, payload, raw=None):
        if raw is not None:
            return self.client.post(
                '/department-duty-log/export/pdf/', data=raw,
                content_type='application/json')
        return self.client.post(
            '/department-duty-log/export/pdf/', data=json.dumps(payload),
            content_type='application/json')

    def test_malformed_json_body_rejected(self):
        resp = self._export(None, raw='{invalid')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('请求体格式不正确', resp.json().get('error', ''))

    def test_non_dict_body_rejected(self):
        resp = self._export(None, raw='[1, 2, 3]')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp.json().get('error'))

    def test_non_string_filter_type_rejected(self):
        resp = self._export({'start_date': {'a': 1}})
        self.assertEqual(resp.status_code, 400)
        self.assertNotEqual(
            resp.json().get('error'), '服务器内部错误，请联系管理员')

    def test_start_after_end_rejected(self):
        resp = self._export({'start_date': '2026-08-30', 'end_date': '2026-08-01'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('结束日期不能早于开始日期', resp.json().get('error', ''))

    def test_overlong_keyword_rejected(self):
        resp = self._export({'keyword': '关' * 101})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('关键字过长', resp.json().get('error', ''))

    def test_empty_result_rejected(self):
        resp = self._export({'start_date': '2020-01-01', 'end_date': '2020-01-02'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('没有可导出的已签记录', resp.json().get('error', ''))

    def test_future_end_date_filter_reaches_export(self):
        """回归修复：未来结束日期作为普通筛选上界放行，进入空结果检查"""
        resp = self._export({
            'start_date': str(date.today()),
            'end_date': str(date.today() + timedelta(days=7)),
        })
        body = resp.json()
        self.assertNotEqual(
            body.get('error'), '服务器内部错误，请联系管理员', body)
        self.assertIn('没有可导出的已签记录', body.get('error', ''))

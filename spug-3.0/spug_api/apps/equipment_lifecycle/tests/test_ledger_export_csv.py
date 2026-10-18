# -*- coding: utf-8 -*-
"""维护台账明细 CSV 导出（2026-10-15 修复与强化）。

- 回归：LedgerExportView 审计语句引用未定义 ledger_type（NameError）导致
  导出请求必 500 且无审计记录——修复后导出正常返回文件；
- 导出重新执行筛选查询（状态/日期/编号/系统/类型），租户边界独立校验；
- 审计记录真实生效筛选范围与导出行数；空结果返回仅表头的 CSV；
- 中文文件名经 RFC 5987（filename*=UTF-8''…）下发。
"""
from urllib.parse import unquote

from unittest import mock

from django.test import TestCase

from apps.equipment_lifecycle.tests.base import make_client, make_system
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    P_LED_EXPORT,
    entry_payload,
    item_payload,
    ledger_payload,
    make_ledger_user,
    post_json,
    create_ledger_ok,
)

EXPORT_URL = '/equipment-lifecycle/ledgers/export/'

# 与 ledger_views.LedgerExportView 表头一致（首列台账编号）
CSV_HEADER_FIRST_CELL = '台账编号'


def _create_ledger(user, system_code='SYS-001', **kwargs):
    """经 API 创建一张最小台账（两项：正常 + 异常含数值）。

    system_code 须在同租户内唯一（唯一约束 uniq_el_systems_tenant_code）；
    台账编号按租户内当日序号生成，跨租户可能同名，隔离断言以系统编码区分。
    """
    system = make_system(user, tenant_id=user.tenant_id, system_code=system_code)
    client = make_client(user)
    payload = ledger_payload(
        [entry_payload(system.id, [
            item_payload(),
            item_payload(item_name='电源电压测量', input_type='number', value_text='',
                         value_number=52, result='abnormal', abnormal_desc='电压偏低'),
        ])],
        **kwargs)
    return create_ledger_ok(client, payload)


def _csv_rows(body):
    """按行拆分 CSV 文本（含表头行）。"""
    text = body.decode('utf-8-sig')
    return [line for line in text.splitlines()]


class LedgerExportCsvTests(TestCase):
    def setUp(self):
        self.user = make_ledger_user('export_op')

    def test_export_returns_csv_file_with_rows(self):
        """导出返回真实 CSV 文件：BOM、表头、数据行与填写值。"""
        data = _create_ledger(self.user)
        response = make_client(self.user).get(EXPORT_URL, {'ledger_type': 'week_month'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])
        body = response.content
        self.assertTrue(body.startswith(b'\xef\xbb\xbf'), 'CSV 须带 UTF-8 BOM 便于 Excel 识别中文')
        rows = _csv_rows(body)
        self.assertEqual(len(rows), 3, '表头 + 两条明细')
        self.assertTrue(rows[0].startswith(CSV_HEADER_FIRST_CELL))
        content = body.decode('utf-8-sig')
        # 行序按 执行日期倒序+id 倒序，断言明细内容存在而非行位置
        self.assertIn(data['ledger_no'], content)
        self.assertIn('设备指示灯检查', content)
        self.assertIn('正常', content)
        self.assertIn('电压偏低', content)
        self.assertIn(',52.0,', content)

    def test_export_filename_is_chinese_by_ledger_type(self):
        """文件名按台账类型中文命名（RFC 5987 编码下发）。"""
        _create_ledger(self.user)
        response = make_client(self.user).get(EXPORT_URL, {'ledger_type': 'week_month'})
        disposition = response['Content-Disposition']
        self.assertIn("filename*=UTF-8''", disposition)
        filename = unquote(disposition.split("''", 1)[1])
        self.assertEqual(filename, '周月维护台账明细.csv')
        # 未带类型参数时为通用命名
        response = make_client(self.user).get(EXPORT_URL)
        filename = unquote(response['Content-Disposition'].split("''", 1)[1])
        self.assertEqual(filename, '维护台账明细.csv')

    def test_export_applies_status_and_date_filters(self):
        """导出重新执行筛选：状态/日期范围只命中匹配台账的明细。"""
        draft = _create_ledger(self.user, system_code='SYS-DRAFT',
                               executed_date='2026-09-10')
        filled = _create_ledger(self.user, system_code='SYS-FILLED',
                                executed_date='2026-10-01')
        client = make_client(self.user)
        resp = post_json(client, '/equipment-lifecycle/ledgers/%s/complete/' % filled['id'], {})
        self.assertFalse(resp.json().get('error'), resp.json())

        # 状态筛选：仅已完成台账的明细
        response = client.get(EXPORT_URL, {'status': 'completed'})
        rows = _csv_rows(response.content)
        self.assertEqual(len(rows), 3)
        content = response.content.decode('utf-8-sig')
        self.assertIn(filled['ledger_no'], content)
        self.assertIn('SYS-FILLED', content)
        self.assertNotIn('SYS-DRAFT', content)

        # 日期范围筛选：仅 10 月台账（编号内嵌执行日期，两台账编号不同）
        response = client.get(EXPORT_URL, {'executed_from': '2026-10-01'})
        rows = _csv_rows(response.content)
        self.assertEqual(len(rows), 3)
        content = response.content.decode('utf-8-sig')
        self.assertIn('SYS-FILLED', content)
        self.assertNotIn('SYS-DRAFT', content)
        self.assertNotIn(draft['ledger_no'], content)

    def test_export_records_audit_with_rows_and_applied_filters(self):
        """审计记录真实行数与生效筛选；无筛选时 filters 为空 dict。"""
        _create_ledger(self.user)
        with mock.patch('apps.equipment_lifecycle.ledger_views.'
                        'record_audit_event') as audit:
            response = make_client(self.user).get(
                EXPORT_URL, {'ledger_type': 'week_month', 'status': 'draft'})
        self.assertEqual(response.status_code, 200)
        audit.assert_called_once()
        args, kwargs = audit.call_args
        self.assertEqual(args[1], 'export')
        self.assertEqual(kwargs['after_value']['rows'], 2)
        self.assertEqual(kwargs['after_value']['filters'],
                         {'ledger_type': 'week_month', 'status': 'draft'})

        with mock.patch('apps.equipment_lifecycle.ledger_views.'
                        'record_audit_event') as audit:
            make_client(self.user).get(EXPORT_URL)
        _, kwargs = audit.call_args
        self.assertEqual(kwargs['after_value']['rows'], 2)
        # 2026-10-17 起默认视图排除已作废：审计如实记录生效的状态口径
        self.assertEqual(kwargs['after_value']['filters'],
                         {'status': '默认(不含已作废)'})

    def test_export_empty_result_returns_header_only(self):
        """空结果：仅表头 CSV，审计 rows=0，不报错。"""
        with mock.patch('apps.equipment_lifecycle.ledger_views.'
                        'record_audit_event') as audit:
            response = make_client(self.user).get(EXPORT_URL)
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])
        rows = _csv_rows(response.content)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].startswith(CSV_HEADER_FIRST_CELL))
        _, kwargs = audit.call_args
        self.assertEqual(kwargs['after_value']['rows'], 0)

    def test_export_isolated_by_tenant(self):
        """跨租户隔离：他租户台账明细不出现在导出结果中。"""
        _create_ledger(self.user, system_code='SYS-OWN')
        other_user = make_ledger_user('export_other', tenant_id='tenant_other')
        _create_ledger(other_user, system_code='SYS-OTHER')
        response = make_client(other_user).get(EXPORT_URL)
        content = response.content.decode('utf-8-sig')
        # 台账编号按租户内序号生成可能同名，以系统编码区分归属
        self.assertNotIn('SYS-OWN', content)
        self.assertIn('SYS-OTHER', content)
        rows = _csv_rows(response.content)
        self.assertEqual(len(rows), 3, '仅本租户两条明细')
        # 反向：本租户导出不含他租户系统
        response = make_client(self.user).get(EXPORT_URL)
        content = response.content.decode('utf-8-sig')
        self.assertIn('SYS-OWN', content)
        self.assertNotIn('SYS-OTHER', content)

    def test_export_requires_export_permission(self):
        """无导出权限：业务错误拒绝，不返回文件。"""
        from apps.equipment_lifecycle.tests.stable_contract.ledger_base import ALL_LEDGER_PERMS
        perms = [code for code in ALL_LEDGER_PERMS if code != P_LED_EXPORT]
        user = make_ledger_user('no_export', perms=perms)
        response = make_client(user).get(EXPORT_URL)
        self.assertTrue(response.json().get('error'))

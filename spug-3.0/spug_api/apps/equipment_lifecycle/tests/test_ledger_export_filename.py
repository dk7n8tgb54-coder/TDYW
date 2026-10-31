# -*- coding: utf-8 -*-
"""Excel 台账导出下载文件名契约（2026-10-31）。

回归点：导出端点曾把路由格式标识 excel 直接当扩展名拼进
Content-Disposition，下载文件名以 .excel 结尾（内容本身仍是有效 xlsx）。
本契约经真实 HTTP 链路（上传样例 → 绑定 → 发布 → 建台账 → 导出）验证：
1. 导出 Excel 的 Content-Disposition 文件名以 .xlsx 结尾、不以 .excel 结尾；
2. 响应体仍是可被 openpyxl 打开的有效 XLSX，填写值真实写入工作簿。
"""
import io
import json
import re
from urllib.parse import unquote

from openpyxl import load_workbook

from apps.equipment_lifecycle.excel_template_views import XLSX_CONTENT_TYPE
from apps.equipment_lifecycle.tests.stable_contract import (
    test_excel_ledger_templates as excel_contract,
)
from apps.equipment_lifecycle.tests.stable_contract.test_excel_ledger_templates import (
    LEDGER_URL, SHEET_MAIN,
)


def disposition_filename(response):
    """从 Content-Disposition 解析 RFC 5987 filename*（导出统一走该形态）。"""
    disposition = response['Content-Disposition']
    match = re.search(r"filename\*=UTF-8''([^;]+)", disposition)
    assert match, disposition
    return unquote(match.group(1))


class ExcelLedgerExportFilenameTests(excel_contract.ExcelLedgerContractBase):
    """导出下载文件名扩展名契约（复用 Excel 上传版稳定契约夹具）。"""

    def _create_draft_ledger(self):
        """上传 → 绑定 → 发布 → 建台账 → 填必填值（Excel 导出拦截未填必填）。"""
        # 自建绑定：文本类型（status 空 options 拒绝一切非空值，夹具用 text）
        template = self.upload_sample()
        bindings = [
            self.make_binding('C4', '第1信道-主电台-PS模块', input_type='text'),
            self.make_binding('D4', '第1信道-主电台-TX模块', input_type='text'),
            self.make_binding('H4', '第1信道-主电台-备注', input_type='text',
                              is_required=False),
        ]
        response = self.save_bindings(template['id'], bindings)
        self.assertEqual(response.json().get('error', ''), '')
        version = self.publish(template['id'])
        response = self.owner_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id']}),
            content_type='application/json')
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        ledger = payload['data']['data']
        values = {bindings[0]['field_id']: '正常', bindings[1]['field_id']: '阻抗正常'}
        response = self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger['id']), json.dumps({'values': values}),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        return ledger, bindings

    def test_export_excel_download_name_ends_with_xlsx(self):
        """草稿导出：文件名为「源文件名-草稿.xlsx」，绝不以 .excel 结尾。"""
        ledger, _ = self._create_draft_ledger()
        response = self.owner_client.post(
            '%s/%s/export/excel/' % (LEDGER_URL, ledger['id']))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], XLSX_CONTENT_TYPE)
        filename = disposition_filename(response)
        # upload_sample 上传源文件名为 信道维护台账验收样例.xlsx，草稿后缀「草稿」
        self.assertEqual(filename, '信道维护台账验收样例-草稿.xlsx')
        self.assertTrue(filename.endswith('.xlsx'), filename)
        self.assertFalse(filename.endswith('.excel'), filename)
        # 响应体仍是有效 XLSX（zip 容器可被 openpyxl 打开）
        workbook = load_workbook(filename=io.BytesIO(response.content))
        self.assertIn(SHEET_MAIN, workbook.sheetnames)

    def test_export_excel_keeps_valid_content_with_filled_values(self):
        """填写后导出：下载名扩展名正确，填写值真实写入有效 XLSX 内容。"""
        ledger, bindings = self._create_draft_ledger()
        values = {bindings[0]['field_id']: '正常', bindings[1]['field_id']: '阻抗正常'}
        response = self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger['id']), json.dumps({'values': values}),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        response = self.owner_client.post(
            '%s/%s/export/excel/' % (LEDGER_URL, ledger['id']))
        self.assertEqual(response['Content-Type'], XLSX_CONTENT_TYPE)
        filename = disposition_filename(response)
        self.assertTrue(filename.endswith('.xlsx'), filename)
        self.assertFalse(filename.endswith('.excel'), filename)
        workbook = load_workbook(filename=io.BytesIO(response.content))
        self.assertEqual(workbook[SHEET_MAIN]['C4'].value, '正常')
        self.assertEqual(workbook[SHEET_MAIN]['D4'].value, '阻抗正常')

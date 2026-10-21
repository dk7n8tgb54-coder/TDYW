# -*- coding: utf-8 -*-
"""浏览器打印引擎 PDF 稳定契约（2026-10-21，真实 Chromium 渲染路径）。

EXCEL_PDF_ENGINE=chromium：统一打印布局分页计划（与网页 print_plan 同源）
→ 统一打印 HTML → 无头 Chromium 打印。本套件走真实 HTTP 链路
（URL→View→Service→HTML→Chromium→PDF），用 pypdf/poppler 验证产物：

1. 纸张与方向：横向模板第 1 页 mediabox = A4 横向（841.89×595.28pt），
   纵向长模板 = A4 纵向，页数与 print_plan 页数一致（网页=PDF 的根基）；
2. 文本层：模板文字与填写值为可选中/可搜索的真实文本（非整页截图），
   多工作表内容全部呈现；
3. 预览 = 下载：print-preview 与 export/pdf 同参数同数据产出同页数、
   同文本；print-preview 结果按内容寻址缓存（值变化即失效）；
4. 底部留白：pdftotext -bbox 量测最后一行文字不超过「页高 - 下边距」
   （维护人/日期落在正文可打印区域内，页面底部保留完整留白）；
5. 必填未填拦截（与 Excel 导出同口径）与非法引擎显式报错。

环境限制显式 NOT_RUN：无 Chromium（detect_browser 为空）或无 pdftotext
时 skip，绝不伪造通过。
"""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from unittest import mock, skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

from apps.equipment_lifecycle import excel_browser_pdf_service, excel_print_cache
from apps.equipment_lifecycle.excel_pdf_service import PdfConversionError
from apps.equipment_lifecycle.tests.base import URL_PREFIX
from apps.equipment_lifecycle.tests.stable_contract.test_excel_ledger_templates import (
    ExcelLedgerContractBase,
)

LEDGER_URL = URL_PREFIX + '/excel-ledgers'
TPL_URL = URL_PREFIX + '/excel-templates'

CHROMIUM = override_settings(EXCEL_PDF_ENGINE='chromium')


def _has_chromium():
    try:
        return excel_browser_pdf_service.detect_browser() is not None
    except Exception:
        return False


HAS_CHROMIUM = _has_chromium()
HAS_PDFTOTEXT = shutil.which('pdftotext') is not None
# A4 纵向 mediabox（pt）
A4_PORTRAIT_PT = (595.5, 841.9)
A4_LANDSCAPE_PT = (841.9, 595.5)


def _pdf_pages_and_size(content):
    """pypdf 读取页数与第 1 页 mediabox（pt）；pypdf 缺失返回 (None, None)。"""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        box = reader.pages[0].mediabox
        return len(reader.pages), (round(float(box.width), 1),
                                   round(float(box.height), 1))
    except ImportError:
        return None, None


def _pdf_text(content):
    """pdftotext 提取文本层（UTF-8），提取失败返回空串。"""
    if not HAS_PDFTOTEXT:
        return ''
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(content)
        path = f.name
    try:
        result = subprocess.run(['pdftotext', '-enc', 'UTF-8', path, '-'],
                                capture_output=True, timeout=30)
        return result.stdout.decode('utf-8', 'replace')
    finally:
        os.unlink(path)


def _pdf_max_text_bottom_pt(content):
    """pdftotext -bbox 量测全文最大文字底边（pt，页高坐标），供底部留白断言。"""
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(content)
        path = f.name
    try:
        result = subprocess.run(['pdftotext', '-bbox', path, '-'],
                                capture_output=True, timeout=30)
        text = result.stdout.decode('utf-8', 'replace')
    finally:
        os.unlink(path)
    ymax_list = [float(m) for m in re.findall(r'yMax="([\d.]+)"', text)]
    return max(ymax_list) if ymax_list else None


def _page_height_pt(content):
    _pages, _size = _pdf_pages_and_size(content)
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    return round(float(reader.pages[0].mediabox.height), 1)


def _wide_landscape_xlsx():
    """代表模板一：横向 A4、多级合并表头、较宽维护表（12 列）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = '巡检记录'
    ws['A1'] = '设备巡检维护记录表'
    ws.merge_cells('A1:L1')
    ws['A1'].font = Font(size=16, bold=True)
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    # 多级表头：一级合并 + 二级细分
    ws['A2'] = '基本信息'
    ws.merge_cells('A2:D2')
    ws['E2'] = '巡检项目'
    ws.merge_cells('E2:H2')
    ws['I2'] = '处理记录'
    ws.merge_cells('I2:L2')
    for col in range(1, 13):
        cell = ws.cell(row=3, column=col, value='%s项' % get_column_letter(col))
        cell.border = Border(*[Side(style='thin')] * 4)
    for row in range(4, 34):
        ws.cell(row=row, column=1, value='设备-%02d' % row)
        ws.cell(row=row, column=2, value='机房%d' % (row % 3))
    for col in range(1, 13):
        ws.column_dimensions[get_column_letter(col)].width = 14
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = 9
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _long_portrait_xlsx():
    """代表模板二：纵向 A4、行数多、底部大面积维护记录/维护人/日期区域。"""
    wb = Workbook()
    ws = wb.active
    ws.title = '维护台账'
    ws['A1'] = '基站月度维护台账'
    ws.merge_cells('A1:H1')
    ws['A1'].font = Font(size=14, bold=True)
    for col in range(1, 9):
        ws.cell(row=2, column=col, value='%s栏' % get_column_letter(col))
    for row in range(3, 81):
        ws.cell(row=row, column=1, value='检查项-%02d' % row)
        ws.cell(row=row, column=2, value='')
    # 底部大区域：维护记录（3 行高合并）、维护人、日期
    ws['A81'] = '维护记录'
    ws.merge_cells('A81:H83')
    ws['A81'].alignment = Alignment(vertical='top', wrap_text=True)
    ws['A84'] = '维护人'
    ws['C84'] = ''
    ws['A85'] = '维护日期'
    ws['C85'] = ''
    for col in range(1, 9):
        ws.column_dimensions[get_column_letter(col)].width = 10
    ws.row_dimensions[81].height = 28
    ws.row_dimensions[82].height = 28
    ws.row_dimensions[83].height = 28
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


@CHROMIUM
@skipUnless(HAS_CHROMIUM, 'Chromium 不可用，浏览器打印引擎用例 NOT_RUN（需安装 playwright chromium）')
class BrowserPdfExportTests(ExcelLedgerContractBase):
    """真实 Chromium 导出：纸张/方向/页数/文本层（横向宽表代表模板）。"""

    def _publish_wide_template(self):
        response = self.owner_client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('wide.xlsx', _wide_landscape_xlsx()),
            'name': '横向巡检模板',
            'ledger_type': 'week_month',
        })
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        template = payload['data']['data']
        bindings = [
            self.make_binding('C6', '巡检结果', sheet='巡检记录', input_type='status'),
            self.make_binding('D6', '处理说明', sheet='巡检记录',
                              input_type='text', is_required=False),
        ]
        response = self.save_bindings(template['id'], bindings)
        self.assertEqual(response.json().get('error', ''), '')
        version = self.publish(template['id'])
        return template, version, bindings

    def _create_filled_ledger(self, version, bindings, extra=None):
        response = self.owner_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id']}),
            content_type='application/json')
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        ledger_id = payload['data']['data']['id']
        values = {'巡检结果值': '正常'}
        named = {bindings[0]['field_id']: '正常',
                 bindings[1]['field_id']: '更换风扇并清理滤网'}
        named.update(extra or {})
        response = self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger_id),
            json.dumps({'values': named}), content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        return ledger_id, named

    def _create_ledger(self, version_id):
        response = self.owner_client.post(
            LEDGER_URL + '/',
            json.dumps({'version_id': version_id, 'ledger_type': 'week_month'}),
            content_type='application/json')
        return response

    def test_landscape_pdf_paper_size_and_text_layer(self):
        template, version, bindings = self._publish_wide_template()
        ledger_id, values = self._create_filled_ledger(version, bindings)
        response = self.owner_client.post(
            '%s/%s/export/pdf/' % (LEDGER_URL, ledger_id))
        self.assertIn('application/pdf', response['Content-Type'])
        self.assertTrue(response.content.startswith(b'%PDF-'))
        pages, size = _pdf_pages_and_size(response.content)
        self.assertEqual(pages, 1)
        # A4 横向真实尺寸（210×297 交换），方向与模板 print 设置一致
        self.assertAlmostEqual(size[0], A4_LANDSCAPE_PT[0], delta=2.5)
        self.assertAlmostEqual(size[1], A4_LANDSCAPE_PT[1], delta=2.5)
        text = _pdf_text(response.content)
        self.assertIn('设备巡检维护记录表', text)
        self.assertIn('基本信息', text)
        self.assertIn('设备-04', text)
        # 填写值为可选中文本（文本层，非整页截图）
        self.assertIn('更换风扇并清理滤网', text)

    def test_pdf_pages_match_print_plan(self):
        """网页 print_plan 页数与真实 PDF 页数一致（统一分页的根基）。"""
        template, version, bindings = self._publish_wide_template()
        ledger_id, _values = self._create_filled_ledger(version, bindings)
        detail = json.loads(self.owner_client.get(
            '%s/%s/' % (LEDGER_URL, ledger_id)).content)
        plan = detail['data']['data']['excel']['version']['print_plan']
        self.assertTrue(plan)
        response = self.owner_client.post(
            '%s/%s/export/pdf/' % (LEDGER_URL, ledger_id))
        pages, _size = _pdf_pages_and_size(response.content)
        self.assertEqual(pages, plan['page_count'])
        self.assertEqual(pages, plan['sheets']['巡检记录']['page_count'])

    def test_required_missing_blocks_browser_export(self):
        template, version, bindings = self._publish_wide_template()
        response = self._create_ledger(version['id'])
        ledger_id = response.json()['data']['data']['id']
        response = self.owner_client.post(
            '%s/%s/export/pdf/' % (LEDGER_URL, ledger_id))
        self.assertIn('必填字段未填写', response.json()['error'])


@CHROMIUM
@skipUnless(HAS_CHROMIUM, 'Chromium 不可用，浏览器打印引擎用例 NOT_RUN')
class BrowserPdfPreviewTests(ExcelLedgerContractBase):
    """打印预览（翻阅真实预览）：预览 = 下载、缓存失效、底部留白。"""

    def _publish_long_template(self):
        response = self.owner_client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('long.xlsx', _long_portrait_xlsx()),
            'name': '纵向长台账模板',
            'ledger_type': 'week_month',
        })
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        template = payload['data']['data']
        bindings = [
            self.make_binding('B10', '检查结论', sheet='维护台账', input_type='status'),
            self.make_binding('C84', '维护人签名', sheet='维护台账', input_type='text'),
            self.make_binding('C85', '维护日期', sheet='维护台账', input_type='date'),
        ]
        response = self.save_bindings(template['id'], bindings)
        self.assertEqual(response.json().get('error', ''), '')
        version = self.publish(template['id'])
        return template, version, bindings

    def _create_filled(self, version, bindings, values=None):
        response = self.owner_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id']}),
            content_type='application/json')
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        ledger_id = payload['data']['data']['id']
        filled = {bindings[0]['field_id']: '正常',
                  bindings[1]['field_id']: '张三',
                  bindings[2]['field_id']: '2026-10-21'}
        filled.update(values or {})
        response = self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger_id),
            json.dumps({'values': filled}), content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        return ledger_id

    def test_preview_equals_export_and_portrait_pages(self):
        """预览与下载同生成服务：页数一致、文本一致；纵向 A4 多页。"""
        template, version, bindings = self._publish_long_template()
        ledger_id = self._create_filled(version, bindings)
        export = self.owner_client.post(
            '%s/%s/export/pdf/' % (LEDGER_URL, ledger_id))
        preview = self.owner_client.post(
            '%s/%s/print-preview/' % (LEDGER_URL, ledger_id))
        self.assertIn('application/pdf', preview['Content-Type'])
        self.assertIn('inline', preview['Content-Disposition'])
        export_pages, size = _pdf_pages_and_size(export.content)
        preview_pages, preview_size = _pdf_pages_and_size(preview.content)
        # A4 纵向（210 宽 × 297 高）
        self.assertAlmostEqual(size[0], A4_PORTRAIT_PT[0], delta=2.5)
        self.assertAlmostEqual(size[1], A4_PORTRAIT_PT[1], delta=2.5)
        self.assertEqual(export_pages, preview_pages)
        self.assertGreaterEqual(export_pages, 2)  # 纵向长模板明确分页
        self.assertEqual(_pdf_text(export.content), _pdf_text(preview.content))
        text = _pdf_text(preview.content)
        self.assertIn('基站月度维护台账', text)
        self.assertIn('检查项-40', text)
        self.assertIn('张三', text)
        self.assertIn('2026-10-21', text)

    def test_preview_bottom_margin_whitespace(self):
        """底部留白：最后一行文字不超过「页高 - 下边距」（末页含维护人/日期）。"""
        template, version, bindings = self._publish_long_template()
        ledger_id = self._create_filled(version, bindings)
        preview = self.owner_client.post(
            '%s/%s/print-preview/' % (LEDGER_URL, ledger_id))
        if not HAS_PDFTOTEXT:
            self.skipTest('pdftotext 不可用，底部留白量测 NOT_RUN')
        height_pt = _page_height_pt(preview.content)
        max_bottom = _pdf_max_text_bottom_pt(preview.content)
        self.assertTrue(max_bottom)
        # 下边距 1.91cm ≈ 54.1pt（+3pt 容差）；维护人/日期在正文区内
        self.assertLessEqual(max_bottom, height_pt - 54.1 + 3)

    def test_preview_cache_hit_and_invalidation(self):
        """缓存命中返回相同产物；填写值变化即失效（内容寻址新键）。"""
        template, version, bindings = self._publish_long_template()
        ledger_id = self._create_filled(version, bindings)
        first = self.owner_client.post(
            '%s/%s/print-preview/' % (LEDGER_URL, ledger_id))
        second = self.owner_client.post(
            '%s/%s/print-preview/' % (LEDGER_URL, ledger_id))
        self.assertEqual(first.content, second.content)
        # 值变化 → 新键 → 新文本
        record = self._get_record(ledger_id)
        binding_by_name = {b['field_name']: b['field_id'] for b in bindings}
        values = record.get_values()
        values[binding_by_name['维护人签名']] = '李四'
        record.values = json.dumps(values, ensure_ascii=False, separators=(',', ':'))
        record.save(update_fields=['values'])
        third = self.owner_client.post(
            '%s/%s/print-preview/' % (LEDGER_URL, ledger_id))
        self.assertIn('李四', _pdf_text(third.content))
        self.assertNotIn('李四', _pdf_text(first.content))

    def _get_record(self, ledger_id):
        from apps.equipment_lifecycle.excel_models import OperationLedgerExcelRecord
        return OperationLedgerExcelRecord.objects.get(ledger_id=ledger_id)

    def test_preview_multi_sheet_content(self):
        """多工作表：主表与第二张表内容都进入 PDF。"""
        wb = Workbook()
        ws = wb.active
        ws.title = '主表'
        ws['A1'] = '主表标题内容'
        ws2 = wb.create_sheet('附表')
        ws2['A1'] = '附表汇总内容'
        # 主表 A3 仅设边框（无值）：纳入解析范围供绑定
        ws['A3'].border = Border(*[Side(style='thin')] * 4)
        buffer = io.BytesIO()
        wb.save(buffer)
        response = self.owner_client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('multi.xlsx', buffer.getvalue()),
            'name': '多表模板',
            'ledger_type': 'week_month',
        })
        template = response.json()['data']['data']
        binding = self.make_binding('A3', '主表填写', sheet='主表',
                                    input_type='text')
        self.assertEqual(self.save_bindings(template['id'], [binding])
                         .json().get('error', ''), '')
        version = self.publish(template['id'])
        response = self.owner_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id']}),
            content_type='application/json')
        ledger_id = response.json()['data']['data']['id']
        preview = self.owner_client.post(
            '%s/%s/print-preview/' % (LEDGER_URL, ledger_id))
        if preview['Content-Type'] != 'application/pdf':
            self.fail('预览返回业务错误: %s' % preview.content.decode('utf-8', 'replace')[:300])
        text = _pdf_text(preview.content)
        self.assertIn('主表标题内容', text)
        self.assertIn('附表汇总内容', text)


class BrowserEngineGuardTests(ExcelLedgerContractBase):
    """引擎守卫：非法配置显式报错（不静默回退）；探测缓存行为。"""

    def _create_filled_ledger(self, version, bindings):
        response = self.owner_client.post(
            LEDGER_URL + '/',
            json.dumps({'version_id': version['id'], 'ledger_type': 'week_month'}),
            content_type='application/json')
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        ledger_id = payload['data']['data']['id']
        values = {bindings[0]['field_id']: '正常',
                  bindings[1]['field_id']: '正常'}
        response = self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger_id),
            json.dumps({'values': values}), content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        return ledger_id

    def test_invalid_engine_business_error(self):
        template, version, bindings = self.create_published_version()
        ledger_id = self._create_filled_ledger(version, bindings)
        with override_settings(EXCEL_PDF_ENGINE='nonsense'):
            response = self.owner_client.post(
                '%s/%s/export/pdf/' % (LEDGER_URL, ledger_id))
        self.assertIn('不支持', response.json()['error'])

    def test_cache_key_changes_with_values(self):
        key_a = excel_print_cache.cache_key(1, 2, '{"a":1}', '{}', 'chromium')
        key_b = excel_print_cache.cache_key(1, 2, '{"a":2}', '{}', 'chromium')
        key_c = excel_print_cache.cache_key(1, 3, '{"a":1}', '{}', 'chromium')
        self.assertNotEqual(key_a, key_b)
        self.assertNotEqual(key_a, key_c)

    def test_print_cache_roundtrip(self):
        key = excel_print_cache.cache_key(991, 992, 'v', 'p', 'chromium')
        path = os.path.join(tempfile.gettempdir(),
                            excel_print_cache.CACHE_DIR_NAME, '%s.pdf' % key)

        def _cleanup():
            try:
                os.remove(path)
            except OSError:
                pass

        self.addCleanup(_cleanup)
        self.assertIsNone(excel_print_cache.load(key))
        excel_print_cache.store(key, b'%PDF-fake')
        self.assertEqual(excel_print_cache.load(key), b'%PDF-fake')

    def test_chromium_unavailable_raises_conversion_error(self):
        """显式 chromium 引擎但环境不可用：转换报明确错误（不静默回退）。"""
        if HAS_CHROMIUM:
            self.skipTest('Chromium 可用，不可用分支 NOT_RUN')
        with mock.patch.object(excel_browser_pdf_service, 'detect_browser',
                               return_value=None):
            with self.assertRaises(PdfConversionError):
                excel_browser_pdf_service.render_html_to_pdf(
                    '<html></html>', tempfile.mkdtemp())

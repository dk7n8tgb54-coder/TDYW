# -*- coding: utf-8 -*-
"""统一打印布局与分页计划稳定契约（2026-10-21）。

excel_print_layout.build_print_plan 是网页分页参考线与浏览器 PDF 的唯一
分页事实来源，本套件用真实 openpyxl 解析产物（parse_workbook）与构造
布局 meta 验证：

1. 纸张/方向/边距解析：A4 真实 210×297mm、横向交换宽高、缺省下边距
   1.91cm（≥15mm 底部留白建议值）、original 预设从源文件 print 设置取
   纸张/方向/缩放；
2. 缩放：fit_width/fit_page 只缩不放、percent/actual；
3. 行分页：贪婪填页、手动分页行、重复表头行后续页重排、跨行合并块
   整块移动、块高于整页拆分并告警、隐藏行零高度；
4. 列分块与 page_order（down_then_over / over_then_down）；
5. 打印区域限定行列范围；空白工作表跳过并告警；
6. 版本详情 print_plan 下发（真实模型链路）：发布版本详情含分页计划，
   上传时物理边距/缩放进入解析（浏览器引擎复现源文件版式的依据）。
"""
import io
import uuid

from django.test import SimpleTestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from openpyxl.styles import Border, Side

from apps.equipment_lifecycle.excel_print_layout import (
    PX_PER_MM,
    build_print_plan,
    column_width_px,
    row_height_px,
)
from apps.equipment_lifecycle.tests.base import URL_PREFIX, make_client, make_user
from apps.equipment_lifecycle.tests.stable_contract.test_excel_ledger_templates import (
    ExcelLedgerContractBase,
)

TPL_URL = URL_PREFIX + '/excel-templates'

# A4 纵向 + 内置缺省边距（1.91/1.78cm）的可打印区域（px @96dpi）
A4_PRINTABLE_W_PX = round((210 - 17.8 - 17.8) * PX_PER_MM, 1)
A4_PRINTABLE_H_PX = round((297 - 19.1 - 19.1) * PX_PER_MM, 1)
DEFAULT_ROW_PX = round(row_height_px(14.25))  # 19


def _sheet_meta(name='Sheet1', max_row=10, max_column=6, merged_ranges=None,
                row_heights=None, column_widths=None, hidden_rows=None,
                hidden_columns=None, cells=None, print_cfg=None):
    return {
        'name': name, 'max_row': max_row, 'max_column': max_column,
        'merged_ranges': merged_ranges or [],
        'row_heights': row_heights or {},
        'column_widths': column_widths or {},
        'hidden_rows': hidden_rows or [],
        'hidden_columns': hidden_columns or [],
        'cells': cells if cells is not None else {'A1': {'v': '标题', 's': None}},
        'print': print_cfg if print_cfg is not None else {},
    }


def _meta(sheets, sheet_name=None, pdf_params=None, bindings=None):
    return {
        'sheet_name': sheet_name if sheet_name is not None else sheets[0]['name'],
        'layout': {'active_sheet': sheet_name or sheets[0]['name'],
                   'sheets': sheets},
        'pdf_params': pdf_params if pdf_params is not None else {},
        'field_bindings': bindings or [],
    }


class PaperConfigTests(SimpleTestCase):
    """纸张/方向/边距解析（含 original 预设与真实物理尺寸）。"""

    def test_default_a4_portrait_with_bottom_margin(self):
        plan = build_print_plan(_meta([_sheet_meta()]))
        self.assertEqual(plan['paper']['name'], 'A4')
        self.assertEqual(plan['paper']['orientation'], 'portrait')
        self.assertEqual(plan['paper']['width_mm'], 210)
        self.assertEqual(plan['paper']['height_mm'], 297)
        # 缺省下边距 19.1mm ≥ 15mm 建议值；页高计算包含底部边距
        self.assertGreaterEqual(plan['margins_mm']['bottom'], 15)
        self.assertAlmostEqual(
            plan['margins_mm']['bottom'], 19.1, places=1)

    def test_landscape_swaps_width_height(self):
        plan = build_print_plan(_meta(
            [_sheet_meta()], pdf_params={'orientation': 'landscape'}))
        self.assertEqual(plan['paper']['orientation'], 'landscape')
        self.assertEqual(plan['paper']['width_mm'], 297)
        self.assertEqual(plan['paper']['height_mm'], 210)

    def test_auto_orientation_resolves_by_content_width(self):
        wide = _sheet_meta(max_column=10, column_widths={
            letter: 20 for letter in 'ABCDEFGHIJ'})
        plan = build_print_plan(_meta([wide], pdf_params={'orientation': 'auto'}))
        self.assertEqual(plan['paper']['orientation'], 'landscape')
        narrow = _sheet_meta(max_column=4, column_widths={
            letter: 10 for letter in 'ABCD'})
        plan = build_print_plan(_meta([narrow], pdf_params={'orientation': 'auto'}))
        self.assertEqual(plan['paper']['orientation'], 'portrait')

    def test_original_preset_uses_source_print_setup(self):
        sheet = _sheet_meta(print_cfg={
            'orientation': 'landscape', 'paper_size': 9,
            'fit_to_width': 1, 'fit_to_height': None,
            'scale': None, 'page_margins': {'top': 2.0, 'bottom': 2.0,
                                            'left': 1.5, 'right': 1.5},
            'print_area': 'A1:F20',
        })
        plan = build_print_plan(_meta([sheet], pdf_params={'preset': 'original'}))
        self.assertEqual(plan['paper']['name'], 'A4')
        self.assertEqual(plan['paper']['orientation'], 'landscape')
        # 物理边距来自源文件 print 设置（读取端修正补全）
        self.assertAlmostEqual(plan['margins_mm']['top'], 20.0, places=1)
        sheet_plan = plan['sheets']['Sheet1']
        self.assertEqual(sheet_plan['print_row_start'], 1)
        self.assertEqual(sheet_plan['print_row_end'], 20)

    def test_custom_margins_override(self):
        plan = build_print_plan(_meta([_sheet_meta()], pdf_params={
            'margins': {'top': 2.5, 'bottom': 1.5, 'left': 2.0, 'right': 2.0}}))
        self.assertAlmostEqual(plan['margins_mm']['top'], 25.0, places=1)
        self.assertAlmostEqual(plan['margins_mm']['bottom'], 15.0, places=1)


class ScaleTests(SimpleTestCase):
    """缩放模式（fit 只缩不放 / percent / actual）。"""

    def test_fit_width_shrinks_wide_content(self):
        wide = _sheet_meta(max_column=6, column_widths={
            letter: 30 for letter in 'ABCDEF'})
        plan = build_print_plan(_meta([wide]))
        scale = plan['sheets']['Sheet1']['scale']
        self.assertLess(scale, 1.0)
        # 内容宽 = 6 列 × (30*7+5) = 215 列宽 px → 缩放后不超过可打印宽度
        content_px = 6 * column_width_px(30)
        self.assertLessEqual(round(content_px * scale, 1), A4_PRINTABLE_W_PX + 0.5)

    def test_fit_width_never_grows(self):
        narrow = _sheet_meta(max_column=2, column_widths={'A': 8, 'B': 8})
        plan = build_print_plan(_meta([narrow]))
        self.assertEqual(plan['sheets']['Sheet1']['scale'], 1.0)

    def test_percent_and_actual(self):
        plan = build_print_plan(_meta(
            [_sheet_meta()], pdf_params={'scale_mode': 'percent',
                                         'scale_percent': 80}))
        self.assertEqual(plan['sheets']['Sheet1']['scale'], 0.8)
        plan = build_print_plan(_meta(
            [_sheet_meta()], pdf_params={'scale_mode': 'actual'}))
        self.assertEqual(plan['sheets']['Sheet1']['scale'], 1.0)


class RowPaginationTests(SimpleTestCase):
    """行方向分页（贪婪填页/手动分页/重复表头/合并块/隐藏行）。"""

    def test_rows_fill_page_greedily(self):
        # 120 行默认行高（19px），纵向可打印 ~978px → 每页 51 行，共 3 页
        sheet = _sheet_meta(max_row=120, max_column=2,
                            cells={'A1': {'v': '标题', 's': None}})
        plan = build_print_plan(_meta([sheet]))
        sheet_plan = plan['sheets']['Sheet1']
        self.assertEqual(sheet_plan['page_count'], 3)
        self.assertEqual(sheet_plan['row_breaks'], [52, 103])
        self.assertEqual(sheet_plan['pages'][0]['row_start'], 1)
        self.assertEqual(sheet_plan['pages'][0]['row_end'], 51)
        self.assertEqual(sheet_plan['pages'][2]['row_end'], 120)

    def test_manual_row_breaks(self):
        sheet = _sheet_meta(max_row=30, max_column=2)
        plan = build_print_plan(_meta(
            [sheet], pdf_params={'row_breaks': [10, 20]}))
        sheet_plan = plan['sheets']['Sheet1']
        # 手动分页行 = 该行后断页（该行为页末行）
        self.assertEqual(sheet_plan['pages'][0]['row_end'], 10)
        self.assertEqual(sheet_plan['pages'][1]['row_start'], 11)
        self.assertEqual(sheet_plan['pages'][1]['row_end'], 20)

    def test_repeat_header_rows_on_later_pages(self):
        sheet = _sheet_meta(max_row=120, max_column=2,
                            cells={'A1': {'v': '标题', 's': None}})
        plan = build_print_plan(_meta(
            [sheet], pdf_params={'repeat_header_rows': '1:2'}))
        pages = plan['sheets']['Sheet1']['pages']
        self.assertIsNone(pages[0]['repeat_rows'])  # 首页自然包含
        self.assertEqual(pages[1]['repeat_rows'], [1, 2])
        self.assertEqual(pages[2]['repeat_rows'], [1, 2])
        # 重排表头占位：第 2 页行数变少（978px 容纳 38px 表头 + 49 行）
        self.assertEqual(pages[1]['row_start'], 52)
        self.assertLess(pages[1]['row_end'], 102)

    def test_merged_block_moves_whole_to_next_page(self):
        # 合并 B50:B52 横跨 51 行分页边界 → 整块移动到下一页
        sheet = _sheet_meta(max_row=60, max_column=3,
                            merged_ranges=['B50:B52'],
                            cells={'A1': {'v': '标题', 's': None}})
        plan = build_print_plan(_meta([sheet]))
        sheet_plan = plan['sheets']['Sheet1']
        self.assertEqual(sheet_plan['row_breaks'][0], 50)
        self.assertEqual(sheet_plan['pages'][1]['row_start'], 50)

    def test_tall_merged_block_splits_with_warning(self):
        # 60 行合并（1140px）高于整页可打印高度 → 拆分 + 明确告警
        sheet = _sheet_meta(max_row=60, max_column=3,
                            merged_ranges=['B1:B60'],
                            cells={'A1': {'v': '标题', 's': None}})
        plan = build_print_plan(_meta([sheet]))
        self.assertTrue(any('跨页拆分' in w for w in plan['warnings']))
        self.assertGreaterEqual(plan['sheets']['Sheet1']['page_count'], 2)

    def test_hidden_rows_zero_height(self):
        # 隐藏行不计高度：60 行中前 10 行隐藏 → 50×19=950px 单页容纳
        sheet = _sheet_meta(max_row=60, max_column=2,
                            hidden_rows=[str(row) for row in range(1, 11)])
        plan = build_print_plan(_meta([sheet]))
        sheet_plan = plan['sheets']['Sheet1']
        self.assertEqual(sheet_plan['page_count'], 1)
        self.assertEqual(sheet_plan['pages'][0]['row_start'], 1)
        self.assertEqual(sheet_plan['pages'][0]['row_end'], 60)


class ColumnBandTests(SimpleTestCase):
    """列方向分块与 page_order（actual 模式：fit_width 会把宽度缩进一页，
    横向分块只在固定缩放下发生——与 Excel 语义一致）。"""

    def _wide_sheet(self):
        return _sheet_meta(max_row=120, max_column=12, column_widths={
            letter: 14 for letter in 'ABCDEFGHIJKL'},
            cells={'A1': {'v': '标题', 's': None}})

    def test_column_bands_by_printable_width(self):
        # 12 列 × (14*7+5)=103px = 1236px，横向可打印 ~988px → 2 块（9+3 列）
        plan = build_print_plan(_meta(
            [self._wide_sheet()],
            pdf_params={'scale_mode': 'actual', 'orientation': 'auto'}))
        sheet_plan = plan['sheets']['Sheet1']
        self.assertEqual(sheet_plan['col_breaks'], [10])
        pages = sheet_plan['pages']
        self.assertEqual(len({(p['col_start'], p['col_end']) for p in pages}), 2)
        self.assertEqual((pages[0]['col_start'], pages[0]['col_end']), (1, 9))
        self.assertEqual((pages[-1]['col_start'], pages[-1]['col_end']), (10, 12))
        # fit_width 缩放后整表宽度进入单页：无横向分块
        fit_plan = build_print_plan(_meta(
            [self._wide_sheet()], pdf_params={'orientation': 'auto'}))
        self.assertEqual(fit_plan['sheets']['Sheet1']['col_breaks'], [])

    def test_page_order_over_then_down(self):
        plan = build_print_plan(_meta(
            [self._wide_sheet()],
            pdf_params={'scale_mode': 'actual', 'orientation': 'auto',
                        'page_order': 'over_then_down'}))
        pages = plan['sheets']['Sheet1']['pages']
        # 先右后下：同一行页的两个列块相邻（列块起始序列 1,10,1,10…）
        col_starts = [p['col_start'] for p in pages[:4]]
        self.assertEqual(col_starts, [1, 10, 1, 10])

    def test_page_order_down_then_over(self):
        plan = build_print_plan(_meta(
            [self._wide_sheet()],
            pdf_params={'scale_mode': 'actual', 'orientation': 'auto'}))
        pages = plan['sheets']['Sheet1']['pages']
        col_starts = [p['col_start'] for p in pages[:4]]
        self.assertEqual(col_starts, [1, 1, 1, 1])


class PrintAreaAndBlankSheetTests(SimpleTestCase):
    """打印区域限定与空白工作表跳过。"""

    def test_print_area_limits_rows_and_columns(self):
        sheet = _sheet_meta(max_row=50, max_column=8)
        plan = build_print_plan(_meta(
            [sheet], pdf_params={'print_area': 'B2:C10'}))
        sheet_plan = plan['sheets']['Sheet1']
        self.assertEqual(sheet_plan['print_row_start'], 2)
        self.assertEqual(sheet_plan['print_row_end'], 10)
        self.assertEqual(sheet_plan['print_col_start'], 2)
        self.assertEqual(sheet_plan['print_col_end'], 3)

    def test_blank_sheet_skipped_with_warning(self):
        blank = _sheet_meta(name='空白页', max_row=5, max_column=5, cells={})
        content = _sheet_meta(name='内容页', max_row=5, max_column=5)
        plan = build_print_plan(_meta([blank, content], sheet_name='内容页'))
        self.assertNotIn('空白页', plan['sheets'])
        self.assertTrue(any('空白页' in w and '没有可打印内容' in w
                            for w in plan['warnings']))

    def test_bound_sheet_with_no_cells_not_skipped(self):
        # 有绑定字段的工作表即使无模板内容也不跳过（填写值要打印）
        sheet = _sheet_meta(name='填写页', max_row=5, max_column=5, cells={})
        binding = [{'field_id': str(uuid.uuid4()), 'sheet_name': '填写页',
                    'cell_coordinate': 'B2', 'field_name': '签名',
                    'input_type': 'text', 'is_required': False,
                    'unit': '', 'options': []}]
        plan = build_print_plan(_meta([sheet], bindings=binding))
        self.assertIn('填写页', plan['sheets'])


class VersionPrintPlanTests(ExcelLedgerContractBase):
    """版本详情 print_plan 下发（真实模型链路，发布版本含分页计划）。"""

    def _upload_simple(self, margins_cm=None):
        wb = Workbook()
        ws = wb.active
        ws.title = '信道维护记录'
        ws['A1'] = '标题'
        for row in range(2, 30):
            ws.cell(row=row, column=1, value='第%d行' % row)
        for letter, width in (('A', 20), ('B', 12)):
            ws.column_dimensions[letter].width = width
        # B5 仅设边框（无值）：纳入解析范围供绑定，不影响内容宽度判定
        ws['B5'].border = Border(*[Side(style='thin')] * 4)
        if margins_cm:
            # openpyxl page_margins 以英寸赋值：cm → inch
            ws.page_margins.left = margins_cm[0] / 2.54
            ws.page_margins.right = margins_cm[1] / 2.54
            ws.page_margins.top = margins_cm[2] / 2.54
            ws.page_margins.bottom = margins_cm[3] / 2.54
        buffer = io.BytesIO()
        wb.save(buffer)
        return buffer.getvalue()

    def _upload_and_publish(self, data, name):
        response = self.owner_client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('plan.xlsx', data),
            'name': name,
            'ledger_type': 'week_month',
        })
        template = response.json()['data']['data']
        binding = self.make_binding('B5', '检查项填写', input_type='text')
        response = self.save_bindings(template['id'], [binding])
        self.assertEqual(response.json().get('error', ''), '')
        return template, self.publish(template['id'])

    def test_version_detail_contains_print_plan(self):
        template, version = self._upload_and_publish(
            self._upload_simple(), '计划测试模板')
        detail = self.owner_client.get(
            '%s/%s/versions/%s/' % (TPL_URL, template['id'], version['version_no']))
        payload = detail.json()['data']['data']
        plan = payload.get('print_plan')
        self.assertTrue(plan)
        self.assertEqual(plan['plan_version'], 1)
        self.assertEqual(plan['paper']['name'], 'A4')
        self.assertIn('信道维护记录', plan['sheets'])
        self.assertGreaterEqual(plan['sheets']['信道维护记录']['page_count'], 1)
        # 上传解析捕获物理边距（inch→cm，openpyxl 缺省左右 0.75in=1.91cm）
        self.assertAlmostEqual(plan['margins_mm']['left'], 19.1, delta=0.3)

    def test_version_detail_plan_respects_file_margins(self):
        template, version = self._upload_and_publish(
            self._upload_simple(margins_cm=(2.0, 2.0, 2.5, 2.5)), '边距测试模板')
        detail = self.owner_client.get(
            '%s/%s/versions/%s/' % (TPL_URL, template['id'], version['version_no']))
        plan = detail.json()['data']['data']['print_plan']
        self.assertAlmostEqual(plan['margins_mm']['left'], 20.0, delta=0.3)
        self.assertAlmostEqual(plan['margins_mm']['bottom'], 25.0, delta=0.3)

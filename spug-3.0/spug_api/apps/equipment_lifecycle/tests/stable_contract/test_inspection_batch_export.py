# -*- coding: utf-8 -*-
"""巡检单批量详情导出稳定契约（按筛选条件批量导出，无手动勾选）。

覆盖行为契约：
- 默认值班日期范围（最近 30 个自然日，含今天）语义 = duty_from >= 起始日、
  duty_to <= 截止日的自然日边界，列表与批量导出共用同一筛选口径；
- 批量 Excel：一个工作簿 = 巡检单汇总 + 每单"信息_单号/明细_单号"两个详情
  工作表；导出筛选范围内全部数据，不受分页参数影响；
- 批量 PDF：一个合并文档（同一 ReportLab 文档流连续生成），每个巡检单
  独立分页（从新页开始）；
- 独立权限 equipment_lifecycle.inspection.export；后端重新执行筛选与
  租户隔离；Excel/PDF 数量上限分别校验；无匹配数据返回统一业务错误；
- 导出为只读行为：不修改巡检单及明细，故障/工单/履历关联数据不受影响；
- 每次批量导出记录一条审计事件（导出类型、数量、筛选条件）。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，Excel 以 openpyxl 读取、
PDF 校验二进制与页数。
"""
import io
import json
import re
from datetime import timedelta
from unittest import mock
from urllib.parse import unquote

from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from openpyxl import load_workbook

from apps.equipment_lifecycle import fault_services, inspection_export
from apps.equipment_lifecycle.models import (
    InspectionDutySheet,
    InspectionRecord,
    SystemEvent,
    SystemFault,
    SystemWorkOrder,
)
from apps.equipment_lifecycle.tests.base import make_client, make_system, make_user
from apps.equipment_lifecycle.tests.stable_contract.inspection_base import (
    INS_URL,
    create_sheet_ok,
    get_sheet_detail,
    get_template_items,
    make_inspection_template,
    make_inspection_user,
    put_records_ok,
    record_spec,
    sheet_payload,
    submit_sheet_ok,
)
from apps.logs.models import AuditLog

BATCH_XLSX_URL = '/equipment-lifecycle/inspection-sheets/batch-export/xlsx'
BATCH_PDF_URL = '/equipment-lifecycle/inspection-sheets/batch-export/pdf'
P_INS_EXPORT = 'equipment_lifecycle.inspection.export'

SUMMARY_SHEET = '巡检单汇总'
EMPTY_ERROR = '当前筛选条件下没有可导出的数据'


def make_export_user(username, tenant_id='tenant_a', with_export=True):
    """仅授予查看（可选导出）权限的用户，避免夹具权限掩盖权限缺失缺陷。"""
    perms = ['equipment_lifecycle.inspection.view']
    if with_export:
        perms.append(P_INS_EXPORT)
    return make_user(username, perms, tenant_id=tenant_id)


def build_sheet(client, template, items, duty_date, submit=True):
    """走真实 API 建单并填 r1（异常）/r2/r3 三轮记录，可选提交。"""
    detail = create_sheet_ok(client, sheet_payload(
        template.id, duty_date=str(duty_date), client_token=f'tok-batch-{duty_date}'))
    sheet_id, version = detail['id'], detail['version']
    plan = [
        record_spec(items['面板指示灯'].id, 'r1', value_text='不正常',
                    abnormal_desc='告警灯红色', onsite_action='已切换备用机'),
        record_spec(items['输出功率读数'].id, 'r2', value_text='512'),
        record_spec(items['驻波比检查'].id, 'r3', value_text='正常'),
    ]
    for spec in plan:
        detail = put_records_ok(client, sheet_id, version, records=[spec])
        version = detail['version']
    if submit:
        detail = submit_sheet_ok(client, sheet_id)
    return detail


def load_workbook_from(response):
    return load_workbook(io.BytesIO(response.content))


def workbook_text(wb_or_ws):
    worksheets = (wb_or_ws.worksheets if hasattr(wb_or_ws, 'worksheets')
                  else [wb_or_ws])
    return '\n'.join(
        str(cell.value) for ws in worksheets for row in ws.iter_rows()
        for cell in row if cell.value is not None)


def summary_rows(wb):
    ws = wb[SUMMARY_SHEET]
    return [row for row in ws.iter_rows(min_row=2, values_only=True) if any(row)]


def pdf_page_count(content):
    """从 reportlab 生成的 PDF 提取页数（页面树 /Count，未压缩对象）。"""
    counts = re.findall(rb'/Count (\d+)', content)
    return max(int(c) for c in counts) if counts else 0


def pdf_title(content):
    """还原 PDF /Title 元数据（八进制转义 → UTF-16BE，去 BOM）。"""
    match = re.search(rb'/Title\s*\(((?:[^()\\]|\\.)*)\)', content)
    if match is None:
        return None
    decoded = re.sub(rb'\\([0-7]{3})',
                     lambda m: bytes([int(m.group(1), 8)]), match.group(1))
    return decoded.decode('utf-16-be').lstrip('\ufeff')


def disposition_filename(response):
    header = response['Content-Disposition']
    assert header.startswith("attachment; filename*=UTF-8''"), header
    return unquote(header.split("UTF-8''", 1)[1])


class InspectionBatchExportTestBase(TestCase):
    """公共夹具：作者（全巡检权限）+ 模板 + 仅查看/导出权限的导出者。"""

    def setUp(self):
        self.admin = make_inspection_user('ins_batch_admin', tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.template = make_inspection_template(
            tenant_id='tenant_a', created_by=self.admin)
        self.items = get_template_items(self.template)
        self.exporter = make_client(make_export_user('ins_batch_exporter'))


class InspectionBatchRangeTest(InspectionBatchExportTestBase):
    """默认 30 个自然日窗口的查询语义：自然日边界，列表与批量同口径。"""

    def test_default_window_natural_day_boundaries(self):
        """默认窗口（today-29 ~ today）按自然日边界命中，早一天/次日不导出。"""
        today = timezone.now().date()
        first_day = today - timedelta(days=29)
        day_before = today - timedelta(days=30)
        sheet_first = build_sheet(self.client, self.template, self.items, first_day)
        sheet_today = build_sheet(self.client, self.template, self.items, today)
        sheet_before = build_sheet(self.client, self.template, self.items, day_before)

        window = f'duty_from={first_day}&duty_to={today}'
        resp = self.exporter.get(f'{BATCH_XLSX_URL}/?{window}')
        self.assertEqual(resp.status_code, 200)
        text = workbook_text(load_workbook_from(resp))
        self.assertIn(sheet_first['sheet_no'], text)
        self.assertIn(sheet_today['sheet_no'], text)
        self.assertNotIn(sheet_before['sheet_no'], text)

        # 截止日边界（<=）：只查截止日当天
        resp = self.exporter.get(f'{BATCH_XLSX_URL}/?duty_from={today}&duty_to={today}')
        text = workbook_text(load_workbook_from(resp))
        self.assertIn(sheet_today['sheet_no'], text)
        self.assertNotIn(sheet_first['sheet_no'], text)

    def test_batch_export_ignores_pagination_params(self):
        """批量导出不受分页影响：带 page/page_size 也导出筛选范围内全部数据。"""
        today = timezone.now().date()
        dates = [today - timedelta(days=2), today - timedelta(days=1), today]
        sheets = [build_sheet(self.client, self.template, self.items, d) for d in dates]
        window = f'duty_from={dates[0]}&duty_to={dates[-1]}'
        resp = self.exporter.get(
            f'{BATCH_XLSX_URL}/?{window}&page=1&page_size=1')
        self.assertEqual(resp.status_code, 200)
        wb = load_workbook_from(resp)
        self.assertEqual(len(summary_rows(wb)), 3)
        text = workbook_text(wb)
        for sheet in sheets:
            self.assertIn(sheet['sheet_no'], text)

    def test_batch_export_empty_result_rejected(self):
        """无匹配数据返回统一业务错误，不生成空文件（两个端点一致）。"""
        for url in (BATCH_XLSX_URL, BATCH_PDF_URL):
            resp = self.exporter.get(f'{url}/?keyword=不存在单号')
            self.assertEqual(resp.status_code, 400, url)
            self.assertEqual(resp.json()['error'], EMPTY_ERROR, url)

    def test_batch_export_invalid_filters_rejected(self):
        """状态不合法 / 日期格式不合法返回明确业务错误。"""
        resp = self.exporter.get(f'{BATCH_XLSX_URL}/?status=invalid')
        self.assertEqual(resp.json()['error'], '状态筛选值不合法')
        resp = self.exporter.get(f'{BATCH_PDF_URL}/?duty_from=2026/09/01')
        self.assertEqual(resp.json()['error'], '值班日起始格式不正确')
        resp = self.exporter.get(f'{BATCH_PDF_URL}/?duty_to=not-a-date')
        self.assertEqual(resp.json()['error'], '值班日截止格式不正确')


class InspectionBatchExcelTest(InspectionBatchExportTestBase):
    """批量 Excel：汇总 + 每单双详情工作表，筛选条件与租户边界。"""

    def setUp(self):
        super().setUp()
        self.today = timezone.now().date()
        self.dates = [self.today - timedelta(days=2),
                      self.today - timedelta(days=1), self.today]
        self.sheets = [
            build_sheet(self.client, self.template, self.items, d) for d in self.dates]
        self.window = f'duty_from={self.dates[0]}&duty_to={self.dates[-1]}'

    def test_batch_excel_workbook_structure(self):
        """一个工作簿：汇总表 + 每单"信息_单号/明细_单号"两个详情工作表。"""
        resp = self.exporter.get(f'{BATCH_XLSX_URL}/?{self.window}&status=submitted')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('spreadsheetml.sheet', resp['Content-Type'])
        self.assertIn('巡检单详情批量_', disposition_filename(resp))
        wb = load_workbook_from(resp)
        expected = [SUMMARY_SHEET]
        for sheet in reversed(self.sheets):  # 查询集排序 -duty_date：新值班日在前
            expected += [f'信息_{sheet["sheet_no"]}', f'明细_{sheet["sheet_no"]}']
        self.assertEqual(wb.sheetnames, expected)

        summary = summary_rows(wb)
        self.assertEqual(len(summary), 3)
        nos = {row[1] for row in summary}
        self.assertEqual(nos, {s['sheet_no'] for s in self.sheets})

        first = self.sheets[-1]  # 列表排序 -duty_date：今天在前
        info_text = workbook_text(wb[f'信息_{first["sheet_no"]}'])
        self.assertIn(first['sheet_no'], info_text)
        self.assertIn('值班员甲', info_text)
        self.assertIn('已提交', info_text)
        matrix_text = workbook_text(wb[f'明细_{first["sheet_no"]}'])
        for expected_text in ('1号收发信机', '面板指示灯', '不正常', '512',
                              '异常说明：告警灯红色', '现场处理：已切换备用机'):
            self.assertIn(expected_text, matrix_text)
        # 未记录轮次显示"未记录"（夹具只填了三轮）
        self.assertIn('未记录', matrix_text)

    def test_batch_excel_respects_status_and_keyword_filters(self):
        """状态与关键字筛选生效：导出内容随筛选条件变化。"""
        draft = build_sheet(self.client, self.template, self.items,
                            self.today + timedelta(days=1), submit=False)
        resp = self.exporter.get(
            f'{BATCH_XLSX_URL}/?duty_from={self.dates[0]}'
            f'&duty_to={self.today + timedelta(days=1)}&status=submitted')
        text = workbook_text(load_workbook_from(resp))
        for sheet in self.sheets:
            self.assertIn(sheet['sheet_no'], text)
        self.assertNotIn(draft['sheet_no'], text)

        resp = self.exporter.get(
            f'{BATCH_XLSX_URL}/?duty_from={self.dates[0]}'
            f'&duty_to={self.today + timedelta(days=1)}'
            f'&keyword={draft["sheet_no"]}')
        text = workbook_text(load_workbook_from(resp))
        self.assertIn(draft['sheet_no'], text)
        for sheet in self.sheets:
            self.assertNotIn(sheet['sheet_no'], text)

    def test_batch_excel_cross_tenant_isolated(self):
        """跨租户巡检单不会出现在导出结果中。"""
        other_admin = make_inspection_user('ins_batch_admin_b', tenant_id='tenant_b')
        template_b = make_inspection_template(
            tenant_id='tenant_b', created_by=other_admin, name='乙方模板')
        other_sheet = InspectionDutySheet.objects.create(
            tenant_id='tenant_b', sheet_no='XJ20990101-9001',
            duty_date=self.today, template=template_b, status='draft',
            uniq_key=f'{self.today}|{template_b.id}',
            created_by=other_admin)

        resp = self.exporter.get(f'{BATCH_XLSX_URL}/?{self.window}')
        self.assertEqual(resp.status_code, 200)
        text = workbook_text(load_workbook_from(resp))
        self.assertNotIn(other_sheet.sheet_no, text)
        for sheet in self.sheets:
            self.assertIn(sheet['sheet_no'], text)

        other = make_client(make_export_user('ins_batch_exporter_b',
                                             tenant_id='tenant_b'))
        resp = other.get(f'{BATCH_XLSX_URL}/?{self.window}')
        self.assertEqual(resp.status_code, 200)
        text = workbook_text(load_workbook_from(resp))
        # 乙方只能导出自己的巡检单
        self.assertIn(other_sheet.sheet_no, text)
        for sheet in self.sheets:
            self.assertNotIn(sheet['sheet_no'], text)

    def test_batch_excel_over_limit_rejected(self):
        """超过 Excel 上限时拒绝导出（收紧上限模拟超量，消息含上限值）。"""
        with mock.patch.object(inspection_export, 'batch_export_limit',
                               return_value=2):
            resp = self.exporter.get(f'{BATCH_XLSX_URL}/?{self.window}')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()['error'],
            '批量导出数据超过 2 条，请缩小值班日期范围或增加筛选条件后重试')

    def test_batch_excel_includes_convert_disposition(self):
        """异常明细存在历史"已转故障"来源数据时，批量 Excel 明细工作表包含转单去向。"""
        target = self.sheets[0]
        record = InspectionRecord.objects.get(pk=next(
            r['id'] for r in target['records'] if r['result'] == 'abnormal'))
        system = make_system(created_by=self.admin, tenant_id='tenant_a')
        with fault_services.health_recalc_lock():
            with transaction.atomic():
                fault_services.create_fault_record(
                    tenant_id='tenant_a', created_by=self.admin,
                    system=system, impact_status='',
                    occurred_at=timezone.now(),
                    discovery=SystemFault.DISCOVERY_PATROL,
                    level=SystemFault.LEVEL_MINOR,
                    phenomenon='历史巡检异常转入的故障',
                    source_type='inspection_record',
                    source_inspection_record=record)

        resp = self.exporter.get(f'{BATCH_XLSX_URL}/?{self.window}')
        text = workbook_text(load_workbook_from(resp))
        self.assertIn('已转故障：GZ', text)


class InspectionBatchPdfTest(InspectionBatchExportTestBase):
    """批量 PDF：有效合并文档，每个巡检单独立分页。"""

    def setUp(self):
        super().setUp()
        self.today = timezone.now().date()
        self.dates = [self.today - timedelta(days=1), self.today]
        self.sheets = [
            build_sheet(self.client, self.template, self.items, d) for d in self.dates]
        self.window = f'duty_from={self.dates[0]}&duty_to={self.dates[-1]}'

    def test_batch_pdf_valid_document_with_per_sheet_pages(self):
        """有效 PDF；每个巡检单从新页开始（单页内容 → 页数 = 巡检单数）。"""
        resp = self.exporter.get(f'{BATCH_PDF_URL}/?{self.window}&page=1&page_size=1')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))
        self.assertIn('巡检单详情批量_', disposition_filename(resp))
        # 多个巡检单之间正确分页：每单内容不满一页 → 页数 = 单数
        self.assertEqual(pdf_page_count(resp.content), len(self.sheets))
        # 文档元数据标题（UTF-16BE，与单条导出同源构建）
        self.assertEqual(pdf_title(resp.content), '值班巡检单批量导出')
        # 真实内容体量（每单：标题 + 信息表 + 四轮矩阵）
        self.assertGreater(len(resp.content), 3000)

    def test_batch_pdf_over_limit_rejected(self):
        """超过 PDF 上限时拒绝导出（Excel 与 PDF 上限分别校验）。"""
        with mock.patch.object(inspection_export, 'batch_export_limit',
                               return_value=1):
            resp = self.exporter.get(f'{BATCH_PDF_URL}/?{self.window}')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()['error'],
            '批量 PDF 导出数据超过 1 条，请缩小值班日期范围或增加筛选条件后重试')
        # 同一数据量仍在 Excel 上限内（默认 500），Excel 不受 PDF 上限影响
        resp = self.exporter.get(f'{BATCH_XLSX_URL}/?{self.window}')
        self.assertEqual(resp.status_code, 200)


class InspectionBatchExportSafetyTest(InspectionBatchExportTestBase):
    """权限、只读性与审计契约。"""

    def setUp(self):
        super().setUp()
        self.today = timezone.now().date()
        self.sheet = build_sheet(self.client, self.template, self.items, self.today)
        self.window = f'duty_from={self.today}&duty_to={self.today}'

    def test_batch_export_requires_independent_permission(self):
        no_perm = make_client(make_export_user('ins_batch_no_perm', with_export=False))
        for url in (BATCH_XLSX_URL, BATCH_PDF_URL):
            resp = no_perm.get(f'{url}/?{self.window}')
            self.assertEqual(resp.json()['error'], '权限拒绝', url)

    def test_batch_export_is_readonly(self):
        """批量导出不修改巡检单及明细，故障/工单/履历关联数据不受影响。"""
        before_detail = get_sheet_detail(self.client, self.sheet['id'])
        fault_count = SystemFault.objects.count()
        order_count = SystemWorkOrder.objects.count()
        event_count = SystemEvent.objects.count()

        for url in (BATCH_XLSX_URL, BATCH_PDF_URL):
            resp = self.exporter.get(f'{url}/?{self.window}')
            self.assertEqual(resp.status_code, 200, url)

        after_detail = get_sheet_detail(self.client, self.sheet['id'])
        self.assertEqual(before_detail['version'], after_detail['version'])
        self.assertEqual(before_detail['status'], after_detail['status'])
        self.assertEqual(before_detail['recorded_rounds'],
                         after_detail['recorded_rounds'])
        self.assertEqual(
            [(r['id'], r['round_no'], r['value_text'], r['result'],
              r['abnormal_desc'], r['onsite_action']) for r in before_detail['records']],
            [(r['id'], r['round_no'], r['value_text'], r['result'],
              r['abnormal_desc'], r['onsite_action']) for r in after_detail['records']])
        self.assertEqual(SystemFault.objects.count(), fault_count)
        self.assertEqual(SystemWorkOrder.objects.count(), order_count)
        self.assertEqual(SystemEvent.objects.count(), event_count)

    def test_single_detail_export_still_works(self):
        """现有单条 Excel/PDF 导出继续通过。"""
        xlsx = self.exporter.get(f'{INS_URL}/{self.sheet["id"]}/export/xlsx/')
        self.assertEqual(xlsx.status_code, 200)
        wb = load_workbook(io.BytesIO(xlsx.content))
        self.assertEqual(wb.sheetnames, ['巡查单信息', '四轮巡检明细'])
        pdf = self.exporter.get(f'{INS_URL}/{self.sheet["id"]}/export/pdf/')
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))

    def test_batch_export_audit_event_recorded(self):
        """每次批量导出记录一条审计事件（导出类型、数量、筛选条件）。"""
        resp = self.exporter.get(f'{BATCH_XLSX_URL}/?{self.window}&status=submitted')
        self.assertEqual(resp.status_code, 200)
        audit = AuditLog.objects.filter(
            tenant_id='tenant_a', target_type='el_inspection_sheet',
            action='export', detail__contains='batch_detail_xlsx').first()
        self.assertIsNotNone(audit)
        detail = json.loads(audit.detail)
        after = detail.get('after') or {}
        self.assertEqual(after.get('export_type'), 'batch_detail_xlsx')
        self.assertEqual(after.get('count'), 1)
        filters = after.get('filters') or {}
        self.assertEqual(filters.get('duty_from'), str(self.today))
        self.assertEqual(filters.get('duty_to'), str(self.today))
        self.assertEqual(filters.get('status'), 'submitted')

        resp = self.exporter.get(f'{BATCH_PDF_URL}/?{self.window}')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(
            tenant_id='tenant_a', action='export',
            detail__contains='batch_detail_pdf').exists())

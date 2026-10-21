# -*- coding: utf-8 -*-
"""台账列表"批量导出 PDF"（按模板多选，2026-10-21）行为测试。

真实执行 HTTP → View → Service → Model 链路（Docker + 隔离测试库）：
- 模板候选清单（GET /ledgers/export-pdf/）：仅本租户、指定台账类型、
  含已停用但有历史台账的模板；各状态数量与"版本 × 状态"分布准确；
  手工补录与无台账模板不出现；跨租户不出现；
- 导出（POST /ledgers/export-pdf/）：
  * 单模板 → 一份合并 PDF；多模板 → ZIP（每模板一份 PDF，不同模板
    不混成一个 PDF），文件名含模板名与导出日期、非法字符净化、同名
    模板以模板 ID 区分且 ZIP 内条目名唯一；
  * 按模板 ID 组织：同模板 v1/v2 各版本台账归同一模板，每条台账用创建
    时版本生成（单条转换打桩为可控页尺寸 PDF 验证版本归属），pypdf
    真实合并，模板内按维护期次从早到晚排列，无可靠期次的排最后按
    创建顺序；
  * 范围由弹窗决定：默认仅已完成（草稿/已作废不纳入），status=all
    显式包含全部；不继承列表筛选（keyword/page 等参数不产生作用），
    也不受分页截取（全部匹配记录参与）；
  * 已停用模板仍可导出历史台账（停用只禁新建）；
  * 边界与失败：跨类型混选拒绝、跨租户拒绝、未知/重复/非法模板 ID
    拒绝、无可导出记录拒绝（含模板名）、总量超限拒绝、预览数量漂移
    拒绝（须重新确认）、任一条转换失败整体终止（错误含模板名与台账
    编号，无部分产物）、状态漂移拒绝、导出权限独立校验、审计记录；
- 真实转换（LibreOffice 可用时）：单模板 PDF 与多模板 ZIP 的页数、
  版本纸张参数保留与实际填写内容。
"""
import io
import json
import uuid
import zipfile
from unittest import mock, skipUnless

from pypdf import PdfReader, PdfWriter

from apps.equipment_lifecycle import ledger_template_group_services
from apps.equipment_lifecycle.excel_ledger_services import ExcelLedgerError
from apps.equipment_lifecycle.excel_pdf_service import detect_soffice
from apps.equipment_lifecycle.excel_models import OperationLedgerExcelTemplate
from apps.equipment_lifecycle.models import (
    LEDGER_STATUS_COMPLETED,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_VOID,
    LEDGER_TYPE_SEASONAL,
    LEDGER_TYPE_WEEK_MONTH,
    OperationLedger,
)
from apps.equipment_lifecycle.tests.base import URL_PREFIX, make_client, make_user
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import P_LED_VIEW
from apps.equipment_lifecycle.tests.stable_contract.test_excel_ledger_templates import (
    LEDGER_URL,
    TPL_URL,
    ExcelLedgerContractBase,
)
from apps.equipment_lifecycle.tests.test_ledger_template_groups import TemplateGroupTestBase

EXPORT_URL = URL_PREFIX + '/ledgers/export-pdf/'


def post_export(client, payload):
    return client.post(
        EXPORT_URL, json.dumps(payload), content_type='application/json')


def ok_data(resp):
    body = resp.json()
    assert not body.get('error'), body
    return body['data']


def list_data(resp):
    """候选清单业务载荷：视图 json_response({'data': {...}}) 双层解包。"""
    return ok_data(resp)['data']


def fake_pdf(width, height, pages=1):
    """构造可控页尺寸的最小合法 PDF（pypdf 空白页），验证合并编排与顺序。"""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width, height)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def page_sizes(content):
    reader = PdfReader(io.BytesIO(content))
    return [(round(float(page.mediabox.width)), round(float(page.mediabox.height)))
            for page in reader.pages]


def zip_entries(content):
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return zf.namelist()


def zip_entry_contents(content):
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def size_close(size, expected, tolerance=2):
    """LibreOffice 产出的页尺寸与期望值近似相等（±2pt）。"""
    return all(abs(a - b) <= tolerance for a, b in zip(size, expected))


class MultiExportListTests(TemplateGroupTestBase):
    """模板候选清单口径：租户/类型/停用/状态与版本分布。"""

    def test_lists_templates_with_status_and_version_counts(self):
        t1 = self.make_template('信道维护台账')
        v1 = self.make_version(t1, 1)
        v2 = self.make_version(t1, 2)
        self.make_excel_ledger(v1, status=LEDGER_STATUS_COMPLETED)
        self.make_excel_ledger(v1, status=LEDGER_STATUS_COMPLETED)
        self.make_excel_ledger(v1, status=LEDGER_STATUS_DRAFT)
        self.make_excel_ledger(v2, status=LEDGER_STATUS_COMPLETED)
        self.make_excel_ledger(v2, status=LEDGER_STATUS_VOID)
        # 无任何台账的模板不出现
        self.make_template('空模板')
        data = list_data(self.client.get(EXPORT_URL, {'ledger_type': LEDGER_TYPE_WEEK_MONTH}))
        self.assertEqual(data['ledger_type'], LEDGER_TYPE_WEEK_MONTH)
        self.assertEqual(data['default_statuses'], ['completed'])
        self.assertEqual(data['max_records'],
                         ledger_template_group_services.MAX_BATCH_EXPORT_RECORDS)
        self.assertEqual(len(data['templates']), 1)
        row = data['templates'][0]
        self.assertEqual(row['template_id'], t1.id)
        self.assertEqual(row['template_name'], '信道维护台账')
        self.assertTrue(row['is_active'])
        self.assertEqual(row['counts'],
                         {'completed': 3, 'draft': 1, 'void': 1})
        self.assertEqual(row['versions'], {
            '1': {'completed': 2, 'draft': 1, 'void': 0},
            '2': {'completed': 1, 'draft': 0, 'void': 1},
        })

    def test_stopped_template_with_history_listed(self):
        template = self.make_template('退役模板', is_active=False)
        self.make_excel_ledger(
            self.make_version(template, 1), status=LEDGER_STATUS_COMPLETED)
        data = list_data(self.client.get(EXPORT_URL, {'ledger_type': LEDGER_TYPE_WEEK_MONTH}))
        self.assertEqual(len(data['templates']), 1)
        self.assertFalse(data['templates'][0]['is_active'])

    def test_manual_and_other_type_not_listed(self):
        template = self.make_template('周月模板')
        self.make_excel_ledger(
            self.make_version(template, 1), status=LEDGER_STATUS_COMPLETED)
        self.make_manual_ledger(status=LEDGER_STATUS_COMPLETED)
        seasonal = self.make_template('季维护模板', ledger_type=LEDGER_TYPE_SEASONAL)
        self.make_excel_ledger(
            self.make_version(seasonal, 1), status=LEDGER_STATUS_COMPLETED)
        data = list_data(self.client.get(EXPORT_URL, {'ledger_type': LEDGER_TYPE_WEEK_MONTH}))
        self.assertEqual([row['template_id'] for row in data['templates']], [template.id])
        seasonal_data = list_data(self.client.get(
            EXPORT_URL, {'ledger_type': LEDGER_TYPE_SEASONAL}))
        self.assertEqual(
            [row['template_id'] for row in seasonal_data['templates']], [seasonal.id])

    def test_cross_tenant_templates_not_listed(self):
        other_template = self.make_template(
            '他租户模板', user=self.other_user)
        self.make_excel_ledger(
            self.make_version(other_template, 1, user=self.other_user),
            status=LEDGER_STATUS_COMPLETED, user=self.other_user)
        data = list_data(self.client.get(EXPORT_URL, {'ledger_type': LEDGER_TYPE_WEEK_MONTH}))
        self.assertEqual(data['templates'], [])

    def test_invalid_ledger_type_rejected(self):
        resp = self.client.get(EXPORT_URL, {'ledger_type': 'unknown'})
        self.assertTrue(resp.json()['error'])

    def test_permission_required(self):
        viewer = make_user('multi_exp_view_%s' % uuid.uuid4().hex[:8], perms=[P_LED_VIEW])
        client = make_client(viewer)
        resp = client.get(EXPORT_URL, {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assertEqual(resp.json()['error'], '权限拒绝')
        resp = post_export(client, {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [1]})
        self.assertEqual(resp.json()['error'], '权限拒绝')


class MultiTemplateExportTests(TemplateGroupTestBase):
    """导出编排：单/多模板、排序、范围、边界与失败（转换打桩）。"""

    def make_ledger_with_period(self, version, period='', status=LEDGER_STATUS_COMPLETED):
        ledger = self.make_excel_ledger(version, status=status)
        if period:
            OperationLedger.objects.filter(pk=ledger.id).update(maintenance_period=period)
        return ledger

    def patch_export(self, fake):
        return mock.patch.object(
            ledger_template_group_services.excel_ledger_services,
            'export_pdf_file', side_effect=fake)

    def assert_file_response(self, response, content_type_prefix):
        if content_type_prefix not in response['Content-Type']:
            self.fail('期望 %s，实际 %s，响应体：%r' % (
                content_type_prefix, response['Content-Type'],
                response.content[:300]))
        self.assertTrue(
            response.content[:5] == b'%PDF-' or response.content[:2] == b'PK',
            '文件魔数不符：%r' % response.content[:8])

    def test_single_template_returns_merged_pdf_ordered_by_period(self):
        template = self.make_template('信道维护台账')
        v1 = self.make_version(template, 1)
        v2 = self.make_version(template, 2)
        late_month = self.make_ledger_with_period(v2, '2026-09')
        week = self.make_ledger_with_period(v1, '2026-09-21')  # 周键起始 09-21 晚于月初
        early_month = self.make_ledger_with_period(v1, '2026-08')
        no_period = self.make_ledger_with_period(v2, '')

        def fake_export(user, ledger):
            # 页尺寸即台账指纹：v1 → 200x300，v2 → 400x500
            if ledger.excel_record.version.version_no == 1:
                return fake_pdf(200, 300)
            return fake_pdf(400, 500)

        with self.patch_export(fake_export) as fake:
            response = post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [template.id]})
        self.assert_file_response(response, 'application/pdf')
        # 期次从早到晚：2026-08 → 2026-09（月初 < 周一 09-21）→ 2026-09；
        # 无期次的排最后按创建顺序（no_period 是最后创建的）
        self.assertEqual(fake.call_args_list[0][0][1].id, early_month.id)
        self.assertEqual(fake.call_args_list[1][0][1].id, late_month.id)
        self.assertEqual(fake.call_args_list[2][0][1].id, week.id)
        self.assertEqual(fake.call_args_list[3][0][1].id, no_period.id)
        self.assertEqual(page_sizes(response.content),
                         [(200, 300), (400, 500), (200, 300), (400, 500)])

    def test_no_period_records_ordered_by_creation(self):
        template = self.make_template('信道维护台账')
        v1 = self.make_version(template, 1)
        first = self.make_ledger_with_period(v1, '')
        second = self.make_ledger_with_period(v1, '')
        with self.patch_export(lambda user, ledger: fake_pdf(100, 100)) as fake:
            post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [template.id]})
        self.assertEqual(
            [call[0][1].id for call in fake.call_args_list], [first.id, second.id])

    def test_multiple_templates_packaged_as_zip_one_pdf_each(self):
        t1 = self.make_template('信道维护台账')
        self.make_ledger_with_period(self.make_version(t1, 1), '2026-08')
        self.make_ledger_with_period(self.make_version(t1, 2), '2026-09')
        t2 = self.make_template('电源巡检台账')
        self.make_ledger_with_period(self.make_version(t2, 1), '2026-08')
        with self.patch_export(lambda user, ledger: fake_pdf(100, 100)):
            response = post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [t1.id, t2.id]})
        self.assert_file_response(response, 'application/zip')
        contents = zip_entry_contents(response.content)
        self.assertEqual(len(contents), 2)
        names = sorted(contents)
        self.assertTrue(names[0].startswith('信道维护台账-批量导出-'))
        self.assertTrue(names[1].startswith('电源巡检台账-批量导出-'))
        for name, content in contents.items():
            self.assertTrue(content.startswith(b'%PDF-'))
        # 模板一台账两条 → 其 PDF 两页；模板二一条 → 一页
        page_counts = {name: len(page_sizes(content))
                       for name, content in contents.items()}
        self.assertEqual(sorted(page_counts.values()), [1, 2])

    def test_same_name_templates_get_distinct_zip_names(self):
        t1 = self.make_template('同名模板')
        t2 = self.make_template('同名模板')
        for template in (t1, t2):
            self.make_ledger_with_period(self.make_version(template, 1), '2026-08')
        with self.patch_export(lambda user, ledger: fake_pdf(100, 100)):
            response = post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [t1.id, t2.id]})
        self.assert_file_response(response, 'application/zip')
        names = zip_entries(response.content)
        self.assertEqual(len(names), 2)
        self.assertEqual(len(set(names)), 2)
        for template_id in (t1.id, t2.id):
            self.assertTrue(any('-%d-' % template_id in name for name in names),
                            names)

    def test_zip_entry_names_sanitized(self):
        template = self.make_template('非法/名称:模板')
        self.make_ledger_with_period(self.make_version(template, 1), '2026-08')
        second = self.make_template('另一模板')
        self.make_ledger_with_period(self.make_version(second, 1), '2026-08')
        with self.patch_export(lambda user, ledger: fake_pdf(100, 100)):
            response = post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                'template_ids': [template.id, second.id]})
        self.assert_file_response(response, 'application/zip')
        for name in zip_entries(response.content):
            self.assertNotIn('/', name)
            self.assertNotIn(':', name)

    def test_default_scope_completed_only_and_explicit_all_widens(self):
        template = self.make_template('信道维护台账')
        v1 = self.make_version(template, 1)
        self.make_ledger_with_period(v1, '2026-08', status=LEDGER_STATUS_COMPLETED)
        self.make_ledger_with_period(v1, '2026-09', status=LEDGER_STATUS_COMPLETED)
        self.make_ledger_with_period(v1, '2026-10', status=LEDGER_STATUS_DRAFT)
        self.make_ledger_with_period(v1, '2026-11', status=LEDGER_STATUS_VOID)
        with self.patch_export(lambda user, ledger: fake_pdf(100, 100)) as fake:
            post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [template.id]})
        self.assertEqual(fake.call_count, 2)  # 默认仅已完成
        with self.patch_export(lambda user, ledger: fake_pdf(100, 100)) as fake:
            post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [template.id],
                'status': 'all'})
        self.assertEqual(fake.call_count, 4)  # 全部（含草稿/已作废）
        with self.patch_export(lambda user, ledger: fake_pdf(100, 100)) as fake:
            post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [template.id],
                'status': 'void'})
        self.assertEqual(fake.call_count, 1)

    def test_list_filters_and_pagination_not_inherited(self):
        template = self.make_template('信道维护台账')
        v1 = self.make_version(template, 1)
        for month in ('2026-08', '2026-09', '2026-10'):
            self.make_ledger_with_period(v1, month)
        # 弹窗范围之外传列表筛选/分页参数（keyword/page）不得影响导出范围：
        # 全部已完成台账参与，不按 keyword 缩小、不按 page_size=1 截取
        with self.patch_export(lambda user, ledger: fake_pdf(100, 100)) as fake:
            post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [template.id],
                'keyword': '不存在的编号', 'page': 1, 'page_size': 1})
        self.assertEqual(fake.call_count, 3)
        data = list_data(self.client.get(EXPORT_URL, {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH}))
        # 候选清单同样不携带 keyword 参数：按类型聚合，数量与导出口径一致
        self.assertEqual(data['templates'][0]['counts']['completed'], 3)

    def test_stopped_template_exportable(self):
        template = self.make_template('退役模板', is_active=False)
        v1 = self.make_version(template, 1)
        self.make_ledger_with_period(v1, '2026-08')
        with self.patch_export(lambda user, ledger: fake_pdf(100, 100)) as fake:
            response = post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [template.id]})
        self.assert_file_response(response, 'application/pdf')
        self.assertEqual(fake.call_count, 1)

    def test_other_type_template_rejected(self):
        template = self.make_template('季维护模板', ledger_type=LEDGER_TYPE_SEASONAL)
        self.make_ledger_with_period(self.make_version(template, 1), '2026-夏秋')
        resp = post_export(self.client, {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [template.id]})
        self.assertEqual(resp.json()['error'], '台账类型与模板不匹配')

    def test_cross_tenant_template_rejected(self):
        template = self.make_template('他租户模板', user=self.other_user)
        self.make_excel_ledger(
            self.make_version(template, 1, user=self.other_user),
            status=LEDGER_STATUS_COMPLETED, user=self.other_user)
        # 租户 A 用户导出租户 B 模板：模板不可见
        resp = post_export(self.client, {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [template.id]})
        self.assertEqual(resp.json()['error'], '模板不存在或无权限访问')

    def test_invalid_template_ids_rejected(self):
        template = self.make_template('信道维护台账')
        self.make_ledger_with_period(self.make_version(template, 1), '2026-08')
        cases = [
            ({'ledger_type': LEDGER_TYPE_WEEK_MONTH}, '请先选择要导出的模板'),
            ({'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': []},
             '请先选择要导出的模板'),
            ({'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': ['abc']},
             '模板选择参数不正确'),
            ({'ledger_type': LEDGER_TYPE_WEEK_MONTH,
              'template_ids': [template.id, template.id]}, '重复项'),
            ({'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [99999999]},
             '模板不存在或无权限访问'),
        ]
        for payload, expected in cases:
            resp = post_export(self.client, payload)
            self.assertIn(expected, resp.json()['error'],
                          '%s -> %s' % (payload, resp.json()))

    def test_zero_exportable_template_rejected_with_name(self):
        template = self.make_template('仅草稿模板')
        self.make_ledger_with_period(
            self.make_version(template, 1), '2026-08', status=LEDGER_STATUS_DRAFT)
        resp = post_export(self.client, {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [template.id]})
        self.assertEqual(
            resp.json()['error'],
            '模板「仅草稿模板」在所选状态范围内没有可导出的台账')

    def test_total_over_limit_rejected(self):
        t1 = self.make_template('模板一')
        t2 = self.make_template('模板二')
        for template in (t1, t2):
            self.make_ledger_with_period(self.make_version(template, 1), '2026-08')
            self.make_ledger_with_period(self.make_version(template, 2), '2026-09')
        with mock.patch.object(ledger_template_group_services,
                               'MAX_BATCH_EXPORT_RECORDS', 3):
            resp = post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                'template_ids': [t1.id, t2.id]})
        error = resp.json()['error']
        self.assertIn('共 4 条', error)
        self.assertIn('超过单次导出上限 3 条', error)

    def test_expected_totals_drift_requires_reconfirm(self):
        template = self.make_template('信道维护台账')
        self.make_ledger_with_period(self.make_version(template, 1), '2026-08')
        self.make_ledger_with_period(self.make_version(template, 2), '2026-09')
        resp = post_export(self.client, {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [template.id],
            'expected_totals': {str(template.id): 5}})
        error = resp.json()['error']
        self.assertIn('与确认时（5 条）不一致', error)
        self.assertIn('重新确认', error)
        # 一致时正常导出
        with self.patch_export(lambda user, ledger: fake_pdf(100, 100)):
            response = post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [template.id],
                'expected_totals': {str(template.id): 2}})
        self.assert_file_response(response, 'application/pdf')

    def test_conversion_failure_aborts_all_without_partial_output(self):
        t1 = self.make_template('甲模板')
        t2 = self.make_template('乙模板')
        ledger_b = self.make_ledger_with_period(self.make_version(t2, 1), '2026-08')
        self.make_ledger_with_period(self.make_version(t1, 1), '2026-08')

        def fake_export(user, ledger):
            if ledger.id == ledger_b.id:
                raise ExcelLedgerError('LibreOffice 转换失败')
            return fake_pdf(100, 100)

        with self.patch_export(fake_export) as fake:
            response = post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                'template_ids': [t1.id, t2.id]})
        body = response.json()
        self.assertIn('模板「乙模板」的台账 %s 生成 PDF 失败' % ledger_b.ledger_no,
                      body['error'])
        # 失败即整体终止：返回 JSON 业务错误，不返回部分 PDF/ZIP
        self.assertIn('application/json', response['Content-Type'])

    def test_status_drift_between_query_and_generate_rejected(self):
        template = self.make_template('信道维护台账')
        v1 = self.make_version(template, 1)
        first = self.make_ledger_with_period(v1, '2026-08')
        second = self.make_ledger_with_period(v1, '2026-09')

        def fake_export(user, ledger):
            if ledger.id == first.id:
                OperationLedger.objects.filter(pk=second.id).update(
                    status=LEDGER_STATUS_VOID)
            return fake_pdf(100, 100)

        with self.patch_export(fake_export) as fake:
            response = post_export(self.client, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'template_ids': [template.id]})
        body = response.json()
        self.assertIn('状态已变化', body['error'])
        self.assertIn(second.ledger_no, body['error'])
        self.assertEqual(fake.call_count, 1)

    def test_export_writes_audit(self):
        template = self.make_template('信道维护台账')
        self.make_ledger_with_period(self.make_version(template, 1), '2026-08')
        self.make_ledger_with_period(self.make_version(template, 2), '2026-09')
        with self.patch_export(lambda user, ledger: fake_pdf(100, 100)):
            with mock.patch('apps.equipment_lifecycle.excel_ledger_views.'
                            'record_audit_event') as audit:
                post_export(self.client, {
                    'ledger_type': LEDGER_TYPE_WEEK_MONTH,
                    'template_ids': [template.id]})
        audit.assert_called_once()
        args, kwargs = audit.call_args
        self.assertEqual(args[1], 'export')
        self.assertEqual(kwargs['after_value']['action_kind'], 'batch_templates_pdf')
        self.assertEqual(kwargs['after_value']['templates'], 1)
        self.assertEqual(kwargs['after_value']['count'], 2)


# v2 打印参数：A3 横向（内容约 20.7cm 宽 → 单页容纳），与 v1 默认 A4 纵向
# 形成可区分的页尺寸指纹；v1 缺省参数 = 样例播种（A4 纵向 fit_width）
A3_LANDSCAPE_PARAMS = {'paper_size': 'A3', 'orientation': 'landscape'}


class MultiTemplateRealConversionTests(ExcelLedgerContractBase):
    """真实转换（LibreOffice 可用时）：ZIP 结构、页数、版本参数与填写内容。

    两个模板（其一含 v1/v2 两个版本的台账）批量导出为 ZIP：每模板一份
    PDF，各台账用创建时版本参数渲染（页尺寸指纹），页数 = 各单条之和，
    填写值真实出现在 PDF 文本中。
    """

    def _publish_version(self, params=None):
        template = self.upload_sample()
        bindings = [self.make_binding('C4', '第1信道-主电台-PS模块')]
        response = self.save_bindings(template['id'], bindings)
        self.assertEqual(response.json().get('error', ''), '')
        if params is not None:
            response = self.owner_client.put(
                '%s/%s/pdf-params/' % (TPL_URL, template['id']),
                json.dumps({'pdf_params': params}),
                content_type='application/json')
            self.assertEqual(response.json().get('error', ''), '')
        version = self.publish(template['id'])
        return template, version, bindings

    def _create_completed_ledger(self, version_id, bindings, period):
        """创建 → 填值 → 完成的台账（带期次标记；默认导出范围不含草稿）。"""
        response = self.owner_client.post(
            LEDGER_URL + '/',
            json.dumps({'version_id': version_id}),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        ledger_id = response.json()['data']['data']['id']
        values = {binding['field_id']: '正常' for binding in bindings}
        response = self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger_id),
            json.dumps({'values': values}), content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        # 期次标记随创建（当前期次），这里直接落库固定值保证排序可断言
        OperationLedger.objects.filter(pk=ledger_id).update(
            maintenance_period=period)
        response = self.owner_client.post(
            '%s/%s/complete/' % (LEDGER_URL, ledger_id))
        self.assertEqual(response.json().get('error', ''), '')
        return ledger_id

    @skipUnless(detect_soffice(), 'LibreOffice 不可用，真实转换用例 NOT_RUN')
    def test_multi_template_zip_pages_versions_and_content(self):
        template_a, v1, bindings = self._publish_version(None)
        self._create_completed_ledger(v1['id'], bindings, '2026-08')
        response = self.owner_client.put(
            '%s/%s/pdf-params/' % (TPL_URL, template_a['id']),
            json.dumps({'pdf_params': A3_LANDSCAPE_PARAMS}),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        v2 = self.publish(template_a['id'])
        self._create_completed_ledger(v2['id'], bindings, '2026-09')
        # 第二个模板改名（upload_sample 上传名固定），避免同名走 ID 去重分支
        template_b, vb, bindings_b = self._publish_version(None)
        OperationLedgerExcelTemplate.objects.filter(pk=template_b['id']).update(
            name='电源巡检台账')
        self._create_completed_ledger(vb['id'], bindings_b, '2026-08')

        response = self.owner_client.post(
            EXPORT_URL, json.dumps({
                'ledger_type': 'week_month',
                'template_ids': [template_a['id'], template_b['id']],
            }), content_type='application/json')
        self.assertIn('application/zip', response['Content-Type'])
        contents = zip_entry_contents(response.content)
        self.assertEqual(len(contents), 2)
        pdf_a = next(content for name, content in contents.items()
                     if name.startswith('信道Excel维护台账'))
        pdf_b = next(content for name, content in contents.items()
                     if name.startswith('电源巡检台账'))
        sizes_a = page_sizes(pdf_a)
        # 样例工作簿两个工作表（记录页 + 结论页），单条台账转换出 2 页；
        # v1 台账（A4 纵向）在前，v2 台账（A3 横向）在后：各版本参数原样保留
        self.assertEqual(len(sizes_a), 4)
        self.assertTrue(all(size_close(size, (595, 842)) for size in sizes_a[:2]))
        self.assertTrue(all(size_close(size, (1191, 842)) for size in sizes_a[2:]))
        # 填写值真实出现在 PDF 文本中（pypdf 文本提取）
        text_a = PdfReader(io.BytesIO(pdf_a)).pages[0].extract_text() or ''
        self.assertIn('正常', text_a)
        # 模板二单条台账 → 2 页 A4 纵向
        sizes_b = page_sizes(pdf_b)
        self.assertEqual(len(sizes_b), 2)
        self.assertTrue(all(size_close(size, (595, 842)) for size in sizes_b))

    @skipUnless(detect_soffice(), 'LibreOffice 不可用，真实转换用例 NOT_RUN')
    def test_single_template_pdf_export(self):
        template, v1, bindings = self._publish_version(None)
        self._create_completed_ledger(v1['id'], bindings, '2026-08')
        response = self.owner_client.post(
            EXPORT_URL, json.dumps({
                'ledger_type': 'week_month', 'template_ids': [template['id']],
            }), content_type='application/json')
        self.assertIn('application/pdf', response['Content-Type'])
        self.assertTrue(response.content.startswith(b'%PDF-'))
        # 样例两工作表 → 单条台账 2 页，均为 A4 纵向（v1 缺省参数）
        sizes = page_sizes(response.content)
        self.assertEqual(len(sizes), 2)
        self.assertTrue(all(size_close(size, (595, 842)) for size in sizes))

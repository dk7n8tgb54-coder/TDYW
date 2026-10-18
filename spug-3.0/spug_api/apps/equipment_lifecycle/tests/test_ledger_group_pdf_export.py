# -*- coding: utf-8 -*-
"""模板组批量 PDF 导出（"导出本模板台账"，2026-10-11）行为测试。

真实执行 HTTP → View → Service → Model 链路（Docker + 隔离测试库）：
- 默认状态范围：仅已完成（草稿/已作废不默认纳入），
  组内状态筛选可显式调整到业务允许的范围（与单条导出一致）；
- 确认与生成同口径：预览（模板名/匹配数/实际日期范围/状态范围/涉及版本）
  与实际导出走同一筛选查询，确认数量与生成条数一致；
- 跨页全量：导出不受分页参数影响，组内全部匹配记录参与，其他模板记录
  不混入（分组按模板主键，不按名称）；
- 版本隔离与合并：每条台账用创建时引用的模板版本生成（单条转换边界
  打桩为可控页尺寸 PDF 验证版本归属），pypdf 真实依序合并，页面尺寸
  原样保留，顺序 = 实际执行日期→台账编号→ID 升序稳定；
- 边界与失败：超过单次上限提示缩小日期范围、任一条生成失败整体失败
  不返回部分 PDF（错误含台账编号）、状态漂移拒绝、manual 组与非法组键
  拒绝、跨租户拒绝、导出权限独立校验、文件名非法字符净化与审计记录；
- 真实转换（LibreOffice 可用时）：不同纸张尺寸/方向的版本合并后各自
  保留，单条 PDF 导出回归哨兵，合并页数 = 各单条页数之和。
"""
import io
import json
import uuid
from urllib.parse import urlencode, unquote
from unittest import mock, skipUnless

from pypdf import PdfReader, PdfWriter

from apps.equipment_lifecycle import ledger_template_group_services
from apps.equipment_lifecycle.excel_ledger_services import ExcelLedgerError
from apps.equipment_lifecycle.excel_pdf_service import detect_soffice
from apps.equipment_lifecycle.models import (
    LEDGER_STATUS_COMPLETED,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_VOID,
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

GROUPS_URL = URL_PREFIX + '/ledgers/template-groups/'


def export_url(group_key):
    return '%s%s/export-pdf/' % (GROUPS_URL, group_key)


def post_export(client, group_key, params=None):
    """导出 POST：筛选参数经 query string 传入（与前端 exportFile 一致）。"""
    query = ('?' + urlencode(params)) if params else ''
    return client.post(export_url(group_key) + query)


def fake_pdf(width, height, pages=1):
    """构造可控页尺寸的最小合法 PDF（pypdf 空白页），验证合并编排与顺序。"""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width, height)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def page_sizes(content):
    """合并 PDF 的页尺寸序列（pt，四舍五入）。"""
    reader = PdfReader(io.BytesIO(content))
    return [(round(float(page.mediabox.width)), round(float(page.mediabox.height)))
            for page in reader.pages]


def size_close(size, expected, tolerance=2):
    """LibreOffice 产出的页尺寸与期望值近似相等（±2pt）。"""
    return all(abs(a - b) <= tolerance for a, b in zip(size, expected))


def ok_data(resp):
    body = resp.json()
    assert not body.get('error'), body
    return body['data']


def preview_payload(resp):
    """预览响应业务载荷：视图 json_response({'data': {...}}) 双层解包。"""
    return ok_data(resp)['data']


class GroupPdfExportPreviewTests(TemplateGroupTestBase):
    """确认数据口径：默认状态范围/实际日期范围/涉及版本/空与拒绝。"""

    def _seed_group(self):
        template = self.make_template('信道维护台账')
        v1 = self.make_version(template, 1)
        v2 = self.make_version(template, 2)
        self.make_excel_ledger(v1, '2026-10-01', status=LEDGER_STATUS_COMPLETED)
        self.make_excel_ledger(v2, '2026-10-05', status=LEDGER_STATUS_COMPLETED)
        self.make_excel_ledger(v2, '2026-10-08', status=LEDGER_STATUS_COMPLETED)
        self.make_excel_ledger(v1, '2026-10-03', status=LEDGER_STATUS_DRAFT)
        self.make_excel_ledger(v1, '2026-10-02', status=LEDGER_STATUS_VOID)
        return template

    def test_preview_default_scope_excludes_draft_and_void(self):
        template = self._seed_group()
        body = preview_payload(self.client.get(
            export_url(template.id), {'ledger_type': LEDGER_TYPE_WEEK_MONTH}))
        self.assertEqual(body['template_name'], '信道维护台账')
        self.assertEqual(body['total'], 3)
        self.assertEqual(body['status_scope'], ['completed'])
        self.assertEqual(str(body['executed_from']), '2026-10-01')
        self.assertEqual(str(body['executed_to']), '2026-10-08')
        self.assertEqual(body['versions'], [
            {'version_no': 1, 'count': 1}, {'version_no': 2, 'count': 2}])
        self.assertEqual(body['max_records'],
                         ledger_template_group_services.MAX_BATCH_EXPORT_RECORDS)

    def test_preview_explicit_status_narrows_scope(self):
        template = self._seed_group()
        body = preview_payload(self.client.get(export_url(template.id), {
            'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'status': 'draft'}))
        self.assertEqual(body['total'], 1)
        self.assertEqual(body['status_scope'], ['draft'])

    def test_empty_matches_preview_zero_and_export_rejected(self):
        template = self._seed_group()
        params = {'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'keyword': '无此编号'}
        self.assertEqual(preview_payload(self.client.get(
            export_url(template.id), params))['total'], 0)
        resp = post_export(self.client, template.id, params)
        self.assertEqual(resp.json()['error'], '没有符合条件的台账，请调整筛选条件后重试')

    def test_manual_group_rejected(self):
        self.make_manual_ledger()
        for method in (self.client.get, self.client.post):
            resp = method(export_url('manual'),
                          {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
            self.assertIn('不支持批量 PDF 导出', resp.json()['error'])

    def test_invalid_group_key_rejected(self):
        for key in ('abc', '999999'):
            resp = self.client.get(export_url(key),
                                   {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
            self.assertEqual(resp.json()['error'], '模板不存在或无权限访问')


class GroupPdfExportGenerationTests(TemplateGroupTestBase):
    """生成与合并：pypdf 真实合并编排（单条转换边界打桩为可控页尺寸 PDF）。"""

    def assert_export_ok(self, response):
        """成功导出 = PDF 二进制响应（不是 JSON，先于任何 .json() 判定）。"""
        self.assertIn('application/pdf', response['Content-Type'])
        self.assertTrue(response.content.startswith(b'%PDF-'))
        return response

    def _patch_export(self, fake):
        return mock.patch.object(
            ledger_template_group_services.excel_ledger_services,
            'export_pdf_file', side_effect=fake)

    def _seed(self, count=3, dates=('2026-10-01', '2026-10-05', '2026-10-08')):
        template = self.make_template('信道维护台账')
        v1 = self.make_version(template, 1)
        v2 = self.make_version(template, 2)
        ledgers = []
        for index in range(count):
            version = v1 if index == 0 else v2
            status = LEDGER_STATUS_COMPLETED
            ledgers.append(self.make_excel_ledger(
                version, dates[index], status=status))
        return template, v1, v2, ledgers

    def test_merges_versions_in_stable_order_keeping_page_sizes(self):
        template, v1, v2, ledgers = self._seed()

        def fake_export(user, ledger):
            # v1 台账 1 页 200x300，v2 台账 2 页 400x500：页尺寸即版本指纹
            if ledger.excel_record.version.version_no == 1:
                return fake_pdf(200, 300)
            return fake_pdf(400, 500, pages=2)

        with self._patch_export(fake_export) as fake:
            response = post_export(self.client, template.id,
                                   {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assert_export_ok(response)
        # 合并页数 = 各单条之和，页尺寸依原序保留（v1 一页在前，v2 两条各两页）
        self.assertEqual(page_sizes(response.content), [
            (200, 300), (400, 500), (400, 500), (400, 500), (400, 500)])
        self.assertEqual(fake.call_count, 3)
        # 生成顺序 = 实际执行日期升序（稳定排序）
        generated = [call[0][1].id for call in fake.call_args_list]
        self.assertEqual(generated, [ledger.id for ledger in ledgers])

    def test_preview_count_matches_generated_count(self):
        template, _, _, _ = self._seed()
        params = {'ledger_type': LEDGER_TYPE_WEEK_MONTH}
        self.assertEqual(preview_payload(self.client.get(
            export_url(template.id), params))['total'], 3)
        with self._patch_export(lambda user, ledger: fake_pdf(100, 100)):
            response = post_export(self.client, template.id, params)
        self.assert_export_ok(response)
        self.assertEqual(len(page_sizes(response.content)), 3)

    def test_export_ignores_pagination_includes_all_pages_of_matches(self):
        template, _, _, ledgers = self._seed()
        with self._patch_export(lambda user, ledger: fake_pdf(100, 100)) as fake:
            response = post_export(self.client, template.id, {
                'ledger_type': LEDGER_TYPE_WEEK_MONTH, 'page': 1, 'page_size': 1})
        self.assert_export_ok(response)
        # 当前筛选下全部 3 条导出（其他分页上的匹配记录不遗漏）
        self.assertEqual(len(page_sizes(response.content)), 3)
        self.assertEqual(fake.call_count, 3)

    def test_other_template_records_not_included(self):
        t1 = self.make_template('模板一')
        self.make_excel_ledger(self.make_version(t1, 1), '2026-10-01',
                               status=LEDGER_STATUS_COMPLETED)
        self.make_excel_ledger(self.make_version(t1, 2), '2026-10-05',
                               status=LEDGER_STATUS_COMPLETED)
        t2 = self.make_template('模板二')
        self.make_excel_ledger(self.make_version(t2, 1), '2026-10-06',
                               status=LEDGER_STATUS_COMPLETED)

        def fake_export(user, ledger):
            return fake_pdf(100, 100)

        with self._patch_export(fake_export):
            response = post_export(self.client, t1.id,
                                   {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assert_export_ok(response)
        # 仅模板一的两条参与（按模板主键分组，同名/其他模板不混入）
        self.assertEqual(len(page_sizes(response.content)), 2)

    def test_oversize_rejected_with_narrow_range_hint(self):
        template, _, _, _ = self._seed()
        with mock.patch.object(ledger_template_group_services,
                               'MAX_BATCH_EXPORT_RECORDS', 2):
            response = post_export(self.client, template.id,
                                   {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        error = response.json()['error']
        self.assertIn('超过单次导出上限 2 条', error)
        self.assertIn('缩小日期范围', error)

    def test_status_drift_between_query_and_generate_rejected(self):
        template, _, _, ledgers = self._seed()

        def fake_export(user, ledger):
            if ledger.id == ledgers[0].id:
                # 第一条生成后、第二条复核前：状态漂移为已作废
                OperationLedger.objects.filter(
                    pk=ledgers[1].id).update(status=LEDGER_STATUS_VOID)
            return fake_pdf(100, 100)

        with self._patch_export(fake_export) as fake:
            response = post_export(self.client, template.id,
                                   {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        body = response.json()
        self.assertIn('状态已变化', body['error'])
        self.assertIn(ledgers[1].ledger_no, body['error'])
        self.assertEqual(fake.call_count, 1)

    def test_one_record_failure_aborts_without_partial_pdf(self):
        template, _, _, ledgers = self._seed()

        def fake_export(user, ledger):
            if ledger.id == ledgers[1].id:
                raise ExcelLedgerError('LibreOffice 转换失败')
            return fake_pdf(100, 100)

        with self._patch_export(fake_export) as fake:
            response = post_export(self.client, template.id,
                                   {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        body = response.json()
        self.assertEqual(body['error'],
                         '台账 %s 生成 PDF 失败：LibreOffice 转换失败' % ledgers[1].ledger_no)
        # 失败即终止：第三条不再生成，不返回部分合并 PDF
        self.assertEqual(fake.call_count, 2)
        self.assertNotIn('application/pdf', response['Content-Type'])

    def test_filename_includes_template_name_and_date_sanitized(self):
        template = self.make_template('非法/名称:模板')
        self.make_excel_ledger(self.make_version(template, 1), '2026-10-01',
                               status=LEDGER_STATUS_COMPLETED)
        with self._patch_export(lambda user, ledger: fake_pdf(100, 100)):
            response = post_export(self.client, template.id,
                                   {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assert_export_ok(response)
        disposition = response['Content-Disposition']
        filename = unquote(disposition.split("''", 1)[1])
        self.assertTrue(filename.startswith('非法名称模板-批量导出-'))
        self.assertNotIn('/', filename)
        self.assertNotIn(':', filename)

    def test_export_writes_audit_without_fill_values(self):
        template, _, _, _ = self._seed()
        with self._patch_export(lambda user, ledger: fake_pdf(100, 100)):
            with mock.patch('apps.equipment_lifecycle.excel_ledger_views.'
                            'record_audit_event') as audit:
                response = post_export(self.client, template.id,
                                       {'ledger_type': LEDGER_TYPE_WEEK_MONTH})
        self.assert_export_ok(response)
        audit.assert_called_once()
        args, kwargs = audit.call_args
        self.assertEqual(args[1], 'export')
        self.assertEqual(kwargs['after_value']['count'], 3)
        self.assertEqual(kwargs['after_value']['group_key'], str(template.id))

    def test_cross_tenant_rejected(self):
        template, _, _, _ = self._seed()
        params = {'ledger_type': LEDGER_TYPE_WEEK_MONTH}
        resp = self.other_client.get(export_url(template.id), params)
        self.assertEqual(resp.json()['error'], '模板不存在或无权限访问')
        resp = post_export(self.other_client, template.id, params)
        self.assertEqual(resp.json()['error'], '模板不存在或无权限访问')

    def test_export_permission_required(self):
        template, _, _, _ = self._seed()
        viewer = make_user('group_pdf_view_%s' % uuid.uuid4().hex[:8],
                           perms=[P_LED_VIEW])
        client = make_client(viewer)
        params = {'ledger_type': LEDGER_TYPE_WEEK_MONTH}
        resp = client.get(export_url(template.id), params)
        self.assertEqual(resp.json()['error'], '权限拒绝')
        resp = post_export(client, template.id, params)
        self.assertEqual(resp.json()['error'], '权限拒绝')


# v2 打印参数：A3 横向（内容约 20.7cm 宽 → 单页容纳），与 v1 默认 A4 纵向
# 形成可区分的页尺寸指纹；v1 缺省参数 = 样例播种（A4 纵向 fit_width）
A3_LANDSCAPE_PARAMS = {'paper_size': 'A3', 'orientation': 'landscape'}


class GroupPdfRealConversionTests(ExcelLedgerContractBase):
    """真实转换（LibreOffice 可用时）：版本参数隔离 + 页面原样保留。

    单条 PDF 导出回归哨兵 + 合并页数守恒 + 各版本纸张尺寸/方向保留，
    一次用例内完成（LibreOffice 转换较慢，减少用例数量）。
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

    def _create_completed_ledger(self, version_id, bindings, executed_date):
        """创建并完成填写台账：批量导出默认状态范围不含草稿，须经真实完成端点。"""
        response = self.owner_client.post(
            LEDGER_URL + '/',
            json.dumps({'version_id': version_id, 'executed_date': executed_date}),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        ledger_id = response.json()['data']['data']['id']
        values = {binding['field_id']: '正常' for binding in bindings}
        response = self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger_id),
            json.dumps({'values': values}), content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        response = self.owner_client.post(
            '%s/%s/complete/' % (LEDGER_URL, ledger_id))
        self.assertEqual(response.json().get('error', ''), '')
        return ledger_id

    @skipUnless(detect_soffice(), 'LibreOffice 不可用，真实转换用例 NOT_RUN')
    def test_batch_keeps_versions_page_setup_and_single_export_regression(self):
        template, v1, bindings = self._publish_version(None)
        ledger_a = self._create_completed_ledger(v1['id'], bindings, '2026-10-01')
        # v2：A3 横向（v1 台账固定使用 v1 快照的 A4 纵向缺省参数）
        response = self.owner_client.put(
            '%s/%s/pdf-params/' % (TPL_URL, template['id']),
            json.dumps({'pdf_params': A3_LANDSCAPE_PARAMS}),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        v2 = self.publish(template['id'])
        ledger_b = self._create_completed_ledger(v2['id'], bindings, '2026-10-05')

        # 单条导出回归哨兵：仍走既有端点，各用创建时版本参数
        single_a = self.owner_client.post(
            '%s/%s/export/pdf/' % (LEDGER_URL, ledger_a))
        self.assertIn('application/pdf', single_a['Content-Type'])
        single_b = self.owner_client.post(
            '%s/%s/export/pdf/' % (LEDGER_URL, ledger_b))
        self.assertIn('application/pdf', single_b['Content-Type'])
        sizes_a = page_sizes(single_a.content)
        sizes_b = page_sizes(single_b.content)
        self.assertTrue(all(size_close(size, (595, 842)) for size in sizes_a))  # v1：A4 纵向
        self.assertTrue(all(size_close(size, (1191, 842)) for size in sizes_b))  # v2：A3 横向

        # 批量导出：同模板不同版本依创建时版本合并，页数 = 各单条之和
        response = post_export(self.owner_client, template['id'],
                               {'ledger_type': 'week_month'})
        self.assertIn('application/pdf', response['Content-Type'])
        self.assertTrue(response.content.startswith(b'%PDF-'))
        merged_sizes = page_sizes(response.content)
        self.assertEqual(merged_sizes, sizes_a + sizes_b)
        # 顺序 = 实际执行日期升序：2026-10-01 的 A4 页在前
        self.assertTrue(size_close(merged_sizes[0], (595, 842)))

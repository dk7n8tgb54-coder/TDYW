# -*- coding: utf-8 -*-
"""数字表单路线周期生成与模板分组行为测试（2026-10-21）。

真实 HTTP/服务路径，覆盖：
- 生成预览/确认：数字表单模板与 Excel 模板同槽位口径（template_kind 区分、
  行键 kind+id 防跨表撞号）、去重唯一约束（重复生成 skipped）、模板行锁；
- 期次语义复用：周从周一计算（周一期次键）、月期次 YYYY-MM、航季；
- 补建：作废占用的槽位按路线补建；手工壳对两条路线同时占位（需人工处理）；
- 概览（period-overview）计入数字表单模板槽位；
- "按模板查看"：数字表单组 group_key='form:<id>'、组内列表、翻阅/批量
  PDF 导出对数字表单组显式拒绝；数字表单台账不出现在 Excel 导出清单。
"""
import json
import tempfile
from datetime import datetime
from unittest import mock

from django.test import TestCase, override_settings

from apps.equipment_lifecycle import ledger_period_services, ledger_services
from apps.equipment_lifecycle.models import (
    LEDGER_STATUS_VOID,
    OperationLedger,
)
from apps.equipment_lifecycle.tests.base import (
    make_client, make_system, make_user, URL_PREFIX,
)
from apps.equipment_lifecycle.tests.test_form_ledger_route import (
    FormRouteTestBase,
)

def fake_today(year, month, day):
    """把生成口径的"今天"固定为指定日期（service 内 timezone.now）。"""
    return mock.patch.object(
        ledger_period_services.timezone, 'now',
        return_value=datetime(year, month, day, 10, 0, 0))


GEN_URL = URL_PREFIX + '/ledgers/period-generate'
REBUILD_URL = GEN_URL + '/rebuild/'
OVERVIEW_URL = URL_PREFIX + '/ledgers/period-overview/'
GROUPS_URL = URL_PREFIX + '/ledgers/template-groups'

# 跨路线用例会真实发布 Excel 模板：每次测试进程使用独立临时目录，避免
# 测试库重建后模板 ID 归小号撞上媒体目录残留版本文件（哈希不同即冲突）
STORAGE_DIR = tempfile.mkdtemp(prefix='el_form_period_generate_')


class FormPeriodGenerateTests(FormRouteTestBase):
    """数字表单模板并入本期应填台账生成（与 Excel 同槽位口径）。"""

    def setUp(self):
        self._storage_override = override_settings(
            EL_EXCEL_TEMPLATE_BASE_DIR=STORAGE_DIR)
        self._storage_override.enable()
        self.addCleanup(self._storage_override.disable)

    def _publish_form_template(self, name='周维护数字表单', ledger_type='week_month',
                               **config):
        template, version = self.create_published_version(
            ledger_type=ledger_type,
            name=name)
        body = {'system': self.system.id}
        body.update(config)
        response = self.owner_client.put(
            '%s/%s/generation-config/' % (URL_PREFIX + '/form-templates',
                                          template['id']),
            json.dumps(body), content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        return template, version

    def test_preview_and_generate_form_template(self):
        template, version = self._publish_form_template(generation_period='weekly')
        with fake_today(2026, 10, 21):
            result, error = ledger_period_services.period_generate_preview(
                self.owner, 'week_month', ['weekly'])
            self.assertIsNone(error)
            entries = result['entries']
            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertEqual(entry['template_kind'], 'form')
            self.assertEqual(entry['template_id'], template['id'])
            self.assertEqual(entry['status'], 'create')
            # 周期键 = 本周周一（2026-10-21 是周三 → 周一 2026-10-19）
            self.assertEqual(entry['maintenance_period'], '2026-10-19')
            # 确认生成：template_ids + template_kinds 平行数组
            result, error = ledger_period_services.period_generate(
                self.owner, 'week_month', ['weekly'], [template['id']], ['form'])
            self.assertIsNone(error)
            self.assertEqual(len(result['created']), 1)
            row = result['created'][0]
            self.assertEqual(row['template_kind'], 'form')
            ledger = OperationLedger.objects.get(pk=row['id'])
            self.assertEqual(ledger.created_from, 'form_template')
            self.assertEqual(ledger.maintenance_period, '2026-10-19')
            self.assertEqual(ledger.form_record.version_id, version['id'])
            self.assertEqual(ledger.form_record.get_values(), {})
            # 重复生成去重（槽位唯一约束 + 判定 skipped）
            result, error = ledger_period_services.period_generate(
                self.owner, 'week_month', ['weekly'], [template['id']], ['form'])
            self.assertIsNone(error)
            self.assertEqual(len(result['created']), 0)
            self.assertEqual(len(result['skipped']), 1)

    def test_kind_ids_prevent_cross_route_collision(self):
        """Excel 与数字表单模板并存时按 kind 正确分桶，互不串数据。

        两条路线的模板主键分属不同表、可能撞号：生成一次后再次预览，两条
        路线的槽位必须各自命中自己的台账（均判定 exists）——若分桶丢失
        kind，撞号主键会读到对方路线的台账而误判。
        """
        import io
        import uuid
        from django.core.files.uploadedfile import SimpleUploadedFile
        from openpyxl import Workbook
        from apps.equipment_lifecycle.excel_template_manage import (
            create_template as create_excel_template,
            save_bindings, publish_version as publish_excel,
        )

        buffer = io.BytesIO()
        workbook = Workbook()
        sheet = workbook.active
        sheet['A1'] = '项目'
        sheet['A2'] = '填写项一'
        sheet['A3'] = ''
        excel_bytes = io.BytesIO()
        workbook.save(excel_bytes)
        upload = SimpleUploadedFile('excel_tpl.xlsx', excel_bytes.getvalue())
        excel_tpl = create_excel_template(self.owner, 'excel_tpl.xlsx', upload.read(), {
            'name': '同号Excel模板', 'ledger_type': 'week_month',
            'description': '', 'system': self.system.id,
            'generation_period': 'weekly'})
        save_bindings(self.owner, excel_tpl, [
            {'sheet_name': sheet.title, 'cell_coordinate': 'A3',
             'field_id': str(uuid.uuid4()),
             'field_name': '填写项一', 'input_type': 'text',
             'is_required': False, 'unit': '', 'options': []}])
        publish_excel(self.owner, excel_tpl)
        form_tpl, _ = self._publish_form_template(
            name='同号数字表单模板', generation_period='weekly')

        with fake_today(2026, 10, 21):
            result, error = ledger_period_services.period_generate(
                self.owner, 'week_month', ['weekly'],
                [excel_tpl.id, form_tpl['id']], ['excel', 'form'])
            self.assertIsNone(error)
            self.assertEqual(
                len(result['created']), 2,
                '实际结果：%s' % json.dumps(
                    {'created': result['created'], 'skipped': result['skipped'],
                     'failed': result['failed']}, default=str, ensure_ascii=False))
            kinds = sorted(row['template_kind'] for row in result['created'])
            self.assertEqual(kinds, ['excel', 'form'])
            # 再次预览：两条路线各自命中自己的台账（kind 分桶正确）
            preview, error = ledger_period_services.period_generate_preview(
                self.owner, 'week_month', ['weekly'])
            self.assertIsNone(error)
            by_kind = {entry['template_kind']: entry
                       for entry in preview['entries']}
            self.assertEqual(by_kind['excel']['template_name'], '同号Excel模板')
            self.assertEqual(by_kind['form']['template_name'], '同号数字表单模板')
            self.assertEqual(by_kind['excel']['status'], 'exists')
            self.assertEqual(by_kind['form']['status'], 'exists')

    def test_seasonal_form_template_enters_seasonal_list(self):
        """季维护数字表单模板按航季期次生成，进入季维护列表。"""
        template, version = self._publish_form_template(
            name='季维护数字表单', ledger_type='seasonal',
            generation_period='seasonal')
        with fake_today(2026, 11, 5):
            result, error = ledger_period_services.period_generate(
                self.owner, 'seasonal', ['seasonal'], [template['id']], ['form'])
            self.assertIsNone(error)
            self.assertEqual(len(result['created']), 1)
            ledger = OperationLedger.objects.get(pk=result['created'][0]['id'])
            self.assertEqual(ledger.ledger_type, 'seasonal')
            self.assertIn('冬春', ledger.maintenance_period)
        # 统一列表按类型筛选落在季维护
        rows = self.owner_client.get(
            URL_PREFIX + '/ledgers/?ledger_type=seasonal').json()['data']['data']
        self.assertTrue(any(item['id'] == ledger.id for item in rows))

    def test_rebuild_after_void_for_form_template(self):
        template, version = self._publish_form_template(generation_period='weekly')
        with fake_today(2026, 10, 21):
            result, error = ledger_period_services.period_generate(
                self.owner, 'week_month', ['weekly'], [template['id']], ['form'])
            ledger_id = result['created'][0]['id']
            # 作废后自动生成不再重建（manual_needed），补建显式重建
            ledger_services.void_ledger(self.owner, ledger_id, '填错了')
            result, error = ledger_period_services.period_generate(
                self.owner, 'week_month', ['weekly'], [template['id']], ['form'])
            self.assertEqual(result['failed'][0]['status'], 'manual_needed')
            row, error = ledger_period_services.period_generate_rebuild(
                self.owner, template['id'], 'form')
            self.assertIsNone(error)
            self.assertEqual(row['template_kind'], 'form')
            self.assertNotEqual(row['id'], ledger_id)
            self.assertTrue(OperationLedger.objects.filter(
                pk=ledger_id, status=LEDGER_STATUS_VOID).exists())

    def test_manual_shell_blocks_both_routes(self):
        """历史手工壳（无路线模板）对两条路线的本期槽位同时占位。"""
        template, version = self._publish_form_template(generation_period='weekly')
        from apps.equipment_lifecycle.models import LEDGER_TYPE_WEEK_MONTH
        ledger = OperationLedger.objects.create(
            tenant_id=self.owner.tenant_id,
            ledger_no='EL-WM-20261019-9901',
            ledger_type=LEDGER_TYPE_WEEK_MONTH,
            status='draft',
            entry_channel='web',
            created_from='manual',
            system=self.system,
            maintenance_period='2026-10-19',
            created_by=self.owner,
        )
        with fake_today(2026, 10, 21):
            result, error = ledger_period_services.period_generate_preview(
                self.owner, 'week_month', ['weekly'])
            entry = result['entries'][0]
            self.assertEqual(entry['status'], 'manual_needed')
            self.assertIn('历史草稿台账', entry['reason'])

    def test_period_overview_counts_form_slots(self):
        template, version = self._publish_form_template(generation_period='weekly')
        with fake_today(2026, 10, 21):
            overview, error = ledger_period_services.period_overview(
                self.owner, 'week_month')
            self.assertIsNone(error)
            week_block = next(
                block for block in overview['blocks'] if block['key'] == 'week')
            self.assertGreaterEqual(week_block['to_generate'], 1)
            self.assertGreaterEqual(week_block['expected'], 1)


class FormTemplateGroupTests(FormRouteTestBase):
    """"按模板查看"的数字表单组：组键 form:<id> 与边界拒绝。"""

    def _create_form_ledger(self, ledger_type='week_month'):
        template, version = self.create_published_version(ledger_type=ledger_type)
        ledger = self.owner_client.post(
            URL_PREFIX + '/form-ledgers/', json.dumps({'version_id': version['id']}),
            content_type='application/json').json()['data']
        return template, version, ledger

    def test_form_group_key_and_group_ledgers(self):
        template, version, ledger = self._create_form_ledger()
        groups = self.owner_client.get(
            GROUPS_URL + '/?ledger_type=week_month').json()['data']['data']
        form_groups = [g for g in groups if g['source_type'] == 'form']
        self.assertEqual(len(form_groups), 1)
        group = form_groups[0]
        self.assertEqual(group['group_key'], 'form:%s' % template['id'])
        self.assertEqual(group['template_name'], template['name'])
        self.assertEqual(group['total'], 1)
        # 组内列表：行结构与统一列表一致且带来源版本
        data = self.owner_client.get(
            '%s/%s/ledgers/?ledger_type=week_month' % (
                GROUPS_URL, group['group_key'])).json()['data']
        self.assertEqual(data['group_name'], template['name'])
        self.assertEqual(len(data['data']), 1)
        row = data['data'][0]
        self.assertEqual(row['source_type'], 'form')
        self.assertEqual(row['source_version_no'], 1)
        # 跨租户组键拒绝
        response = self.other_client.get(
            '%s/%s/ledgers/' % (GROUPS_URL, group['group_key']))
        self.assertIn('不存在', response.json()['error'])

    def test_browse_and_export_rejected_for_form_group(self):
        template, version, ledger = self._create_form_ledger()
        group_key = 'form:%s' % template['id']
        response = self.owner_client.get(
            '%s/%s/browse/' % (GROUPS_URL, group_key))
        self.assertIn('暂不支持翻阅', response.json()['error'])
        response = self.owner_client.get(
            '%s/%s/export-pdf/' % (GROUPS_URL, group_key))
        self.assertIn('暂不支持批量 PDF 导出', response.json()['error'])

    def test_form_ledger_not_in_excel_export_candidates(self):
        """数字表单台账不进入"批量导出 PDF"候选（Excel 版式专属）。"""
        self._create_form_ledger()
        data = self.owner_client.get(
            URL_PREFIX + '/ledgers/export-pdf/?ledger_type=week_month'
        ).json()['data']['data']
        self.assertEqual(data['templates'], [])

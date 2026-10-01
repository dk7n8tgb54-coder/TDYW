# -*- coding: utf-8 -*-
"""Excel 上传版维护台账试点稳定契约：模板发布 + 台账全链路（2026-09-28）。

覆盖任务书验收项（真实 HTTP 路径 URL→View→Service→Model）：
1. 样例 .xlsx 上传解析（双工作表/合并/打印设置），源文件哈希落库；
2. 不支持的文件特性（公式/图表）显式拒绝，绝不静默导入成功；
3. 字段绑定校验（合并锚点/已有内容/重复绑定/非法类型）与落库；
4. 发布级校验与不可变版本（版本写路径 405）；
5. 再次发布产生新版本，旧版本内容不变；
6. 台账创建（周月/季类型边界校验/停用模板拒绝/client_token 幂等）；
7. 填写值保存与类型校验、提交必填校验与状态机；
8. 历史台账固定引用创建时版本：模板发布 v2 后旧台账详情与导出仍走 v1；
9. Excel 导出为版本源文件填充结果（合并保留、单元格含填写值），
   PDF 导出为真实 LibreOffice 转换（环境缺失显式 NOT_RUN），LibreOffice
   不可用时导出返回业务错误；
10. 正式台账列表统一返回 Excel 路线台账（2026-10：source_type 区分来源，
    详情按 created_from 分支；契约细节见 test_ledger_unified_excel.py），
    Excel 独立列表保留互不干扰；
11. 跨租户访问统一按不存在拒绝；
12. 绑定协议收敛（2026-09-29）：default_value/operation_guide/
    abnormal_rule/maintenance_cycles 退役，新保存的绑定不落库、发布
    不依赖，历史草稿/版本快照仍可读取、填写与导出；
13. 批量绑定：多格一次性保存生成独立 UUID 与「前缀-坐标」稳定命名，
    整体原子校验（重复格/合并锚点/数量上限）；
14. 模板删除（2026-09-29）：逻辑删除（is_active=False）幂等，del 权限
    独立校验，跨租户统一"模板不存在或无权限访问"；删除后可用模板接口
    不再返回、新台账拒绝使用、编辑/重传/发布入口拦截；历史版本、填写
    记录与历史台账保留，仍可查看与导出。
15. 草稿 PDF 预览（2026-09-29）：preview/pdf 返回真实 LibreOffice 转换
    结果、只读不改草稿/不建版本、LO 缺失业务错误、跨租户拒绝、残留空
    打印区域不产生空白 PDF；
16. 兼容性检查（2026-09-29）：模板详情返回 status/warnings/unsupported
    （文件缺失/哈希不一致/不支持特性=error；LO 缺失/空打印区域=warning）；
17. 布局元数据（2026-09-29）：边框/填充/字体（下划线/删除线）/行高
    列宽/隐藏行列/打印方向在上传解析时捕获并落库。
"""
import io
import json
import os
import shutil
import tempfile
import uuid
from unittest import mock, skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Border, Side
from openpyxl.utils import get_column_letter

from apps.equipment_lifecycle.excel_pdf_service import detect_soffice
from apps.equipment_lifecycle.excel_sample_template import build_acceptance_sample_xlsx
from apps.equipment_lifecycle.models import OperationLedger
from apps.equipment_lifecycle.tests.base import URL_PREFIX, make_client, make_user

TPL_URL = URL_PREFIX + '/excel-templates'
LEDGER_URL = URL_PREFIX + '/excel-ledgers'

P_TPL = ['equipment_lifecycle.ledger_template.view',
         'equipment_lifecycle.ledger_template.add',
         'equipment_lifecycle.ledger_template.edit']
P_LEDGER = ['equipment_lifecycle.ledger.view', 'equipment_lifecycle.ledger.add',
            'equipment_lifecycle.ledger.edit', 'equipment_lifecycle.ledger.submit',
            'equipment_lifecycle.ledger.export']

SHEET_MAIN = '信道维护记录'
SHEET_SUMMARY = '维护结论'


def _override_storage():
    storage_dir = tempfile.mkdtemp(prefix='el_excel_tpl_test_')
    override = override_settings(EL_EXCEL_TEMPLATE_BASE_DIR=storage_dir)
    return storage_dir, override


class ExcelLedgerContractBase(TestCase):
    """存储隔离 + 双用户夹具（owner 租户内操作，other 跨租户访问）。"""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user('excel_owner_%s' % uuid.uuid4().hex[:8], perms=P_TPL + P_LEDGER)
        cls.other = make_user('excel_other_%s' % uuid.uuid4().hex[:8], perms=P_TPL + P_LEDGER,
                              tenant_id='another')
        cls.owner_client = make_client(cls.owner)
        cls.other_client = make_client(cls.other)

    def setUp(self):
        self._storage_dir, self._override = _override_storage()
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(shutil.rmtree, self._storage_dir, ignore_errors=True)
        super().setUp()

    def upload_sample(self, client=None, name='信道维护台账验收样例.xlsx'):
        client = client or self.owner_client
        response = client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile(name, build_acceptance_sample_xlsx()),
            'name': '信道Excel维护台账',
            'ledger_type': 'week_month',
            'description': '试点验收模板',
        })
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        return payload['data']['data']

    def save_bindings(self, template_id, bindings, client=None):
        client = client or self.owner_client
        return client.put('%s/%s/bindings/' % (TPL_URL, template_id),
                          json.dumps({'field_bindings': bindings}),
                          content_type='application/json')

    def publish(self, template_id, client=None):
        client = client or self.owner_client
        response = client.post('%s/%s/publish/' % (TPL_URL, template_id))
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        return payload['data']['data']

    def make_binding(self, coordinate, field_name, sheet=SHEET_MAIN, **kwargs):
        """新协议绑定对象（八键）；历史属性不再由夹具生成。"""
        binding = {
            'field_id': str(uuid.uuid4()),
            'sheet_name': sheet,
            'cell_coordinate': coordinate,
            'field_name': field_name,
            'input_type': kwargs.get('input_type', 'status'),
            'is_required': kwargs.get('is_required', True),
            'unit': kwargs.get('unit', ''),
            'options': kwargs.get('options', []),
        }
        return binding

    def create_published_version(self, client=None, ledger_type='week_month', **kwargs):
        """直达夹具：上传 → 绑定 3 字段 → 发布，返回 (template, version)。"""
        client = client or self.owner_client
        response = client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('channel.xlsx', build_acceptance_sample_xlsx()),
            'name': kwargs.get('name', '信道Excel维护台账'),
            'ledger_type': ledger_type,
        })
        template = response.json()['data']['data']
        bindings = [
            self.make_binding('C4', '第1信道-主电台-PS模块'),
            self.make_binding('D4', '第1信道-主电台-TX模块'),
            self.make_binding('H4', '第1信道-主电台-备注', input_type='text',
                              is_required=False),
        ]
        response = self.save_bindings(template['id'], bindings, client=client)
        self.assertEqual(response.json().get('error', ''), '')
        version = self.publish(template['id'], client=client)
        return template, version, bindings


class UploadParseTests(ExcelLedgerContractBase):
    """上传解析与不支持特性显式拒绝。"""

    def test_upload_parses_two_sheets_with_hash(self):
        template = self.upload_sample()
        draft = template['draft']
        self.assertEqual(template['ledger_type'], 'week_month')
        self.assertEqual(draft['sheet_name'], SHEET_MAIN)
        sheet_names = [s['name'] for s in draft['layout']['sheets']]
        self.assertEqual(sheet_names, [SHEET_MAIN, SHEET_SUMMARY])
        main_sheet = draft['layout']['sheets'][0]
        self.assertIn('A3:A4', main_sheet['merged_ranges'])
        self.assertEqual(len(template['draft_source_hash']), 64)

    def test_formula_file_rejected_with_feature_named(self):
        wb = Workbook()
        ws = wb.active
        ws.title = 'Sheet1'
        ws['A1'] = '标题'
        ws['B2'] = '=SUM(C1:C2)'
        buffer = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
        wb.save(buffer.name)
        buffer.close()
        self.addCleanup(os.remove, buffer.name)
        from django.core.files.uploadedfile import SimpleUploadedFile
        with open(buffer.name, 'rb') as f:
            data = f.read()
        response = self.owner_client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('formula.xlsx', data),
            'name': '公式模板', 'ledger_type': 'week_month',
        })
        error = response.json()['error']
        self.assertIn('公式计算', error)
        self.assertEqual(OperationLedger.objects.count(), 0)

    def test_non_xlsx_rejected(self):
        response = self.owner_client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('legacy.xls', b'not-excel'),
            'name': '旧格式', 'ledger_type': 'week_month',
        })
        self.assertIn('仅支持 .xlsx', response.json()['error'])


class BindingTests(ExcelLedgerContractBase):
    """字段绑定校验与落库。"""

    def test_bindings_saved_and_restored(self):
        template = self.upload_sample()
        bindings = [self.make_binding('C4', 'PS模块'), self.make_binding('H4', '备注', input_type='text')]
        response = self.save_bindings(template['id'], bindings)
        detail = response.json()['data']['data']
        saved = detail['draft']['field_bindings']
        self.assertEqual([b['cell_coordinate'] for b in saved], ['C4', 'H4'])
        self.assertEqual(saved[0]['field_id'], bindings[0]['field_id'])

    def test_retired_attributes_not_persisted(self):
        """请求携带退役属性也只落新协议八键（2026-09-29 协议收敛）。"""
        template = self.upload_sample()
        binding = self.make_binding('C4', 'PS模块')
        binding.update({
            'default_value': '正常',
            'operation_guide': '检查电源指示灯',
            'abnormal_rule': '指示灯熄灭判定异常',
            'maintenance_cycles': ['week_month'],
        })
        response = self.save_bindings(template['id'], [binding])
        self.assertEqual(response.json().get('error', ''), '')
        saved = response.json()['data']['data']['draft']['field_bindings'][0]
        self.assertEqual(sorted(saved.keys()), sorted([
            'field_id', 'sheet_name', 'cell_coordinate', 'field_name',
            'input_type', 'is_required', 'unit', 'options']))

    def test_batch_atomic_rejected_on_merged_non_anchor(self):
        """批量载荷中一项非法即整体拒绝，不产生部分落库。"""
        template = self.upload_sample()
        bindings = [self.make_binding('C4', 'PS模块'),
                    self.make_binding('A4', '信道锚点')]
        response = self.save_bindings(template['id'], bindings)
        self.assertIn('只能绑定左上角单元格 A3', response.json()['error'])
        detail = self.owner_client.get(
            '%s/%s/' % (TPL_URL, template['id'])).json()['data']['data']
        self.assertEqual(detail['draft']['field_bindings'], [])

    def test_choice_without_options_rejected(self):
        template = self.upload_sample()
        response = self.save_bindings(
            template['id'], [self.make_binding('C4', '结论', input_type='choice')])
        self.assertIn('候选项', response.json()['error'])

    def test_unknown_input_type_rejected(self):
        template = self.upload_sample()
        response = self.save_bindings(
            template['id'], [self.make_binding('C4', 'X', input_type='checkbox')])
        self.assertIn('输入类型', response.json()['error'])

    def test_merged_non_anchor_rejected(self):
        template = self.upload_sample()
        response = self.save_bindings(template['id'], [self.make_binding('A4', '信道')])
        self.assertIn('只能绑定左上角单元格 A3', response.json()['error'])

    def test_content_cell_rejected(self):
        template = self.upload_sample()
        response = self.save_bindings(template['id'], [self.make_binding('C2', '表头格')])
        self.assertIn('已有内容', response.json()['error'])

    def test_duplicate_cell_rejected(self):
        template = self.upload_sample()
        bindings = [self.make_binding('C4', 'PS模块'), self.make_binding('C4', '重复格')]
        response = self.save_bindings(template['id'], bindings)
        self.assertIn('最多绑定一个字段', response.json()['error'])

    def test_reupload_clears_bindings(self):
        template = self.upload_sample()
        self.save_bindings(template['id'], [self.make_binding('C4', 'PS模块')])
        response = self.owner_client.post('%s/%s/draft-file/' % (TPL_URL, template['id']), {
            'file': SimpleUploadedFile('channel.xlsx', build_acceptance_sample_xlsx())})
        detail = response.json()['data']['data']
        self.assertEqual(detail['draft']['field_bindings'], [])
        self.assertNotEqual(detail['draft_source_hash'], '')


class PublishTests(ExcelLedgerContractBase):
    """发布级校验与不可变版本。"""

    def test_publish_requires_bindings(self):
        template = self.upload_sample()
        response = self.owner_client.post('%s/%s/publish/' % (TPL_URL, template['id']))
        self.assertIn('绑定至少一个可填写字段', response.json()['error'])

    def test_publish_ignores_retired_attributes(self):
        """发布不依赖退役属性：历史草稿残留默认值也不阻断发布。"""
        template = self.upload_sample()
        binding = self.make_binding('C4', '结论', input_type='choice',
                                    options=['正常', '异常'])
        binding['default_value'] = '良好'  # 旧属性且不在候选项内
        binding['maintenance_cycles'] = ['daily']  # 旧属性非法值同样忽略
        response = self.save_bindings(template['id'], [binding])
        self.assertEqual(response.json().get('error', ''), '')
        response = self.owner_client.post('%s/%s/publish/' % (TPL_URL, template['id']))
        self.assertEqual(response.json().get('error', ''), '')
        version = response.json()['data']['data']
        self.assertEqual(version['field_count'], 1)

    def test_publish_snapshot_immutable_and_incremental(self):
        template, version, bindings = self.create_published_version()
        self.assertEqual(version['version_no'], 1)
        self.assertEqual(version['field_count'], 3)
        self.assertEqual(version['ledger_type'], 'week_month')
        detail = self.owner_client.get(
            '%s/%s/versions/1/' % (TPL_URL, template['id'])).json()['data']['data']
        self.assertEqual(len(detail['bindings']), 3)
        self.assertEqual(detail['source_hash'], version['source_hash'])
        # 版本写路径缺失 → 405
        version_url = '%s/%s/versions/1/' % (TPL_URL, template['id'])
        self.assertEqual(self.owner_client.put(version_url, content_type='application/json').status_code, 405)
        self.assertEqual(self.owner_client.post(version_url).status_code, 405)
        self.assertEqual(self.owner_client.delete(version_url).status_code, 405)
        # 重新绑定发布 → v2，v1 不变
        new_bindings = [self.make_binding('E4', 'RX模块')]
        self.save_bindings(template['id'], new_bindings)
        version2 = self.publish(template['id'])
        self.assertEqual(version2['version_no'], 2)
        detail_v1 = self.owner_client.get(
            '%s/%s/versions/1/' % (TPL_URL, template['id'])).json()['data']['data']
        self.assertEqual(len(detail_v1['bindings']), 3)


class LegacyBindingCompatTests(ExcelLedgerContractBase):
    """历史绑定（含退役属性）仍可读取、发布、填写与导出。"""

    def _legacy_bindings(self):
        """协议收敛前的绑定形态（含 default_value 等退役属性）。"""
        return [
            {
                'field_id': str(uuid.uuid4()), 'sheet_name': SHEET_MAIN,
                'cell_coordinate': 'C4', 'field_name': '主电台-PS模块',
                'input_type': 'status', 'is_required': True, 'unit': '',
                'options': ['正常', '异常'],
                'default_value': '正常', 'operation_guide': '检查电源指示灯',
                'abnormal_rule': '指示灯熄灭判定异常',
                'maintenance_cycles': ['week_month'],
            },
            {
                'field_id': str(uuid.uuid4()), 'sheet_name': SHEET_MAIN,
                'cell_coordinate': 'H4', 'field_name': '备注',
                'input_type': 'text', 'is_required': False, 'unit': '',
                'options': [], 'default_value': '', 'operation_guide': '',
                'abnormal_rule': '', 'maintenance_cycles': ['all'],
            },
        ]

    def test_legacy_draft_and_version_viewable_fillable_exportable(self):
        from apps.equipment_lifecycle.excel_models import OperationLedgerExcelTemplate
        template = self.upload_sample()
        legacy = self._legacy_bindings()
        # ORM 直写历史草稿（模拟协议收敛前已保存的草稿数据）
        OperationLedgerExcelTemplate.objects.filter(pk=template['id']).update(
            draft_bindings=json.dumps(legacy, ensure_ascii=False))
        # 草稿读取端原样返回旧属性
        detail = self.owner_client.get(
            '%s/%s/' % (TPL_URL, template['id'])).json()['data']['data']
        saved_draft = detail['draft']['field_bindings']
        self.assertEqual(saved_draft[0]['default_value'], '正常')
        self.assertEqual(saved_draft[0]['maintenance_cycles'], ['week_month'])
        # 发布不依赖退役属性（含不在候选项内的默认值也不阻断）
        version = self.publish(template['id'])
        version_detail = self.owner_client.get(
            '%s/%s/versions/%s/' % (TPL_URL, template['id'], version['version_no'])
        ).json()['data']['data']
        published = version_detail['bindings']
        self.assertEqual(published[0]['default_value'], '正常')
        self.assertEqual(published[0]['operation_guide'], '检查电源指示灯')
        # 历史版本创建台账：旧默认值仍按类型校验预填
        response = self.owner_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id'],
                                          'executed_date': '2026-09-29'}),
            content_type='application/json')
        detail = response.json()['data']['data']
        ledger_id = detail['id']
        self.assertEqual(detail['excel']['values'][legacy[0]['field_id']], '正常')
        # 历史版本可正常填写、提交
        values = {legacy[0]['field_id']: '异常', legacy[1]['field_id']: '阻抗正常'}
        response = self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger_id), json.dumps({'values': values}),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        response = self.owner_client.post('%s/%s/submit/' % (LEDGER_URL, ledger_id))
        self.assertEqual(response.json().get('error', ''), '')
        # 历史版本导出 Excel 不因旧属性失败，填写值写入源文件
        response = self.owner_client.post('%s/%s/export/excel/' % (LEDGER_URL, ledger_id))
        workbook = load_workbook(filename=io.BytesIO(response.content))
        self.assertEqual(workbook[SHEET_MAIN]['C4'].value, '异常')
        self.assertEqual(workbook[SHEET_MAIN]['H4'].value, '阻抗正常')


class BatchBindingTests(ExcelLedgerContractBase):
    """批量绑定（多格一次性保存）与数量上限。"""

    def test_batch_bindings_saved_with_unique_ids_and_stable_names(self):
        template = self.upload_sample()
        prefix = '主电台 PS'
        coords = ['C4', 'D4', 'E4']
        bindings = [self.make_binding(coord, '%s-%s' % (prefix, coord))
                    for coord in coords]
        response = self.save_bindings(template['id'], bindings)
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        saved = payload['data']['data']['draft']['field_bindings']
        self.assertEqual([b['cell_coordinate'] for b in saved], coords)
        self.assertEqual([b['field_name'] for b in saved],
                         ['主电台 PS-C4', '主电台 PS-D4', '主电台 PS-E4'])
        field_ids = [b['field_id'] for b in saved]
        self.assertEqual(len(set(field_ids)), 3)
        for field_id in field_ids:
            uuid.UUID(field_id)
        # 重取详情：服务端返回与保存结果一致
        detail = self.owner_client.get(
            '%s/%s/' % (TPL_URL, template['id'])).json()['data']['data']
        self.assertEqual([b['field_id'] for b in detail['draft']['field_bindings']],
                         field_ids)

    def test_batch_duplicate_cell_rejected(self):
        template = self.upload_sample()
        bindings = [self.make_binding('C4', 'PS模块'),
                    self.make_binding('C4', '重复格')]
        response = self.save_bindings(template['id'], bindings)
        self.assertIn('最多绑定一个字段', response.json()['error'])

    def test_batch_exceeds_limit_rejected(self):
        wb = Workbook()
        ws = wb.active
        ws.title = 'Grid'
        ws.cell(row=1, column=1, value='网格标题')
        # 空白格不会扩展 max_row/max_column，用带样式的空格撑出边界
        ws.cell(row=21, column=20).border = Border(bottom=Side(style='thin'))
        buffer = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
        wb.save(buffer.name)
        buffer.close()
        self.addCleanup(os.remove, buffer.name)
        with open(buffer.name, 'rb') as f:
            data = f.read()
        response = self.owner_client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('grid.xlsx', data),
            'name': '网格模板', 'ledger_type': 'week_month',
        })
        template = response.json()['data']['data']
        bindings = []
        for row in range(2, 22):
            for col in range(1, 21):
                bindings.append(self.make_binding(
                    '%s%d' % (get_column_letter(col), row), '字段%d' % len(bindings),
                    sheet='Grid'))
        self.assertGreater(len(bindings), 300)
        response = self.save_bindings(template['id'], bindings[:301])
        self.assertIn('数量超过上限', response.json()['error'])


class LedgerLifecycleTests(ExcelLedgerContractBase):
    """台账创建/填写/提交/历史/导出全链路。"""

    def _create_ledger(self, version_id, client=None, **kwargs):
        client = client or self.owner_client
        body = {'version_id': version_id, 'executed_date': '2026-09-28',
                'executor_names': '验收人', 'ledger_type': 'week_month'}
        body.update(kwargs)
        return client.post(LEDGER_URL + '/', json.dumps(body), content_type='application/json')

    def test_create_submit_and_export_roundtrip(self):
        template, version, bindings = self.create_published_version()
        response = self._create_ledger(version['id'])
        detail = response.json()['data']['data']
        ledger_id = detail['id']
        self.assertTrue(detail['ledger_no'].startswith('EL-WM'))
        self.assertEqual(detail['created_from'], 'excel_template')
        self.assertEqual(detail['excel']['version']['version_no'], 1)
        self.assertEqual(detail['excel']['values'], {})
        # 填写并保存
        values = {bindings[0]['field_id']: '正常', bindings[1]['field_id']: '正常',
                  bindings[2]['field_id']: '阻抗正常'}
        response = self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger_id), json.dumps({'values': values}),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        # 提交（必填齐全）
        response = self.owner_client.post('%s/%s/submit/' % (LEDGER_URL, ledger_id))
        self.assertEqual(response.json().get('error', ''), '')
        self.assertEqual(response.json()['data']['data']['status'], 'submitted')
        # 已提交不允许改值
        response = self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger_id), json.dumps({'values': values}),
            content_type='application/json')
        self.assertIn('不允许修改填写值', response.json()['error'])
        # 历史详情回放版本快照与填写值
        response = self.owner_client.get('%s/%s/' % (LEDGER_URL, ledger_id))
        detail = response.json()['data']['data']
        self.assertEqual(detail['excel']['values'][bindings[0]['field_id']], '正常')
        self.assertEqual(detail['excel']['version']['field_count'], 3)
        return template, version, bindings, ledger_id, values

    def test_submit_blocks_missing_required(self):
        template, version, bindings = self.create_published_version()
        response = self._create_ledger(version['id'])
        ledger_id = response.json()['data']['data']['id']
        values = {bindings[0]['field_id']: '正常'}
        self.owner_client.put('%s/%s/' % (LEDGER_URL, ledger_id),
                              json.dumps({'values': values}), content_type='application/json')
        response = self.owner_client.post('%s/%s/submit/' % (LEDGER_URL, ledger_id))
        self.assertIn('必填字段未填写', response.json()['error'])
        ledger = OperationLedger.objects.get(pk=ledger_id)
        self.assertEqual(ledger.status, 'draft')

    def test_invalid_value_type_rejected(self):
        template, version, bindings = self.create_published_version()
        response = self._create_ledger(version['id'])
        ledger_id = response.json()['data']['data']['id']
        values = {bindings[0]['field_id']: '不是候选项'}
        response = self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger_id), json.dumps({'values': values}),
            content_type='application/json')
        self.assertIn('候选项之一', response.json()['error'])

    def test_ledger_type_boundary_validated(self):
        template, version, _ = self.create_published_version(ledger_type='seasonal',
                                                             name='信道季维护台账')
        response = self._create_ledger(version['id'])
        self.assertIn('与所选台账类型不一致', response.json()['error'])
        # 类型一致可创建
        response = self._create_ledger(version['id'], ledger_type='seasonal')
        self.assertEqual(response.json().get('error', ''), '')
        self.assertTrue(response.json()['data']['data']['ledger_no'].startswith('EL-SE'))

    def test_client_token_idempotent(self):
        template, version, _ = self.create_published_version()
        first = self._create_ledger(version['id'], client_token='tok-excel-001')
        second = self._create_ledger(version['id'], client_token='tok-excel-001')
        self.assertEqual(first.json()['data']['data']['id'], second.json()['data']['data']['id'])
        self.assertEqual(OperationLedger.objects.filter(created_from='excel_template').count(), 1)

    def test_inactive_template_rejected(self):
        template, version, _ = self.create_published_version()
        from apps.equipment_lifecycle.excel_models import OperationLedgerExcelTemplate
        OperationLedgerExcelTemplate.objects.filter(pk=template['id']).update(is_active=False)
        response = self._create_ledger(version['id'])
        self.assertIn('已停用', response.json()['error'])

    def test_history_keeps_referenced_version(self):
        template, version, bindings, ledger_id, values = \
            self.test_create_submit_and_export_roundtrip()
        # 模板改造并发布 v2（绑定与文件均变化）
        self.owner_client.post('%s/%s/draft-file/' % (TPL_URL, template['id']), {
            'file': SimpleUploadedFile('channel.xlsx', build_acceptance_sample_xlsx())})
        self.save_bindings(template['id'], [self.make_binding('F4', 'BB模块')])
        version2 = self.publish(template['id'])
        self.assertEqual(version2['version_no'], 2)
        # 旧台账详情仍是 v1 快照
        detail = self.owner_client.get('%s/%s/' % (LEDGER_URL, ledger_id)).json()['data']['data']
        self.assertEqual(detail['excel']['version']['version_no'], 1)
        self.assertEqual([b['cell_coordinate'] for b in detail['excel']['version']['bindings']],
                         ['C4', 'D4', 'H4'])
        # 旧台账导出仍使用 v1 源文件并填充旧填写值
        response = self.owner_client.post('%s/%s/export/excel/' % (LEDGER_URL, ledger_id))
        workbook = load_workbook(filename=io.BytesIO(response.content))
        self.assertEqual(workbook[SHEET_MAIN]['C4'].value, '正常')
        self.assertEqual(workbook[SHEET_MAIN]['H4'].value, '阻抗正常')

    def test_export_excel_keeps_merges_and_fills(self):
        template, version, bindings = self.create_published_version()
        response = self._create_ledger(version['id'])
        ledger_id = response.json()['data']['data']['id']
        values = {bindings[0]['field_id']: '异常', bindings[1]['field_id']: '正常',
                  bindings[2]['field_id']: '更换模块'}
        self.owner_client.put('%s/%s/' % (LEDGER_URL, ledger_id),
                              json.dumps({'values': values}), content_type='application/json')
        response = self.owner_client.post('%s/%s/export/excel/' % (LEDGER_URL, ledger_id))
        self.assertIn('application/vnd.openxmlformats', response['Content-Type'])
        workbook = load_workbook(filename=io.BytesIO(response.content))
        main = workbook[SHEET_MAIN]
        self.assertEqual(str(main.merged_cells.ranges[0]), 'A1:H1')
        self.assertEqual(main['C4'].value, '异常')
        self.assertEqual(main['A3'].value, '第1信道')

    def test_export_blocked_when_required_missing(self):
        template, version, bindings = self.create_published_version()
        response = self._create_ledger(version['id'])
        ledger_id = response.json()['data']['data']['id']
        response = self.owner_client.post('%s/%s/export/excel/' % (LEDGER_URL, ledger_id))
        self.assertIn('必填字段未填写', response.json()['error'])

    @skipUnless(detect_soffice(), 'LibreOffice 不可用，PDF 导出用例 NOT_RUN（环境限制）')
    def test_export_pdf_real_conversion(self):
        template, version, bindings = self.create_published_version()
        response = self._create_ledger(version['id'])
        ledger_id = response.json()['data']['data']['id']
        values = {bindings[0]['field_id']: '正常', bindings[1]['field_id']: '正常',
                  bindings[2]['field_id']: '测试完成'}
        self.owner_client.put('%s/%s/' % (LEDGER_URL, ledger_id),
                              json.dumps({'values': values}), content_type='application/json')
        response = self.owner_client.post('%s/%s/export/pdf/' % (LEDGER_URL, ledger_id))
        self.assertIn('application/pdf', response['Content-Type'])
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.assertGreater(len(response.content), 1000)

    def test_export_pdf_business_error_without_libreoffice(self):
        """LibreOffice 不可用时返回业务错误（HTTP 200 + error），绝不伪造 PDF。"""
        template, version, bindings = self.create_published_version()
        response = self._create_ledger(version['id'])
        ledger_id = response.json()['data']['data']['id']
        values = {bindings[0]['field_id']: '正常', bindings[1]['field_id']: '正常'}
        self.owner_client.put('%s/%s/' % (LEDGER_URL, ledger_id),
                              json.dumps({'values': values}), content_type='application/json')
        with mock.patch('apps.equipment_lifecycle.excel_pdf_service.detect_soffice',
                        return_value=None):
            response = self.owner_client.post('%s/%s/export/pdf/' % (LEDGER_URL, ledger_id))
        self.assertIn('LibreOffice 不可用', response.json()['error'])


class PdfPrintAreaSanitizeTests(ExcelLedgerContractBase):
    """PDF 转换前打印区域净化（WPS 残留空打印区域致整份空白 PDF 缺陷）。"""

    def _build_workbook_bytes(self, print_area=None):
        wb = Workbook()
        ws = wb.active
        ws.title = SHEET_MAIN
        ws['A1'] = '净化测试表'
        ws['A2'] = '列头'
        ws['C2'] = 'C列'
        ws['A4'] = '行标'
        if print_area:
            ws.print_area = print_area
        buffer = io.BytesIO()
        wb.save(buffer)
        return buffer.getvalue()

    def test_stray_print_area_cleared_and_content_kept(self):
        from apps.equipment_lifecycle.excel_template_services import prepare_pdf_workbook
        cleaned = prepare_pdf_workbook(self._build_workbook_bytes(print_area='H7'))
        workbook = load_workbook(io.BytesIO(cleaned))
        sheet = workbook[SHEET_MAIN]
        self.assertIsNone(sheet.print_area)
        self.assertEqual(sheet['A1'].value, '净化测试表')

    def test_content_print_area_preserved(self):
        from apps.equipment_lifecycle.excel_template_services import prepare_pdf_workbook
        cleaned = prepare_pdf_workbook(self._build_workbook_bytes(print_area='A1:B4'))
        workbook = load_workbook(io.BytesIO(cleaned))
        self.assertIsNotNone(workbook[SHEET_MAIN].print_area)

    def test_export_pdf_not_blank_with_stray_print_area(self):
        """端到端：残留空打印区域的模板导出 PDF 必须包含表单与填写内容。"""
        if not (detect_soffice() and shutil.which('pdftotext')):
            self.skipTest('LibreOffice 或 pdftotext 不可用，PDF 净化端到端用例 NOT_RUN')
        template = self.upload_sample()
        binding = self.make_binding('C4', 'PS模块')
        response = self.save_bindings(template['id'], [binding])
        self.assertEqual(response.json().get('error', ''), '')
        version = self.publish(template['id'])
        response = self.owner_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id'],
                                          'executed_date': '2026-09-29'}),
            content_type='application/json')
        ledger_id = response.json()['data']['data']['id']
        self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger_id),
            json.dumps({'values': {binding['field_id']: '异常'}}),
            content_type='application/json')
        # 直接在源文件上注入残留打印区域（模拟 WPS 上传文件自带）
        from apps.equipment_lifecycle import excel_template_storage
        path = excel_template_storage.version_path(template['id'], version['version_no'])
        workbook = load_workbook(path)
        workbook[SHEET_MAIN].print_area = 'H7'
        workbook.save(path)
        response = self.owner_client.post('%s/%s/export/pdf/' % (LEDGER_URL, ledger_id))
        self.assertIn('application/pdf', response['Content-Type'])
        import subprocess
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(response.content)
            pdf_path = f.name
        self.addCleanup(os.remove, pdf_path)
        text = subprocess.run(['pdftotext', pdf_path, '-'],
                              capture_output=True).stdout.decode('utf-8', 'replace')
        self.assertIn('信道维护记录表', text)
        self.assertIn('异常', text)


class ListIsolationTests(ExcelLedgerContractBase):
    """正式台账列表与 Excel 台账列表的关系。

    2026-10 起正式台账列表统一返回 Excel 路线台账（source_type 区分来源，
    详情按 created_from 分支），本类只保留 Excel 独立列表仍可用的契约；
    统一列表/分支详情/误入拦截契约见 test_ledger_unified_excel.py。
    """

    def test_excel_list_still_scoped_and_unified_list_includes_excel(self):
        from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
            create_ledger_ok, entry_payload, item_payload, ledger_payload,
        )
        template, version, _ = self.create_published_version()
        response = self.owner_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id'], 'executed_date': '2026-09-28'}),
            content_type='application/json')
        excel_id = response.json()['data']['data']['id']
        system = self._make_system()
        create_ledger_ok(self.owner_client, ledger_payload(
            [entry_payload(system.id, [item_payload()])]))
        # 统一列表同时返回两条路线台账
        unified_ids = [r['id'] for r in self.owner_client.get(
            URL_PREFIX + '/ledgers/?ledger_type=week_month').json()['data']['data']]
        self.assertIn(excel_id, unified_ids)
        # Excel 独立列表保留：仍只返回 Excel 路线台账
        excel_ids = [r['id'] for r in self.owner_client.get(
            LEDGER_URL + '/').json()['data']['data']]
        self.assertIn(excel_id, excel_ids)
        self.assertEqual(len(excel_ids), 1)

    def _make_system(self):
        from apps.equipment_lifecycle.tests.base import make_system
        return make_system(self.owner, tenant_id=self.owner.tenant_id)


class TenantIsolationTests(ExcelLedgerContractBase):
    """跨租户访问统一按不存在拒绝。"""

    def test_cross_tenant_template_and_ledger_rejected(self):
        template, version, bindings = self.create_published_version()
        response = self.other_client.get('%s/%s/' % (TPL_URL, template['id']))
        self.assertEqual(response.json()['error'], 'Excel台账模板不存在')
        response = self.other_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id'], 'executed_date': '2026-09-28'}),
            content_type='application/json')
        self.assertEqual(response.json()['error'], '模板版本不存在或未发布')
        self.assertFalse(OperationLedger.objects.filter(created_from='excel_template').exists())

    def test_available_versions_scoped_by_tenant(self):
        template, version, _ = self.create_published_version()
        data = self.other_client.get(TPL_URL + '/available/').json()['data']['data']
        self.assertEqual(data, [])
        data = self.owner_client.get(TPL_URL + '/available/').json()['data']['data']
        self.assertEqual(data[0]['id'], template['id'])
        self.assertEqual(data[0]['versions'][0]['id'], version['id'])


class TemplateDeleteTests(ExcelLedgerContractBase):
    """模板删除（逻辑删除/停用）：权限、租户隔离、幂等与历史完整性。"""

    P_TPL_DEL = 'equipment_lifecycle.ledger_template.del'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # 本类用户额外持有 del 权限：owner 删除本租户模板；other 同持
        # del 权限以验证跨租户隔离（通过权限层后按不存在统一拒绝）
        cls.owner = make_user(
            'excel_del_%s' % uuid.uuid4().hex[:8],
            perms=P_TPL + [cls.P_TPL_DEL] + P_LEDGER)
        cls.owner_client = make_client(cls.owner)
        cls.other = make_user(
            'excel_del_other_%s' % uuid.uuid4().hex[:8],
            perms=P_TPL + [cls.P_TPL_DEL] + P_LEDGER, tenant_id='another')
        cls.other_client = make_client(cls.other)

    def _delete(self, template_id, client=None):
        client = client or self.owner_client
        return client.delete('%s/%s/' % (TPL_URL, template_id))

    def _create_ledger_from_version(self, version, bindings):
        """创建台账并填齐必填值（导出有必填校验），返回 (ledger_id, values)。"""
        response = self.owner_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id'],
                                          'executed_date': '2026-09-29'}),
            content_type='application/json')
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        ledger_id = payload['data']['data']['id']
        values = {b['field_id']: ('异常' if b['input_type'] == 'status' else '已填写')
                  for b in bindings if b.get('is_required')}
        self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger_id),
            json.dumps({'values': values}),
            content_type='application/json')
        return ledger_id, values

    def test_delete_sets_inactive_and_hides_from_available(self):
        template, version, _ = self.create_published_version()
        response = self._delete(template['id'])
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        self.assertFalse(payload['data']['data']['is_active'])
        # 可用模板接口（新建台账模板选择列表）不再返回
        available = self.owner_client.get(TPL_URL + '/available/').json()['data']['data']
        self.assertEqual(available, [])
        # 管理列表保留该模板但呈停用状态
        rows = self.owner_client.get(TPL_URL + '/').json()['data']['data']
        row = next(r for r in rows if r['id'] == template['id'])
        self.assertFalse(row['is_active'])
        # 新建台账拒绝使用该模板
        ledger_response = self.owner_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id'],
                                          'executed_date': '2026-09-29'}),
            content_type='application/json')
        self.assertIn('已停用', ledger_response.json()['error'])

    def test_delete_without_permission_rejected(self):
        from apps.equipment_lifecycle.excel_models import OperationLedgerExcelTemplate
        template, _, _ = self.create_published_version()
        limited = make_user('excel_nodel_%s' % uuid.uuid4().hex[:8], perms=P_TPL)
        response = make_client(limited).delete('%s/%s/' % (TPL_URL, template['id']))
        self.assertEqual(response.json()['error'], '权限拒绝')
        self.assertTrue(
            OperationLedgerExcelTemplate.objects.get(pk=template['id']).is_active)

    def test_cross_tenant_delete_rejected(self):
        from apps.equipment_lifecycle.excel_models import OperationLedgerExcelTemplate
        template, _, _ = self.create_published_version()
        response = self.other_client.delete('%s/%s/' % (TPL_URL, template['id']))
        self.assertEqual(response.json()['error'], '模板不存在或无权限访问')
        self.assertTrue(
            OperationLedgerExcelTemplate.objects.get(pk=template['id']).is_active)

    def test_delete_missing_template_same_error(self):
        response = self._delete(999999)
        self.assertEqual(response.json()['error'], '模板不存在或无权限访问')

    def test_delete_idempotent_and_audited_once(self):
        template, _, _ = self.create_published_version()
        first = self._delete(template['id'])
        self.assertEqual(first.json().get('error', ''), '')
        second = self._delete(template['id'])
        self.assertEqual(second.json().get('error', ''), '')
        self.assertFalse(second.json()['data']['data']['is_active'])
        # 审计只记实际发生停用变更的一次（操作人为当前用户）
        from apps.logs.models import AuditLog
        audits = AuditLog.objects.filter(
            target_type='el_ledger_excel_template',
            target_id=str(template['id']), action='delete')
        self.assertEqual(audits.count(), 1)
        self.assertEqual(audits.first().username, self.owner.username)

    def test_deleted_template_rejects_edit_and_publish(self):
        template, version, _ = self.create_published_version()
        self.assertEqual(self._delete(template['id']).json().get('error', ''), '')
        response = self.save_bindings(template['id'], [self.make_binding('C4', 'PS模块')])
        self.assertIn('已删除（停用）', response.json()['error'])
        response = self.owner_client.post('%s/%s/publish/' % (TPL_URL, template['id']))
        self.assertIn('已删除（停用）', response.json()['error'])
        response = self.owner_client.post('%s/%s/draft-file/' % (TPL_URL, template['id']), {
            'file': SimpleUploadedFile('channel.xlsx', build_acceptance_sample_xlsx())})
        self.assertIn('已删除（停用）', response.json()['error'])
        # 版本不可变：拦截的发布不产生新版本
        versions = self.owner_client.get(
            '%s/%s/versions/' % (TPL_URL, template['id'])).json()['data']['data']
        self.assertEqual(len(versions), 1)

    def test_delete_preserves_versions_and_history_ledger(self):
        from apps.equipment_lifecycle.excel_models import OperationLedgerExcelRecord
        template, version, bindings = self.create_published_version()
        ledger_id, values = self._create_ledger_from_version(version, bindings)
        self.assertEqual(self._delete(template['id']).json().get('error', ''), '')
        # 模板详情仍可查看（停用状态）
        detail = self.owner_client.get(
            '%s/%s/' % (TPL_URL, template['id'])).json()['data']['data']
        self.assertFalse(detail['is_active'])
        # 历史版本列表与版本详情仍可读取
        versions = self.owner_client.get(
            '%s/%s/versions/' % (TPL_URL, template['id'])).json()['data']['data']
        self.assertEqual(len(versions), 1)
        version_detail = self.owner_client.get(
            '%s/%s/versions/%s/' % (TPL_URL, template['id'], version['version_no'])
        ).json()['data']['data']
        self.assertEqual(version_detail['version_no'], 1)
        # 历史台账仍可查看（仍引用创建时版本）并导出 Excel
        ledger_detail = self.owner_client.get(
            '%s/%s/' % (LEDGER_URL, ledger_id)).json()['data']['data']
        self.assertEqual(ledger_detail['excel']['version']['version_no'], 1)
        export = self.owner_client.post('%s/%s/export/excel/' % (LEDGER_URL, ledger_id))
        workbook = load_workbook(filename=io.BytesIO(export.content))
        self.assertEqual(workbook[SHEET_MAIN][bindings[0]['cell_coordinate']].value,
                         values[bindings[0]['field_id']])
        # 填写记录与版本记录完整保留
        self.assertTrue(
            OperationLedgerExcelRecord.objects.filter(ledger_id=ledger_id).exists())


class LayoutMetaDetailTests(ExcelLedgerContractBase):
    """上传解析捕获边框/填充/行高列宽/隐藏行列/打印设置等布局元数据。"""

    def test_upload_captures_layout_metadata(self):
        from openpyxl.styles import Font, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = '样式表'
        ws['A1'] = '样式标题'
        ws['A1'].font = Font(name='宋体', size=14, bold=True,
                             underline='single', strike=True)
        ws['A1'].fill = PatternFill(start_color='FFF2CC', end_color='FFF2CC',
                                    fill_type='solid')
        ws['A1'].border = Border(bottom=Side(style='thin', color='FF000000'))
        ws['B2'] = '数据'
        ws.row_dimensions[1].height = 28.5
        ws.column_dimensions['A'].width = 15.5
        # 隐藏行列须在已用范围内（预览只渲染 max_row/max_column 内的行列）
        ws.row_dimensions[2].hidden = True
        ws.column_dimensions['B'].hidden = True
        ws.page_setup.orientation = 'landscape'
        ws.page_setup.paperSize = 9
        buffer = io.BytesIO()
        wb.save(buffer)
        data = buffer.getvalue()
        response = self.owner_client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('styled.xlsx', data),
            'name': '样式模板', 'ledger_type': 'week_month',
        })
        self.assertEqual(response.json().get('error', ''), '')
        payload = response.json()['data']['data']
        sheet = payload['draft']['layout']['sheets'][0]
        self.assertEqual(sheet['row_heights'], {'1': 28.5})
        # openpyxl 对隐藏列的前一列会回写默认宽度（13.0），只断言显式设置值
        self.assertEqual(sheet['column_widths']['A'], 15.5)
        self.assertEqual(sheet['hidden_rows'], ['2'])
        self.assertEqual(sheet['hidden_columns'], ['B'])
        style = sheet['cells']['A1']['s']
        self.assertTrue(style['font']['bold'])
        self.assertEqual(style['font']['underline'], 'single')
        self.assertTrue(style['font']['strike'])
        # openpyxl 回读会把 6 位色值规范为 8 位（00 前缀），前端预览已兼容
        self.assertTrue(style['fill'].endswith('FFF2CC'))
        self.assertEqual(style['border']['bottom']['style'], 'thin')
        self.assertEqual(sheet['print']['orientation'], 'landscape')
        # 登记哈希 = 源文件 SHA-256
        import hashlib
        self.assertEqual(payload['draft_source_hash'],
                         hashlib.sha256(data).hexdigest())


class TemplatePdfPreviewTests(ExcelLedgerContractBase):
    """模板草稿 PDF 预览（发布前真实打印效果；只读，不改草稿/不建版本）。"""

    def _upload_with_binding(self):
        template = self.upload_sample()
        binding = self.make_binding('C4', 'PS模块')
        response = self.save_bindings(template['id'], [binding])
        self.assertEqual(response.json().get('error', ''), '')
        return template, binding

    def _draft_bytes(self, template_id):
        from apps.equipment_lifecycle import excel_template_storage
        with open(excel_template_storage.draft_path(template_id), 'rb') as f:
            return f.read()

    def _preview(self, template_id, client=None):
        client = client or self.owner_client
        return client.post('%s/%s/preview/pdf/' % (TPL_URL, template_id))

    @skipUnless(detect_soffice(),
                'LibreOffice 不可用，草稿 PDF 预览用例 NOT_RUN（环境限制）')
    def test_draft_preview_returns_real_pdf_and_keeps_draft(self):
        template, _ = self._upload_with_binding()
        before = self._draft_bytes(template['id'])
        response = self._preview(template['id'])
        self.assertIn('application/pdf', response['Content-Type'])
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.assertGreater(len(response.content), 1000)
        # 只读预览：草稿源文件字节与登记哈希均不变
        self.assertEqual(self._draft_bytes(template['id']), before)
        detail = self.owner_client.get(
            '%s/%s/' % (TPL_URL, template['id'])).json()['data']['data']
        self.assertEqual(detail['draft_source_hash'], template['draft_source_hash'])
        # 幂等可重复调用；绑定不是预览前提（无绑定也可预览空白版式）
        self.assertEqual(self._preview(template['id']).status_code, 200)

    def test_draft_preview_business_error_without_libreoffice(self):
        """LibreOffice 不可用时返回业务错误，绝不伪造 PDF。"""
        template, _ = self._upload_with_binding()
        with mock.patch('apps.equipment_lifecycle.excel_pdf_service.detect_soffice',
                        return_value=None):
            response = self._preview(template['id'])
        self.assertIn('LibreOffice 不可用', response.json()['error'])

    def test_draft_preview_without_draft_rejected(self):
        from apps.equipment_lifecycle.excel_models import OperationLedgerExcelTemplate
        template = self.upload_sample()
        OperationLedgerExcelTemplate.objects.filter(pk=template['id']).update(
            draft_layout='', draft_source_hash='')
        response = self._preview(template['id'])
        self.assertIn('没有可预览的草稿', response.json()['error'])

    def test_draft_preview_cross_tenant_rejected(self):
        template, _ = self._upload_with_binding()
        response = self.other_client.post(
            '%s/%s/preview/pdf/' % (TPL_URL, template['id']))
        self.assertEqual(response.json()['error'], 'Excel台账模板不存在')

    @skipUnless(detect_soffice() and shutil.which('pdftotext'),
                'LibreOffice 或 pdftotext 不可用，预览净化端到端用例 NOT_RUN')
    def test_preview_not_blank_with_stray_print_area(self):
        """残留空打印区域的草稿预览 PDF 必须包含表单内容（与导出同净化路径）。"""
        template, _ = self._upload_with_binding()
        from apps.equipment_lifecycle import excel_template_storage
        path = excel_template_storage.draft_path(template['id'])
        workbook = load_workbook(path)
        workbook[SHEET_MAIN].print_area = 'H7'
        workbook.save(path)
        response = self._preview(template['id'])
        self.assertIn('application/pdf', response['Content-Type'])
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(response.content)
            pdf_path = f.name
        self.addCleanup(os.remove, pdf_path)
        import subprocess
        text = subprocess.run(['pdftotext', pdf_path, '-'],
                              capture_output=True).stdout.decode('utf-8', 'replace')
        self.assertIn('信道维护记录表', text)


class TemplateCompatibilityTests(ExcelLedgerContractBase):
    """模板详情兼容性检查结果（status/warnings/unsupported）。"""

    def _detail(self, template_id, client=None, detect=Ellipsis):
        """取模板详情；detect 传值（含 None）时固定 LibreOffice 检测结果。"""
        client = client or self.owner_client
        if detect is Ellipsis:
            return client.get('%s/%s/' % (TPL_URL, template_id)).json()['data']['data']
        with mock.patch('apps.equipment_lifecycle.excel_pdf_service.detect_soffice',
                        return_value=detect):
            return client.get('%s/%s/' % (TPL_URL, template_id)).json()['data']['data']

    def test_compatibility_ok_when_environment_ready(self):
        template = self.upload_sample()
        compat = self._detail(template['id'], detect='/usr/bin/soffice')['compatibility']
        self.assertEqual(compat['status'], 'ok')
        self.assertEqual(compat['warnings'], [])
        self.assertEqual(compat['unsupported'], [])

    def test_compatibility_warning_without_libreoffice(self):
        template = self.upload_sample()
        compat = self._detail(template['id'], detect=None)['compatibility']
        self.assertEqual(compat['status'], 'warning')
        self.assertTrue(any('LibreOffice' in w for w in compat['warnings']))

    def test_compatibility_error_when_draft_file_missing(self):
        from apps.equipment_lifecycle import excel_template_storage
        template = self.upload_sample()
        os.remove(excel_template_storage.draft_path(template['id']))
        compat = self._detail(template['id'])['compatibility']
        self.assertEqual(compat['status'], 'error')
        self.assertTrue(any('丢失' in w for w in compat['warnings']))

    def test_compatibility_error_when_hash_mismatch(self):
        from apps.equipment_lifecycle import excel_template_storage
        template = self.upload_sample()
        wb = Workbook()
        ws = wb.active
        ws.title = 'other'
        ws['A1'] = '另一份文件'
        buffer = io.BytesIO()
        wb.save(buffer)
        with open(excel_template_storage.draft_path(template['id']), 'wb') as f:
            f.write(buffer.getvalue())
        compat = self._detail(template['id'])['compatibility']
        self.assertEqual(compat['status'], 'error')
        self.assertTrue(any('哈希' in w for w in compat['warnings']))

    def test_compatibility_error_for_unsupported_features_in_draft(self):
        """历史草稿若含不支持特性（上传拦截前遗留）→ error + 特性列表。"""
        from apps.equipment_lifecycle import excel_template_storage
        from apps.equipment_lifecycle.excel_models import OperationLedgerExcelTemplate
        template = self.upload_sample()
        wb = Workbook()
        ws = wb.active
        ws.title = SHEET_MAIN
        ws['A1'] = '标题'
        ws['B2'] = '=SUM(C1:C2)'
        buffer = io.BytesIO()
        wb.save(buffer)
        data = buffer.getvalue()
        with open(excel_template_storage.draft_path(template['id']), 'wb') as f:
            f.write(data)
        import hashlib
        OperationLedgerExcelTemplate.objects.filter(pk=template['id']).update(
            draft_source_hash=hashlib.sha256(data).hexdigest())
        compat = self._detail(template['id'])['compatibility']
        self.assertEqual(compat['status'], 'error')
        self.assertIn('公式计算', compat['unsupported'])
        self.assertTrue(any('公式计算' in w for w in compat['warnings']))

    def test_compatibility_warning_for_stray_print_area(self):
        """打印区域不覆盖内容 → warning（PDF 转换时自动忽略，不阻断发布）。"""
        from apps.equipment_lifecycle import excel_template_storage
        from apps.equipment_lifecycle.excel_models import OperationLedgerExcelTemplate
        template = self.upload_sample()
        path = excel_template_storage.draft_path(template['id'])
        workbook = load_workbook(path)
        workbook[SHEET_MAIN].print_area = 'H7'
        buffer = io.BytesIO()
        workbook.save(buffer)
        data = buffer.getvalue()
        with open(path, 'wb') as f:
            f.write(data)
        import hashlib
        OperationLedgerExcelTemplate.objects.filter(pk=template['id']).update(
            draft_source_hash=hashlib.sha256(data).hexdigest())
        compat = self._detail(template['id'], detect='/usr/bin/soffice')['compatibility']
        self.assertEqual(compat['status'], 'warning')
        self.assertTrue(any('打印区域' in w for w in compat['warnings']))

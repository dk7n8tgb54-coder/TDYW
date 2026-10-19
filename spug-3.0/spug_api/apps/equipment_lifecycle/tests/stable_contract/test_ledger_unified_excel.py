# -*- coding: utf-8 -*-
"""统一维护台账列表接入 Excel 路线的稳定契约（2026-10）。

Excel/WPS 模板路线并入正式周月/季维护台账入口后（真实 HTTP 路径
URL→View→Service→Model）：
1. 统一列表 /ledgers/ 同时返回手工补录与 Excel 模板路线台账
   （旧可视化模板路线已随迁移 0045 整体删除），行内携带
   source_type / source_template_name / source_version_no / detail_route 来源字段；
2. 统一详情 /ledgers/<pk>/ 按 created_from 分支：Excel 台账返回版本
   快照（绑定/布局/填写值/编辑状态），普通台账保持既有明细结构；
3. Excel 台账误走普通明细接口被显式拦截（编辑 PUT / 提交 submit），
   正确路径 /excel-ledgers/ 的填写、提交、导出不受影响；
4. 复核/退回/作废沿用正式台账端点（状态机一致），响应为 Excel 详情形态；
5. 正式新增入口的模板选择边界：available 按 ledger_type 过滤（周月入口
   只出周月模板、季维护入口只出季维护模板），草稿（未发布）与停用模板
   不出现；创建时类型不一致、无 add 权限、跨租户一律拒绝；
6. client_token 幂等；模板发布新版本不影响历史 Excel 台账的版本引用；
7. 统一列表筛选（状态/编号关键词/日期）对两条路线同时生效；
8. 租户隔离：统一列表与详情均按租户过滤，跨租户同不存在。
"""
import json
import uuid

from apps.equipment_lifecycle.excel_models import OperationLedgerExcelRecord
from apps.equipment_lifecycle.models import OperationLedger
from apps.equipment_lifecycle.tests.base import URL_PREFIX, make_client, make_system, make_user
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS,
    create_ledger_ok,
    entry_payload,
    item_payload,
    ledger_payload,
)
from apps.equipment_lifecycle.tests.stable_contract.test_excel_ledger_templates import (
    ExcelLedgerContractBase,
    LEDGER_URL,
    P_LEDGER as EXCEL_P_LEDGER,
    TPL_URL,
)

NORMAL_LEDGER_URL = URL_PREFIX + '/ledgers'


class UnifiedLedgerExcelTests(ExcelLedgerContractBase):
    """统一列表/分支详情/入口边界的稳定契约。"""

    def _create_normal_ledger(self, **kwargs):
        system = make_system(self.owner, tenant_id=self.owner.tenant_id)
        payload = ledger_payload([entry_payload(system.id, [item_payload()])], **kwargs)
        return create_ledger_ok(self.owner_client, payload)

    def _create_excel_ledger(self, version_id, client=None, **kwargs):
        client = client or self.owner_client
        body = {'version_id': version_id,
                'ledger_type': 'week_month',
                'client_token': ''}
        body.update(kwargs)
        response = client.post(
            LEDGER_URL + '/', json.dumps(body), content_type='application/json')
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        return payload['data']['data']

    def _fill_required_and_complete(self, excel_detail, bindings):
        values = {b['field_id']: ('异常' if b['input_type'] == 'status' else '已填写')
                  for b in bindings if b.get('is_required')}
        response = self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, excel_detail['id']),
            json.dumps({'values': values}), content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        response = self.owner_client.post(
            '%s/%s/complete/' % (LEDGER_URL, excel_detail['id']))
        self.assertEqual(response.json().get('error', ''), '')
        return values

    # ==================== 统一列表 ====================

    def test_unified_list_contains_both_routes_with_source_fields(self):
        template, version, _ = self.create_published_version()
        excel = self._create_excel_ledger(version['id'])
        normal = self._create_normal_ledger(created_from='manual')
        rows = self.owner_client.get(
            NORMAL_LEDGER_URL + '/?ledger_type=week_month').json()['data']['data']
        by_id = {r['id']: r for r in rows}
        self.assertIn(excel['id'], by_id)
        self.assertIn(normal['id'], by_id)
        excel_row = by_id[excel['id']]
        self.assertEqual(excel_row['source_type'], 'excel')
        self.assertEqual(excel_row['source_template_name'], '信道Excel维护台账')
        self.assertEqual(excel_row['source_version_no'], version['version_no'])
        self.assertEqual(
            excel_row['detail_route'],
            '/el/week-month-ledgers?detail=%d&source=excel' % excel['id'])
        normal_row = by_id[normal['id']]
        self.assertEqual(normal_row['source_type'], 'manual')
        self.assertEqual(
            normal_row['detail_route'],
            '/el/week-month-ledgers?detail=%d&source=manual' % normal['id'])

    def test_manual_ledger_source_type_in_unified_list(self):
        normal = self._create_normal_ledger(created_from='manual')
        rows = self.owner_client.get(NORMAL_LEDGER_URL + '/').json()['data']['data']
        row = next(r for r in rows if r['id'] == normal['id'])
        self.assertEqual(row['source_type'], 'manual')

    def test_unified_list_filters_apply_to_both_routes(self):
        template, version, _ = self.create_published_version()
        excel = self._create_excel_ledger(version['id'])
        normal = self._create_normal_ledger(created_from='manual')
        # 状态筛选：两条路线的草稿都命中
        rows = self.owner_client.get(
            NORMAL_LEDGER_URL + '/?status=draft').json()['data']['data']
        ids = {r['id'] for r in rows}
        self.assertIn(excel['id'], ids)
        self.assertIn(normal['id'], ids)
        # 编号关键词筛选：Excel 台账编号同样可检索
        rows = self.owner_client.get(
            NORMAL_LEDGER_URL + '/?keyword=%s' % excel['ledger_no']).json()['data']['data']
        self.assertEqual([r['id'] for r in rows], [excel['id']])
        # 日期范围筛选
        rows = self.owner_client.get(
            NORMAL_LEDGER_URL + '/?executed_from=2026-09-28&executed_to=2026-09-28').json()['data']['data']
        ids = {r['id'] for r in rows}
        self.assertIn(excel['id'], ids)
        self.assertIn(normal['id'], ids)

    # ==================== 统一详情分支 ====================

    def test_unified_detail_branches_by_created_from(self):
        template, version, bindings = self.create_published_version()
        excel = self._create_excel_ledger(version['id'])
        normal = self._create_normal_ledger(created_from='manual')
        # Excel 台账：返回版本快照（绑定/布局/填写值/编辑状态），无普通明细
        data = self.owner_client.get(
            '%s/%s/' % (NORMAL_LEDGER_URL, excel['id'])).json()['data']
        self.assertEqual(data['created_from'], 'excel_template')
        self.assertEqual(data['excel']['version']['version_no'], version['version_no'])
        self.assertEqual(
            [b['field_name'] for b in data['excel']['version']['bindings']],
            [b['field_name'] for b in bindings])
        self.assertEqual(data['excel']['values'], {})
        self.assertTrue(data['excel']['editable'])
        self.assertIn('layout', data['excel']['version'])
        self.assertNotIn('items', data)
        # 普通台账：保持既有明细结构，无 excel 字段
        data = self.owner_client.get(
            '%s/%s/' % (NORMAL_LEDGER_URL, normal['id'])).json()['data']
        self.assertEqual(data['created_from'], 'manual')
        self.assertNotIn('excel', data)
        self.assertGreater(len(data['items']), 0)

    def test_new_template_version_does_not_affect_history(self):
        template, version, bindings = self.create_published_version()
        excel = self._create_excel_ledger(version['id'])
        # 重新绑定并发布 v2，历史台账详情仍引用 v1
        self.save_bindings(template['id'], [self.make_binding('E4', 'RX模块')])
        self.publish(template['id'])
        data = self.owner_client.get(
            '%s/%s/' % (NORMAL_LEDGER_URL, excel['id'])).json()['data']
        self.assertEqual(data['excel']['version']['version_no'], 1)
        self.assertEqual(len(data['excel']['version']['bindings']), 3)

    # ==================== 误入普通明细接口拦截 ====================

    def test_excel_ledger_rejected_from_normal_edit_and_submit(self):
        template, version, bindings = self.create_published_version()
        excel = self._create_excel_ledger(version['id'])
        # 普通明细编辑接口显式拒绝（须走 Excel 填写值接口）
        response = self.owner_client.put(
            '%s/%s/' % (NORMAL_LEDGER_URL, excel['id']),
            json.dumps({'ledger_type': 'week_month',
                        'entries': []}), content_type='application/json')
        self.assertEqual(response.json()['error'], 'Excel 模板台账请通过 Excel 台账填写接口编辑')
        # 完成填写为统一端点：Excel 台账走同一端点，服务层按版本绑定校验必填
        response = self.owner_client.post(
            '%s/%s/complete/' % (NORMAL_LEDGER_URL, excel['id']))
        self.assertIn('必填字段未填写', response.json()['error'])
        self.assertFalse(OperationLedger.objects.filter(pk=excel['id'], status='completed').exists())
        # 正确路径：Excel 完成填写接口在填齐必填后可用
        self._fill_required_and_complete(excel, bindings)
        self.assertTrue(OperationLedger.objects.filter(pk=excel['id'], status='completed').exists())

    def test_excel_ledger_void_via_formal_endpoints(self):
        template, version, bindings = self.create_published_version()
        excel = self._create_excel_ledger(version['id'])
        self._fill_required_and_complete(excel, bindings)
        operator = make_user('unified_void_%s' % uuid.uuid4().hex[:8],
                             perms=EXCEL_P_LEDGER + ALL_LEDGER_PERMS + [
                                 'equipment_lifecycle.ledger.del'])
        client = make_client(operator)
        # 已完成详情为 Excel 详情形态（版本快照保留，不可编辑）
        response = client.get('%s/%s/' % (NORMAL_LEDGER_URL, excel['id']))
        data = response.json()['data']
        self.assertEqual(data['status'], 'completed')
        self.assertEqual(data['excel']['version']['version_no'], 1)
        self.assertFalse(data['excel']['editable'])
        # 已完成不可再编辑填写值（状态机限制）
        response = client.put(
            '%s/%s/' % (LEDGER_URL, excel['id']),
            json.dumps({'values': {}}), content_type='application/json')
        self.assertIn('不允许修改', response.json()['error'])
        # 作废沿用正式端点
        response = client.post(
            '%s/%s/void/' % (NORMAL_LEDGER_URL, excel['id']),
            json.dumps({'reason': '统一入口作废'}), content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        self.assertEqual(response.json()['data']['status'], 'void')

    # ==================== 正式新增入口边界 ====================

    def test_available_templates_filtered_by_ledger_type(self):
        wm_template, wm_version, _ = self.create_published_version(ledger_type='week_month')
        se_template, se_version, _ = self.create_published_version(
            ledger_type='seasonal', name='季维护Excel模板')
        # 周月入口只返回周月模板，季维护入口只返回季维护模板
        data = self.owner_client.get(
            TPL_URL + '/available/?ledger_type=week_month').json()['data']['data']
        self.assertEqual([t['id'] for t in data], [wm_template['id']])
        data = self.owner_client.get(
            TPL_URL + '/available/?ledger_type=seasonal').json()['data']['data']
        self.assertEqual([t['id'] for t in data], [se_template['id']])
        # 季维护入口创建的台账详情路由为季维护页面
        excel = self._create_excel_ledger(se_version['id'], ledger_type='seasonal')
        rows = self.owner_client.get(
            NORMAL_LEDGER_URL + '/?ledger_type=seasonal').json()['data']['data']
        self.assertEqual([r['id'] for r in rows], [excel['id']])
        self.assertTrue(
            rows[0]['detail_route'].startswith('/el/seasonal-ledgers?detail='))

    def test_draft_template_not_in_available(self):
        template = self.upload_sample()
        self.assertEqual(template['status'], 'draft')
        data = self.owner_client.get(
            TPL_URL + '/available/?ledger_type=week_month').json()['data']['data']
        self.assertEqual(data, [])

    def test_stopped_template_not_in_available_and_create_rejected(self):
        template, version, _ = self.create_published_version()
        # 删除（停用）需要模板 del 权限
        manager = make_user('unified_tpldel_%s' % uuid.uuid4().hex[:8],
                            perms=['equipment_lifecycle.ledger_template.view',
                                   'equipment_lifecycle.ledger_template.del',
                                   'equipment_lifecycle.ledger.view',
                                   'equipment_lifecycle.ledger.add'])
        client = make_client(manager)
        # 停用（逻辑停用）：DELETE 已拆分为物理删除（被引用模板不可删）
        response = client.post('%s/%s/deactivate/' % (TPL_URL, template['id']))
        self.assertEqual(response.json().get('error', ''), '')
        # 停用模板不出现在正式新增选择项
        data = client.get(
            TPL_URL + '/available/?ledger_type=week_month').json()['data']['data']
        self.assertEqual(data, [])
        # 已发布版本直接创建也被拒绝
        response = client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id'],
                                          }),
            content_type='application/json')
        self.assertIn('已停用', response.json()['error'])

    def test_create_with_mismatched_ledger_type_rejected(self):
        template, version, _ = self.create_published_version(ledger_type='week_month')
        # 季维护入口不能选择周月模板（后端独立校验，不信任前端）
        response = self.owner_client.post(
            LEDGER_URL + '/',
            json.dumps({'version_id': version['id'],                        'ledger_type': 'seasonal'}),
            content_type='application/json')
        self.assertIn('不一致', response.json()['error'])
        self.assertFalse(
            OperationLedger.objects.filter(created_from='excel_template').exists())

    def test_create_without_add_permission_rejected(self):
        template, version, _ = self.create_published_version()
        limited = make_user('unified_viewonly_%s' % uuid.uuid4().hex[:8],
                            perms=['equipment_lifecycle.ledger.view'])
        response = make_client(limited).post(
            LEDGER_URL + '/',
            json.dumps({'version_id': version['id'], }),
            content_type='application/json')
        self.assertEqual(response.json()['error'], '权限拒绝')
        self.assertFalse(
            OperationLedgerExcelRecord.objects.exists())

    def test_client_token_idempotent(self):
        template, version, _ = self.create_published_version()
        token = 'unified_%s' % uuid.uuid4().hex
        first = self._create_excel_ledger(version['id'], client_token=token)
        second = self._create_excel_ledger(version['id'], client_token=token)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(
            OperationLedger.objects.filter(created_from='excel_template').count(), 1)

    # ==================== 租户隔离 ====================

    def test_unified_list_and_detail_tenant_isolation(self):
        template, version, _ = self.create_published_version()
        excel = self._create_excel_ledger(version['id'])
        # 其他租户创建自己的台账
        other_normal = create_ledger_ok(
            self.other_client,
            ledger_payload([entry_payload(self._make_other_system().id, [item_payload()])],
                           created_from='manual'))
        # 统一列表互不可见
        owner_rows = self.owner_client.get(NORMAL_LEDGER_URL + '/').json()['data']['data']
        self.assertIn(excel['id'], [r['id'] for r in owner_rows])
        self.assertNotIn(other_normal['id'], [r['id'] for r in owner_rows])
        other_rows = self.other_client.get(NORMAL_LEDGER_URL + '/').json()['data']['data']
        self.assertNotIn(excel['id'], [r['id'] for r in other_rows])
        # 详情跨租户同不存在
        response = self.other_client.get('%s/%s/' % (NORMAL_LEDGER_URL, excel['id']))
        self.assertEqual(response.json()['error'], '台账不存在')

    def _make_other_system(self):
        return make_system(self.other, tenant_id=self.other.tenant_id)

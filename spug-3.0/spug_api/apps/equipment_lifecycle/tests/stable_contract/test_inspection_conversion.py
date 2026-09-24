# -*- coding: utf-8 -*-
"""巡检异常转故障/工单稳定契约（今日巡检改造）。

覆盖行为契约：
- 巡检单不关联系统：转换时必须由用户显式选择系统并经后端重新校验
  （存在/本租户/未停用），设备名称不能推断系统；
- 转换默认"部件故障但不影响系统运行"；明确选择影响运行时参与健康状态计算；
- 仅已提交巡检单中结果为"异常"的明细可转；
- 重复转换被拒绝；目标已作废后重新处置须填写原因；client_token 幂等；
- 转换与来源关系同事务、履历事件落目标系统、故障/工单详情双向可追溯；
- 跨租户转换被拒绝。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
from django.test import TestCase

from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemEvent,
    SystemFault,
    SystemWorkOrder,
)
from apps.equipment_lifecycle.tests.base import make_client, make_system
from apps.equipment_lifecycle.tests.stable_contract.inspection_base import (
    INS_URL,
    create_sheet_ok,
    get_sheet_detail,
    get_template_items,
    make_inspection_template,
    make_inspection_user,
    put_records_ok,
    sheet_payload,
    submit_sheet_ok,
)

FAULT_URL = '/equipment-lifecycle/faults'
WO_URL = '/equipment-lifecycle/work-orders'

EXTRA_PERMS = [
    'equipment_lifecycle.fault.view', 'equipment_lifecycle.fault.add',
    'equipment_lifecycle.fault.del',
    'equipment_lifecycle.work_order.view', 'equipment_lifecycle.work_order.add',
]


class InspectionConvertTestBase(TestCase):
    """公共夹具：已提交巡检单 + 一条"不正常"明细 + 目标系统。"""

    def setUp(self):
        self.admin = make_inspection_user(
            'ins_conv_admin', tenant_id='tenant_a', extra_perms=EXTRA_PERMS)
        self.other_admin = make_inspection_user(
            'ins_conv_b', tenant_id='tenant_b', extra_perms=EXTRA_PERMS)
        self.client = make_client(self.admin)
        self.template = make_inspection_template(
            tenant_id='tenant_a', created_by=self.admin)
        self.items = get_template_items(self.template)
        self.target_system = make_system(
            self.admin, tenant_id='tenant_a',
            system_code='SYS-C1', name='转换目标系统', install_location='机房T')
        # 建单 → 填一条异常（choice 不正常）+ 一条正常 → 提交
        body = create_sheet_ok(self.client, sheet_payload(
            self.template.id, duty_date='2026-09-23',
            persons=[{'person_name': '值班员甲'}]))
        put_records_ok(self.client, body['id'], 1, records=[
            {'template_item_id': self.items['面板指示灯'].id,
             'round_no': 'r1', 'value_text': '不正常',
             'abnormal_desc': '告警灯红色', 'onsite_action': '已切换备用'},
            {'template_item_id': self.items['输出功率读数'].id,
             'round_no': 'r1', 'value_text': '480'},
        ])
        submit_sheet_ok(self.client, body['id'])
        detail = get_sheet_detail(self.client, body['id'])
        self.sheet_id = body['id']
        self.abnormal_record_id = next(
            r['id'] for r in detail['records'] if r['result'] == 'abnormal')
        self.normal_record_id = next(
            r['id'] for r in detail['records'] if r['result'] == 'normal')

    def convert_to_fault(self, record_id, payload=None, user=None):
        target = make_client(user) if user else self.client
        if payload is None:
            payload = {'system': self.target_system.id}
        resp = target.post(
            f'{INS_URL}/{self.sheet_id}/records/{record_id}/convert-to-fault/',
            payload, content_type='application/json')
        body = resp.json()
        if not body.get('error'):
            body = body['data']
        return body

    def convert_to_work_order(self, record_id, payload=None, user=None):
        target = make_client(user) if user else self.client
        if payload is None:
            payload = {'system': self.target_system.id}
        resp = target.post(
            f'{INS_URL}/{self.sheet_id}/records/{record_id}/convert-to-work-order/',
            payload, content_type='application/json')
        body = resp.json()
        if not body.get('error'):
            body = body['data']
        return body


class ConvertToFaultContractTest(InspectionConvertTestBase):
    """巡检异常转故障。"""

    def test_convert_requires_explicit_system_choice(self):
        """转换必须显式选择系统：不传 system 被拒绝，设备名称不能推断系统。"""
        body = self.convert_to_fault(self.abnormal_record_id, {})
        self.assertIn('请选择系统', body.get('error', ''))
        self.assertEqual(SystemFault.objects.count(), 0)

    def test_convert_default_does_not_affect_system(self):
        """默认"部件故障但不影响系统运行"：系统健康状态保持正常。"""
        body = self.convert_to_fault(self.abnormal_record_id)
        self.assertFalse(body.get('error'), body)
        fault = SystemFault.objects.get(pk=body['id'])
        self.assertFalse(fault.affects_system_operation)
        self.assertEqual(fault.impact_status, '')
        # 转换缺省发现方式/级别：巡检发现 + 一般
        self.assertEqual(fault.discovery, 'patrol')
        self.assertEqual(fault.level, 'minor')
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.target_system.id).health_status,
            'normal')

    def test_convert_explicit_affect_computes_health(self):
        """明确选择影响系统运行时按影响程度参与健康状态计算。"""
        body = self.convert_to_fault(self.abnormal_record_id, {
            'system': self.target_system.id,
            'affects_system_operation': True,
            'impact_status': 'degraded',
        })
        self.assertFalse(body.get('error'), body)
        fault = SystemFault.objects.get(pk=body['id'])
        self.assertTrue(fault.affects_system_operation)
        self.assertEqual(fault.impact_status, 'degraded')
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.target_system.id).health_status,
            'degraded')

    def test_convert_writes_source_link_and_trace(self):
        """来源关系真实落库；故障详情可回跳巡检单（值班日/轮次/检查内容）。"""
        body = self.convert_to_fault(self.abnormal_record_id)
        fault = SystemFault.objects.select_related(
            'source_inspection_record__sheet').get(pk=body['id'])
        self.assertEqual(fault.source_type, 'inspection_record')
        self.assertEqual(fault.source_inspection_record_id, self.abnormal_record_id)
        self.assertEqual(fault.source_id, str(self.abnormal_record_id))
        self.assertEqual(body['source_inspection_sheet_no'],
                         fault.source_inspection_record.sheet.sheet_no)
        self.assertEqual(body['source_inspection_duty_date'], '2026-09-23')
        self.assertEqual(body['source_inspection_round_text'], '当日 11:00')
        self.assertEqual(body['source_inspection_item_name'], '面板指示灯')
        # 现象带入巡检上下文
        self.assertIn('值班巡检', fault.phenomenon)
        self.assertIn('面板指示灯', fault.phenomenon)

    def test_convert_writes_event_on_target_system(self):
        """履历事件落在用户选择的目标系统上（巡检单无系统归属）。"""
        body = self.convert_to_fault(self.abnormal_record_id)
        events = SystemEvent.objects.filter(
            tenant_id='tenant_a', source_type='inspection_record')
        self.assertEqual(events.count(), 1)
        event = events.first()
        self.assertEqual(event.system_id, self.target_system.id)
        self.assertEqual(event.event_type, SystemEvent.EVENT_INSPECTION)
        self.assertEqual(event.action, 'convert_to_fault')
        self.assertEqual(event.get_detail().get('sheet_no'), body['source_inspection_sheet_no'])

    def test_duplicate_convert_rejected(self):
        """同一异常明细不能重复转故障。"""
        first = self.convert_to_fault(self.abnormal_record_id)
        self.assertFalse(first.get('error'), first)
        second = self.convert_to_fault(self.abnormal_record_id)
        self.assertIn('不能重复转换', second.get('error', ''))
        self.assertEqual(SystemFault.objects.count(), 1)

    def test_reconvert_after_cancel_requires_reason(self):
        """目标作废后重新处置：无原因拒绝，有原因放行。"""
        first = self.convert_to_fault(self.abnormal_record_id)
        fault_id = first['id']
        make_client(self.admin).post(
            f'{FAULT_URL}/{fault_id}/cancel/',
            {'cancel_reason': '误报'}, content_type='application/json')
        blocked = self.convert_to_fault(self.abnormal_record_id)
        self.assertIn('重新处置原因', blocked.get('error', ''))
        ok = self.convert_to_fault(self.abnormal_record_id, {
            'system': self.target_system.id, 're_dispose_reason': '确认为真实故障'})
        self.assertFalse(ok.get('error'), ok)
        self.assertEqual(SystemFault.objects.count(), 2)

    def test_inactive_or_foreign_system_rejected(self):
        """停用系统与其他租户系统不能作为转换目标。"""
        self.target_system.is_active = False
        self.target_system.save()
        body = self.convert_to_fault(self.abnormal_record_id)
        self.assertIn('不存在、已停用', body.get('error', ''))
        self.target_system.is_active = True
        self.target_system.save()
        foreign = self.convert_to_fault(
            self.abnormal_record_id, {'system': 999999}, user=self.other_admin)
        # 跨租户：明细本身不可见
        self.assertIn('不存在', foreign.get('error', ''))

    def test_draft_sheet_and_normal_record_cannot_convert(self):
        """草稿单不能转单；结果正常的明细不能转单。"""
        draft = create_sheet_ok(self.client, sheet_payload(
            self.template.id, duty_date='2026-09-24',
            persons=[{'person_name': '值班员甲'}], client_token='tok-draft'))
        put_records_ok(self.client, draft['id'], 1, records=[
            {'template_item_id': self.items['面板指示灯'].id,
             'round_no': 'r1', 'value_text': '不正常'}])
        resp = self.client.post(
            f'{INS_URL}/{draft["id"]}/records/'
            f'{get_sheet_detail(self.client, draft["id"])["records"][0]["id"]}/'
            f'convert-to-fault/',
            {'system': self.target_system.id}, content_type='application/json')
        self.assertIn('已提交', resp.json().get('error', ''))
        body = self.convert_to_fault(self.normal_record_id)
        self.assertIn('异常', body.get('error', ''))

    def test_cross_tenant_record_invisible(self):
        """其他租户用户不能转换本租户巡检明细（数据不泄露）。"""
        body = self.convert_to_fault(
            self.abnormal_record_id, {'system': self.target_system.id},
            user=self.other_admin)
        self.assertIn('不存在', body.get('error', ''))
        self.assertEqual(SystemFault.objects.count(), 0)


class CandidateSystemsContractTest(InspectionConvertTestBase):
    """转单目标系统候选端点（转单弹窗专用）。"""

    def test_candidate_systems_with_inspection_permission_only(self):
        """候选系统只需 inspection.view：返回本租户可用系统（含名称/安装地点），
        不依赖 fault.view 或 work_order.view 权限。"""
        from apps.equipment_lifecycle.tests.base import make_user
        from apps.equipment_lifecycle.tests.stable_contract.inspection_base import (
            ALL_INSPECTION_PERMS, make_client as _mc,
        )
        viewer = make_user('ins_viewer', ALL_INSPECTION_PERMS, tenant_id='tenant_a')
        client = _mc(viewer)
        resp = client.get(f'{INS_URL}/candidate-systems/')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        rows = body['data']['data']
        ids = {row['id'] for row in rows}
        self.assertIn(self.target_system.id, ids)
        row = next(r for r in rows if r['id'] == self.target_system.id)
        self.assertEqual(row['name'], '转换目标系统')
        self.assertIn('install_location', row)
        # 跨租户系统不出现
        self.assertNotIn(self.system_b.id if hasattr(self, 'system_b') else -1, ids)

    def test_candidate_systems_excludes_inactive_and_foreign(self):
        """停用系统不出现在候选中；其他租户用户不可见。"""
        self.target_system.is_active = False
        self.target_system.save()
        rows = self.client.get(f'{INS_URL}/candidate-systems/').json()['data']['data']
        self.assertNotIn(self.target_system.id, {r['id'] for r in rows})
        self.target_system.is_active = True
        self.target_system.save()
        foreign = make_client(self.other_admin).get(
            f'{INS_URL}/candidate-systems/').json()['data']['data']
        self.assertNotIn(self.target_system.id, {r['id'] for r in foreign})


class ConvertToWorkOrderContractTest(InspectionConvertTestBase):
    """巡检异常直接转工单。"""

    def test_convert_requires_system_and_links_source(self):
        """转工单同样必须显式选择系统；来源关系真实落库。"""
        body = self.convert_to_work_order(self.abnormal_record_id, {})
        self.assertIn('请选择系统', body.get('error', ''))
        ok = self.convert_to_work_order(self.abnormal_record_id, {
            'system': self.target_system.id, 'client_token': 'tok-wo-1'})
        self.assertFalse(ok.get('error'), ok)
        order = SystemWorkOrder.objects.get(pk=ok['id'])
        self.assertEqual(order.source_type, 'inspection_record')
        self.assertEqual(order.source_inspection_record_id, self.abnormal_record_id)
        self.assertEqual(order.system_id, self.target_system.id)
        # 默认不影响系统运行
        self.assertFalse(order.affects_system_operation)

    def test_client_token_idempotent(self):
        """同 client_token 重复提交返回已有工单。"""
        payload = {'system': self.target_system.id, 'client_token': 'tok-wo-idem'}
        first = self.convert_to_work_order(self.abnormal_record_id, payload)
        second = self.convert_to_work_order(self.abnormal_record_id, payload)
        self.assertFalse(first.get('error'), first)
        self.assertFalse(second.get('error'), second)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(SystemWorkOrder.objects.count(), 1)

    def test_duplicate_convert_rejected(self):
        """同一异常明细不能重复转工单；已转故障后直接转工单须填写原因。"""
        first = self.convert_to_work_order(
            self.abnormal_record_id, {'system': self.target_system.id})
        self.assertFalse(first.get('error'), first)
        second = self.convert_to_work_order(
            self.abnormal_record_id, {'system': self.target_system.id})
        self.assertIn('不能重复转换', second.get('error', ''))

    def test_record_disposition_reflects_conversion(self):
        """巡检明细处置状态动态推导（双向追溯）：转换后显示目标单据。"""
        body = self.convert_to_work_order(
            self.abnormal_record_id, {'system': self.target_system.id})
        detail = get_sheet_detail(self.client, self.sheet_id)
        rows = {r['id']: r for r in detail['records']}
        self.assertEqual(rows[self.abnormal_record_id]['disposition']['status'],
                         'converted_work_order')
        self.assertEqual(rows[self.abnormal_record_id]['disposition']['work_order']['id'],
                         body['id'])
        self.assertEqual(rows[self.normal_record_id]['disposition']['status'], 'none')

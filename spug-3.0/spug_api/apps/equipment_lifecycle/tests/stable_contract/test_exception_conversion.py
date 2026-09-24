# -*- coding: utf-8 -*-
"""异常转单与来源追溯（步骤 3.3）稳定契约测试。

覆盖任务二十四要求的转换行为契约：故障生成维修工单（多张 + 幂等）、
台账异常转故障 / 直接转工单（条件、幂等、重新处置）、来源与目标双向追溯、
处置状态动态计算。转换必须复用步骤 3.1 的正式故障创建服务（同一事务）。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
from django.test import TestCase

from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    OperationLedger,
    OperationLedgerItem,
    SystemFault,
    SystemWorkOrder,
)

from apps.equipment_lifecycle.tests.base import (
    ALL_CONFIG_PERMS, ALL_SYSTEM_PERMS, make_client, make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS, entry_payload, item_payload,
    ledger_payload, make_ledger_user, post_json,
)
from apps.equipment_lifecycle.tests.stable_contract.test_fault_management import (
    ALL_FAULT_PERMS, fault_payload,
)
from apps.equipment_lifecycle.tests.stable_contract.test_work_orders import (
    ALL_WO_PERMS, WorkOrderTestBase, work_order_payload,
)

ALL_HANDLE_PERMS = ALL_LEDGER_PERMS + [
    'equipment_lifecycle.ledger.handle_exception',
]

CONVERT_FAULT_URL = '/equipment-lifecycle/ledgers/{ledger}/items/{item}/convert-to-fault/'
CONVERT_WO_URL = '/equipment-lifecycle/ledgers/{ledger}/items/{item}/convert-to-work-order/'
FAULT_WORK_ORDERS_URL = '/equipment-lifecycle/faults/{pk}/work-orders/'


class ConversionTestBase(WorkOrderTestBase):
    """在工单夹具之上叠加台账权限用户与台账创建工具。"""

    def setUp(self):
        super().setUp()
        # 转单动作要求"处置权限 + 故障/工单新增权限"双权限，给主用户补齐处置权限
        self.admin.set_perms_cache(
            set(ALL_FAULT_PERMS + ALL_WO_PERMS + ALL_HANDLE_PERMS), version=0)
        self.ledger_user = make_ledger_user(
            'cv_ledger_user',
            perms=ALL_HANDLE_PERMS + ALL_SYSTEM_PERMS + ALL_CONFIG_PERMS,
            tenant_id='tenant_a')
        self.other_ledger_user = make_ledger_user(
            'cv_ledger_user_b', perms=ALL_HANDLE_PERMS + ALL_SYSTEM_PERMS + ALL_WO_PERMS,
            tenant_id='tenant_b')

    def make_submitted_ledger(self, system=None, user=None, item_overrides=None,
                              abnormal_count=1, normal_count=0):
        """经 API 创建并提交一张含异常明细的台账，返回 (ledger_id, abnormal_item_ids)。"""
        system = system or self.system_a
        user = user or self.ledger_user
        entries_items = []
        for i in range(normal_count):
            entries_items.append(item_payload(item_name=f'正常项{i}'))
        for i in range(abnormal_count):
            override = dict(abnormal_desc='电压偏低', onsite_action='已紧固接线')
            override.update(item_overrides or {})
            entries_items.append(item_payload(
                item_name=f'电源电压测量{i}', input_type='number', value_text='',
                value_number=50,
                result='abnormal', **override))
        payload = ledger_payload(
            [entry_payload(system.id, entries_items)])
        client = make_client(user)
        body = post_json(client, '/equipment-lifecycle/ledgers/', payload).json()
        self.assertFalse(body.get('error'), body)
        ledger_id = body['data']['id']
        resp = client.post(f'/equipment-lifecycle/ledgers/{ledger_id}/submit/', {},
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        ledger = OperationLedger.objects.get(pk=ledger_id)
        abnormal_ids = list(ledger.items.filter(result='abnormal')
                            .order_by('id').values_list('id', flat=True))
        return ledger_id, abnormal_ids

    def convert_to_fault(self, ledger_id, item_id, user=None, payload=None, expect_error=None):
        client = make_client(user or self.admin)
        resp = client.post(
            CONVERT_FAULT_URL.format(ledger=ledger_id, item=item_id),
            payload or {}, content_type='application/json')
        body = resp.json()
        if expect_error is not None:
            self.assertIn(expect_error, body.get('error', ''), body)
        return body

    def convert_to_work_order(self, ledger_id, item_id, user=None, payload=None,
                              expect_error=None):
        client = make_client(user or self.admin)
        base = {
            'title': '异常直接处置工单',
            'work_type': 'special_maintenance',
            'client_token': '',
        }
        base.update(payload or {})
        resp = client.post(
            CONVERT_WO_URL.format(ledger=ledger_id, item=item_id),
            base, content_type='application/json')
        body = resp.json()
        if expect_error is not None:
            self.assertIn(expect_error, body.get('error', ''), body)
        return body


class FaultToWorkOrderTest(ConversionTestBase):
    """20/21/22/31：故障生成维修工单。"""

    def create_fault_with_impacts(self):
        client = make_client(self.admin)
        body = client.post('/equipment-lifecycle/faults/', fault_payload(
            self.system_a, impact_status='fault'),
            content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        return SystemFault.objects.get(pk=body['data']['id'])

    def test_fault_can_generate_multiple_work_orders(self):
        """20. 一个故障允许根据实际需要生成多张维修工单。"""
        fault = self.create_fault_with_impacts()
        client = make_client(self.admin)
        first = client.post(
            f'/equipment-lifecycle/faults/{fault.id}/create-work-order/',
            {'client_token': 'tok-fault-1'}, content_type='application/json').json()
        self.assertFalse(first.get('error'), first)
        second = client.post(
            f'/equipment-lifecycle/faults/{fault.id}/create-work-order/',
            {'client_token': 'tok-fault-2'}, content_type='application/json').json()
        self.assertFalse(second.get('error'), second)
        orders = SystemWorkOrder.objects.filter(source_type='fault', source_fault=fault)
        self.assertEqual(orders.count(), 2)
        # 默认类型为故障维修，作业系统固定为故障所属系统；
        # 影响运行默认为"否"（部件离线维修不影响系统状态，见 test_health_split.py）
        first_order = orders.order_by('id').first()
        self.assertEqual(first_order.work_type, 'repair')
        self.assertEqual(first_order.system_id, fault.system_id)
        self.assertFalse(first_order.affects_system_operation)
        # 现象带入作业要求
        self.assertEqual(first_order.work_requirement, fault.phenomenon)

    def test_duplicate_fault_convert_request_idempotent(self):
        """21. 重复故障转工单请求不产生重复工单（同 client_token 返回已有工单）。"""
        fault = self.create_fault_with_impacts()
        client = make_client(self.admin)
        first = client.post(
            f'/equipment-lifecycle/faults/{fault.id}/create-work-order/',
            {'client_token': 'tok-idem-1'}, content_type='application/json').json()
        second = client.post(
            f'/equipment-lifecycle/faults/{fault.id}/create-work-order/',
            {'client_token': 'tok-idem-1'}, content_type='application/json').json()
        self.assertFalse(first.get('error'), first)
        self.assertFalse(second.get('error'), second)
        self.assertEqual(first['data']['id'], second['data']['id'])
        self.assertEqual(
            SystemWorkOrder.objects.filter(source_type='fault', source_fault=fault).count(), 1)

    def test_cancelled_fault_cannot_generate_order(self):
        """20 补充：已作废故障不能生成工单。"""
        fault = self.create_fault_with_impacts()
        make_client(self.admin).post(f'/equipment-lifecycle/faults/{fault.id}/cancel/',
                                     {'cancel_reason': '误报'},
                                     content_type='application/json')
        resp = make_client(self.admin).post(
            f'/equipment-lifecycle/faults/{fault.id}/create-work-order/',
            {'client_token': 'tok-x'}, content_type='application/json')
        self.assertIn('已作废', resp.json().get('error', ''), resp.content)

    def test_order_completion_does_not_close_fault(self):
        """22. 工单完成/关闭不自动关闭来源故障，故障恢复仍由 3.1 流程确认。"""
        fault = self.create_fault_with_impacts()
        make_client(self.admin).post(f'/equipment-lifecycle/faults/{fault.id}/start/', {},
                                     content_type='application/json')
        resp = make_client(self.admin).post(
            f'/equipment-lifecycle/faults/{fault.id}/create-work-order/',
            {'client_token': 'tok-flow'}, content_type='application/json').json()
        oid = resp['data']['id']
        client = make_client(self.admin)
        self.dispatch_order(oid)
        self.accept_order(oid)
        self.start_order(oid)
        self.add_record(oid)
        self.submit_review(oid)
        client.post(f'/equipment-lifecycle/work-orders/{oid}/review-pass/', {},
                    content_type='application/json')
        client.post(f'/equipment-lifecycle/work-orders/{oid}/close/', {},
                    content_type='application/json')
        fault.refresh_from_db()
        # 故障仍处于处置中，来源影响保持
        self.assertEqual(fault.status, 'handling')
        system = LifecycleSystem.objects.get(pk=self.system_a.id)
        self.assertEqual(system.health_status, 'fault')

    def test_fault_and_orders_bidirectionally_traceable(self):
        """31. 故障与来源工单双向可追溯。"""
        fault = self.create_fault_with_impacts()
        resp = make_client(self.admin).post(
            f'/equipment-lifecycle/faults/{fault.id}/create-work-order/',
            {'client_token': 'tok-trace'}, content_type='application/json').json()
        oid = resp['data']['id']
        # 工单 → 来源故障
        detail = make_client(self.admin).get(f'/equipment-lifecycle/work-orders/{oid}/').json()['data']
        self.assertEqual(detail['source_type'], 'fault')
        self.assertEqual(detail['source_fault'], fault.id)
        self.assertEqual(detail['source_no'], fault.fault_no)
        # 故障 → 生成工单列表
        resp = make_client(self.admin).get(FAULT_WORK_ORDERS_URL.format(pk=fault.id))
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertIn(oid, [row['id'] for row in resp.json()['data']['data']])

    def test_fault_work_orders_requires_both_perms(self):
        """31 补充：按故障查工单需要工单查看 + 故障查看双权限。"""
        fault = self.create_fault_with_impacts()
        # 无 fault.view 的工单用户
        wo_only = make_user('cv_wo_only', ALL_WO_PERMS, tenant_id='tenant_a')
        resp = make_client(wo_only).get(FAULT_WORK_ORDERS_URL.format(pk=fault.id))
        self.assertIn('权限拒绝', resp.json().get('error', ''), resp.content)


class LedgerItemConvertToFaultTest(ConversionTestBase):
    """23/25/26/28/30：台账异常明细转故障。"""

    def test_abnormal_item_can_convert_to_fault(self):
        """23. 异常台账明细可以转故障（调用正式故障创建服务，同一事务）。"""
        ledger_id, item_ids = self.make_submitted_ledger()
        body = self.convert_to_fault(ledger_id, item_ids[0])
        self.assertFalse(body.get('error'), body)
        fault = SystemFault.objects.get(pk=body['data']['id'])
        # 故障系统固定为明细所属系统
        self.assertEqual(fault.system_id, self.system_a.id)
        self.assertEqual(fault.status, 'pending')
        # 来源关系：真实外键 + 来源类型
        self.assertEqual(fault.source_type, 'ledger_item')
        self.assertEqual(fault.source_ledger_item_id, item_ids[0])
        self.assertEqual(fault.source_id, str(item_ids[0]))
        # 带入台账上下文（现象含台账编号/项目名）
        self.assertIn('EL-', fault.phenomenon)
        # 默认"部件故障但不影响系统运行"：系统健康状态保持正常（同事务重算）
        self.assertFalse(fault.affects_system_operation)
        self.assertEqual(fault.impact_status, '')
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')

    def test_non_abnormal_item_cannot_convert(self):
        """25. 正常、不适用或待复核明细不能转单。"""
        payload = ledger_payload([entry_payload(self.system_a.id, [
            item_payload(item_name='正常检查', result='normal'),
            item_payload(item_name='不适用检查', result='not_applicable', na_reason='本期不适用'),
            item_payload(item_name='待复核检查', result='pending_review'),
        ])])
        body = post_json(make_client(self.ledger_user), '/equipment-lifecycle/ledgers/',
                         payload).json()
        self.assertFalse(body.get('error'), body)
        lid = body['data']['id']
        make_client(self.ledger_user).post(f'/equipment-lifecycle/ledgers/{lid}/submit/', {},
                                           content_type='application/json')
        ledger = OperationLedger.objects.get(pk=lid)
        for item in ledger.items.all():
            self.convert_to_fault(lid, item.id, expect_error='只有结果为"异常"的明细可以转单')
            self.convert_to_work_order(lid, item.id, expect_error='只有结果为"异常"的明细可以转单')
        self.assertEqual(SystemFault.objects.count(), 0)
        self.assertEqual(SystemWorkOrder.objects.count(), 0)

    def test_non_submitted_ledger_cannot_convert(self):
        """26. 草稿、退回或作废台账不能转单。"""
        # 草稿（不提交）
        payload = ledger_payload([entry_payload(self.system_a.id, [
            item_payload(item_name='电压检查', input_type='number', value_text='',
                         value_number=50,
                         result='abnormal', abnormal_desc='偏低'),
        ])])
        body = post_json(make_client(self.ledger_user), '/equipment-lifecycle/ledgers/',
                         payload).json()
        draft_id = body['data']['id']
        ledger = OperationLedger.objects.get(pk=draft_id)
        draft_item = ledger.items.filter(result='abnormal').first()
        self.convert_to_fault(draft_id, draft_item.id, expect_error='不能转单')
        self.assertEqual(SystemFault.objects.count(), 0)
        # 作废
        make_client(self.ledger_user).post(
            f'/equipment-lifecycle/ledgers/{draft_id}/submit/', {},
            content_type='application/json')
        make_client(self.admin).post(
            f'/equipment-lifecycle/ledgers/{draft_id}/void/',
            {'reason': '误录入'}, content_type='application/json')
        self.convert_to_fault(draft_id, draft_item.id, expect_error='不能转单')

    def test_duplicate_conversion_rejected(self):
        """28. 同一异常重复转故障不会产生重复故障；默认只允许直接生成一张。"""
        ledger_id, item_ids = self.make_submitted_ledger()
        first = self.convert_to_fault(ledger_id, item_ids[0])
        self.assertFalse(first.get('error'), first)
        second = self.convert_to_fault(ledger_id, item_ids[0])
        self.assertTrue(second.get('error'))
        self.assertIn('不能重复转换', second['error'])
        self.assertEqual(
            SystemFault.objects.filter(source_ledger_item_id=item_ids[0]).count(), 1)

    def test_redispose_after_target_cancelled_requires_reason(self):
        """28 补充：处置目标作废后重新转故障必须填写重新处置原因。"""
        ledger_id, item_ids = self.make_submitted_ledger()
        first = self.convert_to_fault(ledger_id, item_ids[0])
        fault = SystemFault.objects.get(pk=first['data']['id'])
        make_client(self.admin).post(f'/equipment-lifecycle/faults/{fault.id}/cancel/',
                                     {'cancel_reason': '误判异常'},
                                     content_type='application/json')
        # 不带原因 → 拒绝
        self.convert_to_fault(ledger_id, item_ids[0],
                              expect_error='重新处置')
        # 带原因 → 允许
        second = self.convert_to_fault(ledger_id, item_ids[0],
                                       payload={'re_dispose_reason': '首次判断有误，复核确认异常'})
        self.assertFalse(second.get('error'), second)
        self.assertEqual(
            SystemFault.objects.filter(source_ledger_item_id=item_ids[0]).count(), 2)

    def test_ledger_and_fault_bidirectionally_traceable(self):
        """30. 台账与目标故障双向可追溯；处置状态动态展示。"""
        ledger_id, item_ids = self.make_submitted_ledger(normal_count=1)
        body = self.convert_to_fault(ledger_id, item_ids[0])
        fid = body['data']['id']
        # 故障 → 来源台账明细
        detail = make_client(self.admin).get(f'/equipment-lifecycle/faults/{fid}/').json()['data']
        self.assertEqual(detail['source_ledger_item'], item_ids[0])
        self.assertEqual(detail['source_ledger'], ledger_id)
        self.assertTrue(detail['source_ledger_no'])
        # 台账明细 → 生成故障（处置状态由来源关系动态计算）
        ledger_detail = make_client(self.admin).get(
            f'/equipment-lifecycle/ledgers/{ledger_id}/').json()['data']
        item_view = next(i for i in ledger_detail['items'] if i['id'] == item_ids[0])
        self.assertEqual(item_view['disposition']['status'], 'converted_fault')
        self.assertEqual(item_view['disposition']['fault']['id'], fid)
        # 未处置明细保持未处置
        other_item = next(i for i in ledger_detail['items'] if i['id'] != item_ids[0]
                          and i['result'] != 'abnormal')
        self.assertEqual(other_item['disposition']['status'], 'none')
        # 明细本身不被修改（结果、异常说明保持）
        item_row = OperationLedgerItem.objects.get(pk=item_ids[0])
        self.assertEqual(item_row.result, 'abnormal')
        self.assertEqual(item_row.abnormal_desc, '电压偏低')


class LedgerItemConvertToWorkOrderTest(ConversionTestBase):
    """24/27/29：台账异常明细直接转工单。"""

    def test_abnormal_item_can_convert_to_work_order(self):
        """24. 异常台账明细可以直接转工单（类型由用户明确选择）。"""
        ledger_id, item_ids = self.make_submitted_ledger()
        body = self.convert_to_work_order(ledger_id, item_ids[0], payload={
            'work_type': 'special_maintenance', 'client_token': 'tok-li-1'})
        self.assertFalse(body.get('error'), body)
        order = SystemWorkOrder.objects.get(pk=body['data']['id'])
        # 作业系统固定为明细所属系统
        self.assertEqual(order.system_id, self.system_a.id)
        self.assertEqual(order.work_type, 'special_maintenance')
        self.assertEqual(order.source_type, 'ledger_item')
        self.assertEqual(order.source_ledger_item_id, item_ids[0])
        self.assertTrue(order.source_no)
        # 带入台账上下文（异常说明 + 实测值 + 现场处理组装为作业要求）
        self.assertIn('电压偏低', order.work_requirement)
        self.assertIn('50.0', order.work_requirement)
        self.assertIn('已紧固接线', order.work_requirement)
        # 直接转工单不产生故障
        self.assertEqual(SystemFault.objects.count(), 0)

    def test_one_conversion_creates_only_one_kind(self):
        """27. 同一异常不能在一次处置中同时直接创建故障和工单。"""
        ledger_id, item_ids = self.make_submitted_ledger()
        self.convert_to_fault(ledger_id, item_ids[0])
        # 转故障接口只创建了故障，没有创建工单
        self.assertEqual(SystemWorkOrder.objects.filter(
            source_ledger_item_id=item_ids[0]).count(), 0)
        # 转工单接口只创建了工单，没有创建故障
        lid2, items2 = self.make_submitted_ledger()
        self.convert_to_work_order(lid2, items2[0])
        self.assertEqual(SystemFault.objects.filter(
            source_ledger_item_id=items2[0]).count(), 0)

    def test_duplicate_work_order_conversion_rejected_or_idempotent(self):
        """29. 同一异常重复转工单不会产生重复工单（拒绝；同 token 幂等返回已有）。"""
        ledger_id, item_ids = self.make_submitted_ledger()
        first = self.convert_to_work_order(ledger_id, item_ids[0],
                                           payload={'client_token': 'tok-wo-x'})
        self.assertFalse(first.get('error'), first)
        # 不同 token 重复转 → 拒绝
        second = self.convert_to_work_order(ledger_id, item_ids[0],
                                            payload={'client_token': 'tok-wo-y'})
        self.assertTrue(second.get('error'))
        self.assertIn('不能重复转换', second['error'])
        # 相同 token 重复提交 → 幂等返回已有工单
        third = self.convert_to_work_order(ledger_id, item_ids[0],
                                           payload={'client_token': 'tok-wo-x'})
        self.assertFalse(third.get('error'), third)
        self.assertEqual(third['data']['id'], first['data']['id'])
        self.assertEqual(
            SystemWorkOrder.objects.filter(source_ledger_item_id=item_ids[0]).count(), 1)

    def test_convert_to_order_after_active_fault_requires_reason(self):
        """29 补充：已转故障的异常直接转工单须填写重新处置原因（设计路径为故障→工单）。"""
        ledger_id, item_ids = self.make_submitted_ledger()
        self.convert_to_fault(ledger_id, item_ids[0])
        # 不带原因 → 拒绝
        self.convert_to_work_order(ledger_id, item_ids[0], expect_error='重新处置原因')
        # 带原因 → 允许
        body = self.convert_to_work_order(
            ledger_id, item_ids[0],
            payload={'re_dispose_reason': '故障未认定成立，改走专项维护'},
            expect_error=None)
        self.assertFalse(body.get('error'), body)

    def test_conversion_dual_permission_enforced(self):
        """40 补充：转单双权限（处置权限 + 故障/工单新增权限）后端独立校验。"""
        ledger_id, item_ids = self.make_submitted_ledger()
        # 只有处置权限，无故障新增权限 → 转故障拒绝
        handle_only = make_user('cv_handle_only', ALL_HANDLE_PERMS + ALL_SYSTEM_PERMS,
                                tenant_id='tenant_a')
        self.convert_to_fault(ledger_id, item_ids[0], user=handle_only,
                              expect_error='权限拒绝')
        # 只有处置权限，无工单新增权限 → 转工单拒绝
        self.convert_to_work_order(ledger_id, item_ids[0], user=handle_only,
                                   expect_error='权限拒绝')
        # 无处置权限的工单用户 → 拒绝
        wo_only = make_user('cv_wo_only2', ALL_WO_PERMS + ALL_SYSTEM_PERMS,
                            tenant_id='tenant_a')
        self.convert_to_work_order(ledger_id, item_ids[0], user=wo_only,
                                   expect_error='权限拒绝')
        self.assertEqual(SystemFault.objects.count(), 0)
        self.assertEqual(SystemWorkOrder.objects.count(), 0)

    def test_cross_tenant_conversion_rejected(self):
        """3 补充：跨租户的台账明细不能转单（tenant_b 用户访问 tenant_b 的台账，
        tenant_a 用户不可见）。"""
        ledger_id, item_ids = self.make_submitted_ledger(
            system=self.system_b, user=self.other_ledger_user)
        # tenant_a 管理员访问 tenant_b 台账明细 → 不存在
        self.convert_to_fault(ledger_id, item_ids[0], expect_error='不存在')
        self.convert_to_work_order(ledger_id, item_ids[0], expect_error='不存在')

    def test_disposition_states_cover_all_cases(self):
        """15 补充：未处置/已转故障/已转工单/目标已取消 动态计算。"""
        ledger_id, item_ids = self.make_submitted_ledger(abnormal_count=2)
        # 未处置
        detail = make_client(self.admin).get(
            f'/equipment-lifecycle/ledgers/{ledger_id}/').json()['data']
        disp0 = next(i for i in detail['items'] if i['id'] == item_ids[0])['disposition']
        disp1 = next(i for i in detail['items'] if i['id'] == item_ids[1])['disposition']
        self.assertEqual(disp0['status'], 'none')
        # 已转工单
        self.convert_to_work_order(ledger_id, item_ids[0])
        detail = make_client(self.admin).get(
            f'/equipment-lifecycle/ledgers/{ledger_id}/').json()['data']
        disp0 = next(i for i in detail['items'] if i['id'] == item_ids[0])['disposition']
        self.assertEqual(disp0['status'], 'converted_work_order')
        # 已转故障（另一条明细）
        self.convert_to_fault(ledger_id, item_ids[1])
        detail = make_client(self.admin).get(
            f'/equipment-lifecycle/ledgers/{ledger_id}/').json()['data']
        disp1 = next(i for i in detail['items'] if i['id'] == item_ids[1])['disposition']
        self.assertEqual(disp1['status'], 'converted_fault')
        # 目标已取消
        order = SystemWorkOrder.objects.get(pk=disp0['work_order']['id'])
        make_client(self.admin).post(f'/equipment-lifecycle/work-orders/{order.id}/cancel/',
                                     {'cancel_reason': '计划变更'},
                                     content_type='application/json')
        detail = make_client(self.admin).get(
            f'/equipment-lifecycle/ledgers/{ledger_id}/').json()['data']
        disp0 = next(i for i in detail['items'] if i['id'] == item_ids[0])['disposition']
        self.assertEqual(disp0['status'], 'target_cancelled')


class ManualWorkOrderSourceIntegrityTest(ConversionTestBase):
    """7 补充：人工工单不能伪造来源。"""

    def test_manual_order_cannot_forge_source(self):
        payload = work_order_payload(self.system_a)
        payload['source_type'] = 'fault'  # 试图伪造来源
        payload['source_no'] = 'GZ20260918-0001'
        body = self.create_order_ok(payload)
        order = SystemWorkOrder.objects.get(pk=body['id'])
        # 后端忽略来源字段：人工创建保持 manual 且无来源对象
        self.assertEqual(order.source_type, 'manual')
        self.assertIsNone(order.source_fault_id)
        self.assertIsNone(order.source_ledger_item_id)
        self.assertEqual(order.source_no, '')
        # 来源一致性 DB 约束存在
        constraint_names = [c.name for c in SystemWorkOrder._meta.constraints]
        self.assertIn('el_work_order_source_consistent', constraint_names)

    def test_manual_order_rejects_client_token_replay(self):
        """幂等：同 token 重复创建人工工单返回已有工单。"""
        payload = work_order_payload(self.system_a, title='幂等工单')
        payload['client_token'] = 'tok-manual-1'
        first = self.create_order_ok(payload)
        second = self.create_order_ok(payload)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(SystemWorkOrder.objects.count(), 1)

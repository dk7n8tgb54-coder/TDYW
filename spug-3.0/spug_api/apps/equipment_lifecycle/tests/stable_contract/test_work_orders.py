# -*- coding: utf-8 -*-
"""工单管理与系统健康状态联动（步骤 3.3，单账号协同流程）稳定契约测试。

覆盖工单行为契约：系统 ID 关联、租户隔离、一张工单只关联一个作业系统、
受影响系统参数已删除、快照、状态流转（创建即执行中 → 完成工单 → 关闭/
受控取消）、幂等、affects_system_operation（作业期间是否影响系统运行）
与"维修中"联动、模块边界（无库存/调拨、device/upgrade 无变化）与
3.1/3.2 回归冒烟。派发/接单/复核环节已整体下线（单账号流程）。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
from unittest import mock

from django.apps import apps
from django.test import TestCase
from django.utils import timezone

from apps.equipment_lifecycle import fault_services
from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemFault,
    SystemWorkOrder,
    SystemWorkOrderHandlingRecord,
)

from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS, make_client, make_system, make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.test_fault_management import (
    ALL_FAULT_PERMS, fault_payload,
)

WORK_ORDER_URL = '/equipment-lifecycle/work-orders'

ALL_WO_PERMS = [
    'equipment_lifecycle.work_order.view', 'equipment_lifecycle.work_order.add',
    'equipment_lifecycle.work_order.edit', 'equipment_lifecycle.work_order.execute',
    'equipment_lifecycle.work_order.close',
    'equipment_lifecycle.work_order.del', 'equipment_lifecycle.work_order.export',
]


def work_order_payload(system_obj, **overrides):
    payload = {
        'title': f'{system_obj.system_code} 例行维护工单',
        'work_type': 'special_maintenance',
        'priority': 'normal',
        'system': system_obj.id,
        'affects_system_operation': False,
        'work_location': '机房A 01柜',
        'work_object_desc': '主用交换机',
        'work_requirement': '按规程完成季度维护',
        'client_token': '',
    }
    payload.update(overrides)
    return payload


class WorkOrderTestBase(TestCase):
    """公共夹具：两个租户、可用/停用系统、工单与故障全权限用户。"""

    def setUp(self):
        self.admin = make_user('wo_admin', ALL_SYSTEM_PERMS + ALL_FAULT_PERMS + ALL_WO_PERMS,
                               tenant_id='tenant_a')
        self.other_admin = make_user('wo_admin_b', ALL_SYSTEM_PERMS + ALL_FAULT_PERMS + ALL_WO_PERMS,
                                     tenant_id='tenant_b')
        self.noperm_user = make_user('wo_noperm', ALL_SYSTEM_PERMS, tenant_id='tenant_a')
        self.worker = make_user('wo_worker', ALL_SYSTEM_PERMS + ALL_WO_PERMS, tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.system_a = make_system(self.admin, tenant_id='tenant_a',
                                    system_code='SYS-A1', name='烟台通信系统', install_location='机房A')
        self.system_a2 = make_system(self.admin, tenant_id='tenant_a',
                                     system_code='SYS-A2', name='威海监控系统', install_location='机房B')
        self.system_b = make_system(self.other_admin, tenant_id='tenant_b',
                                    system_code='SYS-B1',
                                    name='烟台通信系统', install_location='机房A-B')

    # ---------- 便捷方法 ----------
    def create_order(self, payload, user=None, expect_error=None):
        client = make_client(user or self.admin)
        resp = client.post(f'{WORK_ORDER_URL}/', payload, content_type='application/json')
        body = resp.json()
        if expect_error is not None:
            self.assertIn(expect_error, body.get('error', ''), body)
        return body

    def create_order_ok(self, payload, user=None):
        body = self.create_order(payload, user=user)
        self.assertFalse(body.get('error'), body)
        return body['data']

    def add_record(self, oid, user=None, expect_error=None, **overrides):
        client = make_client(user or self.admin)
        payload = {
            'handled_at': '2026-09-18 10:00',
            'content': '现场检查并更换板卡',
            'result': '处理完成',
            'work_hours': 1.5,
        }
        payload.update(overrides)
        resp = client.post(f'{WORK_ORDER_URL}/{oid}/handling-records/', payload,
                           content_type='application/json')
        body = resp.json()
        if expect_error is not None:
            self.assertIn(expect_error, body.get('error', ''), body)
        return body

    def complete_order(self, oid, user=None, expect_error=None, **overrides):
        """完成工单（执行中 → 已完成）。"""
        client = make_client(user or self.admin)
        payload = {'process_result': '已完成全部作业步骤，系统恢复正常', 'work_hours': 3.0}
        payload.update(overrides)
        resp = client.post(f'{WORK_ORDER_URL}/{oid}/complete/', payload,
                           content_type='application/json')
        body = resp.json()
        if expect_error is not None:
            self.assertIn(expect_error, body.get('error', ''), body)
        return body

    def run_to_executing(self, system=None, work_type='repair', user=None, affects=True,
                         **overrides):
        """创建工单并返回模型实例（单账号流程：创建即执行中，自动记录 actual_start）。

        affects 映射为 affects_system_operation（默认 True：执行中影响运行）。
        """
        system = system or self.system_a
        data = self.create_order_ok(work_order_payload(
            system, work_type=work_type,
            affects_system_operation=affects, **overrides), user=user)
        order = SystemWorkOrder.objects.get(pk=data['id'])
        self.assertEqual(order.status, SystemWorkOrder.STATUS_EXECUTING)
        self.assertIsNotNone(order.actual_start)
        return order

    def run_to_completed(self, system=None, work_type='repair', user=None, affects=True,
                         **overrides):
        """创建 → 处理记录 → 完成工单，返回工单模型实例。"""
        order = self.run_to_executing(system=system, work_type=work_type, user=user,
                                      affects=affects, **overrides)
        self.add_record(order.id, user=user)
        self.complete_order(order.id, user=user)
        order.refresh_from_db()
        self.assertEqual(order.status, SystemWorkOrder.STATUS_COMPLETED)
        return order

    def create_active_fault(self, system, impact='degraded'):
        """创建一张未恢复的有效故障（影响保持）。"""
        client = make_client(self.admin)
        resp = client.post('/equipment-lifecycle/faults/', fault_payload(
            system, impact_status=impact), content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return SystemFault.objects.get(pk=body['data']['id'])


class WorkOrderCreateValidationTest(WorkOrderTestBase):
    """工单创建校验。"""

    def test_order_requires_valid_system_id(self):
        """工单必须关联有效作业系统ID。"""
        self.create_order(work_order_payload(self.system_a, system=99999),
                          expect_error='作业系统不存在')
        self.assertEqual(SystemWorkOrder.objects.count(), 0)

    def test_system_name_is_not_a_join_key(self):
        """系统名称不能作为关联键：以名称提交必须失败且不产生模糊匹配。"""
        payload = work_order_payload(self.system_a)
        payload['system'] = self.system_a.name  # 名称而非 ID
        self.create_order(payload, expect_error=None)
        self.assertEqual(SystemWorkOrder.objects.count(), 0)

    def test_cannot_link_cross_tenant_system(self):
        """不能关联其他租户系统。"""
        self.create_order(work_order_payload(self.system_b), expect_error='作业系统不存在')
        self.assertEqual(SystemWorkOrder.objects.count(), 0)

    def test_affected_system_ids_param_rejected(self):
        """工单 API 不再接受受影响系统（POST/PUT 均拒绝，不静默忽略）。"""
        self.create_order(work_order_payload(
            self.system_a, affected_system_ids=[self.system_a2.id]),
            expect_error='受影响系统')
        self.assertEqual(SystemWorkOrder.objects.count(), 0)
        # 编辑同样拒绝
        data = self.create_order_ok(work_order_payload(self.system_a))
        client = make_client(self.admin)
        resp = client.put(f'{WORK_ORDER_URL}/{data["id"]}/',
                          work_order_payload(self.system_a,
                                             affected_system_ids=[self.system_a2.id]),
                          content_type='application/json')
        self.assertIn('受影响系统', resp.json().get('error', ''), resp.content)
        order = SystemWorkOrder.objects.get(pk=data['id'])
        # 工单仍只关联原作业系统
        self.assertEqual(order.system_id, self.system_a.id)
        self.assertFalse(
            any(rel.get_accessor_name() == 'affected_systems'
                for rel in SystemWorkOrder._meta.related_objects))

    def test_one_order_links_exactly_one_system(self):
        """一张工单只关联一个作业系统。"""
        data = self.create_order_ok(work_order_payload(self.system_a))
        order = SystemWorkOrder.objects.get(pk=data['id'])
        self.assertEqual(order.system_id, self.system_a.id)
        self.assertNotEqual(order.system_id, self.system_a2.id)

    def test_affects_system_operation_must_be_bool(self):
        """affects_system_operation 非布尔提交被后端重新校验拒绝。"""
        self.create_order(work_order_payload(
            self.system_a, affects_system_operation='yes'),
            expect_error='affects_system_operation')
        self.assertEqual(SystemWorkOrder.objects.count(), 0)

    def test_create_without_component_and_device_resume(self):
        """配置组成项已下线、无设备档案仍可创建工单。"""
        data = self.create_order_ok(work_order_payload(self.system_a))
        self.assertNotIn('work_component', data)
        self.assertEqual(data['work_component_name'], '')
        self.assertEqual(data['work_type'], 'special_maintenance')
        self.assertFalse(data['affects_system_operation'])

    def test_work_no_unique_within_tenant(self):
        """工单编号租户内唯一且自动生成。"""
        first = self.create_order_ok(work_order_payload(self.system_a, title='工单一'))
        second = self.create_order_ok(work_order_payload(self.system_a, title='工单二'))
        self.assertNotEqual(first['work_no'], second['work_no'])
        self.assertTrue(first['work_no'].startswith('WO'))
        constraint_names = [c.name for c in SystemWorkOrder._meta.constraints]
        self.assertIn('uniq_el_work_order_tenant_no', constraint_names)


class WorkOrderSystemLinkTest(WorkOrderTestBase):
    """外键有效性 + 快照。"""

    def test_snapshot_stable_after_system_rename(self):
        """系统改名后工单外键仍有效，详情显示创建时快照。"""
        data = self.create_order_ok(work_order_payload(self.system_a))
        oid = data['id']
        system = LifecycleSystem.objects.get(pk=self.system_a.id)
        old_name, old_code, old_location = system.name, system.system_code, system.install_location
        system.name = '改名后的系统'
        system.install_location = '新机房Z'
        system.save(update_fields=['name', 'install_location'])

        client = make_client(self.admin)
        detail = client.get(f'{WORK_ORDER_URL}/{oid}/').json()['data']
        # 外键仍然有效（返回正式系统 ID）
        self.assertEqual(detail['system'], self.system_a.id)
        # 快照保持创建时内容，不随系统改名变化
        self.assertEqual(detail['system_name'], old_name)
        self.assertEqual(detail['system_code'], old_code)
        self.assertEqual(detail['system_location'], old_location)


class WorkOrderStateFlowTest(WorkOrderTestBase):
    """单账号协同流程状态流转（创建即执行中 → 完成 → 关闭；取消受控）。"""

    def test_created_order_is_executing_with_actual_start(self):
        """新工单创建即执行中，自动记录实际开始时间，不要求负责人/参与人。"""
        data = self.create_order_ok(work_order_payload(self.system_a))
        order = SystemWorkOrder.objects.get(pk=data['id'])
        self.assertEqual(order.status, SystemWorkOrder.STATUS_EXECUTING)
        self.assertIsNotNone(order.actual_start)
        self.assertIsNone(order.owner_id)
        self.assertFalse(order.participants.exists())
        # 不写派发/接单/复核历史字段
        self.assertIsNone(order.dispatched_by_id)
        self.assertIsNone(order.dispatched_at)
        self.assertIsNone(order.accepted_by_id)
        self.assertIsNone(order.accepted_at)
        self.assertIsNone(order.reviewer_id)
        self.assertIsNone(order.reviewed_at)
        # 历史字段未被删除（模型仍保留，可展示历史工单）
        field_names = {f.name for f in SystemWorkOrder._meta.get_fields()}
        for legacy in ('owner', 'dispatched_by', 'dispatched_at', 'accepted_by',
                       'accepted_at', 'reviewer', 'reviewed_at'):
            self.assertIn(legacy, field_names)

    def test_legacy_dispatch_accept_start_routes_removed(self):
        """派发/接单/开始执行/复核路由已下线：请求 404 且不产生状态变化。"""
        data = self.create_order_ok(work_order_payload(self.system_a))
        client = make_client(self.admin)
        for action, payload in (
                ('dispatch', {'owner_id': self.other_admin.id}),
                ('accept', {}),
                ('start', {}),
                ('submit-review', {'process_result': 'x'}),
                ('review-pass', {}),
                ('review-return', {'return_reason': 'x'})):
            resp = client.post(f'{WORK_ORDER_URL}/{data["id"]}/{action}/', payload,
                               content_type='application/json')
            self.assertEqual(resp.status_code, 404, action)
        order = SystemWorkOrder.objects.get(pk=data['id'])
        self.assertEqual(order.status, SystemWorkOrder.STATUS_EXECUTING)
        self.assertIsNone(order.dispatched_by_id)

    def test_complete_requires_result_and_handling_record(self):
        """完成工单必须填写处理结果且存在处理记录。"""
        order = self.run_to_executing(work_type='special_maintenance')
        # 无处理结果
        self.complete_order(order.id, process_result='  ', expect_error='必须填写处理结果')
        # 有结果但无处理记录
        self.complete_order(order.id, expect_error='必须填写处理过程')
        # 补齐处理记录后成功
        self.add_record(order.id)
        body = self.complete_order(order.id)
        self.assertFalse(body.get('error'), body)
        order.refresh_from_db()
        self.assertEqual(order.status, SystemWorkOrder.STATUS_COMPLETED)
        self.assertIsNotNone(order.actual_end)
        self.assertEqual(order.completed_by_id, self.admin.id)
        self.assertIsNotNone(order.completed_at)
        # 不伪造复核语义
        self.assertIsNone(order.reviewer_id)
        self.assertIsNone(order.reviewed_at)

    def test_complete_only_from_executing_and_idempotent(self):
        """只有执行中的工单可以完成；重复提交被状态机拒绝（幂等）。"""
        order = self.run_to_executing(work_type='special_maintenance')
        self.add_record(order.id)
        self.complete_order(order.id)
        order.refresh_from_db()
        actual_end = order.actual_end
        # 再次完成 → 拒绝，数据不变
        self.complete_order(order.id, expect_error='只有执行中的工单可以完成工单')
        order.refresh_from_db()
        self.assertEqual(order.status, SystemWorkOrder.STATUS_COMPLETED)
        self.assertEqual(order.actual_end, actual_end)
        # 已完成不能再次追加处理记录
        self.add_record(order.id, expect_error='只有执行中的工单可以追加处理记录')
        # 已完成的工单不能取消
        resp = make_client(self.admin).post(f'{WORK_ORDER_URL}/{order.id}/cancel/',
                                            {'cancel_reason': '测试'},
                                            content_type='application/json')
        self.assertTrue(resp.json().get('error'), resp.content)
        # 完成后可关闭；关闭后终态
        resp = make_client(self.admin).post(f'{WORK_ORDER_URL}/{order.id}/close/',
                                            {}, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        order.refresh_from_db()
        self.assertEqual(order.status, SystemWorkOrder.STATUS_CLOSED)
        self.assertEqual(order.closed_by_id, self.admin.id)
        resp = make_client(self.admin).post(f'{WORK_ORDER_URL}/{order.id}/close/',
                                            {}, content_type='application/json')
        self.assertTrue(resp.json().get('error'), resp.content)

    def test_edit_executing_order_allowed(self):
        """执行中工单可普通编辑基础信息（不得修改状态）。"""
        data = self.create_order_ok(work_order_payload(self.system_a))
        client = make_client(self.admin)
        resp = client.put(f'{WORK_ORDER_URL}/{data["id"]}/',
                          work_order_payload(self.system_a2, affects_system_operation=True),
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        order = SystemWorkOrder.objects.get(pk=data['id'])
        self.assertEqual(order.system_id, self.system_a2.id)
        self.assertTrue(order.affects_system_operation)
        self.assertEqual(order.status, SystemWorkOrder.STATUS_EXECUTING)

    def test_closed_order_not_editable(self):
        """已关闭工单不能普通编辑。"""
        order = self.run_to_completed(work_type='special_maintenance')
        make_client(self.admin).post(f'{WORK_ORDER_URL}/{order.id}/close/', {},
                                     content_type='application/json')
        resp = make_client(self.admin).put(
            f'{WORK_ORDER_URL}/{order.id}/', work_order_payload(self.system_a),
            content_type='application/json')
        self.assertIn('可以编辑', resp.json().get('error', ''), resp.content)

    def test_del_is_controlled_cancel_not_physical_delete(self):
        """删除权限执行受控取消，不物理删除。"""
        data = self.create_order_ok(work_order_payload(self.system_a))
        resp = make_client(self.admin).post(f'{WORK_ORDER_URL}/{data["id"]}/cancel/',
                                            {'cancel_reason': '计划变更'},
                                            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        order = SystemWorkOrder.objects.get(pk=data['id'])
        self.assertEqual(order.status, SystemWorkOrder.STATUS_CANCELLED)
        self.assertEqual(order.cancel_reason, '计划变更')
        self.assertTrue(SystemWorkOrder.objects.filter(pk=data['id']).exists())

    def test_cancel_records_operator_and_time(self):
        """取消记录取消账号与时间，来源对象不被删除。"""
        order = self.run_to_executing(work_type='special_maintenance')
        before = timezone.now()
        resp = make_client(self.admin).post(f'{WORK_ORDER_URL}/{order.id}/cancel/',
                                            {'cancel_reason': '误建工单'},
                                            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        order.refresh_from_db()
        self.assertEqual(order.status, SystemWorkOrder.STATUS_CANCELLED)
        self.assertEqual(order.cancelled_by_id, self.admin.id)
        self.assertIsNotNone(order.cancelled_at)
        self.assertGreaterEqual(order.cancelled_at, before)


class WorkOrderHealthLinkageTest(WorkOrderTestBase):
    """执行中工单与统一健康状态计算联动（affects_system_operation 规则）。"""

    def test_executing_repair_order_with_affect_sets_repairing(self):
        """执行中且影响运行的故障维修工单使作业系统进入维修中。"""
        order = self.run_to_executing(work_type='repair')
        self.assertTrue(order.affects_system_operation)
        system = LifecycleSystem.objects.get(pk=self.system_a.id)
        self.assertEqual(system.health_status, 'repairing')
        # 完成后回到正常
        self.add_record(order.id)
        self.complete_order(order.id)
        system.refresh_from_db()
        self.assertEqual(system.health_status, 'normal')

    def test_executing_repair_order_without_affect_keeps_normal(self):
        """执行中但不影响运行的维修工单不改变系统状态（离线部件维修）。"""
        order = self.run_to_executing(work_type='repair', affects=False,
                                      title='离线部件维修')
        self.assertFalse(order.affects_system_operation)
        system = LifecycleSystem.objects.get(pk=self.system_a.id)
        self.assertEqual(system.health_status, 'normal')

    def test_repair_order_of_system_a_does_not_change_system_b(self):
        """系统A 的工单不会改变系统B 的状态（不建设跨系统联动）。"""
        self.run_to_executing(work_type='repair', system=self.system_a)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'repairing')
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a2.id).health_status, 'normal')

    def test_non_repair_order_does_not_change_health(self):
        """非故障维修工单不改变系统健康状态。

        2026-09 工单类型收敛后新建只允许故障维修/专项维护；已下线顶层类型
        （技术改造等）的历史工单以 queryset.update 模拟历史数据，
        同样不得参与"维修中"计算（REPAIRING_WORK_ORDER_FILTER 只认 repair）。
        """
        order = self.run_to_executing(work_type='special_maintenance',
                                      title='专项维护-状态不影响')
        system = LifecycleSystem.objects.get(pk=self.system_a.id)
        self.assertEqual(system.health_status, 'normal')
        # 清理：取消该工单，避免影响后续断言
        make_client(self.admin).post(f'{WORK_ORDER_URL}/{order.id}/cancel/',
                                     {'cancel_reason': '测试清理'},
                                     content_type='application/json')
        # 历史顶层类型工单（执行中 + 影响运行）同样不进入维修中
        legacy = self.run_to_executing(work_type='special_maintenance',
                                       title='历史类型-状态不影响')
        SystemWorkOrder.objects.filter(pk=legacy.id).update(work_type='tech_reform')
        fault_services.recompute_systems_health('tenant_a', [self.system_a.id])
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')
        make_client(self.admin).post(f'{WORK_ORDER_URL}/{legacy.id}/cancel/',
                                     {'cancel_reason': '测试清理'},
                                     content_type='application/json')

    def test_interrupted_fault_priority_over_repairing(self):
        """未恢复中断故障的优先级高于维修中。"""
        fault = self.create_active_fault(self.system_a, impact='interrupted')
        order = self.run_to_executing(work_type='repair')
        system = LifecycleSystem.objects.get(pk=self.system_a.id)
        self.assertEqual(system.health_status, 'interrupted')
        # 工单完成仍有未恢复故障 → 回到中断而非正常
        self.add_record(order.id)
        self.complete_order(order.id)
        system.refresh_from_db()
        self.assertEqual(system.health_status, 'interrupted')
        # 故障恢复后 → 正常
        client = make_client(self.admin)
        client.post(f'/equipment-lifecycle/faults/{fault.id}/start/', {},
                    content_type='application/json')
        client.post(f'/equipment-lifecycle/faults/{fault.id}/recover/', {
            'recovered_at': '2026-09-18 12:00', 'recover_confirm': '业务恢复'},
            content_type='application/json')
        system.refresh_from_db()
        self.assertEqual(system.health_status, 'normal')

    def test_completed_order_with_active_fault_keeps_fault_status(self):
        """工单完成后仍有未恢复故障时，系统不会恢复正常。"""
        fault = self.create_active_fault(self.system_a, impact='fault')
        order = self.run_to_executing(work_type='repair')
        system = LifecycleSystem.objects.get(pk=self.system_a.id)
        self.assertEqual(system.health_status, 'repairing')
        self.add_record(order.id)
        self.complete_order(order.id)
        system.refresh_from_db()
        # 工单完成 → 退回故障影响（不是 normal）
        self.assertEqual(system.health_status, 'fault')
        self.assertEqual(SystemFault.objects.get(pk=fault.id).status, 'pending')

    def test_normal_only_after_all_impacts_resolved(self):
        """所有故障和维修影响解除后系统才能恢复正常。"""
        fault = self.create_active_fault(self.system_a, impact='degraded')
        order = self.run_to_executing(work_type='repair')
        system = LifecycleSystem.objects.get(pk=self.system_a.id)
        self.assertEqual(system.health_status, 'repairing')
        self.add_record(order.id)
        self.complete_order(order.id)
        system.refresh_from_db()
        self.assertEqual(system.health_status, 'degraded')
        # 故障恢复确认后 → 正常
        client = make_client(self.admin)
        client.post(f'/equipment-lifecycle/faults/{fault.id}/start/', {},
                    content_type='application/json')
        client.post(f'/equipment-lifecycle/faults/{fault.id}/recover/', {
            'recovered_at': '2026-09-18 12:30', 'recover_confirm': '指标恢复正常'},
            content_type='application/json')
        system.refresh_from_db()
        self.assertEqual(system.health_status, 'normal')

    def test_failed_order_operation_rolls_back_status(self):
        """工单操作失败时状态更新同步回滚。"""
        order = self.run_to_executing(work_type='repair')
        system = LifecycleSystem.objects.get(pk=self.system_a.id)
        self.assertEqual(system.health_status, 'repairing')
        before = order.status
        self.add_record(order.id)
        with mock.patch('apps.equipment_lifecycle.work_order_views.record_audit_event',
                        side_effect=RuntimeError('模拟事务中途失败')):
            resp = make_client(self.admin).post(
                f'{WORK_ORDER_URL}/{order.id}/complete/',
                {'process_result': '结果文本'}, content_type='application/json')
        self.assertTrue(resp.json().get('error'), resp.content)
        order.refresh_from_db()
        system.refresh_from_db()
        self.assertEqual(order.status, before)
        self.assertEqual(system.health_status, 'repairing')

    def test_multiple_faults_and_orders_computed_together(self):
        """多故障、多工单并存时综合查询，取最高优先级影响。"""
        self.create_active_fault(self.system_a, impact='degraded')
        self.create_active_fault(self.system_a2, impact='interrupted')
        repair = self.run_to_executing(work_type='repair')
        # system_a：降级故障 + 执行中维修 → 维修中
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'repairing')
        # system_a2：中断故障（无工单）→ 中断
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a2.id).health_status, 'interrupted')
        # 维修完成 → system_a 回到降级
        self.add_record(repair.id)
        self.complete_order(repair.id)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'degraded')

    def test_recompute_service_idempotent(self):
        """状态计算服务重复调用结果一致（幂等），只读计算不落库差异。"""
        self.create_active_fault(self.system_a, impact='fault')
        self.run_to_executing(work_type='repair')
        first = fault_services.compute_health_status('tenant_a', [self.system_a.id])
        second = fault_services.compute_health_status('tenant_a', [self.system_a.id])
        self.assertEqual(first, second)
        self.assertEqual(first[self.system_a.id], 'repairing')
        # 只读计算不落库差异
        fault_services.compute_health_status('tenant_a', [self.system_a.id])
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'repairing')


class WorkOrderPermissionTest(WorkOrderTestBase):
    """权限与附件访问。"""

    def test_backend_rejects_without_permission(self):
        """权限不足时后端真实拒绝操作（不能只靠前端隐藏按钮）。"""
        # 无 work_order 权限：创建被拒
        resp = make_client(self.noperm_user).post(
            f'{WORK_ORDER_URL}/', work_order_payload(self.system_a),
            content_type='application/json')
        self.assertIn('权限拒绝', resp.json().get('error', ''), resp.content)
        # 有查看权限但无执行权限：完成工单被拒
        viewer = make_user('wo_viewer', ['equipment_lifecycle.work_order.view'] + ALL_SYSTEM_PERMS,
                           tenant_id='tenant_a')
        data = self.create_order_ok(work_order_payload(self.system_a))
        self.add_record(data['id'])
        resp = make_client(viewer).post(f'{WORK_ORDER_URL}/{data["id"]}/complete/',
                                        {'process_result': '结果'},
                                        content_type='application/json')
        self.assertIn('权限拒绝', resp.json().get('error', ''), resp.content)
        order = SystemWorkOrder.objects.get(pk=data['id'])
        self.assertEqual(order.status, SystemWorkOrder.STATUS_EXECUTING)
        # 列表也拒绝
        resp = make_client(self.noperm_user).get(f'{WORK_ORDER_URL}/')
        self.assertIn('权限拒绝', resp.json().get('error', ''), resp.content)

    def test_cross_tenant_order_invisible(self):
        """不同租户的工单互不可见（列表、详情）。"""
        data_b = self.create_order_ok(work_order_payload(self.system_b, title='租户B工单'),
                                      user=self.other_admin)
        # tenant_a 列表看不到 tenant_b 工单
        resp = make_client(self.admin).get(f'{WORK_ORDER_URL}/')
        ids = [row['id'] for row in resp.json()['data']['data']]
        self.assertNotIn(data_b['id'], ids)
        # tenant_a 详情访问 tenant_b 工单 → 不存在
        resp = make_client(self.admin).get(f'{WORK_ORDER_URL}/{data_b["id"]}/')
        self.assertIn('不存在', resp.json().get('error', ''), resp.content)

    def test_attachment_requires_parent_and_tenant(self):
        """附件访问执行父对象和租户权限校验。"""
        order = self.run_to_executing(work_type='special_maintenance')
        record = self.add_record(order.id)
        rid = record['data']['id']
        # 正常访问：空列表
        resp = make_client(self.admin).get(
            f'{WORK_ORDER_URL}/{order.id}/handling-records/{rid}/attachments/')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 父记录不存在 → 拒绝
        resp = make_client(self.admin).get(
            f'{WORK_ORDER_URL}/{order.id}/handling-records/99999/attachments/')
        self.assertIn('不存在', resp.json().get('error', ''), resp.content)
        # 跨租户工单 → 拒绝（先在 tenant_b 建一张）
        other = self.create_order_ok(work_order_payload(self.system_b, title='B附件'),
                                     user=self.other_admin)
        resp = make_client(self.admin).get(
            f'{WORK_ORDER_URL}/{other["id"]}/handling-records/1/attachments/')
        self.assertIn('不存在', resp.json().get('error', ''), resp.content)


class WorkOrderModuleBoundaryTest(WorkOrderTestBase):
    """模块边界。"""

    def test_no_inventory_or_transfer_or_resume_models(self):
        """没有库存、设备调拨或临时事件表模型。

        步骤 3.5 起，统一系统履历（SystemEvent）由步骤 3.4 正式落地，
        不再属于禁止集合；仍禁止库存/调拨/旧履历语义模型。
        """
        model_names = {m.__name__ for m in apps.get_app_config('equipment_lifecycle').get_models()}
        forbidden = {'Inventory', 'Stock', 'SparePart', 'DeviceTransfer', 'Allocation',
                     'SystemResume', 'LifecycleEvent', 'PlanReminder'}
        self.assertEqual(forbidden & model_names, set())
        # 工单模型不关联 DeviceResume
        wo_fields = {f.name for f in SystemWorkOrder._meta.get_fields()}
        self.assertNotIn('device_resume', wo_fields)
        self.assertNotIn('device', wo_fields)

    def test_upgrade_app_unchanged(self):
        """upgrade 模块没有发生变化（模型集合冻结校验）。

        2026-09 升级管理挂接系统档案：UpgradeSystem 字典表删除
        （候选系统改由 equipment_lifecycle.LifecycleSystem 提供），
        冻结基线同步移除该模型。
        """
        expected_upgrade = {'UpgradeRecord', 'UpgradeTemplate',
                            'UpgradePlanStep', 'UpgradeRecordStep', 'UpgradeStatusLog'}
        actual_upgrade = {m.__name__ for m in apps.get_app_config('upgrade').get_models()}
        self.assertEqual(actual_upgrade, expected_upgrade)
        # 设备生命周期模型不依赖 device/upgrade 应用的任何模型
        # （只检查 el 模型自身声明的字段；upgrade→el 的反向关联
        # （如 LifecycleSystem.upgrade_records）是挂接系统的预期方向，不算依赖）
        for model in apps.get_app_config('equipment_lifecycle').get_models():
            for field in model._meta.get_fields():
                if getattr(field, 'concrete', False) is not True:
                    continue
                related = getattr(field, 'related_model', None)
                if related is not None:
                    self.assertNotIn(
                        related._meta.app_label, ('device', 'upgrade'),
                        f'{model.__name__}.{field.name} 不应关联 {related._meta.app_label}')

    def test_fault_and_ledger_flows_still_work(self):
        """步骤 3.1 故障流程与步骤 3.2 台账保存逻辑没有被破坏（回归冒烟）。"""
        from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
            ALL_LEDGER_PERMS, entry_payload, item_payload,
            ledger_payload, make_ledger_user, post_json,
        )
        # 3.1：故障创建 → 处置 → 恢复 → 关闭
        fault = self.create_active_fault(self.system_a, impact='degraded')
        client = make_client(self.admin)
        client.post(f'/equipment-lifecycle/faults/{fault.id}/start/', {},
                    content_type='application/json')
        resp = client.post(f'/equipment-lifecycle/faults/{fault.id}/recover/', {
            'recovered_at': '2026-09-18 11:00', 'recover_confirm': '已恢复'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault.refresh_from_db()
        self.assertEqual(fault.status, 'recovered')
        # 3.2：台账创建（含异常明细）→ 提交 → 复核
        ledger_user = make_ledger_user('wo_ledger_user',
                                       perms=ALL_LEDGER_PERMS + ALL_SYSTEM_PERMS,
                                       tenant_id='tenant_a')
        ledger_client = make_client(ledger_user)
        payload = ledger_payload([entry_payload(self.system_a.id, [
            item_payload(),
            item_payload(item_name='电压检查', input_type='number', value_text='',
                         value_number=50, result='abnormal', abnormal_desc='电压偏低'),
        ])])
        resp = post_json(ledger_client, '/equipment-lifecycle/ledgers/', payload)
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        ledger_id = body['data']['id']
        resp = ledger_client.post(f'/equipment-lifecycle/ledgers/{ledger_id}/submit/',
                                  {}, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        from apps.equipment_lifecycle.models import OperationLedger
        self.assertEqual(OperationLedger.objects.get(pk=ledger_id).status, 'submitted')


class WorkOrderQueryViewTest(WorkOrderTestBase):
    """按系统/按故障查询工单的边界。"""

    def test_system_work_orders_single_system_only(self):
        """按系统查询工单只返回作业系统为该系统的工单（不再区分角色）。"""
        data = self.create_order_ok(work_order_payload(self.system_a))
        client = make_client(self.admin)
        resp = client.get(f'/equipment-lifecycle/systems/{self.system_a.id}/work-orders/')
        rows = resp.json()['data']['data']
        self.assertIn(data['id'], [r['id'] for r in rows])
        self.assertNotIn('order_role', rows[0])
        # 其他系统查不到该工单
        resp = client.get(f'/equipment-lifecycle/systems/{self.system_a2.id}/work-orders/')
        self.assertEqual(resp.json()['data']['data'], [])
        # 跨租户系统 → 拒绝
        resp = client.get(f'/equipment-lifecycle/systems/{self.system_b.id}/work-orders/')
        self.assertIn('不存在', resp.json().get('error', ''), resp.content)

    def test_handling_record_state_restriction(self):
        """处理记录仅执行中可追加；完成后拒绝。"""
        data = self.create_order_ok(work_order_payload(self.system_a, title='记录状态-执行中'))
        self.add_record(data['id'])
        self.complete_order(data['id'])
        self.add_record(data['id'], expect_error='只有执行中的工单可以追加处理记录')
        self.assertEqual(SystemWorkOrderHandlingRecord.objects.filter(work_order_id=data['id']).count(), 1)


class WorkOrderFaultDecouplingTest(WorkOrderTestBase):
    """工单与故障解耦契约（2026-09 处理进展改版固化）：

    - 工单完成不得自动将来源故障标记为恢复或关闭；
    - 故障恢复仍需用户按故障流程显式确认（含本方测试通过后的确认）；
    - 来源故障未恢复期间继续参与系统健康状态计算。
    """

    def create_work_order_from_fault(self, fault, client_token='tok-decouple-1'):
        resp = make_client(self.admin).post(
            f'/equipment-lifecycle/faults/{fault.id}/create-work-order/',
            {'client_token': client_token, 'affects_system_operation': False},
            content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return SystemWorkOrder.objects.get(pk=body['data']['id'])

    def test_completed_work_order_does_not_recover_or_close_fault(self):
        """工单完成后：来源故障仍为处置中，未自动恢复/关闭。"""
        fault = self.create_active_fault(self.system_a, impact='fault')
        client = make_client(self.admin)
        client.post(f'/equipment-lifecycle/faults/{fault.id}/start/',
                    {}, content_type='application/json')
        order = self.create_work_order_from_fault(fault)
        self.assertEqual(order.source_type, 'fault')
        self.assertEqual(order.source_fault_id, fault.id)
        # 单账号流程：创建即执行中，添加处理记录后直接完成
        self.assertEqual(order.status, SystemWorkOrder.STATUS_EXECUTING)
        self.add_record(order.id)
        self.complete_order(order.id)
        order.refresh_from_db()
        self.assertEqual(order.status, SystemWorkOrder.STATUS_COMPLETED)
        # 来源故障状态未被工单完成改动：仍处置中、无恢复数据
        fault.refresh_from_db()
        self.assertEqual(fault.status, SystemFault.STATUS_HANDLING)
        self.assertIsNone(fault.recovered_at)
        self.assertIsNone(fault.recovered_by_id)
        self.assertEqual(fault.final_result, '')
        # 未恢复故障继续参与系统健康状态计算（工单不影响运行 → 不产生维修中）
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'fault')

    def test_fault_can_add_progress_after_work_order_completed(self):
        """工单完成后来源故障仍可继续追加处理进展并按原规则确认恢复。"""
        fault = self.create_active_fault(self.system_a, impact='degraded')
        client = make_client(self.admin)
        client.post(f'/equipment-lifecycle/faults/{fault.id}/start/',
                    {}, content_type='application/json')
        order = self.create_work_order_from_fault(fault)
        self.add_record(order.id)
        self.complete_order(order.id)
        # 故障侧追加处理进展（送厂/返还/测试），然后人工确认恢复
        resp = client.post(f'/equipment-lifecycle/faults/{fault.id}/handling-records/',
                           {'content': '部件已返还，本方测试通过',
                            'progress_type': 'test', 'result': '复测通过',
                            'recorder_name': '复测人乙'},
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        resp = client.post(f'/equipment-lifecycle/faults/{fault.id}/recover/', {
            'recovered_at': '2026-09-18 12:00',
            'recover_confirm': '本方测试通过，业务确认恢复',
        }, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault.refresh_from_db()
        self.assertEqual(fault.status, SystemFault.STATUS_RECOVERED)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')

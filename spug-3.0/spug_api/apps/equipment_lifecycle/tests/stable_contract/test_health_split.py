# -*- coding: utf-8 -*-
"""系统运行状态与部件维修状态分离（稳定契约）。

业务规则：系统健康状态只表示系统对外提供服务的能力
（正常/降级/故障/中断/系统级维修中），部件故障、被替换下来维修、
离线维护默认不影响系统运行（affects_system_operation=False，新默认），
系统健康状态仍然可以是"正常"；只有明确选择"影响系统运行"的故障
（按影响程度 降级/故障/中断）和明确影响系统运行的维修工单（维修中）
才参与健康状态计算；部件维修状态作为独立提示展示
（component_maintenance），不显示为系统"维修中"。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
from datetime import datetime, timedelta

from django.test import TestCase

from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemFault,
    SystemWorkOrder,
)
from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS,
    make_client, make_system, make_user,
)

FAULT_URL = '/equipment-lifecycle/faults'
WO_URL = '/equipment-lifecycle/work-orders'
SYS_URL = '/equipment-lifecycle/systems'

ALL_FAULT_PERMS = [
    'equipment_lifecycle.fault.view', 'equipment_lifecycle.fault.add',
    'equipment_lifecycle.fault.edit', 'equipment_lifecycle.fault.handle',
    'equipment_lifecycle.fault.recover', 'equipment_lifecycle.fault.close',
    'equipment_lifecycle.fault.del', 'equipment_lifecycle.fault.export',
]
ALL_WO_PERMS = [
    'equipment_lifecycle.work_order.view', 'equipment_lifecycle.work_order.add',
    'equipment_lifecycle.work_order.edit', 'equipment_lifecycle.work_order.dispatch',
    'equipment_lifecycle.work_order.accept', 'equipment_lifecycle.work_order.execute',
    'equipment_lifecycle.work_order.review', 'equipment_lifecycle.work_order.close',
    'equipment_lifecycle.work_order.del', 'equipment_lifecycle.work_order.export',
]

_SEQ = {'n': 0}


def _uniq_token(prefix='tok-split'):
    _SEQ['n'] += 1
    return f'{prefix}-{_SEQ["n"]}'


def fault_payload(system_obj, **overrides):
    """默认不传影响开关 = 新业务默认"部件故障但不影响系统运行"。"""
    _SEQ['n'] += 1
    moment = datetime(2026, 9, 24, 8, 0) + timedelta(minutes=_SEQ['n'])
    payload = {
        'system': system_obj.id,
        'impact_status': 'fault',
        'occurred_at': moment.strftime('%Y-%m-%d %H:%M'),
        'discovery': 'patrol',
        'level': 'major',
        'phenomenon': f'板卡告警（场景{_SEQ["n"]}）',
    }
    payload.update(overrides)
    return payload


def work_order_payload(system_obj, **overrides):
    payload = {
        'title': f'{system_obj.system_code} 部件维修工单',
        'work_type': 'repair',
        'priority': 'normal',
        'system': system_obj.id,
        'affects_system_operation': False,
        'work_location': '机房A 01柜',
        'work_object_desc': '故障板卡',
        'work_requirement': '更换故障板卡',
        'client_token': _uniq_token(),
    }
    payload.update(overrides)
    return payload


class HealthSplitTestBase(TestCase):
    """公共夹具：单租户、可用系统。"""

    def setUp(self):
        self.admin = make_user(
            'split_admin', ALL_SYSTEM_PERMS + ALL_FAULT_PERMS + ALL_WO_PERMS,
            tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.system_a = make_system(self.admin, tenant_id='tenant_a',
                                    system_code='SYS-S1', name='烟台通信系统',
                                    install_location='机房A')

    def create_fault(self, payload, expect_error=None):
        resp = self.client.post(f'{FAULT_URL}/', payload,
                                content_type='application/json')
        body = resp.json()
        if expect_error is not None:
            self.assertIn(expect_error, body.get('error', ''), body)
            return body
        self.assertFalse(body.get('error'), body)
        return SystemFault.objects.get(pk=body['data']['id'])

    def create_work_order(self, payload, expect_error=None):
        resp = self.client.post(f'{WO_URL}/', payload,
                                content_type='application/json')
        body = resp.json()
        if expect_error is not None:
            self.assertIn(expect_error, body.get('error', ''), body)
            return body
        self.assertFalse(body.get('error'), body)
        return SystemWorkOrder.objects.get(pk=body['data']['id'])

    def run_work_order_to_executing(self, order_id):
        """派发 → 接单 → 开始执行。"""
        for action, payload in (
                ('dispatch', {'owner_id': self.admin.id}),
                ('accept', {}),
                ('start', {})):
            r = self.client.post(f'{WO_URL}/{order_id}/{action}/', payload,
                                 content_type='application/json')
            self.assertFalse(r.json().get('error'), r.content)

    def system_health(self):
        return LifecycleSystem.objects.get(pk=self.system_a.id).health_status


class ComponentFaultDefaultTest(HealthSplitTestBase):
    """默认"部件故障但不影响系统运行"。"""

    def test_component_fault_keeps_system_normal(self):
        """部件故障（新默认不影响运行）时系统健康状态仍为正常。"""
        fault = self.create_fault(fault_payload(self.system_a))
        self.assertFalse(fault.affects_system_operation)
        # 影响程度被后端强制置空：不影响运行即无系统影响程度
        self.assertEqual(fault.impact_status, '')
        self.assertEqual(self.system_health(), 'normal')

    def test_passed_impact_ignored_when_not_affecting(self):
        """不影响运行时，前端传入的影响程度被后端忽略并强制置空。"""
        fault = self.create_fault(fault_payload(
            self.system_a, affects_system_operation=False, impact_status='interrupted'))
        self.assertFalse(fault.affects_system_operation)
        self.assertEqual(fault.impact_status, '')
        self.assertEqual(self.system_health(), 'normal')

    def test_explicit_affecting_fault_computes_health(self):
        """明确选择影响系统运行时按影响程度正确计算。"""
        for impact, expected in (('degraded', 'degraded'),
                                 ('fault', 'fault'),
                                 ('interrupted', 'interrupted')):
            system = make_system(
                self.admin, tenant_id='tenant_a',
                system_code=f'SYS-IMP-{impact}', name=f'影响程度系统-{impact}',
                install_location='机房X')
            fault = self.create_fault(fault_payload(
                system, affects_system_operation=True, impact_status=impact))
            self.assertTrue(fault.affects_system_operation)
            self.assertEqual(fault.impact_status, impact)
            self.assertEqual(
                LifecycleSystem.objects.get(pk=system.id).health_status, expected)

    def test_affecting_fault_requires_impact(self):
        """影响系统运行时必须选择影响程度。"""
        self.create_fault(
            fault_payload(self.system_a, affects_system_operation=True, impact_status=''),
            expect_error='影响程度')
        self.assertEqual(SystemFault.objects.count(), 0)
        self.create_fault(
            fault_payload(self.system_a, affects_system_operation=True,
                          impact_status='invalid'),
            expect_error='影响程度')
        self.assertEqual(SystemFault.objects.count(), 0)

    def test_mixed_component_and_affecting_faults(self):
        """部件故障与影响运行的故障并存：健康取影响运行的影响程度。"""
        self.create_fault(fault_payload(self.system_a))
        self.create_fault(fault_payload(
            self.system_a, affects_system_operation=True, impact_status='degraded'))
        self.assertEqual(self.system_health(), 'degraded')


class ComponentMaintenanceDisplayTest(HealthSplitTestBase):
    """系统列表/详情的部件维护独立提示（不显示为系统"维修中"）。"""

    def test_list_and_detail_report_component_maintenance(self):
        """部件故障数只统计不影响运行的有效故障；影响运行故障不计入。"""
        self.create_fault(fault_payload(self.system_a))  # 部件故障
        self.create_fault(fault_payload(
            self.system_a, affects_system_operation=True, impact_status='fault'))
        resp = self.client.get(SYS_URL + "/")
        rows = {row['id']: row for row in resp.json()['data']['data']}
        row = rows[self.system_a.id]
        self.assertEqual(row['health_status'], 'fault')
        self.assertEqual(row['component_maintenance']['fault_count'], 1)
        self.assertEqual(row['component_maintenance']['repairing_count'], 0)
        detail = self.client.get(
            f'{SYS_URL}/{self.system_a.id}/').json()['data']
        self.assertEqual(detail['component_maintenance']['fault_count'], 1)

    def test_executing_offline_repair_reported_not_repairing(self):
        """执行中的离线部件维修计入 repairing_count，系统状态保持正常。"""
        self.create_fault(fault_payload(self.system_a))
        order = self.create_work_order(work_order_payload(self.system_a))
        self.run_work_order_to_executing(order.id)
        self.assertEqual(self.system_health(), 'normal')
        resp = self.client.get(SYS_URL + "/")
        row = {r['id']: r for r in resp.json()['data']['data']}[self.system_a.id]
        self.assertEqual(row['health_status'], 'normal')
        self.assertEqual(row['component_maintenance']['repairing_count'], 1)
        self.assertEqual(row['component_maintenance']['fault_count'], 1)


class WorkOrderAffectDefaultsTest(HealthSplitTestBase):
    """故障转工单与手工工单的影响运行默认值。"""

    def test_fault_to_work_order_defaults_to_no_affect(self):
        """故障生成维修工单默认"作业期间不影响系统运行"。"""
        fault = self.create_fault(fault_payload(self.system_a))
        resp = self.client.post(
            f'{FAULT_URL}/{fault.id}/create-work-order/',
            {'client_token': _uniq_token(), 'work_type': 'repair'},
            content_type='application/json').json()
        self.assertFalse(resp.get('error'), resp)
        self.assertFalse(resp['data']['affects_system_operation'])
        order = SystemWorkOrder.objects.get(pk=resp['data']['id'])
        self.run_work_order_to_executing(order.id)
        # 执行中也不改变系统状态（离线部件维修）
        self.assertEqual(self.system_health(), 'normal')

    def test_fault_to_work_order_explicit_affect_sets_repairing(self):
        """转工单时明确选择影响运行 → 执行中进入维修中。"""
        fault = self.create_fault(fault_payload(self.system_a))
        resp = self.client.post(
            f'{FAULT_URL}/{fault.id}/create-work-order/',
            {'client_token': _uniq_token(), 'work_type': 'repair',
             'affects_system_operation': True},
            content_type='application/json').json()
        self.assertFalse(resp.get('error'), resp)
        self.assertTrue(resp['data']['affects_system_operation'])
        order = SystemWorkOrder.objects.get(pk=resp['data']['id'])
        self.run_work_order_to_executing(order.id)
        self.assertEqual(self.system_health(), 'repairing')

    def test_manual_work_order_defaults_to_no_affect(self):
        """手工建单默认不影响运行（前后端默认一致）。"""
        order = self.create_work_order(work_order_payload(self.system_a))
        self.assertFalse(order.affects_system_operation)
        self.run_work_order_to_executing(order.id)
        self.assertEqual(self.system_health(), 'normal')


class FaultEditAffectSemanticsTest(HealthSplitTestBase):
    """故障编辑对影响开关的语义：未提交保留原值，显式提交可翻转。"""

    def _put_fault(self, fault, **extra):
        detail = self.client.get(f'{FAULT_URL}/{fault.id}/').json()['data']
        payload = {k: detail[k] for k in (
            'system', 'impact_status', 'occurred_at', 'discovery',
            'level', 'phenomenon')}
        payload.update(extra)
        resp = self.client.put(f'{FAULT_URL}/{fault.id}/', payload,
                               content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        return SystemFault.objects.get(pk=fault.id)

    def test_edit_without_switch_preserves_original_state(self):
        """编辑未提交影响开关时保留原故障的影响设置。"""
        fault = self.create_fault(fault_payload(
            self.system_a, affects_system_operation=True, impact_status='fault'))
        self.assertEqual(self.system_health(), 'fault')
        fault = self._put_fault(fault, phenomenon='更新现象描述')
        self.assertTrue(fault.affects_system_operation)
        self.assertEqual(fault.impact_status, 'fault')
        self.assertEqual(self.system_health(), 'fault')

    def test_edit_can_flip_to_component_fault(self):
        """编辑显式改为不影响运行 → 影响程度清空、系统恢复正常。"""
        fault = self.create_fault(fault_payload(
            self.system_a, affects_system_operation=True, impact_status='fault'))
        fault = self._put_fault(fault, affects_system_operation=False)
        self.assertFalse(fault.affects_system_operation)
        self.assertEqual(fault.impact_status, '')
        self.assertEqual(self.system_health(), 'normal')

    def test_edit_can_flip_to_affecting(self):
        """编辑显式改为影响运行 → 按影响程度参与计算。"""
        fault = self.create_fault(fault_payload(self.system_a))
        fault = self._put_fault(
            fault, affects_system_operation=True, impact_status='interrupted')
        self.assertTrue(fault.affects_system_operation)
        self.assertEqual(fault.impact_status, 'interrupted')
        self.assertEqual(self.system_health(), 'interrupted')


class ModelDefaultContractTest(HealthSplitTestBase):
    """模型层默认值契约：新记录默认不影响系统运行。"""

    def test_model_field_default_false(self):
        from apps.equipment_lifecycle.models import FAULT_IMPACT_DB_VALUES
        self.assertEqual(
            SystemFault._meta.get_field('affects_system_operation').default, False)
        # 影响程度数据库合法值 = 空串 + 三档影响程度
        self.assertEqual(FAULT_IMPACT_DB_VALUES, ['', 'degraded', 'fault', 'interrupted'])

    def test_service_forces_empty_impact_when_not_affecting(self):
        """创建服务在不影响运行时强制清空影响程度（不信任调用方传值）。"""
        from apps.equipment_lifecycle import fault_services
        fault = fault_services.create_fault_record(
            tenant_id='tenant_a',
            created_by=self.admin,
            system=self.system_a,
            impact_status='interrupted',
            affects_system_operation=False,
            occurred_at=datetime(2026, 9, 24, 9, 0),
            discovery='patrol',
            level='major',
            phenomenon='服务层直建部件故障',
        )
        self.assertFalse(fault.affects_system_operation)
        self.assertEqual(fault.impact_status, '')
        self.assertEqual(self.system_health(), 'normal')

# -*- coding: utf-8 -*-
"""设备全生命周期单系统简化（故障/工单/履历）稳定契约测试。

固化"一张故障单/工单/履历事件只关联一个系统"的业务结论与关键联动：
- 受影响系统结构（模型、表、API 参数）已删除且无运行时残留；
- 台账仍可一张表汇总多个系统（每条明细只属于一个系统）；
- 已恢复故障生成的后续部件维修工单默认不影响系统运行，
  系统不因离线部件维修重新进入"维修中"；
- 系统状态计算只依据本系统记录。

全部通过真实 HTTP 路径 + 隔离测试数据库执行。
"""
from django.db import connection
from django.test import TestCase

from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    OperationLedgerItem,
    SystemEvent,
    SystemFault,
    SystemWorkOrder,
)

from apps.equipment_lifecycle.tests.base import (
    ALL_CONFIG_PERMS, ALL_SYSTEM_PERMS, make_client, make_system, make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS, ALL_TEMPLATE_PERMS,
    create_ledger_ok, entry_payload, item_payload, ledger_payload, post_json,
)

FAULT_URL = '/equipment-lifecycle/faults'
WO_URL = '/equipment-lifecycle/work-orders'
LEDGER_URL = '/equipment-lifecycle/ledgers'

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
P_HANDLE_EXCEPTION = 'equipment_lifecycle.ledger.handle_exception'


def fault_payload(system_obj, **overrides):
    payload = {
        'system': system_obj.id,
        # 本文件的恢复/健康联动契约基于"影响系统运行"的故障（新默认不影响，见 test_health_split.py）
        'affects_system_operation': True,
        'impact_status': 'fault',
        'occurred_at': '2026-09-19 08:00',
        'discovery': 'patrol',
        'level': 'major',
        'phenomenon': '发射机告警，无法正常工作',
    }
    payload.update(overrides)
    return payload


class SingleSystemSimplificationTest(TestCase):
    """单系统简化契约。"""

    def setUp(self):
        perms = (ALL_SYSTEM_PERMS + ALL_CONFIG_PERMS + ALL_FAULT_PERMS + ALL_WO_PERMS +
                 ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS + [P_HANDLE_EXCEPTION])
        self.admin = make_user('ss_admin', perms, tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.system_a = make_system(self.admin, tenant_id='tenant_a',
                                    system_code='SS-A1', name='导航台DVOR系统')
        self.system_a2 = make_system(self.admin, tenant_id='tenant_a',
                                     system_code='SS-A2', name='导航台DME系统')

    # ---------- 结构清理 ----------

    def test_affected_system_tables_dropped(self):
        """受影响系统两表已随 migration 删除，无运行时残留。"""
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'tdyw_el_fault_affected_system'")
            self.assertIsNone(cursor.fetchone())
            cursor.execute("SHOW TABLES LIKE 'tdyw_el_work_order_affected_system'")
            self.assertIsNone(cursor.fetchone())
            cursor.execute("SHOW COLUMNS FROM tdyw_el_fault LIKE 'primary_system%'")
            self.assertIsNone(cursor.fetchone())
            cursor.execute("SHOW COLUMNS FROM tdyw_el_work_order LIKE 'target_system%'")
            self.assertIsNone(cursor.fetchone())
            cursor.execute("SHOW COLUMNS FROM tdyw_el_system_event LIKE 'role'")
            self.assertIsNone(cursor.fetchone())
            # 新字段在位
            cursor.execute("SHOW COLUMNS FROM tdyw_el_work_order LIKE 'affects_system_operation'")
            self.assertIsNotNone(cursor.fetchone())

    # ---------- 台账多系统汇总 ----------

    def test_ledger_still_summarizes_multiple_systems(self):
        """一张台账仍可保存多个系统的不同明细，每条明细只属于一个系统。"""
        payload = ledger_payload([
            entry_payload(self.system_a.id, [
                item_payload(item_name='DVOR 机柜温度检查', result='abnormal',
                             abnormal_desc='温度越限'),
            ]),
            entry_payload(self.system_a2.id, [
                item_payload(item_name='DME 电源电压检查'),
            ]),
        ])
        body = post_json(self.client, f'{LEDGER_URL}/', payload).json()
        self.assertFalse(body.get('error'), body)
        ledger_id = body['data']['id']
        ledger = self.client.get(f'{LEDGER_URL}/{ledger_id}/').json()['data']
        items = OperationLedgerItem.objects.filter(ledger_id=ledger_id)
        self.assertEqual(items.count(), 2)
        systems = {i.system_id for i in items}
        self.assertEqual(systems, {self.system_a.id, self.system_a2.id})
        # 台账表头不属于任何单一系统：序列化无系统字段
        self.assertNotIn('system', ledger)
        self.assertNotIn('system_id', ledger)
        for item in ledger['items']:
            self.assertIn(item['system'], (self.system_a.id, self.system_a2.id))

    # ---------- 系统恢复后的离线部件维修 ----------

    def test_offline_part_repair_after_recovery_keeps_system_normal(self):
        """系统恢复后维修拆下的故障部件：工单继续执行，系统仍保持正常。"""
        # 1) 故障发生 → 系统故障
        body = self.client.post(f'{FAULT_URL}/', fault_payload(self.system_a),
                                content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        fid = body['data']['id']
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'fault')
        # 2) 开始处置 → 确认恢复（系统恢复正常）
        self.client.post(f'{FAULT_URL}/{fid}/start/', {}, content_type='application/json')
        r = self.client.post(f'{FAULT_URL}/{fid}/recover/', {
            'recovered_at': '2026-09-19 10:00', 'recover_confirm': '更换备件后业务恢复',
        }, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')
        # 3) 为已恢复故障生成后续部件维修工单：默认不影响系统运行
        wo_body = self.client.post(
            f'{FAULT_URL}/{fid}/create-work-order/',
            {'client_token': 'tok-offline-1', 'work_type': 'repair',
             'title': '送修板卡离线检测'},
            content_type='application/json').json()
        self.assertFalse(wo_body.get('error'), wo_body)
        self.assertFalse(wo_body['data']['affects_system_operation'])
        self.assertEqual(wo_body['data']['system'], self.system_a.id)
        wid = wo_body['data']['id']
        # 4) 工单推进到执行中：系统仍保持正常
        for action, payload in (('dispatch', {'owner_id': self.admin.id}),
                                ('accept', {}), ('start', {})):
            r = self.client.post(f'{WO_URL}/{wid}/{action}/', payload,
                                 content_type='application/json')
            self.assertFalse(r.json().get('error'), r.content)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')
        order = SystemWorkOrder.objects.get(pk=wid)
        self.assertEqual(order.status, SystemWorkOrder.STATUS_EXECUTING)
        # 5) 履历只有故障系统的事件，无跨系统事件
        events = SystemEvent.objects.filter(tenant_id='tenant_a')
        self.assertEqual(
            {e.system_id for e in events}, {self.system_a.id})
        self.assertEqual(
            {e.source_id for e in events.filter(event_type=SystemEvent.EVENT_WORK_ORDER)},
            {str(wid)})

    def test_unrecovered_fault_repair_order_defaults_to_no_affect(self):
        """尚未恢复的故障生成现场维修工单：默认"作业期间不影响系统运行"，
        执行中不进入"维修中"，系统保持来源故障的"故障"状态；
        仅用户明确选择影响运行时才参与健康状态计算。"""
        body = self.client.post(f'{FAULT_URL}/', fault_payload(self.system_a),
                                content_type='application/json').json()
        fid = body['data']['id']
        wo_body = self.client.post(
            f'{FAULT_URL}/{fid}/create-work-order/',
            {'client_token': 'tok-online-1', 'work_type': 'repair'},
            content_type='application/json').json()
        self.assertFalse(wo_body.get('error'), wo_body)
        self.assertFalse(wo_body['data']['affects_system_operation'])
        wid = wo_body['data']['id']
        for action, payload in (('dispatch', {'owner_id': self.admin.id}),
                                ('accept', {}), ('start', {})):
            self.client.post(f'{WO_URL}/{wid}/{action}/', payload,
                             content_type='application/json')
        # 来源故障仍有效且影响运行 → 系统保持"故障"而非"维修中"
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'fault')

    def test_fault_to_work_order_system_fixed_to_fault_system(self):
        """转单不能把工单改到其他系统：作业系统固定为故障所属系统。"""
        body = self.client.post(f'{FAULT_URL}/', fault_payload(self.system_a),
                                content_type='application/json').json()
        fid = body['data']['id']
        resp = self.client.post(
            f'{FAULT_URL}/{fid}/create-work-order/',
            {'client_token': 'tok-fix-1', 'system': self.system_a2.id},
            content_type='application/json').json()
        self.assertIn('不能指定其他系统', resp.get('error', ''))
        self.assertEqual(SystemWorkOrder.objects.count(), 0)
        # 不指定系统 → 默认故障所属系统
        ok = self.client.post(
            f'{FAULT_URL}/{fid}/create-work-order/',
            {'client_token': 'tok-fix-2'}, content_type='application/json').json()
        self.assertFalse(ok.get('error'), ok)
        self.assertEqual(ok['data']['system'], self.system_a.id)
        self.assertEqual(
            SystemWorkOrder.objects.get(pk=ok['data']['id']).system_id, self.system_a.id)

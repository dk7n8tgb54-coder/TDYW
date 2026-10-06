# -*- coding: utf-8 -*-
"""设备全生命周期单系统简化（故障/履历）稳定契约测试。

固化"一张故障单/履历事件只关联一个系统"的业务结论与关键联动：
- 受影响系统结构（模型、表、API 参数）已删除且无运行时残留；
- 台账仍可一张表汇总多个系统（每条明细只属于一个系统）；
- 工单三表已随"故障维修工单"功能整体删除（2026-09-30），
  维修过程统一由故障处置记录承载，系统状态计算只依据本系统故障记录。

全部通过真实 HTTP 路径 + 隔离测试数据库执行。
"""
from django.db import connection
from django.test import TestCase

from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    OperationLedgerItem,
    SystemEvent,
)

from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS, make_client, make_system, make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS, ALL_TEMPLATE_PERMS,
    create_ledger_ok, entry_payload, item_payload, ledger_payload, post_json,
)

FAULT_URL = '/equipment-lifecycle/faults'
LEDGER_URL = '/equipment-lifecycle/ledgers'

ALL_FAULT_PERMS = [
    'equipment_lifecycle.fault.view', 'equipment_lifecycle.fault.add',
    'equipment_lifecycle.fault.edit', 'equipment_lifecycle.fault.handle',
    'equipment_lifecycle.fault.recover', 'equipment_lifecycle.fault.close',
    'equipment_lifecycle.fault.del', 'equipment_lifecycle.fault.export',
]
P_HANDLE_EXCEPTION = 'equipment_lifecycle.ledger.handle_exception'


class SingleSystemSimplificationTest(TestCase):
    """单系统简化契约。"""

    def setUp(self):
        perms = (ALL_SYSTEM_PERMS + ALL_FAULT_PERMS +
                 ALL_LEDGER_PERMS + ALL_TEMPLATE_PERMS + [P_HANDLE_EXCEPTION])
        self.admin = make_user('ss_admin', perms, tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.system_a = make_system(self.admin, tenant_id='tenant_a',
                                    system_code='SS-A1', name='导航台DVOR系统')
        self.system_a2 = make_system(self.admin, tenant_id='tenant_a',
                                     system_code='SS-A2', name='导航台DME系统')

    # ---------- 结构清理 ----------

    def test_affected_system_tables_dropped(self):
        """受影响系统两表与工单三表已随 migration 删除，无运行时残留。"""
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'tdyw_el_fault_affected_system'")
            self.assertIsNone(cursor.fetchone())
            cursor.execute("SHOW TABLES LIKE 'tdyw_el_work_order_affected_system'")
            self.assertIsNone(cursor.fetchone())
            # 工单三表已随工单功能删除（迁移 0043）
            cursor.execute("SHOW TABLES LIKE 'tdyw_el_work_order'")
            self.assertIsNone(cursor.fetchone())
            cursor.execute("SHOW TABLES LIKE 'tdyw_el_work_order_participant'")
            self.assertIsNone(cursor.fetchone())
            cursor.execute("SHOW TABLES LIKE 'tdyw_el_work_order_handling_record'")
            self.assertIsNone(cursor.fetchone())
            cursor.execute("SHOW COLUMNS FROM tdyw_el_fault LIKE 'primary_system%'")
            self.assertIsNone(cursor.fetchone())
            cursor.execute("SHOW COLUMNS FROM tdyw_el_system_event LIKE 'role'")
            self.assertIsNone(cursor.fetchone())

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

    # ---------- 故障恢复后健康状态只依据本系统故障 ----------

    def test_recovery_restores_health_and_events_single_system(self):
        """故障恢复后系统恢复正常；履历只有故障系统的事件，无跨系统事件。"""
        # 1) 故障发生 → 系统故障
        body = self.client.post(f'{FAULT_URL}/', {
            'system': self.system_a.id,
            'affects_system_operation': True,
            'impact_status': 'fault',
            'occurred_at': '2026-09-19 08:00',
            'phenomenon': '发射机告警，无法正常工作',
            'registrar_name': '登记人甲',
        }, content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        fid = body['data']['id']
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'fault')
        # 2) 确认恢复并结案（新建即处置中，单次事务恢复+关闭，系统恢复正常）
        r = self.client.post(f'{FAULT_URL}/{fid}/recover/', {
            'recovered_at': '2026-09-19 10:00', 'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '更换备件并验证恢复，业务恢复正常',
        }, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')
        # 3) 履历只有故障系统的事件，无跨系统事件、无工单事件
        events = SystemEvent.objects.filter(tenant_id='tenant_a')
        self.assertEqual(
            {e.system_id for e in events}, {self.system_a.id})
        self.assertFalse(
            events.filter(event_type='work_order').exists())

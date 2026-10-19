# -*- coding: utf-8 -*-
"""维护台账异常转统一记录（设备故障）契约测试（2026-10-11 合并改造）。

覆盖真实行为契约（真实 HTTP + 隔离测试数据库 + 数据库状态断言）：
1. 台账异常明细"转故障"创建统一主表设备故障记录（record_type=fault、
   处置中），来源关系（source_type=ledger_item + source_ledger_item 外键）
   双向可追溯；不再创建第二张单；
2. 情况描述/标题由台账明细组装（台账类型/编号 + 检查项 + 异常说明 +
   实测值 + 现场处理内容）；
3. 台账异常处置状态（disposition）按统一记录动态推导：
   未处置/已转故障/目标已撤销登记；
4. 校验：非异常明细、草稿/退回/作废台账、旧巡检台账拒绝；重复转换拒绝；
   目标撤销后重新处置须填原因；
5. 权限：ledger.handle_exception 且同时具备 operation_record.add_fault；
6. 健康状态：转入的影响运行故障参与健康状态计算。
"""
import json

from django.test import TestCase, TransactionTestCase

from apps.equipment_lifecycle.models import LifecycleSystem, OperationLedger
from apps.equipment_lifecycle.operation_models import SystemOperationRecord
from apps.equipment_lifecycle.tests.base import (
    ALL_OPERATION_PERMS, P_OP_ADD_FAULT, P_OP_VIEW,
    make_client, make_system, make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS, LEDGER_URL, entry_payload, item_payload,
    ledger_payload, make_full_ledger, post_json, put_json,
)

def _drop_ledger_type_check():
    """临时拆除台账类型 CHECK（仅隔离测试库，模拟清理前的历史状态）。

    须在 TransactionTestCase 内调用：DDL 会隐式提交，TestCase 原子块内
    执行将破坏事务语义。
    """
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE tdyw_el_operation_ledger "
            "DROP CONSTRAINT el_operation_ledger_type_valid")


def _restore_ledger_type_check():
    """恢复台账类型 CHECK：先删净历史巡检行（存量行违反值域会拒绝建约束）。"""
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE c FROM tdyw_el_ledger_correction c "
            "JOIN tdyw_el_operation_ledger l ON c.ledger_id = l.id "
            "WHERE l.ledger_type = 'inspection'")
        cursor.execute(
            "DELETE i FROM tdyw_el_operation_ledger_item i "
            "JOIN tdyw_el_operation_ledger l ON i.ledger_id = l.id "
            "WHERE l.ledger_type = 'inspection'")
        cursor.execute(
            "DELETE FROM tdyw_el_operation_ledger WHERE ledger_type = 'inspection'")
        cursor.execute(
            "ALTER TABLE tdyw_el_operation_ledger "
            "ADD CONSTRAINT el_operation_ledger_type_valid "
            "CHECK (ledger_type IN ('week_month', 'seasonal'))")


CONVERT_URL = '/equipment-lifecycle/ledgers/%d/items/%d/convert-to-fault/'
RECORDS_CANCEL_URL = '/equipment-lifecycle/records/%d/cancel/'
# handle_exception 不在 ALL_LEDGER_PERMS 内，须显式叠加
LEDGER_HANDLE_PERM = 'equipment_lifecycle.ledger.handle_exception'


class LedgerConvertToFaultTest(TestCase):
    """台账异常明细转统一记录契约。"""

    def setUp(self):
        perms = ALL_LEDGER_PERMS + ALL_OPERATION_PERMS + [LEDGER_HANDLE_PERM]
        self.user = make_user('ledger_convert_user', perms=perms)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        # 一张台账（夹具固定两项：指示灯正常 + 电源电压测量异常）
        detail, system = make_full_ledger(self.user, system=self.system)
        self.ledger = OperationLedger.objects.get(pk=detail['id'])
        items = list(self.ledger.items.order_by('id'))
        self.normal_item = items[0]
        self.abnormal_item = items[1]
        # 完成填写（草稿不可转）
        res = self.client.post(LEDGER_URL + '/%d/complete/' % self.ledger.id,
                               json.dumps({}), content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())

    def _convert(self, item=None, **overrides):
        payload = {
            'affects_system_operation': True,
            'impact_status': 'degraded',
        }
        payload.update(overrides)
        return self.client.post(
            CONVERT_URL % (self.ledger.id, (item or self.abnormal_item).id),
            json.dumps(payload), content_type='application/json')

    def test_convert_creates_unified_fault_record(self):
        res = self._convert()
        data = res.json()['data']
        self.assertFalse(res.json().get('error'), res.json())
        record = SystemOperationRecord.objects.get(pk=data['id'])
        self.assertEqual(record.record_type, 'fault')
        self.assertEqual(record.status, 'handling')
        # 来源关系双向可追溯
        self.assertEqual(record.source_type, 'ledger_item')
        self.assertEqual(record.source_ledger_item_id, self.abnormal_item.id)
        self.assertEqual(record.source_id, str(self.abnormal_item.id))
        self.assertEqual(record.system_id, self.system.id)
        # 描述由明细组装
        self.assertIn('电源电压测量', record.description)
        self.assertIn('电压偏低', record.description)
        self.assertIn('实测值：52', record.description)
        self.assertTrue(record.record_no.startswith('JL'))
        self.assertEqual(SystemOperationRecord.objects.count(), 1)

    def test_convert_affecting_updates_health(self):
        res = self._convert()
        self.assertFalse(res.json().get('error'), res.json())
        self.system.refresh_from_db()
        self.assertEqual(self.system.health_status, 'degraded')

    def test_duplicate_convert_rejected(self):
        res = self._convert()
        self.assertFalse(res.json().get('error'), res.json())
        res = self._convert()
        self.assertIn('不能重复转换', res.json().get('error', ''))
        self.assertEqual(SystemOperationRecord.objects.count(), 1)

    def test_redispose_after_cancel_requires_reason(self):
        first = self._convert()
        record = SystemOperationRecord.objects.get(pk=first.json()['data']['id'])
        # 撤销第一次转换目标
        res = self.client.post(RECORDS_CANCEL_URL % record.id,
                               json.dumps({'cancel_reason': '误转'}),
                               content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        # 未填原因再次转换 → 拒绝
        res = self._convert()
        self.assertIn('重新处置原因', res.json().get('error', ''))
        # 填写原因后允许再次转换（生成新目标）
        res = self._convert(re_dispose_reason='确认异常属实，重新处置')
        self.assertFalse(res.json().get('error'), res.json())
        self.assertEqual(SystemOperationRecord.objects.count(), 2)

    def test_normal_item_rejected(self):
        res = self._convert(item=self.normal_item)
        self.assertIn('异常', res.json().get('error', ''))

    def test_draft_ledger_rejected(self):
        detail, _ = make_full_ledger(self.user, system=self.system)
        ledger = OperationLedger.objects.get(pk=detail['id'])
        item = ledger.items.filter(result='abnormal').first()
        res = self.client.post(CONVERT_URL % (ledger.id, item.id),
                               json.dumps({}), content_type='application/json')
        self.assertIn('草稿', res.json().get('error', ''))

    def test_permission_requires_handle_exception_and_add_fault(self):
        user = make_user('no_convert_perm', perms=ALL_LEDGER_PERMS + [P_OP_VIEW])
        client = make_client(user)
        res = client.post(CONVERT_URL % (self.ledger.id, self.abnormal_item.id),
                          json.dumps({}), content_type='application/json')
        self.assertIn('权限拒绝', res.json().get('error', ''))
        self.assertFalse(SystemOperationRecord.objects.exists())

    def test_cross_tenant_convert_rejected(self):
        other_user = make_user(
            't2_ledger', perms=ALL_LEDGER_PERMS + ALL_OPERATION_PERMS + [LEDGER_HANDLE_PERM],
            tenant_id='tenant_2')
        client = make_client(other_user)
        res = client.post(CONVERT_URL % (self.ledger.id, self.abnormal_item.id),
                          json.dumps({}), content_type='application/json')
        self.assertIn('不存在', res.json().get('error', ''))

    def test_retired_convert_params_rejected(self):
        res = self._convert(discovery='巡检发现')
        self.assertIn('不再支持参数', res.json().get('error', ''))


class LedgerDispositionTest(TestCase):
    """台账异常处置状态（由统一记录关系动态推导）契约。"""

    def setUp(self):
        perms = ALL_LEDGER_PERMS + ALL_OPERATION_PERMS + [LEDGER_HANDLE_PERM]
        self.user = make_user('disposition_user', perms=perms)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        detail, _ = make_full_ledger(self.user, system=self.system)
        self.ledger = OperationLedger.objects.get(pk=detail['id'])
        self.item = self.ledger.items.filter(result='abnormal').first()
        self.client.post(LEDGER_URL + '/%d/complete/' % self.ledger.id,
                         json.dumps({}), content_type='application/json')

    def _abnormal_items_api(self):
        res = self.client.get('/equipment-lifecycle/ledgers/abnormal-items/')
        return res.json()

    def test_none_before_convert(self):
        data = self._abnormal_items_api()['data']
        rows = [row for row in data['data']
                if row.get('disposition') and row['id'] == self.item.id]
        self.assertTrue(rows)
        self.assertEqual(rows[0]['disposition']['status'], 'none')
        self.assertIsNone(rows[0]['disposition']['target'])

    def test_converted_after_convert(self):
        res = self.client.post(CONVERT_URL % (self.ledger.id, self.item.id),
                               json.dumps({'affects_system_operation': False}),
                               content_type='application/json')
        record_id = res.json()['data']['id']
        data = self._abnormal_items_api()['data']
        row = next(row for row in data['data'] if row['id'] == self.item.id)
        self.assertEqual(row['disposition']['status'], 'converted_fault')
        self.assertEqual(row['disposition']['target']['id'], record_id)
        self.assertTrue(row['disposition']['target']['record_no'].startswith('JL'))

    def test_target_cancelled_after_record_cancel(self):
        res = self.client.post(CONVERT_URL % (self.ledger.id, self.item.id),
                               json.dumps({'affects_system_operation': False}),
                               content_type='application/json')
        record_id = res.json()['data']['id']
        self.client.post(RECORDS_CANCEL_URL % record_id,
                         json.dumps({'cancel_reason': '登记有误'}),
                         content_type='application/json')
        data = self._abnormal_items_api()['data']
        row = next(row for row in data['data'] if row['id'] == self.item.id)
        self.assertEqual(row['disposition']['status'], 'target_cancelled')


class LegacyInspectionLedgerConvertRejectedTest(TransactionTestCase):
    """旧巡检台账（历史）转故障显式拒绝契约。

    历史巡检类型不在现行 CHECK 值域内：在 TransactionTestCase 中临时拆除
    CHECK 造历史行（DDL 隐式提交，不能进 TestCase 原子块），断言转换被
    业务规则拒绝后恢复约束。
    """

    def test_legacy_inspection_ledger_rejected(self):
        from django.db import connection

        from apps.equipment_lifecycle.models import OperationLedgerItem
        perms = ALL_LEDGER_PERMS + ALL_OPERATION_PERMS + [LEDGER_HANDLE_PERM]
        user = make_user('legacy_convert_user', perms=perms)
        client = make_client(user)
        system = make_system(user)
        _drop_ledger_type_check()
        try:
            ledger = OperationLedger.objects.create(
                ledger_no='EL-INS-20260101-0001', ledger_type='inspection',
                status='completed',
                tenant_id=user.tenant_id, created_by=user)
            item = OperationLedgerItem.objects.create(
                ledger=ledger, system=system,
                item_name_snapshot='历史巡检项', input_type='text',
                result='abnormal', abnormal_desc='异常', tenant_id=ledger.tenant_id)
            res = client.post(CONVERT_URL % (ledger.id, item.id),
                              json.dumps({}), content_type='application/json')
            self.assertIn('旧巡检台账', res.json().get('error', ''))
            self.assertFalse(SystemOperationRecord.objects.exists())
        finally:
            _restore_ledger_type_check()

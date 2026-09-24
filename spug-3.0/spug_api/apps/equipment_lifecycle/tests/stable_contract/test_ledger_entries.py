# -*- coding: utf-8 -*-
"""步骤 3.2 稳定契约：多系统台账、快照与时间字段（提示词二十三 第 9-14、22-23 项）。"""
from datetime import datetime

from django.test import TestCase

from apps.equipment_lifecycle.models import OperationLedger, OperationLedgerItem
from apps.equipment_lifecycle.tests.base import make_client, make_system
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    LEDGER_URL,
    create_ledger_ok,
    entry_payload,
    item_payload,
    ledger_payload,
    make_ledger_user,
    post_json,
)


class LedgerMultiSystemContractTests(TestCase):
    def setUp(self):
        self.user = make_ledger_user('entry_op')
        self.system_a = make_system(self.user, system_code='SYS-A', name='通信系统A')
        self.system_b = make_system(self.user, system_code='SYS-B', name='通信系统B')

    def test_one_ledger_contains_multiple_systems(self):
        """9. 一张台账可以包含多个系统。"""
        client = make_client(self.user)
        payload = ledger_payload([
            entry_payload(self.system_a.id, [item_payload()]),
            entry_payload(self.system_b.id, [item_payload(item_name='链路状态')]),
        ])
        data = create_ledger_ok(client, payload)
        systems = {i['system'] for i in data['items']}
        self.assertEqual(systems, {self.system_a.id, self.system_b.id})
        ledger = OperationLedger.objects.get(pk=data['id'])
        self.assertEqual(ledger.items.count(), 2)

    def test_every_item_requires_system(self):
        """10. 每条明细必须关联一个系统。"""
        client = make_client(self.user)
        payload = ledger_payload([
            entry_payload(self.system_a.id, [item_payload()]),
            {'system_id': None, 'items': [item_payload()]},
        ])
        resp = post_json(client, LEDGER_URL + '/', payload)
        self.assertTrue(resp.json().get('error'))

    def test_header_and_items_saved_together(self):
        """11. 主表和全部明细一次保存。"""
        client = make_client(self.user)
        payload = ledger_payload([
            entry_payload(self.system_a.id, [item_payload(), item_payload(item_name='第二项')]),
        ])
        data = create_ledger_ok(client, payload)
        self.assertTrue(OperationLedger.objects.filter(pk=data['id']).exists())
        self.assertEqual(
            OperationLedgerItem.objects.filter(ledger_id=data['id']).count(), 2)
        self.assertTrue(data['ledger_no'].startswith('EL-WM-'))

    def test_invalid_item_rolls_back_whole_ledger(self):
        """12. 任一明细校验失败时整张台账回滚（不产生只有表头没有明细的台账）。"""
        client = make_client(self.user)
        before = OperationLedger.objects.count()
        payload = ledger_payload([
            entry_payload(self.system_a.id, [item_payload()]),
            entry_payload(self.system_b.id, [
                item_payload(item_name='电压测量', input_type='number',
                             value_text='', value_number='abc')]),
        ])
        resp = post_json(client, LEDGER_URL + '/', payload)
        self.assertTrue(resp.json().get('error'))
        self.assertIn('填写值', resp.json()['error'])
        self.assertEqual(OperationLedger.objects.count(), before)
        self.assertFalse(OperationLedgerItem.objects.exists())

    def test_fk_survives_system_rename(self):
        """13. 系统名称修改后外键仍有效。"""
        client = make_client(self.user)
        data = create_ledger_ok(client, ledger_payload(
            [entry_payload(self.system_a.id, [item_payload()])]))
        item = OperationLedgerItem.objects.get(ledger_id=data['id'])
        self.system_a.name = '通信系统A-改名后'
        self.system_a.save()
        item.refresh_from_db()
        self.assertEqual(item.system_id, self.system_a.id)
        self.assertEqual(item.system.name, '通信系统A-改名后')

    def test_history_shows_system_snapshot(self):
        """14. 历史台账显示保存时的系统名称和编号快照。"""
        client = make_client(self.user)
        data = create_ledger_ok(client, ledger_payload(
            [entry_payload(self.system_a.id, [item_payload()])]))
        item = OperationLedgerItem.objects.get(ledger_id=data['id'])
        self.assertEqual(item.system_name_snapshot, '通信系统A')
        self.assertEqual(item.system_code_snapshot, 'SYS-A')
        self.assertEqual(item.system_location_snapshot, '烟台中心站机房A')
        self.system_a.name = '新名字系统'
        self.system_a.system_code = 'SYS-A'  # 编码不可变，仅名称变化
        self.system_a.save()
        item.refresh_from_db()
        self.assertEqual(item.system_name_snapshot, '通信系统A')
        resp = make_client(self.user).get('%s/%s/' % (LEDGER_URL, data['id']))
        view = resp.json()['data']['items'][0]
        self.assertEqual(view['system_name'], '通信系统A')
        self.assertEqual(view['system_code'], 'SYS-A')

    def test_executed_and_entry_times_saved_separately(self):
        """22. 实际执行时间与平台录入时间分别保存。"""
        client = make_client(self.user)
        data = create_ledger_ok(client, ledger_payload(
            [entry_payload(self.system_a.id, [
                item_payload(executed_at='2026-09-10 09:30')])]))
        ledger = OperationLedger.objects.get(pk=data['id'])
        item = OperationLedgerItem.objects.get(ledger_id=data['id'])
        self.assertEqual(str(ledger.executed_date), '2026-09-10')
        self.assertEqual(ledger.executed_start, datetime(2026, 9, 10, 9, 0))
        self.assertEqual(ledger.executed_end, datetime(2026, 9, 10, 11, 0))
        self.assertEqual(item.executed_at, datetime(2026, 9, 10, 9, 30))
        # created_at 为录入时间（当前），晚于实际执行日期
        self.assertGreater(ledger.created_at.date(), ledger.executed_date)

    def test_manual_ledger_entry_note_removed(self):
        """23. 补录说明字段已删除（2026-09-21）：临时直接新建不再要求补录说明。"""
        client = make_client(self.user)
        payload = ledger_payload(
            [entry_payload(self.system_a.id, [item_payload()])], created_from='manual')
        data = create_ledger_ok(client, payload)
        self.assertNotIn('entry_note', data)
        self.assertNotIn('shift', data)
        self.assertNotIn('location_scope', data)
        self.assertNotIn('collaborator_names', data)
        self.assertNotIn('summary', data)

    def test_ledger_no_unique_per_type_and_day(self):
        """台账编号按类型+日期自增且租户内唯一。"""
        client = make_client(self.user)
        first = create_ledger_ok(client, ledger_payload(
            [entry_payload(self.system_a.id, [item_payload()])]))
        second = create_ledger_ok(client, ledger_payload(
            [entry_payload(self.system_a.id, [item_payload()])]))
        self.assertNotEqual(first['ledger_no'], second['ledger_no'])
        self.assertTrue(first['ledger_no'].startswith('EL-WM-20260910-'))

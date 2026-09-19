# -*- coding: utf-8 -*-
"""步骤 3.2 稳定契约：巡检点（提示词二十三 第 1-4 项）。"""
from django.test import TestCase

from apps.equipment_lifecycle.models import OperationLedgerItem, SystemInspectionPoint
from apps.equipment_lifecycle.tests.base import make_client, make_system
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    POINT_URL,
    create_ledger_ok,
    entry_payload,
    item_payload,
    ledger_payload,
    make_ledger_user,
    make_point,
    post_json,
    put_json,
)


class InspectionPointContractTests(TestCase):
    def setUp(self):
        self.user = make_ledger_user('point_op')
        self.system = make_system(self.user)

    def test_point_must_belong_to_system(self):
        """1. 巡检点必须关联系统 ID：缺少 system 或 system 不存在时创建失败。"""
        client = make_client(self.user)
        resp = post_json(client, POINT_URL + '/', {'point_code': 'P-X', 'name': '无系统巡检点'})
        data = resp.json()
        self.assertTrue(data.get('error'))
        # 传一个不存在的系统 ID 同样失败
        resp = post_json(client, POINT_URL + '/', {'system': 999999, 'point_code': 'P-X', 'name': 'x'})
        self.assertTrue(resp.json().get('error'))
        self.assertFalse(SystemInspectionPoint.objects.filter(point_code='P-X').exists())

    def test_point_cannot_reference_other_tenant_system(self):
        """2. 巡检点不能关联其他租户的系统。"""
        other_admin = make_ledger_user('other_point_admin', tenant_id='tenant-b')
        other_system = make_system(other_admin, tenant_id='tenant-b')
        client = make_client(self.user)
        resp = post_json(client, POINT_URL + '/', {
            'system': other_system.id, 'point_code': 'P-B', 'name': '越权巡检点'})
        data = resp.json()
        self.assertTrue(data.get('error'))
        self.assertFalse(SystemInspectionPoint.objects.filter(point_code='P-B').exists())

    def test_deactivated_point_rejected_for_new_ledger(self):
        """3. 停用巡检点不能用于新台账。"""
        point = make_point(self.system, self.user)
        point.is_active = False
        point.save()
        client = make_client(self.user)
        payload = ledger_payload([
            entry_payload(self.system.id, [item_payload(inspection_point_id=point.id)])])
        resp = post_json(client, '/equipment-lifecycle/ledgers/', payload)
        data = resp.json()
        self.assertTrue(data.get('error'))
        self.assertIn('停用', data['error'])

    def test_history_keeps_point_snapshot_after_deactivation(self):
        """4. 历史台账仍显示停用巡检点快照。"""
        point = make_point(self.system, self.user, name='天线区域')
        client = make_client(self.user)
        ledger = create_ledger_ok(client, ledger_payload([
            entry_payload(self.system.id, [item_payload(inspection_point_id=point.id)])]))
        point.is_active = False
        point.save()
        item = OperationLedgerItem.objects.get(ledger_id=ledger['id'])
        self.assertEqual(item.inspection_point_id, point.id)
        self.assertEqual(item.point_name_snapshot, '天线区域')
        # 详情接口仍返回快照名称
        resp = make_client(self.user).get('/equipment-lifecycle/ledgers/%s/' % ledger['id'])
        detail = resp.json()['data']
        target = [i for i in detail['items'] if i['id'] == item.id][0]
        self.assertEqual(target['inspection_point_name'], '天线区域')

    def test_point_unique_code_within_system(self):
        """巡检点同一租户同一系统内编码唯一（补充校验）。"""
        client = make_client(self.user)
        first = post_json(client, POINT_URL + '/', {
            'system': self.system.id, 'point_code': 'P-DUP', 'name': '操作席'})
        self.assertFalse(first.json().get('error'))
        second = post_json(client, POINT_URL + '/', {
            'system': self.system.id, 'point_code': 'P-DUP', 'name': '操作席2'})
        self.assertTrue(second.json().get('error'))

    def test_point_put_and_active(self):
        """巡检点编辑与停用走管理权限。"""
        point = make_point(self.system, self.user)
        client = make_client(self.user)
        resp = put_json(client, '%s/%s/' % (POINT_URL, point.id), {'name': '电源区域'})
        self.assertFalse(resp.json().get('error'))
        resp = put_json(client, '%s/%s/active/' % (POINT_URL, point.id), {'is_active': False})
        self.assertFalse(resp.json().get('error'))
        point.refresh_from_db()
        self.assertFalse(point.is_active)

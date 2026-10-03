# -*- coding: utf-8 -*-
"""台账异常转故障（2026-09-30 工单下线后仅存链路）稳定契约测试。

覆盖转换行为契约：台账异常转故障（条件、重新处置、来源与目标双向追溯、
处置状态动态计算）。转换必须复用步骤 3.1 的正式故障创建服务（同一事务）。
故障生成维修工单 / 台账异常直接转工单等工单链路已随工单功能整体删除
（API 移除契约见 test_work_order_removal.py）。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
from django.test import TestCase

from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    OperationLedger,
    OperationLedgerItem,
    SystemFault,
)

from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS, make_client, make_system, make_user,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS, entry_payload, item_payload,
    ledger_payload, make_ledger_user, post_json,
)

ALL_HANDLE_PERMS = ALL_LEDGER_PERMS + [
    'equipment_lifecycle.ledger.handle_exception',
]

CONVERT_FAULT_URL = '/equipment-lifecycle/ledgers/{ledger}/items/{item}/convert-to-fault/'


class ConversionTestBase(TestCase):
    """公共夹具：两个租户、可用系统、台账权限用户与台账创建工具。"""

    def setUp(self):
        # 转故障动作要求"处置权限 + 故障新增权限"双权限
        self.admin = make_user(
            'cv_admin', ALL_SYSTEM_PERMS + ALL_HANDLE_PERMS + [
                'equipment_lifecycle.fault.view', 'equipment_lifecycle.fault.add',
                'equipment_lifecycle.fault.edit', 'equipment_lifecycle.fault.handle',
                'equipment_lifecycle.fault.recover', 'equipment_lifecycle.fault.close',
                'equipment_lifecycle.fault.del',
            ], tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.system_a = make_system(self.admin, tenant_id='tenant_a',
                                    system_code='SYS-A1', name='烟台通信系统',
                                    install_location='机房A')
        self.system_a2 = make_system(self.admin, tenant_id='tenant_a',
                                     system_code='SYS-A2', name='威海监控系统',
                                     install_location='机房B')
        self.ledger_user = make_ledger_user(
            'cv_ledger_user',
            perms=ALL_HANDLE_PERMS + ALL_SYSTEM_PERMS,
            tenant_id='tenant_a')
        self.other_ledger_user = make_ledger_user(
            'cv_ledger_user_b', perms=ALL_HANDLE_PERMS + ALL_SYSTEM_PERMS,
            tenant_id='tenant_b')
        self.system_b = make_system(self.other_ledger_user, tenant_id='tenant_b',
                                    system_code='SYS-B1',
                                    name='烟台通信系统', install_location='机房A-B')

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


class LedgerItemConvertToFaultTest(ConversionTestBase):
    """23/25/26/28/30：台账异常明细转故障。"""

    def test_abnormal_item_can_convert_to_fault(self):
        """23. 异常台账明细可以转故障（调用正式故障创建服务，同一事务）。"""
        ledger_id, item_ids = self.make_submitted_ledger()
        body = self.convert_to_fault(ledger_id, item_ids[0])
        self.assertFalse(body.get('error'), body)
        fault = SystemFault.objects.get(pk=body['data']['id'])
        # 故障系统固定为明细所属系统；转故障即进入处置中（新建即处置中）
        self.assertEqual(fault.system_id, self.system_a.id)
        self.assertEqual(fault.status, 'handling')
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
        """25. 正常、不适用或待复核明细不能转故障。"""
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
            self.convert_to_fault(lid, item.id, expect_error='只有结果为"异常"的明细可以转故障')
        self.assertEqual(SystemFault.objects.count(), 0)

    def test_non_submitted_ledger_cannot_convert(self):
        """26. 草稿、退回或作废台账不能转故障。"""
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
        self.convert_to_fault(draft_id, draft_item.id, expect_error='不能转故障')
        self.assertEqual(SystemFault.objects.count(), 0)
        # 作废
        make_client(self.ledger_user).post(
            f'/equipment-lifecycle/ledgers/{draft_id}/submit/', {},
            content_type='application/json')
        make_client(self.admin).post(
            f'/equipment-lifecycle/ledgers/{draft_id}/void/',
            {'reason': '误录入'}, content_type='application/json')
        self.convert_to_fault(draft_id, draft_item.id, expect_error='不能转故障')

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

    def test_conversion_dual_permission_enforced(self):
        """40 补充：转故障双权限（处置权限 + 故障新增权限）后端独立校验。"""
        ledger_id, item_ids = self.make_submitted_ledger()
        # 只有处置权限，无故障新增权限 → 转故障拒绝
        handle_only = make_user('cv_handle_only', ALL_HANDLE_PERMS + ALL_SYSTEM_PERMS,
                                tenant_id='tenant_a')
        self.convert_to_fault(ledger_id, item_ids[0], user=handle_only,
                              expect_error='权限拒绝')
        self.assertEqual(SystemFault.objects.count(), 0)

    def test_cross_tenant_conversion_rejected(self):
        """3 补充：跨租户的台账明细不能转故障（tenant_b 用户访问 tenant_b 的台账，
        tenant_a 用户不可见）。"""
        ledger_id, item_ids = self.make_submitted_ledger(
            system=self.system_b, user=self.other_ledger_user)
        # tenant_a 管理员访问 tenant_b 台账明细 → 不存在
        self.convert_to_fault(ledger_id, item_ids[0], expect_error='不存在')

    def test_disposition_states_cover_fault_cases(self):
        """15 补充：未处置/已转故障/目标已取消 动态计算（工单枚举已删除）。"""
        ledger_id, item_ids = self.make_submitted_ledger(abnormal_count=2)
        # 未处置
        detail = make_client(self.admin).get(
            f'/equipment-lifecycle/ledgers/{ledger_id}/').json()['data']
        disp0 = next(i for i in detail['items'] if i['id'] == item_ids[0])['disposition']
        disp1 = next(i for i in detail['items'] if i['id'] == item_ids[1])['disposition']
        self.assertEqual(disp0['status'], 'none')
        self.assertNotIn('work_order', disp0)
        # 已转故障（第一条明细）
        self.convert_to_fault(ledger_id, item_ids[0])
        detail = make_client(self.admin).get(
            f'/equipment-lifecycle/ledgers/{ledger_id}/').json()['data']
        disp0 = next(i for i in detail['items'] if i['id'] == item_ids[0])['disposition']
        self.assertEqual(disp0['status'], 'converted_fault')
        # 目标已取消：作废来源故障后展示 target_cancelled
        fault = SystemFault.objects.get(pk=disp0['fault']['id'])
        make_client(self.admin).post(f'/equipment-lifecycle/faults/{fault.id}/cancel/',
                                     {'cancel_reason': '误判异常'},
                                     content_type='application/json')
        detail = make_client(self.admin).get(
            f'/equipment-lifecycle/ledgers/{ledger_id}/').json()['data']
        disp0 = next(i for i in detail['items'] if i['id'] == item_ids[0])['disposition']
        self.assertEqual(disp0['status'], 'target_cancelled')

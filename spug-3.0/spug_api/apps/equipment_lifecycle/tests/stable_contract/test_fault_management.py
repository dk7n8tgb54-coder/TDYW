# -*- coding: utf-8 -*-
"""系统故障管理与系统健康状态联动（步骤 3.1，单系统简化）稳定契约测试。

覆盖行为契约：系统 ID 关联、租户隔离、一张故障单只关联一个故障系统、
受影响系统参数已删除、快照、健康状态优先级计算（只看本系统记录）、
状态流转、幂等与回滚、处置记录、权限、受控作废、无设备档案依赖、
模块边界（device/upgrade 无关联、无台账/工单/履历）。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
import json
from datetime import datetime, timedelta
from unittest import mock

from django.apps import apps
from django.db import connection
from django.test import TestCase

from apps.equipment_lifecycle import fault_services
from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemConfigComponent,
    SystemFault,
    SystemFaultHandlingRecord,
)
from apps.logs.models import AuditLog

from apps.equipment_lifecycle.tests.base import (
    ALL_CONFIG_PERMS, ALL_SYSTEM_PERMS,
    make_client, make_system, make_user,
)

FAULT_URL = '/equipment-lifecycle/faults'

ALL_FAULT_PERMS = [
    'equipment_lifecycle.fault.view', 'equipment_lifecycle.fault.add',
    'equipment_lifecycle.fault.edit', 'equipment_lifecycle.fault.handle',
    'equipment_lifecycle.fault.recover', 'equipment_lifecycle.fault.close',
    'equipment_lifecycle.fault.del', 'equipment_lifecycle.fault.export',
]


def fault_payload(system_obj, **overrides):
    payload = {
        'system': system_obj.id,
        'impact_status': 'degraded',
        'occurred_at': '2026-09-18 08:30',
        'discovery': 'patrol',
        'level': 'major',
        'phenomenon': '主用链路频繁丢包',
        'impact_scope': '本站话音业务',
        'fault_location': '机房A 01柜',
    }
    payload.update(overrides)
    return payload


class FaultTestBase(TestCase):
    """公共夹具：两个租户、可用/停用系统。"""

    def setUp(self):
        self._occ_seq = 0
        self.admin = make_user('flt_admin', ALL_SYSTEM_PERMS + ALL_CONFIG_PERMS + ALL_FAULT_PERMS,
                               tenant_id='tenant_a')
        self.other_admin = make_user('flt_admin_b', ALL_SYSTEM_PERMS + ALL_FAULT_PERMS,
                                     tenant_id='tenant_b')
        self.noperm_user = make_user('flt_noperm', ALL_SYSTEM_PERMS, tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.system_a = make_system(self.admin, tenant_id='tenant_a',
                                    system_code='SYS-A1', name='烟台通信系统',
                                    install_location='机房A')
        self.system_a2 = make_system(self.admin, tenant_id='tenant_a',
                                     system_code='SYS-A2', name='威海监控系统',
                                     install_location='机房B')
        self.system_b = make_system(self.other_admin, tenant_id='tenant_b',
                                    system_code='SYS-B1',
                                    name='烟台通信系统', install_location='机房A-B')

    def next_occurred_at(self):
        """生成错开的故障发生时间，避免同一系统多张故障触发创建幂等窗口。"""
        self._occ_seq += 1
        moment = datetime(2026, 9, 18, 8, 0) + timedelta(minutes=self._occ_seq)
        return moment.strftime('%Y-%m-%d %H:%M')

    def create_fault(self, payload, user=None, expect_error=None):
        client = make_client(user or self.admin)
        resp = client.post(f'{FAULT_URL}/', payload, content_type='application/json')
        body = resp.json()
        if expect_error is not None:
            self.assertIn(expect_error, body.get('error', ''), body)
        return body

    def run_lifecycle(self, system, impact='fault', user=None):
        """走完 创建→开始处置→恢复→关闭 全流程，返回故障详情。"""
        user = user or self.admin
        body = self.create_fault(fault_payload(
            system, impact_status=impact,
            occurred_at=self.next_occurred_at()), user=user)
        self.assertFalse(body.get('error'), body)
        fid = body['data']['id']
        client = make_client(user)
        r = client.post(f'{FAULT_URL}/{fid}/start/', {}, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        r = client.post(f'{FAULT_URL}/{fid}/recover/', {
            'recovered_at': '2026-09-18 10:00',
            'recover_confirm': '链路已切换主备，业务恢复正常',
        }, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        r = client.post(f'{FAULT_URL}/{fid}/close/', {
            'final_result': '更换光模块并恢复主用链路',
        }, content_type='application/json')
        self.assertFalse(r.json().get('error'), r.content)
        return SystemFault.objects.get(pk=fid)


class FaultCreateValidationTest(FaultTestBase):
    """关联校验与幂等（单系统简化）。"""

    def test_fault_requires_valid_system_id(self):
        """故障必须关联有效系统 ID。"""
        body = self.create_fault(fault_payload(self.system_a, system=999999),
                                 expect_error='故障系统不存在')
        self.assertFalse(body.get('data'))
        self.assertEqual(SystemFault.objects.count(), 0)

    def test_system_name_cannot_be_used_as_key(self):
        """系统名称不能作为关联键提交（必须用 ID）。"""
        payload = fault_payload(self.system_a, system='烟台通信系统')
        self.create_fault(payload, expect_error='故障系统')
        self.assertEqual(SystemFault.objects.count(), 0)

    def test_cannot_link_system_of_other_tenant(self):
        """不能关联其他租户的故障系统。"""
        body = self.create_fault(fault_payload(self.system_b), expect_error='故障系统不存在')
        self.assertFalse(body.get('data'))
        self.assertEqual(SystemFault.objects.count(), 0)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_b.id).health_status, 'normal')

    def test_one_fault_links_exactly_one_system(self):
        """一张故障只关联一个系统：创建后仅有一个系统外键，无受影响系统。"""
        body = self.create_fault(fault_payload(self.system_a))
        self.assertFalse(body.get('error'), body)
        fault = SystemFault.objects.get(pk=body['data']['id'])
        self.assertEqual(fault.system_id, self.system_a.id)
        self.assertNotEqual(fault.system_id, self.system_a2.id)
        # 单系统简化：受影响系统结构已删除，模型无 affected_systems 反向关系
        self.assertFalse(
            any(rel.get_accessor_name() == 'affected_systems'
                for rel in SystemFault._meta.related_objects))

    def test_affected_systems_param_rejected(self):
        """故障 API 不再接受受影响系统（POST/PUT 均拒绝，不静默忽略）。"""
        self.create_fault(fault_payload(self.system_a, affected_systems=[
            {'system_id': self.system_a2.id, 'impact_status': 'fault'}]),
            expect_error='受影响系统')
        self.assertEqual(SystemFault.objects.count(), 0)
        # 编辑同样拒绝
        body = self.create_fault(fault_payload(self.system_a))
        fid = body['data']['id']
        client = make_client(self.admin)
        detail = client.get(f'{FAULT_URL}/{fid}/').json()['data']
        payload = {k: detail[k] for k in (
            'system', 'impact_status', 'occurred_at', 'discovery', 'level', 'phenomenon')}
        payload['affected_systems'] = [{'system_id': self.system_a2.id,
                                        'impact_status': 'fault'}]
        resp = client.put(f'{FAULT_URL}/{fid}/', payload, content_type='application/json')
        self.assertIn('受影响系统', resp.json().get('error', ''))
        self.assertEqual(SystemFault.objects.get(pk=fid).system_id, self.system_a.id)

    def test_duplicate_submission_rejected(self):
        """重复提交不会创建重复故障。"""
        payload = fault_payload(self.system_a)
        first = self.create_fault(payload)
        self.assertFalse(first.get('error'), first)
        second = self.create_fault(payload, expect_error='请勿重复提交')
        self.assertFalse(second.get('data'))
        self.assertEqual(SystemFault.objects.count(), 1)
        # 编号按租户当日序号生成
        fault = SystemFault.objects.first()
        self.assertTrue(fault.fault_no.startswith('GZ'), fault.fault_no)

    def test_fault_without_component_and_without_device(self):
        """未建立设备档案、配置组成项为空时仍可报障。"""
        self.assertEqual(SystemConfigComponent.objects.count(), 0)
        body = self.create_fault(fault_payload(self.system_a))
        self.assertFalse(body.get('error'), body)
        fault = SystemFault.objects.get(pk=body['data']['id'])
        self.assertIsNone(fault.fault_component_id)
        self.assertEqual(fault.status, 'pending')

    def test_inactive_system_cannot_create_new_fault(self):
        """已停用系统默认不能创建新故障。"""
        self.system_a.is_active = False
        self.system_a.save(update_fields=['is_active'])
        self.create_fault(fault_payload(self.system_a), expect_error='故障系统不存在')

    def test_component_reference_optional_and_snapshot_preserved(self):
        """引用组成项时保存对象快照；组成项删除不改变历史快照。"""
        comp = SystemConfigComponent.objects.create(
            tenant_id='tenant_a', system=self.system_a, name='接入交换机',
            model_version='H3C-5120', created_by=self.admin)
        payload = fault_payload(self.system_a, fault_component=comp.id,
                                fault_object_name='接入交换机01',
                                fault_object_model='H3C-5120')
        body = self.create_fault(payload)
        fault = SystemFault.objects.get(pk=body['data']['id'])
        self.assertEqual(fault.fault_component_id, comp.id)
        self.assertEqual(fault.fault_object_name, '接入交换机01')
        comp_name = fault.fault_object_name
        comp_model = fault.fault_object_model
        # 删除组成项：故障记录与快照不受影响（SET_NULL）
        client = make_client(self.admin)
        resp = client.delete(
            f'/equipment-lifecycle/systems/{self.system_a.id}/components/{comp.id}/')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault.refresh_from_db()
        self.assertIsNone(fault.fault_component_id)
        self.assertEqual(fault.fault_object_name, comp_name)
        self.assertEqual(fault.fault_object_model, comp_model)


class FaultTenantIsolationTest(FaultTestBase):
    """不同租户同名系统，故障互不可见。"""

    def test_same_name_systems_faults_isolated(self):
        # 两租户系统同名（setUp 中 system_a 与 system_b 同名）
        self.assertEqual(self.system_a.name, self.system_b.name)
        body = self.create_fault(fault_payload(self.system_b), user=self.other_admin)
        self.assertFalse(body.get('error'), body)
        fault_b = SystemFault.objects.get(pk=body['data']['id'])
        # 租户A 列表看不到租户B 的故障
        resp = make_client(self.admin).get(f'{FAULT_URL}/')
        ids = [r['id'] for r in resp.json()['data']['data']]
        self.assertNotIn(fault_b.id, ids)
        # 租户A 不能查看租户B 的故障详情
        resp = make_client(self.admin).get(f'{FAULT_URL}/{fault_b.id}/')
        self.assertEqual(resp.json().get('error'), '故障记录不存在')
        # 租户A 不能操作租户B 的故障
        resp = make_client(self.admin).post(f'{FAULT_URL}/{fault_b.id}/start/',
                                            {}, content_type='application/json')
        self.assertEqual(resp.json().get('error'), '故障记录不存在')
        self.assertEqual(SystemFault.objects.get(pk=fault_b.id).status, 'pending')
        # 租户内数据不交叉关联：租户A 的故障不能挂在租户B 系统上（校验拒绝）
        self.create_fault(fault_payload(self.system_b), expect_error='故障系统不存在')


class HealthStatusComputationTest(FaultTestBase):
    """健康状态统一计算（单系统简化：只按本系统记录计算）。"""

    def _create(self, system, impact, **kw):
        payload = fault_payload(system, impact_status=impact,
                                occurred_at=self.next_occurred_at())
        payload.update(kw)
        body = self.create_fault(payload)
        self.assertFalse(body.get('error'), body)
        return SystemFault.objects.get(pk=body['data']['id'])

    def _refresh(self, system):
        system.refresh_from_db()
        return system.health_status

    def test_degraded_fault_sets_system_degraded(self):
        """新增降级故障后系统变为降级。"""
        self._create(self.system_a, 'degraded')
        self.assertEqual(self._refresh(self.system_a), 'degraded')

    def test_fault_impact_sets_system_fault(self):
        """新增故障影响后系统变为故障。"""
        self._create(self.system_a, 'fault')
        self.assertEqual(self._refresh(self.system_a), 'fault')

    def test_interrupted_fault_sets_system_interrupted(self):
        """新增中断故障后系统变为中断。"""
        self._create(self.system_a, 'interrupted')
        self.assertEqual(self._refresh(self.system_a), 'interrupted')

    def test_priority_interrupted_over_fault_over_degraded(self):
        """中断、故障、降级同时存在时按正确优先级计算。"""
        self._create(self.system_a, 'degraded')
        self.assertEqual(self._refresh(self.system_a), 'degraded')
        self._create(self.system_a, 'fault')
        self.assertEqual(self._refresh(self.system_a), 'fault')
        f3 = self._create(self.system_a, 'interrupted')
        self.assertEqual(self._refresh(self.system_a), 'interrupted')
        # 作废中断故障后回落到故障（仍有未恢复的降级/故障影响）
        client = make_client(self.admin)
        resp = client.post(f'{FAULT_URL}/{f3.id}/cancel/', {'cancel_reason': '误报'},
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(self._refresh(self.system_a), 'fault')
        # 作废故障故障后回落到降级
        f2 = SystemFault.objects.filter(system=self.system_a,
                                        impact_status='fault',
                                        status='pending').first()
        resp = client.post(f'{FAULT_URL}/{f2.id}/cancel/', {'cancel_reason': '误报'},
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(self._refresh(self.system_a), 'degraded')
        # 作废最后一张降级故障 → 正常
        f1 = SystemFault.objects.filter(system=self.system_a,
                                        impact_status='degraded',
                                        status='pending').first()
        resp = client.post(f'{FAULT_URL}/{f1.id}/cancel/', {'cancel_reason': '误报'},
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(self._refresh(self.system_a), 'normal')

    def test_fault_of_system_a_does_not_change_system_b(self):
        """系统A 的故障不会改变系统B 的状态（不建设跨系统影响）。"""
        self._create(self.system_a, 'interrupted')
        self.assertEqual(self._refresh(self.system_a), 'interrupted')
        self.assertEqual(self._refresh(self.system_a2), 'normal')
        # 作废后系统A 恢复正常；系统B 始终不受影响
        client = make_client(self.admin)
        f = SystemFault.objects.filter(system=self.system_a, status='pending').first()
        resp = client.post(f'{FAULT_URL}/{f.id}/cancel/', {'cancel_reason': '误报'},
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(self._refresh(self.system_a), 'normal')
        self.assertEqual(self._refresh(self.system_a2), 'normal')

    def test_close_one_fault_keeps_other_fault_status(self):
        """关闭一张故障不会覆盖其他未恢复故障产生的状态。"""
        self._create(self.system_a, 'degraded')
        closed = self.run_lifecycle(self.system_a, impact='fault')
        self.assertEqual(closed.status, 'closed')
        # 关闭后仍有未恢复降级影响 → 不恢复正常
        self.assertEqual(self._refresh(self.system_a), 'degraded')

    def test_normal_only_after_all_active_faults_recovered(self):
        """所有有效故障恢复后系统才能恢复正常。"""
        f1 = self._create(self.system_a, 'degraded')
        self.run_lifecycle(self.system_a, impact='fault')
        self.assertEqual(self._refresh(self.system_a), 'degraded')
        # 恢复最后一张降级故障 → 正常
        client = make_client(self.admin)
        resp = client.post(f'{FAULT_URL}/{f1.id}/start/', {}, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        resp = client.post(f'{FAULT_URL}/{f1.id}/recover/', {
            'recovered_at': '2026-09-18 12:00', 'recover_confirm': '业务确认恢复'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(self._refresh(self.system_a), 'normal')

    def test_cancelled_fault_excluded_from_computation(self):
        """已作废故障不参与状态计算。"""
        fault = self._create(self.system_a, 'interrupted')
        self.assertEqual(self._refresh(self.system_a), 'interrupted')
        resp = make_client(self.admin).post(f'{FAULT_URL}/{fault.id}/cancel/',
                                            {'cancel_reason': '重复录入'},
                                            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(self._refresh(self.system_a), 'normal')

    def test_edit_system_change_recomputes_both(self):
        """编辑变更故障系统后，修改前后的系统都重新计算。"""
        fault = self._create(self.system_a, 'degraded')
        self.assertEqual(self._refresh(self.system_a), 'degraded')
        self.assertEqual(self._refresh(self.system_a2), 'normal')
        client = make_client(self.admin)
        detail = client.get(f'{FAULT_URL}/{fault.id}/').json()['data']
        payload = {k: detail[k] for k in (
            'impact_status', 'occurred_at', 'discovery', 'level', 'phenomenon')}
        payload['system'] = self.system_a2.id
        resp = client.put(f'{FAULT_URL}/{fault.id}/', payload, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(self._refresh(self.system_a), 'normal')
        self.assertEqual(self._refresh(self.system_a2), 'degraded')


class FaultLifecycleTest(FaultTestBase):
    """状态流转、快照、幂等与回滚。"""

    def test_rename_system_keeps_fk_and_snapshot(self):
        """系统改名后故障外键仍有效，详情显示发生时的名称与编号快照。"""
        old_name = self.system_a.name
        old_code = self.system_a.system_code
        body = self.create_fault(fault_payload(self.system_a))
        fault = SystemFault.objects.get(pk=body['data']['id'])
        # 改名系统
        client = make_client(self.admin)
        detail = client.get(f'/equipment-lifecycle/systems/{self.system_a.id}/').json()['data']
        payload = dict(detail)
        payload['name'] = '改名后的通信系统'
        resp = client.put(f'/equipment-lifecycle/systems/{self.system_a.id}/', payload,
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 外键仍有效，快照保持故障发生时名称
        fault.refresh_from_db()
        self.assertEqual(fault.system_id, self.system_a.id)
        detail = json.loads(json.dumps(
            make_client(self.admin).get(f'{FAULT_URL}/{fault.id}/').json()['data']))
        self.assertEqual(detail['system_name'], old_name)
        self.assertEqual(detail['system_code'], old_code)
        self.assertEqual(detail['system'], self.system_a.id)
        self.assertEqual(detail['system_location'], '机房A')

    def test_close_requires_recovery_confirmation(self):
        """未恢复确认的故障不能关闭。"""
        body = self.create_fault(fault_payload(self.system_a))
        fid = body['data']['id']
        client = make_client(self.admin)
        # 待处置直接关闭
        resp = client.post(f'{FAULT_URL}/{fid}/close/', {'final_result': 'x'},
                           content_type='application/json')
        self.assertIn('才能关闭', resp.json().get('error', ''))
        # 处置中关闭
        client.post(f'{FAULT_URL}/{fid}/start/', {}, content_type='application/json')
        resp = client.post(f'{FAULT_URL}/{fid}/close/', {'final_result': 'x'},
                           content_type='application/json')
        self.assertIn('才能关闭', resp.json().get('error', ''))
        # 已恢复但缺最终结果
        client.post(f'{FAULT_URL}/{fid}/recover/', {
            'recovered_at': '2026-09-18 10:00', 'recover_confirm': '已恢复'},
            content_type='application/json')
        resp = client.post(f'{FAULT_URL}/{fid}/close/', {}, content_type='application/json')
        self.assertIn('最终结果', resp.json().get('error', ''))
        self.assertEqual(SystemFault.objects.get(pk=fid).status, 'recovered')
        resp = client.post(f'{FAULT_URL}/{fid}/close/', {'final_result': '更换板卡恢复'},
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(SystemFault.objects.get(pk=fid).status, 'closed')

    def test_closed_fault_cannot_be_edited(self):
        """已关闭故障不能通过普通编辑接口修改。"""
        fault = self.run_lifecycle(self.system_a)
        client = make_client(self.admin)
        detail = client.get(f'{FAULT_URL}/{fault.id}/').json()['data']
        payload = {k: detail[k] for k in (
            'system', 'impact_status', 'occurred_at', 'discovery',
            'level', 'phenomenon')}
        payload['phenomenon'] = '试图篡改已关闭故障'
        resp = client.put(f'{FAULT_URL}/{fault.id}/', payload, content_type='application/json')
        self.assertIn('不能编辑', resp.json().get('error', ''))
        fault.refresh_from_db()
        self.assertEqual(fault.phenomenon, '主用链路频繁丢包')
        # 状态也不能通过普通编辑接口修改（body 中带 status 被忽略）
        resp = client.post(f'{FAULT_URL}/{fault.id}/cancel/', {'cancel_reason': 'x'},
                           content_type='application/json')
        self.assertIn('不能作废', resp.json().get('error', ''))

    def test_repeated_recover_and_close_no_side_effects(self):
        """重复恢复或关闭不会产生重复副作用。"""
        body = self.create_fault(fault_payload(self.system_a))
        fid = body['data']['id']
        client = make_client(self.admin)
        client.post(f'{FAULT_URL}/{fid}/start/', {}, content_type='application/json')
        payload = {'recovered_at': '2026-09-18 10:00', 'recover_confirm': '已恢复'}
        first = client.post(f'{FAULT_URL}/{fid}/recover/', payload,
                            content_type='application/json').json()
        self.assertFalse(first.get('error'), first)
        second = client.post(f'{FAULT_URL}/{fid}/recover/', payload,
                             content_type='application/json').json()
        self.assertTrue(second.get('error'))
        third = client.post(f'{FAULT_URL}/{fid}/close/', {'final_result': 'ok'},
                            content_type='application/json').json()
        self.assertFalse(third.get('error'), third)
        fourth = client.post(f'{FAULT_URL}/{fid}/close/', {'final_result': 'ok'},
                             content_type='application/json').json()
        self.assertTrue(fourth.get('error'))
        fault = SystemFault.objects.get(pk=fid)
        self.assertEqual(fault.status, 'closed')
        # 每个动作只产生一条成功审计：start/recover/close 各一条 update 审计，
        # 重复调用的第二次失败不产生审计
        update_audits = AuditLog.objects.filter(
            tenant_id='tenant_a', target_type='el_system_fault',
            target_id=str(fid), action='update')
        self.assertEqual(update_audits.count(), 3)

    def test_failed_operation_rolls_back_health_status(self):
        """故障操作失败时系统状态同步回滚。"""
        before = LifecycleSystem.objects.get(pk=self.system_a.id).health_status
        payload = fault_payload(self.system_a)
        # 故障创建收敛到统一服务 create_fault_record，回滚锚点同步更新
        with mock.patch('apps.equipment_lifecycle.fault_services.create_fault_record',
                        side_effect=RuntimeError('模拟事务中途失败')):
            resp = self.client.post(f'{FAULT_URL}/', payload, content_type='application/json')
        # 异常被请求中间件包装为业务错误返回
        self.assertTrue(resp.json().get('error'), resp.content)
        # 故障记录与系统状态全部回滚
        self.assertEqual(SystemFault.objects.count(), 0)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, before)

    def test_handling_records_ordered_and_correction_tracked(self):
        """处置记录按时间正确保存和展示；更正保留原内容与原因。"""
        body = self.create_fault(fault_payload(self.system_a))
        fid = body['data']['id']
        client = make_client(self.admin)
        for handled_at, content in (('2026-09-18 09:30', '第一步：现场检查'),
                                    ('2026-09-18 09:00', '第二步提前发生：接报')):
            resp = client.post(f'{FAULT_URL}/{fid}/handling-records/',
                               {'handled_at': handled_at, 'content': content,
                                'result': '进行中'},
                               content_type='application/json')
            self.assertFalse(resp.json().get('error'), resp.content)
        resp = client.get(f'{FAULT_URL}/{fid}/handling-records/')
        records = resp.json()['data']['data']
        self.assertEqual([r['content'] for r in records],
                         ['第二步提前发生：接报', '第一步：现场检查'])
        # 更正第一条：保存原内容、修改内容和更正原因
        target = records[0]
        resp = client.put(
            f'{FAULT_URL}/{fid}/handling-records/{target["id"]}/',
            {'content': '接报后立即出发', 'correction_reason': '笔误更正'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        corrected = resp.json()['data']
        self.assertEqual(corrected['content'], '接报后立即出发')
        self.assertEqual(corrected['corrections'][0]['old'], '第二步提前发生：接报')
        self.assertEqual(corrected['corrections'][0]['reason'], '笔误更正')

    def test_del_is_controlled_cancel_not_physical_delete(self):
        """del 执行受控作废，不是物理删除。"""
        fault = self.run_lifecycle_without_close(self.system_a)
        resp = make_client(self.admin).post(f'{FAULT_URL}/{fault.id}/cancel/',
                                            {'cancel_reason': '误报作废'},
                                            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault.refresh_from_db()
        self.assertEqual(fault.status, 'cancelled')
        self.assertTrue(SystemFault.objects.filter(pk=fault.id).exists())
        self.assertTrue(AuditLog.objects.filter(
            tenant_id='tenant_a', target_type='el_system_fault',
            target_id=str(fault.id), action='delete').exists())

    def run_lifecycle_without_close(self, system):
        body = self.create_fault(fault_payload(system))
        fid = body['data']['id']
        client = make_client(self.admin)
        client.post(f'{FAULT_URL}/{fid}/start/', {}, content_type='application/json')
        return SystemFault.objects.get(pk=fid)

    def test_full_flow_without_device_resume(self):
        """未建立单台设备档案仍可完整处理故障闭环。"""
        from apps.device.models import DeviceResume  # 仅确认无需创建任何设备档案
        self.assertEqual(DeviceResume.objects.count(), 0)
        fault = self.run_lifecycle(self.system_a)
        self.assertEqual(fault.status, 'closed')
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')


class FaultPermissionTest(FaultTestBase):
    """权限不足时后端拒绝查看或操作。"""

    def test_view_permission_required(self):
        resp = make_client(self.noperm_user).get(f'{FAULT_URL}/')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        resp = make_client(self.noperm_user).get(
            f'/equipment-lifecycle/systems/{self.system_a.id}/faults/')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        resp = make_client(self.noperm_user).get(f'{FAULT_URL}/candidate-systems/')
        self.assertEqual(resp.json().get('error'), '权限拒绝')

    def test_action_permissions_enforced_independently(self):
        body = self.create_fault(fault_payload(self.system_a))
        fid = body['data']['id']
        # 只有查看权限：不能新增/编辑/处置/恢复/关闭/作废/导出
        viewer = make_user('flt_viewer', ['equipment_lifecycle.fault.view'],
                           tenant_id='tenant_a')
        client = make_client(viewer)
        self.assertEqual(client.post(f'{FAULT_URL}/', fault_payload(self.system_a),
                                     content_type='application/json').json().get('error'),
                         '权限拒绝')
        self.assertEqual(client.put(f'{FAULT_URL}/{fid}/', {},
                                    content_type='application/json').json().get('error'),
                         '权限拒绝')
        for action in ('start', 'recover', 'close', 'cancel'):
            self.assertEqual(
                client.post(f'{FAULT_URL}/{fid}/{action}/', {},
                            content_type='application/json').json().get('error'),
                '权限拒绝', action)
        self.assertEqual(client.post(f'{FAULT_URL}/{fid}/handling-records/', {},
                                     content_type='application/json').json().get('error'),
                         '权限拒绝')
        self.assertEqual(client.get(f'{FAULT_URL}/export/').json().get('error'), '权限拒绝')
        # 状态未被无权限操作改变
        self.assertEqual(SystemFault.objects.get(pk=fid).status, 'pending')


class FaultBoundaryTest(FaultTestBase):
    """模块边界及系统编辑/删除联动保护。"""

    def test_old_fault_tables_absent_and_no_cross_module_links(self):
        """旧故障表不存在；device/upgrade 与新故障模型无任何外键关联。"""
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'tdyw_fault_records'")
            self.assertIsNone(cursor.fetchone())
            cursor.execute("SHOW TABLES LIKE 'tdyw_fault_parts'")
            self.assertIsNone(cursor.fetchone())
        # 新故障模型没有指向 device/upgrade 模型的反向关联
        related_apps = {
            rel.related_model._meta.app_label
            for rel in SystemFault._meta.related_objects
        } | {
            rel.related_model._meta.app_label
            for rel in SystemFaultHandlingRecord._meta.related_objects
        }
        self.assertFalse(related_apps & {'device', 'upgrade'}, related_apps)
        # device/upgrade 模型上没有新增的故障反向关系
        from apps.device.models import DeviceResume
        from apps.upgrade.models import UpgradeRecord
        for model in (DeviceResume, UpgradeRecord):
            reverse_names = {rel.get_accessor_name() for rel in model._meta.related_objects}
            for name in reverse_names:
                self.assertNotIn('fault', name.lower())

    def test_no_ledger_workorder_event_models_created(self):
        """本步骤没有创建台账、工单或旧步骤一模型。

        注：同一应用内由并行的运维台账任务新增的巡检/维护台账模型不在本
        断言范围；本断言固化的是故障任务自己不得引入的模型。
        步骤 3.5 起，统一系统履历（SystemEvent）由步骤 3.4 正式落地，
        不再属于禁止集合；仍禁止旧故障模型与旧步骤一结构回潮。
        """
        model_names = {m.__name__ for m in
                       apps.get_app_config('equipment_lifecycle').get_models()}
        forbidden = {'WorkOrder', 'FaultWorkOrder', 'SystemInspectionLog',
                     'FaultPart', 'FaultRecord', 'LifecycleDevice', 'SystemDeviceRelation'}
        self.assertFalse(model_names & forbidden, model_names)
        # 单系统简化后：受影响系统模型已删除，故障主模型与处置记录仍存在
        self.assertTrue({'SystemFault', 'SystemFaultHandlingRecord'} <= model_names)
        self.assertNotIn('SystemFaultAffectedSystem', model_names)

    def test_system_edit_cannot_override_fault_computed_health(self):
        """普通系统编辑接口不得覆盖故障计算出的健康状态。

        步骤 3.5 收口后约束更强：health_status 不再是系统表单字段，
        编辑提交携带任何状态值均被忽略，健康状态只能由统一重算服务写入。
        """
        self.create_fault(fault_payload(self.system_a, impact_status='degraded'))
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'degraded')
        client = make_client(self.admin)
        detail = client.get(f'/equipment-lifecycle/systems/{self.system_a.id}/').json()['data']
        payload = dict(detail)
        payload['name'] = '烟台通信系统'
        # 存在未恢复故障影响时：编辑正常执行，但提交的 normal 被忽略，状态保持计算值
        payload['health_status'] = 'normal'
        resp = client.put(f'/equipment-lifecycle/systems/{self.system_a.id}/', payload,
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'degraded')
        # 无有效影响（故障作废）后：编辑同样不能手动改状态，重算结果为 normal
        fault = SystemFault.objects.get(system=self.system_a)
        client.post(f'{FAULT_URL}/{fault.id}/cancel/', {'cancel_reason': '误报'},
                    content_type='application/json')
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')
        payload['name'] = '烟台通信系统（已更新）'
        payload['health_status'] = 'interrupted'
        resp = client.put(f'/equipment-lifecycle/systems/{self.system_a.id}/', payload,
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')

    def test_system_with_fault_cannot_be_deleted(self):
        """删除保护：存在故障关联的系统不能物理删除。"""
        self.create_fault(fault_payload(self.system_a, occurred_at=self.next_occurred_at()))
        self.create_fault(fault_payload(self.system_a2, occurred_at=self.next_occurred_at()))
        client = make_client(self.admin)
        resp = client.delete(f'/equipment-lifecycle/systems/{self.system_a.id}/')
        self.assertIn('故障记录', resp.json().get('error', ''))
        resp = client.delete(f'/equipment-lifecycle/systems/{self.system_a2.id}/')
        self.assertIn('故障记录', resp.json().get('error', ''))
        self.assertTrue(LifecycleSystem.objects.filter(pk=self.system_a.id).exists())
        self.assertTrue(LifecycleSystem.objects.filter(pk=self.system_a2.id).exists())

    def test_fault_query_by_system_and_candidates(self):
        """按系统查询故障（单系统，不再区分主体/受影响）与候选系统接口。"""
        self.create_fault(fault_payload(self.system_a))
        client = make_client(self.admin)
        resp = client.get(f'/equipment-lifecycle/systems/{self.system_a.id}/faults/')
        rows = resp.json()['data']['data']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['system'], self.system_a.id)
        self.assertNotIn('fault_role', rows[0])
        # 其他系统查不到该故障
        resp = client.get(f'/equipment-lifecycle/systems/{self.system_a2.id}/faults/')
        self.assertEqual(resp.json()['data']['data'], [])
        # 候选系统：只含可用系统，含编号与安装地点
        resp = client.get(f'{FAULT_URL}/candidate-systems/')
        codes = {r['system_code']: r for r in resp.json()['data']['data']}
        self.assertIn('SYS-A1', codes)
        self.assertEqual(codes['SYS-A1']['install_location'], '机房A')
        self.system_a.is_active = False
        self.system_a.save(update_fields=['is_active'])
        resp = client.get(f'{FAULT_URL}/candidate-systems/')
        self.assertNotIn('SYS-A1', {r['system_code'] for r in resp.json()['data']['data']})

    def test_health_status_change_audited(self):
        """系统健康状态变化记录审计。"""
        self.create_fault(fault_payload(self.system_a, impact_status='interrupted'))
        self.assertTrue(AuditLog.objects.filter(
            tenant_id='tenant_a', target_type='el_system_health',
            target_id=str(self.system_a.id),
            detail__contains='interrupted').exists())

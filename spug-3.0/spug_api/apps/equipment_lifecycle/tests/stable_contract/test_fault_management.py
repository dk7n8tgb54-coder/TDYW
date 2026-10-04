# -*- coding: utf-8 -*-
"""系统故障处置与系统健康状态联动（步骤 3.1，单系统简化）稳定契约测试。

覆盖行为契约：系统 ID 关联、租户隔离、一张故障单只关联一个故障系统、
受影响系统参数已删除、快照、健康状态优先级计算（只看本系统记录）、
状态流转、幂等与回滚、处理进展（进展类型/时间默认/更正留痕）、
故障登记人与进展记录人（实际操作人员，共用登录账号可区分）、权限、
受控作废、无设备档案依赖、
模块边界（device/upgrade 无关联、无台账/履历）。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
import json
from datetime import datetime, timedelta
from unittest import mock

from django.apps import apps
from django.db import connection
from django.test import TestCase

from apps.account.models import User
from apps.equipment_lifecycle import fault_services
from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemFault,
    SystemFaultHandlingRecord,
)
from apps.logs.models import AuditLog

from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS,
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
        # 默认构造"影响系统运行"的故障：健康状态相关契约均基于显式影响运行；
        # "部件故障但不影响运行"（新默认）的契约见 test_health_split.py
        'affects_system_operation': True,
        'impact_status': 'degraded',
        'occurred_at': '2026-09-18 08:30',
        'phenomenon': '主用链路频繁丢包',
        'registrar_name': '登记人甲',
    }
    payload.update(overrides)
    return payload


class FaultTestBase(TestCase):
    """公共夹具：两个租户、可用/停用系统。"""

    def setUp(self):
        self._occ_seq = 0
        self.admin = make_user('flt_admin', ALL_SYSTEM_PERMS + ALL_FAULT_PERMS,
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
        """走完 创建（即处置中）→确认恢复并结案 全流程，返回故障详情。"""
        user = user or self.admin
        body = self.create_fault(fault_payload(
            system, impact_status=impact,
            occurred_at=self.next_occurred_at()), user=user)
        self.assertFalse(body.get('error'), body)
        fid = body['data']['id']
        client = make_client(user)
        r = client.post(f'{FAULT_URL}/{fid}/recover/', {
            'recovered_at': '2026-09-18 10:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '更换光模块并恢复主用链路，业务验证恢复正常',
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
            expect_error='affected_systems')
        self.assertEqual(SystemFault.objects.count(), 0)
        # 编辑同样拒绝
        body = self.create_fault(fault_payload(self.system_a))
        fid = body['data']['id']
        client = make_client(self.admin)
        detail = client.get(f'{FAULT_URL}/{fid}/').json()['data']
        payload = {k: detail[k] for k in (
            'system', 'impact_status', 'occurred_at', 'phenomenon')}
        payload['affected_systems'] = [{'system_id': self.system_a2.id,
                                        'impact_status': 'fault'}]
        resp = client.put(f'{FAULT_URL}/{fid}/', payload, content_type='application/json')
        self.assertIn('affected_systems', resp.json().get('error', ''))
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
        """未建立设备档案（配置组成项已下线）时仍可报障。"""
        body = self.create_fault(fault_payload(self.system_a))
        self.assertFalse(body.get('error'), body)
        fault = SystemFault.objects.get(pk=body['data']['id'])
        self.assertEqual(fault.fault_component_name, '')
        self.assertEqual(fault.status, 'handling')

    def test_inactive_system_cannot_create_new_fault(self):
        """已停用系统默认不能创建新故障。"""
        self.system_a.is_active = False
        self.system_a.save(update_fields=['is_active'])
        self.create_fault(fault_payload(self.system_a), expect_error='故障系统不存在')

    def test_component_api_removed(self):
        """配置组成项功能已下线：组成项接口不再可达。"""
        client = make_client(self.admin)
        resp = client.get(
            f'/equipment-lifecycle/systems/{self.system_a.id}/components/')
        self.assertEqual(resp.status_code, 404)


class FaultFieldRetirementTest(FaultTestBase):
    """字段退役契约（2026-09-29）：处置负责人/发现方式/级别/影响范围/故障位置
    已整体删除，恢复确认人改为手输姓名。

    产品规则：五个字段相关入参/筛选/导出列一并移除；创建/编辑/开始处置的
    旧参数出现即拒绝（不静默忽略）；恢复确认人 recovered_by_name 手动输入
    必填、不预填登录账号。
    """

    def test_removed_params_rejected_on_create(self):
        """创建接口显式拒绝已删除字段参数且不落库。"""
        base = fault_payload(self.system_a, occurred_at=self.next_occurred_at())
        for key, value in (
                ('discovery', 'patrol'), ('level', 'major'),
                ('impact_scope', '话音业务'), ('fault_location', '机房A'),
                ('handler_id', 1)):
            payload = dict(base)
            payload[key] = value
            body = self.create_fault(payload)
            self.assertIn('已不再支持参数', body.get('error', ''), body)
            self.assertIn(key, body.get('error', ''), body)
        self.assertEqual(SystemFault.objects.count(), 0)

    def test_removed_params_rejected_on_edit(self):
        """编辑接口同样拒绝已删除字段参数，原数据不被改动。"""
        fid = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at()))['data']['id']
        client = make_client(self.admin)
        detail = client.get(f'{FAULT_URL}/{fid}/').json()['data']
        edit = {k: detail[k] for k in ('system', 'impact_status', 'occurred_at', 'phenomenon')}
        edit['discovery'] = 'patrol'
        resp = client.put(f'{FAULT_URL}/{fid}/', edit, content_type='application/json')
        self.assertIn('discovery', resp.json().get('error', ''))
        fault = SystemFault.objects.get(pk=fid)
        self.assertEqual(fault.phenomenon, '主用链路频繁丢包')

    def test_start_endpoint_removed(self):
        """开始处置接口已随流程简化整体删除（新建即处置中）。"""
        fid = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at()))['data']['id']
        resp = make_client(self.admin).post(
            f'{FAULT_URL}/{fid}/start/', {'handler_id': 1},
            content_type='application/json')
        self.assertEqual(resp.status_code, 404)
        # 新建故障即处置中，无需也不存在开始处置步骤
        self.assertEqual(SystemFault.objects.get(pk=fid).status, 'handling')

    def test_legacy_status_values_rejected_by_db(self):
        """旧流程 pending/recovered 状态已删除：数据库层拒绝写入旧状态值。

        模块未上线无历史包袱：迁移 0051 收紧 CHECK 约束后，
        任何写入旧状态值的路径（含直接 SQL）都必须失败。
        """
        fid = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at()))['data']['id']
        with connection.cursor() as cursor:
            for legacy in ('pending', 'recovered'):
                with self.assertRaises(Exception):
                    cursor.execute(
                        'UPDATE tdyw_el_fault SET status = %s WHERE id = %s',
                        [legacy, fid])
        # 非法状态未被写入（保持处置中），合法状态仍可正常更新
        self.assertEqual(SystemFault.objects.get(pk=fid).status, 'handling')
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE tdyw_el_fault SET status = %s WHERE id = %s',
                ['closed', fid])
        self.assertEqual(SystemFault.objects.get(pk=fid).status, 'closed')

    def test_recover_and_close_requires_all_fields(self):
        """确认恢复并结案一次性校验：必填项缺失即拒绝且不落库，旧参数拒绝。"""
        fid = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at()))['data']['id']
        client = make_client(self.admin)
        full = {
            'recovered_at': '2026-09-18 10:00',
            'recovered_by_name': '确认人甲',
            'recovery_close_note': '更换备件并验证恢复，业务验证正常',
        }
        # 缺恢复确认人 / 缺恢复确认与结案说明 / 缺恢复时间
        for missing in ('recovered_by_name', 'recovery_close_note',
                        'recovered_at'):
            payload = {k: v for k, v in full.items() if k != missing}
            resp = client.post(f'{FAULT_URL}/{fid}/recover/', payload,
                               content_type='application/json')
            self.assertTrue(resp.json().get('error'), resp.content)
            self.assertEqual(SystemFault.objects.get(pk=fid).status, 'handling')
        # 结案说明只填空格同样拒绝（不能为空或纯空格）
        resp = client.post(f'{FAULT_URL}/{fid}/recover/', dict(
            full, recovery_close_note='   '), content_type='application/json')
        self.assertIn('结案说明不能为空', resp.json().get('error', ''))
        self.assertEqual(SystemFault.objects.get(pk=fid).status, 'handling')
        # 旧参数（恢复确认信息/最终结果）已合并删除：出现即拒绝，不静默忽略
        for old_param in ('recover_confirm', 'final_result'):
            resp = client.post(f'{FAULT_URL}/{fid}/recover/', dict(
                full, **{old_param: '旧字段内容'}),
                content_type='application/json')
            self.assertIn('不再支持参数', resp.json().get('error', ''), resp.content)
            self.assertEqual(SystemFault.objects.get(pk=fid).status, 'handling')
        # 恢复时间早于故障发生时间同样拒绝
        resp = client.post(f'{FAULT_URL}/{fid}/recover/', dict(
            full, recovered_at='2026-09-18 07:00'), content_type='application/json')
        self.assertIn('恢复时间不能早于', resp.json().get('error', ''))
        self.assertEqual(SystemFault.objects.get(pk=fid).status, 'handling')
        # 必填项齐全：一次操作直接进入终态已关闭，恢复字段完整落库
        resp = client.post(f'{FAULT_URL}/{fid}/recover/', full,
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault = SystemFault.objects.get(pk=fid)
        self.assertEqual(fault.status, 'closed')
        self.assertEqual(str(fault.recovered_at), '2026-09-18 10:00:00')
        self.assertEqual(fault.recovered_by_name, '确认人甲')
        self.assertEqual(
            fault.recovery_close_note, '更换备件并验证恢复，业务验证正常')
        self.assertIsNotNone(fault.recovered_confirmed_at)

    def test_level_filter_and_export_columns_removed(self):
        """级别筛选参数被忽略；CSV 导出不再包含发现方式/级别/处置负责人等列。"""
        self.create_fault(fault_payload(self.system_a,
                                        occurred_at=self.next_occurred_at()))
        client = make_client(self.admin)
        resp = client.get(f'{FAULT_URL}/', {'level': 'major'})
        self.assertFalse(resp.json().get('error'), resp.content)
        rows = resp.json()['data']['data']
        self.assertEqual(len(rows), 1)
        resp = client.get(f'{FAULT_URL}/export/')
        self.assertEqual(resp.status_code, 200)
        text = resp.content.decode('utf-8-sig')
        self.assertIn('恢复确认人', text)
        self.assertIn('主用链路频繁丢包', text)
        for gone in ('发现方式', '故障级别', '处置负责人', '影响范围', '故障位置'):
            self.assertNotIn(gone, text)

    def test_export_unified_close_note_and_excludes_cancelled(self):
        """导出只含"结案说明"列（与详情一致），不再含两个旧字段；
        已撤销故障默认仍不导出。"""
        closed = self.run_lifecycle(self.system_a)
        detail = make_client(self.admin).get(
            f'{FAULT_URL}/{closed.id}/').json()['data']
        client = make_client(self.admin)
        text = client.get(f'{FAULT_URL}/export/').content.decode('utf-8-sig')
        # 新列存在且内容与详情展示一致（详情接口同源字段）
        self.assertIn('结案说明', text)
        self.assertIn(detail['recovery_close_note'], text)
        # 两个旧列不再出现（新列名不包含旧列名子串，可直接断言）
        for gone in ('恢复确认信息', '最终结果'):
            self.assertNotIn(gone, text)
        # 已撤销故障不在默认导出中（撤销一张新故障后其编号不出现）
        body = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at()))
        fid = body['data']['id']
        resp = client.post(f'{FAULT_URL}/{fid}/cancel/', {'cancel_reason': '误报'},
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        rows_after = client.get(f'{FAULT_URL}/export/').content.decode('utf-8-sig')
        cancelled_no = SystemFault.objects.get(pk=fid).fault_no
        self.assertNotIn(cancelled_no, rows_after)

    def test_edit_minimal_payload_preserves_history(self):
        """精简编辑载荷（不含对象型号/序列号）保留原值，不静默清空历史数据。"""
        payload = fault_payload(self.system_a, occurred_at=self.next_occurred_at(),
                                fault_object_name='接入交换机01',
                                fault_object_model='H3C-5120', fault_object_sn='SN001')
        fid = self.create_fault(payload)['data']['id']
        client = make_client(self.admin)
        minimal = {
            'system': self.system_a.id,
            'affects_system_operation': True,
            'impact_status': 'degraded',
            'occurred_at': '2026-09-18 09:00',
            'phenomenon': '现象描述更新',
            'fault_object_name': '接入交换机02',
        }
        resp = client.put(f'{FAULT_URL}/{fid}/', minimal, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault = SystemFault.objects.get(pk=fid)
        self.assertEqual(fault.phenomenon, '现象描述更新')
        self.assertEqual(fault.fault_object_name, '接入交换机02')
        self.assertEqual(fault.fault_object_model, 'H3C-5120')
        self.assertEqual(fault.fault_object_sn, 'SN001')


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
        # 租户A 不能操作租户B 的故障（动作接口同样租户隔离）
        resp = make_client(self.admin).post(f'{FAULT_URL}/{fault_b.id}/recover/',
                                            {'recovered_at': '2026-09-18 10:00'},
                                            content_type='application/json')
        self.assertEqual(resp.json().get('error'), '故障记录不存在')
        self.assertEqual(SystemFault.objects.get(pk=fault_b.id).status, 'handling')
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
                                        status='handling').first()
        resp = client.post(f'{FAULT_URL}/{f2.id}/cancel/', {'cancel_reason': '误报'},
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(self._refresh(self.system_a), 'degraded')
        # 作废最后一张降级故障 → 正常
        f1 = SystemFault.objects.filter(system=self.system_a,
                                        impact_status='degraded',
                                        status='handling').first()
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
        f = SystemFault.objects.filter(system=self.system_a, status='handling').first()
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
        # 确认恢复并结案最后一张降级故障 → 正常
        client = make_client(self.admin)
        resp = client.post(f'{FAULT_URL}/{f1.id}/recover/', {
            'recovered_at': '2026-09-18 12:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '更换光模块恢复链路，业务确认恢复'},
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
        payload = {k: detail[k] for k in ('impact_status', 'occurred_at', 'phenomenon')}
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

    def test_close_endpoint_deprecated_merged_into_recover(self):
        """旧单独关闭接口已废弃：返回清晰业务错误且不改状态、不写审计。"""
        body = self.create_fault(fault_payload(self.system_a))
        fid = body['data']['id']
        client = make_client(self.admin)
        before_audits = AuditLog.objects.filter(
            tenant_id='tenant_a', target_type='el_system_fault',
            target_id=str(fid)).count()
        resp = client.post(f'{FAULT_URL}/{fid}/close/', {'final_result': 'x'},
                           content_type='application/json')
        # 废弃接口返回明确指引，不执行任何状态变更
        self.assertIn('确认恢复并结案', resp.json().get('error', ''))
        self.assertEqual(SystemFault.objects.get(pk=fid).status, 'handling')
        self.assertEqual(AuditLog.objects.filter(
            tenant_id='tenant_a', target_type='el_system_fault',
            target_id=str(fid)).count(), before_audits)
        # 合并操作：确认恢复并结案一次事务完成（必填字段一次提交）
        payload = {
            'recovered_at': '2026-09-18 10:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '更换备件并验证恢复，业务验证正常',
        }
        resp = client.post(f'{FAULT_URL}/{fid}/recover/', payload,
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(SystemFault.objects.get(pk=fid).status, 'closed')

    def test_closed_fault_cannot_be_edited(self):
        """已关闭故障不能通过普通编辑接口修改。"""
        fault = self.run_lifecycle(self.system_a)
        client = make_client(self.admin)
        detail = client.get(f'{FAULT_URL}/{fault.id}/').json()['data']
        payload = {k: detail[k] for k in (
            'system', 'impact_status', 'occurred_at', 'phenomenon')}
        payload['phenomenon'] = '试图篡改已关闭故障'
        resp = client.put(f'{FAULT_URL}/{fault.id}/', payload, content_type='application/json')
        self.assertIn('不能编辑', resp.json().get('error', ''))
        fault.refresh_from_db()
        self.assertEqual(fault.phenomenon, '主用链路频繁丢包')
        # 状态也不能通过普通编辑接口修改（body 中带 status 被忽略）
        resp = client.post(f'{FAULT_URL}/{fault.id}/cancel/', {'cancel_reason': 'x'},
                           content_type='application/json')
        self.assertIn('已关闭的故障不能撤销', resp.json().get('error', ''))

    def test_repeated_recover_and_close_no_side_effects(self):
        """重复确认恢复并结案不产生重复副作用（终态保护 + 审计/履历只写一次）。"""
        body = self.create_fault(fault_payload(self.system_a))
        fid = body['data']['id']
        client = make_client(self.admin)
        payload = {'recovered_at': '2026-09-18 10:00',
                   'recovered_by_name': '恢复确认人甲',
                   'recovery_close_note': '更换备件并验证恢复'}
        first = client.post(f'{FAULT_URL}/{fid}/recover/', payload,
                            content_type='application/json').json()
        self.assertFalse(first.get('error'), first)
        # 已关闭为终态：重复确认恢复并结案必须失败
        second = client.post(f'{FAULT_URL}/{fid}/recover/', payload,
                             content_type='application/json').json()
        self.assertTrue(second.get('error'))
        # 废弃的单独关闭接口同样失败（返回合并指引）
        third = client.post(f'{FAULT_URL}/{fid}/close/', {'final_result': 'ok'},
                            content_type='application/json').json()
        self.assertTrue(third.get('error'))
        fault = SystemFault.objects.get(pk=fid)
        self.assertEqual(fault.status, 'closed')
        # 成功操作只产生一条 update 审计；重复/废弃调用的失败不产生审计
        update_audits = AuditLog.objects.filter(
            tenant_id='tenant_a', target_type='el_system_fault',
            target_id=str(fid), action='update')
        self.assertEqual(update_audits.count(), 1)
        # 履历"故障恢复确认"与"故障关闭"两节点各恰好一条（同一事务写入）
        from apps.equipment_lifecycle.models import SystemEvent
        actions = list(SystemEvent.objects.filter(
            tenant_id='tenant_a', source_type='fault',
            source_id=str(fid)).values_list('action', flat=True))
        self.assertEqual(sorted(actions), ['close', 'create', 'recover'])

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
        """处理进展按时间正确保存和展示；更正保留原内容与原因。"""
        body = self.create_fault(fault_payload(self.system_a))
        fid = body['data']['id']
        client = make_client(self.admin)
        for handled_at, content in (('2026-09-18 09:30', '第一步：现场检查'),
                                    ('2026-09-18 09:00', '第二步提前发生：接报')):
            resp = client.post(f'{FAULT_URL}/{fid}/handling-records/',
                               {'handled_at': handled_at, 'content': content,
                                'result': '进行中', 'recorder_name': '记录人甲'},
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
        """创建（即处置中）故障，不结案，返回故障详情。"""
        body = self.create_fault(fault_payload(system))
        fid = body['data']['id']
        return SystemFault.objects.get(pk=fid)

    def test_full_flow_without_device_archive(self):
        """未建立任何单台设备档案仍可完整处理故障闭环。"""
        fault = self.run_lifecycle(self.system_a)
        self.assertEqual(fault.status, 'closed')
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')


class FaultHandlingProgressTest(FaultTestBase):
    """处理进展契约（2026-09 改版）：类型结构化选填、时间默认、可直接恢复。

    覆盖：本方维修、送厂维修、仅测试、暂未修复等场景均能保存进展；
    进展类型可为空（历史记录兼容）；
    未恢复故障持续参与健康状态计算。
    """

    def add_progress(self, fid, user=None, expect_error=None, **overrides):
        payload = {'content': '现场检查，设备告警与现象一致',
                   'recorder_name': '记录人甲'}
        payload.update(overrides)
        client = make_client(user or self.admin)
        resp = client.post(f'{FAULT_URL}/{fid}/handling-records/', payload,
                           content_type='application/json')
        body = resp.json()
        if expect_error is not None:
            self.assertIn(expect_error, body.get('error', ''), body)
        return body

    def _create_started_fault(self, impact='fault'):
        """创建一张影响运行的有效故障（新建即处置中），返回 (fault, client)。"""
        body = self.create_fault(fault_payload(
            self.system_a, impact_status=impact, occurred_at=self.next_occurred_at()))
        self.assertFalse(body.get('error'), body)
        fid = body['data']['id']
        client = make_client(self.admin)
        return SystemFault.objects.get(pk=fid), client

    def test_progress_type_saved_as_structured_field(self):
        """进展类型以正式结构化字段存储并返回文本（送厂场景）。"""
        fault, client = self._create_started_fault()
        body = self.add_progress(fault.id, progress_type='to_vendor',
                                 content='故障部件拆下送厂家维修',
                                 result='待厂家反馈')
        self.assertFalse(body.get('error'), body)
        record = SystemFaultHandlingRecord.objects.get(pk=body['data']['id'])
        self.assertEqual(record.progress_type, 'to_vendor')
        self.assertEqual(record.to_view()['progress_type_text'], '送厂')
        # 时间线接口同样返回结构化类型
        rows = client.get(f'{FAULT_URL}/{fault.id}/handling-records/').json()['data']['data']
        target = [r for r in rows if r['id'] == record.id][0]
        self.assertEqual(target['progress_type'], 'to_vendor')
        self.assertEqual(target['progress_type_text'], '送厂')

    def test_progress_type_optional_and_default_empty(self):
        """不提交进展类型仍可保存（空串=未选择，历史记录同口径）。"""
        fault, _ = self._create_started_fault()
        body = self.add_progress(fault.id)
        self.assertFalse(body.get('error'), body)
        record = SystemFaultHandlingRecord.objects.get(pk=body['data']['id'])
        self.assertEqual(record.progress_type, '')
        self.assertEqual(record.to_view()['progress_type_text'], '')

    def test_progress_type_invalid_rejected(self):
        """非法进展类型拒绝且不落库（不通过文本拼接解析类型）。"""
        fault, _ = self._create_started_fault()
        self.add_progress(fault.id, progress_type='bogus', expect_error='进展类型不合法')
        self.assertEqual(SystemFaultHandlingRecord.objects.count(), 0)

    def test_all_progress_type_choices_accepted(self):
        """全部候选类型（检查/本方处理/送厂/厂家反馈/返还/测试/持续观察/其他）可用。"""
        choices = SystemFaultHandlingRecord.PROGRESS_TYPE_CHOICES
        fault, _ = self._create_started_fault()
        for value, _text in choices:
            body = self.add_progress(fault.id, progress_type=value)
            self.assertFalse(body.get('error'), body)
        self.assertEqual(
            SystemFaultHandlingRecord.objects.filter(fault=fault).count(),
            len(choices))

    def test_handled_at_defaults_to_now(self):
        """进展时间缺省为当前时间（服务端兜底，不信任前端默认）。"""
        from django.utils import timezone
        fault, _ = self._create_started_fault()
        body = self.add_progress(fault.id)
        self.assertFalse(body.get('error'), body)
        record = SystemFaultHandlingRecord.objects.get(pk=body['data']['id'])
        now = timezone.now()
        self.assertIsNotNone(record.handled_at)
        self.assertLessEqual(record.handled_at, now)
        self.assertGreater((now - record.handled_at).total_seconds(), -5)

    def test_future_handled_at_rejected(self):
        """进展时间晚于当前时间被拒绝。"""
        fault, _ = self._create_started_fault()
        self.add_progress(fault.id, handled_at='2099-01-01 10:00',
                          expect_error='进展时间不能晚于当前时间')
        self.assertEqual(SystemFaultHandlingRecord.objects.count(), 0)

    def test_correction_updates_type_and_keeps_history(self):
        """更正可修改进展类型并留痕；不提交类型时保留原值。"""
        fault, _ = self._create_started_fault()
        body = self.add_progress(fault.id, progress_type='check', content='初步检查')
        rid = body['data']['id']
        client = make_client(self.admin)
        # 更正提交新类型
        resp = client.put(f'{FAULT_URL}/{fault.id}/handling-records/{rid}/',
                          {'content': '确认为发射机故障', 'progress_type': 'self_fix',
                           'correction_reason': '补充定位结论'},
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemFaultHandlingRecord.objects.get(pk=rid)
        self.assertEqual(record.progress_type, 'self_fix')
        self.assertEqual(record.get_corrections()[0]['old'], '初步检查')
        # 更正不提交类型：保留原值
        resp = client.put(f'{FAULT_URL}/{fault.id}/handling-records/{rid}/',
                          {'content': '确认为发射机故障（修订）',
                           'correction_reason': '文字修订'},
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record.refresh_from_db()
        self.assertEqual(record.progress_type, 'self_fix')

    def test_unrecovered_fault_keeps_progress_and_health_impact(self):
        """暂未修复/送厂维修中：可持续追加进展，故障保持未恢复，
        影响运行的系统健康状态不显示正常。"""
        fault, client = self._create_started_fault(impact='fault')
        for progress_type, content in (
                ('check', '现场检查确认发射机无输出'),
                ('to_vendor', '发射机拆下送厂家维修'),
                ('vendor_feedback', '厂家反馈主板损坏，待返修'),
                ('watch', '备用链路保障中，持续观察')):
            body = self.add_progress(fault.id, progress_type=progress_type, content=content)
            self.assertFalse(body.get('error'), body)
        fault.refresh_from_db()
        self.assertEqual(fault.status, 'handling')
        self.assertIsNone(fault.recovered_at)
        # 系统健康状态保持故障（未恢复继续参与计算），不因持续填写进展而结束
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'fault')

    def test_fault_can_record_progress_and_recover(self):
        """仅凭处理进展即可闭环：测试通过后一次"确认恢复并结案"收尾。"""
        fault, client = self._create_started_fault(impact='degraded')
        body = self.add_progress(fault.id, progress_type='test',
                                 content='更换备件后本方测试，各项指标正常',
                                 work_hours=2.5)
        self.assertFalse(body.get('error'), body)
        resp = client.post(f'{FAULT_URL}/{fault.id}/recover/', {
            'recovered_at': '2026-09-18 11:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '更换备件并测试通过，本方测试通过，业务验证正常',
        }, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault.refresh_from_db()
        self.assertEqual(fault.status, 'closed')
        # 处理进展含工时（原工单处理记录的工时由进展承接）
        records = SystemFaultHandlingRecord.objects.filter(fault=fault)
        self.assertEqual(
            [r.work_hours for r in records if r.work_hours is not None], [2.5])
        self.assertEqual(
            LifecycleSystem.objects.get(pk=self.system_a.id).health_status, 'normal')

    def test_closed_fault_cannot_add_progress(self):
        """已关闭/已作废的故障不能追加处理进展（终态保护）。"""
        fault = self.run_lifecycle(self.system_a)
        self.add_progress(fault.id, expect_error='不能追加处理进展')
        self.assertEqual(
            SystemFaultHandlingRecord.objects.filter(fault=fault).count(), 0)


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
        # 只有查看权限：不能新增/编辑/恢复结案/关闭/作废/导出
        viewer = make_user('flt_viewer', ['equipment_lifecycle.fault.view'],
                           tenant_id='tenant_a')
        client = make_client(viewer)
        self.assertEqual(client.post(f'{FAULT_URL}/', fault_payload(self.system_a),
                                     content_type='application/json').json().get('error'),
                         '权限拒绝')
        self.assertEqual(client.put(f'{FAULT_URL}/{fid}/', {},
                                    content_type='application/json').json().get('error'),
                         '权限拒绝')
        # start 接口已删除（404）；recover/close/cancel 独立校验权限
        self.assertEqual(
            client.post(f'{FAULT_URL}/{fid}/start/', {},
                        content_type='application/json').status_code, 404)
        for action in ('recover', 'close', 'cancel'):
            self.assertEqual(
                client.post(f'{FAULT_URL}/{fid}/{action}/', {},
                            content_type='application/json').json().get('error'),
                '权限拒绝', action)
        self.assertEqual(client.post(f'{FAULT_URL}/{fid}/handling-records/', {},
                                     content_type='application/json').json().get('error'),
                         '权限拒绝')
        self.assertEqual(client.get(f'{FAULT_URL}/export/').json().get('error'), '权限拒绝')
        # 状态未被无权限操作改变
        self.assertEqual(SystemFault.objects.get(pk=fid).status, 'handling')

    def test_recover_and_close_requires_both_perms(self):
        """合并操作须同时具备 recover 与 close 权限，缺一即后端拒绝。"""
        body = self.create_fault(fault_payload(self.system_a))
        fid = body['data']['id']
        payload = {
            'recovered_at': '2026-09-18 10:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '更换备件并验证恢复，业务验证正常',
        }
        # 只有 recover 权限：缺 close 权限，合并操作被后端独立拒绝
        only_recover = make_user(
            'flt_only_recover',
            ['equipment_lifecycle.fault.view', 'equipment_lifecycle.fault.recover'],
            tenant_id='tenant_a')
        resp = make_client(only_recover).post(
            f'{FAULT_URL}/{fid}/recover/', payload, content_type='application/json')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        # 只有 close 权限：缺 recover 权限，同样拒绝（@auth 层拦截）
        only_close = make_user(
            'flt_only_close',
            ['equipment_lifecycle.fault.view', 'equipment_lifecycle.fault.close'],
            tenant_id='tenant_a')
        resp = make_client(only_close).post(
            f'{FAULT_URL}/{fid}/recover/', payload, content_type='application/json')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        # 两种情况下状态均未改变、未写入恢复字段
        fault = SystemFault.objects.get(pk=fid)
        self.assertEqual(fault.status, 'handling')
        self.assertIsNone(fault.recovered_at)
        # 两权限齐备后同一载荷成功
        both = make_user(
            'flt_both_perms',
            ['equipment_lifecycle.fault.view', 'equipment_lifecycle.fault.recover',
             'equipment_lifecycle.fault.close'],
            tenant_id='tenant_a')
        resp = make_client(both).post(
            f'{FAULT_URL}/{fid}/recover/', payload, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(SystemFault.objects.get(pk=fid).status, 'closed')


class FaultBoundaryTest(FaultTestBase):
    """模块边界及系统编辑/删除联动保护。"""

    def test_old_fault_tables_absent_and_no_cross_module_links(self):
        """旧故障表不存在；device/upgrade 与新故障模型无任何外键关联。"""
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'tdyw_fault_records'")
            self.assertIsNone(cursor.fetchone())
            cursor.execute("SHOW TABLES LIKE 'tdyw_fault_parts'")
            self.assertIsNone(cursor.fetchone())
        # 新故障模型没有指向 upgrade 模型的反向关联
        related_apps = {
            rel.related_model._meta.app_label
            for rel in SystemFault._meta.related_objects
        } | {
            rel.related_model._meta.app_label
            for rel in SystemFaultHandlingRecord._meta.related_objects
        }
        self.assertFalse(related_apps & {'upgrade'}, related_apps)
        # upgrade 模型上没有新增的故障反向关系
        from apps.upgrade.models import UpgradeRecord
        reverse_names = {rel.get_accessor_name() for rel in UpgradeRecord._meta.related_objects}
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


class FaultRegistrarAndProgressRecorderTest(FaultTestBase):
    """故障登记人与进展记录人契约（2026-09 人员记录优化，手动输入姓名）。

    语义：两者均为手动输入的姓名文本，只表示"实际添加记录的人"，不代表
    负责整个故障或承担维修责任（处置负责人字段已删除，登记/确认均为手输姓名，
    能力不变）；姓名为文本快照、不关联 User——实际操作人可能没有系统账号
    （多人共用一个登录账号时，各条记录登记/记录实际操作人姓名）。
    登录账号仍通过审计字段（created_by / 进展.handler）独立留痕。
    """

    def test_registrar_name_saved_independent_of_created_by(self):
        """手动输入登记人姓名可保存（无需是系统用户），与 created_by 分字段。"""
        body = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at(),
            registrar_name='实际登记人张三'))
        self.assertFalse(body.get('error'), body)
        fault = SystemFault.objects.get(pk=body['data']['id'])
        # 登记人=手动输入姓名；created_by=登录账号；两者独立
        self.assertEqual(fault.registrar_name, '实际登记人张三')
        self.assertEqual(fault.created_by_id, self.admin.id)
        detail = body['data']
        self.assertEqual(detail['registrar_name'], '实际登记人张三')
        self.assertEqual(detail['created_by_name'], self.admin.username)
        # 姓名不要求存在于用户表
        self.assertFalse(User.objects.filter(username='实际登记人张三').exists())

    def test_registrar_name_required_on_manual_create(self):
        """手工新增必须显式提交登记人姓名（不默认当前登录用户）。"""
        before = SystemFault.objects.count()
        self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at(),
            registrar_name='  '),
            expect_error='故障登记人不能为空')
        self.assertEqual(SystemFault.objects.count(), before)

    def test_registrar_name_accepts_any_manual_text(self):
        """任意手动输入文本均接受（strip 后保存，限长 100）。"""
        raw_name = '  外部协助人员-李四（无系统账号）  '
        body = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at(),
            registrar_name=raw_name))
        self.assertFalse(body.get('error'), body)
        fault = SystemFault.objects.get(pk=body['data']['id'])
        self.assertEqual(fault.registrar_name, raw_name.strip())

    def test_list_detail_export_show_registrar_name(self):
        """列表、详情与 CSV 导出均显示故障登记人姓名。"""
        fid = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at(),
            registrar_name='实际登记人张三'))['data']['id']
        client = make_client(self.admin)
        row = client.get(f'{FAULT_URL}/').json()['data']['data'][0]
        self.assertEqual(row['registrar_name'], '实际登记人张三')
        detail = client.get(f'{FAULT_URL}/{fid}/').json()['data']
        self.assertEqual(detail['registrar_name'], '实际登记人张三')
        resp = client.get(f'{FAULT_URL}/export/')
        self.assertEqual(resp.status_code, 200)
        text = resp.content.decode('utf-8-sig')
        self.assertIn('故障登记人', text)
        self.assertIn('实际登记人张三', text)

    def test_progress_records_store_manual_recorder_name_per_record(self):
        """共用登录账号时不同人员可分别添加进展，每条进展保存实际记录人姓名。"""
        body = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at(),
            registrar_name='实际登记人张三'))
        fid = body['data']['id']
        client = make_client(self.admin)
        first = client.post(
            f'{FAULT_URL}/{fid}/handling-records/',
            {'content': '现场检查确认', 'progress_type': 'check',
             'recorder_name': '检查人王五'},
            content_type='application/json').json()
        self.assertFalse(first.get('error'), first)
        second = client.post(
            f'{FAULT_URL}/{fid}/handling-records/',
            {'content': '送厂家维修', 'progress_type': 'to_vendor',
             'recorder_name': '送修人赵六', 'result': '待厂家反馈'},
            content_type='application/json').json()
        self.assertFalse(second.get('error'), second)
        records = list(SystemFaultHandlingRecord.objects.filter(fault_id=fid).order_by('id'))
        # 每条进展保存各自的手动姓名；登录账号统一记录在 handler（审计）
        self.assertEqual(records[0].recorder_name, '检查人王五')
        self.assertEqual(records[1].recorder_name, '送修人赵六')
        self.assertEqual(records[0].handler_id, self.admin.id)
        self.assertEqual(records[1].handler_id, self.admin.id)
        # 时间线接口返回 recorder_name（历史回落 handler_name 由前端处理）
        rows = client.get(f'{FAULT_URL}/{fid}/handling-records/').json()['data']['data']
        names = {r['id']: r for r in rows}
        self.assertEqual(names[records[0].id]['recorder_name'], '检查人王五')
        self.assertEqual(names[records[1].id]['recorder_name'], '送修人赵六')

    def test_progress_recorder_name_required(self):
        """追加进展必须显式提交记录人姓名（不默认当前登录用户）。"""
        body = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at()))
        fid = body['data']['id']
        client = make_client(self.admin)
        resp = client.post(f'{FAULT_URL}/{fid}/handling-records/',
                           {'content': '持续观察', 'recorder_name': '  '},
                           content_type='application/json')
        self.assertIn('进展记录人不能为空', resp.json().get('error', ''))
        self.assertEqual(SystemFaultHandlingRecord.objects.count(), 0)

    def test_correction_updates_recorder_name_and_keeps_when_not_submitted(self):
        """更正可修改进展记录人姓名；未提交时保留原值（历史兼容）。"""
        body = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at()))
        fid = body['data']['id']
        client = make_client(self.admin)
        resp = client.post(f'{FAULT_URL}/{fid}/handling-records/',
                           {'content': '初步检查', 'progress_type': 'check',
                            'recorder_name': '记录人甲'},
                           content_type='application/json')
        rid = resp.json()['data']['id']
        # 显式提交新记录人姓名
        resp = client.put(f'{FAULT_URL}/{fid}/handling-records/{rid}/',
                          {'content': '初步检查（补记实际操作人）',
                           'recorder_name': '实际检查人王五',
                           'correction_reason': '登记实际检查人'},
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemFaultHandlingRecord.objects.get(pk=rid)
        self.assertEqual(record.recorder_name, '实际检查人王五')
        # 未提交记录人：保留原值
        resp = client.put(f'{FAULT_URL}/{fid}/handling-records/{rid}/',
                          {'content': '初步检查（修订）', 'correction_reason': '文字修订'},
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record.refresh_from_db()
        self.assertEqual(record.recorder_name, '实际检查人王五')

    def test_progress_recorder_name_history_fallback(self):
        """历史进展无 recorder_name（空串）时正常查看更正，展示回落 handler 用户名。"""
        body = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at()))
        fid = body['data']['id']
        record = SystemFaultHandlingRecord.objects.create(
            tenant_id='tenant_a',
            fault_id=fid,
            handled_at=datetime(2026, 1, 5, 9, 0),
            handler=self.admin,
            content='历史进展记录（无记录人姓名字段）',
        )
        client = make_client(self.admin)
        rows = client.get(f'{FAULT_URL}/{fid}/handling-records/').json()['data']['data']
        target = [r for r in rows if r['id'] == record.id][0]
        self.assertEqual(target['recorder_name'], '')
        self.assertEqual(target['handler_name'], self.admin.username)
        # 更正历史记录（不提交记录人）仍成功且姓名保持为空
        resp = client.put(f'{FAULT_URL}/{fid}/handling-records/{record.id}/',
                          {'content': '历史进展（修订）', 'correction_reason': '文字修订'},
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record.refresh_from_db()
        self.assertEqual(record.recorder_name, '')

    def test_history_fault_without_registrar_view_edit_export(self):
        """历史故障（登记人为空）可查看、编辑、导出，编辑不补写登记人。"""
        fault = SystemFault.objects.create(
            tenant_id='tenant_a',
            fault_no='GZ20260101-0001',
            system=self.system_a,
            impact_status='degraded',
            affects_system_operation=True,
            system_code=self.system_a.system_code,
            system_name=self.system_a.name,
            system_location=self.system_a.install_location,
            occurred_at=datetime(2026, 1, 1, 8, 0),
            phenomenon='历史遗留故障（无登记人）',
            created_by=self.admin,
        )
        client = make_client(self.admin)
        detail = client.get(f'{FAULT_URL}/{fault.id}/').json()['data']
        self.assertEqual(detail['registrar_name'], '')
        # 编辑（不提交登记人）仍然成功且登记人保持为空
        resp = client.put(f'{FAULT_URL}/{fault.id}/', {
            'system': self.system_a.id,
            'affects_system_operation': True,
            'impact_status': 'degraded',
            'occurred_at': '2026-01-01 08:00',
            'phenomenon': '历史遗留故障（编辑补充）',
        }, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault.refresh_from_db()
        self.assertEqual(fault.registrar_name, '')
        # 导出：登记人列为空串，不报错
        resp = client.get(f'{FAULT_URL}/export/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('历史遗留故障（编辑补充）', resp.content.decode('utf-8-sig'))

    def test_unfixed_fault_with_progress_not_auto_recovered(self):
        """暂未修复场景：追加"持续观察"进展后故障保持处置中，不被自动恢复/关闭。"""
        body = self.create_fault(fault_payload(
            self.system_a, impact_status='fault',
            occurred_at=self.next_occurred_at()))
        fid = body['data']['id']
        client = make_client(self.admin)
        resp = client.post(f'{FAULT_URL}/{fid}/handling-records/',
                           {'content': '主板返修中，暂未修复，下一步等待厂家寄回',
                            'progress_type': 'watch', 'result': '暂未修复',
                            'recorder_name': '值班跟踪人'},
                           content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault = SystemFault.objects.get(pk=fid)
        self.assertEqual(fault.status, 'handling')
        self.assertIsNone(fault.recovered_at)
        self.assertEqual(fault.recovered_by_name, '')
        self.assertNotEqual(fault.status, SystemFault.STATUS_CLOSED)

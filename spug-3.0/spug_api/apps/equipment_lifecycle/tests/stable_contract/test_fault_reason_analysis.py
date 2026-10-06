# -*- coding: utf-8 -*-
"""原因分析流程优化（2026-10）稳定契约测试。

覆盖行为契约（全部走真实 HTTP 路径 + 隔离测试数据库，验证数据库状态与
真实副作用）：
- 新增故障支持初步原因分析（reason_analysis 非必填，不填写可正常创建，
  新建成功即处置中）；
- 原因分析专用更新端点 PUT faults/{id}/reason-analysis/：只提交原因分析
  字段即可保存（fault.edit 权限 + 审计留痕 + 状态校验），"原因未明"必须
  填写未明说明，允许清空误录内容；
- 确认恢复并结案接收最终原因分析：可修改、可选"原因未明"（后端独立校验
  未明必填说明）、未提交时保留原值（旧客户端兼容）；
- 处置类型字段已删除（2026-10-05）：排查过程作为处置措施文本记录，旧参数出现即拒绝；
- 历史数据兼容：reason_unknown 缺省 False，历史无原因分析故障正常查看。

原因分析是单一字段 reason_analysis：新增=初步原因分析、处置中=初步判断、
结案=最终原因；reason_unknown 只是不强迫用户填写虚假原因的标记。
"""
import json
from datetime import datetime, timedelta

from django.test import TestCase

from apps.equipment_lifecycle.models import SystemFault, SystemFaultHandlingRecord
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
        'affects_system_operation': True,
        'impact_status': 'degraded',
        'occurred_at': '2026-09-18 08:30',
        'phenomenon': '主用链路频繁丢包',
        'registrar_name': '登记人甲',
    }
    payload.update(overrides)
    return payload


class ReasonAnalysisTestBase(TestCase):
    """公共夹具：两个租户、可用系统（与故障管理主套件同口径）。"""

    def setUp(self):
        self._occ_seq = 0
        self.admin = make_user('rsa_admin', ALL_SYSTEM_PERMS + ALL_FAULT_PERMS,
                               tenant_id='tenant_a')
        self.other_admin = make_user('rsa_admin_b', ALL_SYSTEM_PERMS + ALL_FAULT_PERMS,
                                     tenant_id='tenant_b')
        self.noperm_user = make_user('rsa_noperm', ALL_SYSTEM_PERMS,
                                     tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.system_a = make_system(self.admin, tenant_id='tenant_a',
                                    system_code='SYS-A1', name='烟台通信系统',
                                    install_location='机房A')

    def next_occurred_at(self):
        """生成错开的故障发生时间，避免触发创建幂等窗口。"""
        self._occ_seq += 1
        moment = datetime(2026, 9, 18, 8, 0) + timedelta(minutes=self._occ_seq)
        return moment.strftime('%Y-%m-%d %H:%M')

    def create_fault(self, payload, user=None):
        client = make_client(user or self.admin)
        resp = client.post(f'{FAULT_URL}/', payload, content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body

    def update_reason(self, fid, payload, user=None):
        client = make_client(user or self.admin)
        return client.put(f'{FAULT_URL}/{fid}/reason-analysis/', payload,
                          content_type='application/json')


class FaultCreateReasonAnalysisTest(ReasonAnalysisTestBase):
    """新增故障的初步原因分析契约。"""

    def test_create_with_preliminary_reason_saved(self):
        """新增填写初步原因分析随创建保存并出现在详情响应。"""
        body = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at(),
            reason_analysis='现场检查疑为光模块老化'))
        fault = SystemFault.objects.get(pk=body['data']['id'])
        self.assertEqual(fault.reason_analysis, '现场检查疑为光模块老化')
        self.assertEqual(fault.status, 'handling')
        self.assertFalse(fault.reason_unknown)
        self.assertEqual(body['data']['reason_analysis'], '现场检查疑为光模块老化')
        self.assertIn('reason_unknown', body['data'])

    def test_create_without_reason_allowed(self):
        """不填写原因分析可正常创建（非必填，原因未知不阻塞报障）。"""
        body = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at()))
        fault = SystemFault.objects.get(pk=body['data']['id'])
        self.assertEqual(fault.reason_analysis, '')
        self.assertFalse(fault.reason_unknown)
        self.assertEqual(fault.status, 'handling')


class FaultReasonAnalysisUpdateTest(ReasonAnalysisTestBase):
    """原因分析专用更新端点契约（详情页补充/修改弹窗出口）。"""

    def _create_handling_fault(self, **kw):
        body = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at(), **kw))
        return SystemFault.objects.get(pk=body['data']['id'])

    def test_update_reason_on_handling_fault(self):
        """处置中故障可直接补充/修改原因分析，只提交原因分析字段。"""
        fault = self._create_handling_fault()
        resp = self.update_reason(fault.id, {
            'reason_analysis': '经排查确认为光模块老化',
            'reason_unknown': False,
        })
        self.assertFalse(resp.json().get('error'), resp.content)
        fault.refresh_from_db()
        self.assertEqual(fault.reason_analysis, '经排查确认为光模块老化')
        self.assertFalse(fault.reason_unknown)
        # 响应为完整详情（含处置记录概览统计），供前端保存后直接刷新
        self.assertEqual(resp.json()['data']['reason_analysis'], '经排查确认为光模块老化')
        self.assertIn('handling_record_count', resp.json()['data'])
        # 更新人/更新时间留痕
        self.assertEqual(fault.updated_by_id, self.admin.id)

    def test_reason_update_writes_audit_with_before_after(self):
        """原因分析修改写入业务审计：变更前后值（含全文与未明标记）留痕。"""
        fault = self._create_handling_fault(reason_analysis='旧初步判断')
        before_count = AuditLog.objects.filter(
            tenant_id='tenant_a', target_type='el_system_fault',
            target_id=str(fault.id), action='update').count()
        resp = self.update_reason(fault.id, {
            'reason_analysis': '确认为光模块老化',
            'reason_unknown': False,
        })
        self.assertFalse(resp.json().get('error'), resp.content)
        audits = AuditLog.objects.filter(
            tenant_id='tenant_a', target_type='el_system_fault',
            target_id=str(fault.id), action='update')
        self.assertEqual(audits.count(), before_count + 1)
        detail = json.loads(audits.latest('id').detail)
        self.assertEqual(detail['before']['reason_analysis'], '旧初步判断')
        self.assertEqual(detail['after']['reason_analysis'], '确认为光模块老化')
        self.assertIn('reason_unknown', detail['before'])
        self.assertIn('reason_unknown', detail['after'])

    def test_unknown_reason_requires_explanation(self):
        """选择"原因未明"必须填写未明说明（不接受无说明的未明标记）。"""
        fault = self._create_handling_fault()
        resp = self.update_reason(fault.id, {'reason_analysis': '', 'reason_unknown': True})
        self.assertIn('原因未明', resp.json().get('error', ''))
        fault.refresh_from_db()
        self.assertFalse(fault.reason_unknown)
        self.assertEqual(fault.reason_analysis, '')

    def test_unknown_reason_with_explanation_saved(self):
        """原因未明 + 未明说明正常保存（说明存入 reason_analysis 单一字段）。"""
        fault = self._create_handling_fault()
        resp = self.update_reason(fault.id, {
            'reason_analysis': '多方排查未复现，暂无法定位',
            'reason_unknown': True,
        })
        self.assertFalse(resp.json().get('error'), resp.content)
        fault.refresh_from_db()
        self.assertTrue(fault.reason_unknown)
        self.assertEqual(fault.reason_analysis, '多方排查未复现，暂无法定位')

    def test_clear_reason_allowed(self):
        """提交空文本清空误录的原因（回到"尚未分析"状态）。"""
        fault = self._create_handling_fault(reason_analysis='误录内容')
        resp = self.update_reason(fault.id, {'reason_analysis': '', 'reason_unknown': False})
        self.assertFalse(resp.json().get('error'), resp.content)
        fault.refresh_from_db()
        self.assertEqual(fault.reason_analysis, '')
        self.assertFalse(fault.reason_unknown)

    def test_length_limit_enforced(self):
        """原因分析超长被截断到 2000 字（与模型字段限长一致）。"""
        fault = self._create_handling_fault()
        resp = self.update_reason(fault.id, {'reason_analysis': '长' * 3000})
        self.assertFalse(resp.json().get('error'), resp.content)
        fault.refresh_from_db()
        self.assertEqual(len(fault.reason_analysis), 2000)

    def test_closed_fault_cannot_update_reason(self):
        """已关闭故障原因分析只读（终态保护，最终原因不可再修改）。"""
        fault = self._create_handling_fault()
        client = make_client(self.admin)
        resp = client.post(f'{FAULT_URL}/{fault.id}/recover/', {
            'recovered_at': '2026-09-18 10:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '业务验证恢复，更换备件并验证恢复',
        }, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        resp = self.update_reason(fault.id, {'reason_analysis': '试图篡改最终原因'})
        self.assertIn('不能修改原因分析', resp.json().get('error', ''))
        fault.refresh_from_db()
        self.assertEqual(fault.status, 'closed')
        self.assertEqual(fault.reason_analysis, '')

    def test_cancelled_fault_cannot_update_reason(self):
        """已作废故障同样封闭原因分析修改。"""
        fault = self._create_handling_fault()
        client = make_client(self.admin)
        resp = client.post(f'{FAULT_URL}/{fault.id}/cancel/',
                           {'cancel_reason': '误报'}, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        resp = self.update_reason(fault.id, {'reason_analysis': '试图修改'})
        self.assertIn('不能修改原因分析', resp.json().get('error', ''))
        fault.refresh_from_db()
        self.assertEqual(fault.reason_analysis, '')

    def test_permission_required(self):
        """原因分析修改独立校验 fault.edit 权限（view/recover 权限不足即拒绝）。"""
        fault = self._create_handling_fault()
        resp = self.update_reason(fault.id, {'reason_analysis': 'x'},
                                  user=self.noperm_user)
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        recover_only = make_user(
            'rsa_recover_only',
            ['equipment_lifecycle.fault.view', 'equipment_lifecycle.fault.recover'],
            tenant_id='tenant_a')
        resp = self.update_reason(fault.id, {'reason_analysis': 'x'}, user=recover_only)
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        fault.refresh_from_db()
        self.assertEqual(fault.reason_analysis, '')

    def test_tenant_isolated(self):
        """其他租户不能修改本租户故障的原因分析。"""
        fault = self._create_handling_fault()
        resp = self.update_reason(fault.id, {'reason_analysis': '跨租户修改'},
                                  user=self.other_admin)
        self.assertEqual(resp.json().get('error'), '故障记录不存在')
        fault.refresh_from_db()
        self.assertEqual(fault.reason_analysis, '')


class FaultRecoverFinalReasonTest(ReasonAnalysisTestBase):
    """确认恢复并结案携带最终原因分析契约。"""

    def _create_handling_fault(self, **kw):
        body = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at(), **kw))
        return SystemFault.objects.get(pk=body['data']['id'])

    def _recover(self, fault, payload, user=None, expect_error=None):
        client = make_client(user or self.admin)
        resp = client.post(f'{FAULT_URL}/{fault.id}/recover/', payload,
                           content_type='application/json')
        body = resp.json()
        if expect_error is not None:
            self.assertIn(expect_error, body.get('error', ''), body)
        return body

    def test_recover_saves_final_reason(self):
        """结案提交的最终原因分析保存到故障记录，状态进入已关闭。"""
        fault = self._create_handling_fault(reason_analysis='初步判断：疑为光模块老化')
        body = self._recover(fault, {
            'recovered_at': '2026-09-18 10:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '业务验证恢复，更换备件并验证恢复',
            'reason_analysis': '确认为光模块老化，已更换并复测',
            'reason_unknown': False,
        })
        self.assertFalse(body.get('error'), body)
        fault.refresh_from_db()
        self.assertEqual(fault.status, 'closed')
        self.assertEqual(fault.reason_analysis, '确认为光模块老化，已更换并复测')
        self.assertFalse(fault.reason_unknown)
        # 详情响应同步返回最终原因与统一结案说明
        self.assertEqual(body['data']['reason_analysis'], '确认为光模块老化，已更换并复测')
        self.assertEqual(
            body['data']['recovery_close_note'], '业务验证恢复，更换备件并验证恢复')
        self.assertNotIn('recover_confirm', body['data'])
        self.assertNotIn('final_result', body['data'])

    def test_recover_unknown_reason_with_explanation(self):
        """结案选择"原因未明"+说明可正常结案（不强迫填写虚假原因）。"""
        fault = self._create_handling_fault()
        body = self._recover(fault, {
            'recovered_at': '2026-09-18 10:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '业务验证恢复，系统已恢复正常',
            'reason_analysis': '现象未再复现，多方排查无法定位',
            'reason_unknown': True,
        })
        self.assertFalse(body.get('error'), body)
        fault.refresh_from_db()
        self.assertEqual(fault.status, 'closed')
        self.assertTrue(fault.reason_unknown)
        self.assertEqual(fault.reason_analysis, '现象未再复现，多方排查无法定位')

    def test_recover_unknown_reason_requires_explanation(self):
        """结案勾选"原因未明"但未填写说明：后端独立校验拒绝且不结案。"""
        fault = self._create_handling_fault()
        self._recover(fault, {
            'recovered_at': '2026-09-18 10:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '业务验证恢复，系统已恢复正常',
            'reason_unknown': True,
        }, expect_error='原因未明')
        fault.refresh_from_db()
        self.assertEqual(fault.status, 'handling')
        self.assertFalse(fault.reason_unknown)

    def test_recover_without_reason_fields_keeps_existing(self):
        """旧客户端结案载荷不带原因字段时保留原值（向后兼容，不清空历史）。"""
        fault = self._create_handling_fault(reason_analysis='处置中的初步判断')
        body = self._recover(fault, {
            'recovered_at': '2026-09-18 10:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '业务验证恢复，更换备件并验证恢复',
        })
        self.assertFalse(body.get('error'), body)
        fault.refresh_from_db()
        self.assertEqual(fault.reason_analysis, '处置中的初步判断')
        self.assertFalse(fault.reason_unknown)

    def test_recover_can_modify_existing_reason(self):
        """结案弹窗回填的原因可修改后提交（默认回填、结案前可改）。"""
        fault = self._create_handling_fault(reason_analysis='初步判断：疑为链路问题')
        body = self._recover(fault, {
            'recovered_at': '2026-09-18 10:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '业务验证恢复，更换备件并验证恢复',
            'reason_analysis': '更正为传输链路闪断，已恢复',
        })
        self.assertFalse(body.get('error'), body)
        fault.refresh_from_db()
        self.assertEqual(fault.reason_analysis, '更正为传输链路闪断，已恢复')

    def test_recover_final_reason_change_audited(self):
        """结案修改最终原因进入审计（before 保留修改前原因）。"""
        fault = self._create_handling_fault(reason_analysis='初步判断：疑为链路问题')
        body = self._recover(fault, {
            'recovered_at': '2026-09-18 10:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '业务验证恢复，更换备件并验证恢复',
            'reason_analysis': '最终原因：光模块老化',
        })
        self.assertFalse(body.get('error'), body)
        audit = AuditLog.objects.filter(
            tenant_id='tenant_a', target_type='el_system_fault',
            target_id=str(fault.id), action='update').latest('id')
        detail = json.loads(audit.detail)
        self.assertEqual(detail['before']['reason_analysis'], '初步判断：疑为链路问题')
        self.assertEqual(detail['after']['reason_analysis'], '最终原因：光模块老化')
        self.assertEqual(detail['after']['status'], 'closed')
        # 审计前后值使用统一结案说明字段（before 为空、after 为提交内容）
        self.assertEqual(detail['before']['recovery_close_note'], '')
        self.assertEqual(
            detail['after']['recovery_close_note'], '业务验证恢复，更换备件并验证恢复')
        self.assertNotIn('recover_confirm', detail['after'])
        self.assertNotIn('final_result', detail['after'])


class FaultProgressTypeRetiredTest(ReasonAnalysisTestBase):
    """处置类型字段退役契约（2026-10-05）：排查过程直接作为处置措施记录。"""

    def test_fault_locate_param_rejected(self):
        """已删除的处置类型旧参数出现即拒绝且不落库。"""
        body = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at()))
        fid = body['data']['id']
        client = make_client(self.admin)
        resp = client.post(f'{FAULT_URL}/{fid}/handling-records/', {
            'content': '更换备件前后对比测试，定位为光模块老化',
            'progress_type': 'fault_locate',
            'recorder_name': '记录人甲',
        }, content_type='application/json')
        self.assertIn('处置记录已不再支持参数', resp.json().get('error', ''))
        self.assertEqual(
            SystemFaultHandlingRecord.objects.filter(fault_id=fid).count(), 0)

    def test_plain_progress_still_works_without_type(self):
        """不带处置类型的普通处置措施仍可入库，故障状态与健康影响不变。"""
        body = self.create_fault(fault_payload(
            self.system_a, impact_status='fault',
            occurred_at=self.next_occurred_at()))
        fid = body['data']['id']
        client = make_client(self.admin)
        resp = client.post(f'{FAULT_URL}/{fid}/handling-records/', {
            'content': '现场复测定位中',
            'recorder_name': '记录人甲',
        }, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemFaultHandlingRecord.objects.get(pk=resp.json()['data']['id'])
        self.assertEqual(record.content, '现场复测定位中')
        fault = SystemFault.objects.get(pk=fid)
        self.assertEqual(fault.status, 'handling')
        self.assertIsNone(fault.recovered_at)
        # 审计仍记录处置记录追加（既有机制无回归）
        self.assertTrue(AuditLog.objects.filter(
            tenant_id='tenant_a', target_type='el_system_fault',
            target_id=str(fid),
            detail__contains='add_handling_record').exists())


class FaultReasonCompatibilityTest(ReasonAnalysisTestBase):
    """历史数据兼容契约。"""

    def test_history_fault_without_reason_view_and_edit(self):
        """历史故障（无原因分析）详情正常返回，展示口径由前端判读为"尚未分析"。"""
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
            phenomenon='历史遗留故障（无原因分析）',
            created_by=self.admin,
        )
        detail = make_client(self.admin).get(f'{FAULT_URL}/{fault.id}/').json()['data']
        self.assertEqual(detail['reason_analysis'], '')
        self.assertFalse(detail['reason_unknown'])
        # 历史故障（处置中）仍可通过专用端点补充原因分析
        resp = self.update_reason(fault.id, {'reason_analysis': '补充的原因分析'})
        self.assertFalse(resp.json().get('error'), resp.content)
        fault.refresh_from_db()
        self.assertEqual(fault.reason_analysis, '补充的原因分析')

    def test_reason_fields_not_cleared_by_normal_edit(self):
        """普通编辑（未提交原因字段）不静默清空既有原因分析。"""
        body = self.create_fault(fault_payload(
            self.system_a, occurred_at=self.next_occurred_at(),
            reason_analysis='编辑前的原因分析'))
        fid = body['data']['id']
        client = make_client(self.admin)
        resp = client.put(f'{FAULT_URL}/{fid}/', {
            'system': self.system_a.id,
            'affects_system_operation': True,
            'impact_status': 'degraded',
            'occurred_at': '2026-09-18 09:00',
            'phenomenon': '现象描述更新',
        }, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault = SystemFault.objects.get(pk=fid)
        self.assertEqual(fault.reason_analysis, '编辑前的原因分析')

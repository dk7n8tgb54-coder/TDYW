# -*- coding: utf-8 -*-
"""运行处置记录——设备故障生命周期与系统健康状态契约测试（2026-10-11）。

覆盖真实行为契约（真实 HTTP + 隔离测试数据库 + 健康状态落库断言）：
1. 健康状态只受"设备故障 + 处置中 + 影响系统运行"的记录影响：
   创建/编辑影响程度/切换系统/认定/恢复结案/撤销时重算；
   一般记录与异常事件（含影响范围描述）一律不改变健康状态；
2. 确认恢复并结案：字段校验（恢复时间/确认人/结案说明/原因未明）、
   终态保护、双权限（recover 且 close）、健康重算；
3. 撤销登记：原因必填、终态保护、退出健康计算；
4. 原因分析专用更新：仅处置中可改、原因未明必须填说明；
5. 多故障并存时取最高影响，一张关闭不覆盖其他未恢复故障。
"""
import json

from django.test import TestCase

from apps.equipment_lifecycle.models import LifecycleSystem
from apps.equipment_lifecycle.operation_models import (
    SystemOperationProgress,
    SystemOperationRecord,
)
from apps.equipment_lifecycle.tests.base import (
    ALL_OPERATION_PERMS, P_OP_CANCEL, P_OP_CLOSE, P_OP_EDIT, P_OP_RECOVER,
    P_OP_VIEW, RECORDS_URL, make_client, make_record, make_system, make_user,
)


class HealthImpactTest(TestCase):
    """健康状态只受有效设备故障影响的契约。"""

    def setUp(self):
        self.user = make_user('health_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)

    def _create_fault(self, affects=True, impact='degraded', **overrides):
        self._seq = getattr(self, '_seq', 0) + 1
        payload = {
            'record_type': 'fault',
            'system': self.system.id,
            'occurred_at': '2026-10-11 08:00',
            'title': '设备故障-%d' % self._seq,
            'description': '故障描述-%d' % self._seq,
            'registrar_name': '张三',
            'affects_system_operation': affects,
            'impact_status': impact,
        }
        payload.update(overrides)
        res = self.client.post(RECORDS_URL + '/', payload,
                               content_type='application/json')
        data = res.json()
        self.assertFalse(data.get('error'), data)
        return SystemOperationRecord.objects.get(pk=data['data']['id'])

    def _health(self):
        self.system.refresh_from_db()
        return self.system.health_status

    def test_creating_affecting_fault_degrades_health(self):
        fault = self._create_fault(impact='degraded')
        self.assertEqual(self._health(), 'degraded')

    def test_impact_level_maps_to_health(self):
        self._create_fault(impact='fault')
        self.assertEqual(self._health(), 'fault')
        LifecycleSystem.objects.filter(pk=self.system.id).update(health_status='normal')
        self._create_fault(impact='interrupted')
        self.assertEqual(self._health(), 'interrupted')

    def test_component_fault_does_not_affect_health(self):
        self._create_fault(affects=False)
        self.assertEqual(self._health(), 'normal')

    def test_routine_and_abnormal_never_affect_health(self):
        for seq, record_type in enumerate(('routine', 'abnormal')):
            res = self.client.post(RECORDS_URL + '/', {
                'record_type': record_type,
                'system': self.system.id,
                'occurred_at': '2026-10-11 08:00',
                'title': '运行记录-%d' % seq,
                'description': '影响范围：全站（仅为描述文本）-%d' % seq,
                'registrar_name': '张三',
            }, content_type='application/json')
            self.assertFalse(res.json().get('error'), res.json())
        self.assertEqual(self._health(), 'normal')

    def test_recover_closes_and_restores_health(self):
        fault = self._create_fault(impact='degraded')
        self.assertEqual(self._health(), 'degraded')
        res = self.client.post(
            RECORDS_URL + '/%d/recover/' % fault.id,
            json.dumps({
                'recovered_at': '2026-10-11 12:00',
                'recovered_by_name': '赵六',
                'recovery_close_note': '更换电源模块，观察30分钟无异常',
            }), content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        fault.refresh_from_db()
        self.assertEqual(fault.status, 'closed')
        self.assertEqual(fault.recovered_by_name, '赵六')
        self.assertIsNotNone(fault.recovered_confirmed_at)
        self.assertEqual(self._health(), 'normal')

    def test_cancel_removes_health_impact(self):
        fault = self._create_fault(impact='interrupted')
        self.assertEqual(self._health(), 'interrupted')
        res = self.client.post(
            RECORDS_URL + '/%d/cancel/' % fault.id,
            json.dumps({'cancel_reason': '误报，重复登记'}),
            content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        fault.refresh_from_db()
        self.assertEqual(fault.status, 'cancelled')
        self.assertEqual(self._health(), 'normal')

    def test_edit_impact_recomputes_health(self):
        fault = self._create_fault(impact='degraded')
        self.assertEqual(self._health(), 'degraded')
        res = self.client.put(RECORDS_URL + '/%d/' % fault.id,
                              json.dumps({
                                  'system': self.system.id,
                                  'occurred_at': '2026-10-11 08:00',
                                  'title': '设备故障',
                                  'description': '故障描述',
                                  'affects_system_operation': True,
                                  'impact_status': 'interrupted',
                              }), content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        self.assertEqual(self._health(), 'interrupted')
        # 改为不影响运行后恢复正常
        res = self.client.put(RECORDS_URL + '/%d/' % fault.id,
                              json.dumps({
                                  'system': self.system.id,
                                  'occurred_at': '2026-10-11 08:00',
                                  'title': '设备故障',
                                  'description': '故障描述',
                                  'affects_system_operation': False,
                              }), content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        self.assertEqual(self._health(), 'normal')

    def test_edit_system_switch_recomputes_both_systems(self):
        other = make_system(self.user, system_code='SYS-B', name='系统B',
                            install_location='备用机房')
        fault = self._create_fault(impact='fault')
        self.assertEqual(self._health(), 'fault')
        res = self.client.put(RECORDS_URL + '/%d/' % fault.id,
                              json.dumps({
                                  'system': other.id,
                                  'occurred_at': '2026-10-11 08:00',
                                  'title': '设备故障',
                                  'description': '故障描述',
                                  'affects_system_operation': True,
                                  'impact_status': 'fault',
                              }), content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        self.system.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.system.health_status, 'normal')
        self.assertEqual(other.health_status, 'fault')

    def test_highest_impact_wins_and_close_keeps_other(self):
        degraded = self._create_fault(impact='degraded')
        interrupted = self._create_fault(impact='interrupted')
        self.assertEqual(self._health(), 'interrupted')
        # 关闭中断故障后，降级故障仍生效
        res = self.client.post(
            RECORDS_URL + '/%d/recover/' % interrupted.id,
            json.dumps({
                'recovered_at': '2026-10-11 12:00',
                'recovered_by_name': '赵六',
                'recovery_close_note': '恢复完成',
            }), content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        self.assertEqual(self._health(), 'degraded')
        degraded.refresh_from_db()
        self.assertEqual(degraded.status, 'handling')


class RecoverAndCloseValidationTest(TestCase):
    """确认恢复并结案字段校验与权限契约。"""

    def setUp(self):
        self.user = make_user('recover_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.fault = make_record(self.user, self.system, record_type='fault')

    def _recover(self, **overrides):
        payload = {
            'recovered_at': '2026-10-11 12:00',
            'recovered_by_name': '赵六',
            'recovery_close_note': '更换电源模块后恢复正常',
        }
        payload.update(overrides)
        for key, value in list(payload.items()):
            if value is None:
                payload.pop(key)
        return self.client.post(RECORDS_URL + '/%d/recover/' % self.fault.id,
                                json.dumps(payload), content_type='application/json')

    def test_recover_requires_recover_and_close_perms(self):
        user = make_user('recover_only', perms=[P_OP_VIEW, P_OP_RECOVER])
        client = make_client(user)
        res = client.post(RECORDS_URL + '/%d/recover/' % self.fault.id,
                          json.dumps({'recovered_at': '2026-10-11 12:00',
                                      'recovered_by_name': '赵六',
                                      'recovery_close_note': '说明'}),
                          content_type='application/json')
        self.assertIn('权限拒绝', res.json().get('error', ''))
        self.fault.refresh_from_db()
        self.assertEqual(self.fault.status, 'handling')

    def test_recover_missing_fields_rejected(self):
        for field in ('recovered_at', 'recovered_by_name', 'recovery_close_note'):
            self.fault.refresh_from_db()
            res = self._recover(**{field: None})
            self.assertTrue(res.json().get('error'), f'{field} 缺失应报错')
            self.fault.refresh_from_db()
            self.assertEqual(self.fault.status, 'handling')

    def test_blank_close_note_rejected(self):
        res = self._recover(recovery_close_note='   ')
        self.assertIn('结案说明', res.json().get('error', ''))

    def test_recovered_at_before_occurred_rejected(self):
        res = self._recover(recovered_at='2026-10-10 07:00')
        self.assertIn('不能早于', res.json().get('error', ''))

    def test_recovered_at_future_rejected(self):
        res = self._recover(recovered_at='2030-01-01 00:00')
        self.assertIn('不能晚于当前时间', res.json().get('error', ''))

    def test_final_reason_unknown_requires_note(self):
        # 未提交 reason_analysis（省略而非空串）：保留原值为空 + 未明 → 必填说明
        res = self._recover(reason_unknown=True, reason_analysis=None)
        self.assertIn('原因未明', res.json().get('error', ''))

    def test_final_reason_saved_on_close(self):
        res = self._recover(reason_analysis='电源模块老化', reason_unknown=False)
        self.assertFalse(res.json().get('error'), res.json())
        self.fault.refresh_from_db()
        self.assertEqual(self.fault.reason_analysis, '电源模块老化')
        self.assertFalse(self.fault.reason_unknown)

    def test_closed_is_terminal(self):
        self._recover()
        self.fault.refresh_from_db()
        self.assertEqual(self.fault.status, 'closed')
        res = self._recover()
        self.assertIn('处置中', res.json().get('error', ''))

    def test_retired_recover_params_rejected(self):
        res = self._recover(recover_confirm='旧字段')
        self.assertIn('不再支持参数', res.json().get('error', ''))


class CancelValidationTest(TestCase):
    """撤销登记契约（仅设备故障、原因必填、终态保护）。"""

    def setUp(self):
        self.user = make_user('cancel_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.fault = make_record(self.user, self.system, record_type='fault')

    def test_cancel_requires_reason(self):
        res = self.client.post(RECORDS_URL + '/%d/cancel/' % self.fault.id,
                               json.dumps({'cancel_reason': '  '}),
                               content_type='application/json')
        self.assertIn('撤销原因', res.json().get('error', ''))

    def test_cancel_records_reason_and_actor(self):
        res = self.client.post(RECORDS_URL + '/%d/cancel/' % self.fault.id,
                               json.dumps({'cancel_reason': '重复登记'}),
                               content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        self.fault.refresh_from_db()
        self.assertEqual(self.fault.status, 'cancelled')
        self.assertEqual(self.fault.cancel_reason, '重复登记')
        self.assertIsNotNone(self.fault.cancelled_at)
        self.assertIsNotNone(self.fault.cancelled_by_id)

    def test_cancelled_is_terminal(self):
        self.client.post(RECORDS_URL + '/%d/cancel/' % self.fault.id,
                         json.dumps({'cancel_reason': '重复登记'}),
                         content_type='application/json')
        res = self.client.post(RECORDS_URL + '/%d/cancel/' % self.fault.id,
                               json.dumps({'cancel_reason': '再次撤销'}),
                               content_type='application/json')
        self.assertIn('不能重复撤销', res.json().get('error', ''))

    def test_closed_fault_cannot_be_cancelled(self):
        SystemOperationRecord.objects.filter(pk=self.fault.id).update(status='closed')
        res = self.client.post(RECORDS_URL + '/%d/cancel/' % self.fault.id,
                               json.dumps({'cancel_reason': '撤销已关闭'}),
                               content_type='application/json')
        self.assertIn('已关闭', res.json().get('error', ''))

    def test_cancel_permission_required(self):
        user = make_user('no_cancel', perms=[P_OP_VIEW, P_OP_EDIT, P_OP_CLOSE,
                                             P_OP_RECOVER])
        client = make_client(user)
        res = client.post(RECORDS_URL + '/%d/cancel/' % self.fault.id,
                          json.dumps({'cancel_reason': 'x'}),
                          content_type='application/json')
        self.assertIn('权限拒绝', res.json().get('error', ''))

    def test_abnormal_record_cannot_be_cancelled(self):
        abnormal = make_record(self.user, self.system, record_type='abnormal')
        res = self.client.post(RECORDS_URL + '/%d/cancel/' % abnormal.id,
                               json.dumps({'cancel_reason': 'x'}),
                               content_type='application/json')
        self.assertIn('只有设备故障', res.json().get('error', ''))


class ReasonAnalysisTest(TestCase):
    """原因分析专用更新契约。"""

    def setUp(self):
        self.user = make_user('reason_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.fault = make_record(self.user, self.system, record_type='fault')

    def test_update_reason_analysis(self):
        res = self.client.put(RECORDS_URL + '/%d/reason-analysis/' % self.fault.id,
                              json.dumps({'reason_analysis': '天馈接头进水'}),
                              content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        self.fault.refresh_from_db()
        self.assertEqual(self.fault.reason_analysis, '天馈接头进水')
        self.assertFalse(self.fault.reason_unknown)

    def test_unknown_reason_requires_note(self):
        res = self.client.put(RECORDS_URL + '/%d/reason-analysis/' % self.fault.id,
                              json.dumps({'reason_unknown': True,
                                          'reason_analysis': ''}),
                              content_type='application/json')
        self.assertIn('原因未明', res.json().get('error', ''))
        # 填写未明说明后可保存
        res = self.client.put(RECORDS_URL + '/%d/reason-analysis/' % self.fault.id,
                              json.dumps({'reason_unknown': True,
                                          'reason_analysis': '仍在排查中'}),
                              content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        self.fault.refresh_from_db()
        self.assertTrue(self.fault.reason_unknown)
        self.assertEqual(self.fault.reason_analysis, '仍在排查中')

    def test_closed_fault_reason_readonly(self):
        SystemOperationRecord.objects.filter(pk=self.fault.id).update(status='closed')
        res = self.client.put(RECORDS_URL + '/%d/reason-analysis/' % self.fault.id,
                              json.dumps({'reason_analysis': 'x'}),
                              content_type='application/json')
        self.assertIn('不能修改原因分析', res.json().get('error', ''))

    def test_abnormal_record_rejected(self):
        abnormal = make_record(self.user, self.system, record_type='abnormal')
        res = self.client.put(RECORDS_URL + '/%d/reason-analysis/' % abnormal.id,
                              json.dumps({'reason_analysis': 'x'}),
                              content_type='application/json')
        self.assertIn('只有设备故障', res.json().get('error', ''))


class FaultEditabilityTest(TestCase):
    """故障封闭状态契约：已关闭/已撤销不能追加进展或上传附件。"""

    def setUp(self):
        self.user = make_user('lock_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.fault = make_record(self.user, self.system, record_type='fault')
        self.progress = SystemOperationProgress.objects.create(
            tenant_id=self.fault.tenant_id, record=self.fault,
            handled_at='2026-10-11 09:00:00', handler=self.user,
            handler_name='张三', content='排查中')

    def test_closed_fault_rejects_progress(self):
        SystemOperationRecord.objects.filter(pk=self.fault.id).update(status='closed')
        res = self.client.post(RECORDS_URL + '/%d/progress/' % self.fault.id,
                               json.dumps({'content': '补充'}),
                               content_type='application/json')
        self.assertIn('不能追加进展', res.json().get('error', ''))

    def test_closed_fault_rejects_attachment_upload(self):
        SystemOperationRecord.objects.filter(pk=self.fault.id).update(status='closed')
        from django.core.files.uploadedfile import SimpleUploadedFile
        res = self.client.post(
            RECORDS_URL + '/%d/attachments/' % self.fault.id,
            {'file': SimpleUploadedFile('a.txt', b'content')})
        self.assertIn('不能上传附件', res.json().get('error', ''))

    def test_handling_fault_allows_progress(self):
        res = self.client.post(RECORDS_URL + '/%d/progress/' % self.fault.id,
                               json.dumps({'content': '更换电源模块',
                                           'work_hours': 1.5}),
                               content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        self.fault.refresh_from_db()
        self.assertEqual(self.fault.status, 'handling')
        self.assertEqual(self.fault.progress_records.count(), 2)

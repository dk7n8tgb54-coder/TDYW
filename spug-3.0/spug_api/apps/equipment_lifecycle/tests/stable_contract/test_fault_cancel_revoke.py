# -*- coding: utf-8 -*-
"""故障"撤销登记"改版（2026-10-03）稳定契约测试。

原"作废"能力保留（后端状态值 cancelled 不变，历史数据兼容），用户可见
文案统一为"已撤销"。覆盖行为契约（全部通过真实 HTTP 路径 + 隔离测试
数据库执行，验证数据库状态与真实副作用）：

1. 默认故障列表/系统页签/导出排除已撤销记录（后端排除，不依赖前端隐藏）；
2. 显式 status=cancelled 筛选/导出时返回已撤销记录；
3. 撤销操作：仅处置中可撤销、原因必填（空/纯空格拒绝）、不物理删除、
   撤销原因/撤销人/撤销时间落库；
4. 已关闭不能撤销；已撤销不能重复撤销、不能编辑、不能追加处理进展、
   不能确认恢复并结案（后端拒绝，前端隐藏按钮不作为边界）；
5. 撤销后业务审计日志与故障生命周期履历（SystemEvent cancel）均存在；
6. 撤销后系统健康状态回落（已撤销不参与健康状态计算）；
7. 已撤销详情响应携带撤销原因/撤销人/撤销时间（历史追溯）。
"""
import csv
import io
from datetime import datetime, timedelta

from django.test import TestCase

from apps.account.models import User
from apps.equipment_lifecycle import fault_services
from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemEvent,
    SystemFault,
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
        'affects_system_operation': True,
        'impact_status': 'degraded',
        'occurred_at': '2026-10-03 08:30',
        'phenomenon': '主用链路频繁丢包',
        'registrar_name': '登记人甲',
    }
    payload.update(overrides)
    return payload


class FaultCancelRevokeTestBase(TestCase):
    """公共夹具：单租户、可用系统、全故障权限账号。"""

    def setUp(self):
        self._occ_seq = 0
        self.admin = make_user('rvk_admin', ALL_SYSTEM_PERMS + ALL_FAULT_PERMS,
                               tenant_id='tenant_r')
        self.client = make_client(self.admin)
        self.system_a = make_system(self.admin, tenant_id='tenant_r',
                                    system_code='SYS-R1', name='撤销测试通信系统',
                                    install_location='机房R')

    def next_occurred_at(self):
        self._occ_seq += 1
        moment = datetime(2026, 10, 3, 8, 0) + timedelta(minutes=self._occ_seq)
        return moment.strftime('%Y-%m-%d %H:%M')

    def create_fault(self, **overrides):
        payload = fault_payload(self.system_a, occurred_at=self.next_occurred_at(),
                                **overrides)
        body = self.client.post(f'{FAULT_URL}/', payload,
                                content_type='application/json').json()
        self.assertFalse(body.get('error'), body)
        return SystemFault.objects.get(pk=body['data']['id'])

    def cancel(self, fault, reason='误报'):
        return self.client.post(f'{FAULT_URL}/{fault.id}/cancel/',
                                {'cancel_reason': reason},
                                content_type='application/json')

    def list_body(self, url):
        """列表响应解析（json_response 对 dict 载荷多包一层 data：取内层）。"""
        return self.client.get(url).json()['data']

    def refresh(self, system):
        system.refresh_from_db()
        return system.health_status


class FaultListDefaultExcludesCancelledTest(FaultCancelRevokeTestBase):
    """默认列表/系统页签/导出排除已撤销（后端口径，不依赖前端隐藏）。"""

    def setUp(self):
        super().setUp()
        self.f_handling = self.create_fault()
        closed = self.create_fault()
        resp = make_client(self.admin).post(f'{FAULT_URL}/{closed.id}/recover/', {
            'recovered_at': '2026-10-03 10:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '更换备件并验证恢复，业务验证正常',
        }, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.f_closed = SystemFault.objects.get(pk=closed.id)
        self.f_cancelled = self.create_fault()
        resp = self.cancel(self.f_cancelled, '重复登记')
        self.assertFalse(resp.json().get('error'), resp.content)

    def test_default_list_excludes_cancelled(self):
        """默认列表不返回已撤销记录（数据与分页总数均排除）。"""
        body = self.list_body(f'{FAULT_URL}/')
        ids = [row['id'] for row in body['data']]
        self.assertIn(self.f_handling.id, ids)
        self.assertIn(self.f_closed.id, ids)
        self.assertNotIn(self.f_cancelled.id, ids)
        self.assertEqual(body['total'], 2)

    def test_status_filter_cancelled_returns_only_cancelled(self):
        """显式 status=cancelled 时仅返回已撤销记录。"""
        body = self.list_body(f'{FAULT_URL}/?status=cancelled')
        ids = [row['id'] for row in body['data']]
        self.assertEqual(ids, [self.f_cancelled.id])
        self.assertEqual(body['total'], 1)
        # 状态文案为新口径"已撤销"
        self.assertEqual(body['data'][0]['status_text'], '已撤销')

    def test_status_filter_active_statuses(self):
        """显式指定处置中/已关闭筛选与默认口径一致。"""
        body = self.list_body(f'{FAULT_URL}/?status=handling')
        self.assertEqual([r['id'] for r in body['data']], [self.f_handling.id])
        body = self.list_body(f'{FAULT_URL}/?status=closed')
        self.assertEqual([r['id'] for r in body['data']], [self.f_closed.id])

    def test_invalid_status_filter_rejected(self):
        body = self.client.get(f'{FAULT_URL}/?status=void').json()
        self.assertIn('不合法', body.get('error', ''))

    def test_system_fault_tab_default_excludes_cancelled(self):
        """系统详情故障页签默认排除已撤销；显式筛选时返回。"""
        tab_url = f'/equipment-lifecycle/systems/{self.system_a.id}/faults/'
        body = self.list_body(tab_url)
        ids = [row['id'] for row in body['data']]
        self.assertNotIn(self.f_cancelled.id, ids)
        self.assertEqual(body['total'], 2)
        body = self.list_body(tab_url + '?status=cancelled')
        self.assertEqual([r['id'] for r in body['data']], [self.f_cancelled.id])

    def _export_rows(self, query=''):
        resp = self.client.get(f'{FAULT_URL}/export/{query}')
        self.assertEqual(resp.status_code, 200)
        text = resp.content.decode('utf-8-sig')
        return list(csv.reader(io.StringIO(text))), text

    def test_default_export_excludes_cancelled(self):
        """默认导出不含已撤销记录；显式 status=cancelled 仅导出已撤销。"""
        rows, text = self._export_rows()
        self.assertEqual(len(rows), 3)  # 表头 + 处置中 + 已关闭
        self.assertNotIn(self.f_cancelled.fault_no, text)
        rows, text = self._export_rows('?status=cancelled')
        self.assertEqual(len(rows), 2)  # 表头 + 已撤销
        self.assertIn(self.f_cancelled.fault_no, text)
        self.assertEqual(rows[1][4], '已撤销')
        # 无效状态筛选拒绝导出
        resp = self.client.get(f'{FAULT_URL}/export/?status=void')
        self.assertIn('不合法', resp.json().get('error', ''))


class FaultCancelOperationTest(FaultCancelRevokeTestBase):
    """撤销操作本身的行为契约。"""

    def test_handling_fault_can_be_cancelled_with_trace(self):
        """处置中故障可撤销：状态/原因/撤销人/撤销时间落库，不物理删除。"""
        fault = self.create_fault()
        before_count = SystemFault.objects.count()
        resp = self.cancel(fault, '系统与现象填写有误，需重新登记')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault.refresh_from_db()
        self.assertEqual(fault.status, SystemFault.STATUS_CANCELLED)
        self.assertEqual(fault.cancel_reason, '系统与现象填写有误，需重新登记')
        self.assertIsNotNone(fault.cancelled_at)
        self.assertEqual(fault.cancelled_by_id, self.admin.id)
        # 不物理删除
        self.assertEqual(SystemFault.objects.count(), before_count)
        # 详情响应携带撤销信息（历史追溯）
        detail = self.client.get(f'{FAULT_URL}/{fault.id}/').json()['data']
        self.assertEqual(detail['cancel_reason'], '系统与现象填写有误，需重新登记')
        self.assertIsNotNone(detail['cancelled_at'])
        self.assertEqual(detail['cancelled_by_name'], self.admin.username)

    def test_cancel_reason_required(self):
        """撤销原因不能为空或纯空格。"""
        fault = self.create_fault()
        resp = self.client.post(f'{FAULT_URL}/{fault.id}/cancel/', {},
                                content_type='application/json')
        self.assertTrue(resp.json().get('error'), resp.content)
        resp = self.cancel(fault, '   ')
        self.assertIn('撤销原因不能为空', resp.json().get('error', ''))
        fault.refresh_from_db()
        self.assertEqual(fault.status, SystemFault.STATUS_HANDLING)

    def test_closed_fault_cannot_be_cancelled(self):
        """已关闭故障不能撤销（真实故障已完成结案，状态不变）。"""
        fault = self.create_fault()
        resp = make_client(self.admin).post(f'{FAULT_URL}/{fault.id}/recover/', {
            'recovered_at': '2026-10-03 10:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '更换备件并验证恢复，业务验证正常',
        }, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        resp = self.cancel(fault)
        self.assertIn('已关闭的故障不能撤销', resp.json().get('error', ''))
        fault.refresh_from_db()
        self.assertEqual(fault.status, SystemFault.STATUS_CLOSED)

    def test_cancelled_fault_cannot_be_cancelled_again(self):
        """已撤销故障不能重复撤销。"""
        fault = self.create_fault()
        first = self.cancel(fault, '误报')
        self.assertFalse(first.json().get('error'), first.content)
        second = self.cancel(fault, '再次撤销')
        self.assertIn('不能重复撤销', second.json().get('error', ''))

    def test_cancelled_fault_rejects_write_operations(self):
        """已撤销详情只读：编辑/原因分析/追加进展/恢复结案均后端拒绝。"""
        fault = self.create_fault()
        resp = self.cancel(fault, '重复登记')
        self.assertFalse(resp.json().get('error'), resp.content)
        detail = self.client.get(f'{FAULT_URL}/{fault.id}/').json()['data']
        # 普通编辑拒绝
        payload = {k: detail[k] for k in ('system', 'occurred_at', 'phenomenon')}
        payload['phenomenon'] = '试图篡改已撤销故障'
        resp = self.client.put(f'{FAULT_URL}/{fault.id}/', payload,
                               content_type='application/json')
        self.assertIn('已撤销', resp.json().get('error', ''))
        # 原因分析修改拒绝
        resp = self.client.put(f'{FAULT_URL}/{fault.id}/reason-analysis/',
                               {'reason_analysis': '试图修改'},
                               content_type='application/json')
        self.assertIn('已撤销', resp.json().get('error', ''))
        # 追加处理进展拒绝（权限齐备仍被状态校验拦截）
        resp = self.client.post(
            f'{FAULT_URL}/{fault.id}/handling-records/',
            {'content': '试图追加进展', 'recorder_name': '记录员甲'},
            content_type='application/json')
        self.assertIn('已撤销', resp.json().get('error', ''))
        self.assertEqual(fault.handling_records.count(), 0)
        # 确认恢复并结案拒绝
        resp = self.client.post(f'{FAULT_URL}/{fault.id}/recover/', {
            'recovered_at': '2026-10-03 10:00',
            'recovered_by_name': '恢复确认人甲',
            'recovery_close_note': '更换备件并验证恢复，业务验证正常',
        }, content_type='application/json')
        self.assertIn('只有处置中的故障', resp.json().get('error', ''))
        fault.refresh_from_db()
        self.assertEqual(fault.status, SystemFault.STATUS_CANCELLED)
        self.assertEqual(fault.phenomenon, '主用链路频繁丢包')

    def test_cancel_writes_audit_and_lifecycle_history(self):
        """撤销后业务审计日志与故障生命周期履历均存在，原履历保留。"""
        fault = self.create_fault()
        create_events = SystemEvent.objects.filter(
            source_type='fault', source_id=fault.id, action='create').count()
        self.assertEqual(create_events, 1)
        resp = self.cancel(fault, '重复登记')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 业务审计（action=delete 为撤销登记的审计语义）
        self.assertTrue(AuditLog.objects.filter(
            tenant_id='tenant_r', target_type='el_system_fault',
            target_id=str(fault.id), action='delete').exists())
        # 履历：原 create 事件保留 + 追加 cancel 事件（原因落 detail）
        events = SystemEvent.objects.filter(source_type='fault', source_id=fault.id)
        self.assertEqual(
            events.filter(action='create').count(), 1)
        cancel_events = list(events.filter(action='cancel'))
        self.assertEqual(len(cancel_events), 1)
        self.assertEqual(
            cancel_events[0].get_detail().get('cancel_reason'), '重复登记')
        self.assertEqual(cancel_events[0].title, '故障撤销登记')
        self.assertEqual(cancel_events[0].created_by_id, self.admin.id)

    def test_cancelled_fault_excluded_from_health(self):
        """撤销后系统健康状态回落正常（已撤销不参与健康状态计算）。"""
        fault = self.create_fault()  # affects_system_operation=True, degraded
        self.assertEqual(self.refresh(self.system_a), LifecycleSystem.HEALTH_DEGRADED)
        resp = self.cancel(fault, '误报')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(self.refresh(self.system_a), LifecycleSystem.HEALTH_NORMAL)
        # 服务层只读计算口径一致（健康状态只看处置中故障）
        self.assertEqual(
            fault_services.compute_health_status('tenant_r', [self.system_a.id]),
            {self.system_a.id: LifecycleSystem.HEALTH_NORMAL})

    def test_cancel_requires_del_permission(self):
        """撤销保留原权限控制：仅具备 fault.del 权限的用户可执行。"""
        fault = self.create_fault()
        viewer = make_user('rvk_viewer', ALL_SYSTEM_PERMS +
                           ['equipment_lifecycle.fault.view'], tenant_id='tenant_r')
        resp = make_client(viewer).post(
            f'{FAULT_URL}/{fault.id}/cancel/', {'cancel_reason': '误报'},
            content_type='application/json')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        fault.refresh_from_db()
        self.assertEqual(fault.status, SystemFault.STATUS_HANDLING)
        self.assertFalse(AuditLog.objects.filter(
            target_type='el_system_fault', target_id=str(fault.id),
            action='delete').exists())

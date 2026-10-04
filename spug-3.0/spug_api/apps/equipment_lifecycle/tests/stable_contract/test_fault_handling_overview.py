# -*- coding: utf-8 -*-
"""故障"处理进展概览"统计契约测试（2026-10 流程简化配套）。

覆盖行为契约：
- 列表与详情接口返回后端聚合的只读统计字段
  handling_record_count / latest_handled_at / latest_handling_content；
- 数量只统计真实处理进展记录（SystemFaultHandlingRecord 行）：更正留痕
  （corrections JSON）与系统履历节点均不计入；已关闭/已作废故障保留
  历史数量；无进展返回 0；
- 列表聚合单次 IN 查询完成，查询数不随故障行数增长（无 N+1）；
- 多故障统计互不串数（不重复计数）；
- 统计遵守租户过滤与权限边界（跨租户不可见、无权限拒绝）。

全部通过真实 HTTP 路径 + 隔离测试数据库执行，验证数据库状态与真实副作用。
"""
from datetime import datetime

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.equipment_lifecycle.models import (
    SystemFault,
    SystemFaultHandlingRecord,
)

from apps.equipment_lifecycle.tests.base import (
    ALL_SYSTEM_PERMS,
    make_client, make_system, make_user,
)

FAULT_URL = '/equipment-lifecycle/faults'

FAULT_PERMS = [
    'equipment_lifecycle.fault.view', 'equipment_lifecycle.fault.add',
    'equipment_lifecycle.fault.edit', 'equipment_lifecycle.fault.handle',
    'equipment_lifecycle.fault.recover', 'equipment_lifecycle.fault.close',
    'equipment_lifecycle.fault.del',
]


def fault_payload(system_obj, **overrides):
    payload = {
        'system': system_obj.id,
        # 健康联动与本统计契约无关，默认构造"影响系统运行"的故障
        'affects_system_operation': True,
        'impact_status': 'degraded',
        'occurred_at': '2026-10-01 08:30',
        'phenomenon': '主用链路频繁丢包',
        'registrar_name': '登记人甲',
    }
    payload.update(overrides)
    return payload


class HandlingOverviewTestBase(TestCase):
    """公共夹具：两个租户、可用系统、全量故障权限。"""

    def setUp(self):
        self.admin = make_user('ovw_admin', ALL_SYSTEM_PERMS + FAULT_PERMS,
                               tenant_id='tenant_a')
        self.other_admin = make_user('ovw_admin_b', ALL_SYSTEM_PERMS + FAULT_PERMS,
                                     tenant_id='tenant_b')
        self.noperm_user = make_user('ovw_noperm', ALL_SYSTEM_PERMS,
                                     tenant_id='tenant_a')
        self.client = make_client(self.admin)
        self.system_a = make_system(self.admin, tenant_id='tenant_a',
                                    system_code='OVW-A1', name='概览通信系统',
                                    install_location='机房A')
        self.system_b = make_system(self.other_admin, tenant_id='tenant_b',
                                    system_code='OVW-B1', name='概览通信系统B',
                                    install_location='机房B')

    def create_fault(self, system, user=None, **overrides):
        """创建故障（新建即处置中），返回 SystemFault 实例。"""
        payload = fault_payload(system, **overrides)
        resp = make_client(user or self.admin).post(
            f'{FAULT_URL}/', payload, content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return SystemFault.objects.get(pk=body['data']['id'])

    def add_progress(self, fault, handled_at, content, user=None, **overrides):
        """追加一条处理进展，返回响应体。"""
        payload = {'handled_at': handled_at, 'content': content,
                   'recorder_name': '记录人甲'}
        payload.update(overrides)
        resp = make_client(user or self.admin).post(
            f'{FAULT_URL}/{fault.id}/handling-records/', payload,
            content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body

    def list_rows(self, user=None, query=''):
        """返回（本租户故障列表行, 按 id 索引的行字典）。"""
        resp = make_client(user or self.admin).get(f'{FAULT_URL}/{query}')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        rows = body['data']['data']
        return rows, {r['id']: r for r in rows}

    def get_detail(self, fault, user=None):
        resp = make_client(user or self.admin).get(f'{FAULT_URL}/{fault.id}/')
        return resp.json()['data']


class HandlingOverviewFieldTest(HandlingOverviewTestBase):
    """统计字段口径：数量、最新时间、最后记录内容。"""

    def test_create_fault_status_handling_and_zero_overview(self):
        """新建故障即处置中；列表与详情均返回 handling_record_count=0。"""
        fault = self.create_fault(self.system_a)
        self.assertEqual(fault.status, 'handling')
        rows, by_id = self.list_rows()
        self.assertEqual(by_id[fault.id]['handling_record_count'], 0)
        self.assertIsNone(by_id[fault.id]['latest_handled_at'])
        self.assertEqual(by_id[fault.id]['latest_handling_content'], '')
        detail = self.get_detail(fault)
        self.assertEqual(detail['handling_record_count'], 0)
        self.assertIsNone(detail['latest_handled_at'])
        self.assertEqual(detail['latest_handling_content'], '')

    def test_two_progress_records_counted_in_list_and_detail(self):
        """新增两条进展后列表与详情都返回数量 2 与最新一条的时间/内容。"""
        fault = self.create_fault(self.system_a)
        self.add_progress(fault, '2026-10-01 09:00', '现场检查，确认链路异常')
        self.add_progress(fault, '2026-10-01 09:30', '更换备件后完成业务验证')
        rows, by_id = self.list_rows()
        self.assertEqual(by_id[fault.id]['handling_record_count'], 2)
        # latest_handled_at 经 DateTimeEncoder 序列化为 YYYY-MM-DD HH:MM:SS 文本
        self.assertEqual(by_id[fault.id]['latest_handled_at'], '2026-10-01 09:30:00')
        self.assertEqual(by_id[fault.id]['latest_handling_content'], '更换备件后完成业务验证')
        detail = self.get_detail(fault)
        self.assertEqual(detail['handling_record_count'], 2)
        self.assertEqual(detail['latest_handled_at'], '2026-10-01 09:30:00')
        self.assertEqual(detail['latest_handling_content'], '更换备件后完成业务验证')

    def test_same_handled_at_takes_latest_created_record(self):
        """进展时间并列时取后创建（id 更大）的一条作为最后记录。"""
        fault = self.create_fault(self.system_a)
        self.add_progress(fault, '2026-10-01 09:00', '先登记的观察记录')
        self.add_progress(fault, '2026-10-01 09:00', '后登记的补充结论')
        _, by_id = self.list_rows()
        self.assertEqual(by_id[fault.id]['handling_record_count'], 2)
        self.assertEqual(by_id[fault.id]['latest_handling_content'], '后登记的补充结论')

    def test_correction_keeps_count_and_updates_latest_content(self):
        """更正进展内容不增加数量，"最后记录"同步为更正后的内容。"""
        fault = self.create_fault(self.system_a)
        self.add_progress(fault, '2026-10-01 09:00', '初步检查（笔误）')
        record = SystemFaultHandlingRecord.objects.filter(fault=fault).first()
        resp = make_client(self.admin).put(
            f'{FAULT_URL}/{fault.id}/handling-records/{record.id}/',
            {'content': '初步检查（已更正）', 'correction_reason': '笔误更正'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 更正留痕保存在 corrections JSON 内，不产生新的进展行
        self.assertEqual(SystemFaultHandlingRecord.objects.filter(fault=fault).count(), 1)
        rows, by_id = self.list_rows()
        self.assertEqual(by_id[fault.id]['handling_record_count'], 1)
        self.assertEqual(by_id[fault.id]['latest_handling_content'], '初步检查（已更正）')
        detail = self.get_detail(fault)
        self.assertEqual(detail['handling_record_count'], 1)
        self.assertEqual(detail['latest_handling_content'], '初步检查（已更正）')

    def test_closed_and_cancelled_faults_keep_history_counts(self):
        """已关闭/已撤销故障仍保留历史处理进展数量（已撤销经显式筛选查询）。
        2026-10-03 撤销登记改版：默认列表只含有效故障，已撤销记录退出主列表，
        详情与显式 status=cancelled 筛选仍返回历史统计。"""
        closed = self.create_fault(self.system_a, occurred_at='2026-10-01 08:00')
        self.add_progress(closed, '2026-10-01 09:00', '检查确认')
        self.add_progress(closed, '2026-10-01 09:20', '更换备件并验证')
        resp = make_client(self.admin).post(
            f'{FAULT_URL}/{closed.id}/recover/', {
                'recovered_at': '2026-10-01 10:00',
                'recovered_by_name': '确认人甲',
                'recovery_close_note': '业务验证恢复，更换备件并复测通过',
            }, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(SystemFault.objects.get(pk=closed.id).status, 'closed')

        cancelled = self.create_fault(self.system_a, occurred_at='2026-10-01 11:00')
        self.add_progress(cancelled, '2026-10-01 11:30', '重复登记前的检查')
        resp = make_client(self.admin).post(
            f'{FAULT_URL}/{cancelled.id}/cancel/', {'cancel_reason': '重复登记'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)

        # 默认列表只含有效故障：已关闭保留历史统计，已撤销不再出现
        rows, by_id = self.list_rows()
        self.assertEqual(by_id[closed.id]['status'], 'closed')
        self.assertEqual(by_id[closed.id]['handling_record_count'], 2)
        self.assertEqual(by_id[closed.id]['latest_handling_content'], '更换备件并验证')
        self.assertNotIn(cancelled.id, [r['id'] for r in rows])
        # 显式筛选已撤销：历史统计完整保留
        _, cancelled_by_id = self.list_rows(query='?status=cancelled')
        self.assertEqual(cancelled_by_id[cancelled.id]['status'], 'cancelled')
        self.assertEqual(cancelled_by_id[cancelled.id]['handling_record_count'], 1)
        # 详情同样保留历史数量
        self.assertEqual(self.get_detail(closed)['handling_record_count'], 2)
        self.assertEqual(self.get_detail(cancelled)['handling_record_count'], 1)

    def test_system_fault_list_returns_overview(self):
        """系统详情"故障记录"页签接口同样返回后端统计概览。"""
        fault = self.create_fault(self.system_a)
        self.add_progress(fault, '2026-10-01 09:00', '现场检查')
        resp = make_client(self.admin).get(
            f'/equipment-lifecycle/systems/{self.system_a.id}/faults/')
        rows = resp.json()['data']['data']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['handling_record_count'], 1)
        self.assertEqual(rows[0]['latest_handling_content'], '现场检查')


class HandlingOverviewAggregationTest(HandlingOverviewTestBase):
    """多故障统计准确性与查询效率（无 N+1）。"""

    def test_multiple_faults_counted_independently(self):
        """多张故障并存时各自行统计准确，不重复计数、不串数。"""
        fault_2 = self.create_fault(self.system_a, occurred_at='2026-10-01 08:00')
        self.add_progress(fault_2, '2026-10-01 09:00', '二号故障进展一')
        self.add_progress(fault_2, '2026-10-01 09:10', '二号故障进展二')
        fault_1 = self.create_fault(self.system_a, occurred_at='2026-10-01 08:05')
        self.add_progress(fault_1, '2026-10-01 09:05', '一号故障进展一')
        fault_0 = self.create_fault(self.system_a, occurred_at='2026-10-01 08:10')
        _, by_id = self.list_rows()
        self.assertEqual(by_id[fault_2.id]['handling_record_count'], 2)
        self.assertEqual(by_id[fault_2.id]['latest_handling_content'], '二号故障进展二')
        self.assertEqual(by_id[fault_1.id]['handling_record_count'], 1)
        self.assertEqual(by_id[fault_1.id]['latest_handling_content'], '一号故障进展一')
        self.assertEqual(by_id[fault_0.id]['handling_record_count'], 0)
        self.assertIsNone(by_id[fault_0.id]['latest_handled_at'])

    def test_list_overview_queries_do_not_scale_with_fault_count(self):
        """列表统计为聚合查询：页内故障行数增长不带来额外查询（无 N+1）。"""
        client = make_client(self.admin)
        # 全部用 9 月日期（不晚于当前时间，避免发生时间校验拒绝）
        for seq in range(1, 4):
            self.create_fault(self.system_a, occurred_at=f'2026-09-0{seq} 08:00',
                              phenomenon=f'故障现象-{seq}')
            fault = SystemFault.objects.order_by('-id').first()
            self.add_progress(fault, f'2026-09-0{seq} 09:00', f'进展-{seq}')
        with CaptureQueriesContext(connection) as ctx_small:
            resp = client.get(f'{FAULT_URL}/', {'page': 1, 'page_size': 20})
            self.assertFalse(resp.json().get('error'), resp.content)
        # 再造 5 张有进展的故障后，同页大小的列表查询数不得增长
        for seq in range(4, 9):
            self.create_fault(self.system_a, occurred_at=f'2026-09-{seq:02d} 08:00',
                              phenomenon=f'故障现象-{seq}')
            fault = SystemFault.objects.order_by('-id').first()
            self.add_progress(fault, f'2026-09-{seq:02d} 09:00', f'进展-{seq}')
        with CaptureQueriesContext(connection) as ctx_large:
            resp = client.get(f'{FAULT_URL}/', {'page': 1, 'page_size': 20})
            self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(len(ctx_large), len(ctx_small))
        _, by_id = self.list_rows()
        self.assertEqual(len(by_id), 8)
        for row in by_id.values():
            self.assertEqual(row['handling_record_count'], 1)


class HandlingOverviewBoundaryTest(HandlingOverviewTestBase):
    """统计的租户隔离与权限边界。"""

    def test_overview_respects_tenant_isolation(self):
        """跨租户故障与其统计数量互不可见。"""
        fault_b = self.create_fault(self.system_b, user=self.other_admin)
        self.add_progress(fault_b, '2026-10-01 09:00', '租户B 的进展', user=self.other_admin)
        rows, _ = self.list_rows()
        self.assertNotIn(fault_b.id, [r['id'] for r in rows])
        resp = make_client(self.admin).get(f'{FAULT_URL}/{fault_b.id}/')
        self.assertEqual(resp.json().get('error'), '故障记录不存在')

    def test_overview_requires_view_permission(self):
        """无 view 权限的用户既看不到列表也看不到统计。"""
        fault = self.create_fault(self.system_a)
        self.add_progress(fault, '2026-10-01 09:00', '现场检查')
        resp = make_client(self.noperm_user).get(f'{FAULT_URL}/')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        resp = make_client(self.noperm_user).get(f'{FAULT_URL}/{fault.id}/')
        self.assertEqual(resp.json().get('error'), '权限拒绝')

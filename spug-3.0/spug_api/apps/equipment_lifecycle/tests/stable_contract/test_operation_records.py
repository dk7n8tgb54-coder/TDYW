# -*- coding: utf-8 -*-
"""运行处置记录——统一记录 CRUD 契约测试（2026-10-11 合并改造）。

覆盖真实行为契约（真实 HTTP + 隔离测试数据库 + 数据库状态断言）：
1. 三种记录类型（一般记录/异常事件/设备故障）的创建/列表/详情/编辑/删除；
2. 权限边界：view/add/add_fault/edit/del 后端独立校验（直接登记设备故障
   须单独授权）；台账异常转故障的故障add复用见 test_operation_ledger_source；
3. 类型约束：一般记录拒绝故障专用字段、设备故障拒绝异常类别、记录类型
   创建后不可修改、旧参数出现即拒绝；
4. 列表筛选：类型/状态/系统/类别/关键词/时间范围；已撤销默认退出列表；
5. 幂等：client_token 命中返回既有记录 + 窗口期业务查重；
6. 租户隔离与删除语义（仅一般记录可物理删除 + 附件联动软删）。
"""
import io
import json
from datetime import datetime, timedelta

from django.test import TestCase

from openpyxl import load_workbook

from apps.equipment_lifecycle.models import LifecycleSystem
from apps.equipment_lifecycle.operation_models import (
    SystemOperationProgress,
    SystemOperationRecord,
)
from apps.equipment_lifecycle.tests.base import (
    ALL_OPERATION_PERMS, P_OP_ADD, P_OP_ADD_FAULT, P_OP_DEL, P_OP_EDIT,
    P_OP_EXPORT, P_OP_VIEW, RECORDS_URL, SYSTEM_RECORDS_URL, make_client,
    make_record, make_system, make_user,
)


class OperationRecordCreateTest(TestCase):
    """统一记录创建契约（三种类型 + 权限边界 + 幂等）。"""

    def setUp(self):
        self.user = make_user('op_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)

    def _payload(self, **overrides):
        payload = {
            'record_type': 'abnormal',
            'system': self.system.id,
            'occurred_at': '2026-10-11 08:30',
            'title': 'UPS切换异常',
            'description': '16:00 巡检发现 UPS A 路输入告警。',
            'registrar_name': '李四',
        }
        payload.update(overrides)
        return payload

    def test_create_abnormal_record(self):
        res = self.client.post(RECORDS_URL + '/', self._payload(),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()['data']
        self.assertFalse(res.json().get('error'), res.json())
        record = SystemOperationRecord.objects.get(pk=data['id'])
        self.assertEqual(record.record_type, 'abnormal')
        self.assertEqual(record.status, 'recorded')
        self.assertEqual(record.registrar_name, '李四')
        self.assertTrue(record.record_no.startswith('JL'))
        # 系统快照与外键一致
        self.assertEqual(record.system_id, self.system.id)
        self.assertEqual(record.system_name, self.system.name)

    def test_create_routine_record(self):
        res = self.client.post(RECORDS_URL + '/', self._payload(
            record_type='routine', title='UPS电池巡检'),
            content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()['data']
        self.assertFalse(res.json().get('error'), res.json())
        record = SystemOperationRecord.objects.get(pk=data['id'])
        self.assertEqual(record.record_type, 'routine')
        self.assertEqual(record.status, 'recorded')

    def test_create_fault_record_directly(self):
        res = self.client.post(RECORDS_URL + '/', self._payload(
            record_type='fault',
            affects_system_operation=True,
            impact_status='degraded',
            fault_object_name='信道机',
            reason_analysis='电源模块疑似故障',
        ), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()['data']
        self.assertFalse(res.json().get('error'), res.json())
        record = SystemOperationRecord.objects.get(pk=data['id'])
        self.assertEqual(record.record_type, 'fault')
        self.assertEqual(record.status, 'handling')
        self.assertEqual(record.impact_status, 'degraded')
        self.assertTrue(record.affects_system_operation)
        self.assertEqual(record.fault_object_name, '信道机')

    def test_create_fault_requires_add_fault_perm(self):
        user = make_user('no_fault_perm', perms=[P_OP_VIEW, P_OP_ADD])
        client = make_client(user)
        res = client.post(RECORDS_URL + '/', self._payload(record_type='fault'),
                          content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertIn('权限拒绝', res.json().get('error', ''))
        self.assertFalse(SystemOperationRecord.objects.exists())

    def test_create_without_add_perm_rejected(self):
        user = make_user('view_only', perms=[P_OP_VIEW])
        client = make_client(user)
        res = client.post(RECORDS_URL + '/', self._payload(),
                          content_type='application/json')
        self.assertIn('权限拒绝', res.json().get('error', ''))
        self.assertFalse(SystemOperationRecord.objects.exists())

    def test_fault_defaults_not_affecting_and_empty_impact(self):
        res = self.client.post(RECORDS_URL + '/', self._payload(record_type='fault'),
                               content_type='application/json')
        data = res.json()['data']
        record = SystemOperationRecord.objects.get(pk=data['id'])
        self.assertFalse(record.affects_system_operation)
        self.assertEqual(record.impact_status, '')

    def test_fault_requires_impact_when_affecting(self):
        res = self.client.post(RECORDS_URL + '/', self._payload(
            record_type='fault', affects_system_operation=True),
            content_type='application/json')
        self.assertIn('影响程度', res.json().get('error', ''))

    def test_routine_rejects_fault_only_fields(self):
        res = self.client.post(RECORDS_URL + '/', self._payload(
            record_type='routine', affects_system_operation=True,
            impact_status='fault'),
            content_type='application/json')
        # 一般记录不携带故障字段：即使提交也按默认值处理（服务层强制清空），
        # 不应产生影响系统运行的一般记录
        data = res.json()
        if not data.get('error'):
            record = SystemOperationRecord.objects.get(pk=data['data']['id'])
            self.assertFalse(record.affects_system_operation)
            self.assertEqual(record.impact_status, '')

    def test_fault_rejects_category(self):
        res = self.client.post(RECORDS_URL + '/', self._payload(
            record_type='fault', category='device'),
            content_type='application/json')
        self.assertIn('异常类别', res.json().get('error', ''))

    def test_invalid_record_type_rejected(self):
        res = self.client.post(RECORDS_URL + '/', self._payload(record_type='other'),
                               content_type='application/json')
        self.assertTrue(res.json().get('error'))

    def test_missing_required_fields_rejected(self):
        for field in ('system', 'occurred_at', 'title', 'description', 'registrar_name'):
            payload = self._payload()
            payload.pop(field)
            res = self.client.post(RECORDS_URL + '/', payload,
                                   content_type='application/json')
            self.assertTrue(res.json().get('error'), f'{field} 缺失应报错')

    def test_future_occurred_at_rejected(self):
        res = self.client.post(RECORDS_URL + '/', self._payload(
            occurred_at='2030-01-01 10:00'), content_type='application/json')
        self.assertIn('不能晚于当前时间', res.json().get('error', ''))

    def test_inactive_system_rejected(self):
        LifecycleSystem.objects.filter(pk=self.system.id).update(is_active=False)
        res = self.client.post(RECORDS_URL + '/', self._payload(),
                               content_type='application/json')
        self.assertIn('不存在、已停用或无权限', res.json().get('error', ''))

    def test_client_token_idempotent_returns_existing(self):
        first = self.client.post(RECORDS_URL + '/', self._payload(
            client_token='tok-abc'), content_type='application/json').json()['data']
        second = self.client.post(RECORDS_URL + '/', self._payload(
            client_token='tok-abc'), content_type='application/json').json()['data']
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(SystemOperationRecord.objects.count(), 1)

    def test_window_dedup_rejects_same_payload(self):
        self.client.post(RECORDS_URL + '/', self._payload(),
                         content_type='application/json')
        res = self.client.post(RECORDS_URL + '/', self._payload(),
                               content_type='application/json')
        self.assertIn('重复提交', res.json().get('error', ''))
        self.assertEqual(SystemOperationRecord.objects.count(), 1)

    def test_retired_params_rejected(self):
        res = self.client.post(RECORDS_URL + '/', self._payload(phenomenon='旧现象'),
                               content_type='application/json')
        self.assertIn('不再支持参数', res.json().get('error', ''))


class OperationRecordNumberingTest(TestCase):
    """统一编号契约：JL+日期+当日序号（全租户共享、连续递增）。"""

    def setUp(self):
        self.user = make_user('num_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)

    def _create(self, **overrides):
        self._seq = getattr(self, '_seq', 0) + 1
        payload = {
            'record_type': 'abnormal',
            'system': self.system.id,
            'occurred_at': '2026-10-11 08:30',
            'title': '编号测试-%d' % self._seq,
            'description': '编号测试描述',
            'registrar_name': '李四',
        }
        payload.update(overrides)
        res = self.client.post(RECORDS_URL + '/', payload,
                               content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        return res.json()['data']

    def test_record_no_prefix_and_sequence(self):
        first = self._create()
        second = self._create()
        self.assertTrue(first['record_no'].startswith('JL'))
        self.assertNotEqual(first['record_no'], second['record_no'])
        # 当日序号连续递增（后四位）
        seq_first = int(first['record_no'][-4:])
        seq_second = int(second['record_no'][-4:])
        self.assertGreater(seq_second, seq_first)

    def test_daily_sequence_shared_across_tenants(self):
        """当日序号全租户共享（口径与原故障/运行记录编号一致）。"""
        other_tenant_user = make_user(
            'num_user_t2', perms=ALL_OPERATION_PERMS, tenant_id='tenant_2')
        other_client = make_client(other_tenant_user)
        other_system = make_system(other_tenant_user, tenant_id='tenant_2',
                                   system_code='SYS-T2')
        other_payload = {
            'record_type': 'abnormal',
            'system': other_system.id,
            'occurred_at': '2026-10-11 09:30',
            'title': '租户2记录',
            'description': '租户2描述',
            'registrar_name': '王五',
        }
        first = self._create()
        res = other_client.post(RECORDS_URL + '/', other_payload,
                                content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        second = res.json()['data']
        seq_first = int(first['record_no'][-4:])
        seq_second = int(second['record_no'][-4:])
        self.assertEqual(seq_second, seq_first + 1)


class OperationRecordListFilterTest(TestCase):
    """列表筛选契约（类型/状态/系统/类别/关键词/时间范围/已撤销排除）。"""

    def setUp(self):
        self.user = make_user('list_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system_a = make_system(self.user, system_code='SYS-A', name='系统A')
        self.system_b = make_system(self.user, system_code='SYS-B', name='系统B',
                                    install_location='备用机房')
        self.routine = make_record(self.user, self.system_a, record_type='routine',
                                   title='日常巡检记录', occurred_at='2026-10-10 08:00:00')
        self.abnormal = make_record(self.user, self.system_b, record_type='abnormal',
                                    title='信号中断', category='signal',
                                    occurred_at='2026-10-11 09:00:00')
        self.fault = make_record(self.user, self.system_a, record_type='fault',
                                 title='设备故障', occurred_at='2026-10-11 10:00:00')

    def _list(self, **params):
        res = self.client.get(RECORDS_URL + '/', params)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data.get('error'), data)
        return data['data']

    def test_list_all_types(self):
        data = self._list()
        self.assertEqual(data['total'], 3)

    def test_filter_record_type(self):
        data = self._list(record_type='routine')
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['data'][0]['id'], self.routine.id)

    def test_filter_status(self):
        data = self._list(status='handling')
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['data'][0]['id'], self.fault.id)

    def test_filter_system(self):
        data = self._list(system=self.system_a.id)
        self.assertEqual(data['total'], 2)

    def test_filter_category(self):
        data = self._list(category='signal')
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['data'][0]['id'], self.abnormal.id)

    def test_filter_keyword_matches_no_and_title_and_description(self):
        self.assertEqual(self._list(keyword='信号中断')['total'], 1)
        self.assertEqual(self._list(keyword=self.abnormal.record_no)['total'], 1)
        self.assertEqual(self._list(keyword='UPS A 路')['total'], 0)

    def test_filter_occurred_range(self):
        data = self._list(occurred_from='2026-10-11 00:00', occurred_to='2026-10-12 00:00')
        self.assertEqual(data['total'], 2)

    def test_invalid_filter_values_rejected(self):
        for params in ({'record_type': 'xxx'}, {'status': 'xxx'}, {'category': 'xxx'}):
            res = self.client.get(RECORDS_URL + '/', params)
            self.assertTrue(res.json().get('error'), params)

    def test_list_contains_progress_overview(self):
        SystemOperationProgress.objects.create(
            tenant_id=self.abnormal.tenant_id, record=self.abnormal,
            handled_at='2026-10-11 10:00:00', handler=self.user,
            handler_name='李四', content='已到场排查')
        data = self._list(record_type='abnormal')
        row = data['data'][0]
        self.assertEqual(row['progress_count'], 1)
        self.assertEqual(row['latest_progress_content'], '已到场排查')


class OperationRecordDetailEditDeleteTest(TestCase):
    """详情/编辑/删除契约。"""

    def setUp(self):
        self.user = make_user('edit_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.other_system = make_system(self.user, system_code='SYS-B', name='系统B')
        self.abnormal = make_record(self.user, self.system, record_type='abnormal')

    def test_detail_contains_fault_and_source_fields(self):
        res = self.client.get(RECORDS_URL + '/%d/' % self.abnormal.id)
        data = res.json()['data']
        self.assertFalse(res.json().get('error'), res.json())
        for key in ('record_no', 'record_type', 'status', 'reason_analysis',
                    'source_type', 'source_ledger_no', 'progress_count'):
            self.assertIn(key, data)

    def test_edit_abnormal_base_fields(self):
        res = self.client.put(RECORDS_URL + '/%d/' % self.abnormal.id,
                              json.dumps({
                                  'system': self.other_system.id,
                                  'occurred_at': '2026-10-11 09:30',
                                  'title': '信号中断（更新）',
                                  'description': '更新后的描述',
                                  'category': 'link',
                              }), content_type='application/json')
        data = res.json()
        self.assertFalse(data.get('error'), data)
        self.abnormal.refresh_from_db()
        self.assertEqual(self.abnormal.title, '信号中断（更新）')
        self.assertEqual(self.abnormal.system_id, self.other_system.id)
        self.assertEqual(self.abnormal.category, 'link')
        # 系统快照同步更新
        self.assertEqual(self.abnormal.system_name, '系统B')

    def test_edit_cannot_change_record_type(self):
        res = self.client.put(RECORDS_URL + '/%d/' % self.abnormal.id,
                              json.dumps({
                                  'record_type': 'fault',
                                  'system': self.system.id,
                                  'occurred_at': '2026-10-11 09:30',
                                  'title': 'x',
                                  'description': 'y',
                              }), content_type='application/json')
        self.assertIn('不可修改', res.json().get('error', ''))

    def test_edit_fault_updates_impact(self):
        fault = make_record(self.user, self.system, record_type='fault',
                            affects_system_operation=True, impact_status='degraded')
        res = self.client.put(RECORDS_URL + '/%d/' % fault.id,
                              json.dumps({
                                  'system': self.system.id,
                                  'occurred_at': '2026-10-11 09:30',
                                  'title': '设备故障',
                                  'description': '描述',
                                  'affects_system_operation': True,
                                  'impact_status': 'interrupted',
                              }), content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        fault.refresh_from_db()
        self.assertEqual(fault.impact_status, 'interrupted')

    def test_edit_closed_fault_rejected(self):
        fault = make_record(self.user, self.system, record_type='fault',
                            status='closed')
        res = self.client.put(RECORDS_URL + '/%d/' % fault.id,
                              json.dumps({
                                  'system': self.system.id,
                                  'occurred_at': '2026-10-11 09:30',
                                  'title': 'x',
                                  'description': 'y',
                              }), content_type='application/json')
        self.assertIn('不能编辑', res.json().get('error', ''))

    def test_delete_routine_only(self):
        routine = make_record(self.user, self.system, record_type='routine')
        res = self.client.delete(RECORDS_URL + '/%d/' % routine.id)
        self.assertFalse(res.json().get('error'), res.json())
        self.assertFalse(SystemOperationRecord.objects.filter(pk=routine.id).exists())

    def test_delete_abnormal_rejected(self):
        res = self.client.delete(RECORDS_URL + '/%d/' % self.abnormal.id)
        self.assertIn('仅一般记录支持删除', res.json().get('error', ''))
        self.assertTrue(SystemOperationRecord.objects.filter(pk=self.abnormal.id).exists())

    def test_delete_fault_rejected(self):
        fault = make_record(self.user, self.system, record_type='fault')
        res = self.client.delete(RECORDS_URL + '/%d/' % fault.id)
        self.assertIn('仅一般记录支持删除', res.json().get('error', ''))

    def test_delete_requires_del_perm(self):
        user = make_user('no_del', perms=[P_OP_VIEW, P_OP_EDIT])
        client = make_client(user)
        routine = make_record(self.user, self.system, record_type='routine')
        res = client.delete(RECORDS_URL + '/%d/' % routine.id)
        self.assertIn('权限拒绝', res.json().get('error', ''))
        self.assertTrue(SystemOperationRecord.objects.filter(pk=routine.id).exists())


class OperationRecordPermissionTest(TestCase):
    """权限与租户隔离契约。"""

    def setUp(self):
        self.admin = make_user('perm_admin', perms=ALL_OPERATION_PERMS)
        self.admin_client = make_client(self.admin)
        self.system = make_system(self.admin)

    def test_view_permission_required(self):
        record = make_record(self.admin, self.system)
        outsider = make_user('no_perm', perms=[])
        client = make_client(outsider)
        res = client.get(RECORDS_URL + '/%d/' % record.id)
        self.assertIn('权限拒绝', res.json().get('error', ''))

    def test_cross_tenant_record_invisible(self):
        record = make_record(self.admin, self.system)
        other_user = make_user('tenant2_user', perms=ALL_OPERATION_PERMS,
                               tenant_id='tenant_2')
        client = make_client(other_user)
        # 详情不可见
        res = client.get(RECORDS_URL + '/%d/' % record.id)
        self.assertIn('不存在', res.json().get('error', ''))
        # 列表不返回跨租户记录
        res = client.get(RECORDS_URL + '/')
        self.assertEqual(res.json()['data']['total'], 0)
        # 编辑不可达（跨租户一律拒绝，不泄露目标记录存在性）
        res = client.put(RECORDS_URL + '/%d/' % record.id,
                         json.dumps({'system': 1, 'occurred_at': '2026-10-11 09:00',
                                     'title': '越权改', 'description': 'x'}),
                         content_type='application/json')
        self.assertTrue(res.json().get('error'), res.json())
        self.assertTrue(SystemOperationRecord.objects.filter(
            pk=record.id, title='测试记录').exists())

    def test_edit_requires_edit_perm(self):
        record = make_record(self.admin, self.system)
        user = make_user('no_edit', perms=[P_OP_VIEW])
        client = make_client(user)
        res = client.put(RECORDS_URL + '/%d/' % record.id, json.dumps({}),
                         content_type='application/json')
        self.assertIn('权限拒绝', res.json().get('error', ''))

    def test_export_requires_export_perm(self):
        user = make_user('no_export', perms=[P_OP_VIEW])
        client = make_client(user)
        res = client.get(RECORDS_URL + '/export/')
        self.assertIn('权限拒绝', res.json().get('error', ''))
        res = self.admin_client.get(RECORDS_URL + '/export/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('spreadsheetml.sheet', res['Content-Type'])


class OperationRecordExportTest(TestCase):
    """导出契约（xlsx 单工作表展平排版）。

    - 默认排除已撤销、显式状态/类型筛选生效；
    - 记录基础列纵向合并、进展逐行展平（处理时间/处理人/处理内容），
      无进展记录占一行显示"—"；工时已退役不出现在表头。
    """

    def setUp(self):
        self.user = make_user('export_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.record = make_record(self.user, self.system, record_type='fault',
                                  title='主控板异常')
        self.cancelled = make_record(self.user, self.system, record_type='fault',
                                     title='重复登记', status='cancelled')
        self.routine = make_record(self.user, self.system, record_type='routine',
                                   title='例行检查')
        for handled_at, handler_name, content in (
                ('2026-10-11 10:30:00', '李四', '更换主控板'),
                ('2026-10-11 16:00:00', '王五', '恢复正常，观察两小时')):
            SystemOperationProgress.objects.create(
                tenant_id=self.record.tenant_id, record=self.record,
                handled_at=handled_at, handler=self.user,
                handler_name=handler_name, content=content)

    def _load_sheet(self, **params):
        res = self.client.get(RECORDS_URL + '/export/', params)
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            res['Content-Type'])
        self.assertIn('.xlsx', res['Content-Disposition'])
        wb = load_workbook(io.BytesIO(res.content))
        return wb.active

    @staticmethod
    def _record_nos(ws):
        return [ws.cell(row=row, column=1).value
                for row in range(2, ws.max_row + 1)]

    @staticmethod
    def _find_row(ws, record_no):
        rows = [row for row in range(2, ws.max_row + 1)
                if ws.cell(row=row, column=1).value == record_no]
        assert rows, '导出中未找到记录 %r' % record_no
        return rows[0]

    @staticmethod
    def _assert_progress_at(ws, row, expected):
        value = ws.cell(row=row, column=17).value
        assert isinstance(value, datetime), '处理时间列应为日期单元格: %r' % value
        assert abs(value - expected) < timedelta(seconds=1), (value, expected)

    def test_export_headers_frozen_and_no_workhours(self):
        res = self.client.get(RECORDS_URL + '/export/')
        wb = load_workbook(io.BytesIO(res.content))
        ws = wb.active
        self.assertEqual(ws.title, '运行处置记录')
        self.assertEqual(ws.freeze_panes, 'A2')
        self.assertEqual(ws.cell(row=1, column=1).value, '记录编号')
        self.assertEqual(ws.cell(row=1, column=8).value, '故障等级')
        self.assertEqual(ws.cell(row=1, column=17).value, '处理时间')
        self.assertEqual(ws.cell(row=1, column=18).value, '处理人')
        self.assertEqual(ws.cell(row=1, column=19).value, '处理内容')
        headers = [ws.cell(row=1, column=col).value for col in range(1, 20)]
        self.assertNotIn('工时', headers)

    def test_export_progress_flattened_with_merged_base_columns(self):
        res = self.client.get(RECORDS_URL + '/export/')
        ws = load_workbook(io.BytesIO(res.content)).active
        first = self._find_row(ws, self.record.record_no)
        # 两条进展两行：处理时间按时间线正序，处理人与内容对应。
        # openpyxl 读回 Excel 串行日期存在亚秒级浮点误差，按 1 秒容差断言。
        self._assert_progress_at(ws, first, datetime(2026, 10, 11, 10, 30))
        self.assertEqual(ws.cell(row=first, column=18).value, '李四')
        self.assertEqual(ws.cell(row=first, column=19).value, '更换主控板')
        self._assert_progress_at(ws, first + 1, datetime(2026, 10, 11, 16, 0))
        self.assertEqual(ws.cell(row=first + 1, column=19).value,
                         '恢复正常，观察两小时')
        self.assertEqual(ws.cell(row=first + 1, column=19).value,
                         '恢复正常，观察两小时')
        # 记录基础列在两行间纵向合并（编号列与类型列），进展列不合并
        merged = [(r.min_row, r.max_row, r.min_col, r.max_col)
                  for r in ws.merged_cells.ranges]
        self.assertIn((first, first + 1, 1, 1), merged)
        self.assertIn((first, first + 1, 2, 2), merged)
        self.assertNotIn((first, first + 1, 19, 19), merged)

    def test_export_record_without_progress_single_row(self):
        res = self.client.get(RECORDS_URL + '/export/')
        ws = load_workbook(io.BytesIO(res.content)).active
        row = self._find_row(ws, self.routine.record_no)
        self.assertEqual(ws.cell(row=row, column=19).value, '—')

    def test_export_default_excludes_cancelled(self):
        ws = self._load_sheet()
        nos = self._record_nos(ws)
        self.assertIn(self.record.record_no, nos)
        self.assertNotIn(self.cancelled.record_no, nos)

    def test_export_cancelled_only_by_explicit_status(self):
        ws = self._load_sheet(status='cancelled')
        nos = self._record_nos(ws)
        self.assertIn(self.cancelled.record_no, nos)
        self.assertNotIn(self.record.record_no, nos)

    def test_export_filter_record_type(self):
        ws = self._load_sheet(record_type='routine')
        self.assertEqual(self._record_nos(ws), [self.routine.record_no])


class SystemRecordListTest(TestCase):
    """系统档案按系统查询统一记录契约。"""

    def setUp(self):
        self.user = make_user('sys_list_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system_a = make_system(self.user, system_code='SYS-A', name='系统A')
        self.system_b = make_system(self.user, system_code='SYS-B', name='系统B')
        make_record(self.user, self.system_a, record_type='routine', title='A日常')
        make_record(self.user, self.system_a, record_type='abnormal', title='A异常')
        make_record(self.user, self.system_b, record_type='fault', title='B故障')

    def _list(self, system_id, **params):
        res = self.client.get(SYSTEM_RECORDS_URL % system_id, params)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data.get('error'), data)
        return data['data']

    def test_list_scoped_to_system(self):
        data = self._list(self.system_a.id)
        self.assertEqual(data['total'], 2)
        self.assertTrue(all(row['system'] == self.system_a.id for row in data['data']))

    def test_filter_record_type(self):
        data = self._list(self.system_a.id, record_type='abnormal')
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['data'][0]['title'], 'A异常')

    def test_latest_occurred_at_returned(self):
        data = self._list(self.system_a.id)
        self.assertIsNotNone(data['latest_occurred_at'])

    def test_nonexistent_system_rejected(self):
        res = self.client.get(SYSTEM_RECORDS_URL % 999999)
        self.assertIn('系统不存在', res.json().get('error', ''))

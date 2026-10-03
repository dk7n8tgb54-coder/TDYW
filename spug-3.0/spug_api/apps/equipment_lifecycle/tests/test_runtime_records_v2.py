# -*- coding: utf-8 -*-
"""运行记录第二版（2026-10）真实行为测试：研判 / 转故障 / 重复问题 / 待办 / 统计。

覆盖任务要求的行为断言（HTTP 真实路径 + 数据库副作用，不使用源码字符串匹配）：
1. 运行记录可进入 待研判 → 无需跟进/跟进中/已处理/已关闭/已转故障；
2. 研判一次动作写入研判人/时间/说明并落审计；
3. 研判转正式故障须填研判说明，转换建立正式外键并带入结构化字段；
4. 同一记录只能成功转为一个正式故障（重复/并发不重复创建）；
5. 转故障后的处理进展进入故障模块，运行记录侧被拒绝；
6. 重复问题：相似记录查询 / 双向关联 / 取消关联 / 标记重复发生；
7. 关联必须租户隔离，跨租户记录不可见也不可关联；
8. 待办列表只显示跟进中记录（超期/跟进人/计划时间筛选）；
9. 统计遵守租户隔离，巡视/维护/配置变更/升级数据不进入运行记录统计；
10. 无权限用户不能研判、转故障、标记重要、关闭或关联。
"""
import threading
import uuid
from datetime import timedelta

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.equipment_lifecycle.models import (
    InspectionDutySheet,
    InspectionTemplate,
    LifecycleSystem,
    OperationLedger,
    SystemEvent,
    SystemFault,
    SystemRuntimeRecord,
    SystemRuntimeRecordDuplicateLink,
)
from apps.equipment_lifecycle.tests.base import (
    URL_PREFIX,
    make_client, make_system, make_user,
)
from apps.logs.models import AuditLog
from apps.upgrade.models import UpgradeRecord
from apps.utils.test_helpers import make_upgrade_no

P_VIEW = 'equipment_lifecycle.runtime_record.view'
P_ADD = 'equipment_lifecycle.runtime_record.add'
P_EDIT = 'equipment_lifecycle.runtime_record.edit'
P_TRIAGE = 'equipment_lifecycle.runtime_record.triage'
P_RESOLVE = 'equipment_lifecycle.runtime_record.resolve'
P_CLOSE = 'equipment_lifecycle.runtime_record.close'
P_CONVERT = 'equipment_lifecycle.runtime_record.convert_fault'
P_IMPORTANT = 'equipment_lifecycle.runtime_record.important'
P_LINK = 'equipment_lifecycle.runtime_record.link'

ALL_RUNTIME_PERMS = [P_VIEW, P_ADD, P_EDIT, P_TRIAGE, P_RESOLVE, P_CLOSE,
                     P_CONVERT, P_IMPORTANT, P_LINK]
FAULT_PERMS = ['equipment_lifecycle.fault.add', 'equipment_lifecycle.fault.handle',
               'equipment_lifecycle.fault.view']

RECORDS_URL = URL_PREFIX + '/runtime-records'


def make_record_payload(**overrides):
    payload = {
        'system': None,
        'occurred_at': '2026-10-01 08:30',
        'title': '主用链路丢包告警',
        'description': '值班发现主用链路丢包，十分钟后自行恢复',
        'registrar_name': '张三',
    }
    payload.update(overrides)
    return payload


class RuntimeRecordV2TestBase(TestCase):
    """公共夹具：全权限用户 + 受限用户 + 双租户（client 须在 setUp 创建，见 v1 注释）。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user(
            'rt2_admin_%s' % uuid.uuid4().hex[:8],
            ALL_RUNTIME_PERMS + FAULT_PERMS, tenant_id='tenant_a')
        cls.noperm = make_user(
            'rt2_noperm_%s' % uuid.uuid4().hex[:8], [], tenant_id='tenant_a')
        # 只有查看权限（无研判/关联/转故障权限）
        cls.viewer = make_user(
            'rt2_view_%s' % uuid.uuid4().hex[:8],
            [P_VIEW, P_ADD], tenant_id='tenant_a')
        # 只有研判权限（无转故障/重要权限）
        cls.triager = make_user(
            'rt2_tri_%s' % uuid.uuid4().hex[:8],
            [P_VIEW, P_TRIAGE], tenant_id='tenant_a')
        cls.other_admin = make_user(
            'rt2_other_%s' % uuid.uuid4().hex[:8],
            ALL_RUNTIME_PERMS + FAULT_PERMS, tenant_id='tenant_b')

    def setUp(self):
        self.client = make_client(self.admin)
        self.viewer_client = make_client(self.viewer)
        self.triager_client = make_client(self.triager)
        self.noperm_client = make_client(self.noperm)
        self.other_client = make_client(self.other_admin)
        self.system = make_system(self.admin, tenant_id='tenant_a',
                                  system_code='RT2-SYS-%s' % uuid.uuid4().hex[:6].upper())
        self.other_system = make_system(
            self.other_admin, tenant_id='tenant_b',
            system_code='RT2-SYS-B-%s' % uuid.uuid4().hex[:6].upper())

    def create_record(self, client=None, system=None, **overrides):
        client = client or self.client
        payload = make_record_payload(
            system=(system or self.system).id, **overrides)
        resp = client.post(RECORDS_URL + '/', payload,
                           content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    def assert_runtime_events(self, record_id, actions):
        events = SystemEvent.objects.filter(
            source_type='runtime_record', source_id=str(record_id))
        self.assertEqual(
            sorted(e.action for e in events), sorted(actions),
            [(e.action, e.title) for e in events])
        return events


class TriageStateFlowTests(RuntimeRecordV2TestBase):
    """1. 状态闭环：待研判 → 无需跟进/跟进中 → 已处理 → 已关闭。"""

    def test_pending_triage_then_triage_outcomes(self):
        data = self.create_record()
        record_id = data['id']
        # 已记录 → 待研判
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/pending-triage/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'pending_triage')
        # 重复提交研判 → 拒绝
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/pending-triage/', {},
            content_type='application/json')
        self.assertIn('待研判', resp.json().get('error', ''))
        # 待研判 → 跟进中（研判结论：需要跟进）
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'needs_follow_up': True, 'follow_up_name': '王值班',
             'planned_handle_at': '2026-10-03 09:00',
             'triage_note': '需要观察链路质量'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record.refresh_from_db()
        self.assertEqual(record.status, 'following_up')
        self.assertTrue(record.needs_follow_up)
        self.assertEqual(record.follow_up_name, '王值班')
        self.assertIsNotNone(record.planned_handle_at)
        self.assertEqual(record.triage_note, '需要观察链路质量')
        self.assertEqual(record.triaged_by_name, self.admin.nickname)
        self.assertIsNotNone(record.triaged_at)
        self.assertIsNotNone(record.triaged_by_id)
        # 跟进中 → 已处理 → 已关闭（resolved_at 记录首次处理时间）
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/resolve/',
            {'handling_result': '链路稳定'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record.refresh_from_db()
        self.assertEqual(record.status, 'resolved')
        first_resolved_at = record.resolved_at
        self.assertIsNotNone(first_resolved_at)
        resp = self.client.post(RECORDS_URL + f'/{record_id}/close/', {},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record.refresh_from_db()
        self.assertEqual(record.status, 'closed')

    def test_triage_no_follow_up_and_reopen(self):
        data = self.create_record()
        record_id = data['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'needs_follow_up': False, 'triage_note': '瞬时抖动，无需跟进'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'no_follow_up')
        self.assertFalse(record.needs_follow_up)
        # 无需跟进后改判：可重新跟进（研判后改判路径）
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/follow-up/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record.refresh_from_db()
        self.assertEqual(record.status, 'following_up')

    def test_triage_rejected_after_conclusion(self):
        data = self.create_record()
        record_id = data['id']
        self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'needs_follow_up': False}, content_type='application/json')
        # 已有结论（无需跟进）的记录不能再研判
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'needs_follow_up': True}, content_type='application/json')
        self.assertIn('研判', resp.json().get('error', ''))
        # 已关闭记录同样不能研判
        data2 = self.create_record(occurred_at='2026-10-01 07:30')
        self.client.post(
            RECORDS_URL + f'/{data2["id"]}/close/', {},
            content_type='application/json')
        resp = self.client.post(
            RECORDS_URL + f'/{data2["id"]}/triage/',
            {'needs_follow_up': True}, content_type='application/json')
        self.assertIn('研判', resp.json().get('error', ''))

    def test_triage_writes_audit_log(self):
        data = self.create_record()
        record_id = data['id']
        before = AuditLog.objects.filter(
            target_type='el_runtime_record', target_id=str(record_id)).count()
        self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'needs_follow_up': True, 'triage_note': '判定需要跟进'},
            content_type='application/json')
        after = AuditLog.objects.filter(
            target_type='el_runtime_record', target_id=str(record_id)).count()
        self.assertGreater(after, before)

    def test_triage_affect_update_generates_event_once(self):
        # 创建时未影响运行 → 研判升级为影响运行 → 补写一次 status_change 履历
        data = self.create_record()
        record_id = data['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'needs_follow_up': True, 'affects_system_operation': True,
             'impact_status': 'degraded'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.impact_status, 'degraded')
        self.assert_runtime_events(record_id, ['status_change'])
        # 创建时已影响运行的记录 → 只有 create 履历，研判不再重复生成
        data2 = self.create_record(
            affects_system_operation=True, impact_status='fault',
            occurred_at='2026-10-01 09:30')
        resp = self.client.post(
            RECORDS_URL + f'/{data2["id"]}/triage/',
            {'needs_follow_up': True, 'affects_system_operation': True,
             'impact_status': 'fault'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assert_runtime_events(data2['id'], ['create'])

    def test_triage_mark_important_once_with_reason(self):
        data = self.create_record()
        record_id = data['id']
        # 研判标记重要必须填原因
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'needs_follow_up': False, 'mark_important': True},
            content_type='application/json')
        self.assertIn('原因', resp.json().get('error', ''))
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'needs_follow_up': False, 'mark_important': True,
             'importance_reason': '造成业务中断，纳入重要履历'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.importance, 'important')
        self.assertEqual(record.importance_reason, '造成业务中断，纳入重要履历')
        self.assert_runtime_events(record_id, ['mark_important'])
        # 已重要记录再次研判标记重要 → 拒绝且不重复生成履历
        data2 = self.create_record(occurred_at='2026-10-01 10:00')
        self.client.post(
            RECORDS_URL + f'/{data2["id"]}/mark-important/',
            {'importance_reason': '首次标记'},
            content_type='application/json')
        resp = self.client.post(
            RECORDS_URL + f'/{data2["id"]}/triage/',
            {'needs_follow_up': False, 'mark_important': True,
             'importance_reason': '重复标记'},
            content_type='application/json')
        self.assertIn('已标记为重要', resp.json().get('error', ''))
        self.assert_runtime_events(data2['id'], ['mark_important'])


class TriageConvertFaultTests(RuntimeRecordV2TestBase):
    """3/4/5. 研判转正式故障：必填说明、正式外键、字段带入、进展归故障模块。"""

    def test_triage_convert_requires_note_and_exclusive_follow_up(self):
        data = self.create_record()
        record_id = data['id']
        # 缺研判说明 → 拒绝
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'convert_to_fault': True}, content_type='application/json')
        self.assertIn('研判说明', resp.json().get('error', ''))
        self.assertEqual(SystemFault.objects.count(), 0)
        # 转故障与需要跟进互斥
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'convert_to_fault': True, 'needs_follow_up': True,
             'triage_note': '说明'}, content_type='application/json')
        self.assertIn('不能同时标记需要跟进', resp.json().get('error', ''))
        self.assertEqual(SystemFault.objects.count(), 0)

    def test_triage_convert_creates_fault_with_fk_and_fields(self):
        data = self.create_record(
            object_name='DVOR 信标机', object_model='VR12',
            category='device', initial_reason='疑为功放模块老化')
        record_id = data['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'convert_to_fault': True, 'triage_note': '确认设备故障，需正式处置',
             'affects_system_operation': True, 'impact_status': 'fault'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault_no = resp.json()['data']['converted_fault_no']
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'converted_fault')
        self.assertFalse(record.needs_follow_up)
        fault = SystemFault.objects.get(fault_no=fault_no, tenant_id='tenant_a')
        # 正式外键双向关联 + 来源类型
        self.assertEqual(fault.source_runtime_record_id, record_id)
        self.assertEqual(fault.source_type, 'runtime_record')
        # 结构化字段带入故障（对象名称/型号/初步原因/影响程度）
        self.assertEqual(fault.fault_object_name, 'DVOR 信标机')
        self.assertEqual(fault.fault_object_model, 'VR12')
        self.assertEqual(fault.reason_analysis, '疑为功放模块老化')
        self.assertEqual(fault.impact_status, 'fault')
        # 故障详情暴露来源运行记录（双向追溯）
        resp = self.client.get(URL_PREFIX + f'/faults/{fault.id}/')
        self.assertFalse(resp.json().get('error'), resp.content)
        detail = resp.json()['data']
        self.assertEqual(detail['source_runtime_record'], record_id)
        self.assertEqual(detail['source_runtime_record_no'], record.record_no)
        # 重复研判转故障 → 状态机拒绝，不产生第二张有效故障
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'convert_to_fault': True, 'triage_note': '再次转换'},
            content_type='application/json')
        self.assertIn('研判', resp.json().get('error', ''))
        self.assertEqual(
            SystemFault.objects.filter(source_runtime_record_id=record_id).count(), 1)

    def test_progress_after_convert_belongs_to_fault(self):
        data = self.create_record()
        record_id = data['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'convert_to_fault': True, 'triage_note': '转正式故障处置'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault_id = SystemRuntimeRecord.objects.get(pk=record_id).generated_faults.first().id
        # 运行记录侧：不允许再追加普通处理进展
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/progress/',
            {'content': '记录侧进展', 'handler_name': '张三'},
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        # 故障模块：正式处理进展正常追加（唯一处置主线）
        resp = self.client.post(
            URL_PREFIX + f'/faults/{fault_id}/handling-records/',
            {'content': '现场检查功放模块，确认故障', 'recorder_name': '李四'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        resp = self.client.get(
            URL_PREFIX + f'/faults/{fault_id}/handling-records/')
        self.assertEqual(len(resp.json()['data']['data']), 1)
        self.assertIn('功放模块', resp.json()['data']['data'][0]['content'])


class DuplicateIssueTests(RuntimeRecordV2TestBase):
    """6/7. 重复问题：相似查询/双向关联/取消关联/标记重复发生/租户隔离。"""

    def test_link_unlink_and_duplicate_count(self):
        first = self.create_record(title='链路中断', occurred_at='2026-10-01 08:00')
        second = self.create_record(title='链路再次中断', occurred_at='2026-10-01 14:00')
        # 相似记录查询：同系统时间窗口内，排除自身
        resp = self.client.get(
            RECORDS_URL + f'/{first["id"]}/similar/', {'window_days': 30})
        self.assertFalse(resp.json().get('error'), resp.content)
        similar_ids = [r['id'] for r in resp.json()['data']['data']]
        self.assertIn(second['id'], similar_ids)
        self.assertNotIn(first['id'], similar_ids)
        # 建立关联
        resp = self.client.post(
            RECORDS_URL + f'/{first["id"]}/duplicate-links/',
            {'duplicate_id': second['id'], 'note': '同一链路问题重复发生'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        link_id = resp.json()['data']['id']
        # 双向可见：second 详情可见"被关联到"
        resp = self.client.get(RECORDS_URL + f'/{second["id"]}/duplicate-links/')
        rows = resp.json()['data']['data']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['direction'], 'inbound')
        self.assertEqual(rows[0]['other_record']['id'], first['id'])
        # 已关联记录不再出现在相似查询
        resp = self.client.get(RECORDS_URL + f'/{first["id"]}/similar/')
        self.assertNotIn(second['id'], [r['id'] for r in resp.json()['data']['data']])
        # 列表行携带双向合计的关联数量
        resp = self.client.get(RECORDS_URL + '/', {'keyword': '链路'})
        counts = {r['id']: r.get('duplicate_count')
                  for r in resp.json()['data']['data']}
        self.assertEqual(counts[first['id']], 1)
        self.assertEqual(counts[second['id']], 1)
        # 原始记录保留（关联不合并、不删改原始记录）
        self.assertTrue(
            SystemRuntimeRecord.objects.filter(pk=first['id'], title='链路中断').exists())
        self.assertTrue(
            SystemRuntimeRecord.objects.filter(pk=second['id']).exists())
        # 取消关联（对端也可解除）
        resp = self.client.delete(
            RECORDS_URL + f'/{second["id"]}/duplicate-links/{link_id}/',
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(SystemRuntimeRecordDuplicateLink.objects.count(), 0)

    def test_link_validations(self):
        first = self.create_record()
        # 自关联拒绝
        resp = self.client.post(
            RECORDS_URL + f'/{first["id"]}/duplicate-links/',
            {'duplicate_id': first['id']}, content_type='application/json')
        self.assertIn('自身', resp.json().get('error', ''))
        second = self.create_record(occurred_at='2026-10-01 09:00')
        # 重复关联（含反向）拒绝
        self.client.post(
            RECORDS_URL + f'/{first["id"]}/duplicate-links/',
            {'duplicate_id': second['id']}, content_type='application/json')
        resp = self.client.post(
            RECORDS_URL + f'/{second["id"]}/duplicate-links/',
            {'duplicate_id': first['id']}, content_type='application/json')
        self.assertIn('已存在关联', resp.json().get('error', ''))
        self.assertEqual(SystemRuntimeRecordDuplicateLink.objects.count(), 1)

    def test_cross_tenant_link_rejected(self):
        first = self.create_record()
        other_record = self.create_record(
            client=self.other_client, system=self.other_system)
        # 跨租户记录不可见（similar/详情），关联被拒绝
        resp = self.client.post(
            RECORDS_URL + f'/{first["id"]}/duplicate-links/',
            {'duplicate_id': other_record['id']}, content_type='application/json')
        self.assertIn('不存在或无权限', resp.json().get('error', ''))
        self.assertEqual(SystemRuntimeRecordDuplicateLink.objects.count(), 0)

    def test_mark_repeated_toggle_and_guard(self):
        data = self.create_record()
        record_id = data['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/mark-repeated/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertTrue(resp.json()['data']['is_repeated'])
        # 取消标记
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/mark-repeated/',
            {'is_repeated': False}, content_type='application/json')
        self.assertFalse(resp.json()['data']['is_repeated'])
        # 关联相似记录不自动置位（手动标记才生效）
        second = self.create_record(occurred_at='2026-10-01 10:00')
        self.client.post(
            RECORDS_URL + f'/{data["id"]}/duplicate-links/',
            {'duplicate_id': second['id']}, content_type='application/json')
        second_record = SystemRuntimeRecord.objects.get(pk=second['id'])
        self.assertFalse(second_record.is_repeated)
        # 已关闭记录不能修改重复标记
        self.client.post(RECORDS_URL + f'/{record_id}/close/', {},
                         content_type='application/json')
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/mark-repeated/', {},
            content_type='application/json')
        self.assertIn('已关闭或已转故障', resp.json().get('error', ''))

    def test_system_history_filters_and_summary(self):
        base = self.create_record(
            title='信标机告警', object_name='DVOR', category='device',
            occurred_at='2026-10-01 08:00')
        self.create_record(
            title='供电波动', category='power', occurred_at='2026-10-01 08:00')
        # 按异常类别筛选系统历史运行记录
        resp = self.client.get(
            URL_PREFIX + f'/systems/{self.system.id}/runtime-records/',
            {'category': 'device'})
        rows = resp.json()['data']['data']
        self.assertEqual([r['id'] for r in rows], [base['id']])
        self.assertTrue(resp.json()['data'].get('latest_occurred_at'))
        # 按对象名称关键词筛选
        resp = self.client.get(
            URL_PREFIX + f'/systems/{self.system.id}/runtime-records/',
            {'keyword': 'DVOR'})
        self.assertEqual(resp.json()['data']['total'], 1)


class TodoListTests(RuntimeRecordV2TestBase):
    """8. 待办列表只显示跟进中记录，支持超期/跟进人/计划时间筛选。"""

    def setUp(self):
        super().setUp()
        self.following = self.create_record(title='跟进中问题')
        self.client.post(
            RECORDS_URL + f'/{self.following["id"]}/triage/',
            {'needs_follow_up': True, 'follow_up_name': '王值班',
             'planned_handle_at': '2020-01-01 09:00'},
            content_type='application/json')
        self.resolved = self.create_record(
            title='已处理问题', occurred_at='2026-10-01 09:00')
        self.client.post(
            RECORDS_URL + f'/{self.resolved["id"]}/resolve/', {},
            content_type='application/json')
        self.closed = self.create_record(
            title='已关闭问题', occurred_at='2026-10-01 10:00')
        self.client.post(
            RECORDS_URL + f'/{self.closed["id"]}/close/', {},
            content_type='application/json')

    def test_todo_only_following_up(self):
        resp = self.client.get(RECORDS_URL + '/todo/')
        body = resp.json()['data']
        ids = [r['id'] for r in body['data']]
        self.assertIn(self.following['id'], ids)
        self.assertNotIn(self.resolved['id'], ids)
        self.assertNotIn(self.closed['id'], ids)
        # 已关闭/转故障的记录不会回到待办
        self.assertGreaterEqual(body['overdue_count'], 1)

    def test_todo_filters(self):
        resp = self.client.get(RECORDS_URL + '/todo/', {'overdue': 'yes'})
        self.assertIn(self.following['id'],
                      [r['id'] for r in resp.json()['data']['data']])
        resp = self.client.get(RECORDS_URL + '/todo/', {'follow_up_name': '王值班'})
        self.assertIn(self.following['id'],
                      [r['id'] for r in resp.json()['data']['data']])
        resp = self.client.get(RECORDS_URL + '/todo/', {'follow_up_name': '不存在的人'})
        self.assertEqual(resp.json()['data']['total'], 0)
        # 计划处理时间范围筛选（__gte/__lt）
        resp = self.client.get(RECORDS_URL + '/todo/', {
            'planned_from': '2019-01-01 00:00', 'planned_to': '2021-01-01 00:00'})
        self.assertIn(self.following['id'],
                      [r['id'] for r in resp.json()['data']['data']])
        resp = self.client.get(RECORDS_URL + '/todo/', {
            'planned_from': '2030-01-01 00:00', 'planned_to': '2031-01-01 00:00'})
        self.assertEqual(resp.json()['data']['total'], 0)

    def test_follow_up_updates_assignee_when_already_following(self):
        # 已跟进中记录携带跟进字段 → 仅更新跟进安排，不报"重复标记"
        resp = self.client.post(
            RECORDS_URL + f'/{self.following["id"]}/follow-up/',
            {'follow_up_name': '李值班', 'planned_handle_at': '2026-10-05 09:00'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=self.following['id'])
        self.assertEqual(record.follow_up_name, '李值班')
        self.assertEqual(record.status, 'following_up')
        # 无字段重复标记 → 维持第一版拒绝
        resp = self.client.post(
            RECORDS_URL + f'/{self.following["id"]}/follow-up/', {},
            content_type='application/json')
        self.assertIn('已处于跟进中', resp.json().get('error', ''))


class RuntimeStatisticsTests(RuntimeRecordV2TestBase):
    """9/15. 统计：租户隔离、只统计运行记录、时间范围 __gte/__lt。"""

    def test_statistics_counts_and_tenant_isolation(self):
        normal = self.create_record(title='普通情况')
        following = self.create_record(
            title='跟进情况', occurred_at='2026-10-01 09:00')
        self.client.post(
            RECORDS_URL + f'/{following["id"]}/triage/',
            {'needs_follow_up': True}, content_type='application/json')
        converted = self.create_record(
            title='转故障情况', occurred_at='2026-10-01 10:00')
        self.client.post(
            RECORDS_URL + f'/{converted["id"]}/convert-to-fault/', {},
            content_type='application/json')
        duplicated = self.create_record(
            title='重复问题', occurred_at='2026-10-01 11:00')
        self.client.post(
            RECORDS_URL + f'/{duplicated["id"]}/mark-repeated/', {},
            content_type='application/json')
        important = self.create_record(
            title='重要情况', occurred_at='2026-10-01 12:00')
        self.client.post(
            RECORDS_URL + f'/{important["id"]}/mark-important/',
            {'importance_reason': '业务中断'}, content_type='application/json')
        # 租户 B 的记录不计入租户 A 统计
        self.create_record(
            client=self.other_client, system=self.other_system,
            title='租户B记录')

        resp = self.client.get(RECORDS_URL + '/statistics/')
        self.assertFalse(resp.json().get('error'), resp.content)
        stats = resp.json()['data']
        totals = stats['totals']
        self.assertEqual(totals['total'], 5)
        self.assertEqual(totals['following_up'], 1)
        self.assertEqual(totals['converted_fault'], 1)
        self.assertEqual(totals['duplicated'], 1)
        self.assertEqual(totals['important'], 1)
        # 状态维度 / 系统维度
        self.assertEqual(stats['by_status'].get('following_up'), 1)
        system_rows = stats['by_system']
        self.assertEqual(len(system_rows), 1)
        self.assertEqual(system_rows[0]['system'], self.system.id)
        self.assertEqual(system_rows[0]['total'], 5)

    def test_statistics_excludes_other_business_data(self):
        """15. 巡视、维护、升级数据不进入运行记录统计。"""
        self.create_record(title='唯一的运行记录')
        # 周月维护台账
        OperationLedger.objects.create(
            tenant_id='tenant_a', ledger_no='EL-WM-TEST-0001',
            ledger_type='week_month', executed_date='2026-10-01',
            created_by=self.admin)
        # 值班巡检单
        template = InspectionTemplate.objects.create(
            name='巡检模板', created_by=self.admin, tenant_id='tenant_a')
        InspectionDutySheet.objects.create(
            tenant_id='tenant_a', sheet_no='XJ20261002-0001',
            duty_date='2026-10-02', template=template,
            uniq_key='2026-10-02|%d' % template.id, created_by=self.admin)
        # 系统升级记录
        UpgradeRecord.objects.create(
            upgrade_no=make_upgrade_no(),
            tenant_id='tenant_a', title='软件升级', system=self.system,
            system_code=self.system.system_code, system_name=self.system.name,
            system_location=self.system.install_location,
            upgrade_type='软件升级', owner='测试',
            created_by=self.admin)
        resp = self.client.get(RECORDS_URL + '/statistics/')
        totals = resp.json()['data']['totals']
        self.assertEqual(totals['total'], 1)
        self.assertEqual(resp.json()['data']['by_status'], {'recorded': 1})

    def test_statistics_time_range_and_avg_resolve(self):
        handled = self.create_record(title='已处理情况')
        self.client.post(
            RECORDS_URL + f'/{handled["id"]}/resolve/', {},
            content_type='application/json')
        # 范围外（未来）→ 0 条
        resp = self.client.get(RECORDS_URL + '/statistics/', {
            'occurred_from': '2030-01-01 00:00',
            'occurred_to': '2030-02-01 00:00'})
        self.assertEqual(resp.json()['data']['totals']['total'], 0)
        # 覆盖当前 → 计入且平均处理时长为数值
        resp = self.client.get(RECORDS_URL + '/statistics/')
        totals = resp.json()['data']['totals']
        self.assertEqual(totals['total'], 1)
        self.assertIsNotNone(totals['avg_resolve_hours'])
        self.assertIsInstance(totals['avg_resolve_hours'], float)
        # 趋势按日返回且总数一致
        trend = resp.json()['data']['trend']
        self.assertTrue(trend)
        self.assertEqual(sum(d['total'] for d in trend), 1)

    def test_statistics_stale_open_records(self):
        stale = self.create_record(title='长期未关闭')
        SystemRuntimeRecord.objects.filter(pk=stale['id']).update(
            created_at=timezone.now() - timedelta(days=30))
        fresh = self.create_record(title='新记录', occurred_at='2026-10-01 13:00')
        resp = self.client.get(RECORDS_URL + '/statistics/')
        totals = resp.json()['data']['totals']
        self.assertEqual(totals['stale_open'], 1)
        # 关闭后不再计入长期未关闭
        self.client.post(RECORDS_URL + f'/{stale["id"]}/close/', {},
                         content_type='application/json')
        resp = self.client.get(RECORDS_URL + '/statistics/')
        self.assertEqual(resp.json()['data']['totals']['stale_open'], 0)
        self.assertTrue(
            SystemRuntimeRecord.objects.filter(pk=fresh['id']).exists())


class ConcurrencyTriageConvertTests(TransactionTestCase):
    """4. 真实线程并发"研判转故障"：行锁 + 状态机仲裁，只能成功一次。"""

    def test_concurrent_triage_convert_creates_single_fault(self):
        from django.db import connections

        admin = make_user(
            'rt2_cc_%s' % uuid.uuid4().hex[:8], ALL_RUNTIME_PERMS + FAULT_PERMS,
            tenant_id='tenant_a')
        system = make_system(admin, tenant_id='tenant_a')
        record = SystemRuntimeRecord.objects.create(
            tenant_id='tenant_a',
            record_no='YX2-CC-0001',
            system=system,
            system_code=system.system_code,
            system_name=system.name,
            system_location=system.install_location,
            occurred_at='2026-10-01 08:00',
            title='并发研判转故障记录',
            description='并发研判转故障行为测试',
            created_by=admin,
        )
        barrier = threading.Barrier(2)
        results = {}

        def _runner(key):
            def run():
                client = make_client(admin)
                try:
                    barrier.wait(timeout=15)
                except Exception:
                    pass
                try:
                    resp = client.post(
                        RECORDS_URL + f'/{record.id}/triage/',
                        {'convert_to_fault': True, 'triage_note': '并发研判转故障'},
                        content_type='application/json')
                    body = resp.json()
                    results[key] = None if body.get('error') else body['data']['id']
                finally:
                    connections.close_all()
            return run

        threads = [threading.Thread(target=_runner(key)) for key in ('a', 'b')]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertEqual(set(results.keys()), {'a', 'b'}, results)
        winners = [key for key, value in results.items() if value is not None]
        self.assertEqual(len(winners), 1, results)
        # 终态：恰好一条有效故障，记录状态已转故障
        self.assertEqual(
            SystemFault.objects.filter(source_runtime_record_id=record.id).count(), 1)
        record.refresh_from_db()
        self.assertEqual(record.status, 'converted_fault')


class V2PermissionTests(RuntimeRecordV2TestBase):
    """10. 无权限用户不能研判、关联；只读用户可看待办与统计。"""

    def test_triage_requires_permission(self):
        data = self.create_record()
        for client in (self.viewer_client, self.noperm_client):
            resp = client.post(
                RECORDS_URL + f'/{data["id"]}/triage/',
                {'needs_follow_up': True}, content_type='application/json')
            self.assertTrue(resp.json().get('error'))
            resp = client.post(
                RECORDS_URL + f'/{data["id"]}/pending-triage/', {},
                content_type='application/json')
            self.assertTrue(resp.json().get('error'))
            resp = client.post(
                RECORDS_URL + f'/{data["id"]}/no-follow-up/', {},
                content_type='application/json')
            self.assertTrue(resp.json().get('error'))
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.status, 'recorded')

    def test_convert_and_important_require_own_permissions(self):
        data = self.create_record()
        # 仅有研判权限（无 fault.add）→ 研判转故障拒绝
        resp = self.triager_client.post(
            RECORDS_URL + f'/{data["id"]}/triage/',
            {'convert_to_fault': True, 'triage_note': '说明'},
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(SystemFault.objects.count(), 0)
        # 研判标记重要需要 important 权限
        resp = self.triager_client.post(
            RECORDS_URL + f'/{data["id"]}/triage/',
            {'needs_follow_up': False, 'mark_important': True,
             'importance_reason': '原因'},
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.importance, 'normal')
        # 标记重要独立端点同样受限（无 important 权限）
        resp = self.triager_client.post(
            RECORDS_URL + f'/{data["id"]}/mark-important/',
            {'importance_reason': '原因'}, content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_link_requires_permission(self):
        first = self.create_record()
        second = self.create_record(occurred_at='2026-10-01 09:30')
        for client in (self.viewer_client, self.noperm_client):
            resp = client.post(
                RECORDS_URL + f'/{first["id"]}/duplicate-links/',
                {'duplicate_id': second['id']}, content_type='application/json')
            self.assertTrue(resp.json().get('error'))
            resp = client.post(
                RECORDS_URL + f'/{first["id"]}/mark-repeated/', {},
                content_type='application/json')
            self.assertTrue(resp.json().get('error'))
        self.assertEqual(SystemRuntimeRecordDuplicateLink.objects.count(), 0)

    def test_view_perm_user_can_read_todo_and_statistics(self):
        data = self.create_record()
        self.client.post(
            RECORDS_URL + f'/{data["id"]}/triage/',
            {'needs_follow_up': True}, content_type='application/json')
        for url in (RECORDS_URL + '/todo/', RECORDS_URL + '/statistics/'):
            resp = self.viewer_client.get(url)
            self.assertFalse(resp.json().get('error'), resp.content)
        # 查看者可以读相似记录与关联列表
        resp = self.viewer_client.get(RECORDS_URL + f'/{data["id"]}/similar/')
        self.assertFalse(resp.json().get('error'), resp.content)

    def test_close_permission_required(self):
        data = self.create_record()
        resp = self.viewer_client.post(
            RECORDS_URL + f'/{data["id"]}/close/', {},
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.status, 'recorded')

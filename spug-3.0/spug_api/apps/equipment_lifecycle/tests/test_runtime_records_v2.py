# -*- coding: utf-8 -*-
"""运行异常记录第二版（2026-10）真实行为测试：状态闭环 / 转故障 / 待办 / 统计。

覆盖任务要求的行为断言（HTTP 真实路径 + 数据库副作用，不使用源码字符串匹配）：
1. 状态机（2026-10-05 第四版，研判不再是必经步骤）：新建即已记录（登记
   已完成的合法稳定状态，可长期保留，不作为待办）；首条跟进记录（追加
   处理进展）触发跟进中；完成跟进入已完成（可重新跟进）；转故障由独立
   端点完成（recorded/following_up 均可直接转换）；
2. 旧端点（2026-10-06 随状态归一/重复功能退役删除）：triage/close/similar/
   duplicate-links/mark-repeated/pending-triage/no-follow-up/mark-important
   路由一律 404；
3. 转正式故障建立正式外键并带入结构化字段；重复/并发转换不重复创建；
4. 转故障后的处理进展进入故障模块，运行异常记录侧被拒绝；
5. 动作写业务审计（record_audit_event），新流程不写系统履历；
6. 待办列表只显示跟进中记录（超期/跟进人/计划时间筛选）；
7. 统计遵守租户隔离，状态维度为四状态原值计数（无 duplicated/important
   键），巡视/维护/配置变更/升级数据不进入运行异常记录统计；
8. 无权限用户不能追加进展/完成跟进/重新跟进；只读用户可看待办与统计；
9. 系统详情页签筛选（异常类别/关键词）与最近发生时间摘要。
"""
import threading
import uuid
from datetime import timedelta

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.equipment_lifecycle.models import (
    InspectionDutySheet,
    InspectionTemplate,
    OperationLedger,
    SystemEvent,
    SystemFault,
    SystemRuntimeRecord,
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
P_RESOLVE = 'equipment_lifecycle.runtime_record.resolve'
P_CONVERT = 'equipment_lifecycle.runtime_record.convert_fault'

# triage/close/link 权限码已随旧端点删除（2026-10-06 状态归一清理），
# important 权限码已随"标记重要"功能删除，均不再参与授权
ALL_RUNTIME_PERMS = [P_VIEW, P_ADD, P_EDIT, P_RESOLVE, P_CONVERT]
FAULT_PERMS = ['equipment_lifecycle.fault.add', 'equipment_lifecycle.fault.handle',
               'equipment_lifecycle.fault.view']

RECORDS_URL = URL_PREFIX + '/runtime-records'

# 已删除的旧端点（路由不存在，一律 404）
REMOVED_ACTION_ROUTES = (
    'triage/', 'close/', 'similar/', 'duplicate-links/',
    'duplicate-links/1/', 'mark-repeated/', 'mark-important/',
    'pending-triage/', 'no-follow-up/',
)


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
        # 只有查看/新增权限（无处理进展/完成跟进/转故障权限）
        cls.viewer = make_user(
            'rt2_view_%s' % uuid.uuid4().hex[:8],
            [P_VIEW, P_ADD], tenant_id='tenant_a')
        cls.other_admin = make_user(
            'rt2_other_%s' % uuid.uuid4().hex[:8],
            ALL_RUNTIME_PERMS + FAULT_PERMS, tenant_id='tenant_b')

    def setUp(self):
        self.client = make_client(self.admin)
        self.viewer_client = make_client(self.viewer)
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

    def start_follow_up(self, record_id, content='现场跟进处理', client=None):
        """已记录 → 跟进中：追加首条处理进展（第四版流程，无研判中转）。"""
        client = client or self.client
        resp = client.post(
            RECORDS_URL + f'/{record_id}/progress/',
            {'content': content},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)

    def assert_runtime_events(self, record_id, actions):
        events = SystemEvent.objects.filter(
            source_type='runtime_record', source_id=str(record_id))
        self.assertEqual(
            sorted(e.action for e in events), sorted(actions),
            [(e.action, e.title) for e in events])
        return events


class StateFlowTests(RuntimeRecordV2TestBase):
    """1/2. 状态闭环：已记录（留痕稳定态）→ 跟进中（首条跟进记录）→
    已完成（可重新跟进）；旧兼容端点路由一律 404。"""

    def test_created_record_is_recorded_and_stable(self):
        """新建成功即 recorded（合法稳定状态），不做动作状态不被自动推进。"""
        data = self.create_record()
        self.assertEqual(data['status'], 'recorded')
        self.assertEqual(data['status_text'], '已记录')
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.status, 'recorded')
        resp = self.client.get(RECORDS_URL + f'/{data["id"]}/')
        self.assertEqual(resp.json()['data']['status'], 'recorded')
        record.refresh_from_db()
        self.assertEqual(record.status, 'recorded')

    def test_removed_action_routes_return_404(self):
        """旧端点（研判/关闭/重复问题/标记重要/中转端点）已整体删除：404。"""
        data = self.create_record()
        record_id = data['id']
        for action in REMOVED_ACTION_ROUTES:
            resp = self.client.post(
                RECORDS_URL + f'/{record_id}/{action}', {},
                content_type='application/json')
            self.assertEqual(resp.status_code, 404, action)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'recorded')

    def test_first_progress_moves_to_following_up_then_complete(self):
        """首条跟进记录进入跟进中；完成跟进入已完成；已完成可重新跟进。"""
        data = self.create_record()
        record_id = data['id']
        self.start_follow_up(record_id, content='现场检查，需要持续观察')
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'following_up')
        self.assertTrue(record.needs_follow_up)
        # 研判不再是必经步骤：新流程不写研判字段
        self.assertIsNone(record.triaged_at)
        # 跟进中 → 完成跟进（已完成，resolved_at 记录首次完成时间）
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/resolve/',
            {'handling_result': '链路稳定'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record.refresh_from_db()
        self.assertEqual(record.status, 'completed')
        first_resolved_at = record.resolved_at
        self.assertIsNotNone(first_resolved_at)
        # 已完成重新跟进直接回跟进中（不要求关闭，closed 状态已退役）
        resp = self.client.post(RECORDS_URL + f'/{record_id}/follow-up/', {},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record.refresh_from_db()
        self.assertEqual(record.status, 'following_up')
        # 再次完成跟进不覆盖首次完成时间
        self.client.post(RECORDS_URL + f'/{record_id}/resolve/', {},
                         content_type='application/json')
        record.refresh_from_db()
        self.assertEqual(record.resolved_at, first_resolved_at)

    def test_actions_write_audit_log(self):
        """处理进展/完成跟进/重新跟进动作写业务审计。"""
        data = self.create_record()
        record_id = data['id']
        before = AuditLog.objects.filter(
            target_type='el_runtime_record', target_id=str(record_id)).count()
        self.start_follow_up(record_id)
        self.client.post(RECORDS_URL + f'/{record_id}/resolve/', {},
                         content_type='application/json')
        self.client.post(RECORDS_URL + f'/{record_id}/follow-up/', {},
                         content_type='application/json')
        after = AuditLog.objects.filter(
            target_type='el_runtime_record', target_id=str(record_id)).count()
        self.assertGreater(after, before)

    def test_new_flow_writes_no_system_event(self):
        """运行异常记录不写系统履历（第四版起，历史事件保留仅供回溯）。"""
        data = self.create_record()
        record_id = data['id']
        self.start_follow_up(record_id)
        self.client.post(RECORDS_URL + f'/{record_id}/resolve/', {},
                         content_type='application/json')
        self.client.post(RECORDS_URL + f'/{record_id}/follow-up/', {},
                         content_type='application/json')
        self.assert_runtime_events(record_id, [])


class ConvertFaultTests(RuntimeRecordV2TestBase):
    """3/4. 转正式故障：独立端点、正式外键、字段带入、进展归故障模块。"""

    def test_convert_creates_fault_with_fk_and_fields(self):
        data = self.create_record(
            category='device', initial_reason='疑为功放模块老化')
        record_id = data['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/convert-to-fault/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault_no = resp.json()['data']['fault_no']
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'converted_fault')
        self.assertFalse(record.needs_follow_up)
        fault = SystemFault.objects.get(fault_no=fault_no, tenant_id='tenant_a')
        # 正式外键双向关联 + 来源类型
        self.assertEqual(fault.source_runtime_record_id, record_id)
        self.assertEqual(fault.source_type, 'runtime_record')
        # 结构化字段带入故障（初步原因保留；影响属性按故障默认
        # "不影响系统运行"；具体对象/影响字段已随记录字段删除不再带入）
        self.assertEqual(fault.fault_object_name, '')
        self.assertEqual(fault.fault_object_model, '')
        self.assertEqual(fault.reason_analysis, '疑为功放模块老化')
        self.assertFalse(fault.affects_system_operation)
        self.assertEqual(fault.impact_status, '')
        # 故障详情暴露来源运行异常记录（双向追溯）
        resp = self.client.get(URL_PREFIX + f'/faults/{fault.id}/')
        self.assertFalse(resp.json().get('error'), resp.content)
        detail = resp.json()['data']
        self.assertEqual(detail['source_runtime_record'], record_id)
        self.assertEqual(detail['source_runtime_record_no'], record.record_no)
        # 转故障后记录详情可见关联故障
        resp = self.client.get(RECORDS_URL + f'/{record_id}/')
        self.assertEqual(resp.json()['data']['converted_fault'], fault.id)

    def test_convert_twice_rejected(self):
        data = self.create_record()
        record_id = data['id']
        self.client.post(RECORDS_URL + f'/{record_id}/convert-to-fault/', {},
                         content_type='application/json')
        resp = self.client.post(RECORDS_URL + f'/{record_id}/convert-to-fault/', {},
                                content_type='application/json')
        self.assertIn('不能重复转换', resp.json().get('error', ''))
        self.assertEqual(
            SystemFault.objects.filter(source_runtime_record_id=record_id).count(), 1)

    def test_progress_after_convert_belongs_to_fault(self):
        data = self.create_record()
        record_id = data['id']
        self.start_follow_up(record_id)
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/convert-to-fault/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault_id = SystemRuntimeRecord.objects.get(
            pk=record_id).generated_faults.first().id
        # 运行异常记录侧：不允许再追加普通处理进展
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


class TodoListTests(RuntimeRecordV2TestBase):
    """6. 待办列表只显示跟进中记录，支持超期/跟进人/计划时间筛选。"""

    def setUp(self):
        super().setUp()
        # 状态机：已记录经首条跟进记录进入跟进中
        self.following = self.create_record(title='跟进中问题')
        self.start_follow_up(self.following['id'])
        self.client.post(
            RECORDS_URL + f'/{self.following["id"]}/follow-up/',
            {'follow_up_name': '王值班', 'planned_handle_at': '2020-01-01 09:00'},
            content_type='application/json')
        self.resolved = self.create_record(
            title='已完成问题', occurred_at='2026-10-01 09:00')
        self.start_follow_up(self.resolved['id'])
        self.client.post(
            RECORDS_URL + f'/{self.resolved["id"]}/resolve/', {},
            content_type='application/json')
        self.converted = self.create_record(
            title='已转故障问题', occurred_at='2026-10-01 10:00')
        self.client.post(
            RECORDS_URL + f'/{self.converted["id"]}/convert-to-fault/', {},
            content_type='application/json')
        # 留痕记录（已记录是合法稳定状态，不进入待办）
        self.untouched = self.create_record(
            title='留痕记录', occurred_at='2026-10-01 11:00')

    def test_todo_only_following_up(self):
        resp = self.client.get(RECORDS_URL + '/todo/')
        body = resp.json()['data']
        ids = [r['id'] for r in body['data']]
        self.assertIn(self.following['id'], ids)
        self.assertNotIn(self.resolved['id'], ids)
        self.assertNotIn(self.converted['id'], ids)
        # 留痕的已记录不是待办事项
        self.assertNotIn(self.untouched['id'], ids)
        self.assertGreaterEqual(body['overdue_count'], 1)

    def test_created_with_follow_up_flag_stays_recorded_and_not_todo(self):
        """新建表单勾选"需要跟进"只作标记：状态仍为已记录，不进跟进待办
        （进入跟进流程必须经首条跟进记录，不能把所有记录变成待办）。"""
        data = self.create_record(title='勾选需要跟进的留痕',
                                  occurred_at='2026-10-01 12:00',
                                  needs_follow_up=True)
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.status, 'recorded')
        self.assertTrue(record.needs_follow_up)
        resp = self.client.get(RECORDS_URL + '/todo/')
        body = resp.json()['data']
        self.assertNotIn(data['id'], [r['id'] for r in body['data']])
        # 首条跟进记录后才进入跟进中并进入待办
        self.start_follow_up(data['id'])
        record.refresh_from_db()
        self.assertEqual(record.status, 'following_up')
        resp = self.client.get(RECORDS_URL + '/todo/')
        self.assertIn(data['id'],
                      [r['id'] for r in resp.json()['data']['data']])

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
        # 无字段重复标记 → 维持拒绝
        resp = self.client.post(
            RECORDS_URL + f'/{self.following["id"]}/follow-up/', {},
            content_type='application/json')
        self.assertIn('已处于跟进中', resp.json().get('error', ''))


class RuntimeStatisticsTests(RuntimeRecordV2TestBase):
    """7. 统计：租户隔离、只统计运行异常记录、状态维度为四状态原值计数。"""

    def test_statistics_counts_and_tenant_isolation(self):
        normal = self.create_record(title='普通情况')
        following = self.create_record(
            title='跟进情况', occurred_at='2026-10-01 09:00')
        self.start_follow_up(following['id'])
        converted = self.create_record(
            title='转故障情况', occurred_at='2026-10-01 10:00')
        self.start_follow_up(converted['id'])
        self.client.post(
            RECORDS_URL + f'/{converted["id"]}/convert-to-fault/', {},
            content_type='application/json')
        completed = self.create_record(
            title='已完成情况', occurred_at='2026-10-01 11:00')
        self.start_follow_up(completed['id'])
        self.client.post(
            RECORDS_URL + f'/{completed["id"]}/resolve/', {},
            content_type='application/json')
        # 租户 B 的记录不计入租户 A 统计
        self.create_record(
            client=self.other_client, system=self.other_system,
            title='租户B记录')

        resp = self.client.get(RECORDS_URL + '/statistics/')
        self.assertFalse(resp.json().get('error'), resp.content)
        stats = resp.json()['data']
        totals = stats['totals']
        self.assertEqual(totals['total'], 4)
        self.assertEqual(totals['following_up'], 1)
        self.assertEqual(totals['converted_fault'], 1)
        # 重复问题统计键已随重复功能退役删除（标记重要同）
        self.assertNotIn('duplicated', totals)
        self.assertNotIn('important', totals)
        # 状态维度为四状态原值计数 / 系统维度
        self.assertEqual(stats['by_status'].get('recorded'), 1)
        self.assertEqual(stats['by_status'].get('following_up'), 1)
        self.assertEqual(stats['by_status'].get('completed'), 1)
        self.assertEqual(stats['by_status'].get('converted_fault'), 1)
        system_rows = stats['by_system']
        self.assertEqual(len(system_rows), 1)
        self.assertEqual(system_rows[0]['system'], self.system.id)
        self.assertEqual(system_rows[0]['total'], 4)
        self.assertNotIn('important', system_rows[0])

    def test_statistics_excludes_other_business_data(self):
        """巡视、维护、升级数据不进入运行异常记录统计。"""
        self.create_record(title='唯一的运行异常记录')
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
        handled = self.create_record(title='已完成情况')
        # 首条跟进记录进入跟进中后完成跟进（已记录不能直接完成跟进）
        self.start_follow_up(handled['id'])
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
        """长期未关闭只统计跟进中（留痕为合法稳定状态，不计积压）。"""
        stale = self.create_record(title='长期跟进未关闭')
        self.start_follow_up(stale['id'])
        self.client.post(
            RECORDS_URL + f'/{stale["id"]}/follow-up/',
            {'follow_up_name': '王值班'}, content_type='application/json')
        SystemRuntimeRecord.objects.filter(pk=stale['id']).update(
            created_at=timezone.now() - timedelta(days=30))
        # 留痕的已记录同样创建超过 30 天，但不计入长期未关闭
        plain = self.create_record(title='长期留痕记录',
                                   occurred_at='2026-10-01 13:00')
        SystemRuntimeRecord.objects.filter(pk=plain['id']).update(
            created_at=timezone.now() - timedelta(days=30))
        fresh = self.create_record(title='新记录', occurred_at='2026-10-01 14:00')
        resp = self.client.get(RECORDS_URL + '/statistics/')
        totals = resp.json()['data']['totals']
        self.assertEqual(totals['stale_open'], 1)
        # 完成跟进后不再计入长期未关闭
        self.client.post(RECORDS_URL + f'/{stale["id"]}/resolve/', {},
                         content_type='application/json')
        resp = self.client.get(RECORDS_URL + '/statistics/')
        self.assertEqual(resp.json()['data']['totals']['stale_open'], 0)
        self.assertTrue(
            SystemRuntimeRecord.objects.filter(pk=fresh['id']).exists())


class ConcurrencyConvertTests(TransactionTestCase):
    """3. 真实线程并发转故障：行锁 + 状态机仲裁，只能成功一次。"""

    def test_concurrent_convert_creates_single_fault(self):
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
            title='并发转故障记录',
            description='并发转故障行为测试',
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
                        RECORDS_URL + f'/{record.id}/convert-to-fault/', {},
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
    """8. 无权限用户不能追加进展/完成跟进/重新跟进；只读用户可看待办与统计。"""

    def test_progress_and_resolve_require_permission(self):
        data = self.create_record()
        for client in (self.viewer_client, self.noperm_client):
            resp = client.post(
                RECORDS_URL + f'/{data["id"]}/progress/',
                {'content': '无权限进展'}, content_type='application/json')
            self.assertTrue(resp.json().get('error'))
            resp = client.post(
                RECORDS_URL + f'/{data["id"]}/resolve/', {},
                content_type='application/json')
            self.assertTrue(resp.json().get('error'))
            resp = client.post(
                RECORDS_URL + f'/{data["id"]}/follow-up/', {},
                content_type='application/json')
            self.assertTrue(resp.json().get('error'))
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.status, 'recorded')

    def test_convert_requires_own_permissions(self):
        data = self.create_record()
        # 仅有查看/新增权限（无 convert_fault）→ 转故障拒绝
        resp = self.viewer_client.post(
            RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(SystemFault.objects.count(), 0)
        # 旧端点对任何用户均不存在（路由 404，与权限无关）
        for client in (self.viewer_client, self.noperm_client):
            resp = client.post(
                RECORDS_URL + f'/{data["id"]}/mark-important/',
                {'importance_reason': '原因'}, content_type='application/json')
            self.assertEqual(resp.status_code, 404)

    def test_view_perm_user_can_read_todo_and_statistics(self):
        data = self.create_record()
        self.start_follow_up(data['id'])
        for url in (RECORDS_URL + '/todo/', RECORDS_URL + '/statistics/'):
            resp = self.viewer_client.get(url)
            self.assertFalse(resp.json().get('error'), resp.content)
        # 查看者可读详情与进展列表
        resp = self.viewer_client.get(RECORDS_URL + f'/{data["id"]}/progress/')
        self.assertFalse(resp.json().get('error'), resp.content)


class SystemHistoryFilterTests(RuntimeRecordV2TestBase):
    """9. 系统详情页签筛选（异常类别/关键词）与最近发生时间摘要。"""

    def test_system_history_filters_and_summary(self):
        base = self.create_record(
            title='信标机告警', category='device',
            occurred_at='2026-10-01 08:00')
        self.create_record(
            title='供电波动', category='power', occurred_at='2026-10-01 08:00')
        # 按异常类别筛选系统历史运行异常记录
        resp = self.client.get(
            URL_PREFIX + f'/systems/{self.system.id}/runtime-records/',
            {'category': 'device'})
        rows = resp.json()['data']['data']
        self.assertEqual([r['id'] for r in rows], [base['id']])
        self.assertTrue(resp.json()['data'].get('latest_occurred_at'))
        # 按标题关键词筛选
        resp = self.client.get(
            URL_PREFIX + f'/systems/{self.system.id}/runtime-records/',
            {'keyword': '信标机'})
        self.assertEqual(resp.json()['data']['total'], 1)

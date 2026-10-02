# -*- coding: utf-8 -*-
"""运行记录（2026-10 第一版）真实行为测试。

覆盖任务要求的行为断言（HTTP 真实路径 + 数据库副作用，不使用源码字符串匹配）：
1. 只填系统/时间/标题/描述即可创建；
2. 普通记录可直接处理并关闭；
3. 跟进记录可追加多条处理进展；
4. 处理进展更正留痕，不能静默覆盖；
5. 同一记录只能转为一条有效故障（含真实线程并发场景）；
6. 转故障建立正式外键，记录状态正确变化；
7. 普通小问题不自动生成 SystemEvent；
8. 标记重要按规则生成履历，重复操作不重复生成；
9. 租户之间互不可见；
10. 无权限用户不能创建、查看、转故障或关闭；
11. 附件访问必须先校验父对象与租户；
12. 幂等令牌不能创建重复记录；
13. 并发转故障只能成功一次；
14. 运行记录不含巡视、维护、升级和配置变更数据；
15. 关闭后的记录不能继续被普通编辑。
"""
import shutil
import tempfile
import threading
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings

from apps.equipment_lifecycle import fault_services, runtime_record_services
from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemEvent,
    SystemFault,
    SystemRuntimeRecord,
    SystemRuntimeRecordProgress,
)
from apps.equipment_lifecycle.tests.base import (
    URL_PREFIX,
    make_client, make_system, make_user,
)

P_VIEW = 'equipment_lifecycle.runtime_record.view'
P_ADD = 'equipment_lifecycle.runtime_record.add'
P_EDIT = 'equipment_lifecycle.runtime_record.edit'
P_RESOLVE = 'equipment_lifecycle.runtime_record.resolve'
P_CLOSE = 'equipment_lifecycle.runtime_record.close'
P_CONVERT = 'equipment_lifecycle.runtime_record.convert_fault'
P_IMPORTANT = 'equipment_lifecycle.runtime_record.important'

ALL_RUNTIME_PERMS = [P_VIEW, P_ADD, P_EDIT, P_RESOLVE, P_CLOSE, P_CONVERT, P_IMPORTANT]
FAULT_ADD_PERM = 'equipment_lifecycle.fault.add'
# 转故障目标作废（受控作废）需要故障 del 权限
FAULT_DEL_PERM = 'equipment_lifecycle.fault.del'

RECORDS_URL = URL_PREFIX + '/runtime-records'


def make_record_payload(**overrides):
    payload = {
        'system': None,
        'occurred_at': '2026-10-01 08:30',
        'title': '主用链路短暂中断',
        'description': '值班发现主用链路丢包约 3 分钟后自行恢复',
    }
    payload.update(overrides)
    return payload


class RuntimeRecordTestBase(TestCase):
    """公共夹具：全权限用户 + 无权限用户 + 双租户。

    用户与系统放 setUpTestData（每类一次）；client 必须在 setUp 中创建——
    Django 4.2 的 TestCase.client 是惰性 property，每个测试会重建默认
    client，setUpTestData 中赋值的 cls.client 不生效（无 token 头 → 401）。
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user(
            'rt_admin_%s' % uuid.uuid4().hex[:8],
            ALL_RUNTIME_PERMS + [FAULT_ADD_PERM, FAULT_DEL_PERM],
            tenant_id='tenant_a')
        cls.noperm = make_user(
            'rt_noperm_%s' % uuid.uuid4().hex[:8], [], tenant_id='tenant_a')
        cls.other_admin = make_user(
            'rt_other_%s' % uuid.uuid4().hex[:8],
            ALL_RUNTIME_PERMS + [FAULT_ADD_PERM],
            tenant_id='tenant_b')
        # 履历查看用户（同租户）：验证运行记录事件进入系统履历页面
        cls.event_viewer = make_user(
            'rt_viewer_%s' % uuid.uuid4().hex[:8],
            [P_VIEW, 'equipment_lifecycle.system_event.view'],
            tenant_id='tenant_a')

    def setUp(self):
        self.client = make_client(self.admin)
        self.other_client = make_client(self.other_admin)
        self.noperm_client = make_client(self.noperm)
        self.viewer_client = make_client(self.event_viewer)
        self.system = make_system(self.admin, tenant_id='tenant_a',
                                  system_code='RT-SYS-%s' % uuid.uuid4().hex[:6].upper())
        self.other_system = make_system(self.other_admin, tenant_id='tenant_b',
                                        system_code='RT-SYS-B-%s' % uuid.uuid4().hex[:6].upper())

    def create_record(self, client=None, system=None, **overrides):
        client = client or self.client
        payload = make_record_payload(
            system=(system or self.system).id, **overrides)
        resp = client.post(RECORDS_URL + '/', payload,
                           content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']


class MinimalCreateTests(RuntimeRecordTestBase):
    """1. 只填写系统、时间、标题和描述即可创建。"""

    def test_create_with_minimal_fields(self):
        data = self.create_record()
        self.assertTrue(data['id'])
        self.assertRegex(data['record_no'], r'^YX\d{8}-\d{4}$')
        self.assertEqual(data['status'], 'recorded')
        self.assertEqual(data['status_text'], '已记录')
        self.assertEqual(data['importance'], 'normal')
        # 快照：创建时点系统编号/名称/安装地点
        self.assertEqual(data['system_code'], self.system.system_code)
        self.assertEqual(data['system_name'], self.system.name)
        self.assertEqual(data['system_location'], self.system.install_location)
        # 数据库副作用
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.tenant_id, 'tenant_a')
        self.assertEqual(record.created_by_id, self.admin.id)
        self.assertEqual(record.impact_status, '')

    def test_required_fields_enforced(self):
        for missing in ('system', 'occurred_at', 'title', 'description'):
            payload = make_record_payload(system=self.system.id)
            payload.pop(missing)
            resp = self.client.post(RECORDS_URL + '/', payload,
                                    content_type='application/json')
            self.assertTrue(resp.json().get('error'), resp.content)
        self.assertEqual(SystemRuntimeRecord.objects.count(), 0)

    def test_impact_requires_affect_flag(self):
        # 不影响运行时影响程度强制存空串；影响运行时必须选择影响程度
        data = self.create_record(
            title='不影响运行的情况', affects_system_operation=False,
            impact_status='degraded')
        self.assertEqual(data['impact_status'], '')
        resp = self.client.post(RECORDS_URL + '/', make_record_payload(
            system=self.system.id, title='影响但未选程度',
            affects_system_operation=True),
            content_type='application/json')
        self.assertIn('影响程度', resp.json().get('error', ''))
        data = self.create_record(
            title='影响运行的情况', occurred_at='2026-10-01 08:40',
            affects_system_operation=True, impact_status='interrupted')
        self.assertEqual(data['impact_status'], 'interrupted')

    def test_created_by_user_without_add_perm_rejected(self):
        resp = self.noperm_client.post(
            RECORDS_URL + '/', make_record_payload(system=self.system.id),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(SystemRuntimeRecord.objects.count(), 0)


class SimpleResolveCloseTests(RuntimeRecordTestBase):
    """2. 普通运行记录可以直接处理并关闭。"""

    def test_resolve_then_close(self):
        data = self.create_record(handling_result='现场已处理')
        record_id = data['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/resolve/',
            {'handling_result': '确认稳定运行'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(resp.json()['data']['status'], 'resolved')
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.handling_result, '确认稳定运行')
        self.assertFalse(record.needs_follow_up)
        resp = self.client.post(RECORDS_URL + f'/{record_id}/close/', {},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record.refresh_from_db()
        self.assertEqual(record.status, 'closed')
        # 关闭后不能追加进展 / 不能再次关闭
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/progress/',
            {'content': '补充进展', 'handler_name': '张三'},
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        resp = self.client.post(RECORDS_URL + f'/{record_id}/close/', {},
                                content_type='application/json')
        self.assertIn('重复关闭', resp.json().get('error', ''))

    def test_direct_close_from_recorded(self):
        data = self.create_record()
        resp = self.client.post(RECORDS_URL + f'/{data["id"]}/close/', {},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.status, 'closed')


class FollowUpProgressTests(RuntimeRecordTestBase):
    """3. 需要跟进的记录可以追加多条处理进展。"""

    def test_follow_up_and_append_progress(self):
        data = self.create_record(needs_follow_up=True)
        record_id = data['id']
        resp = self.client.post(RECORDS_URL + f'/{record_id}/follow-up/', {},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'following_up')
        self.assertTrue(record.needs_follow_up)
        for idx in range(2):
            resp = self.client.post(
                RECORDS_URL + f'/{record_id}/progress/',
                {'content': '第%d次跟进：持续观察' % (idx + 1),
                 'handler_name': '值班员甲',
                 'work_hours': 0.5},
                content_type='application/json')
            self.assertFalse(resp.json().get('error'), resp.content)
        resp = self.client.get(RECORDS_URL + f'/{record_id}/progress/')
        rows = resp.json()['data']['data']
        self.assertEqual(len(rows), 2)
        self.assertEqual([r['handler_name'] for r in rows], ['值班员甲', '值班员甲'])
        self.assertEqual(
            SystemRuntimeRecordProgress.objects.filter(record_id=record_id).count(), 2)

    def test_progress_correction_keeps_history(self):
        """4. 处理进展支持更正历史，不能静默覆盖。"""
        data = self.create_record()
        record_id = data['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/progress/',
            {'content': '更换主用链路', 'handler_name': '值班员甲'},
            content_type='application/json')
        progress_id = resp.json()['data']['id']
        # 缺少更正原因 → 拒绝
        resp = self.client.put(
            RECORDS_URL + f'/{record_id}/progress/{progress_id}/',
            {'content': '更换备用链路'},
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        # 带原因更正 → 原内容留痕
        resp = self.client.put(
            RECORDS_URL + f'/{record_id}/progress/{progress_id}/',
            {'content': '更换备用链路', 'correction_reason': '笔误更正'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        progress = SystemRuntimeRecordProgress.objects.get(pk=progress_id)
        self.assertEqual(progress.content, '更换备用链路')
        corrections = progress.get_corrections()
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]['old'], '更换主用链路')
        self.assertEqual(corrections[0]['new'], '更换备用链路')
        self.assertEqual(corrections[0]['reason'], '笔误更正')

    def test_progress_forbidden_after_terminal(self):
        data = self.create_record()
        self.client.post(RECORDS_URL + f'/{data["id"]}/close/', {},
                         content_type='application/json')
        resp = self.client.post(
            RECORDS_URL + f'/{data["id"]}/progress/',
            {'content': '关闭后补录', 'handler_name': '值班员甲'},
            content_type='application/json')
        self.assertIn('已关闭或已转故障', resp.json().get('error', ''))


class ConvertToFaultTests(RuntimeRecordTestBase):
    """5/6. 转为正式故障：一次转换 + 正式外键 + 状态变化。"""

    def test_convert_creates_fault_with_fk(self):
        data = self.create_record(
            affects_system_operation=True, impact_status='degraded')
        record_id = data['id']
        resp = self.client.post(RECORDS_URL + f'/{record_id}/convert-to-fault/', {},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault_no = resp.json()['data']['fault_no']
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'converted_fault')
        fault = SystemFault.objects.get(fault_no=fault_no, tenant_id='tenant_a')
        # 正式外键（不得使用自由文本代替外键）
        self.assertEqual(fault.source_runtime_record_id, record_id)
        self.assertEqual(fault.source_type, 'runtime_record')
        self.assertEqual(fault.source_id, str(record_id))
        # 初始字段由记录带入：系统/影响/标题+描述组装现象
        self.assertEqual(fault.system_id, self.system.id)
        self.assertEqual(fault.affects_system_operation, True)
        self.assertEqual(fault.impact_status, 'degraded')
        self.assertIn(record.title, fault.phenomenon)
        self.assertIn(record.description, fault.phenomenon)
        # 记录详情可见关联故障
        resp = self.client.get(RECORDS_URL + f'/{record_id}/')
        self.assertEqual(resp.json()['data']['converted_fault'], fault.id)

    def test_convert_twice_rejected(self):
        data = self.create_record()
        resp = self.client.post(RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        resp = self.client.post(RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
                                content_type='application/json')
        self.assertIn('不能重复转换', resp.json().get('error', ''))
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.generated_faults.count(), 1)

    def test_convert_requires_fault_add_perm(self):
        limited = make_user(
            'rt_conv_%s' % uuid.uuid4().hex[:8], ALL_RUNTIME_PERMS, tenant_id='tenant_a')
        limited_client = make_client(limited)
        data = self.create_record(client=limited_client)
        resp = limited_client.post(
            RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
            content_type='application/json')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        self.assertEqual(SystemFault.objects.count(), 0)

    def test_convert_after_cancelled_fault_requires_reason(self):
        data = self.create_record()
        resp = self.client.post(RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
                                content_type='application/json')
        fault = SystemFault.objects.get(
            source_runtime_record_id=data['id'])
        # 受控作废首张故障
        resp = self.client.post(
            URL_PREFIX + f'/faults/{fault.id}/cancel/',
            {'cancel_reason': '误转'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 无原因再次转换 → 拒绝；带原因 → 允许
        resp = self.client.post(RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
                                content_type='application/json')
        self.assertIn('重新处置原因', resp.json().get('error', ''))
        resp = self.client.post(
            RECORDS_URL + f'/{data["id"]}/convert-to-fault/',
            {'re_dispose_reason': '故障复发，重新处置'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(
            SystemFault.objects.filter(source_runtime_record_id=data['id']).count(), 2)


class SystemEventRulesTests(RuntimeRecordTestBase):
    """7/8. 履历规则：普通记录不生成；影响运行/标记重要按规则生成且不重复。"""

    def assert_runtime_events(self, record_id, actions):
        events = SystemEvent.objects.filter(
            source_type='runtime_record', source_id=str(record_id))
        self.assertEqual(
            sorted(e.action for e in events), sorted(actions),
            [(e.action, e.title) for e in events])
        return events

    def test_normal_record_no_system_event(self):
        first = self.create_record(title='普通情况一', occurred_at='2026-10-01 08:00')
        second = self.create_record(
            title='普通情况二', occurred_at='2026-10-01 08:10',
            handling_result='小问题已处理')
        self.assert_runtime_events(first['id'], [])
        self.assert_runtime_events(second['id'], [])

    def test_affecting_record_creates_event_once(self):
        data = self.create_record(
            affects_system_operation=True, impact_status='interrupted')
        events = self.assert_runtime_events(data['id'], ['create'])
        event = events.first()
        self.assertEqual(event.event_type, 'runtime')
        self.assertEqual(event.source_no, data['record_no'])
        self.assertEqual(event.system_id, self.system.id)

    def test_mark_important_requires_reason_and_generates_event_once(self):
        data = self.create_record()
        record_id = data['id']
        # 缺原因 → 拒绝
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/mark-important/', {},
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assert_runtime_events(record_id, [])
        # 首次标记 → 一条 mark_important 履历
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/mark-important/',
            {'importance_reason': '造成业务中断影响值班'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(resp.json()['data']['importance'], 'important')
        events = self.assert_runtime_events(record_id, ['mark_important'])
        self.assertIn('造成业务中断', events.first().get_detail().get('importance_reason', ''))
        # 重复标记 → 拒绝且不重复生成履历
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/mark-important/',
            {'importance_reason': '再次标记'},
            content_type='application/json')
        self.assertIn('已标记为重要', resp.json().get('error', ''))
        self.assert_runtime_events(record_id, ['mark_important'])
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.importance_reason, '造成业务中断影响值班')

    def test_important_record_visible_in_event_groups(self):
        """标记重要的运行记录进入系统履历事项聚合（2026-10-01 缺陷回归）。

        缺陷：履历聚合白名单（MAIN_EVENT_TYPES/GROUP_SOURCE_TYPES）未纳入
        runtime/runtime_record，标记重要的记录在履历页面不可见。
        """
        data = self.create_record(title='需要进入履历的情况',
                                  occurred_at='2026-10-01 08:00')
        record_id = data['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/mark-important/',
            {'importance_reason': '影响值班业务'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 履历事项聚合主列表：运行记录事项可见（真实状态/标题取业务表）
        resp = self.viewer_client.get(URL_PREFIX + '/system-event-groups/')
        self.assertFalse(resp.json().get('error'), resp.content)
        items = []
        for group in resp.json()['data']['data']:
            if group['system']['id'] == self.system.id:
                items = group['items']
        runtime_items = [i for i in items if i['source_type'] == 'runtime_record']
        self.assertEqual(len(runtime_items), 1, items)
        item = runtime_items[0]
        self.assertEqual(item['event_type'], 'runtime')
        self.assertEqual(item['item_no'], data['record_no'])
        self.assertEqual(item['source_id'], str(record_id))
        self.assertEqual(item['status'], 'recorded')
        self.assertEqual(item['status_text'], '已记录')
        self.assertEqual(item['title'], '需要进入履历的情况')
        # 节点时间线接口：普通记录创建不写履历，仅 mark_important 一条
        resp = self.viewer_client.get(
            URL_PREFIX + '/system-event-groups/nodes/'
            f'?system={self.system.id}&source_type=runtime_record&source_id={record_id}')
        self.assertFalse(resp.json().get('error'), resp.content)
        actions = {n['action'] for n in resp.json()['data']['data']}
        self.assertEqual(actions, {'mark_important'})

    def test_converted_record_visible_in_event_groups(self):
        """转为故障的运行记录在履历事项聚合中可见且状态为已转故障。"""
        data = self.create_record(title='转故障进履历',
                                  occurred_at='2026-10-01 08:10')
        resp = self.client.post(RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        resp = self.viewer_client.get(URL_PREFIX + '/system-event-groups/')
        groups = resp.json()['data']['data']
        runtime_items = [
            item for group in groups if group['system']['id'] == self.system.id
            for item in group['items'] if item['source_type'] == 'runtime_record']
        self.assertEqual(len(runtime_items), 1)
        self.assertEqual(runtime_items[0]['status'], 'converted_fault')
        self.assertEqual(runtime_items[0]['status_text'], '已转故障')
        # 同系统同时存在故障事项（来源 fault）与运行记录事项，互不归并
        fault_items = [
            item for group in groups if group['system']['id'] == self.system.id
            for item in group['items'] if item['source_type'] == 'fault']
        self.assertEqual(len(fault_items), 1)

    def test_convert_generates_fault_and_runtime_events(self):
        data = self.create_record()
        resp = self.client.post(RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 记录侧 convert_to_fault 履历 + 故障侧 create 履历（source_type=fault）
        self.assert_runtime_events(data['id'], ['convert_to_fault'])
        fault = SystemFault.objects.get(
            source_runtime_record_id=data['id'])
        self.assertTrue(SystemEvent.objects.filter(
            source_type='fault', source_id=str(fault.id), action='create').exists())
        # 履历事件保留运行记录编号与来源链接
        event = SystemEvent.objects.get(
            source_type='runtime_record', source_id=str(data['id']))
        self.assertEqual(event.source_no, data['record_no'])


class TenantAndPermissionTests(RuntimeRecordTestBase):
    """9/10. 租户隔离与权限独立校验。"""

    def test_tenant_isolation(self):
        data = self.create_record()
        # 租户B用户列表看不到租户A记录
        resp = self.other_client.get(RECORDS_URL + '/')
        ids = [r['id'] for r in resp.json()['data']['data']]
        self.assertNotIn(data['id'], ids)
        # 详情/编辑/转故障/关闭一律拒绝
        resp = self.other_client.get(RECORDS_URL + f'/{data["id"]}/')
        self.assertEqual(resp.json().get('error'), '运行记录不存在')
        resp = self.other_client.post(
            RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
            content_type='application/json')
        self.assertEqual(resp.json().get('error'), '运行记录不存在')
        resp = self.other_client.post(
            RECORDS_URL + f'/{data["id"]}/close/', {},
            content_type='application/json')
        self.assertEqual(resp.json().get('error'), '运行记录不存在')
        self.assertEqual(
            SystemRuntimeRecord.objects.filter(pk=data['id']).count(), 1)

    def test_action_permission_required(self):
        data = self.create_record()
        record_id = data['id']
        cases = [
            ('post', RECORDS_URL + '/', {'system': self.system.id,
                                         'occurred_at': '2026-10-01 08:30',
                                         'title': '无权限标题', 'description': 'x'}),
            ('get', RECORDS_URL + f'/{record_id}/', None),
            ('post', RECORDS_URL + f'/{record_id}/close/', {}),
            ('post', RECORDS_URL + f'/{record_id}/resolve/', {}),
        ]
        for method, url, payload in cases:
            kwargs = {'content_type': 'application/json'} if payload is not None else {}
            resp = getattr(self.noperm_client, method)(url, payload, **kwargs) \
                if payload is not None else getattr(self.noperm_client, method)(url)
            self.assertTrue(resp.json().get('error'), (method, url, resp.content))


class IdempotencyTests(RuntimeRecordTestBase):
    """12. 幂等令牌不能创建重复记录。"""

    def test_client_token_returns_existing_record(self):
        token = 'tok-%s' % uuid.uuid4().hex
        first = self.create_record(client_token=token)
        resp = self.client.post(RECORDS_URL + '/', make_record_payload(
            system=self.system.id, title='重复提交的不同标题', client_token=token),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(resp.json()['data']['id'], first['id'])
        self.assertEqual(SystemRuntimeRecord.objects.count(), 1)

    def test_recent_duplicate_rejected(self):
        self.create_record()
        resp = self.client.post(RECORDS_URL + '/', make_record_payload(
            system=self.system.id),
            content_type='application/json')
        self.assertIn('请勿重复提交相同运行记录', resp.json().get('error', ''))
        self.assertEqual(SystemRuntimeRecord.objects.count(), 1)


class ConcurrencyConvertTests(TransactionTestCase):
    """13. 真实线程并发转故障：行锁仲裁，只能成功一次。"""

    def test_concurrent_convert_only_once(self):
        from django.db import connections

        admin = make_user(
            'rt_cc_%s' % uuid.uuid4().hex[:8], ALL_RUNTIME_PERMS + [FAULT_ADD_PERM],
            tenant_id='tenant_a')
        system = make_system(admin, tenant_id='tenant_a')
        record = SystemRuntimeRecord.objects.create(
            tenant_id='tenant_a',
            record_no='YX-CC-0001',
            system=system,
            system_code=system.system_code,
            system_name=system.name,
            system_location=system.install_location,
            occurred_at='2026-10-01 08:00',
            title='并发转换记录',
            description='并发转故障行为测试',
            created_by=admin,
        )
        barrier = threading.Barrier(2)
        results = {}

        def _runner(key):
            def run():
                try:
                    barrier.wait(timeout=15)
                except Exception:
                    pass
                try:
                    with fault_services.health_recalc_lock():
                        with transaction.atomic():
                            locked = SystemRuntimeRecord.objects.select_for_update().get(
                                pk=record.id)
                            fault = runtime_record_services.convert_runtime_record_to_fault(
                                record=locked, created_by=admin)
                            results[key] = fault.id
                except runtime_record_services.RuntimeRecordConvertError:
                    results[key] = None
                finally:
                    connections.close_all()
            return run

        t1 = threading.Thread(target=_runner('a'))
        t2 = threading.Thread(target=_runner('b'))
        t1.start()
        t2.start()
        t1.join(timeout=60)
        t2.join(timeout=60)

        self.assertEqual(set(results.keys()), {'a', 'b'}, results)
        winners = [k for k, v in results.items() if v is not None]
        self.assertEqual(len(winners), 1, results)
        # 终态：恰好一条有效故障，记录状态已转故障
        self.assertEqual(
            SystemFault.objects.filter(source_runtime_record_id=record.id).count(), 1)
        record.refresh_from_db()
        self.assertEqual(record.status, 'converted_fault')


class ModuleBoundaryTests(RuntimeRecordTestBase):
    """14. 运行记录不含巡视、维护、升级和配置变更数据。"""

    def test_list_only_contains_runtime_records(self):
        data = self.create_record()
        # 同系统创建一张故障（其他模块数据）
        fault_services.create_fault_record(
            tenant_id='tenant_a', created_by=self.admin, system=self.system,
            affects_system_operation=False, impact_status='',
            occurred_at='2026-10-01 07:00', phenomenon='模块边界测试故障')
        resp = self.client.get(RECORDS_URL + '/')
        rows = resp.json()['data']['data']
        self.assertEqual([r['id'] for r in rows], [data['id']])
        self.assertTrue(all(r['record_no'].startswith('YX') for r in rows))
        # 系统详情运行记录页签同样只含运行记录
        resp = self.client.get(URL_PREFIX + f'/systems/{self.system.id}/runtime-records/')
        rows = resp.json()['data']['data']
        self.assertEqual([r['id'] for r in rows], [data['id']])


class EditRuleTests(RuntimeRecordTestBase):
    """15. 关闭后的运行记录不能继续被普通编辑；编辑未关闭记录正常。"""

    def test_edit_open_record(self):
        data = self.create_record()
        resp = self.client.put(
            RECORDS_URL + f'/{data["id"]}/',
            {'system': self.system.id, 'occurred_at': '2026-10-01 09:00',
             'title': '更新后的标题', 'description': '更新后的描述',
             'measures_taken': '已切换备用链路'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.title, '更新后的标题')
        self.assertEqual(record.measures_taken, '已切换备用链路')
        self.assertEqual(record.updated_by_id, self.admin.id)

    def test_closed_record_not_editable(self):
        data = self.create_record()
        self.client.post(RECORDS_URL + f'/{data["id"]}/close/', {},
                         content_type='application/json')
        resp = self.client.put(
            RECORDS_URL + f'/{data["id"]}/',
            {'system': self.system.id, 'occurred_at': '2026-10-01 09:00',
             'title': '关闭后编辑', 'description': '不应生效'},
            content_type='application/json')
        self.assertIn('已关闭或已转故障', resp.json().get('error', ''))
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.title, data['title'])

    def test_converted_record_not_editable(self):
        data = self.create_record()
        self.client.post(RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
                         content_type='application/json')
        resp = self.client.put(
            RECORDS_URL + f'/{data["id"]}/',
            {'system': self.system.id, 'occurred_at': '2026-10-01 09:00',
             'title': '转换后编辑', 'description': '不应生效'},
            content_type='application/json')
        self.assertIn('已关闭或已转故障', resp.json().get('error', ''))


class AttachmentAccessTests(RuntimeRecordTestBase):
    """11. 附件访问必须先校验运行记录父对象和租户。"""

    def setUp(self):
        super().setUp()
        storage_dir = tempfile.mkdtemp(prefix='el_rt_att_test_')
        override = override_settings(MEDIA_ROOT=storage_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, storage_dir, ignore_errors=True)

    def _upload(self, record_id, client=None):
        client = client or self.client
        return client.post(
            RECORDS_URL + f'/{record_id}/attachments/',
            {'file': SimpleUploadedFile('现场照片.png', b'\x89PNG-fake-content')})

    def test_upload_list_download_delete(self):
        data = self.create_record()
        record_id = data['id']
        resp = self._upload(record_id)
        self.assertFalse(resp.json().get('error'), resp.content)
        att_id = resp.json()['data']['id']
        resp = self.client.get(RECORDS_URL + f'/{record_id}/attachments/')
        self.assertEqual([a['id'] for a in resp.json()['data']['data']], [att_id])
        resp = self.client.get(
            RECORDS_URL + f'/{record_id}/attachments/{att_id}/download/')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete(RECORDS_URL + f'/{record_id}/attachments/{att_id}/')
        self.assertFalse(resp.json().get('error'), resp.content)
        resp = self.client.get(RECORDS_URL + f'/{record_id}/attachments/')
        self.assertEqual(resp.json()['data']['data'], [])

    def test_cross_record_and_tenant_attachment_denied(self):
        data_a = self.create_record()
        data_b = self.create_record(title='另一条记录')
        resp = self._upload(data_a['id'])
        att_id = resp.json()['data']['id']
        # 父对象不匹配：记录B下访问记录A的附件 → 拒绝
        resp = self.client.get(
            RECORDS_URL + f'/{data_b["id"]}/attachments/{att_id}/download/')
        self.assertTrue(resp.json().get('error'), resp.content)
        resp = self.client.delete(
            RECORDS_URL + f'/{data_b["id"]}/attachments/{att_id}/')
        self.assertTrue(resp.json().get('error'))
        # 跨租户：租户B用户访问 → 父对象即不可见
        resp = self.other_client.get(
            RECORDS_URL + f'/{data_a["id"]}/attachments/{att_id}/download/')
        self.assertTrue(resp.json().get('error'))
        # 跨模块附件（故障进展附件）挂到运行记录路由 → 拒绝
        fault_services.create_fault_record(
            tenant_id='tenant_a', created_by=self.admin, system=self.system,
            affects_system_operation=False, impact_status='',
            occurred_at='2026-10-01 07:00', phenomenon='跨模块附件测试')
        fault = SystemFault.objects.order_by('-id').first()
        progress = SystemFault.objects.get(pk=fault.id).handling_records.create(
            tenant_id='tenant_a', fault=fault, handled_at='2026-10-01 07:30',
            handler=self.admin, content='跨模块进展')
        from apps.evidence.models import EvidenceAttachment
        other_att = EvidenceAttachment.objects.create(
            tenant_id='tenant_a', module='equipment_lifecycle',
            object_type='el_fault_handling', object_id=str(progress.id),
            file_name='他模块.png', file_path='evidence/other.png',
            file_size=10, uploaded_by_id=self.admin.id)
        resp = self.client.get(
            RECORDS_URL + f'/{data_a["id"]}/attachments/{other_att.id}/download/')
        self.assertTrue(resp.json().get('error'))

# -*- coding: utf-8 -*-
"""运行记录（2026-10 第一版）真实行为测试。

覆盖任务要求的行为断言（HTTP 真实路径 + 数据库副作用，不使用源码字符串匹配）：
1. 只填系统/时间/标题/描述即可创建；
2. 状态机（2026-10-05 第四版，研判不再是必经步骤）：用户可见状态只有
   已记录/跟进中/已完成/已转故障；已记录为登记已完成的合法稳定状态
   （可长期保留，不进待办，无需研判）；追加首条跟进记录即进入跟进中；
   转故障为独立动作（recorded/following_up 均可直接转换）；已记录不能
   直接完成跟进；旧 close/triage 兼容端点已随 2026-10-06 状态归一删除
   （404），旧状态值由 CHECK 约束拒绝写入；
3. 跟进记录可追加多条处理进展（跟进计划已删除：追加进展是唯一跟进动作，
   已完成记录追加进展即重新跟进，follow-up 端点 404）；
4. 处理进展更正留痕，不能静默覆盖（处理结果/本次工时字段已删除，携带
   旧参数即拒绝）；
5. 同一记录只能转为一条有效故障（含真实线程并发场景）；
6. 转故障建立正式外键，记录状态正确变化；
7. 运行记录一律不写系统履历（2026-10-05 第四版：普通/转为故障均不生成
   SystemEvent，历史事件保留）；
8. 具体对象名称/对象型号/影响系统运行（含影响程度）/标记重要已删除
   （2026-10-06）：创建/编辑请求携带旧参数即拒绝，mark-important 端点
   不再存在（404）；
9. 租户之间互不可见；
10. 无权限用户不能创建、查看、转故障或完成跟进；
11. 附件访问必须先校验父对象与租户；
12. 幂等令牌不能创建重复记录；
13. 并发转故障只能成功一次；
14. 运行记录不含巡视、维护、升级和配置变更数据；
15. 已转故障的记录不能继续被普通编辑；
16. 旧状态（待研判/无需跟进/已处理/已关闭）已由迁移 0007 归一：数据库
    CHECK 约束拒绝旧值，状态筛选只接受四状态，旧接口路由 404；
17. 信息分层收敛（2026-10-04）：事实/处理两类信息各归其位，新数据
    不再写入 已采取措施/处理结果/初步原因/影响范围；跟进人/计划处理时间
    （跟进计划）与处理进展的处理结果/本次工时已删除（2026-10-06 迁移 0009），
    研判快照字段已彻底删除（2026-10-07 迁移 0010），处理进展追加式不覆盖。
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
P_CONVERT = 'equipment_lifecycle.runtime_record.convert_fault'

# important 权限码已随"标记重要"功能删除（2026-10-06），不再参与授权；
# triage/close 权限码已随旧端点删除（2026-10-06 状态归一清理）
ALL_RUNTIME_PERMS = [P_VIEW, P_ADD, P_EDIT, P_RESOLVE, P_CONVERT]
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
        'registrar_name': '张三',
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

    def start_follow_up(self, record_id, content='现场跟进处理', client=None):
        """已记录 → 跟进中：追加首条处理进展（第四版流程，无研判中转）。"""
        client = client or self.client
        resp = client.post(
            RECORDS_URL + f'/{record_id}/progress/',
            {'content': content},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)


class MinimalCreateTests(RuntimeRecordTestBase):
    """1. 只填写系统、时间、标题和描述即可创建。"""

    def test_create_with_minimal_fields(self):
        data = self.create_record()
        self.assertTrue(data['id'])
        self.assertRegex(data['record_no'], r'^YX\d{8}-\d{4}$')
        self.assertEqual(data['status'], 'recorded')
        self.assertEqual(data['status_text'], '已记录')
        # 登记人：手动输入姓名随创建写入并在详情返回
        self.assertEqual(data['registrar_name'], '张三')
        # 快照：创建时点系统编号/名称/安装地点
        self.assertEqual(data['system_code'], self.system.system_code)
        self.assertEqual(data['system_name'], self.system.name)
        self.assertEqual(data['system_location'], self.system.install_location)
        # 数据库副作用
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.tenant_id, 'tenant_a')
        self.assertEqual(record.created_by_id, self.admin.id)
        self.assertEqual(record.registrar_name, '张三')

    def test_required_fields_enforced(self):
        for missing in ('system', 'occurred_at', 'title', 'description',
                        'registrar_name'):
            payload = make_record_payload(system=self.system.id)
            payload.pop(missing)
            resp = self.client.post(RECORDS_URL + '/', payload,
                                    content_type='application/json')
            self.assertTrue(resp.json().get('error'), resp.content)
        self.assertEqual(SystemRuntimeRecord.objects.count(), 0)

    def test_registrar_name_rules(self):
        # 登记人为空白文本视同未填
        resp = self.client.post(
            RECORDS_URL + '/',
            make_record_payload(system=self.system.id, registrar_name='   '),
            content_type='application/json')
        self.assertIn('登记人', resp.json().get('error', ''))
        self.assertEqual(SystemRuntimeRecord.objects.count(), 0)
        # 多人以顿号分隔提交，首尾空白清洗后原样保存
        data = self.create_record(registrar_name='  张三 、李四  ')
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.registrar_name, '张三 、李四')

    def test_retired_params_rejected_on_create(self):
        """具体对象名称/对象型号/影响系统运行/影响程度/重要程度/跟进计划
        字段已删除（2026-10-06）：创建请求携带任一旧参数即拒绝，不静默忽略。"""
        for key, value in (
                ('affects_system_operation', True),
                ('impact_status', 'degraded'),
                ('object_name', '交换机'),
                ('object_model', 'S5700'),
                ('importance', 'important'),
                ('importance_reason', '原因'),
                ('follow_up_name', '李值班'),
                ('planned_handle_at', '2026-10-07 15:00')):
            payload = make_record_payload(system=self.system.id, **{key: value})
            resp = self.client.post(RECORDS_URL + '/', payload,
                                    content_type='application/json')
            self.assertIn('已删除', resp.json().get('error', ''), key)
        self.assertEqual(SystemRuntimeRecord.objects.count(), 0)

    def test_created_by_user_without_add_perm_rejected(self):
        resp = self.noperm_client.post(
            RECORDS_URL + '/', make_record_payload(system=self.system.id),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(SystemRuntimeRecord.objects.count(), 0)


class SimpleResolveCloseTests(RuntimeRecordTestBase):
    """2. 状态机（四状态收敛）：已记录是登记已完成的合法稳定状态（可长期
    保留，不进待办）；完成跟进 = following_up → completed（已完成，可重新
    跟进）；已记录不能直接完成跟进；旧 close/triage 端点已删除（404）。"""

    def test_complete_follow_up_then_reopen(self):
        """完成跟进入已完成（不要求再关闭），已完成可重新跟进。"""
        data = self.create_record(handling_result='现场已处理')
        record_id = data['id']
        # 已记录追加首条跟进记录进入跟进中 → 完成跟进
        self.start_follow_up(record_id)
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/resolve/',
            {'handling_result': '确认稳定运行'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(resp.json()['data']['status'], 'completed')
        self.assertEqual(resp.json()['data']['status_text'], '已完成')
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'completed')
        self.assertEqual(record.handling_result, '确认稳定运行')
        self.assertFalse(record.needs_follow_up)
        # 首次完成跟进时间落库（统计平均处理时长用）
        self.assertIsNotNone(record.resolved_at)
        # 已完成不能重复完成跟进
        resp = self.client.post(RECORDS_URL + f'/{record_id}/resolve/', {},
                                content_type='application/json')
        self.assertIn('不能重复完成跟进', resp.json().get('error', ''))
        # 已完成不要求关闭：重新跟进 = 追加一条处理进展（follow-up 端点已删除）
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/progress/',
            {'content': '问题复发，重新跟进'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record.refresh_from_db()
        self.assertEqual(record.status, 'following_up')
        self.assertTrue(record.needs_follow_up)

    def test_recorded_cannot_complete_follow_up(self):
        """已记录不能直接完成跟进（留痕记录不经过跟进流程）。"""
        data = self.create_record()
        record_id = data['id']
        resp = self.client.post(RECORDS_URL + f'/{record_id}/resolve/', {},
                                content_type='application/json')
        self.assertIn('完成跟进', resp.json().get('error', ''))
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'recorded')

    def test_legacy_close_triage_and_follow_up_routes_removed(self):
        """旧 close/triage/follow-up 端点已随状态归一与跟进计划退役整体删除：
        路由不存在（404）。"""
        data = self.create_record()
        record_id = data['id']
        for suffix, payload in (
                ('/close/', {'handling_result': '直接关闭'}),
                ('/triage/', {'needs_follow_up': True}),
                ('/follow-up/', {'follow_up_name': '李值班'})):
            resp = self.client.post(
                RECORDS_URL + f'/{record_id}{suffix}', payload,
                content_type='application/json')
            self.assertEqual(resp.status_code, 404, suffix)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'recorded')

    def test_recorded_stable_without_triage(self):
        """已记录是合法稳定状态：不做任何动作即可长期保留，不产生错误或待办。"""
        data = self.create_record()
        record_id = data['id']
        # 详情正常返回，状态保持已记录
        resp = self.client.get(RECORDS_URL + f'/{record_id}/')
        self.assertFalse(resp.json().get('error'), resp.content)
        detail = resp.json()['data']
        self.assertEqual(detail['status'], 'recorded')
        self.assertEqual(detail['status_text'], '已记录')
        # 列表同样以已记录呈现，不进入任何待办口径
        resp = self.client.get(RECORDS_URL + '/', {'status': 'recorded'})
        rows = resp.json()['data']['data']
        self.assertIn(record_id, [r['id'] for r in rows])
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'recorded')

    def test_recorded_cannot_resolve_directly(self):
        """已记录不能直接完成跟进（完成跟进仅针对跟进中的记录）。"""
        data = self.create_record()
        record_id = data['id']
        resp = self.client.post(RECORDS_URL + f'/{record_id}/resolve/', {},
                                content_type='application/json')
        self.assertIn('完成跟进', resp.json().get('error', ''))
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'recorded')

    def test_legacy_statuses_absent_from_state_machine(self):
        """旧状态已随迁移 0007 归一：状态机与合法枚举不再包含旧值。"""
        from apps.equipment_lifecycle.models import (
            RUNTIME_RECORD_STATUS_VALUES,
            RUNTIME_RECORD_TRANSITIONS,
        )
        legacy = ('pending_triage', 'no_follow_up', 'resolved', 'closed')
        for value in legacy:
            self.assertNotIn(value, RUNTIME_RECORD_STATUS_VALUES)
        for source, targets in RUNTIME_RECORD_TRANSITIONS.items():
            self.assertNotIn(source, legacy)
            for value in legacy:
                self.assertNotIn(value, targets,
                                 '状态 %s 不应再允许流转为 %s' % (source, value))

    def test_converted_fault_is_terminal(self):
        """converted_fault 为终态：不允许再次流转，旧研判端点已删除（404）。"""
        data = self.create_record()
        record_id = data['id']
        # 已记录经首条跟进记录进入跟进中，再经独立转换端点转故障
        self.start_follow_up(record_id)
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/convert-to-fault/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(
            SystemRuntimeRecord.objects.get(pk=record_id).status,
            'converted_fault')
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/triage/',
            {'needs_follow_up': False}, content_type='application/json')
        self.assertEqual(resp.status_code, 404)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'converted_fault')


class HistoricalStatusBackfillTests(RuntimeRecordTestBase):
    """16. 旧状态归一（迁移 0007）：数据库 CHECK 约束拒绝旧值写入，状态
    筛选只接受四状态，已完成可重新跟进。"""

    def test_legacy_status_rejected_by_check_constraint(self):
        """旧状态值不在 CHECK 约束合法集合内：直接写库被数据库拒绝。"""
        from django.db import IntegrityError, transaction as db_transaction
        data = self.create_record(
            title='旧状态约束-%s' % uuid.uuid4().hex[:6])
        for legacy in ('pending_triage', 'no_follow_up', 'resolved', 'closed'):
            with self.subTest(status=legacy):
                with self.assertRaises(IntegrityError):
                    with db_transaction.atomic():
                        SystemRuntimeRecord.objects.filter(
                            pk=data['id']).update(status=legacy)
        data = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(data.status, 'recorded')

    def test_status_filter_accepts_only_four_states(self):
        """状态筛选取值为四状态原值；旧状态值被校验拒绝。"""
        recorded = self.create_record(
            title='留痕记录', occurred_at='2026-10-01 08:00')
        self.start_follow_up(recorded['id'])
        completed = self.create_record(
            title='已完成记录', occurred_at='2026-10-01 08:05')
        self.start_follow_up(completed['id'])
        resp = self.client.post(
            RECORDS_URL + f'/{completed["id"]}/resolve/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 跟进中筛选只命中跟进中记录
        resp = self.client.get(RECORDS_URL + '/', {'status': 'following_up'})
        ids = [r['id'] for r in resp.json()['data']['data']]
        self.assertIn(recorded['id'], ids)
        self.assertNotIn(completed['id'], ids)
        # 已完成筛选只命中已完成记录
        resp = self.client.get(RECORDS_URL + '/', {'status': 'completed'})
        ids = [r['id'] for r in resp.json()['data']['data']]
        self.assertIn(completed['id'], ids)
        self.assertNotIn(recorded['id'], ids)
        # 旧状态值不再是合法筛选参数
        for legacy in ('pending_triage', 'no_follow_up', 'resolved', 'closed'):
            resp = self.client.get(RECORDS_URL + '/', {'status': legacy})
            self.assertIn('状态筛选值不合法', resp.json().get('error', ''), legacy)

    def test_completed_can_reopen(self):
        """已完成可重新跟进：追加一条处理进展即重新进入跟进中。"""
        data = self.create_record()
        self.start_follow_up(data['id'])
        resp = self.client.post(
            RECORDS_URL + f'/{data["id"]}/resolve/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        resp = self.client.post(
            RECORDS_URL + f'/{data["id"]}/progress/',
            {'content': '故障复发，重新跟进'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.status, 'following_up')
        self.assertTrue(record.needs_follow_up)

class FollowUpProgressTests(RuntimeRecordTestBase):
    """3. 跟进中的记录可以追加多条处理进展（跟进 = 追加进展，无独立计划）。"""

    def test_follow_up_and_append_progress(self):
        data = self.create_record(needs_follow_up=True)
        record_id = data['id']
        # 新建勾选"需要跟进"只作标记：进入跟进中须追加首条处理进展
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/progress/',
            {'content': '第1次跟进：开始处理', 'handler_name': '值班员甲'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'following_up')
        self.assertTrue(record.needs_follow_up)
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/progress/',
            {'content': '第2次跟进：持续观察', 'handler_name': '值班员甲'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        resp = self.client.get(RECORDS_URL + f'/{record_id}/progress/')
        rows = resp.json()['data']['data']
        self.assertEqual(len(rows), 2)
        self.assertEqual([r['handler_name'] for r in rows], ['值班员甲', '值班员甲'])
        # 已删除字段（处理结果/本次工时）不再出现在进展响应中
        self.assertNotIn('result', rows[0])
        self.assertNotIn('work_hours', rows[0])
        self.assertEqual(
            SystemRuntimeRecordProgress.objects.filter(record_id=record_id).count(), 2)

    def test_retired_progress_params_rejected(self):
        """处理结果/本次工时已删除（2026-10-06）：追加/更正进展携带旧参数
        即拒绝，不静默忽略。"""
        data = self.create_record()
        record_id = data['id']
        for retired in ({'result': '已恢复'}, {'work_hours': 0.5},
                        {'follow_up_name': '李值班'},
                        {'planned_handle_at': '2026-10-07 15:00'}):
            payload = dict({'content': '现场检查'}, **retired)
            resp = self.client.post(
                RECORDS_URL + f'/{record_id}/progress/', payload,
                content_type='application/json')
            self.assertIn('已删除', resp.json().get('error', ''), retired)
        self.assertEqual(
            SystemRuntimeRecordProgress.objects.filter(record_id=record_id).count(), 0)

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
        # 已转故障为终态：经首条跟进记录进入跟进中后转故障
        self.start_follow_up(data['id'])
        resp = self.client.post(
            RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        resp = self.client.post(
            RECORDS_URL + f'/{data["id"]}/progress/',
            {'content': '转故障后补录', 'handler_name': '值班员甲'},
            content_type='application/json')
        self.assertIn('已转故障', resp.json().get('error', ''))


class InfoLayeringTests(RuntimeRecordTestBase):
    """17. 信息分层收敛（2026-10-04）：运行事实/处理过程两类信息各归其位——
    新增表单只提交事实字段；处理进展是处理过程唯一入口且追加式；新数据
    不再写入 已采取措施/处理结果/初步原因/影响范围（历史字段后端列保留，
    历史值不删）；跟进人/计划处理时间（跟进计划）与处理进展的处理结果/
    本次工时已删除（2026-10-06 迁移 0009）；研判快照字段已彻底删除
    （2026-10-07 迁移 0010）。"""

    def test_facts_only_create_leaves_judgement_and_handling_fields_empty(self):
        """只提交事实字段创建：成功即已记录，处理字段全部为空。"""
        data = self.create_record(category='link')
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.status, 'recorded')
        self.assertEqual(record.category, 'link')
        for empty in ('measures_taken', 'handling_result', 'initial_reason',
                      'impact_scope'):
            self.assertEqual(getattr(record, empty), '', empty)
        self.assertFalse(record.needs_follow_up)

    def test_triage_snapshot_fields_absent_from_model_and_detail(self):
        """研判快照字段已彻底删除（2026-10-07 迁移 0010）：模型无字段，
        详情接口不返回 triage 键；旧参数随已删除字段一并拒绝。"""
        data = self.create_record()
        record_id = data['id']
        self.start_follow_up(record_id)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'following_up')
        for field in ('triaged_at', 'triaged_by', 'triaged_by_name', 'triage_note'):
            self.assertFalse(hasattr(record, field), field)
        resp = self.client.get(RECORDS_URL + f'/{record_id}/')
        detail = resp.json()['data']
        for key in ('triaged_at', 'triaged_by_name', 'triage_note'):
            self.assertNotIn(key, detail, key)
        # 请求体携带旧研判参数即拒绝
        resp = self.client.put(
            RECORDS_URL + f'/{record_id}/',
            {'system': self.system.id, 'occurred_at': '2026-10-01 09:00',
             'title': '更新标题', 'description': '更新描述',
             'triage_note': '旧研判说明'},
            content_type='application/json')
        self.assertIn('已删除', resp.json().get('error', ''))
        self.assertEqual(record.measures_taken, '')
        self.assertEqual(record.handling_result, '')
        self.assertEqual(record.initial_reason, '')
        self.assertEqual(record.impact_scope, '')

    def test_progress_append_does_not_overwrite(self):
        """处理进展追加式：多条进展并存互不覆盖，处理过程不写全局处理字段。"""
        data = self.create_record()
        record_id = data['id']
        for content in ('第一次检查：现场确认告警', '第二次处理：更换备件'):
            resp = self.client.post(
                RECORDS_URL + f'/{record_id}/progress/',
                {'content': content, 'handler_name': '值班员甲'},
                content_type='application/json')
            self.assertFalse(resp.json().get('error'), resp.content)
        rows = SystemRuntimeRecordProgress.objects.filter(
            record_id=record_id).order_by('handled_at', 'id')
        self.assertEqual(
            [r.content for r in rows],
            ['第一次检查：现场确认告警', '第二次处理：更换备件'])
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.measures_taken, '')
        self.assertEqual(record.handling_result, '')

    def test_complete_follow_up_without_result_fields(self):
        """完成跟进为纯状态动作：不携带处理字段时进入已完成且不写处理结果
        （最终说明走处理进展，不写入全局结果字段）。"""
        data = self.create_record()
        record_id = data['id']
        self.start_follow_up(record_id)
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/resolve/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'completed')
        self.assertEqual(record.handling_result, '')
        self.assertEqual(record.measures_taken, '')


class ConvertToFaultTests(RuntimeRecordTestBase):
    """5/6. 转为正式故障：一次转换 + 正式外键 + 状态变化。"""

    def test_convert_creates_fault_with_fk(self):
        data = self.create_record()
        record_id = data['id']
        # 转故障为独立动作：已记录可直接转换（不依赖研判，第四版）
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
        # 初始字段由记录带入：系统/标题+描述组装现象；影响属性按故障默认
        # （不影响系统运行；具体对象/影响字段已随记录字段删除不再带入）
        self.assertEqual(fault.system_id, self.system.id)
        self.assertFalse(fault.affects_system_operation)
        self.assertEqual(fault.impact_status, '')
        self.assertIn(record.title, fault.phenomenon)
        self.assertIn(record.description, fault.phenomenon)
        # 记录详情可见关联故障
        resp = self.client.get(RECORDS_URL + f'/{record_id}/')
        self.assertEqual(resp.json()['data']['converted_fault'], fault.id)

    def test_convert_retired_params_rejected(self):
        """转故障请求携带已删除的影响字段旧参数即拒绝（2026-10-06）。"""
        data = self.create_record()
        resp = self.client.post(
            RECORDS_URL + f'/{data["id"]}/convert-to-fault/',
            {'affects_system_operation': True, 'impact_status': 'fault'},
            content_type='application/json')
        self.assertIn('已删除', resp.json().get('error', ''))
        self.assertEqual(SystemFault.objects.count(), 0)

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
        self.assertFalse(resp.json().get('error'), resp.content)
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
    """7/8. 履历规则（2026-10-05 第四版）：运行记录一律不写系统履历——
    普通记录、转为故障均不生成 SystemEvent（历史已写入的事件保留）；
    正式故障的履历由故障服务生成。标记重要端点已随字段删除移除。"""

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

    def test_mark_important_endpoint_removed(self):
        """mark-important 端点已随标记重要字段删除移除（404）。"""
        data = self.create_record()
        record_id = data['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/mark-important/',
            {'importance_reason': '造成业务中断影响值班'},
            content_type='application/json')
        self.assertEqual(resp.status_code, 404)
        self.assert_runtime_events(record_id, [])

    def test_runtime_record_absent_from_event_groups(self):
        """运行记录不进入系统履历事项聚合（第四版退出履历）。

        2026-10-05 起运行记录整体退出履历，聚合中不再出现 runtime_record
        事项（历史已写入的事件仍按原样展示）。
        """
        data = self.create_record(title='仅作留痕的情况',
                                  occurred_at='2026-10-01 08:00')
        record_id = data['id']
        # 履历事项聚合主列表：本系统不出现 runtime_record 事项
        resp = self.viewer_client.get(URL_PREFIX + '/system-event-groups/')
        self.assertFalse(resp.json().get('error'), resp.content)
        items = []
        for group in resp.json()['data']['data']:
            if group['system']['id'] == self.system.id:
                items = group['items']
        runtime_items = [i for i in items if i['source_type'] == 'runtime_record']
        self.assertEqual(runtime_items, [], items)
        self.assertTrue(SystemRuntimeRecord.objects.filter(pk=record_id).exists())

    def test_converted_record_absent_from_event_groups_fault_visible(self):
        """转故障后：运行记录事项不出现在履历聚合，正式故障事项可见。"""
        data = self.create_record(title='转故障后故障进履历',
                                  occurred_at='2026-10-01 08:10')
        self.start_follow_up(data['id'])
        resp = self.client.post(RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assert_runtime_events(data['id'], [])
        resp = self.viewer_client.get(URL_PREFIX + '/system-event-groups/')
        groups = resp.json()['data']['data']
        runtime_items = [
            item for group in groups if group['system']['id'] == self.system.id
            for item in group['items'] if item['source_type'] == 'runtime_record']
        self.assertEqual(runtime_items, [])
        fault_items = [
            item for group in groups if group['system']['id'] == self.system.id
            for item in group['items'] if item['source_type'] == 'fault']
        self.assertEqual(len(fault_items), 1)

    def test_convert_generates_fault_event_only(self):
        data = self.create_record()
        self.start_follow_up(data['id'])
        resp = self.client.post(RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 记录侧不再写履历；故障侧 create 履历（source_type=fault）正常生成
        self.assert_runtime_events(data['id'], [])
        fault = SystemFault.objects.get(
            source_runtime_record_id=data['id'])
        self.assertTrue(SystemEvent.objects.filter(
            source_type='fault', source_id=str(fault.id), action='create').exists())


class TenantAndPermissionTests(RuntimeRecordTestBase):
    """9/10. 租户隔离与权限独立校验。"""

    def test_tenant_isolation(self):
        data = self.create_record()
        # 租户B用户列表看不到租户A记录
        resp = self.other_client.get(RECORDS_URL + '/')
        ids = [r['id'] for r in resp.json()['data']['data']]
        self.assertNotIn(data['id'], ids)
        # 详情/转故障/完成跟进/重新跟进一律拒绝
        resp = self.other_client.get(RECORDS_URL + f'/{data["id"]}/')
        self.assertEqual(resp.json().get('error'), '运行记录不存在')
        resp = self.other_client.post(
            RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
            content_type='application/json')
        self.assertEqual(resp.json().get('error'), '运行记录不存在')
        resp = self.other_client.post(
            RECORDS_URL + f'/{data["id"]}/resolve/', {},
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
            status=SystemRuntimeRecord.STATUS_RECORDED,
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
    """15. 已转故障的运行记录不能继续被普通编辑；编辑未终态记录正常。"""

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
        # 普通编辑不得改变状态：已记录编辑后仍是已记录
        self.assertEqual(record.status, 'recorded')
        # 编辑接口不接收登记人：原登记人保持不变（仅新增可填）
        self.assertEqual(record.registrar_name, data['registrar_name'])

    def test_converted_record_not_editable(self):
        data = self.create_record()
        self.start_follow_up(data['id'])
        self.client.post(RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
                         content_type='application/json')
        resp = self.client.put(
            RECORDS_URL + f'/{data["id"]}/',
            {'system': self.system.id, 'occurred_at': '2026-10-01 09:00',
             'title': '转换后编辑', 'description': '不应生效'},
            content_type='application/json')
        self.assertIn('已转故障', resp.json().get('error', ''))
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.title, data['title'])


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

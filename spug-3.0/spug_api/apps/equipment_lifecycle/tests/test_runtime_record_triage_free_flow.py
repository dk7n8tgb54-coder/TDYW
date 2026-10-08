# -*- coding: utf-8 -*-
"""运行记录第四版流程测试（2026-10-05）：研判不再是必经步骤。

覆盖任务要求的验收场景（HTTP 真实路径 + 数据库副作用，不使用源码字符串匹配）：
1. 新建后状态为"已记录"（recorded），不产生任何研判要求；
2. 新建后无需研判即可离开（详情/列表正常，无待办、无积压口径）；
3. "已记录"可以编辑、开始跟进（保存首条跟进记录）、转为正式故障；
4. 保存第一条跟进记录后进入"跟进中"（following_up）；
5. 跟进记录可以持续追加，状态保持跟进中；
6. "已记录"不进入待办（待办只含跟进中）；
7. 具体对象名称/对象型号/影响系统运行（含影响程度）/标记重要已删除
   （2026-10-06）：创建/编辑携带旧参数即拒绝，mark-important 端点 404；
8. "已记录"可以直接转为正式故障（故障单带入事实字段；影响属性按故障
   默认"不影响系统运行"）；
9. 转故障后运行记录只读（编辑/追加进展/重新跟进全部拒绝，
   mark-important 端点 404）；
10. 历史待研判/无需跟进/已关闭数据可以正常展示（文案归并 + 筛选命中 +
    待办排除 + 按已记录处理可继续流转）。

场景 11（页面不再请求或打开 TriageModal）为前端行为断言，见
spug_web .../runtimeRecord/__tests__（TriageModal 组件文件已删除，
顶部按钮矩阵与请求端点由前端测试套件覆盖）。
"""
import uuid

from django.test import TestCase

from apps.equipment_lifecycle.models import (
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

# important 权限码已随"标记重要"功能删除（2026-10-06），不再参与授权
ALL_RUNTIME_PERMS = [P_VIEW, P_ADD, P_EDIT, P_RESOLVE, P_CONVERT]
FAULT_ADD_PERM = 'equipment_lifecycle.fault.add'

RECORDS_URL = URL_PREFIX + '/runtime-records'


def make_record_payload(**overrides):
    payload = {
        'system': None,
        'occurred_at': '2026-10-05 08:30',
        'title': '主用链路短暂中断',
        'description': '值班发现主用链路丢包，几分钟后自行恢复',
        'registrar_name': '张三',
    }
    payload.update(overrides)
    return payload


class TriageFreeFlowTestBase(TestCase):
    """公共夹具：全权限用户（无需研判权限即可走完新流程）+ 无权限用户。

    用户与系统放 setUpTestData；client 必须在 setUp 中创建——Django 4.2 的
    TestCase.client 是惰性 property，每个测试会重建默认 client。
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user(
            'rt4_admin_%s' % uuid.uuid4().hex[:8],
            ALL_RUNTIME_PERMS + [FAULT_ADD_PERM], tenant_id='tenant_a')
        cls.noperm = make_user(
            'rt4_noperm_%s' % uuid.uuid4().hex[:8], [], tenant_id='tenant_a')
        cls.other_admin = make_user(
            'rt4_other_%s' % uuid.uuid4().hex[:8],
            ALL_RUNTIME_PERMS + [FAULT_ADD_PERM], tenant_id='tenant_b')

    def setUp(self):
        self.client = make_client(self.admin)
        self.noperm_client = make_client(self.noperm)
        self.system = make_system(self.admin, tenant_id='tenant_a',
                                  system_code='RT4-SYS-%s' % uuid.uuid4().hex[:6].upper())
        self.other_system = make_system(
            self.other_admin, tenant_id='tenant_b',
            system_code='RT4-SYS-B-%s' % uuid.uuid4().hex[:6].upper())

    def create_record(self, client=None, system=None, **overrides):
        client = client or self.client
        payload = make_record_payload(
            system=(system or self.system).id, **overrides)
        resp = client.post(RECORDS_URL + '/', payload,
                           content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    def add_progress(self, record_id, content='现场检查，确认恢复', **extra):
        return self.client.post(
            RECORDS_URL + f'/{record_id}/progress/',
            dict({'content': content, 'handler_name': '值班员甲'}, **extra),
            content_type='application/json')


class RecordedWithoutTriageTests(TriageFreeFlowTestBase):
    """场景 1/2/6：新建即已记录，无需研判即可离开，不进入待办。"""

    def test_new_record_is_recorded_without_triage_requirement(self):
        data = self.create_record()
        self.assertEqual(data['status'], 'recorded')
        self.assertEqual(data['status_text'], '已记录')
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.status, 'recorded')
        self.assertFalse(record.needs_follow_up)
        # 研判快照字段已彻底删除（2026-10-07 迁移 0010）
        self.assertFalse(hasattr(record, 'triaged_at'))
        self.assertFalse(hasattr(record, 'triage_note'))

    def test_record_can_be_left_alone_after_create(self):
        """新建后不做任何动作即可离开：详情/列表正常，无待办、无积压计数。"""
        data = self.create_record()
        record_id = data['id']
        resp = self.client.get(RECORDS_URL + f'/{record_id}/')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(resp.json()['data']['status'], 'recorded')
        resp = self.client.get(RECORDS_URL + '/', {'status': 'recorded'})
        self.assertIn(record_id, [r['id'] for r in resp.json()['data']['data']])
        # 待办为空（已记录不进待办）
        resp = self.client.get(RECORDS_URL + '/todo/')
        self.assertEqual(resp.json()['data']['data'], [])
        self.assertEqual(resp.json()['data']['total'], 0)
        # 普通记录不产生履历事件
        self.assertEqual(
            SystemEvent.objects.filter(
                source_type='runtime_record', source_id=str(record_id)).count(), 0)

    def test_recorded_not_in_todo(self):
        """场景 6：已记录（含创建时误标 needs_follow_up）不进入待办，
        保存首条跟进记录后才出现在待办。"""
        plain = self.create_record(title='普通留痕记录')
        flagged = self.create_record(title='误标跟进的记录', needs_follow_up=True)
        resp = self.client.get(RECORDS_URL + '/todo/')
        self.assertEqual(resp.json()['data']['total'], 0)
        # 保存首条跟进记录后进入跟进中 → 待办可见
        resp = self.add_progress(flagged['id'])
        self.assertFalse(resp.json().get('error'), resp.content)
        resp = self.client.get(RECORDS_URL + '/todo/')
        todo_ids = [r['id'] for r in resp.json()['data']['data']]
        self.assertIn(flagged['id'], todo_ids)
        self.assertNotIn(plain['id'], todo_ids)


class FirstProgressTransitionsTests(TriageFreeFlowTestBase):
    """场景 3（开始跟进）/4/5：首条跟进记录触发跟进中，可持续追加。"""

    def test_first_progress_transitions_to_following_up(self):
        data = self.create_record()
        record_id = data['id']
        resp = self.add_progress(record_id, '开始跟进：现场检查')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'following_up')
        self.assertTrue(record.needs_follow_up)
        self.assertEqual(
            SystemRuntimeRecordProgress.objects.filter(record_id=record_id).count(), 1)
        # 详情真实返回跟进中
        resp = self.client.get(RECORDS_URL + f'/{record_id}/')
        self.assertEqual(resp.json()['data']['status'], 'following_up')
        self.assertEqual(resp.json()['data']['status_text'], '跟进中')

    def test_progress_keeps_appending_while_following_up(self):
        data = self.create_record()
        record_id = data['id']
        self.add_progress(record_id, '第一次跟进')
        self.add_progress(record_id, '第二次跟进')
        self.add_progress(record_id, '第三次跟进')
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'following_up')
        rows = SystemRuntimeRecordProgress.objects.filter(
            record_id=record_id).order_by('handled_at', 'id')
        self.assertEqual(
            [r.content for r in rows], ['第一次跟进', '第二次跟进', '第三次跟进'])

    def test_completed_reopens_via_progress_append(self):
        """已完成追加处理进展即重新跟进（completed → following_up）；
        follow-up 端点已随跟进计划删除，追加进展是唯一重新跟进入口。"""
        data = self.create_record()
        record_id = data['id']
        self.add_progress(record_id)
        resp = self.client.post(RECORDS_URL + f'/{record_id}/resolve/', {},
                                content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'completed')
        resp = self.add_progress(record_id, '问题复发，重新跟进')
        self.assertFalse(resp.json().get('error'), resp.content)
        record.refresh_from_db()
        self.assertEqual(record.status, 'following_up')
        self.assertTrue(record.needs_follow_up)


class RetiredFieldsContractTests(TriageFreeFlowTestBase):
    """场景 7/8（2026-10-06 修订）：具体对象名称/对象型号/影响系统运行（含
    影响程度）/标记重要已整体删除——创建/编辑携带旧参数即拒绝，mark-important
    端点不再存在；这些动作与研判是否发生彻底无关。"""

    def test_retired_impact_params_rejected_on_create_and_edit(self):
        # 创建：影响属性旧参数拒绝
        for key, value in (
                ('affects_system_operation', True),
                ('impact_status', 'interrupted'),
                ('object_name', 'DVOR 信标机'),
                ('object_model', 'VR12'),
                ('importance', 'important'),
                ('importance_reason', '影响航班起飞，需上级关注')):
            payload = make_record_payload(system=self.system.id, **{key: value})
            resp = self.client.post(RECORDS_URL + '/', payload,
                                    content_type='application/json')
            self.assertIn('已删除', resp.json().get('error', ''), key)
        self.assertEqual(SystemRuntimeRecord.objects.count(), 0)
        # 编辑：旧参数同样拒绝
        data = self.create_record()
        resp = self.client.put(
            RECORDS_URL + f'/{data["id"]}/',
            make_record_payload(system=self.system.id,
                                affects_system_operation=True),
            content_type='application/json')
        self.assertIn('已删除', resp.json().get('error', ''))
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.status, 'recorded')

    def test_mark_important_endpoint_removed_regardless_of_status(self):
        """mark-important 端点已删除（404）：已记录/跟进中/已转故障均无此入口。"""
        data = self.create_record()
        record_id = data['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/mark-important/',
            {'importance_reason': '影响航班起飞，需上级关注'},
            content_type='application/json')
        self.assertEqual(resp.status_code, 404)
        # 跟进中同样 404
        self.add_progress(record_id)
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/mark-important/',
            {'importance_reason': '重复发生，需专项分析'},
            content_type='application/json')
        self.assertEqual(resp.status_code, 404)


class DirectConvertTests(TriageFreeFlowTestBase):
    """场景 9/10：已记录/跟进中直接转故障；转故障后只读。"""

    def test_recorded_converts_directly_with_fact_fields(self):
        data = self.create_record(
            title='DVOR 信号中断',
            description='主用 DVOR 告警丢波道',
            initial_reason='功放模块疑似故障')
        record_id = data['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/convert-to-fault/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        fault_no = resp.json()['data']['fault_no']
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'converted_fault')
        fault = SystemFault.objects.get(fault_no=fault_no, tenant_id='tenant_a')
        self.assertEqual(fault.source_runtime_record_id, record_id)
        self.assertEqual(fault.source_type, 'runtime_record')
        # 事实字段随转换带入故障单（系统/现象/初步原因）；影响属性按故障
        # 默认"不影响系统运行"（对象名称/型号/影响字段已随记录字段删除）
        self.assertEqual(fault.system_id, self.system.id)
        self.assertFalse(fault.affects_system_operation)
        self.assertEqual(fault.impact_status, '')
        self.assertEqual(fault.reason_analysis, '功放模块疑似故障')
        self.assertIn('DVOR 信号中断', fault.phenomenon)

    def test_following_up_converts_directly(self):
        data = self.create_record()
        self.add_progress(data['id'])
        resp = self.client.post(
            RECORDS_URL + f'/{data["id"]}/convert-to-fault/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.status, 'converted_fault')

    def test_record_read_only_after_convert(self):
        """转故障后运行记录只读：编辑/追加进展/标记重要/重新跟进全部拒绝
        （mark-important 端点已随字段删除移除，直接 404）。"""
        data = self.create_record()
        record_id = data['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/convert-to-fault/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        # 编辑拒绝
        resp = self.client.put(
            RECORDS_URL + f'/{record_id}/',
            make_record_payload(system=self.system.id, title='试图编辑'),
            content_type='application/json')
        self.assertIn('不能编辑', resp.json().get('error', ''))
        # 追加进展拒绝
        resp = self.add_progress(record_id)
        self.assertIn('不能追加处理进展', resp.json().get('error', ''))
        # 标记重要入口已删除（404）
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/mark-important/',
            {'importance_reason': '补标记'}, content_type='application/json')
        self.assertEqual(resp.status_code, 404)
        # 重新跟进端点已随跟进计划删除（404，终态无任何出口）
        resp = self.client.post(RECORDS_URL + f'/{record_id}/follow-up/', {},
                                content_type='application/json')
        self.assertEqual(resp.status_code, 404)
        # 待办不可见；详情返回关联故障
        resp = self.client.get(RECORDS_URL + '/todo/')
        self.assertNotIn(record_id, [r['id'] for r in resp.json()['data']['data']])
        resp = self.client.get(RECORDS_URL + f'/{record_id}/')
        detail = resp.json()['data']
        self.assertEqual(detail['status'], 'converted_fault')
        self.assertEqual(detail['status_text'], '已转故障')
        self.assertTrue(detail['converted_fault'])


class LegacyStatusRetiredTests(TriageFreeFlowTestBase):
    """场景 11（2026-10-06 修订）：旧状态（待研判/无需跟进/已处理/已关闭）
    已由迁移 0007 按语义归一为 recorded/completed，数据库 CHECK 约束拒绝
    旧值写入；状态筛选不再接受旧值。"""

    def test_legacy_statuses_rejected_by_check_constraint(self):
        from django.db import IntegrityError, transaction as db_transaction

        for legacy in ('pending_triage', 'no_follow_up', 'resolved', 'closed'):
            with self.subTest(status=legacy):
                data = self.create_record(title='旧状态拒绝 %s' % legacy)
                with self.assertRaises(IntegrityError):
                    with db_transaction.atomic():
                        SystemRuntimeRecord.objects.filter(
                            pk=data['id']).update(status=legacy)
                record = SystemRuntimeRecord.objects.get(pk=data['id'])
                self.assertEqual(record.status, 'recorded')

    def test_legacy_status_filter_values_rejected(self):
        data = self.create_record()
        for legacy in ('pending_triage', 'no_follow_up', 'resolved', 'closed'):
            resp = self.client.get(RECORDS_URL + '/', {'status': legacy})
            self.assertIn('状态筛选值不合法', resp.json().get('error', ''), legacy)
        # 详情正常返回，记录保持已记录
        resp = self.client.get(RECORDS_URL + f'/{data["id"]}/')
        self.assertEqual(resp.json()['data']['status_text'], '已记录')

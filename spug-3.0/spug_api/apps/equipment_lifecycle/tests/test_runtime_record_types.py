# -*- coding: utf-8 -*-
"""运行记录 record_type（2026-10-07）真实行为测试。

覆盖任务要求的行为断言（HTTP 真实路径 + 数据库副作用，不使用源码字符串匹配）：
1. 新建日常运行记录（routine）：record_type 落库、状态恒为已记录、
   作业内容/操作结果或检查结果写入既有 measures_taken/handling_result 字段；
2. 新建异常事件记录（abnormal）：沿用既有异常字段与流程；
3. 未传 record_type 的旧请求默认按异常事件处理（兼容口径与迁移 0011
   历史回填一致）；
4. 历史记录回填为异常事件：模型 default=abnormal 即迁移回填口径，
   迁移在测试库建库时真实执行（0011/0012 链）；
5. 日常记录不能调用研判/跟进/完成跟进/转故障接口（后端独立校验，
   非前端隐藏）；
6. 异常记录原有状态流转不回归：追加进展 → 跟进中，完成跟进 → 已完成；
7. 列表按记录类型筛选；
8. 权限与租户隔离：删除需要 runtime_record.del 权限；跨租户不可见；
9. 数据库 CHECK 约束拒绝非法 record_type（迁移 0012 真实生效）；
10. 统计接口按记录类型筛选，未传默认 abnormal（原有异常统计口径不变）。
"""
import shutil
import tempfile
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction as db_transaction
from django.test import TestCase, TransactionTestCase, override_settings

from apps.equipment_lifecycle.models import (
    SystemRuntimeRecord,
)
from apps.equipment_lifecycle.tests.base import (
    URL_PREFIX,
    make_client, make_system, make_user,
)
from apps.evidence.models import EvidenceAttachment
from apps.logs.models import AuditLog

P_VIEW = 'equipment_lifecycle.runtime_record.view'
P_ADD = 'equipment_lifecycle.runtime_record.add'
P_EDIT = 'equipment_lifecycle.runtime_record.edit'
P_RESOLVE = 'equipment_lifecycle.runtime_record.resolve'
P_CONVERT = 'equipment_lifecycle.runtime_record.convert_fault'
P_DEL = 'equipment_lifecycle.runtime_record.del'

ALL_RUNTIME_PERMS = [P_VIEW, P_ADD, P_EDIT, P_RESOLVE, P_CONVERT, P_DEL]
FAULT_ADD_PERM = 'equipment_lifecycle.fault.add'

RECORDS_URL = URL_PREFIX + '/runtime-records'


def make_record_payload(**overrides):
    payload = {
        'system': None,
        'occurred_at': '2026-10-06 08:30',
        'title': 'UPS电源切换及南山UPS电池检查紧固',
        'description': '航后按计划完成UPS电源切换与电池检查',
        'registrar_name': '李四',
    }
    payload.update(overrides)
    return payload


class RecordTypeTestBase(TestCase):
    """公共夹具：全权限（含 del）用户 + 双租户（client 须在 setUp 创建）。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user(
            'rtt_admin_%s' % uuid.uuid4().hex[:8],
            ALL_RUNTIME_PERMS + [FAULT_ADD_PERM], tenant_id='tenant_a')
        cls.noperm = make_user(
            'rtt_noperm_%s' % uuid.uuid4().hex[:8], [], tenant_id='tenant_a')
        cls.other_admin = make_user(
            'rtt_other_%s' % uuid.uuid4().hex[:8],
            ALL_RUNTIME_PERMS, tenant_id='tenant_b')

    def setUp(self):
        self.client = make_client(self.admin)
        self.noperm_client = make_client(self.noperm)
        self.other_client = make_client(self.other_admin)
        self.system = make_system(self.admin, tenant_id='tenant_a',
                                  system_code='RTT-SYS-%s' % uuid.uuid4().hex[:6].upper())
        self.other_system = make_system(
            self.other_admin, tenant_id='tenant_b',
            system_code='RTT-SYS-B-%s' % uuid.uuid4().hex[:6].upper())

    def create_record(self, client=None, system=None, **overrides):
        client = client or self.client
        if 'title' not in overrides:
            # 标题缺省加唯一后缀：避开创建窗口期业务查重（同租户/同系统/
            # 同发生时间/同标题 30 秒内视为重复）
            overrides['title'] = make_record_payload()['title'] + uuid.uuid4().hex[:6]
        payload = make_record_payload(
            system=(system or self.system).id, **overrides)
        resp = client.post(RECORDS_URL + '/', payload,
                           content_type='application/json')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        return body['data']

    def get_detail(self, record_id, client=None):
        client = client or self.client
        resp = client.get(RECORDS_URL + f'/{record_id}/')
        self.assertFalse(resp.json().get('error'), resp.content)
        return resp.json()['data']


class RoutineCreateTests(RecordTypeTestBase):
    """1/2/3. 三种创建路径的 record_type 落库与兼容口径。"""

    def test_create_routine_record(self):
        """新建日常运行记录：类型落库、状态已记录、作业内容写入既有字段。"""
        data = self.create_record(
            record_type='routine',
            measures_taken='切换UPS电源并紧固南山UPS电池连接端子',
            handling_result='作业完成，UPS切换正常，电池端子无松动')
        self.assertEqual(data['record_type'], 'routine')
        self.assertEqual(data['record_type_text'], '日常运行')
        self.assertEqual(data['status'], 'recorded')
        self.assertEqual(data['status_text'], '已记录')
        self.assertEqual(data['measures_taken'], '切换UPS电源并紧固南山UPS电池连接端子')
        self.assertEqual(data['handling_result'], '作业完成，UPS切换正常，电池端子无松动')
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.record_type, 'routine')
        self.assertFalse(record.needs_follow_up)

    def test_create_abnormal_record_explicit(self):
        """新建异常事件记录（显式 abnormal）：沿用既有异常字段。"""
        data = self.create_record(
            record_type='abnormal',
            title='120.85主、121.5主、130主电台交流电源故障',
            category='power', initial_reason='交流电源模块故障')
        self.assertEqual(data['record_type'], 'abnormal')
        self.assertEqual(data['record_type_text'], '异常事件')
        self.assertEqual(data['category'], 'power')
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.initial_reason, '交流电源模块故障')

    def test_create_without_record_type_defaults_abnormal(self):
        """旧请求未传 record_type：后端按异常事件兼容处理。"""
        data = self.create_record()
        self.assertEqual(data['record_type'], 'abnormal')
        record = SystemRuntimeRecord.objects.get(pk=data['id'])
        self.assertEqual(record.record_type, 'abnormal')

    def test_create_with_empty_record_type_defaults_abnormal(self):
        data = self.create_record(record_type='')
        self.assertEqual(data['record_type'], 'abnormal')

    def test_create_with_invalid_record_type_rejected(self):
        resp = self.client.post(
            RECORDS_URL + '/',
            make_record_payload(system=self.system.id, record_type='daily'),
            content_type='application/json')
        self.assertEqual(resp.json().get('error'), '记录类型取值不合法')
        self.assertEqual(SystemRuntimeRecord.objects.count(), 0)

    def test_routine_rejects_abnormal_only_fields(self):
        """日常运行记录携带异常专属字段/跟进标记 → 拒绝（后端独立校验）。"""
        cases = [
            {'record_type': 'routine', 'initial_reason': '原因'},
            {'record_type': 'routine', 'impact_scope': '全网'},
            {'record_type': 'routine', 'needs_follow_up': True},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                resp = self.client.post(
                    RECORDS_URL + '/',
                    make_record_payload(system=self.system.id, **payload),
                    content_type='application/json')
                self.assertTrue(resp.json().get('error'), resp.content)
        self.assertEqual(SystemRuntimeRecord.objects.count(), 0)


class RecordTypeListFilterTests(RecordTypeTestBase):
    """7. 列表按记录类型筛选。"""

    def test_list_filter_by_record_type(self):
        routine = self.create_record(record_type='routine', title='日常巡检作业')
        abnormal = self.create_record(
            record_type='abnormal', title='链路中断异常')
        resp = self.client.get(RECORDS_URL + '/', {'record_type': 'routine'})
        self.assertFalse(resp.json().get('error'), resp.content)
        ids = [r['id'] for r in resp.json()['data']['data']]
        self.assertIn(routine['id'], ids)
        self.assertNotIn(abnormal['id'], ids)
        resp = self.client.get(RECORDS_URL + '/', {'record_type': 'abnormal'})
        ids = [r['id'] for r in resp.json()['data']['data']]
        self.assertIn(abnormal['id'], ids)
        self.assertNotIn(routine['id'], ids)
        # 不传筛选：两类都返回；列表行带 record_type 字段
        resp = self.client.get(RECORDS_URL + '/')
        rows = resp.json()['data']['data']
        self.assertEqual({r['record_type'] for r in rows}, {'routine', 'abnormal'})

    def test_list_filter_invalid_record_type_rejected(self):
        resp = self.client.get(RECORDS_URL + '/', {'record_type': 'daily'})
        self.assertEqual(resp.json().get('error'), '记录类型筛选值不合法')

    def test_list_filter_respects_tenant(self):
        routine = self.create_record(record_type='routine')
        resp = self.other_client.get(
            RECORDS_URL + '/', {'record_type': 'routine'})
        ids = [r['id'] for r in resp.json()['data']['data']]
        self.assertNotIn(routine['id'], ids)


class RoutineActionBlockedTests(RecordTypeTestBase):
    """5. 日常记录不能调用跟进/完成跟进/转故障接口（后端独立校验）。"""

    def setUp(self):
        super().setUp()
        self.routine = self.create_record(record_type='routine')

    def test_routine_progress_rejected(self):
        resp = self.client.post(
            RECORDS_URL + f'/{self.routine["id"]}/progress/',
            {'content': '例行巡检记录'}, content_type='application/json')
        self.assertEqual(
            resp.json().get('error'), '日常运行记录不支持追加处理进展')
        record = SystemRuntimeRecord.objects.get(pk=self.routine['id'])
        self.assertEqual(record.status, 'recorded')

    def test_routine_resolve_rejected(self):
        resp = self.client.post(
            RECORDS_URL + f'/{self.routine["id"]}/resolve/', {},
            content_type='application/json')
        self.assertEqual(resp.json().get('error'), '日常运行记录不支持完成跟进')
        record = SystemRuntimeRecord.objects.get(pk=self.routine['id'])
        self.assertEqual(record.status, 'recorded')

    def test_routine_convert_to_fault_rejected(self):
        resp = self.client.post(
            RECORDS_URL + f'/{self.routine["id"]}/convert-to-fault/', {},
            content_type='application/json')
        self.assertEqual(resp.json().get('error'), '日常运行记录不能转为正式故障')
        record = SystemRuntimeRecord.objects.get(pk=self.routine['id'])
        self.assertEqual(record.status, 'recorded')
        self.assertEqual(record.generated_faults.count(), 0)


class AbnormalFlowRegressionTests(RecordTypeTestBase):
    """6. 异常记录原有状态流转不回归。"""

    def test_abnormal_flow_follow_up_and_complete(self):
        abnormal = self.create_record(record_type='abnormal')
        record_id = abnormal['id']
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/progress/',
            {'content': '现场检查电台电源'}, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'following_up')
        resp = self.client.post(
            RECORDS_URL + f'/{record_id}/resolve/', {},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        record = SystemRuntimeRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, 'completed')


class RecordTypeEditTests(RecordTypeTestBase):
    """record_type 创建后不可修改；routine 编辑走既有字段。"""

    def test_put_cannot_change_record_type(self):
        routine = self.create_record(record_type='routine')
        resp = self.client.put(
            RECORDS_URL + f'/{routine["id"]}/',
            make_record_payload(system=self.system.id, record_type='abnormal'),
            content_type='application/json')
        self.assertEqual(resp.json().get('error'), '记录类型创建后不可修改')
        record = SystemRuntimeRecord.objects.get(pk=routine['id'])
        self.assertEqual(record.record_type, 'routine')

    def test_put_without_record_type_keeps_original(self):
        routine = self.create_record(record_type='routine')
        resp = self.client.put(
            RECORDS_URL + f'/{routine["id"]}/',
            make_record_payload(system=self.system.id, title='作业内容更新后标题'),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        data = self.get_detail(routine['id'])
        self.assertEqual(data['record_type'], 'routine')
        self.assertEqual(data['title'], '作业内容更新后标题')

    def test_put_routine_updates_work_fields(self):
        routine = self.create_record(record_type='routine')
        resp = self.client.put(
            RECORDS_URL + f'/{routine["id"]}/',
            make_record_payload(
                system=self.system.id,
                measures_taken='补录： additionally 紧固接地端子',
                handling_result='复查完成'),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.content)
        data = self.get_detail(routine['id'])
        self.assertEqual(data['measures_taken'], '补录： additionally 紧固接地端子')
        self.assertEqual(data['handling_result'], '复查完成')

    def test_put_routine_rejects_abnormal_fields(self):
        routine = self.create_record(record_type='routine')
        resp = self.client.put(
            RECORDS_URL + f'/{routine["id"]}/',
            make_record_payload(system=self.system.id, initial_reason='不应写入'),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'), resp.content)



class RoutineDeleteTests(RecordTypeTestBase):
    """8. 日常运行记录删除：权限与附件清理。"""

    def setUp(self):
        super().setUp()
        storage_dir = tempfile.mkdtemp(prefix='el_rtt_del_')
        override = override_settings(MEDIA_ROOT=storage_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, storage_dir, ignore_errors=True)

    def _upload(self, record_id):
        return self.client.post(
            RECORDS_URL + f'/{record_id}/attachments/',
            {'file': SimpleUploadedFile('作业照片.png', b'\x89PNG-fake-content')})

    def test_delete_routine_record_with_attachments(self):
        routine = self.create_record(record_type='routine')
        resp = self._upload(routine['id'])
        self.assertFalse(resp.json().get('error'), resp.content)
        att_id = resp.json()['data']['id']
        resp = self.client.delete(RECORDS_URL + f'/{routine["id"]}/')
        self.assertFalse(resp.json().get('error'), resp.content)
        self.assertEqual(
            SystemRuntimeRecord.objects.filter(pk=routine['id']).count(), 0)
        # 附件默认管理器过滤已软删记录：用 all_with_deleted 断言软删留痕
        att = EvidenceAttachment.objects.all_with_deleted().get(pk=att_id)
        self.assertTrue(att.is_deleted)
        self.assertEqual(att.delete_reason, '运行记录删除联动清理')
        # 审计留痕
        self.assertTrue(AuditLog.objects.filter(
            target_type='el_runtime_record', action='delete',
            target_id=str(routine['id'])).exists())

    def test_delete_abnormal_record_rejected(self):
        abnormal = self.create_record(record_type='abnormal')
        resp = self.client.delete(RECORDS_URL + f'/{abnormal["id"]}/')
        self.assertEqual(resp.json().get('error'), '仅日常运行记录支持删除')
        self.assertEqual(
            SystemRuntimeRecord.objects.filter(pk=abnormal['id']).count(), 1)

    def test_delete_requires_del_permission(self):
        routine = self.create_record(record_type='routine')
        limited = make_user(
            'rtt_limited_%s' % uuid.uuid4().hex[:8],
            [P_VIEW, P_EDIT], tenant_id='tenant_a')
        resp = make_client(limited).delete(RECORDS_URL + f'/{routine["id"]}/')
        self.assertTrue(resp.json().get('error'), resp.content)
        self.assertEqual(
            SystemRuntimeRecord.objects.filter(pk=routine['id']).count(), 1)

    def test_delete_respects_tenant(self):
        routine = self.create_record(record_type='routine')
        resp = self.other_client.delete(RECORDS_URL + f'/{routine["id"]}/')
        self.assertTrue(resp.json().get('error'), resp.content)
        self.assertEqual(
            SystemRuntimeRecord.objects.filter(pk=routine['id']).count(), 1)


class StatisticsRecordTypeTests(RecordTypeTestBase):
    """10. 统计接口按记录类型筛选；未传默认 abnormal（原异常口径不变）。"""

    def _get_stats(self, params=None):
        resp = self.client.get(RECORDS_URL + '/statistics/', params or {})
        self.assertFalse(resp.json().get('error'), resp.content)
        return resp.json()['data']

    def test_statistics_default_abnormal(self):
        self.create_record(record_type='routine', title='日常作业')
        self.create_record(record_type='abnormal', title='异常事件')
        stats = self._get_stats()
        self.assertEqual(stats['totals']['total'], 1)
        self.assertEqual(stats['record_type'], 'abnormal')

    def test_statistics_filter_routine(self):
        self.create_record(record_type='routine', title='日常作业')
        self.create_record(record_type='routine', title='日常作业二')
        self.create_record(record_type='abnormal', title='异常事件')
        stats = self._get_stats({'record_type': 'routine'})
        self.assertEqual(stats['totals']['total'], 2)
        self.assertEqual(stats['by_status'], {'recorded': 2})

    def test_statistics_respects_tenant(self):
        self.create_record(record_type='routine')
        self.other_client.post(
            RECORDS_URL + '/',
            make_record_payload(system=self.other_system.id, record_type='routine'),
            content_type='application/json')
        stats = self._get_stats({'record_type': 'routine'})
        self.assertEqual(stats['totals']['total'], 1)

    def test_statistics_invalid_record_type_rejected(self):
        resp = self.client.get(
            RECORDS_URL + '/statistics/', {'record_type': 'daily'})
        self.assertEqual(resp.json().get('error'), '记录类型取值不合法')


class RecordTypeCheckConstraintTests(TransactionTestCase):
    """4/9. 迁移真实执行（测试库建库跑 0011-0012 链）+ CHECK 约束生效。"""

    def test_invalid_record_type_rejected_by_check_constraint(self):
        user = make_user(
            'rtt_chk_%s' % uuid.uuid4().hex[:8], [], tenant_id='tenant_a')
        system = make_system(user, tenant_id='tenant_a',
                             system_code='RTT-CHK-%s' % uuid.uuid4().hex[:6].upper())
        record = SystemRuntimeRecord.objects.create(
            tenant_id='tenant_a', record_no='YX20261007-0001',
            system=system, system_code=system.system_code,
            system_name=system.name, system_location=system.install_location,
            occurred_at='2026-10-06 08:00', title='约束测试', description='x',
            registrar_name='张三', created_by=user)
        # 模型 default 即迁移 0011 历史回填口径：直接 ORM 创建未传类型 = abnormal
        self.assertEqual(record.record_type, 'abnormal')
        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                SystemRuntimeRecord.objects.filter(
                    pk=record.pk).update(record_type='daily')
        record.refresh_from_db()
        self.assertEqual(record.record_type, 'abnormal')

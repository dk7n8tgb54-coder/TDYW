# -*- coding: utf-8 -*-
"""运行处置记录——统一处理进展契约测试（2026-10-11 合并改造）。

覆盖真实行为契约（真实 HTTP + 隔离测试数据库 + 数据库状态断言）：
1. 统一进展追加式时间线（处理时间/处理人/处理内容/可选工时/更正历史）；
2. 类型差异：
   - 一般记录允许补充进展但不改变状态（恒为"已记录"，不进故障状态机）；
   - 异常事件首条进展即进入跟进中、已完成追加进展即重新跟进、完成跟进
     resolved_at 首次生效；
   - 设备故障仅处置中可追加（已关闭/已撤销拒绝）；
3. 更正留痕（原内容/新内容/更正原因），无原因拒绝；
4. 主记录级附件上传/列表/删除契约；进展级附件端点已退役（请求 404）；
5. 旧参数（progress_type/result）出现即拒绝。
"""
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.evidence.models import EvidenceAttachment

from apps.equipment_lifecycle.operation_models import (
    SystemOperationProgress,
    SystemOperationRecord,
)
from apps.equipment_lifecycle.tests.base import (
    ALL_OPERATION_PERMS, P_OP_EDIT, P_OP_PROGRESS, P_OP_VIEW, RECORDS_URL,
    make_client, make_record, make_system, make_user,
)


class ProgressAddTest(TestCase):
    """统一进展追加与状态联动契约。"""

    def setUp(self):
        self.user = make_user('progress_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)

    def _add_progress(self, record, **overrides):
        payload = {
            'handled_at': '2026-10-11 10:00',
            'content': '现场检查完成',
            'handler_name': '李四',
        }
        payload.update(overrides)
        return self.client.post(RECORDS_URL + '/%d/progress/' % record.id,
                                json.dumps(payload), content_type='application/json')

    def test_abnormal_first_progress_moves_to_following_up(self):
        record = make_record(self.user, self.system, record_type='abnormal')
        res = self._add_progress(record)
        self.assertFalse(res.json().get('error'), res.json())
        record.refresh_from_db()
        self.assertEqual(record.status, 'following_up')
        self.assertEqual(record.progress_records.count(), 1)
        progress = record.progress_records.first()
        self.assertEqual(progress.handler_name, '李四')
        self.assertEqual(progress.content, '现场检查完成')

    def test_completed_progress_reopens_following_up(self):
        record = make_record(self.user, self.system, record_type='abnormal',
                             status='completed', resolved_at='2026-10-10 10:00:00')
        res = self._add_progress(record)
        self.assertFalse(res.json().get('error'), res.json())
        record.refresh_from_db()
        self.assertEqual(record.status, 'following_up')

    def test_complete_sets_completed_and_first_resolved_at(self):
        record = make_record(self.user, self.system, record_type='abnormal')
        self._add_progress(record)
        res = self.client.post(RECORDS_URL + '/%d/complete/' % record.id, '{}',
                               content_type='application/json')
        self.assertFalse(res.json().get('error'), res.json())
        record.refresh_from_db()
        self.assertEqual(record.status, 'completed')
        first_resolved = record.resolved_at
        self.assertIsNotNone(first_resolved)
        # 重新跟进 → 再次完成：resolved_at 不被覆盖
        self._add_progress(record)
        self.client.post(RECORDS_URL + '/%d/complete/' % record.id, '{}',
                         content_type='application/json')
        record.refresh_from_db()
        self.assertEqual(record.resolved_at, first_resolved)

    def test_complete_recorded_rejected(self):
        record = make_record(self.user, self.system, record_type='abnormal')
        res = self.client.post(RECORDS_URL + '/%d/complete/' % record.id, '{}',
                               content_type='application/json')
        self.assertTrue(res.json().get('error'))
        record.refresh_from_db()
        self.assertEqual(record.status, 'recorded')

    def test_routine_progress_keeps_recorded_status(self):
        """一般记录允许补充进展，但不进入故障/跟进状态机。"""
        record = make_record(self.user, self.system, record_type='routine')
        res = self._add_progress(record, content='作业完成情况补充')
        self.assertFalse(res.json().get('error'), res.json())
        record.refresh_from_db()
        self.assertEqual(record.status, 'recorded')
        self.assertEqual(record.progress_records.count(), 1)

    def test_routine_complete_rejected(self):
        record = make_record(self.user, self.system, record_type='routine')
        res = self.client.post(RECORDS_URL + '/%d/complete/' % record.id, '{}',
                               content_type='application/json')
        self.assertIn('只有异常事件', res.json().get('error', ''))

    def test_routine_identify_rejected(self):
        record = make_record(self.user, self.system, record_type='routine')
        res = self.client.post(RECORDS_URL + '/%d/identify-fault/' % record.id,
                               json.dumps({'affects_system_operation': False}),
                               content_type='application/json')
        self.assertIn('只有异常事件', res.json().get('error', ''))

    def test_fault_handling_accepts_progress_with_work_hours(self):
        record = make_record(self.user, self.system, record_type='fault')
        res = self._add_progress(record, content='更换电源模块', work_hours=2.5)
        self.assertFalse(res.json().get('error'), res.json())
        progress = record.progress_records.first()
        self.assertEqual(progress.work_hours, 2.5)
        record.refresh_from_db()
        self.assertEqual(record.status, 'handling')

    def test_fault_closed_rejects_progress(self):
        record = make_record(self.user, self.system, record_type='fault',
                             status='closed')
        res = self._add_progress(record)
        self.assertIn('不能追加进展', res.json().get('error', ''))

    def test_fault_cancelled_rejects_progress(self):
        record = make_record(self.user, self.system, record_type='fault',
                             status='cancelled')
        res = self._add_progress(record)
        self.assertIn('不能追加进展', res.json().get('error', ''))

    def test_progress_requires_progress_perm(self):
        record = make_record(self.user, self.system, record_type='abnormal')
        user = make_user('no_progress', perms=[P_OP_VIEW, P_OP_EDIT])
        client = make_client(user)
        res = client.post(RECORDS_URL + '/%d/progress/' % record.id,
                          json.dumps({'content': 'x'}),
                          content_type='application/json')
        self.assertIn('权限拒绝', res.json().get('error', ''))

    def test_progress_content_required_and_future_time_rejected(self):
        record = make_record(self.user, self.system, record_type='abnormal')
        res = self._add_progress(record, content='  ')
        self.assertIn('处理内容', res.json().get('error', ''))
        res = self._add_progress(record, handled_at='2030-01-01 10:00')
        self.assertIn('不能晚于当前时间', res.json().get('error', ''))

    def test_retired_progress_params_rejected(self):
        record = make_record(self.user, self.system, record_type='abnormal')
        res = self._add_progress(record, result='旧结果字段')
        self.assertIn('不再支持参数', res.json().get('error', ''))

    def test_progress_timeline_order(self):
        record = make_record(self.user, self.system, record_type='abnormal')
        self._add_progress(record, handled_at='2026-10-11 10:00', content='第一条')
        self._add_progress(record, handled_at='2026-10-11 09:00', content='更早一条')
        res = self.client.get(RECORDS_URL + '/%d/progress/' % record.id)
        body = res.json()['data']
        self.assertEqual(
            [row['content'] for row in body['data']], ['更早一条', '第一条'])
        self.assertEqual(body['total'], 2)


class ProgressCorrectTest(TestCase):
    """统一进展更正契约（更正原因必填、原内容留痕）。"""

    def setUp(self):
        self.user = make_user('correct_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.record = make_record(self.user, self.system, record_type='abnormal')
        self.progress = SystemOperationProgress.objects.create(
            tenant_id=self.record.tenant_id, record=self.record,
            handled_at='2026-10-11 09:00:00', handler=self.user,
            handler_name='李四', content='原始内容',
            work_hours=1.0)

    def _correct(self, **overrides):
        payload = {
            'content': '更正后的内容',
            'correction_reason': '录入有误',
        }
        payload.update(overrides)
        for key, value in list(payload.items()):
            if value is None:
                payload.pop(key)
        return self.client.put(
            RECORDS_URL + '/%d/progress/%d/' % (self.record.id, self.progress.id),
            json.dumps(payload), content_type='application/json')

    def test_correction_keeps_history(self):
        res = self._correct(handler_name='王五', work_hours=2.0,
                            handled_at='2026-10-11 09:30')
        self.assertFalse(res.json().get('error'), res.json())
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.content, '更正后的内容')
        self.assertEqual(self.progress.handler_name, '王五')
        self.assertEqual(self.progress.work_hours, 2.0)
        corrections = self.progress.get_corrections()
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]['old'], '原始内容')
        self.assertEqual(corrections[0]['new'], '更正后的内容')
        self.assertEqual(corrections[0]['reason'], '录入有误')

    def test_correction_without_reason_rejected(self):
        res = self._correct(correction_reason='  ')
        self.assertIn('更正原因', res.json().get('error', ''))
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.content, '原始内容')

    def test_correction_requires_edit_perm(self):
        user = make_user('no_edit_correct', perms=[P_OP_VIEW, P_OP_PROGRESS])
        client = make_client(user)
        res = client.put(
            RECORDS_URL + '/%d/progress/%d/' % (self.record.id, self.progress.id),
            json.dumps({'content': 'x', 'correction_reason': 'y'}),
            content_type='application/json')
        self.assertIn('权限拒绝', res.json().get('error', ''))

    def test_correction_cross_record_rejected(self):
        other = make_record(self.user, self.system, record_type='abnormal',
                            title='另一条')
        res = self.client.put(
            RECORDS_URL + '/%d/progress/%d/' % (other.id, self.progress.id),
            json.dumps({'content': 'x', 'correction_reason': 'y'}),
            content_type='application/json')
        self.assertIn('不存在', res.json().get('error', ''))


class RecordAttachmentTest(TestCase):
    """主记录级附件契约（进展级附件已于 2026-10-13 退役，端点与路由已删）。"""

    def setUp(self):
        self.user = make_user('att_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.record = make_record(self.user, self.system, record_type='abnormal')

    def test_progress_attachment_routes_retired(self):
        """进展级附件端点已整体下线：任何请求返回 404，不存在可用入口。"""
        res = self.client.get(
            RECORDS_URL + '/%d/progress/%d/attachments/' % (self.record.id, 1))
        self.assertEqual(res.status_code, 404)
        res = self.client.post(
            RECORDS_URL + '/%d/progress/%d/attachments/' % (self.record.id, 1),
            {'file': SimpleUploadedFile('a.txt', b'x')})
        self.assertEqual(res.status_code, 404)

    def test_record_level_attachment_crud(self):
        """主记录级附件：三类记录均可上传；删除走记录附件路由。"""
        res = self.client.post(
            RECORDS_URL + '/%d/attachments/' % self.record.id,
            {'file': SimpleUploadedFile('rec.txt', b'record file')})
        self.assertFalse(res.json().get('error'), res.json())
        att = res.json()['data']
        self.assertTrue(EvidenceAttachment.objects.filter(
            pk=att['id'], object_type='el_operation_record',
            object_id=str(self.record.id)).exists())
        # 列表（裸数组契约，同 contract/interference 附件列表）
        res = self.client.get(RECORDS_URL + '/%d/attachments/' % self.record.id)
        rows = res.json()['data']
        self.assertIsInstance(rows, list)
        self.assertEqual([row['file_name'] for row in rows], ['rec.txt'])
        # 删除
        res = self.client.delete(RECORDS_URL + '/%d/attachments/%d/' % (
            self.record.id, att['id']))
        self.assertFalse(res.json().get('error'), res.json())
        # 默认 Manager 过滤软删行：全量查询断言软删落库
        self.assertTrue(EvidenceAttachment.objects.all_with_deleted().filter(
            pk=att['id'], is_deleted=True).exists())

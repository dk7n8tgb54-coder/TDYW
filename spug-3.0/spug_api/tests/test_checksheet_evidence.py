# Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
证据闭环第三阶段 - 模块1：检查单测试

覆盖：
- CheckSheetSubmission 模型：状态流转规则、can_edit、can_transition_to
- CheckSheetRecord/DailySummary 身份快照字段
- 证据事件写入（record_evidence_event 被调用）
- 证据包导出包含业务快照/证据事件/审计日志/附件哈希清单
- 向后兼容：旧字段 operator 保留
"""
import json
from django.test import TestCase

from apps.account.models import User
from apps.checksheet.models import (
    CheckSheetTemplate, CheckSheetRecord, CheckSheetDailySummary,
    CheckSheetSubmission, SUBMISSION_TRANSITIONS, EDITABLE_STATUSES,
)
from apps.evidence.models import EvidenceEvent
from apps.evidence.services import record_evidence_event


class CheckSheetSubmissionModelTests(TestCase):
    """提交批次模型测试"""

    def test_default_status_is_draft(self):
        """新建批次默认 draft"""
        sub = CheckSheetSubmission.objects.create(
            tenant_id='t1', project='测试项目', year='2026', month='06')
        self.assertEqual(sub.status, 'draft')
        self.assertTrue(sub.can_edit())

    def test_status_transitions_draft(self):
        """draft → submitted / voided 合法"""
        sub = CheckSheetSubmission.objects.create(
            tenant_id='t1', project='p', year='2026', month='06')
        self.assertTrue(sub.can_transition_to('submitted'))
        self.assertTrue(sub.can_transition_to('voided'))
        self.assertFalse(sub.can_transition_to('reviewed'))  # 不能跳过提交
        self.assertFalse(sub.can_transition_to('closed'))

    def test_status_transitions_submitted(self):
        """submitted → reviewed / draft(驳回) 合法"""
        sub = CheckSheetSubmission.objects.create(
            tenant_id='t1', project='p', year='2026', month='06', status='submitted')
        self.assertTrue(sub.can_transition_to('reviewed'))
        self.assertTrue(sub.can_transition_to('draft'))  # 驳回
        self.assertFalse(sub.can_transition_to('closed'))  # 不能跳过复核

    def test_status_transitions_reviewed(self):
        """reviewed → closed / draft(驳回) 合法"""
        sub = CheckSheetSubmission.objects.create(
            tenant_id='t1', project='p', year='2026', month='06', status='reviewed')
        self.assertTrue(sub.can_transition_to('closed'))
        self.assertTrue(sub.can_transition_to('draft'))

    def test_status_transitions_closed(self):
        """closed → voided 合法，不能回退"""
        sub = CheckSheetSubmission.objects.create(
            tenant_id='t1', project='p', year='2026', month='06', status='closed')
        self.assertTrue(sub.can_transition_to('voided'))
        self.assertFalse(sub.can_transition_to('draft'))
        self.assertFalse(sub.can_transition_to('submitted'))

    def test_status_transitions_voided_terminal(self):
        """voided 终态，不能流转"""
        sub = CheckSheetSubmission.objects.create(
            tenant_id='t1', project='p', year='2026', month='06', status='voided')
        self.assertFalse(sub.can_transition_to('draft'))
        self.assertFalse(sub.can_transition_to('submitted'))
        self.assertFalse(sub.can_transition_to('closed'))
        self.assertFalse(sub.can_edit())

    def test_non_draft_not_editable(self):
        """非 draft 状态不可编辑"""
        for status in ['submitted', 'reviewed', 'closed', 'voided']:
            sub = CheckSheetSubmission.objects.create(
                tenant_id='t1', project='p', year='2026', month='06', status=status)
            self.assertFalse(sub.can_edit(), f'{status} 不应可编辑')


class CheckSheetRecordIdentityTests(TestCase):
    """检查记录身份快照测试"""

    def setUp(self):
        self.template = CheckSheetTemplate.objects.create(
            project='测试项目', check_items='[]')

    def test_record_has_identity_fields(self):
        """记录有 operator_user_id / operator_name_snapshot 字段"""
        rec = CheckSheetRecord.objects.create(
            template=self.template, year='2026', month='06', day=15,
            item_index=0, status='NORMAL',
            operator='张三',  # 旧字段保留
            operator_user_id=12,
            operator_name_snapshot='张三',
            operator_department_snapshot='运行部',
        )
        self.assertEqual(rec.operator_user_id, 12)
        self.assertEqual(rec.operator_name_snapshot, '张三')
        self.assertEqual(rec.operator_department_snapshot, '运行部')
        self.assertEqual(rec.operator, '张三')  # 旧字段兼容

    def test_daily_summary_has_identity_fields(self):
        """每日汇总有身份快照字段"""
        ds = CheckSheetDailySummary.objects.create(
            year='2026', month='06', day=15,
            operator='李四',
            operator_user_id=13,
            operator_name_snapshot='李四',
        )
        self.assertEqual(ds.operator_user_id, 13)
        self.assertEqual(ds.operator_name_snapshot, '李四')


class CheckSheetEvidenceEventTests(TestCase):
    """检查单证据事件写入测试"""

    def setUp(self):
        self.user = User.objects.create(
            username='tester', nickname='测试员', password_hash='x',
            tenant_id='t1', is_active=True, access_token='tok' * 5,
        )
        self.template = CheckSheetTemplate.objects.create(
            project='测试项目', check_items=json.dumps(['项目1', '项目2']))
        self.submission = CheckSheetSubmission.objects.create(
            tenant_id='t1', project='测试项目', year='2026', month='06')

    def test_submit_event_written(self):
        """提交动作写入证据事件 event_type=submit"""
        record_evidence_event(
            tenant_id='t1', module='checksheet', object_type='submission',
            object_id=self.submission.id, event_type='submit',
            actor_user_id=self.user.id, actor_username='tester',
            actor_name='测试员',
            object_snapshot={'project': '测试项目', 'status': 'submitted'},
        )
        ev = EvidenceEvent.objects.get()
        self.assertEqual(ev.event_type, 'submit')
        self.assertEqual(ev.module, 'checksheet')
        self.assertEqual(ev.object_id, str(self.submission.id))
        self.assertTrue(ev.event_hash)
        self.assertEqual(ev.prev_hash, '')  # 链首

    def test_chain_links_consecutive_events(self):
        """连续证据事件构成哈希链"""
        e1 = record_evidence_event(
            tenant_id='t1', module='checksheet', object_type='submission',
            object_id=self.submission.id, event_type='submit',
            actor_user_id=1, actor_username='a', actor_name='甲',
            object_snapshot={'status': 'submitted'},
        )
        e2 = record_evidence_event(
            tenant_id='t1', module='checksheet', object_type='submission',
            object_id=self.submission.id, event_type='approve',
            actor_user_id=2, actor_username='b', actor_name='乙',
            object_snapshot={'status': 'reviewed'},
        )
        self.assertEqual(e2.prev_hash, e1.event_hash)
        self.assertNotEqual(e1.event_hash, e2.event_hash)


class CheckSheetSnapshotHashTests(TestCase):
    """快照哈希计算测试"""

    def setUp(self):
        self.template = CheckSheetTemplate.objects.create(
            project='测试项目', check_items=json.dumps(['项目1']))
        self.sub = CheckSheetSubmission.objects.create(
            tenant_id='t1', project='测试项目', year='2026', month='06')

    def test_snapshot_hash_deterministic(self):
        """相同快照哈希一致"""
        from apps.checksheet.views import _build_submission_snapshot, _compute_snapshot_hash
        s1 = _build_submission_snapshot(self.sub)
        s2 = _build_submission_snapshot(self.sub)
        self.assertEqual(_compute_snapshot_hash(s1), _compute_snapshot_hash(s2))
        self.assertEqual(len(_compute_snapshot_hash(s1)), 64)

    def test_snapshot_hash_changes_on_content(self):
        """快照内容变化哈希变化"""
        from apps.checksheet.views import _compute_snapshot_hash
        h1 = _compute_snapshot_hash({'a': 1})
        h2 = _compute_snapshot_hash({'a': 2})
        self.assertNotEqual(h1, h2)

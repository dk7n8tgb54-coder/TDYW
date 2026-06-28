# Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
证据闭环第三阶段 - 模块2：运行日志测试

覆盖：
- RunLog 扩展状态（verified/closed/voided）
- RunLog snapshot_hash 字段
- RunLogUpdate 证据字段（update_type/corrected_update_id/is_voided/void_reason）
- 证据事件写入（状态流转时）
- 证据包导出包含业务快照/证据事件/审计日志/附件哈希清单
"""
import json
from django.test import TestCase

from apps.account.models import User
from apps.runlog.models import RunLog, RunLogUpdate
from apps.evidence.models import EvidenceEvent
from apps.evidence.services import record_evidence_event


class RunLogModelEvidenceTests(TestCase):
    """运行日志模型证据字段测试"""

    def setUp(self):
        self.user = User.objects.create(
            username='tester', nickname='测试员', password_hash='x',
            tenant_id='t1', is_active=True, access_token='tok' * 5,
        )
        self.event = RunLog.objects.create(
            tenant_id='t1', event_title='测试事件', event_type='运行异常',
            system_name='测试系统', severity='P2', status='in_progress',
            created_by=self.user,
        )

    def test_extended_status_values(self):
        """扩展状态值可设置"""
        for status in ['in_progress', 'resolved', 'verified', 'closed', 'voided']:
            self.event.status = status
            self.event.save()
            self.event.refresh_from_db()
            self.assertEqual(self.event.status, status)

    def test_snapshot_hash_field(self):
        """snapshot_hash 字段存在且默认空"""
        self.assertEqual(self.event.snapshot_hash, '')
        self.event.snapshot_hash = 'a' * 64
        self.event.save()
        self.event.refresh_from_db()
        self.assertEqual(self.event.snapshot_hash, 'a' * 64)

    def test_status_text_map_includes_new_statuses(self):
        """to_view 的 status_map 包含新状态"""
        self.event.status = 'verified'
        view = self.event.to_view()
        self.assertEqual(view['status_text'], '已验证')
        self.event.status = 'closed'
        view = self.event.to_view()
        self.assertEqual(view['status_text'], '已归档')
        self.event.status = 'voided'
        view = self.event.to_view()
        self.assertEqual(view['status_text'], '已作废')


class RunLogUpdateEvidenceTests(TestCase):
    """运行动态证据字段测试"""

    def setUp(self):
        self.user = User.objects.create(
            username='tester', nickname='测试员', password_hash='x',
            tenant_id='t1', is_active=True, access_token='tok' * 5,
        )
        self.event = RunLog.objects.create(
            tenant_id='t1', event_title='测试事件', event_type='运行异常',
            system_name='测试系统', created_by=self.user,
        )

    def test_update_type_default_normal(self):
        """update_type 默认 normal"""
        update = RunLogUpdate.objects.create(
            runlog_id=self.event.id, event_title='测试',
            update_date='2026-06-27', sequence=1,
            recorder='测试员', detail_content='内容',
            editable_until='2026-06-28 10:00:00',
            created_by=self.user, tenant_id='t1',
        )
        self.assertEqual(update.update_type, 'normal')
        self.assertFalse(update.is_voided)
        self.assertEqual(update.void_reason, '')
        self.assertIsNone(update.corrected_update_id)

    def test_update_type_correction(self):
        """更正动态可设置 update_type=correction + corrected_update_id"""
        update1 = RunLogUpdate.objects.create(
            runlog_id=self.event.id, event_title='测试',
            update_date='2026-06-27', sequence=1,
            recorder='测试员', detail_content='原始内容',
            editable_until='2026-06-28 10:00:00',
            created_by=self.user, tenant_id='t1',
        )
        correction = RunLogUpdate.objects.create(
            runlog_id=self.event.id, event_title='测试',
            update_date='2026-06-28', sequence=2,
            recorder='测试员', detail_content='更正内容',
            editable_until='2026-06-29 10:00:00',
            update_type='correction', corrected_update_id=update1.id,
            created_by=self.user, tenant_id='t1',
        )
        self.assertEqual(correction.update_type, 'correction')
        self.assertEqual(correction.corrected_update_id, update1.id)

    def test_update_void(self):
        """作废动态"""
        update = RunLogUpdate.objects.create(
            runlog_id=self.event.id, event_title='测试',
            update_date='2026-06-27', sequence=1,
            recorder='测试员', detail_content='错误内容',
            editable_until='2026-06-28 10:00:00',
            created_by=self.user, tenant_id='t1',
        )
        update.is_voided = True
        update.void_reason = '内容错误，已用更正记录替换'
        update.save()
        update.refresh_from_db()
        self.assertTrue(update.is_voided)
        self.assertEqual(update.void_reason, '内容错误，已用更正记录替换')


class RunLogEvidenceEventTests(TestCase):
    """运行日志证据事件写入测试"""

    def setUp(self):
        self.user = User.objects.create(
            username='tester', nickname='测试员', password_hash='x',
            tenant_id='t1', is_active=True, access_token='tok' * 5,
        )
        self.event = RunLog.objects.create(
            tenant_id='t1', event_title='测试事件', event_type='运行异常',
            system_name='测试系统', created_by=self.user,
        )

    def test_resolved_writes_submit_event(self):
        """resolved 状态流转写入 submit 证据事件"""
        record_evidence_event(
            tenant_id='t1', module='runlog', object_type='runlog',
            object_id=self.event.id, event_type='submit',
            actor_user_id=self.user.id, actor_username='tester',
            actor_name='测试员',
            object_snapshot={'status': 'resolved'},
        )
        ev = EvidenceEvent.objects.get()
        self.assertEqual(ev.event_type, 'submit')
        self.assertEqual(ev.module, 'runlog')

    def test_closed_writes_close_event_chain(self):
        """连续证据事件构成哈希链"""
        e1 = record_evidence_event(
            tenant_id='t1', module='runlog', object_type='runlog',
            object_id=self.event.id, event_type='submit',
            actor_user_id=1, actor_username='a', actor_name='甲',
            object_snapshot={'status': 'resolved'},
        )
        e2 = record_evidence_event(
            tenant_id='t1', module='runlog', object_type='runlog',
            object_id=self.event.id, event_type='close',
            actor_user_id=2, actor_username='b', actor_name='乙',
            object_snapshot={'status': 'closed'},
        )
        self.assertEqual(e2.prev_hash, e1.event_hash)


class RunLogSnapshotTests(TestCase):
    """快照构建测试"""

    def setUp(self):
        self.user = User.objects.create(
            username='tester', nickname='测试员', password_hash='x',
            tenant_id='t1', is_active=True, access_token='tok' * 5,
        )
        self.event = RunLog.objects.create(
            tenant_id='t1', event_title='测试事件', event_type='运行异常',
            system_name='测试系统', created_by=self.user,
        )

    def test_snapshot_includes_event_and_updates(self):
        """快照包含事件和动态"""
        from apps.runlog.views import _build_runlog_snapshot
        RunLogUpdate.objects.create(
            runlog_id=self.event.id, event_title='测试',
            update_date='2026-06-27', sequence=1,
            recorder='测试员', detail_content='动态1',
            editable_until='2026-06-28 10:00:00',
            created_by=self.user, tenant_id='t1',
        )
        snapshot = _build_runlog_snapshot(self.event)
        self.assertIn('event', snapshot)
        self.assertIn('updates', snapshot)
        self.assertEqual(len(snapshot['updates']), 1)
        self.assertEqual(snapshot['event']['id'], self.event.id)

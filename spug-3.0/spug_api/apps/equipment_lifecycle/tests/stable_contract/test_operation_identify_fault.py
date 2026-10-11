# -*- coding: utf-8 -*-
"""运行与故障记录——异常事件原记录认定正式故障契约测试（2026-10-11）。

覆盖真实行为契约（真实 HTTP + 隔离测试数据库 + 数据库状态断言）：
1. 认定后仍是同一条记录（主键不变），不创建第二张单；
2. 记录类型 abnormal → fault、状态 → 处置中，故障所需字段补充生效；
3. 原描述、登记人、附件与全部进展原样保留（含进展附件归属不变）；
4. 认定触发系统健康状态重算（影响运行时生效）；
5. 校验：日常运行/已完成/已是正式故障拒绝认定；影响运行时影响程度必填。
"""
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.evidence.models import EvidenceAttachment

from apps.equipment_lifecycle.models import LifecycleSystem
from apps.equipment_lifecycle.operation_models import (
    SystemOperationProgress,
    SystemOperationRecord,
)
from apps.evidence.attachment_service import AttachmentService
from apps.equipment_lifecycle.tests.base import (
    ALL_OPERATION_PERMS, P_OP_EDIT, P_OP_IDENTIFY_FAULT, P_OP_VIEW, RECORDS_URL,
    make_client, make_record, make_system, make_user,
)


def _identify_url(pk):
    return RECORDS_URL + '/%d/identify-fault/' % pk


class IdentifyFaultTest(TestCase):
    """异常事件认定正式故障契约。"""

    def setUp(self):
        self.user = make_user('identify_user', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)
        self.record = make_record(
            self.user, self.system, record_type='abnormal',
            title='信号异常', description='16:00 发现 DVOR 监视信号波动。',
            registrar_name='李四')
        # 预置：两条进展 + 记录级附件 + 进展级附件
        self.progress_a = SystemOperationProgress.objects.create(
            tenant_id=self.record.tenant_id, record=self.record,
            handled_at='2026-10-11 09:00:00', handler=self.user,
            handler_name='李四', content='初步排查，未定位')
        self.progress_b = SystemOperationProgress.objects.create(
            tenant_id=self.record.tenant_id, record=self.record,
            handled_at='2026-10-11 10:00:00', handler=self.user,
            handler_name='王五', content='波动持续，升级观察')
        att, error = AttachmentService.upload(
            SimpleUploadedFile('log.txt', b'raw log content'),
            self.user, 'equipment_lifecycle', 'el_operation_record',
            self.record.id, owner_tenant_id=self.record.tenant_id)
        assert not error, error
        self.record_attachment = att
        att2, error = AttachmentService.upload(
            SimpleUploadedFile('shot.png', b'png-bytes'),
            self.user, 'equipment_lifecycle', 'el_operation_progress',
            self.progress_a.id, owner_tenant_id=self.record.tenant_id)
        assert not error, error
        self.progress_attachment = att2

    def _identify(self, **overrides):
        payload = {
            'affects_system_operation': True,
            'impact_status': 'fault',
            'reason_analysis': '天馈系统驻波比异常',
            'fault_object_name': '天馈系统',
        }
        payload.update(overrides)
        return self.client.post(_identify_url(self.record.id),
                                json.dumps(payload), content_type='application/json')

    def test_identify_updates_same_record(self):
        res = self._identify()
        data = res.json()['data']
        self.assertFalse(res.json().get('error'), res.json())
        # 同一条记录：主键不变
        self.assertEqual(data['id'], self.record.id)
        self.assertEqual(SystemOperationRecord.objects.count(), 1)
        record = SystemOperationRecord.objects.get(pk=self.record.id)
        self.assertEqual(record.record_type, 'fault')
        self.assertEqual(record.status, 'handling')
        self.assertEqual(record.impact_status, 'fault')
        self.assertTrue(record.affects_system_operation)
        self.assertEqual(record.reason_analysis, '天馈系统驻波比异常')
        self.assertEqual(record.fault_object_name, '天馈系统')
        # 编号不可变（不换发新编号）
        self.assertEqual(record.record_no, self.record.record_no)

    def test_identify_preserves_description_registrar_progress_attachments(self):
        self._identify()
        record = SystemOperationRecord.objects.get(pk=self.record.id)
        # 原描述与登记人保留
        self.assertEqual(record.description, '16:00 发现 DVOR 监视信号波动。')
        self.assertEqual(record.registrar_name, '李四')
        # 全部进展保留（数量与内容）
        progress = list(record.progress_records.order_by('handled_at'))
        self.assertEqual(len(progress), 2)
        self.assertEqual(progress[0].content, '初步排查，未定位')
        self.assertEqual(progress[1].content, '波动持续，升级观察')
        # 记录级与进展级附件归属不变、未删除
        self.assertTrue(EvidenceAttachment.objects.filter(
            pk=self.record_attachment.id, is_deleted=False,
            object_id=str(record.id)).exists())
        self.assertTrue(EvidenceAttachment.objects.filter(
            pk=self.progress_attachment.id, is_deleted=False,
            object_id=str(self.progress_a.id)).exists())

    def test_identify_triggers_health_recompute(self):
        self.system.refresh_from_db()
        self.assertEqual(self.system.health_status, 'normal')
        self._identify()
        self.system.refresh_from_db()
        self.assertEqual(self.system.health_status, 'fault')

    def test_identify_not_affecting_keeps_health_normal(self):
        res = self._identify(affects_system_operation=False, impact_status='')
        self.assertFalse(res.json().get('error'), res.json())
        self.system.refresh_from_db()
        self.assertEqual(self.system.health_status, 'normal')
        record = SystemOperationRecord.objects.get(pk=self.record.id)
        self.assertFalse(record.affects_system_operation)
        self.assertEqual(record.impact_status, '')

    def test_identify_without_impact_rejected(self):
        res = self._identify(impact_status='')
        self.assertIn('影响程度', res.json().get('error', ''))
        self.record.refresh_from_db()
        self.assertEqual(self.record.record_type, 'abnormal')

    def test_routine_cannot_be_identified(self):
        routine = make_record(self.user, self.system, record_type='routine')
        res = self.client.post(_identify_url(routine.id),
                               json.dumps({'affects_system_operation': False}),
                               content_type='application/json')
        self.assertIn('只有异常事件', res.json().get('error', ''))
        routine.refresh_from_db()
        self.assertEqual(routine.record_type, 'routine')

    def test_completed_abnormal_cannot_be_identified(self):
        SystemOperationRecord.objects.filter(pk=self.record.id).update(
            status='completed', resolved_at='2026-10-11 11:00:00')
        res = self._identify()
        self.assertIn('不能认定', res.json().get('error', ''))
        self.record.refresh_from_db()
        self.assertEqual(self.record.record_type, 'abnormal')

    def test_already_fault_cannot_be_identified_again(self):
        self._identify()
        res = self._identify()
        self.assertIn('只有异常事件', res.json().get('error', ''))

    def test_identify_requires_permission(self):
        user = make_user('no_identify', perms=[P_OP_VIEW, P_OP_EDIT])
        client = make_client(user)
        res = client.post(_identify_url(self.record.id),
                          json.dumps({'affects_system_operation': False}),
                          content_type='application/json')
        self.assertIn('权限拒绝', res.json().get('error', ''))
        self.record.refresh_from_db()
        self.assertEqual(self.record.record_type, 'abnormal')

    def test_identify_cross_tenant_rejected(self):
        other_user = make_user('t2_identify', perms=ALL_OPERATION_PERMS,
                               tenant_id='tenant_2')
        client = make_client(other_user)
        res = client.post(_identify_url(self.record.id),
                          json.dumps({'affects_system_operation': False}),
                          content_type='application/json')
        self.assertIn('不存在', res.json().get('error', ''))

    def test_identify_occurred_at_override(self):
        res = self._identify(occurred_at='2026-10-11 07:30')
        self.assertFalse(res.json().get('error'), res.json())
        record = SystemOperationRecord.objects.get(pk=self.record.id)
        self.assertEqual(str(record.occurred_at), '2026-10-11 07:30:00')

    def test_identify_after_first_progress_still_works(self):
        """跟进中的异常事件同样可直接认定（recorded/following_up 均可）。"""
        self.client.post(RECORDS_URL + '/%d/progress/' % self.record.id,
                         json.dumps({'content': '继续观察'}),
                         content_type='application/json')
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'following_up')
        res = self._identify()
        self.assertFalse(res.json().get('error'), res.json())
        record = SystemOperationRecord.objects.get(pk=self.record.id)
        self.assertEqual(record.record_type, 'fault')
        self.assertEqual(record.status, 'handling')
        # 认定前的进展完整保留
        self.assertEqual(record.progress_records.count(), 3)

    def test_db_constraint_enforces_type_status_match(self):
        """DB CHECK 兜底：类型与状态非法组合被数据库拒绝。"""
        from django.db import IntegrityError, connection
        with connection.cursor() as cursor:
            with self.assertRaises(Exception):
                cursor.execute(
                    "UPDATE tdyw_el_operation_record SET record_type='routine', "
                    "status='handling' WHERE id=%s", [self.record.id])

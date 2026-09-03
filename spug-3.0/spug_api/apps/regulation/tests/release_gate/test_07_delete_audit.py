"""R-07 附件删除、规章删除、审计与事务副作用。

覆盖用户要求：
- 删除附件后 is_deleted / deleted_by / deleted_at 正确更新
- 删除后的附件不出现在列表、下载、预览接口
- 物理删除失败时必须有日志或待清理机制，不能静默丢失状态
- 删除规章时验证所有关联附件的数据库记录和物理文件处理
- 重复删除已删除附件、删除不存在附件、删除其他规章附件必须安全失败
- 审计事件包含操作者、目标规章、操作类型、必要附件信息，不含敏感 token
- on_commit 清理逻辑不会在事务回滚前误删物理文件
"""
import os
from unittest.mock import patch

from apps.regulation.models import Regulation, RegulationAttachment
from .base import RegulationGateTestCase, RegulationGateTransactionTestCase


class AttachmentSoftDeleteTests(RegulationGateTestCase):
    """R-07-01 附件软删除字段与可见性"""

    def setUp(self):
        super().setUp()
        self.att = self.make_attachment_record(self.regulation, 'sd.pdf', b'sd-body')

    def test_soft_delete_updates_fields(self):
        resp = self.admin_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/')
        self.assertEqual(resp.json()['error'], '')
        self.att.refresh_from_db()
        self.assertTrue(self.att.is_deleted)
        self.assertEqual(self.att.deleted_by_id, self.admin.id)
        self.assertIsNotNone(self.att.deleted_at)

    def test_deleted_attachment_hidden_from_list(self):
        self.admin_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/')
        resp = self.viewer_client.get(f'/regulation/{self.regulation.id}/attachments/')
        self.assertEqual(resp.json()['data'], [])

    def test_deleted_attachment_hidden_from_detail(self):
        self.admin_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/')
        resp = self.viewer_client.get(f'/regulation/{self.regulation.id}/')
        self.assertEqual(resp.json()['data']['attachments'], [])

    def test_deleted_attachment_not_downloadable(self):
        self.admin_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/')
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/download/')
        self.assertEqual(resp.json()['error'], '附件不存在')

    def test_deleted_attachment_not_previewable(self):
        self.admin_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/')
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/preview-url/')
        self.assertEqual(resp.json()['error'], '附件不存在')

    def test_delete_attachment_audit_event_recorded(self):
        self.admin_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/')
        from apps.logs.models import AuditLog
        log = AuditLog.objects.filter(
            target_type='regulation', action='delete_attachment',
            target_id=str(self.regulation.id)).first()
        self.assertIsNotNone(log, '删除附件应产生 delete_attachment 审计事件')
        self.assertIn(str(self.att.id), log.detail)
        self.assertNotIn('preview_token', (log.detail or '').lower())

    def test_repeat_delete_fails_safely(self):
        first = self.admin_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/')
        second = self.admin_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/')
        self.assertEqual(first.json()['error'], '')
        self.assertEqual(second.json()['error'], '附件不存在')
        self.assertEqual(second.status_code, 200, '重复删除不得 500')

    def test_delete_nonexistent_attachment_fails_safely(self):
        resp = self.admin_client.delete(
            f'/regulation/{self.regulation.id}/attachments/999999/')
        self.assertEqual(resp.json()['error'], '附件不存在')

    def test_delete_other_regulation_attachment_fails_safely(self):
        other = self.make_attachment_record(self.regulation2, 'other.pdf', b'other')
        resp = self.admin_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{other.id}/')
        self.assertEqual(resp.json()['error'], '附件不存在')
        other.refresh_from_db()
        self.assertFalse(other.is_deleted)

    def test_delete_requires_upload_permission(self):
        resp = self.editor_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.att.refresh_from_db()
        self.assertFalse(self.att.is_deleted)

    def test_delete_attachment_of_nonexistent_regulation(self):
        resp = self.admin_client.delete('/regulation/999999/attachments/1/')
        self.assertEqual(resp.json()['error'], '规章不存在')


class AttachmentPhysicalCleanupTests(RegulationGateTransactionTestCase):
    """R-07-02 物理文件清理（需要真实事务提交以触发 on_commit）"""

    def test_physical_file_removed_after_commit(self):
        att = self.make_attachment_record(self.regulation, 'pc.pdf', b'pc-body')
        abs_path = os.path.join(self._tmp_storage, att.file_path)
        self.assertTrue(os.path.exists(abs_path))
        resp = self.admin_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{att.id}/')
        self.assertEqual(resp.json()['error'], '')
        self.assertFalse(os.path.exists(abs_path), '事务提交后物理文件应被删除')

    def test_rollback_preserves_physical_file(self):
        att = self.make_attachment_record(self.regulation, 'rb.pdf', b'rb-body')
        abs_path = os.path.join(self._tmp_storage, att.file_path)
        with patch('apps.regulation.views.record_audit_event',
                   side_effect=Exception('模拟审计写入失败')):
            self.admin_client.delete(
                f'/regulation/{self.regulation.id}/attachments/{att.id}/')
        att.refresh_from_db()
        self.assertFalse(att.is_deleted, '事务回滚后 is_deleted 应为 False')
        self.assertTrue(os.path.exists(abs_path), '回滚后物理文件必须保留')

    def test_physical_delete_failure_does_not_break_soft_delete(self):
        """物理删除失败：软删除状态已落库，仅记录日志，无待清理重试机制"""
        att = self.make_attachment_record(self.regulation, 'pd.pdf', b'pd-body')
        abs_path = os.path.join(self._tmp_storage, att.file_path)
        with patch('apps.regulation.storage.safe_delete_attachment_file',
                   return_value=(False, '模拟删除失败')) as mocked:
            resp = self.admin_client.delete(
                f'/regulation/{self.regulation.id}/attachments/{att.id}/')
        self.assertEqual(resp.json()['error'], '', '物理删除失败不应导致接口报错')
        att.refresh_from_db()
        self.assertTrue(att.is_deleted, '软删除状态必须落库')
        self.assertTrue(mocked.called)
        self.assertTrue(os.path.exists(abs_path), '物理文件删除失败后仍残留')
        self.assertNotIn('is_pending_clean',
                         {f.name for f in RegulationAttachment._meta.get_fields()},
                         '规章附件无 is_pending_clean 待清理重试机制')


class RegulationDeleteCascadeTests(RegulationGateTransactionTestCase):
    """R-07-03 删除规章的级联与物理文件处理"""

    def test_delete_cascades_attachment_records_and_files(self):
        a1 = self.make_attachment_record(self.regulation, 'c1.pdf', b'c1')
        a2 = self.make_attachment_record(self.regulation, 'c2.pdf', b'c2')
        p1 = os.path.join(self._tmp_storage, a1.file_path)
        p2 = os.path.join(self._tmp_storage, a2.file_path)
        resp = self.admin_client.delete(f'/regulation/{self.regulation.id}/')
        self.assertEqual(resp.json()['error'], '')
        self.assertFalse(RegulationAttachment.objects.filter(
            regulation_id=self.regulation.id).exists())
        self.assertFalse(os.path.exists(p1), '规章删除后附件物理文件应被清理')
        self.assertFalse(os.path.exists(p2))

    def test_delete_does_not_touch_other_regulation_files(self):
        keep = self.make_attachment_record(self.regulation2, 'keep.pdf', b'keep')
        self.make_attachment_record(self.regulation, 'gone.pdf', b'gone')
        keep_path = os.path.join(self._tmp_storage, keep.file_path)
        self.admin_client.delete(f'/regulation/{self.regulation.id}/')
        self.assertTrue(os.path.exists(keep_path), '其他规章的附件必须不受影响')
        self.assertTrue(RegulationAttachment.objects.filter(pk=keep.pk).exists())

    def test_delete_rollback_preserves_files(self):
        att = self.make_attachment_record(self.regulation, 'rb2.pdf', b'rb2')
        abs_path = os.path.join(self._tmp_storage, att.file_path)
        with patch('apps.regulation.models.Regulation.delete',
                   side_effect=Exception('模拟删除失败')):
            self.admin_client.delete(f'/regulation/{self.regulation.id}/')
        self.assertTrue(Regulation.objects.filter(pk=self.regulation.id).exists())
        self.assertTrue(os.path.exists(abs_path), '回滚后物理文件必须保留')

    def test_soft_deleted_attachments_are_cascade_removed(self):
        att = self.make_attachment_record(self.regulation, 'sdc.pdf', b'sdc')
        RegulationAttachment.objects.filter(pk=att.pk).update(is_deleted=True)
        resp = self.admin_client.delete(f'/regulation/{self.regulation.id}/')
        self.assertEqual(resp.json()['error'], '')
        self.assertFalse(RegulationAttachment.objects.filter(pk=att.pk).exists())


class AuditEventIntegrityTests(RegulationGateTestCase):
    """R-07-04 审计事件完整性与脱敏

    ⚠️ 已知缺陷（REG-AUDIT-001，P1）：
    规章模块的 retire / upload_attachment / download_attachment / delete_attachment
    四类业务审计事件，因 action 取值不在 AuditLog 的 DB CHECK 约束
    audit_action_valid 白名单内，写入被数据库拒绝后由 save_audit_log 静默吞掉，
    仅落 error 日志 + 告警，主流程不失败 -> 审计事件 100% 丢失。
    以下相关用例为 defect_reproduction，断言指向期望的正确行为（修复前失败）。
    """

    def test_create_update_retire_delete_all_audited(self):
        from apps.logs.models import AuditLog
        reg_id = self.regulation.id
        self.admin_client.put(f'/regulation/{reg_id}/', {'title': '审计改名'},
                              content_type='application/json')
        self.admin_client.post(f'/regulation/{reg_id}/retire/')
        self.admin_client.delete(f'/regulation/{reg_id}/')
        actions = set(AuditLog.objects.filter(
            target_type='regulation', target_id=str(reg_id)
        ).values_list('action', flat=True))
        for expected in ('update', 'retire', 'delete'):
            self.assertIn(expected, actions, f'应产生 {expected} 审计事件')

    def test_audit_records_operator_and_target(self):
        from apps.logs.models import AuditLog
        self.admin_client.post(f'/regulation/{self.regulation.id}/retire/')
        log = AuditLog.objects.filter(
            target_type='regulation', action='retire',
            target_id=str(self.regulation.id)).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.username, self.admin.username)
        self.assertEqual(log.user_id, self.admin.id)
        self.assertEqual(log.target_name, '基准规章')
        self.assertTrue(log.is_success)

    def test_audit_detail_has_no_sensitive_token(self):
        from apps.logs.models import AuditLog
        att = self.make_attachment_record(self.regulation, 'sens.pdf', b'x')
        self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{att.id}/preview-url/')
        self.admin_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{att.id}/')
        for log in AuditLog.objects.filter(target_type='regulation'):
            detail = (log.detail or '').lower()
            self.assertNotIn('preview_token', detail)
            self.assertNotIn('access_token', detail)
            self.assertNotIn('x-token', detail)

    def test_audit_action_values_outside_declared_choices(self):
        """retire / upload_attachment 等 action 不在 AuditLog.ACTION_CHOICES 内"""
        from apps.logs.models import AuditLog
        self.admin_client.post(f'/regulation/{self.regulation.id}/retire/')
        log = AuditLog.objects.filter(action='retire').first()
        self.assertIsNotNone(log)
        declared = {code for code, _label in AuditLog.ACTION_CHOICES}
        self.assertNotIn('retire', declared,
                         'retire 未声明在 ACTION_CHOICES 中，审计筛选下拉无法枚举')

    def test_sensitive_keyword_sanitizer_masks_tokens(self):
        from apps.logs.audit import sanitize_audit_detail
        sanitized = sanitize_audit_detail(
            {'attachment_id': 1, 'preview_token': 'secret-value', 'file_name': 'a.pdf'})
        self.assertNotIn('secret-value', str(sanitized))
        self.assertIn('attachment_id', sanitized)


class AuditActionConstraintRootCauseTests(RegulationGateTestCase):
    """REG-AUDIT-001 根因证据：DB CHECK 约束拒绝规章模块的自定义 action

    通过真实数据库写入证明根因，而非读取源码。
    """

    CUSTOM_ACTIONS = (
        'retire', 'upload_attachment', 'download_attachment', 'delete_attachment',
    )

    def test_custom_actions_violate_db_check_constraint(self):
        from django.db import DatabaseError, transaction
        from apps.logs.models import AuditLog
        for action in self.CUSTOM_ACTIONS:
            with self.assertRaises(DatabaseError, msg=f'{action} 应被 CHECK 约束拒绝'):
                with transaction.atomic():
                    AuditLog.objects.create(
                        user_id=self.admin.id, username=self.admin.username,
                        action=action, target_type='regulation', target_id='1',
                        target_name='t', detail='', ip='127.0.0.1',
                        tenant_id='default')

    def test_whitelisted_actions_are_persisted(self):
        from apps.logs.models import AuditLog
        for action in ('create', 'update', 'delete'):
            AuditLog.objects.create(
                user_id=self.admin.id, username=self.admin.username,
                action=action, target_type='regulation', target_id='1',
                target_name='t', detail='', ip='127.0.0.1', tenant_id='default')
        self.assertEqual(AuditLog.objects.filter(target_name='t').count(), 3)

    def test_save_audit_log_swallows_constraint_error(self):
        """save_audit_log 捕获异常后静默返回：调用方无感知，主流程继续成功"""
        from apps.logs.audit import save_audit_log
        save_audit_log(
            user_id=self.admin.id, username=self.admin.username,
            action='retire', target_type='regulation', target_id='1',
            target_name='should-be-lost', tenant_id='default')
        from apps.logs.models import AuditLog
        self.assertFalse(
            AuditLog.objects.filter(target_name='should-be-lost').exists(),
            '根因确认：非法 action 的审计事件被静默丢弃，主流程不感知')

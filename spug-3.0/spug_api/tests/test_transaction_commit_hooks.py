# -*- coding: utf-8 -*-
"""Regression tests for filesystem and Celery work deferred until commit."""
from types import SimpleNamespace
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase

from apps.evidence.attachment_service import AttachmentService
from apps.evidence.models import EvidenceAttachment
from apps.utils.test_helpers import make_user


class TransactionCommitHookTest(TestCase):
    def setUp(self):
        self.user = make_user('commit_hook_user', is_supper=True)

    def _make_attachment(self):
        return EvidenceAttachment.objects.create(
            tenant_id=self.user.tenant_id,
            module='radio_license',
            object_type='license',
            object_id='1',
            file_name='proof.pdf',
            file_path='/media/proof.pdf',
            file_hash_sha256='a' * 64,
            uploaded_by_id=self.user.id,
            uploaded_by_name=self.user.nickname,
        )

    def test_attachment_file_removal_runs_after_commit(self):
        attachment = self._make_attachment()
        with patch.object(AttachmentService, '_remove_physical_file', return_value=None) as remove:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                error = AttachmentService.soft_delete(
                    self.user, attachment.id, reason='测试删除', delete_file=True,
                )
                self.assertIsNone(error)
                remove.assert_not_called()

            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
            remove.assert_called_once()

    def test_attachment_file_removal_is_discarded_on_rollback(self):
        attachment = self._make_attachment()
        with patch.object(AttachmentService, '_remove_physical_file', return_value=None) as remove:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                try:
                    with transaction.atomic():
                        AttachmentService.soft_delete(
                            self.user, attachment.id, reason='回滚测试', delete_file=True,
                        )
                        raise RuntimeError('force rollback')
                except RuntimeError:
                    pass

            self.assertEqual(callbacks, [])
            remove.assert_not_called()
            attachment.refresh_from_db()
            self.assertFalse(attachment.is_deleted)

    def test_merge_task_dispatch_runs_after_commit(self):
        from apps.document.views.upload import merge as merge_view

        params = {
            'file_hash': 'b' * 32,
            'file_name': 'archive.bin',
            'file_size': 10,
            'total_chunks': 1,
            'folder_id': None,
            'is_public': False,
            'transfer_id': 999,
            'system_folder': '',
        }
        names = {
            'file_path': '/tmp/archive.bin',
            'physical_name': 'archive.bin',
            'logical_name': 'archive.bin',
            'display_name': 'archive.bin',
        }
        request = SimpleNamespace(user=self.user)

        with patch.object(merge_view, 'get_merge_task_file_path', return_value='/tmp/merge-task.json'), \
                patch.object(merge_view.os, 'makedirs'), \
                patch.object(merge_view.merge_file_chunks, 'AsyncResult', return_value=SimpleNamespace(id='task-id')), \
                patch.object(merge_view.merge_file_chunks, 'apply_async') as apply_async:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                with transaction.atomic():
                    merge_view.submit_merge_task(
                        params, names, '/tmp/chunks', self.user.tenant_id, request,
                    )
                    apply_async.assert_not_called()

            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
            apply_async.assert_called_once()

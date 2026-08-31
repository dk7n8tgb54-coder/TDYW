# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""协作任务到期附件清理任务测试

覆盖：到期已完成任务的附件文件与记录清理、任务/交付记录保留、幂等重跑、
进行中与近期完成任务不受影响、已作废与已删除任务的清理。
"""
import os
import tempfile
from datetime import timedelta

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from apps.evidence.models import EvidenceAttachment

from apps.coop_task.models import CoopTask, CoopTaskDelivery
from apps.coop_task.tasks import cleanup_expired_task_attachments
from apps.coop_task.tests.test_coop_task import CoopTaskFlowTestsBase


def _backdate(**kwargs):
    """把 now 往前推（按关键字天数/小时构造过去时间点）"""
    return timezone.now() - timedelta(**kwargs)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), COOP_TASK_FILE_RETENTION_DAYS=365)
class CleanupTaskTests(CoopTaskFlowTestsBase):
    """到期任务附件清理"""

    def _upload(self, delivery_id, filename='总结.pdf'):
        file = SimpleUploadedFile(filename, b'%PDF-1.4 data')
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{delivery_id}/attachments/', {'file': file})
        self.assertFalse(resp.json().get('error'), resp.json())

    def _create_completed_with_files(self):
        """创建一个全部验收完成的任务（两份材料各带一个附件），返回 (task_id, delivery_ids)"""
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        task_id = data['id']
        assignment_id = CoopTaskDelivery.objects.filter(
            assignment__task_id=task_id).first().assignment_id
        deliveries = list(CoopTaskDelivery.objects.filter(assignment_id=assignment_id))
        for delivery in deliveries:
            self._upload(delivery.id)
            self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
        for delivery in deliveries:
            resp = self.initiator_client.post(f'/coop-task/deliveries/{delivery.id}/accept/')
            self.assertFalse(resp.json().get('error'), resp.json())
        task = CoopTask.objects.get(pk=task_id)
        self.assertEqual(task.status, 'completed')
        return task_id, [d.id for d in deliveries]

    def test_expired_completed_task_files_cleaned(self):
        """到期已完成任务：附件文件与记录物理清理，任务/交付记录保留，重跑幂等"""
        task_id, delivery_ids = self._create_completed_with_files()
        attachments = list(EvidenceAttachment.objects.filter(
            module='coop_task', object_type='delivery'))
        self.assertEqual(len(attachments), 2)
        file_paths = [os.path.join(settings.MEDIA_ROOT, a.file_path) for a in attachments]
        for path in file_paths:
            self.assertTrue(os.path.exists(path))

        # 回溯完成时间至保留期之外并触发清理
        CoopTask.objects.filter(pk=task_id).update(completed_at=_backdate(days=400))
        result = cleanup_expired_task_attachments()
        self.assertEqual(result['expired_tasks'], 1)
        self.assertEqual(result['deleted'], 2)
        self.assertEqual(result['failed'], 0)
        # 附件记录与物理文件均已移除
        self.assertFalse(EvidenceAttachment.objects.filter(
            module='coop_task', object_type='delivery').exists())
        for path in file_paths:
            self.assertFalse(os.path.exists(path))
        # 任务/交付明细记录保留
        self.assertTrue(CoopTask.objects.filter(pk=task_id).exists())
        self.assertTrue(CoopTaskDelivery.objects.filter(id__in=delivery_ids).exists())
        # 幂等：重复运行无副作用
        result = cleanup_expired_task_attachments()
        self.assertEqual(result['expired_tasks'], 1)
        self.assertEqual(result['deleted'], 0)

    def test_recent_and_in_progress_untouched(self):
        """进行中任务与保留期内完成任务不受清理影响"""
        # 进行中任务带附件
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        ongoing_id = data['id']
        delivery_id = CoopTaskDelivery.objects.filter(
            assignment__task_id=ongoing_id).first().id
        self._upload(delivery_id)
        # 刚完成的任务带附件
        recent_id, _ = self._create_completed_with_files()
        CoopTask.objects.filter(pk=recent_id).update(completed_at=_backdate(days=10))

        result = cleanup_expired_task_attachments()
        self.assertEqual(result['expired_tasks'], 0)
        self.assertEqual(result['deleted'], 0)
        # 进行中 1 个 + 刚完成 2 个，全部保留
        self.assertEqual(EvidenceAttachment.objects.filter(
            module='coop_task', object_type='delivery').count(), 3)

    def test_voided_task_cleaned_after_retention(self):
        """已作废任务到期后附件清理"""
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        task_id = data['id']
        delivery_id = CoopTaskDelivery.objects.filter(
            assignment__task_id=task_id).first().id
        self._upload(delivery_id)
        resp = self.initiator_client.post(f'/coop-task/tasks/{task_id}/void/')
        self.assertFalse(resp.json().get('error'), resp.json())
        CoopTask.objects.filter(pk=task_id).update(updated_at=_backdate(days=400))

        result = cleanup_expired_task_attachments()
        self.assertEqual(result['deleted'], 1)
        self.assertFalse(EvidenceAttachment.objects.filter(
            module='coop_task', object_type='delivery').exists())

    def test_deleted_task_cleaned_after_retention(self):
        """已删除任务到期后附件清理"""
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        task_id = data['id']
        delivery_id = CoopTaskDelivery.objects.filter(
            assignment__task_id=task_id).first().id
        self._upload(delivery_id)
        resp = self.initiator_client.delete(f'/coop-task/tasks/{task_id}/')
        self.assertFalse(resp.json().get('error'), resp.json())
        CoopTask.objects.all_with_deleted().filter(pk=task_id).update(
            deleted_at=_backdate(days=400))

        result = cleanup_expired_task_attachments()
        self.assertEqual(result['expired_tasks'], 1)
        self.assertEqual(result['deleted'], 1)
        self.assertFalse(EvidenceAttachment.objects.filter(
            module='coop_task', object_type='delivery').exists())

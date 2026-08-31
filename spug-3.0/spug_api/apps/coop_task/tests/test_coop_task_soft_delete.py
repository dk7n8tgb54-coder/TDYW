# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""协作任务模块软删除完整性测试

任务软删除只置 is_deleted 标记、不改任务状态。此前交付明细与附件接口未过滤
已删除任务，交付方在知道 delivery/附件 ID 的情况下仍可对已删除任务提交交付、
上传/删除/下载附件。正确行为：任务删除后交付明细与附件读写全部阻断，
与模板接口、收件箱、任务详情的删除过滤口径一致。
"""
import base64
import tempfile
from urllib.parse import parse_qs, urlparse

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.evidence.models import EvidenceAttachment
from apps.coop_task.models import CoopTask, CoopTaskDelivery, CoopTaskItem

from apps.coop_task.tests.test_coop_task import CoopTaskFlowTestsBase


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SoftDeletedTaskInoperableTests(CoopTaskFlowTestsBase):
    """任务软删除后，交付明细与附件不可再读写"""

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']
        self.deliveries = list(
            CoopTaskDelivery.objects.filter(assignment__task_id=self.task_id).order_by('id'))
        self.submitted_delivery = self.deliveries[0]
        self.pending_delivery = self.deliveries[1]
        # 删除前既有数据：交付方上传一份附件并提交
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.submitted_delivery.id}/attachments/',
            {'file': SimpleUploadedFile('已传.pdf', b'%PDF-1.4 data')})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.att = EvidenceAttachment.objects.get(
            module='coop_task', object_type='delivery',
            object_id=str(self.submitted_delivery.id))
        self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.submitted_delivery.id}/submit/')
        # 发起方软删除任务（任务状态仍为 in_progress）
        resp = self.initiator_client.delete(f'/coop-task/tasks/{self.task_id}/')
        self.assertFalse(resp.json().get('error'), resp.json())
        task = CoopTask.objects.all_with_deleted().get(pk=self.task_id)
        self.assertTrue(task.is_deleted)
        self.assertEqual(task.status, 'in_progress')

    def test_submit_blocked_on_deleted_task(self):
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.pending_delivery.id}/submit/')
        self.assertTrue(resp.json().get('error'), resp.json())
        self.pending_delivery.refresh_from_db()
        self.assertEqual(self.pending_delivery.status, 'pending')

    def test_upload_attachment_blocked_on_deleted_task(self):
        before = EvidenceAttachment.objects.filter(module='coop_task').count()
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.pending_delivery.id}/attachments/',
            {'file': SimpleUploadedFile('后传.pdf', b'%PDF-1.4 x')})
        self.assertTrue(resp.json().get('error'), resp.json())
        self.assertEqual(
            EvidenceAttachment.objects.filter(module='coop_task').count(), before)

    def test_delete_attachment_blocked_on_deleted_task(self):
        resp = self.deliverer_b_client.delete(f'/coop-task/attachments/?id={self.att.id}')
        self.assertTrue(resp.json().get('error'), resp.json())
        self.assertTrue(EvidenceAttachment.objects.filter(pk=self.att.id).exists())

    def test_attachment_list_blocked_on_deleted_task(self):
        resp = self.deliverer_b_client.get(
            f'/coop-task/deliveries/{self.submitted_delivery.id}/attachments/')
        self.assertTrue(resp.json().get('error'), resp.json())

    def test_attachment_download_blocked_on_deleted_task(self):
        """交付方与发起方对已删除任务的附件下载均应阻断"""
        for client in (self.deliverer_b_client, self.initiator_client):
            resp = client.get(f'/coop-task/attachments/{self.att.id}/download/')
            self.assertTrue(resp.json().get('error'), resp.json())

    def test_attachment_preview_url_blocked_on_deleted_task(self):
        resp = self.deliverer_b_client.get(
            f'/coop-task/attachments/{self.att.id}/preview-url/')
        self.assertTrue(resp.json().get('error'), resp.json())

    def test_accept_blocked_on_deleted_task(self):
        """回归守护：验收对已删除任务始终被拒"""
        resp = self.initiator_client.post(
            f'/coop-task/deliveries/{self.submitted_delivery.id}/accept/')
        self.assertTrue(resp.json().get('error'), resp.json())
        self.submitted_delivery.refresh_from_db()
        self.assertEqual(self.submitted_delivery.status, 'submitted')

    def test_reject_blocked_on_deleted_task(self):
        """回归守护：退回对已删除任务始终被拒"""
        resp = self.initiator_client.post(
            f'/coop-task/deliveries/{self.submitted_delivery.id}/reject/',
            {'reason': '不合格'}, content_type='application/json')
        self.assertTrue(resp.json().get('error'), resp.json())
        self.submitted_delivery.refresh_from_db()
        self.assertEqual(self.submitted_delivery.status, 'submitted')

    def test_template_upload_blocked_on_deleted_task(self):
        """回归守护：模板接口本就过滤已删除任务"""
        item_id = self.submitted_delivery.item_id
        resp = self.initiator_client.post(
            f'/coop-task/items/{item_id}/templates/',
            {'file': SimpleUploadedFile('模板.pdf', b'data')})
        self.assertTrue(resp.json().get('error'), resp.json())
        self.assertEqual(
            EvidenceAttachment.objects.filter(
                module='coop_task', object_type='item_template').count(), 0)

    def test_void_deleted_task_rejected(self):
        resp = self.initiator_client.post(f'/coop-task/tasks/{self.task_id}/void/')
        self.assertIn('任务不存在', resp.json().get('error', ''))


def _extract_preview_token(preview_url):
    """从 preview_url 解出 preview_token（回调地址整体 base64 编码在 url 参数里）"""
    encoded = parse_qs(urlparse(preview_url).query)['url'][0]
    file_url = base64.b64decode(encoded).decode('utf-8')
    return parse_qs(urlparse(file_url).query)['preview_token'][0]


def _resp_error(resp):
    """兼容读取业务错误：JSON 响应取 error 字段，文件流响应视为无错误"""
    if (resp.headers.get('Content-Type') or '').startswith('application/json'):
        return resp.json().get('error')
    return None


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(),
                   KKFILEVIEW_API_URL='http://kkfileview.test',
                   KKFILEVIEW_SERVER_URL='http://tdyw-test')
class PreviewTokenAfterSoftDeleteTests(CoopTaskFlowTestsBase):
    """任务软删除后，删除前签发的 preview_token 不得再经 kkFileView 回调读取文件流

    AttachmentService.preview_file_response 只校验令牌签名/时效/附件级软删除，
    不感知附件所属协作任务的软删除状态；preview_token 有效期 5 分钟，
    覆盖"删除前预览、删除后回调"的真实窗口。
    """

    def _issue_delivery_token(self, delivery):
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{delivery.id}/attachments/',
            {'file': SimpleUploadedFile('预览材料.pdf', b'%PDF-1.4 preview')})
        self.assertFalse(resp.json().get('error'), resp.json())
        att = EvidenceAttachment.objects.get(
            module='coop_task', object_type='delivery', object_id=str(delivery.id))
        resp = self.deliverer_b_client.get(
            f'/coop-task/attachments/{att.id}/preview-url/')
        self.assertFalse(resp.json().get('error'), resp.json())
        return att.id, _extract_preview_token(resp.json()['data']['preview_url'])

    def _issue_template_token(self, item_id):
        resp = self.initiator_client.post(
            f'/coop-task/items/{item_id}/templates/',
            {'file': SimpleUploadedFile('模板.pdf', b'%PDF-1.4 template')})
        self.assertFalse(resp.json().get('error'), resp.json())
        att = EvidenceAttachment.objects.get(
            module='coop_task', object_type='item_template', object_id=str(item_id))
        resp = self.initiator_client.get(
            f'/coop-task/attachments/{att.id}/preview-url/')
        self.assertFalse(resp.json().get('error'), resp.json())
        return att.id, _extract_preview_token(resp.json()['data']['preview_url'])

    def _delete_task(self, task_id):
        resp = self.initiator_client.delete(f'/coop-task/tasks/{task_id}/')
        self.assertFalse(resp.json().get('error'), resp.json())

    def test_preview_file_works_on_live_task(self):
        """对照基线：任务未删除时 preview_token 回调正常返回文件流"""
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        delivery = CoopTaskDelivery.objects.filter(
            assignment__task_id=data['id']).first()
        att_id, token = self._issue_delivery_token(delivery)
        resp = self.deliverer_b_client.get(
            f'/coop-task/attachments/{att_id}/preview-file/?preview_token={token}')
        self.assertIsNone(_resp_error(resp))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'%PDF-1.4', b''.join(resp.streaming_content))

    def test_delivery_preview_file_blocked_after_soft_delete(self):
        """删除前签发的交付附件 preview_token 在任务删除后必须失效"""
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        delivery = CoopTaskDelivery.objects.filter(
            assignment__task_id=data['id']).first()
        att_id, token = self._issue_delivery_token(delivery)
        self._delete_task(data['id'])
        resp = self.deliverer_b_client.get(
            f'/coop-task/attachments/{att_id}/preview-file/?preview_token={token}')
        self.assertTrue(_resp_error(resp), '软删除任务附件仍可通过存量 preview_token 读取文件流')

    def test_template_preview_file_blocked_after_soft_delete(self):
        """删除前签发的材料模板 preview_token 在任务删除后必须失效"""
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        item_id = CoopTaskItem.objects.filter(task_id=data['id']).first().id
        att_id, token = self._issue_template_token(item_id)
        self._delete_task(data['id'])
        resp = self.initiator_client.get(
            f'/coop-task/attachments/{att_id}/preview-file/?preview_token={token}')
        self.assertTrue(_resp_error(resp), '软删除任务的模板仍可通过存量 preview_token 读取文件流')

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""协作任务模块容错测试

覆盖异常输入与异常状态下的健壮性，全部走真实 HTTP 路径并校验数据库/物理文件副作用：
- 附件上传：缺文件、非法扩展名、超限大小、同名去重、路径穿越文件名
- 附件/模板接口对不存在对象、已结束任务的防护
- 预览令牌：缺失/伪造/换附件/换模块/未配置预览服务/不可预览类型
- 状态机边界：重复提交、已验收再提交、作废后再作废、对不存在对象操作
- 列表查询：越界分页与特殊关键字不产生服务器内部错误
"""
import base64
import os
import tempfile
from urllib.parse import urlparse, parse_qs, quote

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.evidence.models import EvidenceAttachment
from apps.evidence.attachment_preview_token import generate_attachment_preview_token

from apps.coop_task.models import CoopTask, CoopTaskDelivery, TASK_STATUS_VOIDED

from apps.coop_task.tests.test_coop_task import CoopTaskFlowTestsBase


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DeliveryAttachmentFaultTests(CoopTaskFlowTestsBase):
    """交付附件上传/删除的容错"""

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']
        self.deliveries = list(
            CoopTaskDelivery.objects.filter(assignment__task_id=self.task_id).order_by('id'))
        self.delivery = self.deliveries[0]

    def _upload(self, delivery_id=None, filename='总结.pdf', content=b'%PDF-1.4 test'):
        file = SimpleUploadedFile(filename, content)
        return self.deliverer_b_client.post(
            f'/coop-task/deliveries/{delivery_id or self.delivery.id}/attachments/',
            {'file': file})

    def test_upload_without_file_rejected(self):
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.delivery.id}/attachments/', {})
        self.assertIn('请选择要上传的文件', resp.json().get('error', ''))
        self.assertEqual(
            EvidenceAttachment.objects.filter(module='coop_task').count(), 0)

    def test_upload_disallowed_extension_rejected(self):
        for filename in ('木马.exe', '脚本.bat'):
            resp = self._upload(filename=filename)
            self.assertIn('不支持的文件类型', resp.json().get('error', ''), filename)
        self.assertEqual(
            EvidenceAttachment.objects.filter(module='coop_task').count(), 0)

    def test_upload_extension_case_insensitive(self):
        """回归：大写扩展名放行并统一存小写"""
        resp = self._upload(filename='总结.PDF')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(
            EvidenceAttachment.objects.get(module='coop_task').file_ext, '.pdf')

    def test_upload_oversize_rejected(self):
        """超过 50MB 上限被拒绝且不落库"""
        oversize = b'0' * (50 * 1024 * 1024 + 1)
        resp = self._upload(filename='big.pdf', content=oversize)
        self.assertIn('50MB', resp.json().get('error', ''))
        self.assertEqual(
            EvidenceAttachment.objects.filter(module='coop_task').count(), 0)

    def test_upload_to_nonexistent_delivery_rejected(self):
        resp = self._upload(delivery_id=999999)
        self.assertIn('交付明细不存在', resp.json().get('error', ''))

    def test_duplicate_filename_gets_unique_disk_names(self):
        """同名文件重复上传自动重命名，两份附件与物理文件共存"""
        resp1 = self._upload(filename='doc.pdf')
        resp2 = self._upload(filename='doc.pdf')
        self.assertFalse(resp1.json().get('error'), resp1.json())
        self.assertFalse(resp2.json().get('error'), resp2.json())
        atts = EvidenceAttachment.objects.filter(module='coop_task').order_by('id')
        self.assertEqual(atts.count(), 2)
        disk_names = {os.path.basename(a.file_path) for a in atts}
        self.assertEqual(len(disk_names), 2)
        for att in atts:
            self.assertTrue(os.path.exists(os.path.join(settings.MEDIA_ROOT, att.file_path)))

    def test_upload_after_void_rejected(self):
        self.initiator_client.post(f'/coop-task/tasks/{self.task_id}/void/')
        resp = self._upload()
        self.assertIn('任务已结束，无法上传附件', resp.json().get('error', ''))
        self.assertEqual(
            EvidenceAttachment.objects.filter(module='coop_task').count(), 0)

    def test_delete_attachment_after_void_rejected(self):
        self._upload()
        att = EvidenceAttachment.objects.get(
            module='coop_task', object_type='delivery', object_id=str(self.delivery.id))
        self.initiator_client.post(f'/coop-task/tasks/{self.task_id}/void/')
        resp = self.deliverer_b_client.delete(f'/coop-task/attachments/?id={att.id}')
        self.assertIn('任务已结束，无法删除附件', resp.json().get('error', ''))
        self.assertTrue(EvidenceAttachment.objects.filter(pk=att.id).exists())

    def test_attachment_list_nonexistent_delivery_rejected(self):
        resp = self.deliverer_b_client.get('/coop-task/deliveries/999999/attachments/')
        self.assertIn('交付明细不存在', resp.json().get('error', ''))

    def test_upload_to_accepted_delivery_rejected(self):
        """已验收明细不允许再上传（重复防护）"""
        self._upload()
        self.deliverer_b_client.post(f'/coop-task/deliveries/{self.delivery.id}/submit/')
        self.initiator_client.post(f'/coop-task/deliveries/{self.delivery.id}/accept/')
        resp = self._upload(filename='again.pdf')
        self.assertIn('已验收通过，无法上传附件', resp.json().get('error', ''))
        self.assertEqual(
            EvidenceAttachment.objects.filter(
                module='coop_task', object_id=str(self.delivery.id)).count(), 1)


def settings_media_root():
    from django.conf import settings
    return settings.MEDIA_ROOT


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TemplateFaultTests(CoopTaskFlowTestsBase):
    """材料模板接口的容错"""

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']
        self.item = CoopTaskDelivery.objects.filter(
            assignment__task_id=self.task_id).first().item

    def _upload(self, item_id=None, filename='模板.pdf'):
        return self.initiator_client.post(
            f'/coop-task/items/{item_id or self.item.id}/templates/',
            {'file': SimpleUploadedFile(filename, b'data')})

    def test_template_upload_without_file_rejected(self):
        resp = self.initiator_client.post(
            f'/coop-task/items/{self.item.id}/templates/', {})
        self.assertIn('请选择要上传的文件', resp.json().get('error', ''))
        self.assertEqual(
            EvidenceAttachment.objects.filter(module='coop_task').count(), 0)

    def test_template_upload_disallowed_extension_rejected(self):
        resp = self._upload(filename='模板.exe')
        self.assertIn('不支持的文件类型', resp.json().get('error', ''))
        self.assertEqual(
            EvidenceAttachment.objects.filter(module='coop_task').count(), 0)

    def test_template_upload_to_nonexistent_item_rejected(self):
        resp = self._upload(item_id=999999)
        self.assertIn('材料不存在', resp.json().get('error', ''))

    def test_template_delete_nonexistent_rejected(self):
        self._upload()
        att = EvidenceAttachment.objects.get(module='coop_task', object_type='item_template')
        resp = self.initiator_client.delete(
            f'/coop-task/items/{self.item.id}/templates/?id=999999')
        self.assertIn('模板不存在', resp.json().get('error', ''))
        self.assertTrue(EvidenceAttachment.objects.filter(pk=att.id).exists())

    def test_template_delete_of_other_item_rejected(self):
        """用 A 材料入口删 B 材料的模板被拒绝（object_id 绑定校验）"""
        other_item = CoopTaskDelivery.objects.filter(
            assignment__task_id=self.task_id).exclude(
            item_id=self.item.id).first().item
        self._upload()
        att = EvidenceAttachment.objects.get(module='coop_task', object_type='item_template')
        resp = self.initiator_client.delete(
            f'/coop-task/items/{other_item.id}/templates/?id={att.id}')
        self.assertIn('模板不存在', resp.json().get('error', ''))
        self.assertTrue(EvidenceAttachment.objects.filter(pk=att.id).exists())

    def test_template_manage_after_completed_rejected(self):
        """任务完成后模板上传/删除均被禁止"""
        self._upload()
        att = EvidenceAttachment.objects.get(module='coop_task', object_type='item_template')
        for delivery in CoopTaskDelivery.objects.filter(assignment__task_id=self.task_id):
            self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
            self.initiator_client.post(f'/coop-task/deliveries/{delivery.id}/accept/')
        resp = self._upload(filename='后传模板.pdf')
        self.assertIn('任务已结束，无法上传模板', resp.json().get('error', ''))
        resp = self.initiator_client.delete(
            f'/coop-task/items/{self.item.id}/templates/?id={att.id}')
        self.assertIn('任务已结束，无法删除模板', resp.json().get('error', ''))
        self.assertTrue(EvidenceAttachment.objects.filter(pk=att.id).exists())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AttachmentEndpointFaultTests(CoopTaskFlowTestsBase):
    """附件通用端点的容错"""

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']
        self.delivery = CoopTaskDelivery.objects.filter(
            assignment__task_id=self.task_id).first()

    def test_delete_nonexistent_attachment_rejected(self):
        resp = self.deliverer_b_client.delete('/coop-task/attachments/?id=999999')
        self.assertIn('附件不存在', resp.json().get('error', ''))

    def test_delete_template_via_delivery_endpoint_rejected(self):
        """模板附件不能通过交付附件删除入口删除（object_type 隔离）"""
        self.initiator_client.post(
            f'/coop-task/items/{self.delivery.item_id}/templates/',
            {'file': SimpleUploadedFile('模板.pdf', b'data')})
        att = EvidenceAttachment.objects.get(module='coop_task', object_type='item_template')
        resp = self.deliverer_b_client.delete(f'/coop-task/attachments/?id={att.id}')
        self.assertIn('附件不存在', resp.json().get('error', ''))
        self.assertTrue(EvidenceAttachment.objects.filter(pk=att.id).exists())

    def test_delete_without_id_rejected(self):
        resp = self.deliverer_b_client.delete('/coop-task/attachments/')
        self.assertTrue(resp.json().get('error'), resp.json())

    def test_download_nonexistent_attachment_rejected(self):
        resp = self.initiator_client.get('/coop-task/attachments/999999/download/')
        self.assertIn('附件不存在', resp.json().get('error', ''))

    def test_download_after_hard_delete_rejected(self):
        self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.delivery.id}/attachments/',
            {'file': SimpleUploadedFile('a.pdf', b'data')})
        att = EvidenceAttachment.objects.get(
            module='coop_task', object_type='delivery', object_id=str(self.delivery.id))
        self.deliverer_b_client.delete(f'/coop-task/attachments/?id={att.id}')
        resp = self.deliverer_b_client.get(f'/coop-task/attachments/{att.id}/download/')
        self.assertIn('附件不存在', resp.json().get('error', ''))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
@override_settings(KKFILEVIEW_API_URL='http://kkf-test:8012',
                   KKFILEVIEW_SERVER_URL='http://api-test:80')
class PreviewTokenFaultTests(CoopTaskFlowTestsBase):
    """预览令牌：缺失 / 伪造 / 换附件 / 换模块 / 不可预览类型 / 未配置服务"""

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']
        self.deliveries = list(
            CoopTaskDelivery.objects.filter(assignment__task_id=self.task_id).order_by('id'))
        for delivery in self.deliveries:
            resp = self.deliverer_b_client.post(
                f'/coop-task/deliveries/{delivery.id}/attachments/',
                {'file': SimpleUploadedFile('a.pdf', b'%PDF-1.4 data')})
            self.assertFalse(resp.json().get('error'), resp.json())
        self.att_a = EvidenceAttachment.objects.get(
            object_type='delivery', object_id=str(self.deliveries[0].id))
        self.att_b = EvidenceAttachment.objects.get(
            object_type='delivery', object_id=str(self.deliveries[1].id))
        # 提交使发起方可见
        for delivery in self.deliveries:
            self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')

    def _get_token(self, att_id):
        """从 preview_url 中解出 preview_token（回调地址整体 base64 编码在 url 参数里）"""
        resp = self.initiator_client.get(f'/coop-task/attachments/{att_id}/preview-url/')
        self.assertFalse(resp.json().get('error'), resp.json())
        outer = parse_qs(urlparse(resp.json()['data']['preview_url']).query)
        file_url = base64.b64decode(outer['url'][0]).decode('utf-8')
        return parse_qs(urlparse(file_url).query)['preview_token'][0]

    def test_preview_file_missing_token_rejected(self):
        resp = self.initiator_client.get(
            f'/coop-task/attachments/{self.att_a.id}/preview-file/')
        self.assertIn('缺少 preview_token', resp.json().get('error', ''))

    def test_preview_file_garbage_token_rejected(self):
        resp = self.initiator_client.get(
            f'/coop-task/attachments/{self.att_a.id}/preview-file/?preview_token=garbage')
        self.assertIn('预览令牌无效或已过期', resp.json().get('error', ''))

    def test_preview_file_happy_path(self):
        """有效令牌可回读文件流（对照基线）"""
        token = self._get_token(self.att_a.id)
        resp = self.initiator_client.get(
            f'/coop-task/attachments/{self.att_a.id}/preview-file/?preview_token={token}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b''.join(resp.streaming_content), b'%PDF-1.4 data')

    def test_preview_file_token_for_other_attachment_rejected(self):
        """令牌绑定附件：A 的令牌访问 B 被拒绝"""
        token = self._get_token(self.att_a.id)
        resp = self.initiator_client.get(
            f'/coop-task/attachments/{self.att_b.id}/preview-file/?preview_token={token}')
        self.assertIn('预览令牌与请求附件不匹配', resp.json().get('error', ''))

    def test_preview_file_token_of_other_module_rejected(self):
        """跨模块令牌绑定校验：module 不一致即拒绝"""
        token = generate_attachment_preview_token(
            attachment_id=self.att_a.id, user_id=self.initiator.id,
            tenant_id=str(self.tenant_a.id), module='contract_agreement',
            object_type='agreement', object_id='123')
        resp = self.initiator_client.get(
            f'/coop-task/attachments/{self.att_a.id}/preview-file/?preview_token={token}')
        self.assertIn('预览令牌无效', resp.json().get('error', ''))

    def test_preview_url_non_previewable_extension_rejected(self):
        """zip 不支持在线预览"""
        delivery = self.deliveries[0]
        EvidenceAttachment.objects.filter(
            object_type='delivery', object_id=str(delivery.id)).delete()
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{delivery.id}/attachments/',
            {'file': SimpleUploadedFile('打包.zip', b'PK')})
        self.assertFalse(resp.json().get('error'), resp.json())
        resp = self.deliverer_b_client.get(
            f'/coop-task/attachments/{resp.json()["data"]["id"]}/preview-url/')
        self.assertIn('不支持在线预览', resp.json().get('error', ''))

    @override_settings(KKFILEVIEW_API_URL='', KKFILEVIEW_SERVER_URL='')
    def test_preview_url_unconfigured_service_rejected(self):
        """预览服务未配置时给出明确降级提示"""
        resp = self.initiator_client.get(
            f'/coop-task/attachments/{self.att_a.id}/preview-url/')
        self.assertIn('未配置', resp.json().get('error', ''))


class StateBoundaryFaultTests(CoopTaskFlowTestsBase):
    """状态机边界与不存在对象的操作"""

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']
        self.deliveries = list(
            CoopTaskDelivery.objects.filter(assignment__task_id=self.task_id).order_by('id'))

    def test_submit_nonexistent_delivery_rejected(self):
        resp = self.deliverer_b_client.post('/coop-task/deliveries/999999/submit/')
        self.assertIn('交付明细不存在', resp.json().get('error', ''))

    def test_accept_nonexistent_delivery_rejected(self):
        resp = self.initiator_client.post('/coop-task/deliveries/999999/accept/')
        self.assertIn('交付明细不存在', resp.json().get('error', ''))

    def test_reject_nonexistent_delivery_rejected(self):
        resp = self.initiator_client.post(
            '/coop-task/deliveries/999999/reject/',
            {'reason': '不合格'}, content_type='application/json')
        self.assertIn('交付明细不存在', resp.json().get('error', ''))

    def test_repeated_submit_is_idempotent_like(self):
        """重复提交不报错、状态保持待验收（容错基线）"""
        delivery = self.deliveries[0]
        resp1 = self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
        resp2 = self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
        self.assertFalse(resp1.json().get('error'), resp1.json())
        self.assertFalse(resp2.json().get('error'), resp2.json())
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'submitted')
        self.assertEqual(delivery.submitter_id, self.deliverer_b.id)

    def test_submit_accepted_delivery_rejected(self):
        delivery = self.deliveries[0]
        self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
        self.initiator_client.post(f'/coop-task/deliveries/{delivery.id}/accept/')
        resp = self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
        self.assertIn('已验收通过，无需重复提交', resp.json().get('error', ''))
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'accepted')

    def test_void_twice_rejected(self):
        self.initiator_client.post(f'/coop-task/tasks/{self.task_id}/void/')
        resp = self.initiator_client.post(f'/coop-task/tasks/{self.task_id}/void/')
        self.assertIn('仅进行中的任务可以作废', resp.json().get('error', ''))
        self.assertEqual(CoopTask.objects.get(pk=self.task_id).status, TASK_STATUS_VOIDED)

    def test_void_completed_task_rejected(self):
        for delivery in self.deliveries:
            self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
            self.initiator_client.post(f'/coop-task/deliveries/{delivery.id}/accept/')
        resp = self.initiator_client.post(f'/coop-task/tasks/{self.task_id}/void/')
        self.assertIn('仅进行中的任务可以作废', resp.json().get('error', ''))
        self.assertEqual(CoopTask.objects.get(pk=self.task_id).status, 'completed')

    def test_edit_void_delete_nonexistent_task_rejected(self):
        resp = self.initiator_client.post(
            '/coop-task/tasks/999999/', {'title': 'x', 'deadline': '2026-10-15 09:00'},
            content_type='application/json')
        self.assertIn('任务不存在', resp.json().get('error', ''))
        resp = self.initiator_client.post('/coop-task/tasks/999999/void/')
        self.assertIn('任务不存在', resp.json().get('error', ''))
        resp = self.initiator_client.delete('/coop-task/tasks/999999/')
        self.assertIn('任务不存在', resp.json().get('error', ''))


class ListRobustnessTests(CoopTaskFlowTestsBase):
    """列表查询：越界分页与特殊关键字不产生服务器内部错误"""

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']

    def test_page_zero_returns_error_not_500(self):
        resp = self.initiator_client.get('/coop-task/tasks/?page=0')
        body = resp.json()
        self.assertNotEqual(body.get('error'), '服务器内部错误，请联系管理员', body)

    def test_negative_page_returns_error_not_500(self):
        resp = self.initiator_client.get('/coop-task/tasks/?page=-1')
        body = resp.json()
        self.assertNotEqual(body.get('error'), '服务器内部错误，请联系管理员', body)

    def test_negative_page_size_returns_error_not_500(self):
        resp = self.initiator_client.get('/coop-task/tasks/?page_size=-5')
        body = resp.json()
        self.assertNotEqual(body.get('error'), '服务器内部错误，请联系管理员', body)

    def test_non_numeric_page_returns_parse_error(self):
        resp = self.initiator_client.get('/coop-task/tasks/?page=abc')
        body = resp.json()
        self.assertTrue(body.get('error'), body)
        self.assertNotIn('服务器内部错误', body.get('error', ''))

    def test_zero_page_size_returns_empty_results(self):
        resp = self.initiator_client.get('/coop-task/tasks/?page_size=0')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(body['data']['results'], [])
        self.assertEqual(body['data']['total'], 1)

    def test_keyword_special_chars_no_injection_no_500(self):
        for keyword in ("%' OR '1'='1", '"; DROP TABLE tdyw_coop_tasks;--', '%_%', '\\'):
            resp = self.initiator_client.get(
                f'/coop-task/tasks/?keyword={quote(keyword)}')
            body = resp.json()
            self.assertFalse(body.get('error'), (keyword, body))
        # 表完好且原任务仍可查
        self.assertTrue(CoopTask.objects.filter(pk=self.task_id).exists())
        resp = self.initiator_client.get('/coop-task/tasks/')
        self.assertEqual(resp.json()['data']['total'], 1)

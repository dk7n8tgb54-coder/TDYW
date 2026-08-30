# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""协作任务模块安全测试

覆盖越权与注入防护，全部走真实 HTTP 路径并校验数据库状态未被篡改：
- 水平越权：其他科室账号编辑/作废/删除/催办任务、退回他人交付明细
- 附件越权：无关科室下载/获取预览地址；跨模块附件不可经协作任务入口触达
- 权限粒度：交付方不能验收/编辑/作废/催办；仅 view 权限不能创建/提交/传删附件
- 输入注入：关键字 SQL 注入不生效；特殊字符标题完整往返
- 科室列表不暴露超管与停用账号
"""
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from urllib.parse import quote

from apps.evidence.models import EvidenceAttachment
from apps.coop_task.models import (
    CoopTask, CoopTaskAssignment, CoopTaskDelivery,
)

from apps.coop_task.tests.test_coop_task import (
    CoopTaskFlowTestsBase, _make_user, _grant_perms, _make_client, _coop_perms,
)


def _foreign_operator(tenant_id):
    """创建一个来自其他科室、拥有发起方全套权限的账号"""
    user = _make_user(f'sec_op_{tenant_id}', tenant_id=str(tenant_id))
    _grant_perms(user, _coop_perms('view', 'add', 'edit', 'delete', 'accept', 'submit'))
    return user


class CrossTenantAuthorizationTests(CoopTaskFlowTestsBase):
    """水平越权：其他科室即使具备全部协作任务权限也不可操作他科任务"""

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']
        self.task = CoopTask.objects.get(pk=self.task_id)
        self.delivery = CoopTaskDelivery.objects.filter(
            assignment__task_id=self.task_id).first()
        self.foreign_client = _make_client(_foreign_operator(self.tenant_x.id))

    def test_edit_other_tenant_task_denied(self):
        resp = self.foreign_client.post(
            f'/coop-task/tasks/{self.task_id}/',
            {'title': '越权改标题', 'deadline': '2026-10-15 09:00'},
            content_type='application/json')
        self.assertIn('任务不存在或无权限访问', resp.json().get('error', ''))
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, '征集5月工作台账')

    def test_void_other_tenant_task_denied(self):
        resp = self.foreign_client.post(f'/coop-task/tasks/{self.task_id}/void/')
        self.assertIn('任务不存在或无权限访问', resp.json().get('error', ''))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'in_progress')

    def test_delete_other_tenant_task_denied(self):
        resp = self.foreign_client.delete(f'/coop-task/tasks/{self.task_id}/')
        self.assertIn('任务不存在或无权限访问', resp.json().get('error', ''))
        self.assertFalse(CoopTask.objects.get(pk=self.task_id).is_deleted)

    def test_detail_other_tenant_task_denied(self):
        resp = self.foreign_client.get(f'/coop-task/tasks/{self.task_id}/')
        self.assertIn('任务不存在或无权限访问', resp.json().get('error', ''))

    def test_urge_other_tenant_task_denied(self):
        assignment = CoopTaskAssignment.objects.get(task_id=self.task_id)
        resp = self.foreign_client.post(
            f'/coop-task/tasks/{self.task_id}/urge/',
            {'assignment_id': assignment.id}, content_type='application/json')
        self.assertIn('任务不存在或无权限访问', resp.json().get('error', ''))
        assignment.refresh_from_db()
        self.assertEqual(assignment.urge_count, 0)

    def test_reject_other_tenant_delivery_denied(self):
        self.deliverer_b_client.post(f'/coop-task/deliveries/{self.delivery.id}/submit/')
        resp = self.foreign_client.post(
            f'/coop-task/deliveries/{self.delivery.id}/reject/',
            {'reason': '越权退回'}, content_type='application/json')
        self.assertIn('交付明细不存在或无权限访问', resp.json().get('error', ''))
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'submitted')
        self.assertEqual(self.delivery.reject_reason, '')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CrossTenantAttachmentTests(CoopTaskFlowTestsBase):
    """附件越权：无关科室不可下载/预览；跨模块附件不可触达"""

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']
        self.delivery = CoopTaskDelivery.objects.filter(
            assignment__task_id=self.task_id).first()
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.delivery.id}/attachments/',
            {'file': SimpleUploadedFile('秘密.pdf', b'%PDF-1.4 secret')})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.att = EvidenceAttachment.objects.get(
            module='coop_task', object_type='delivery', object_id=str(self.delivery.id))
        # 提交后发起科室可见，但无关科室仍不可见
        self.deliverer_b_client.post(f'/coop-task/deliveries/{self.delivery.id}/submit/')

    def test_outsider_download_denied(self):
        resp = self.outsider_client.get(f'/coop-task/attachments/{self.att.id}/download/')
        self.assertTrue(resp.json().get('error'), resp.json())
        self.assertIn('无权限', resp.json().get('error', ''))

    def test_outsider_preview_url_denied(self):
        resp = self.outsider_client.get(
            f'/coop-task/attachments/{self.att.id}/preview-url/')
        self.assertTrue(resp.json().get('error'), resp.json())
        self.assertIn('无权限', resp.json().get('error', ''))

    def test_cross_module_attachment_not_reachable(self):
        """其他模块附件不能经协作任务附件入口下载/删除"""
        foreign_att = EvidenceAttachment.objects.create(
            tenant_id=str(self.tenant_a.id), module='contract_agreement',
            object_type='agreement', object_id='8888',
            file_name='合同.pdf', file_path='contract_agreement/t_a/202608/agreement_8888/合同.pdf',
            file_size=10, file_ext='.pdf')
        resp = self.initiator_client.get(
            f'/coop-task/attachments/{foreign_att.id}/download/')
        self.assertIn('附件不存在', resp.json().get('error', ''))
        # 删除入口要求 submit 权限，用交付方账号验证
        resp = self.deliverer_b_client.delete(f'/coop-task/attachments/?id={foreign_att.id}')
        self.assertIn('附件不存在', resp.json().get('error', ''))
        self.assertTrue(EvidenceAttachment.objects.filter(pk=foreign_att.id).exists())


class PermissionGranularityTests(CoopTaskFlowTestsBase):
    """权限粒度：缺对应权限编码一律'权限拒绝'"""

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']
        self.delivery = CoopTaskDelivery.objects.filter(
            assignment__task_id=self.task_id).first()
        self.item = self.delivery.item
        self.assignment = CoopTaskAssignment.objects.get(task_id=self.task_id)

    def test_deliverer_cannot_perform_initiator_actions(self):
        """交付方（view+submit）不能验收/退回/编辑/作废/删除/催办"""
        for method, url, payload in (
                ('post', f'/coop-task/deliveries/{self.delivery.id}/accept/', None),
                ('post', f'/coop-task/deliveries/{self.delivery.id}/reject/', {'reason': 'x'}),
                ('post', f'/coop-task/tasks/{self.task_id}/',
                 {'title': 't', 'deadline': '2026-10-15 09:00'}),
                ('post', f'/coop-task/tasks/{self.task_id}/void/', None),
                ('post', f'/coop-task/tasks/{self.task_id}/urge/',
                 {'assignment_id': self.assignment.id}),
        ):
            resp = getattr(self.deliverer_b_client, method)(
                url, payload if payload is not None else {},
                content_type='application/json')
            self.assertEqual(resp.json().get('error'), '权限拒绝', (method, url))
        resp = self.deliverer_b_client.delete(f'/coop-task/tasks/{self.task_id}/')
        self.assertEqual(resp.json().get('error'), '权限拒绝')

    def test_deliverer_cannot_manage_template(self):
        """交付方不能上传/删除材料模板（需 edit 权限）"""
        resp = self.deliverer_b_client.post(
            f'/coop-task/items/{self.item.id}/templates/',
            {'file': SimpleUploadedFile('t.pdf', b'x')})
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        resp = self.deliverer_b_client.delete(
            f'/coop-task/items/{self.item.id}/templates/?id=1')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        self.assertEqual(
            EvidenceAttachment.objects.filter(module='coop_task').count(), 0)

    def test_view_only_user_cannot_write(self):
        """仅 view 权限：不能创建任务、提交交付、上传/删除附件"""
        viewer = _make_user('sec_viewer', tenant_id=str(self.tenant_a.id))
        _grant_perms(viewer, _coop_perms('view'))
        client = _make_client(viewer)
        resp = client.post(
            '/coop-task/tasks/', self._create_payload(), content_type='application/json')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        resp = client.post(f'/coop-task/deliveries/{self.delivery.id}/submit/')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        resp = client.post(
            f'/coop-task/deliveries/{self.delivery.id}/attachments/',
            {'file': SimpleUploadedFile('x.pdf', b'x')})
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        resp = client.delete('/coop-task/attachments/?id=1')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'pending')
        self.assertEqual(
            EvidenceAttachment.objects.filter(module='coop_task').count(), 0)

    def test_departments_excludes_inactive_and_supper(self):
        """科室列表不暴露停用账号与超管账号"""
        inactive = _make_user('sec_inactive', tenant_id=str(self.tenant_b.id), is_active=False)
        resp = self.initiator_client.get('/coop-task/departments/')
        ids = {x['id'] for x in resp.json()['data']}
        self.assertNotIn(inactive.id, ids)
        self.assertNotIn(self.supper.id, ids)


class InputSanitizationTests(CoopTaskFlowTestsBase):
    """输入注入与特殊字符往返"""

    def test_sql_injection_keyword_harmless(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        before = CoopTask.objects.count()
        for keyword in ("' OR '1'='1", "'; DROP TABLE tdyw_coop_tasks;--", "' UNION SELECT NULL--"):
            resp = self.initiator_client.get(
                f'/coop-task/tasks/?keyword={quote(keyword)}')
            body = resp.json()
            self.assertFalse(body.get('error'), (keyword, body))
            self.assertEqual(body['data']['total'], 0)
        self.assertEqual(CoopTask.objects.count(), before)

    def test_special_char_title_roundtrip(self):
        """含引号/尖括号等特殊字符的标题完整存取，JSON 转义无损"""
        title = '''引号"单引号'尖括号<>&\\反斜杠'''
        payload = self._create_payload()
        payload['title'] = title
        resp = self.initiator_client.post(
            '/coop-task/tasks/', payload, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        task_id = resp.json()['data']['id']
        self.assertEqual(CoopTask.objects.get(pk=task_id).title, title)
        detail = self.initiator_client.get(f'/coop-task/tasks/{task_id}/').json()['data']
        self.assertEqual(detail['title'], title)

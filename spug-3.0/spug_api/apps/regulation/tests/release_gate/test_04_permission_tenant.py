"""R-04 权限矩阵与租户隔离（stable_contract / P0-P1 安全）。

覆盖用户要求：
- 无规章权限账号 / 仅 view / 全权限 / 不同租户账号
- 未授权用户不能通过直接调用 API 访问受保护接口
- viewer 不能创建、编辑、删除、废止、上传或删除附件
- upload 权限不能自动获得 download / category_manage / delete 规章权限
- download 权限不能绕过规章访问范围
- 所有拒绝场景验证 HTTP 响应、业务 error 字段、数据库无变化、物理文件无变化
"""
from apps.regulation.models import Regulation, RegulationAttachment, RegulationCategory
from .base import RegulationGateTestCase


class UnauthenticatedAccessTests(RegulationGateTestCase):
    """R-04-01 未授权 / 无效 token"""

    def _bare_client(self, token=None):
        from django.test import Client
        client = Client()
        client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
        if token is not None:
            client.defaults['HTTP_X_TOKEN'] = token
        return client

    def test_invalid_token_rejected_with_401(self):
        resp = self._bare_client('0' * 32).get('/regulation/')
        self.assertEqual(resp.status_code, 401, '无效 token 应返回 401')

    def test_missing_token_rejected_with_401(self):
        resp = self._bare_client().get('/regulation/')
        self.assertEqual(resp.status_code, 401)

    def test_no_perm_user_rejected_on_every_protected_endpoint(self):
        endpoints = [
            ('get', '/regulation/', None),
            ('get', f'/regulation/{self.regulation.id}/', None),
            ('get', '/regulation/categories/tree/', None),
            ('get', '/regulation/categories/', None),
            ('post', '/regulation/create/', {'title': 'x', 'rule_no': 'x'}),
            ('put', f'/regulation/{self.regulation.id}/', {'title': 'x'}),
            ('delete', f'/regulation/{self.regulation.id}/', None),
            ('post', f'/regulation/{self.regulation.id}/retire/', None),
            ('get', f'/regulation/{self.regulation.id}/attachments/', None),
            ('post', '/regulation/categories/', {'name': 'x'}),
        ]
        for method, url, body in endpoints:
            client = getattr(self.no_perm_client, method)
            resp = client(url) if body is None else client(url, body, content_type='application/json')
            self.assertEqual(resp.json()['error'], '权限拒绝',
                             f'{method.upper()} {url} 应拒绝无权限用户')


class ViewerReadOnlyTests(RegulationGateTestCase):
    """R-04-02 viewer 不得产生任何写副作用"""

    def setUp(self):
        super().setUp()
        self.att = self.make_attachment_record(self.regulation, 'viewer.pdf')

    def test_viewer_cannot_create(self):
        resp = self.viewer_client.post('/regulation/create/',
                                       {'title': '越权创建', 'rule_no': 'RG-VW-01'},
                                       content_type='application/json')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.assertFalse(Regulation.objects.filter(rule_no='RG-VW-01').exists())

    def test_viewer_cannot_edit(self):
        resp = self.viewer_client.put(f'/regulation/{self.regulation.id}/',
                                      {'title': '越权改名'}, content_type='application/json')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.title, '基准规章')

    def test_viewer_cannot_delete(self):
        resp = self.viewer_client.delete(f'/regulation/{self.regulation.id}/')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.assertTrue(Regulation.objects.filter(pk=self.regulation.id).exists())

    def test_viewer_cannot_retire(self):
        resp = self.viewer_client.post(f'/regulation/{self.regulation.id}/retire/')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.status, Regulation.STATUS_ACTIVE)

    def test_viewer_cannot_upload(self):
        before = self.physical_file_count()
        resp = self.upload(self.viewer_client, self.regulation.id, 'viewer-up.pdf')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.assertEqual(self.physical_file_count(), before, '无权限上传不得产生物理文件')

    def test_viewer_cannot_delete_attachment(self):
        resp = self.viewer_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.att.refresh_from_db()
        self.assertFalse(self.att.is_deleted, '无权限删除不得改变数据库状态')
        self.assertEqual(self.physical_file_count(), 1, '无权限删除不得删除物理文件')

    def test_viewer_cannot_download(self):
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/download/')
        self.assertEqual(resp.json()['error'], '权限拒绝')

    def test_viewer_can_read_list_detail_and_attachments(self):
        self.assertEqual(self.viewer_client.get('/regulation/').json()['error'], '')
        self.assertEqual(
            self.viewer_client.get(f'/regulation/{self.regulation.id}/').json()['error'], '')
        self.assertEqual(
            self.viewer_client.get(
                f'/regulation/{self.regulation.id}/attachments/').json()['error'], '')


class PermissionSeparationTests(RegulationGateTestCase):
    """R-04-03 权限不得相互隐含"""

    def setUp(self):
        super().setUp()
        self.att = self.make_attachment_record(self.regulation, 'sep.pdf')

    def test_upload_perm_does_not_grant_download(self):
        resp = self.uploader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/download/')
        self.assertEqual(resp.json()['error'], '权限拒绝')

    def test_upload_perm_does_not_grant_category_manage(self):
        resp = self.uploader_client.post('/regulation/categories/', {'name': 'x'},
                                         content_type='application/json')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.assertFalse(RegulationCategory.objects.filter(name='x').exists())

    def test_upload_perm_does_not_grant_regulation_delete(self):
        resp = self.uploader_client.delete(f'/regulation/{self.regulation.id}/')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.assertTrue(Regulation.objects.filter(pk=self.regulation.id).exists())

    def test_upload_perm_does_not_grant_regulation_edit(self):
        resp = self.uploader_client.put(f'/regulation/{self.regulation.id}/',
                                        {'title': 'x'}, content_type='application/json')
        self.assertEqual(resp.json()['error'], '权限拒绝')

    def test_download_perm_does_not_grant_upload(self):
        resp = self.upload(self.downloader_client, self.regulation.id, 'dl-up.pdf')
        self.assertEqual(resp.json()['error'], '权限拒绝')

    def test_download_perm_does_not_grant_attachment_delete(self):
        resp = self.downloader_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/')
        self.assertEqual(resp.json()['error'], '权限拒绝')

    def test_add_perm_does_not_grant_edit_or_delete(self):
        reg = Regulation.objects.create(title='仅创建者', rule_no='RG-CR-01',
                                        status=Regulation.STATUS_ACTIVE)
        self.assertEqual(
            self.creator_client.put(f'/regulation/{reg.id}/', {'title': 'x'},
                                    content_type='application/json').json()['error'],
            '权限拒绝')
        self.assertEqual(self.creator_client.delete(f'/regulation/{reg.id}/').json()['error'],
                         '权限拒绝')
        self.assertTrue(Regulation.objects.filter(pk=reg.id).exists())

    def test_delete_perm_does_not_grant_edit(self):
        self.assertEqual(
            self.deleter_client.put(f'/regulation/{self.regulation.id}/', {'title': 'x'},
                                    content_type='application/json').json()['error'],
            '权限拒绝')


class DownloadScopeTests(RegulationGateTestCase):
    """R-04-04 download 权限不得绕过规章访问范围"""

    def setUp(self):
        super().setUp()
        self.att1 = self.make_attachment_record(self.regulation, 'scope1.pdf', b'content-1')
        self.att2 = self.make_attachment_record(self.regulation2, 'scope2.pdf', b'content-2')

    def test_cannot_download_other_regulation_attachment(self):
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att2.id}/download/')
        self.assertEqual(resp.json()['error'], '附件不存在')
        self.assertNotIn(b'content-2', resp.content)

    def test_cannot_preview_other_regulation_attachment(self):
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att2.id}/preview-url/')
        self.assertEqual(resp.json()['error'], '附件不存在')

    def test_cannot_delete_other_regulation_attachment(self):
        resp = self.admin_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{self.att2.id}/')
        self.assertEqual(resp.json()['error'], '附件不存在')
        self.att2.refresh_from_db()
        self.assertFalse(self.att2.is_deleted)

    def test_non_numeric_attachment_id_does_not_route(self):
        """URL 正则限制 att_id 为数字：非数字路径不匹配路由 -> 404，不进入视图"""
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/abc/download/')
        self.assertEqual(resp.status_code, 404)

    def test_regulation_id_tampering_cannot_reach_other_attachment(self):
        """把 URL 中的规章 ID 换成另一条规章，附件 ID 不变 -> 必须失败"""
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation2.id}/attachments/{self.att1.id}/download/')
        self.assertEqual(resp.json()['error'], '附件不存在')
        self.assertNotIn(b'content-1', resp.content)


class TenantIsolationTests(RegulationGateTestCase):
    """R-04-05 租户隔离核对

    Regulation / RegulationCategory / RegulationAttachment 均无 tenant_id 字段，
    本组用例验证"跨租户可见"的实际行为，供产品侧确认是否符合预期。
    """

    def test_model_has_no_tenant_id_field(self):
        for model in (Regulation, RegulationCategory, RegulationAttachment):
            fields = {f.name for f in model._meta.get_fields()}
            self.assertNotIn('tenant_id', fields,
                             f'{model.__name__} 无 tenant_id，数据为全局共享')

    def test_other_tenant_can_read_all_regulations(self):
        resp = self.other_tenant_client.get('/regulation/')
        self.assertEqual(resp.json()['error'], '')
        self.assertEqual(resp.json()['data']['total'], 2,
                         '不同租户账号可读取全部规章（全局共享，非按租户隔离）')

    def test_other_tenant_can_read_detail_of_foreign_regulation(self):
        resp = self.other_tenant_client.get(f'/regulation/{self.regulation.id}/')
        self.assertEqual(resp.json()['error'], '')
        self.assertEqual(resp.json()['data']['title'], '基准规章')

    def test_other_tenant_can_read_categories(self):
        resp = self.other_tenant_client.get('/regulation/categories/tree/')
        self.assertEqual(resp.json()['error'], '')
        names = [n['name'] for n in resp.json()['data']]
        self.assertIn('根分类', names)

    def test_other_tenant_can_read_attachment_list(self):
        self.make_attachment_record(self.regulation, 'tenant.pdf')
        resp = self.other_tenant_client.get(f'/regulation/{self.regulation.id}/attachments/')
        self.assertEqual(resp.json()['error'], '')
        self.assertEqual(len(resp.json()['data']), 1)

    def test_other_tenant_still_bound_by_permission(self):
        """跨租户可见，但权限体系仍独立生效"""
        from .base import make_user, make_client
        stranger = make_user('rg_stranger', [], tenant_id='other_tenant')
        resp = make_client(stranger).get('/regulation/')
        self.assertEqual(resp.json()['error'], '权限拒绝')

    def test_audit_log_records_operator_tenant(self):
        from apps.logs.models import AuditLog
        self.admin_client.post('/regulation/create/',
                               {'title': '租户审计', 'rule_no': 'RG-TN-01'},
                               content_type='application/json')
        log = AuditLog.objects.filter(target_name='租户审计').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.tenant_id, self.admin.tenant_id)


class PermissionDenialSideEffectTests(RegulationGateTestCase):
    """R-04-06 拒绝场景不得留下任何副作用"""

    def test_denied_upload_leaves_no_file_and_no_record(self):
        before_files = self.physical_file_count()
        resp = self.upload(self.viewer_client, self.regulation.id, 'denied.pdf')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.assertEqual(RegulationAttachment.objects.count(), 0)
        self.assertEqual(self.physical_file_count(), before_files)

    def test_denied_delete_leaves_record_and_file_intact(self):
        att = self.make_attachment_record(self.regulation, 'keep.pdf', b'keep-me')
        resp = self.viewer_client.delete(
            f'/regulation/{self.regulation.id}/attachments/{att.id}/')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        att.refresh_from_db()
        self.assertFalse(att.is_deleted)
        self.assertIsNone(att.deleted_at)
        self.assertIsNone(att.deleted_by_id)
        self.assertEqual(self.physical_file_count(), 1)

    def test_denied_regulation_delete_leaves_attachments_intact(self):
        self.make_attachment_record(self.regulation, 'keep2.pdf', b'keep2')
        resp = self.editor_client.delete(f'/regulation/{self.regulation.id}/')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.assertEqual(RegulationAttachment.objects.filter(
            regulation_id=self.regulation.id).count(), 1)
        self.assertEqual(self.physical_file_count(), 1)

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""原稿上传/下载/预览与越权拒绝的真实行为测试

授权语义（2026-10-31 授权模型改造）：上传原稿（新增/更换来源）业务
门禁=手册所有者或制度管理员（页面 upload 权限码门控入口）；下载/预览
按手册授权行判定，tenant_id 不参与判定。
"""
import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.institution import storage
from apps.institution.models import (Manual, ManualFile,
                                     ManualOperationLog, ManualOriginal)
from apps.institution.models import ManualAuthorization
from apps.institution.tests.base import (
    ALL_PERMS, PERM_DOWNLOAD, PERM_EDIT, PERM_UPLOAD, PERM_VIEW,
    get_data, has_error, make_client, make_grant, make_user, setup_test_env,
)

DOCX_BYTES = b'PK\x03\x04 minimal docx'
DOC_BYTES = b'\xd0\xcf\x11\xe0 legacy doc'


class OriginalUploadTests(TestCase):
    def setUp(self):
        setup_test_env()
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(storage, 'get_institution_storage_base',
                               return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.manager = make_user('mgr', tenant_id='deptA', perms=ALL_PERMS)
        self.manager_client = make_client(self.manager)

    def _make_manual(self):
        manual = Manual.objects.create(
            name='科室操作手册', code='CZ-001',
            org_type=Manual.OWNER_SECTION, org_name='甲科室',
            owner=self.manager, tenant_id='deptA')
        # 原稿归属制度文件：先建主文件条目（无草稿，不影响上传语义）
        self.file_entry = ManualFile.objects.create(
            manual=manual, display_name='主文件.docx', sort_order=0)
        return manual

    def test_upload_docx_ok_with_side_effects(self):
        manual = self._make_manual()
        upload = SimpleUploadedFile('操作手册.docx', DOCX_BYTES,
                                    content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        resp = self.manager_client.post(
            f'/institution/manuals/{manual.id}/files/{self.file_entry.id}/originals/upload/',
            {'file': upload})
        self.assertFalse(has_error(resp))
        data = get_data(resp)
        self.assertEqual(data['file_name'], '操作手册.docx')
        original = ManualOriginal.objects.get(pk=data['id'])
        self.assertEqual(original.file_id, self.file_entry.id)
        self.assertTrue(original.file_hash)
        abs_path = storage.resolve_absolute_path(original.file_path)
        self.assertTrue(os.path.exists(abs_path))
        self.assertTrue(ManualOperationLog.objects.filter(
            manual=manual, action='upload_original').exists())

    def test_upload_reject_txt(self):
        manual = self._make_manual()
        upload = SimpleUploadedFile('a.txt', b'text')
        resp = self.manager_client.post(
            f'/institution/manuals/{manual.id}/files/{self.file_entry.id}/originals/upload/', {'file': upload})
        self.assertTrue(has_error(resp))
        self.assertIn('.doc', resp.json()['error'])

    def test_upload_without_file(self):
        manual = self._make_manual()
        resp = self.manager_client.post(
            f'/institution/manuals/{manual.id}/files/{self.file_entry.id}/originals/upload/', {})
        self.assertTrue(has_error(resp))

    def test_upload_requires_owner_or_admin(self):
        """上传原稿业务门禁=手册所有者/平台超管：编制授权与页面权限
        均不足以放行（2026-10-31 授权模型改造）"""
        manual = self._make_manual()
        editor = make_user('editor', tenant_id='deptB', perms=[PERM_UPLOAD])
        make_grant(manual, editor, can_edit=True)
        upload = SimpleUploadedFile('a.docx', DOCX_BYTES)
        resp = make_client(editor).post(
            f'/institution/manuals/{manual.id}/files/{self.file_entry.id}/originals/upload/', {'file': upload})
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])
        # 平台超管（is_supper）可以上传（"制度管理员"码已废除）
        admin = make_user('admin', is_supper=True, tenant_id='deptA')
        upload.seek(0)
        resp = make_client(admin).post(
            f'/institution/manuals/{manual.id}/files/{self.file_entry.id}/originals/upload/', {'file': upload})
        self.assertFalse(has_error(resp))

    def test_upload_needs_module_perm(self):
        manual = self._make_manual()
        editor = make_user('e', tenant_id='deptA', perms=[PERM_EDIT])
        upload = SimpleUploadedFile('a.docx', DOCX_BYTES)
        resp = make_client(editor).post(
            f'/institution/manuals/{manual.id}/files/{self.file_entry.id}/originals/upload/', {'file': upload})
        self.assertTrue(has_error(resp))

    def test_originals_never_overwritten(self):
        """同一手册上传两次产生两条记录与两个文件，原稿不覆盖"""
        manual = self._make_manual()
        for name in ('v1.docx', 'v2.docx'):
            upload = SimpleUploadedFile(name, DOCX_BYTES + name.encode())
            resp = self.manager_client.post(
                f'/institution/manuals/{manual.id}/files/{self.file_entry.id}/originals/upload/',
                {'file': upload})
            self.assertFalse(has_error(resp))
        self.assertEqual(ManualOriginal.objects.filter(manual=manual).count(), 2)
        paths = [storage.resolve_absolute_path(o.file_path)
                 for o in ManualOriginal.objects.filter(manual=manual)]
        self.assertTrue(all(os.path.exists(p) for p in paths))
        self.assertNotEqual(paths[0], paths[1])


class OriginalDownloadTests(TestCase):
    def setUp(self):
        setup_test_env()
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(storage, 'get_institution_storage_base',
                               return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.manager = make_user('mgr', tenant_id='deptA', perms=ALL_PERMS)
        self.manager_client = make_client(self.manager)
        self.manual = Manual.objects.create(
            name='科室操作手册', code='CZ-001',
            org_type=Manual.OWNER_SECTION, org_name='甲科室',
            owner=self.manager, tenant_id='deptA')
        rel = storage.build_relative_path('original', self.manual.id, 'a.docx')
        abs_path = storage.resolve_absolute_path(rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'wb') as f:
            f.write(DOCX_BYTES)
        self.file_entry = ManualFile.objects.create(
            manual=self.manual, display_name='主文件.docx', sort_order=0)
        self.original = ManualOriginal.objects.create(
            manual=self.manual, file=self.file_entry, file_path=rel,
            original_name='a.docx', ext='.docx', file_size=len(DOCX_BYTES),
            uploaded_by=self.manager)

    def test_download_by_view_grant_holder_cross_tenant(self):
        holder = make_user('h', tenant_id='deptB', perms=[PERM_VIEW, PERM_DOWNLOAD])
        make_grant(self.manual, holder, can_view=True)
        resp = make_client(holder).get(
            f'/institution/manuals/{self.manual.id}/originals/{self.original.id}/download/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.streaming)

    def test_download_denied_without_grant(self):
        insider = make_user('in', tenant_id='deptA',
                            perms=[PERM_VIEW, PERM_DOWNLOAD])
        resp = make_client(insider).get(
            f'/institution/manuals/{self.manual.id}/originals/{self.original.id}/download/')
        self.assertTrue(has_error(resp))

    def test_download_denied_without_module_perm(self):
        holder = make_user('h', tenant_id='deptB', perms=[PERM_VIEW])
        make_grant(self.manual, holder, can_view=True)
        resp = make_client(holder).get(
            f'/institution/manuals/{self.manual.id}/originals/{self.original.id}/download/')
        self.assertTrue(has_error(resp))

    def test_preview_url_by_grant_holder(self):
        holder = make_user('h', tenant_id='deptB', perms=[PERM_VIEW])
        make_grant(self.manual, holder, can_view=True)
        resp = make_client(holder).get(
            f'/institution/manuals/{self.manual.id}/originals/{self.original.id}/preview-url/')
        self.assertFalse(has_error(resp))
        data = get_data(resp)
        self.assertEqual(data['preview_type'], 'kkfileview')
        self.assertIn('onlinePreview?url=', data['preview_url'])

    def test_preview_file_stream_via_token(self):
        """preview_token 回源文件流：令牌无效/授权不符拒绝，有效则返回文件"""
        holder = make_user('h', tenant_id='deptB', perms=[PERM_VIEW])
        make_grant(self.manual, holder, can_view=True)
        resp = make_client(holder).get(
            f'/institution/manuals/{self.manual.id}/originals/{self.original.id}/preview-url/')
        self.assertFalse(has_error(resp))
        import base64
        from urllib.parse import urlparse, parse_qs
        # 从 kkFileView URL 中还原回源地址（preview_url 是 base64(url)）
        data = get_data(resp)
        file_url = base64.b64decode(
            data['preview_url'].split('url=')[1]).decode()
        query = parse_qs(urlparse(file_url).query)
        token = query['preview_token'][0]
        # 测试直连 Django URLconf；生产由 nginx 剥离 /api 前缀
        stream_path = urlparse(file_url).path.replace('/api', '', 1)
        client = make_client(holder)
        ok_resp = client.get(f'{stream_path}?preview_token={token}')
        self.assertEqual(ok_resp.status_code, 200)
        # 无令牌拒绝
        no_token = client.get(stream_path)
        self.assertTrue(has_error(no_token))
        # 令牌签发后撤销授权：文件流二次校验拒绝（防撤权后凭旧令牌取文件）
        ManualAuthorization.objects.filter(
            manual=self.manual, account=holder).delete()
        revoked_resp = client.get(f'{stream_path}?preview_token={token}')
        self.assertTrue(has_error(revoked_resp))

"""资料库权限与对象级校验发布门禁测试（stable_contract）。

覆盖 6 类角色、后端直连 API 鉴权、对象归属校验、传输记录归属校验、
以及 HTTP 200 + {"error": ...} 必须被识别为业务失败。
"""
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.document.models import DocumentFilePublic, DocumentFolderPublic, DocumentTransfer
from tests.helpers.test_base import (
    get_response_data, has_error, make_client, make_user, post_json, setup_test_env)

from .helpers import (
    PB, PERM_COPY, PERM_CREATE_FOLDER, PERM_DELETE, PERM_DOWNLOAD, PERM_MOVE,
    PERM_RENAME, PERM_UPLOAD, PERM_VIEW, PB_DELETE, StorageCleanupMixin,
    bind_party_building, make_file, make_folder, unique)

FOLDER_URL = '/document/folder/'
UPLOAD_URL = '/document/upload/'

# 普通资料库：可编辑但不可删除
PERMS_EDITOR = [
    PERM_VIEW, PERM_UPLOAD, PERM_DOWNLOAD, PERM_CREATE_FOLDER,
    PERM_RENAME, PERM_COPY, PERM_MOVE,
]
PERMS_DELETER = PERMS_EDITOR + [PERM_DELETE]


def pb_perm(op):
    return f'document.party_building_document.{op}'


PB_ALL_PERMS = [pb_perm(op) for op in (
    'view', 'upload', 'download', 'delete', 'create_folder', 'copy', 'move', 'rename')]


class PermissionMatrixTest(StorageCleanupMixin, TestCase):
    """资料库权限矩阵"""

    @classmethod
    def setUpTestData(cls):
        cls.viewer = make_user('gate_viewer', perms=[PERM_VIEW])
        cls.editor = make_user('gate_editor', perms=PERMS_EDITOR)
        cls.deleter = make_user('gate_deleter', perms=PERMS_DELETER)
        cls.noperm = make_user('gate_noperm', perms=[])
        cls.normal_only = make_user('gate_normal_only', perms=PERMS_DELETER)
        cls.pb_only = make_user('gate_pb_only', perms=PB_ALL_PERMS)
        cls.admin = make_user('gate_perm_admin', is_supper=True)

    def setUp(self):
        super().setUp()
        setup_test_env()
        self.clients = {}
        for name in ('viewer', 'editor', 'deleter', 'noperm', 'normal_only',
                     'pb_only', 'admin'):
            c = make_client(getattr(self, name))
            c.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'
            self.clients[name] = c

        self.pb_root = make_folder(name=unique('党建根'), created_by=self.admin)
        self.binding = bind_party_building(self.pb_root)
        self.pb_sub = make_folder(name=unique('党建子'), parent=self.pb_root,
                                  created_by=self.admin)

        # 每个角色自己的目录/文件（公共空间对象级校验要求本人创建）
        self.own = {}
        for name in ('editor', 'deleter', 'normal_only'):
            user = getattr(self, name)
            folder = make_folder(name=unique(f'{name}_dir'), created_by=user)
            file_obj = make_file(folder=folder, created_by=user,
                                 name=unique(f'{name}_f') + '.txt')
            self.track_path(file_obj.file_path)
            self.own[name] = {'folder': folder, 'file': file_obj}

    # ---------- 1. 无权限 ----------

    def test_01_noperm_cannot_list(self):
        """无资料库权限用户列目录 -> 权限拒绝"""
        resp = self.clients['noperm'].get(FOLDER_URL, {'is_public': 'true'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('error'), '权限拒绝', resp.json())

    def test_02_noperm_cannot_upload(self):
        """无权限用户上传 -> 权限拒绝，无文件落库"""
        resp = self.clients['noperm'].post(UPLOAD_URL, data={
            'file': SimpleUploadedFile('noperm.txt', b'x', content_type='text/plain'),
            'is_public': 'true',
        })
        self.assertEqual(resp.json().get('error'), '权限拒绝', resp.json())
        self.assertFalse(DocumentFilePublic.objects.filter(
            display_name='noperm.txt').exists())

    def test_03_noperm_cannot_delete(self):
        """无权限用户删除他人文件 -> 权限拒绝"""
        target = self.own['deleter']['file']
        resp = self.clients['noperm'].delete(
            f'/document/file/?id={target.id}&is_public=true')
        self.assertEqual(resp.json().get('error'), '权限拒绝', resp.json())
        self.assertTrue(DocumentFilePublic.objects.filter(id=target.id).exists())

    # ---------- 2. 仅查看 ----------

    def test_04_viewer_can_list(self):
        """仅查看角色可以列目录"""
        resp = self.clients['viewer'].get(FOLDER_URL, {'is_public': 'true'})
        self.assertFalse(has_error(resp), resp.json())

    def test_05_viewer_cannot_create_folder(self):
        """仅查看角色不能建目录"""
        resp = post_json(self.clients['viewer'], FOLDER_URL,
                         {'name': unique('viewer_dir'), 'is_public': True})
        self.assertEqual(resp.json().get('error'), '权限拒绝', resp.json())

    def test_06_viewer_cannot_upload(self):
        """仅查看角色不能上传"""
        resp = self.clients['viewer'].post(UPLOAD_URL, data={
            'file': SimpleUploadedFile('viewer.txt', b'x', content_type='text/plain'),
            'is_public': 'true',
        })
        self.assertEqual(resp.json().get('error'), '权限拒绝', resp.json())

    def test_07_viewer_cannot_delete(self):
        """仅查看角色不能删除"""
        target = self.own['deleter']['file']
        resp = self.clients['viewer'].delete(
            f'/document/file/?id={target.id}&is_public=true')
        self.assertEqual(resp.json().get('error'), '权限拒绝', resp.json())
        self.assertTrue(DocumentFilePublic.objects.filter(id=target.id).exists())

    # ---------- 3. 可编辑不可删除 ----------

    def test_08_editor_can_create_folder(self):
        """编辑角色可以建目录"""
        resp = post_json(self.clients['editor'], FOLDER_URL,
                         {'name': unique('editor_new'), 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())

    def test_09_editor_can_rename_own_folder(self):
        """编辑角色可以重命名自己的目录"""
        folder = self.own['editor']['folder']
        new_name = unique('editor_renamed')
        resp = post_json(self.clients['editor'], '/document/folder/rename/',
                         {'id': folder.id, 'name': new_name, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())
        folder.refresh_from_db()
        self.assertEqual(folder.name, new_name)

    def test_10_editor_cannot_delete_own_folder(self):
        """编辑角色（无 delete 权限）不能删除自己的目录"""
        folder = self.own['editor']['folder']
        resp = self.clients['editor'].delete(
            f'{FOLDER_URL}?id={folder.id}&is_public=true')
        self.assertEqual(resp.json().get('error'), '权限拒绝', resp.json())
        self.assertTrue(DocumentFolderPublic.objects.filter(id=folder.id).exists())

    def test_11_editor_cannot_delete_own_file(self):
        """编辑角色不能删除自己的文件"""
        file_obj = self.own['editor']['file']
        resp = self.clients['editor'].delete(
            f'/document/file/?id={file_obj.id}&is_public=true')
        self.assertEqual(resp.json().get('error'), '权限拒绝', resp.json())
        self.assertTrue(DocumentFilePublic.objects.filter(id=file_obj.id).exists())

    # ---------- 4. 可删除 ----------

    def test_12_deleter_can_delete_own_file(self):
        """删除角色可以删除自己的文件（DB + 物理文件）"""
        file_obj = self.own['deleter']['file']
        self.assertTrue(os.path.exists(file_obj.file_path))
        resp = self.clients['deleter'].delete(
            f'/document/file/?id={file_obj.id}&is_public=true')
        self.assertFalse(has_error(resp), resp.json())
        self.assertFalse(DocumentFilePublic.objects.filter(id=file_obj.id).exists())
        self.assertFalse(os.path.exists(file_obj.file_path))

    def test_13_deleter_can_delete_own_folder(self):
        """删除角色可以删除自己的目录"""
        folder = self.own['deleter']['folder']
        resp = self.clients['deleter'].delete(
            f'{FOLDER_URL}?id={folder.id}&is_public=true')
        self.assertFalse(has_error(resp), resp.json())
        self.assertFalse(DocumentFolderPublic.objects.filter(id=folder.id).exists())

    # ---------- 5. 对象级归属校验 ----------

    def test_14_cannot_delete_other_users_public_file(self):
        """非创建人不能删除公共空间他人文件 -> not_owner"""
        target = self.own['deleter']['file']
        resp = self.clients['normal_only'].delete(
            f'/document/file/?id={target.id}&is_public=true')
        body = resp.json()
        self.assertTrue(body.get('error'), body)
        self.assertEqual(body.get('code'), 403)
        self.assertEqual(body.get('reason'), 'not_owner')
        self.assertTrue(DocumentFilePublic.objects.filter(id=target.id).exists())

    def test_15_cannot_rename_other_users_public_file(self):
        """非创建人不能重命名他人文件"""
        target = self.own['deleter']['file']
        old_name = target.display_name
        resp = post_json(self.clients['normal_only'], '/document/file/rename/',
                         {'id': target.id, 'name': 'hacked.txt', 'is_public': True})
        body = resp.json()
        self.assertTrue(body.get('error'), body)
        self.assertEqual(body.get('reason'), 'not_owner')
        target.refresh_from_db()
        self.assertEqual(target.display_name, old_name)

    def test_16_cannot_move_other_users_public_folder(self):
        """非创建人不能移动他人目录"""
        target = self.own['deleter']['folder']
        other = self.own['normal_only']['folder']
        resp = post_json(self.clients['normal_only'], '/document/folder/move/',
                         {'id': target.id, 'target_id': other.id, 'is_public': True})
        self.assertTrue(resp.json().get('error'), resp.json())
        target.refresh_from_db()
        self.assertIsNone(target.parent_id)

    # ---------- 6. 普通权限与党建权限不可互相替代 ----------

    def test_17_normal_perms_cannot_access_pb(self):
        """只有普通资料库权限 -> 访问党建上下文被拒"""
        resp = self.clients['normal_only'].get(
            FOLDER_URL, {'id': self.pb_root.id, 'is_public': 'true',
                         'system_folder': PB})
        self.assertEqual(resp.json().get('error'), '权限拒绝', resp.json())

    def test_18_pb_perms_cannot_access_normal_library(self):
        """只有党建权限 -> 访问普通资料库被拒"""
        resp = self.clients['pb_only'].get(FOLDER_URL, {'is_public': 'true'})
        self.assertEqual(resp.json().get('error'), '权限拒绝', resp.json())

    def test_19_pb_perms_can_access_pb(self):
        """党建权限 -> 可以访问党建目录"""
        resp = self.clients['pb_only'].get(
            FOLDER_URL, {'id': self.pb_root.id, 'is_public': 'true',
                         'system_folder': PB})
        self.assertFalse(has_error(resp), resp.json())

    def test_20_pb_perms_cannot_delete_via_normal_context(self):
        """党建权限用户在普通上下文删除普通文件 -> 被拒"""
        target = self.own['normal_only']['file']
        resp = self.clients['pb_only'].delete(
            f'/document/file/?id={target.id}&is_public=true')
        self.assertEqual(resp.json().get('error'), '权限拒绝', resp.json())
        self.assertTrue(DocumentFilePublic.objects.filter(id=target.id).exists())

    def test_21_spoof_system_folder_cannot_bypass_perm(self):
        """普通权限用户伪造 system_folder 不得提升为党建访问"""
        resp = self.clients['normal_only'].get(
            FOLDER_URL, {'id': self.pb_root.id, 'is_public': 'true',
                         'system_folder': 'industry_rules'})
        # industry_rules 是 legacy 别名，归一化后仍需党建权限
        self.assertEqual(resp.json().get('error'), '权限拒绝', resp.json())

    # ---------- 7. 传输记录归属 ----------

    def test_22_cannot_update_progress_of_other_users_transfer(self):
        """不能更新他人传输记录进度"""
        target = DocumentTransfer.objects.create(
            tenant_id='admin', user=self.deleter, transfer_type='UPLOAD',
            status='UPLOADING', file_name='other.txt', file_size=1024,
            file_path='', is_public=True)
        resp = post_json(self.clients['normal_only'],
                         f'/document/transfers/{target.id}/progress/',
                         {'progress': 50})
        self.assertTrue(resp.json().get('error'), resp.json())

    def test_23_cannot_delete_other_users_transfer(self):
        """不能删除他人传输记录"""
        target = DocumentTransfer.objects.create(
            tenant_id='admin', user=self.deleter, transfer_type='UPLOAD',
            status='COMPLETED', file_name='other2.txt', file_size=1024,
            file_path='', is_public=True)
        resp = self.clients['normal_only'].delete(
            f'/document/transfers/{target.id}/delete/')
        self.assertTrue(resp.json().get('error'), resp.json())
        self.assertTrue(DocumentTransfer.objects.filter(id=target.id).exists())

    def test_24_transfer_list_only_returns_own(self):
        """传输记录列表只返回自己的记录"""
        mine = DocumentTransfer.objects.create(
            tenant_id='admin', user=self.normal_only, transfer_type='UPLOAD',
            status='PENDING', file_name='mine.txt', file_size=1024,
            file_path='', is_public=True)
        others = DocumentTransfer.objects.create(
            tenant_id='admin', user=self.deleter, transfer_type='UPLOAD',
            status='PENDING', file_name='theirs.txt', file_size=1024,
            file_path='', is_public=True)
        resp = self.clients['normal_only'].get('/document/transfers/',
                                               {'is_public': 'true'})
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp) or []
        ids = [t['id'] if isinstance(t, dict) else t for t in data]
        self.assertIn(mine.id, ids)
        self.assertNotIn(others.id, ids)

    # ---------- 8. HTTP 200 + error 必须识别为业务失败 ----------

    def test_25_business_error_uses_http_200_with_error_field(self):
        """业务失败返回 HTTP 200 + error 字段（不是 4xx/5xx）"""
        resp = self.clients['noperm'].get(FOLDER_URL, {'is_public': 'true'})
        self.assertEqual(resp.status_code, 200, '本项目约定业务失败用 HTTP 200 + error')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(resp.json().get('data'), '', 'error 非空时 data 必须为空')

    def test_26_success_response_has_empty_error(self):
        """成功响应 error 为空字符串"""
        resp = self.clients['viewer'].get(FOLDER_URL, {'is_public': 'true'})
        self.assertEqual(resp.json().get('error'), '')

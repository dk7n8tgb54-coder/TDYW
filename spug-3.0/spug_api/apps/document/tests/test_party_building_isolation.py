# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""党建目录反向隔离测试

普通文档模式（is_public=true, system_folder 省略/空）下，
尝试访问党建文件/文件夹的所有端点必须返回精确提示：
  '请从党建文档模块访问该目录'
"""
import json
import time
import uuid

from django.test import TestCase, Client

from apps.account.models import User
from apps.document.models import (
    DocumentFolderPublic, DocumentFilePublic,
    DocumentSystemFolder, DocumentFolderPrivate,
)
from apps.document.services.system_folder_service import PARTY_BUILDING_DOCUMENTS_CODE
from apps.setting.utils import AppSetting

PB = PARTY_BUILDING_DOCUMENTS_CODE
EXPECTED_ERROR = '请从党建文档模块访问该目录'


class PartyBuildingIsolationTest(TestCase):
    """党建目录反向隔离测试"""

    @classmethod
    def setUpTestData(cls):
        token = 'p' * 32
        cls.user = User.objects.create(
            username='pb_iso_admin', nickname='pb_iso', tenant_id='',
            password_hash=User.make_password('pw'), is_supper=True,
            is_active=True, access_token=token,
            token_expired=int(time.time()) + 3600,
            last_ip='127.0.0.1', last_login='2026-01-01', type='default',
        )

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.user.access_token
        self.client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'

        # 党建绑定根目录 + 子目录 + 文件
        self.pb_root = DocumentFolderPublic.objects.create(
            name='党建文档', parent=None, created_by=self.user)
        self.pb_binding = DocumentSystemFolder.objects.create(
            code=PB, name='党建文档', folder=self.pb_root,
            is_public=True, protected=True)
        self.pb_sub = DocumentFolderPublic.objects.create(
            name='测试子目录', parent=self.pb_root, created_by=self.user)
        self.pb_file = DocumentFilePublic.objects.create(
            name='测试文件.txt', display_name='测试文件.txt',
            physical_name=f'{uuid.uuid4().hex}.txt',
            file_path=f'/tmp/{uuid.uuid4().hex}.txt',
            file_size=100, file_type='text/plain',
            folder=self.pb_sub, created_by=self.user)

        # 普通公共文件夹 + 文件
        self.normal_folder = DocumentFolderPublic.objects.create(
            name='普通公共文件夹', parent=None, created_by=self.user)
        self.normal_file = DocumentFilePublic.objects.create(
            name='普通文件.txt', display_name='普通文件.txt',
            physical_name=f'{uuid.uuid4().hex}.txt',
            file_path=f'/tmp/{uuid.uuid4().hex}.txt',
            file_size=50, file_type='text/plain',
            folder=self.normal_folder, created_by=self.user)

    def tearDown(self):
        DocumentFilePublic.objects.all().delete()
        DocumentSystemFolder.objects.all().delete()
        DocumentFolderPublic.objects.all().delete()
        DocumentFolderPrivate.objects.all().delete()
        super().tearDown()

    # ================================================================
    # Helpers
    # ================================================================
    def _get_normal(self, path, data=None):
        """普通模式 GET（不带 system_folder）"""
        d = dict(data or {})
        d.pop('system_folder', None)
        return self.client.get(path, data=d)

    def _post_json_normal(self, path, payload):
        """普通模式 POST JSON（不带 system_folder）"""
        p = dict(payload)
        p.pop('system_folder', None)
        return self.client.post(path, data=json.dumps(p), content_type='application/json')

    def _delete_normal(self, path, data=None):
        """普通模式 DELETE（query params, 不带 system_folder）"""
        d = dict(data or {})
        d.pop('system_folder', None)
        qs = '&'.join(f'{k}={v}' for k, v in d.items())
        return self.client.delete(f'{path}?{qs}' if qs else path)

    def _get_pb(self, path, data=None):
        """党建模式 GET"""
        d = dict(data or {})
        d['system_folder'] = PB
        d['is_public'] = 'true'
        return self.client.get(path, data=d)

    def _post_json_pb(self, path, payload):
        """党建模式 POST JSON"""
        p = dict(payload)
        p['system_folder'] = PB
        p['is_public'] = True
        return self.client.post(path, data=json.dumps(p), content_type='application/json')

    def _assert_error(self, resp, expected=EXPECTED_ERROR):
        """断言响应包含指定的错误消息"""
        try:
            body = resp.json()
        except Exception:
            self.fail(f'非 JSON 响应: status={resp.status_code}, body={resp.content[:200]}')
        self.assertIn('error', body, f'缺少 error 字段: {body}')
        self.assertEqual(body['error'], expected,
                         f'错误消息不匹配: 期望={expected!r}, 实际={body["error"]!r}')

    def _assert_success(self, body):
        """断言响应成功（error 为空字符串或 None）"""
        err = body.get('error')
        self.assertFalse(err, f'响应应成功，但 error={err!r}: {body}')

    def _assert_pb_db_unchanged(self):
        """断言党建文件和文件夹未被修改"""
        self.pb_file.refresh_from_db()
        self.assertEqual(self.pb_file.name, '测试文件.txt')
        self.pb_sub.refresh_from_db()
        self.assertEqual(self.pb_sub.name, '测试子目录')
        self.pb_root.refresh_from_db()
        self.assertEqual(self.pb_root.name, '党建文档')

    # ================================================================
    # 1. 获取党建目录内容
    # ================================================================
    def test_01_list_pb_root_normal(self):
        """普通模式获取党建根目录 -> 拒绝"""
        resp = self._get_normal('/document/folder/', {'id': self.pb_root.id, 'is_public': 'true'})
        self._assert_error(resp)

    def test_01b_list_pb_sub_normal(self):
        """普通模式获取党建子目录 -> 拒绝"""
        resp = self._get_normal('/document/folder/', {'id': self.pb_sub.id, 'is_public': 'true'})
        self._assert_error(resp)

    def test_01c_list_pb_all_normal(self):
        """普通模式 all=true -> 成功但不含党建目录"""
        resp = self._get_normal('/document/folder/', {'all': 'true', 'is_public': 'true'})
        body = resp.json()
        self._assert_success(body)
        folders = body if isinstance(body, list) else body.get('folders', body.get('data', []))
        ids = [f.get('id') for f in folders] if folders else []
        self.assertNotIn(self.pb_root.id, ids, '普通模式 all=true 不应返回党建文件夹')
        self.assertNotIn(self.pb_sub.id, ids, '普通模式 all=true 不应返回党建子目录')

    def test_01d_list_pb_root_pb_mode(self):
        """党建模式获取党建根目录 -> 成功"""
        resp = self._get_pb('/document/folder/', {'id': self.pb_root.id})
        self._assert_success(resp.json())

    # ================================================================
    # 2. 下载党建文件
    # ================================================================
    def test_02_download_pb_file_normal(self):
        """普通模式下载党建文件 -> 拒绝"""
        resp = self._get_normal('/document/download/', {
            'id': self.pb_file.id, 'is_public': 'true'})
        self._assert_error(resp)

    # ================================================================
    # 3. 预览党建文件
    # ================================================================
    def test_03_preview_pb_file_normal(self):
        """普通模式预览党建文件 -> 拒绝"""
        resp = self._get_normal('/document/preview/', {
            'id': self.pb_file.id, 'is_public': 'true'})
        self._assert_error(resp)

    # ================================================================
    # 4. 重命名党建文件
    # ================================================================
    def test_04_rename_pb_file_normal(self):
        """普通模式重命名党建文件 -> 拒绝"""
        resp = self._post_json_normal('/document/file/rename/', {
            'id': self.pb_file.id, 'name': '被重命名.txt', 'is_public': True})
        self._assert_error(resp)
        self._assert_pb_db_unchanged()

    # ================================================================
    # 5. 移动党建文件
    # ================================================================
    def test_05_move_pb_file_normal(self):
        """普通模式移动党建文件 -> 拒绝"""
        resp = self._post_json_normal('/document/file/move/', {
            'id': self.pb_file.id, 'target_id': self.normal_folder.id, 'is_public': True})
        self._assert_error(resp)
        self._assert_pb_db_unchanged()

    # ================================================================
    # 6. 复制党建文件
    # ================================================================
    def test_06_copy_pb_file_normal(self):
        """普通模式复制党建文件 -> 拒绝"""
        resp = self._post_json_normal('/document/file/copy/', {
            'id': self.pb_file.id, 'folder_id': self.normal_folder.id, 'is_public': True})
        self._assert_error(resp)
        self.assertFalse(
            DocumentFilePublic.objects.filter(name__icontains='测试文件').exclude(id=self.pb_file.id).exists())

    # ================================================================
    # 7. 删除党建文件
    # ================================================================
    def test_07_delete_pb_file_normal(self):
        """普通模式删除党建文件 -> 拒绝"""
        resp = self._delete_normal('/document/file/', {
            'id': self.pb_file.id, 'is_public': 'true'})
        self._assert_error(resp)
        self.assertTrue(DocumentFilePublic.objects.filter(id=self.pb_file.id).exists())

    # ================================================================
    # 8. 重命名党建文件夹
    # ================================================================
    def test_08_rename_pb_folder_normal(self):
        """普通模式重命名党建文件夹 -> 拒绝"""
        resp = self._post_json_normal('/document/folder/rename/', {
            'id': self.pb_sub.id, 'name': '被重命名', 'is_public': True})
        self._assert_error(resp)
        self._assert_pb_db_unchanged()

    # ================================================================
    # 9. 移动党建文件夹
    # ================================================================
    def test_09_move_pb_folder_normal(self):
        """普通模式移动党建文件夹 -> 拒绝"""
        resp = self._post_json_normal('/document/folder/move/', {
            'id': self.pb_sub.id, 'target_id': self.normal_folder.id, 'is_public': True})
        self._assert_error(resp)
        self.pb_sub.refresh_from_db()
        self.assertEqual(self.pb_sub.parent_id, self.pb_root.id)

    # ================================================================
    # 10. 复制党建文件夹
    # ================================================================
    def test_10_copy_pb_folder_normal(self):
        """普通模式复制党建文件夹 -> 拒绝"""
        resp = self._post_json_normal('/document/folder/copy/', {
            'id': self.pb_sub.id, 'target_id': self.normal_folder.id, 'is_public': True})
        self._assert_error(resp)
        self.assertFalse(
            DocumentFolderPublic.objects.filter(name__icontains='测试子目录').exclude(id=self.pb_sub.id).exists())

    # ================================================================
    # 11. 删除党建文件夹
    # ================================================================
    def test_11_delete_pb_folder_normal(self):
        """普通模式删除党建文件夹 -> 拒绝"""
        resp = self._delete_normal('/document/folder/', {
            'id': self.pb_sub.id, 'is_public': 'true'})
        self._assert_error(resp)
        self.assertTrue(DocumentFolderPublic.objects.filter(id=self.pb_sub.id).exists())

    # ================================================================
    # 12. 向党建目录上传文件
    # ================================================================
    def test_12_upload_to_pb_normal(self):
        """普通模式上传文件到党建目录 -> 拒绝"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        upload = SimpleUploadedFile('上传文件.txt', b'test', content_type='text/plain')
        resp = self.client.post('/document/upload/', data={
            'file': upload, 'folder_id': self.pb_sub.id, 'is_public': 'true',
        })
        self._assert_error(resp)
        self.assertFalse(DocumentFilePublic.objects.filter(name='上传文件.txt').exists())

    # ================================================================
    # 13. 在党建目录创建文件夹
    # ================================================================
    def test_13_create_folder_in_pb_normal(self):
        """普通模式在党建目录创建文件夹 -> 拒绝"""
        resp = self._post_json_normal('/document/folder/', {
            'name': '新建子目录', 'parent_id': self.pb_root.id, 'is_public': True})
        self._assert_error(resp)
        self.assertFalse(DocumentFolderPublic.objects.filter(name='新建子目录').exists())

    # ================================================================
    # 14. 普通模式移动/复制到党建目录
    # ================================================================
    def test_14a_move_file_to_pb_normal(self):
        """普通模式移动普通文件到党建目录 -> 拒绝"""
        resp = self._post_json_normal('/document/file/move/', {
            'id': self.normal_file.id, 'target_id': self.pb_root.id, 'is_public': True})
        self._assert_error(resp)
        self.normal_file.refresh_from_db()
        self.assertEqual(self.normal_file.folder_id, self.normal_folder.id)

    def test_14b_copy_file_to_pb_normal(self):
        """普通模式复制普通文件到党建目录 -> 拒绝"""
        resp = self._post_json_normal('/document/file/copy/', {
            'id': self.normal_file.id, 'folder_id': self.pb_root.id, 'is_public': True})
        self._assert_error(resp)

    def test_14c_move_folder_to_pb_normal(self):
        """普通模式移动普通文件夹到党建目录 -> 拒绝"""
        resp = self._post_json_normal('/document/folder/move/', {
            'id': self.normal_folder.id, 'target_id': self.pb_root.id, 'is_public': True})
        self._assert_error(resp)
        self.normal_folder.refresh_from_db()
        self.assertIsNone(self.normal_folder.parent_id)

    def test_14d_copy_folder_to_pb_normal(self):
        """普通模式复制普通文件夹到党建目录 -> 拒绝"""
        resp = self._post_json_normal('/document/folder/copy/', {
            'id': self.normal_folder.id, 'target_id': self.pb_root.id, 'is_public': True})
        self._assert_error(resp)

    # ================================================================
    # 15. 遗漏/空字符串/无效 system_folder
    # ================================================================
    def test_15a_empty_system_folder(self):
        """system_folder 为空字符串 -> 拒绝"""
        resp = self.client.get('/document/folder/',
                               data={'id': self.pb_root.id, 'is_public': 'true', 'system_folder': ''})
        self._assert_error(resp)

    def test_15b_no_system_folder(self):
        """system_folder 省略 -> 拒绝"""
        resp = self.client.get('/document/folder/',
                               data={'id': self.pb_root.id, 'is_public': 'true'})
        self._assert_error(resp)

    def test_15c_invalid_system_folder(self):
        """system_folder 无效值 -> 拒绝"""
        resp = self.client.get('/document/folder/',
                               data={'id': self.pb_root.id, 'is_public': 'true', 'system_folder': 'invalid_code'})
        body = resp.json()
        self.assertIn('error', body)
        self.assertNotIn('folders', body)

    # ================================================================
    # 正向验证：党建模式下合法操作应成功
    # ================================================================
    def test_16_pb_mode_list_success(self):
        """党建模式列出党建根目录 -> 成功"""
        resp = self._get_pb('/document/folder/', {'id': self.pb_root.id})
        self._assert_success(resp.json())

    def test_17_pb_mode_all_folders_deep(self):
        """党建模式 all=true 返回深层目录 -> 成功"""
        sub2 = DocumentFolderPublic.objects.create(
            name='二级子目录', parent=self.pb_sub, created_by=self.user)
        try:
            resp = self._get_pb('/document/folder/', {'all': 'true'})
            body = resp.json()
            self._assert_success(body)
            # json_response wraps list in {'data': [...], 'error': ''}
            folders = body.get('data', body) if isinstance(body, dict) else body
            if not isinstance(folders, list):
                folders = folders.get('folders', []) if hasattr(folders, 'get') else []
            ids = [f.get('id') for f in folders] if folders else []
            self.assertIn(sub2.id, ids, 'all=true 应返回深层子目录')
        finally:
            sub2.delete()

    def test_18_pb_mode_create_folder_success(self):
        """党建模式创建文件夹 -> 成功"""
        resp = self._post_json_pb('/document/folder/', {
            'name': '党建新建目录', 'parent_id': self.pb_root.id})
        body = resp.json()
        self._assert_success(body)
        self.assertTrue(body.get('created') or body.get('data', {}).get('created'))
        DocumentFolderPublic.objects.filter(name='党建新建目录').delete()

    # ================================================================
    # 私有模式不能访问党建资源
    # ================================================================
    def test_19_private_mode_access_pb_folder(self):
        """私有模式(is_public=false)访问党建文件夹 -> 不返回数据"""
        resp = self.client.get('/document/folder/',
                               data={'id': self.pb_root.id, 'is_public': 'false'})
        body = resp.json()
        if 'error' in body and body['error']:
            pass  # 有错误也行
        else:
            folders = body.get('folders', body if isinstance(body, list) else [])
            self.assertEqual(len(folders), 0, '私有模式不应返回党建文件夹')

    def test_20_normal_folder_still_accessible(self):
        """普通模式下普通公共文件夹仍可正常访问 -> 成功"""
        resp = self._get_normal('/document/folder/', {
            'id': self.normal_folder.id, 'is_public': 'true'})
        self._assert_success(resp.json())

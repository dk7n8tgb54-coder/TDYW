"""党建文档系统目录隔离发布门禁测试（stable_contract）。

设计原则（fail-closed）：
- 党建上下文 -> 对象必须落在党建 scope 内
- 普通公共上下文 -> 对象必须不在任何系统 scope 内（反向隔离）
- 源与目标独立校验，跨 scope 一律拒绝
"""
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.document.libs.document_utils import (
    get_document_absolute_path, get_document_storage_base_path, is_safe_path)
from apps.document.models import (
    DocumentFilePublic, DocumentFolderPublic, DocumentSystemFolder)
from tests.helpers.test_base import (
    get_response_data, has_error, make_client, make_user, post_json, setup_test_env)

from .helpers import (
    PB, StorageCleanupMixin, bind_party_building, make_file, make_folder, unique)

NORMAL_SCOPE_ERR = '请从党建文档模块访问该目录'
SCOPE_ERR = '无权访问党建文档目录外的资料'
PROTECTED_ROOT_ERR = '党建文档根目录不允许删除、重命名或移动'
UPLOAD_TARGET_ERR = '党建文档文件必须上传到党建文档目录内'
MUST_PUBLIC_ERR = '党建文档模式仅支持公共空间'

FOLDER_URL = '/document/folder/'
UPLOAD_URL = '/document/upload/'


class PartyBuildingIsolationTest(StorageCleanupMixin, TestCase):
    """党建目录与公共资料库双向隔离"""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user('pb_gate_admin', is_supper=True)

    def setUp(self):
        super().setUp()
        setup_test_env()
        self.client = make_client(self.admin)
        self.client.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'

        # 党建根目录 + 绑定 + 子目录 + 文件
        self.pb_root = make_folder(name=unique('党建文档'), created_by=self.admin)
        self.binding = bind_party_building(self.pb_root)
        self.pb_sub = make_folder(name=unique('党建子目录'),
                                  parent=self.pb_root, created_by=self.admin)
        self.pb_file = make_file(folder=self.pb_sub, created_by=self.admin,
                                 name=unique('党建文件') + '.txt')
        self.track_path(self.pb_file.file_path)

        # 普通公共目录 + 文件
        self.normal_folder = make_folder(name=unique('普通目录'), created_by=self.admin)
        self.normal_file = make_file(folder=self.normal_folder, created_by=self.admin,
                                     name=unique('普通文件') + '.txt')
        self.track_path(self.normal_file.file_path)

    # ---------- helpers ----------

    def _pb_params(self, extra=None):
        d = {'is_public': True, 'system_folder': PB}
        d.update(extra or {})
        return d

    def _get_pb(self, url, extra=None):
        return self.client.get(url, self._pb_params(extra))

    def _get_normal(self, url, extra=None):
        d = {'is_public': True}
        d.update(extra or {})
        return self.client.get(url, d)

    def _post_pb(self, url, payload):
        p = self._pb_params(payload)
        return post_json(self.client, url, p)

    def _post_normal(self, url, payload):
        p = {'is_public': True}
        p.update(payload)
        return post_json(self.client, url, p)

    def _delete_qs(self, url, params):
        qs = '&'.join(f'{k}={v}' for k, v in params.items())
        return self.client.delete(f'{url}?{qs}')

    # ---------- 1. 合法党建上下文 ----------

    def test_01_pb_context_can_list_pb_root(self):
        """党建上下文可读党建根目录"""
        resp = self._get_pb(FOLDER_URL, {'id': self.pb_root.id})
        self.assertFalse(has_error(resp), resp.json())

    def test_02_pb_context_can_list_pb_sub(self):
        """党建上下文可读党建子目录"""
        resp = self._get_pb(FOLDER_URL, {'id': self.pb_sub.id})
        self.assertFalse(has_error(resp), resp.json())

    def test_03_pb_context_can_download_pb_file(self):
        """党建上下文可下载党建文件"""
        resp = self._get_pb('/document/download/', {'id': self.pb_file.id})
        self.assertEqual(resp.status_code, 200)
        if resp['Content-Type'].startswith('application/json'):
            self.assertFalse(has_error(resp), resp.json())
        else:
            self.assertIn('attachment', resp.get('Content-Disposition', ''))

    # ---------- 2. 普通上下文不能访问党建 ----------

    def test_04_normal_context_cannot_list_pb_root(self):
        """普通上下文列党建根目录 -> 拒绝"""
        resp = self._get_normal(FOLDER_URL, {'id': self.pb_root.id})
        self.assertEqual(resp.json().get('error'), NORMAL_SCOPE_ERR, resp.json())

    def test_05_normal_context_cannot_list_pb_sub(self):
        """普通上下文列党建子目录 -> 拒绝"""
        resp = self._get_normal(FOLDER_URL, {'id': self.pb_sub.id})
        self.assertEqual(resp.json().get('error'), NORMAL_SCOPE_ERR, resp.json())

    def test_06_normal_context_cannot_download_pb_file(self):
        """普通上下文下载党建文件 -> 拒绝"""
        resp = self._get_normal('/document/download/', {'id': self.pb_file.id})
        self.assertEqual(resp.json().get('error'), NORMAL_SCOPE_ERR, resp.json())

    def test_07_normal_context_cannot_preview_pb_file(self):
        """普通上下文预览党建文件 -> 拒绝"""
        resp = self._get_normal('/document/preview/', {'id': self.pb_file.id})
        self.assertEqual(resp.json().get('error'), NORMAL_SCOPE_ERR, resp.json())

    def test_08_normal_context_cannot_rename_pb_file(self):
        """普通上下文重命名党建文件 -> 拒绝且数据不变"""
        resp = self._post_normal('/document/file/rename/',
                                 {'id': self.pb_file.id, 'name': 'hacked.txt'})
        self.assertTrue(has_error(resp), resp.json())
        self.pb_file.refresh_from_db()
        self.assertNotEqual(self.pb_file.display_name, 'hacked.txt')

    def test_09_normal_context_cannot_delete_pb_file(self):
        """普通上下文删除党建文件 -> 拒绝且记录保留"""
        resp = self._delete_qs('/document/file/',
                               {'id': self.pb_file.id, 'is_public': 'true'})
        self.assertTrue(has_error(resp), resp.json())
        self.assertTrue(DocumentFilePublic.objects.filter(id=self.pb_file.id).exists())

    def test_10_normal_context_cannot_delete_pb_folder(self):
        """普通上下文删除党建目录 -> 拒绝"""
        resp = self._delete_qs('/document/folder/',
                               {'id': self.pb_sub.id, 'is_public': 'true'})
        self.assertTrue(has_error(resp), resp.json())
        self.assertTrue(DocumentFolderPublic.objects.filter(id=self.pb_sub.id).exists())

    def test_11_normal_context_cannot_upload_into_pb_folder(self):
        """普通上下文向党建目录上传 -> 拒绝"""
        resp = self.client.post(UPLOAD_URL, data={
            'file': SimpleUploadedFile('injected.txt', b'x', content_type='text/plain'),
            'folder_id': self.pb_sub.id,
            'is_public': 'true',
        })
        self.assertTrue(has_error(resp), resp.json())
        self.assertFalse(DocumentFilePublic.objects.filter(display_name='injected.txt').exists())

    def test_12_normal_context_cannot_create_folder_in_pb_root(self):
        """普通上下文在党建目录建子目录 -> 拒绝"""
        resp = self._post_normal(FOLDER_URL,
                                 {'name': unique('注入目录'), 'parent_id': self.pb_root.id})
        self.assertTrue(has_error(resp), resp.json())

    def test_13_normal_mode_hides_pb_from_root_listing(self):
        """普通模式根目录列表不包含党建目录"""
        resp = self._get_normal(FOLDER_URL)
        data = get_response_data(resp)
        self.assertNotIn(self.pb_root.id, [f['id'] for f in data['folders']])

    def test_14_normal_mode_hides_pb_from_all_folders(self):
        """普通模式 all=true 不包含党建目录"""
        resp = self._get_normal(FOLDER_URL, {'all': 'true'})
        body = resp.json()
        folders = body.get('data') or []
        self.assertNotIn(self.pb_root.id, [f['id'] for f in folders])
        self.assertNotIn(self.pb_sub.id, [f['id'] for f in folders])

    # ---------- 3. 普通 -> 党建 的移动/复制 ----------

    def test_15_normal_cannot_move_file_into_pb(self):
        """普通上下文移动普通文件到党建目录 -> 拒绝"""
        resp = self._post_normal('/document/file/move/',
                                 {'id': self.normal_file.id, 'target_id': self.pb_root.id})
        self.assertTrue(has_error(resp), resp.json())
        self.normal_file.refresh_from_db()
        self.assertEqual(self.normal_file.folder_id, self.normal_folder.id)

    def test_16_normal_cannot_copy_file_into_pb(self):
        """普通上下文复制普通文件到党建目录 -> 拒绝"""
        resp = self._post_normal('/document/file/copy/',
                                 {'id': self.normal_file.id, 'folder_id': self.pb_sub.id})
        self.assertTrue(has_error(resp), resp.json())
        self.assertFalse(DocumentFilePublic.objects.filter(
            folder_id=self.pb_sub.id).exclude(id=self.pb_file.id).exists())

    def test_17_normal_cannot_move_folder_into_pb(self):
        """普通上下文移动普通目录到党建目录 -> 拒绝"""
        resp = self._post_normal('/document/folder/move/',
                                 {'id': self.normal_folder.id, 'target_id': self.pb_root.id})
        self.assertTrue(has_error(resp), resp.json())
        self.normal_folder.refresh_from_db()
        self.assertIsNone(self.normal_folder.parent_id)

    # ---------- 4. 党建 -> 普通 的移动/复制 ----------

    def test_18_pb_cannot_move_file_out(self):
        """党建上下文把文件移出党建目录 -> 拒绝"""
        resp = self._post_pb('/document/file/move/',
                             {'id': self.pb_file.id, 'target_id': self.normal_folder.id})
        self.assertTrue(has_error(resp), resp.json())
        self.pb_file.refresh_from_db()
        self.assertEqual(self.pb_file.folder_id, self.pb_sub.id)

    def test_19_pb_cannot_copy_file_out(self):
        """党建上下文把文件复制到普通目录 -> 拒绝"""
        resp = self._post_pb('/document/file/copy/',
                             {'id': self.pb_file.id, 'folder_id': self.normal_folder.id})
        self.assertTrue(has_error(resp), resp.json())

    def test_20_pb_cannot_move_folder_out(self):
        """党建上下文把目录移出党建目录 -> 拒绝"""
        resp = self._post_pb('/document/folder/move/',
                             {'id': self.pb_sub.id, 'target_id': self.normal_folder.id})
        self.assertTrue(has_error(resp), resp.json())
        self.pb_sub.refresh_from_db()
        self.assertEqual(self.pb_sub.parent_id, self.pb_root.id)

    def test_21_pb_cannot_move_file_to_root(self):
        """党建上下文把文件移到根目录（脱离党建）-> 拒绝"""
        resp = self._post_pb('/document/file/move/',
                             {'id': self.pb_file.id, 'target_id': None})
        self.assertTrue(has_error(resp), resp.json())
        self.pb_file.refresh_from_db()
        self.assertEqual(self.pb_file.folder_id, self.pb_sub.id)

    # ---------- 5. 党建根目录保护 ----------

    def test_22_pb_root_cannot_be_deleted(self):
        """党建根目录不允许删除"""
        resp = self._delete_qs('/document/folder/',
                               {'id': self.pb_root.id, 'is_public': 'true',
                                'system_folder': PB})
        self.assertEqual(resp.json().get('error'), PROTECTED_ROOT_ERR, resp.json())
        self.assertTrue(DocumentFolderPublic.objects.filter(id=self.pb_root.id).exists())

    def test_23_pb_root_cannot_be_renamed(self):
        """党建根目录不允许重命名"""
        resp = self._post_pb('/document/folder/rename/',
                             {'id': self.pb_root.id, 'name': '被改名'})
        self.assertEqual(resp.json().get('error'), PROTECTED_ROOT_ERR, resp.json())
        self.pb_root.refresh_from_db()
        self.assertNotEqual(self.pb_root.name, '被改名')

    def test_24_pb_root_cannot_be_moved(self):
        """党建根目录不允许移动"""
        resp = self._post_pb('/document/folder/move/',
                             {'id': self.pb_root.id, 'target_id': self.normal_folder.id})
        self.assertEqual(resp.json().get('error'), PROTECTED_ROOT_ERR, resp.json())
        self.pb_root.refresh_from_db()
        self.assertIsNone(self.pb_root.parent_id)

    # ---------- 6. 无效 / 缺失 system_folder 必须 fail-closed ----------

    def test_25_missing_system_folder_rejected(self):
        """省略 system_folder 访问党建目录 -> 拒绝"""
        resp = self._get_normal(FOLDER_URL, {'id': self.pb_root.id})
        self.assertEqual(resp.json().get('error'), NORMAL_SCOPE_ERR, resp.json())

    def test_26_empty_system_folder_rejected(self):
        """system_folder 为空串访问党建目录 -> 拒绝"""
        resp = self.client.get(FOLDER_URL, {'id': self.pb_root.id,
                                            'is_public': 'true', 'system_folder': ''})
        self.assertEqual(resp.json().get('error'), NORMAL_SCOPE_ERR, resp.json())

    def test_27_invalid_system_folder_rejected(self):
        """非法 system_folder -> 拒绝且不返回数据"""
        resp = self.client.get(FOLDER_URL, {'id': self.pb_root.id,
                                            'is_public': 'true',
                                            'system_folder': 'evil_code'})
        body = resp.json()
        self.assertTrue(body.get('error'), body)
        self.assertNotIn('folders', body)

    def test_28_invalid_system_folder_does_not_fallback_to_normal_perm(self):
        """非法 system_folder 不得回退到普通权限（fail-closed）"""
        resp = self.client.get(FOLDER_URL, {'is_public': 'true',
                                            'system_folder': 'evil_code'})
        self.assertTrue(resp.json().get('error'), resp.json())

    def test_29_pb_requires_public_space(self):
        """党建上下文 + is_public=false -> 拒绝"""
        resp = self.client.get(FOLDER_URL, {'id': self.pb_root.id,
                                            'is_public': 'false',
                                            'system_folder': PB})
        self.assertEqual(resp.json().get('error'), MUST_PUBLIC_ERR, resp.json())

    def test_30_pb_upload_requires_folder(self):
        """党建上下文上传必须指定党建目录"""
        resp = self.client.post(UPLOAD_URL, data={
            'file': SimpleUploadedFile('pb_root.txt', b'x', content_type='text/plain'),
            'is_public': 'true',
            'system_folder': PB,
        })
        self.assertEqual(resp.json().get('error'), UPLOAD_TARGET_ERR, resp.json())

    # ---------- 7. 搜索隔离 ----------

    def test_31_normal_search_does_not_return_pb(self):
        """普通模式搜索不到党建文件/目录"""
        resp = self._get_normal('/document/folder/search/',
                                {'keyword': self.pb_file.display_name})
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertNotIn(self.pb_file.id, [f['id'] for f in data['files']])
        self.assertNotIn(self.pb_sub.id, [f['id'] for f in data['folders']])

    def test_32_pb_search_does_not_return_normal(self):
        """党建模式搜索不到公共资料库文件/目录"""
        resp = self._get_pb('/document/folder/search/',
                            {'keyword': self.normal_file.display_name})
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertNotIn(self.normal_file.id, [f['id'] for f in data['files']])
        self.assertNotIn(self.normal_folder.id, [f['id'] for f in data['folders']])

    def test_33_pb_search_can_find_pb_file(self):
        """党建模式可以搜到自己的文件（正向能力不被隔离误伤）"""
        resp = self._get_pb('/document/folder/search/',
                            {'keyword': self.pb_file.display_name})
        data = get_response_data(resp)
        self.assertIn(self.pb_file.id, [f['id'] for f in data['files']])

    # ---------- 8. 党建上传物理路径归属 ----------

    def test_34_pb_upload_lands_in_party_building_storage(self):
        """党建上传的物理文件落在 party_building_documents 存储目录内"""
        fname = unique('pb上传') + '.txt'
        resp = self.client.post(UPLOAD_URL, data={
            'file': SimpleUploadedFile(fname, b'pb-content', content_type='text/plain'),
            'folder_id': self.pb_sub.id,
            'is_public': 'true',
            'system_folder': PB,
        })
        self.assertFalse(has_error(resp), resp.json())
        obj = DocumentFilePublic.objects.filter(display_name=fname).first()
        self.assertIsNotNone(obj)
        self.track_path(obj.file_path)
        expected_base = get_document_absolute_path(system_folder=PB)
        self.assertTrue(is_safe_path(expected_base, obj.file_path),
                        f'党建文件必须落在党建存储目录内: {obj.file_path}')
        self.assertIn('party_building_documents', obj.file_path)
        self.assertTrue(os.path.exists(obj.file_path))

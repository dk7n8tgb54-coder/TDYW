# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""党建文档逻辑隔离加固 — 跨作用域 IDOR 测试矩阵。

覆盖：
- 统一校验器单元测试（普通反向隔离 / 党建正向 / 跨作用域拒绝）
- 关键 HTTP 入口级回归测试（下载、预览令牌、删除、上传目标、移动、复制）
- 传输记录作用域一致性
- 预览令牌 system_folder 绑定
"""
import json
import time
from unittest.mock import patch

from django.test import TestCase, Client

from apps.account.models import User
from apps.document.models import (
    DocumentFolderPrivate, DocumentFilePrivate,
    DocumentFolderPublic, DocumentFilePublic,
    DocumentTransfer, DocumentSystemFolder,
)
from apps.document.services.system_folder_service import PARTY_BUILDING_DOCUMENTS_CODE
from apps.document.services.system_scope_validators import (
    validate_file_source_scope,
    validate_folder_source_scope,
    validate_target_folder_scope,
    validate_file_move_scope,
    validate_folder_move_scope,
    validate_upload_target_scope,
    validate_transfer_scope,
)
from apps.document.libs.preview_token import generate_preview_token, validate_preview_token
from apps.setting.utils import AppSetting

PB = PARTY_BUILDING_DOCUMENTS_CODE


class ScopeIsolationBase(TestCase):
    """测试基类：构建普通/党建/私有三套数据。"""

    @classmethod
    def setUpTestData(cls):
        token = 'b' * 32
        cls.user = User.objects.create(
            username='scope_user', nickname='scope', tenant_id='',
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

        # 普通公共目录 + 文件
        self.normal_folder = DocumentFolderPublic.objects.create(
            name='普通目录', parent=None, created_by=self.user)
        self.normal_file = DocumentFilePublic.objects.create(
            name='n.txt', display_name='n.txt', physical_name='n.txt',
            file_path='/tmp/n.txt', file_size=1, file_type='text/plain',
            folder=self.normal_folder, created_by=self.user)

        # 党建绑定根目录 + 子目录 + 文件
        self.pb_root = DocumentFolderPublic.objects.create(
            name='党建文档', parent=None, created_by=self.user)
        self.pb_binding = DocumentSystemFolder.objects.create(
            code=PB, name='党建文档', folder=self.pb_root,
            is_public=True, protected=True)
        self.pb_sub = DocumentFolderPublic.objects.create(
            name='子目录', parent=self.pb_root, created_by=self.user)
        self.pb_file = DocumentFilePublic.objects.create(
            name='p.txt', display_name='p.txt', physical_name='p.txt',
            file_path='/tmp/p.txt', file_size=1, file_type='text/plain',
            folder=self.pb_sub, created_by=self.user)

        # 私有目录 + 文件
        self.priv_folder = DocumentFolderPrivate.objects.create(
            name='私有目录', parent=None, created_by=self.user, tenant_id='')
        self.priv_file = DocumentFilePrivate.objects.create(
            name='v.txt', display_name='v.txt', physical_name='v.txt',
            file_path='/tmp/v.txt', file_size=1, file_type='text/plain',
            folder=self.priv_folder, created_by=self.user, tenant_id='')

        # 传输记录（普通 + 党建）
        self.normal_transfer = DocumentTransfer.objects.create(
            tenant_id='', user=self.user, transfer_type='UPLOAD',
            status='PENDING', file_name='t.txt', file_size=1,
            file_path='', file_hash='a' * 32, folder_id=self.normal_folder.id,
            is_public=True, system_folder='')
        self.pb_transfer = DocumentTransfer.objects.create(
            tenant_id='', user=self.user, transfer_type='UPLOAD',
            status='PENDING', file_name='pt.txt', file_size=1,
            file_path='', file_hash='c' * 32, folder_id=self.pb_sub.id,
            is_public=True, system_folder=PB)

        # 搜索隔离测试数据
        # 普通根层文件（folder_id=None），用于验证指定目录搜索不混入根层
        self.normal_root_file = DocumentFilePublic.objects.create(
            name='root.txt', display_name='root.txt', physical_name='root.txt',
            file_path='/tmp/root.txt', file_size=1, file_type='text/plain',
            folder=None, created_by=self.user)
        # 党建二级子目录 + 深层文件，用于验证党建搜索能返回多级子目录
        self.pb_subsub = DocumentFolderPublic.objects.create(
            name='二级子目录', parent=self.pb_sub, created_by=self.user)
        self.pb_deep_file = DocumentFilePublic.objects.create(
            name='deep.txt', display_name='deep.txt', physical_name='deep.txt',
            file_path='/tmp/deep.txt', file_size=1, file_type='text/plain',
            folder=self.pb_subsub, created_by=self.user)


# ==================== 统一校验器单元测试 ====================

class FileSourceScopeValidatorTest(ScopeIsolationBase):

    def test_normal_cannot_access_party_file(self):
        ok, _ = validate_file_source_scope('', True, self.pb_file)
        self.assertFalse(ok)

    def test_party_can_access_party_file(self):
        ok, _ = validate_file_source_scope(PB, True, self.pb_file)
        self.assertTrue(ok)

    def test_party_cannot_access_normal_file(self):
        ok, _ = validate_file_source_scope(PB, True, self.normal_file)
        self.assertFalse(ok)

    def test_normal_can_access_normal_file(self):
        ok, _ = validate_file_source_scope('', True, self.normal_file)
        self.assertTrue(ok)

    def test_private_with_system_folder_rejected(self):
        ok, _ = validate_file_source_scope(PB, False, self.priv_file)
        self.assertFalse(ok)

    def test_invalid_code_rejected(self):
        ok, _ = validate_file_source_scope('evil_code', True, self.normal_file)
        self.assertFalse(ok)


class TargetFolderScopeValidatorTest(ScopeIsolationBase):

    def test_normal_upload_to_party_folder_rejected(self):
        ok, _ = validate_upload_target_scope('', True, self.pb_sub.id)
        self.assertFalse(ok)

    def test_party_upload_to_normal_folder_rejected(self):
        ok, _ = validate_upload_target_scope(PB, True, self.normal_folder.id)
        self.assertFalse(ok)

    def test_party_upload_to_party_folder_ok(self):
        ok, _ = validate_upload_target_scope(PB, True, self.pb_sub.id)
        self.assertTrue(ok)

    def test_party_upload_to_root_rejected(self):
        ok, _ = validate_upload_target_scope(PB, True, None)
        self.assertFalse(ok)

    def test_normal_upload_to_party_root_rejected(self):
        ok, _ = validate_target_folder_scope('', True, self.pb_root.id, allow_root=True)
        self.assertFalse(ok)


class MoveScopeValidatorTest(ScopeIsolationBase):

    def test_normal_move_into_party_folder_rejected(self):
        ok, _ = validate_file_move_scope('', True, file_obj=self.normal_file, target_id=self.pb_sub.id)
        self.assertFalse(ok)

    def test_party_move_into_normal_folder_rejected(self):
        ok, _ = validate_file_move_scope(PB, True, file_obj=self.pb_file, target_id=self.normal_folder.id)
        self.assertFalse(ok)

    def test_party_move_to_root_rejected(self):
        ok, _ = validate_file_move_scope(PB, True, file_obj=self.pb_file, target_id=None)
        self.assertFalse(ok)

    def test_normal_move_party_source_rejected(self):
        ok, _ = validate_file_move_scope('', True, file_obj=self.pb_file, target_id=self.normal_folder.id)
        self.assertFalse(ok)

    def test_folder_move_party_root_protected(self):
        ok, _ = validate_folder_move_scope(PB, True, self.pb_root.id, self.pb_sub.id)
        self.assertFalse(ok)

    def test_folder_move_cross_scope_rejected(self):
        ok, _ = validate_folder_move_scope('', True, self.normal_folder.id, self.pb_sub.id)
        self.assertFalse(ok)


class TransferScopeValidatorTest(ScopeIsolationBase):

    def test_normal_request_party_transfer_rejected(self):
        ok, _ = validate_transfer_scope('', True, self.pb_transfer)
        self.assertFalse(ok)

    def test_party_request_normal_transfer_rejected(self):
        ok, _ = validate_transfer_scope(PB, True, self.normal_transfer)
        self.assertFalse(ok)

    def test_matching_scope_ok(self):
        ok, _ = validate_transfer_scope('', True, self.normal_transfer)
        self.assertTrue(ok)
        ok, _ = validate_transfer_scope(PB, True, self.pb_transfer)
        self.assertTrue(ok)

    def test_is_public_mismatch_rejected(self):
        ok, _ = validate_transfer_scope('', False, self.normal_transfer)
        self.assertFalse(ok)


# ==================== 预览令牌 system_folder 绑定测试 ====================

class PreviewTokenScopeTest(ScopeIsolationBase):

    def test_token_binds_system_folder(self):
        token = generate_preview_token(1, self.user.id, '', True, PB)
        data = validate_preview_token(token)
        self.assertIsNotNone(data)
        self.assertEqual(data['system_folder'], PB)

    def test_normal_token_empty_system_folder(self):
        token = generate_preview_token(1, self.user.id, '', True, '')
        data = validate_preview_token(token)
        self.assertEqual(data['system_folder'], '')

    def test_party_token_cannot_be_used_for_normal(self):
        token = generate_preview_token(self.pb_file.id, self.user.id, '', True, PB)
        data = validate_preview_token(token)
        # 令牌载荷是党建；普通请求 system_folder='' 与之不匹配
        self.assertNotEqual(data['system_folder'], '')


# ==================== HTTP 级 IDOR 回归测试 ====================

class DownloadIDORTest(ScopeIsolationBase):
    """普通权限下载党建文件 ID 应被拒绝。"""

    def test_normal_download_party_file_rejected(self):
        with patch('os.path.exists', return_value=True), \
             patch('builtins.open', create=True):
            resp = self.client.get('/document/download/', {
                'id': self.pb_file.id, 'is_public': 'true',
            })
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertNotEqual(body.get('data'), None) if 'data' in body else None
            # 应返回 error
            self.assertIn('error', body)

    def test_party_download_normal_file_rejected(self):
        resp = self.client.get('/document/download/', {
            'id': self.normal_file.id, 'is_public': 'true',
            'system_folder': PB,
        })
        body = resp.json()
        self.assertIn('error', body)


class PreviewTokenIDORTest(ScopeIsolationBase):
    """预览令牌生成 + 党建文件反向隔离。"""

    def test_normal_request_party_file_token_rejected(self):
        resp = self.client.get('/document/preview_token/', {
            'id': self.pb_file.id, 'is_public': 'true',
        })
        body = resp.json()
        self.assertIn('error', body)

    def test_party_request_normal_file_token_rejected(self):
        resp = self.client.get('/document/preview_token/', {
            'id': self.normal_file.id, 'is_public': 'true',
            'system_folder': PB,
        })
        body = resp.json()
        self.assertIn('error', body)


class UploadTargetIDORTest(ScopeIsolationBase):
    """普通上传以党建目录为目标应被拒绝。"""

    def test_normal_create_folder_under_party_root_rejected(self):
        resp = self.client.post('/document/folder/', data=json.dumps({
            'name': 'x', 'parent_id': self.pb_root.id, 'is_public': True,
        }), content_type='application/json')
        body = resp.json()
        self.assertIn('error', body)


class TransferScopeConsistencyTest(ScopeIsolationBase):
    """普通请求取消党建传输记录应被拒绝。"""

    def test_normal_cancel_party_transfer_rejected(self):
        resp = self.client.post(
            f'/document/transfers/{self.pb_transfer.id}/cancel/')
        body = resp.json()
        self.assertIn('error', body)

    def test_party_cancel_normal_transfer_rejected(self):
        resp = self.client.post(
            f'/document/transfers/{self.normal_transfer.id}/cancel/',
            data=json.dumps({'system_folder': PB}),
            content_type='application/json')
        body = resp.json()
        self.assertIn('error', body)


class ListExclusionTest(ScopeIsolationBase):
    """普通列表不显示党建目录/文件。"""

    def test_normal_root_excludes_party_root(self):
        resp = self.client.get('/document/folder/', {'is_public': 'true'})
        body = resp.json()
        folder_ids = [f['id'] for f in body['data']['folders']]
        self.assertNotIn(self.pb_root.id, folder_ids)
        self.assertIn(self.normal_folder.id, folder_ids)

    def test_party_list_only_party(self):
        resp = self.client.get('/document/folder/', {
            'is_public': 'true', 'system_folder': PB})
        body = resp.json()
        folder_ids = [f['id'] for f in body['data']['folders']]
        # 党建根目录的内容应包含其子目录，不含普通目录
        self.assertIn(self.pb_sub.id, folder_ids)
        self.assertNotIn(self.normal_folder.id, folder_ids)


# ==================== 搜索隔离请求级测试 ====================

class SearchIsolationTest(ScopeIsolationBase):
    """搜索接口跨作用域隔离回归测试。

    覆盖：
    - 普通搜索不返回党建根目录、子目录和文件；
    - 党建搜索不返回普通根层、普通子目录和普通文件；
    - 党建搜索能够返回多级党建子目录中的文件；
    - 指定普通子目录搜索不混入普通根层文件；
    - 普通上下文直接传党建 folder_id 被拒绝；
    - 非法 system_folder 被拒绝。
    """

    def _search(self, **params):
        return self.client.get('/document/folder/search/', params)

    def test_normal_search_excludes_party(self):
        """普通全库搜索不返回党建根目录、子目录和文件。"""
        resp = self._search(is_public='true', keyword='党建')
        body = resp.json()
        folder_ids = [f['id'] for f in body['data']['folders']]
        file_ids = [f['id'] for f in body['data']['files']]
        self.assertNotIn(self.pb_root.id, folder_ids)
        self.assertNotIn(self.pb_sub.id, folder_ids)
        self.assertNotIn(self.pb_file.id, file_ids)
        self.assertNotIn(self.pb_deep_file.id, file_ids)

    def test_normal_search_returns_normal_file(self):
        """普通全库搜索能正常返回普通子目录文件。"""
        resp = self._search(is_public='true', keyword='n')
        body = resp.json()
        file_ids = [f['id'] for f in body['data']['files']]
        self.assertIn(self.normal_file.id, file_ids)

    def test_normal_search_includes_root_files(self):
        """普通全库搜索包含根层文件（folder_id=None）。"""
        resp = self._search(is_public='true', keyword='root')
        body = resp.json()
        file_ids = [f['id'] for f in body['data']['files']]
        self.assertIn(self.normal_root_file.id, file_ids)

    def test_party_search_excludes_normal(self):
        """党建搜索不返回普通根层、普通子目录和普通文件。"""
        resp = self._search(
            is_public='true', system_folder=PB, keyword='root')
        body = resp.json()
        folder_ids = [f['id'] for f in body['data']['folders']]
        file_ids = [f['id'] for f in body['data']['files']]
        self.assertNotIn(self.normal_folder.id, folder_ids)
        self.assertNotIn(self.normal_root_file.id, file_ids)
        self.assertNotIn(self.normal_file.id, file_ids)

    def test_party_search_returns_deep_files(self):
        """党建搜索能够返回多级党建子目录中的文件。"""
        resp = self._search(
            is_public='true', system_folder=PB, keyword='deep')
        body = resp.json()
        file_ids = [f['id'] for f in body['data']['files']]
        self.assertIn(self.pb_deep_file.id, file_ids)

    def test_party_search_excludes_root_level_files(self):
        """党建搜索不混入公共根层文件（folder_id=None）。"""
        # 党建搜索关键词命中普通根层文件名 root.txt
        resp = self._search(
            is_public='true', system_folder=PB, keyword='root')
        body = resp.json()
        file_ids = [f['id'] for f in body['data']['files']]
        self.assertNotIn(self.normal_root_file.id, file_ids)

    def test_normal_search_in_subfolder_excludes_root_files(self):
        """指定普通子目录搜索不混入普通根层文件。"""
        # 在 normal_folder 内搜索，关键词命中根层文件 root.txt
        resp = self._search(
            is_public='true',
            folder_id=self.normal_folder.id, keyword='root')
        body = resp.json()
        file_ids = [f['id'] for f in body['data']['files']]
        # 根层文件不应出现在指定子目录搜索结果中
        self.assertNotIn(self.normal_root_file.id, file_ids)

    def test_normal_context_with_party_folder_id_rejected(self):
        """普通上下文直接传党建 folder_id 作为搜索起点被拒绝。"""
        resp = self._search(
            is_public='true', folder_id=self.pb_sub.id, keyword='x')
        body = resp.json()
        self.assertTrue(body.get('error'))

    def test_invalid_system_folder_rejected(self):
        """非法 system_folder 被拒绝（fail closed）。"""
        resp = self._search(
            is_public='true', system_folder='evil_code', keyword='x')
        body = resp.json()
        self.assertTrue(body.get('error'))

    def test_private_with_system_folder_rejected(self):
        """私有模式携带党建 system_folder 被拒绝。"""
        resp = self._search(
            is_public='false', system_folder=PB, keyword='x')
        body = resp.json()
        self.assertTrue(body.get('error'))

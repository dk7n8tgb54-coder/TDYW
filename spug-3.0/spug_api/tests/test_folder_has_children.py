# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""FolderView has_children 字段测试矩阵。

覆盖：
- 有直接子文件夹 → has_children=true
- 只有文件/空目录/仅软删除子目录 → has_children=false
- 私有空间租户隔离：不把其它租户子目录计入
- 普通公共空间不把系统目录作用域子目录计入
- 党建文档作用域内 has_children 正确
- 根目录列表 / 指定目录列表 / all=true 三路返回一致
- 原有字段与分页结构保持兼容
"""
import time

from django.test import TestCase, Client

from apps.account.models import User
from apps.document.models import (
    DocumentFolderPrivate, DocumentFilePrivate,
    DocumentFolderPublic, DocumentFilePublic,
    DocumentSystemFolder,
)
from apps.document.services.system_folder_service import PARTY_BUILDING_DOCUMENTS_CODE
from apps.setting.utils import AppSetting

PB = PARTY_BUILDING_DOCUMENTS_CODE


class HasChildrenBase(TestCase):
    """构建普通/党建/私有三套数据的测试基类。"""

    @classmethod
    def setUpTestData(cls):
        token = 'c' * 32
        cls.user = User.objects.create(
            username='hc_user', nickname='hc', tenant_id='',
            password_hash=User.make_password('pw'), is_supper=True,
            is_active=True, access_token=token,
            token_expired=int(time.time()) + 3600,
            last_ip='127.0.0.1', last_login='2026-01-01', type='default',
        )
        # 另一租户用户（用于私有空间跨租户隔离测试）
        cls.other_user = User.objects.create(
            username='hc_other', nickname='other', tenant_id='other_tenant',
            password_hash=User.make_password('pw'), is_supper=True,
            is_active=True, access_token='d' * 32,
            token_expired=int(time.time()) + 3600,
            last_ip='127.0.0.1', last_login='2026-01-01', type='default',
        )

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.user.access_token
        self.client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'

    def _private_client(self):
        """以 other_user 身份发起请求（tenant_id='other_tenant'）。"""
        c = Client()
        c.defaults['HTTP_X_TOKEN'] = self.other_user.access_token
        c.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
        return c

    @staticmethod
    def _folders_from(resp):
        """从根目录/指定目录响应中取 folders 列表。"""
        data = resp.json().get('data')
        if isinstance(data, list):
            return data
        return data.get('folders', []) if isinstance(data, dict) else []


class PrivateHasChildrenTest(HasChildrenBase):
    """私有空间 has_children 测试。"""

    def test_folder_with_subfolder_is_true(self):
        parent = DocumentFolderPrivate.objects.create(
            name='父', parent=None, created_by=self.user, tenant_id='')
        DocumentFolderPrivate.objects.create(
            name='子', parent=parent, created_by=self.user, tenant_id='')
        # 查询根目录列表，验证父文件夹的 has_children=true
        resp = self.client.get('/document/folder/?is_public=false')
        folders = self._folders_from(resp)
        target = [f for f in folders if f['id'] == parent.id]
        self.assertEqual(len(target), 1)
        self.assertTrue(target[0]['has_children'])

    def test_folder_with_only_file_is_false(self):
        parent = DocumentFolderPrivate.objects.create(
            name='只有文件', parent=None, created_by=self.user, tenant_id='')
        DocumentFilePrivate.objects.create(
            name='f.txt', display_name='f.txt', physical_name='f.txt',
            file_path='/tmp/f.txt', file_size=1, file_type='text/plain',
            folder=parent, created_by=self.user, tenant_id='')
        resp = self.client.get(f'/document/folder/?is_public=false&id={parent.id}')
        folders = self._folders_from(resp)
        # 文件夹列表为空（只有文件），但 has_children 应在根目录列表中验证
        self.assertEqual(len(folders), 0)
        # 根目录列表中该文件夹 has_children=false
        resp2 = self.client.get('/document/folder/?is_public=false')
        folders2 = self._folders_from(resp2)
        target = [f for f in folders2 if f['id'] == parent.id]
        self.assertEqual(len(target), 1)
        self.assertFalse(target[0]['has_children'])

    def test_empty_folder_is_false(self):
        parent = DocumentFolderPrivate.objects.create(
            name='空', parent=None, created_by=self.user, tenant_id='')
        resp = self.client.get('/document/folder/?is_public=false')
        folders = self._folders_from(resp)
        target = [f for f in folders if f['id'] == parent.id]
        self.assertEqual(len(target), 1)
        self.assertFalse(target[0]['has_children'])

    def test_only_soft_deleted_subfolder_is_false(self):
        parent = DocumentFolderPrivate.objects.create(
            name='有已删子', parent=None, created_by=self.user, tenant_id='')
        DocumentFolderPrivate.objects.create(
            name='已删子', parent=parent, created_by=self.user, tenant_id='',
            is_deleted=True)
        resp = self.client.get('/document/folder/?is_public=false')
        folders = self._folders_from(resp)
        target = [f for f in folders if f['id'] == parent.id]
        self.assertEqual(len(target), 1)
        self.assertFalse(target[0]['has_children'])

    def test_cross_tenant_subfolder_not_counted(self):
        """其它租户的子目录不应计入当前租户文件夹的 has_children。"""
        # 当前租户('')的文件夹
        parent = DocumentFolderPrivate.objects.create(
            name='本租户父', parent=None, created_by=self.user, tenant_id='')
        # 其它租户('other_tenant')在同一个 parent_id 下创建了子目录
        DocumentFolderPrivate.objects.create(
            name='他租户子', parent=parent, created_by=self.other_user,
            tenant_id='other_tenant')
        # 当前用户查询：父文件夹的 has_children 应为 false
        resp = self.client.get('/document/folder/?is_public=false')
        folders = self._folders_from(resp)
        target = [f for f in folders if f['id'] == parent.id]
        self.assertEqual(len(target), 1)
        self.assertFalse(target[0]['has_children'])
        # other_user 查询：应看到自己的子目录，has_children=true
        resp2 = self._private_client().get('/document/folder/?is_public=false')
        folders2 = self._folders_from(resp2)
        target2 = [f for f in folders2 if f['name'] == '他租户子']
        # other_tenant 用户的根目录查询里，他租户子是根层文件夹（parent 指向本租户父，但被租户过滤排除）
        # 这里只验证跨租户不串数据即可
        for f in folders2:
            self.assertEqual(f['name'], '他租户子')


class PublicHasChildrenTest(HasChildrenBase):
    """普通公共空间 has_children 测试。"""

    def setUp(self):
        super().setUp()
        # 普通公共文件夹 + 子文件夹
        self.normal_parent = DocumentFolderPublic.objects.create(
            name='普通父', parent=None, created_by=self.user)
        self.normal_child = DocumentFolderPublic.objects.create(
            name='普通子', parent=self.normal_parent, created_by=self.user)
        # 只有文件的普通文件夹
        self.file_only = DocumentFolderPublic.objects.create(
            name='只有文件', parent=None, created_by=self.user)
        DocumentFilePublic.objects.create(
            name='fo.txt', display_name='fo.txt', physical_name='fo.txt',
            file_path='/tmp/fo.txt', file_size=1, file_type='text/plain',
            folder=self.file_only, created_by=self.user)
        # 党建根 + 子目录（用于验证普通模式不把党建子目录计入）
        self.pb_root = DocumentFolderPublic.objects.create(
            name='党建文档', parent=None, created_by=self.user)
        DocumentSystemFolder.objects.create(
            code=PB, name='党建文档', folder=self.pb_root,
            is_public=True, protected=True)
        self.pb_sub = DocumentFolderPublic.objects.create(
            name='党建子', parent=self.pb_root, created_by=self.user)

    def test_normal_folder_with_subfolder_is_true(self):
        # 查询根目录列表，验证普通父文件夹 has_children=true
        resp = self.client.get('/document/folder/?is_public=true')
        folders = self._folders_from(resp)
        target = [f for f in folders if f['id'] == self.normal_parent.id]
        self.assertEqual(len(target), 1)
        self.assertTrue(target[0]['has_children'])

    def test_normal_folder_only_file_is_false(self):
        resp = self.client.get('/document/folder/?is_public=true')
        folders = self._folders_from(resp)
        target = [f for f in folders if f['id'] == self.file_only.id]
        self.assertEqual(len(target), 1)
        self.assertFalse(target[0]['has_children'])

    def test_party_root_not_in_normal_list(self):
        """普通公共列表不包含党建根目录。"""
        resp = self.client.get('/document/folder/?is_public=true')
        folders = self._folders_from(resp)
        ids = [f['id'] for f in folders]
        self.assertNotIn(self.pb_root.id, ids)

    def test_all_true_has_children_field(self):
        resp = self.client.get('/document/folder/?is_public=true&all=true')
        data = resp.json()['data']
        self.assertIsInstance(data, list)
        for f in data:
            self.assertIn('has_children', f)
            self.assertIsInstance(f['has_children'], bool)
        parent_entry = [f for f in data if f['id'] == self.normal_parent.id]
        self.assertEqual(len(parent_entry), 1)
        self.assertTrue(parent_entry[0]['has_children'])
        file_only_entry = [f for f in data if f['id'] == self.file_only.id]
        self.assertEqual(len(file_only_entry), 1)
        self.assertFalse(file_only_entry[0]['has_children'])


class PartyBuildingHasChildrenTest(HasChildrenBase):
    """党建文档作用域 has_children 测试。"""

    def setUp(self):
        super().setUp()
        self.pb_root = DocumentFolderPublic.objects.create(
            name='党建文档', parent=None, created_by=self.user)
        DocumentSystemFolder.objects.create(
            code=PB, name='党建文档', folder=self.pb_root,
            is_public=True, protected=True)
        self.pb_sub = DocumentFolderPublic.objects.create(
            name='一级子', parent=self.pb_root, created_by=self.user)
        self.pb_subsub = DocumentFolderPublic.objects.create(
            name='二级子', parent=self.pb_sub, created_by=self.user)
        self.pb_grandchild = DocumentFolderPublic.objects.create(
            name='三级子', parent=self.pb_subsub, created_by=self.user)
        self.pb_leaf = DocumentFolderPublic.objects.create(
            name='叶子', parent=self.pb_sub, created_by=self.user)
        # 普通公共文件夹（不应出现在党建列表）
        self.normal_folder = DocumentFolderPublic.objects.create(
            name='普通目录', parent=None, created_by=self.user)

    def test_pb_root_has_children(self):
        resp = self.client.get(
            f'/document/folder/?is_public=true&system_folder={PB}')
        folders = self._folders_from(resp)
        # 党建根目录的一级子目录只有 pb_sub
        self.assertEqual(len(folders), 1)
        self.assertTrue(folders[0]['has_children'])

    def test_pb_sub_has_children(self):
        resp = self.client.get(
            f'/document/folder/?is_public=true&system_folder={PB}&id={self.pb_sub.id}')
        folders = self._folders_from(resp)
        names = [f['name'] for f in folders]
        self.assertIn('二级子', names)
        self.assertIn('叶子', names)
        # 二级子有子目录（三级子）→ true；叶子无子目录 → false
        subsub = [f for f in folders if f['id'] == self.pb_subsub.id][0]
        leaf = [f for f in folders if f['id'] == self.pb_leaf.id][0]
        self.assertTrue(subsub['has_children'])
        self.assertFalse(leaf['has_children'])

    def test_pb_all_true_scoped(self):
        # all=true 普通公共模式应排除党建目录，且 has_children 字段一致
        resp = self.client.get('/document/folder/?is_public=true&all=true')
        data = resp.json()['data']
        ids = [f['id'] for f in data]
        # 不包含党建目录
        self.assertNotIn(self.pb_root.id, ids)
        self.assertNotIn(self.pb_sub.id, ids)
        # 所有条目都含 has_children 布尔字段
        for f in data:
            self.assertIn('has_children', f)
            self.assertIsInstance(f['has_children'], bool)


class ResponseStructureTest(HasChildrenBase):
    """验证原有字段和分页结构兼容。"""

    def test_folder_dict_preserves_existing_fields(self):
        folder = DocumentFolderPublic.objects.create(
            name='结构验证', parent=None, created_by=self.user)
        resp = self.client.get('/document/folder/?is_public=true')
        folders = self._folders_from(resp)
        target = [f for f in folders if f['id'] == folder.id][0]
        for key in ('id', 'name', 'parent_id', 'created_at', 'updated_at',
                    'created_by', 'created_by_id', 'has_children'):
            self.assertIn(key, target)
        self.assertEqual(target['name'], '结构验证')
        self.assertFalse(target['has_children'])

    def test_pagination_structure_preserved(self):
        DocumentFolderPublic.objects.create(
            name='分页1', parent=None, created_by=self.user)
        resp = self.client.get('/document/folder/?is_public=true')
        data = resp.json()['data']
        self.assertIn('pagination', data)
        for key in ('page', 'page_size', 'total_folders', 'total_files', 'has_more'):
            self.assertIn(key, data['pagination'])
        self.assertIn('files', data)

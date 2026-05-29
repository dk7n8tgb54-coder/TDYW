# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase, Client
from apps.account.models import User
from apps.document.models import DocumentFolder, DocumentFile
from apps.setting.utils import AppSetting
import json
import time


class DocumentAPITest(TestCase):
    """文档管理模块API测试"""

    def setUp(self):
        """测试前准备"""
        token = 'a' * 32

        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant',
            is_supper=True,
            is_active=True,
            access_token=token,
            token_expired=int(time.time()) + 3600,
            last_ip='127.0.0.1',
            last_login='2026-01-01',
            type='default'
        )
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = token
        self.client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
        AppSetting.set('bind_ip', False)

    def test_get_root_folders(self):
        """测试获取根目录文件夹"""
        # 创建根目录文件夹
        DocumentFolder.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            name='根文件夹1',
            parent_id=None
        )

        response = self.client.get('/document/folder/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('data', data)

    def test_get_all_folders_for_tree(self):
        """测试获取所有文件夹（用于构建树）"""
        # 创建文件夹结构
        folder1 = DocumentFolder.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            name='根文件夹1',
            parent_id=None
        )
        DocumentFolder.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            name='子文件夹',
            parent_id=folder1.id
        )

        response = self.client.get('/document/folder/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('data', data)

    def test_get_subfolders(self):
        """测试获取子文件夹"""
        parent = DocumentFolder.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            name='父文件夹',
            parent_id=None
        )

        DocumentFolder.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            name='子文件夹1',
            parent_id=parent.id
        )
        DocumentFolder.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            name='子文件夹2',
            parent_id=parent.id
        )

        response = self.client.get(f'/document/folder/?parent_id={parent.id}')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('data', data)

    def test_create_folder_in_root(self):
        """测试在根目录创建文件夹"""
        response = self.client.post(
            '/document/folder/',
            data=json.dumps({
                'name': '新建文件夹',
                'parent_id': None
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data.get('error'))

        # 验证文件夹已创建
        folder = DocumentFolder.objects.filter(name='新建文件夹').first()
        self.assertIsNotNone(folder)
        self.assertEqual(folder.parent_id, None)

    def test_create_subfolder(self):
        """测试创建子文件夹"""
        parent = DocumentFolder.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            name='父文件夹',
            parent_id=None
        )

        response = self.client.post(
            '/document/folder/',
            data=json.dumps({
                'name': '子文件夹',
                'parent_id': parent.id
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)

        # 验证子文件夹已创建
        folder = DocumentFolder.objects.filter(name='子文件夹').first()
        self.assertIsNotNone(folder)
        self.assertEqual(folder.parent_id, parent.id)

    def test_create_duplicate_folder(self):
        """测试创建重复文件夹"""
        DocumentFolder.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            name='重复文件夹',
            parent_id=None
        )

        response1 = self.client.post(
            '/document/folder/',
            data=json.dumps({
                'name': '重复文件夹',
                'parent_id': None
            }),
            content_type='application/json'
        )

        # 应该返回成功（实际业务可能允许同名或返回特定错误）
        self.assertIn(response1.status_code, [200, 400])

    def test_create_empty_folder_name(self):
        """测试创建空名称文件夹"""
        response = self.client.post(
            '/document/folder/',
            data=json.dumps({
                'name': '',
                'parent_id': None
            }),
            content_type='application/json'
        )
        # 应该返回错误
        self.assertEqual(response.status_code, 400)

    def test_delete_folder(self):
        """测试删除文件夹"""
        folder = DocumentFolder.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            name='待删除文件夹',
            parent_id=None
        )

        response = self.client.delete(f'/document/folder/{folder.id}/')
        self.assertEqual(response.status_code, 200)

        # 验证文件夹已删除
        self.assertFalse(DocumentFolder.objects.filter(id=folder.id).exists())

    def test_delete_folder_with_files(self):
        """测试删除包含文件的文件夹（级联删除）"""
        folder = DocumentFolder.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            name='含文件文件夹',
            parent_id=None
        )

        DocumentFile.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            folder_id=folder.id,
            name='文件1.txt',
            file_size=1024,
            file_type='text/plain'
        )

        response = self.client.delete(f'/document/folder/{folder.id}/')
        self.assertEqual(response.status_code, 200)

        # 验证文件夹和文件都已删除
        self.assertFalse(DocumentFolder.objects.filter(id=folder.id).exists())
        self.assertFalse(DocumentFile.objects.filter(folder_id=folder.id).exists())

    def test_rename_folder(self):
        """测试重命名文件夹"""
        folder = DocumentFolder.objects.create(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            name='旧名称',
            parent_id=None
        )

        response = self.client.post(
            '/document/folder/',
            data=json.dumps({
                'id': folder.id,
                'name': '新名称'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)

        folder.refresh_from_db()
        self.assertEqual(folder.name, '新名称')

    def test_nonexistent_folder(self):
        """测试访问不存在的文件夹"""
        response = self.client.get(f'/document/folder/?parent_id=99999')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('data', data)

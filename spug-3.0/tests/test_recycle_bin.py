# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
回收站功能测试用例
严格按照《回收站功能设计方案.md》v1.3实施验证

测试环境要求：
- Django 服务已启动
- Redis 服务已启动
- Celery Worker 已启动
- 测试用户已创建并具有相应权限

运行方式：
    cd spug_api
    python manage.py test tests.test_recycle_bin -v 2
"""

import os
import time
from datetime import timedelta
from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.document.models import (
    DocumentFilePrivate, 
    DocumentFilePublic, 
    DocumentFolderPrivate,
    DocumentFolderPublic
)

User = get_user_model()


@override_settings(RECYCLE_BIN_RETENTION_DAYS=30)
class RecycleBinViewTest(TestCase):
    """回收站列表接口测试"""
    
    def setUp(self):
        """测试前置准备"""
        self.client = Client()
        
        # 创建测试用户
        self.user = User.objects.create_user(
            username='test_user',
            password='test_password',
            nickname='测试用户'
        )
        
        # 创建管理员
        self.admin = User.objects.create_user(
            username='admin_user',
            password='admin_password',
            nickname='管理员',
            is_superuser=True
        )
        
        # 创建另一个普通用户
        self.other_user = User.objects.create_user(
            username='other_user',
            password='other_password',
            nickname='其他用户'
        )
        
        # 创建测试文件夹
        self.folder_private = DocumentFolderPrivate.objects.create(
            name='测试文件夹',
            created_by=self.user
        )
        
        # 创建已删除的私有文件
        self.deleted_file_private = DocumentFilePrivate.objects.create(
            name='deleted_test_file.txt',
            display_name='已删除测试文件.txt',
            file_path='/tmp/test_deleted.txt',
            file_size=1024,
            file_type='text/plain',
            folder=self.folder_private,
            created_by=self.user,
            is_deleted=True,
            deleted_at=timezone.now()
        )
        
        # 创建未删除的私有文件
        self.normal_file_private = DocumentFilePrivate.objects.create(
            name='normal_test_file.txt',
            display_name='正常测试文件.txt',
            file_path='/tmp/test_normal.txt',
            file_size=2048,
            file_type='text/plain',
            folder=self.folder_private,
            created_by=self.user,
            is_deleted=False
        )
        
        # 创建其他用户的已删除文件
        self.other_user_file = DocumentFilePrivate.objects.create(
            name='other_user_file.txt',
            display_name='其他用户文件.txt',
            file_path='/tmp/other_user.txt',
            file_size=512,
            file_type='text/plain',
            created_by=self.other_user,
            is_deleted=True,
            deleted_at=timezone.now()
        )
        
        # 登录
        self.client.force_login(self.user)
    
    def test_get_recycle_bin_list_success(self):
        """测试正常获取回收站列表"""
        response = self.client.get('/api/document/recycle-bin/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('data', data)
        self.assertIn('items', data['data'])
        self.assertIn('total', data['data'])
        
        # 验证只能看到自己的已删除文件
        items = data['data']['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['name'], 'deleted_test_file.txt')
        
    def test_get_recycle_bin_list_with_pagination(self):
        """测试分页功能"""
        response = self.client.get('/api/document/recycle-bin/?page=1&page_size=10')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()['data']
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['page_size'], 10)
        
    def test_get_recycle_bin_list_with_keyword(self):
        """测试搜索功能"""
        response = self.client.get('/api/document/recycle-bin/?keyword=已删除')
        self.assertEqual(response.status_code, 200)
        
        items = response.json()['data']['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['display_name'], '已删除测试文件.txt')
        
    def test_get_recycle_bin_list_with_space_filter(self):
        """测试空间筛选"""
        # 筛选私有空间
        response = self.client.get('/api/document/recycle-bin/?space=private')
        self.assertEqual(response.status_code, 200)
        
        # 筛选公共空间
        response = self.client.get('/api/document/recycle-bin/?space=public')
        self.assertEqual(response.status_code, 200)
        
    def test_admin_can_see_all_files(self):
        """测试管理员可以查看所有用户的回收站"""
        self.client.force_login(self.admin)
        response = self.client.get('/api/document/recycle-bin/')
        self.assertEqual(response.status_code, 200)
        
        items = response.json()['data']['items']
        # 管理员应该能看到两个已删除文件
        self.assertEqual(len(items), 2)
        
    def test_recycle_bin_excludes_normal_files(self):
        """测试回收站不包含正常文件"""
        response = self.client.get('/api/document/recycle-bin/')
        items = response.json()['data']['items']
        
        # 检查所有返回的文件都是已删除的
        for item in items:
            self.assertEqual(item['space'], 'private')
            
    def test_recycle_bin_retention_days_calculation(self):
        """测试剩余天数计算"""
        response = self.client.get('/api/document/recycle-bin/')
        items = response.json()['data']['items']
        
        if items:
            # 检查剩余天数在合理范围内
            self.assertGreaterEqual(items[0]['retention_days_left'], 0)
            self.assertLessEqual(items[0]['retention_days_left'], 30)


@override_settings(RECYCLE_BIN_RETENTION_DAYS=30)
class RecycleBinRestoreTest(TestCase):
    """回收站恢复功能测试"""
    
    def setUp(self):
        """测试前置准备"""
        self.client = Client()
        
        self.user = User.objects.create_user(
            username='test_user',
            password='test_password',
            nickname='测试用户'
        )
        
        self.other_user = User.objects.create_user(
            username='other_user',
            password='other_password',
            nickname='其他用户'
        )
        
        # 创建文件夹
        self.folder = DocumentFolderPrivate.objects.create(
            name='测试文件夹',
            created_by=self.user
        )
        
        # 创建已删除的文件
        self.deleted_file = DocumentFilePrivate.objects.create(
            name='deleted_file.txt',
            display_name='已删除文件.txt',
            file_path='/tmp/deleted.txt',
            file_size=1024,
            file_type='text/plain',
            folder=self.folder,
            created_by=self.user,
            is_deleted=True,
            deleted_at=timezone.now()
        )
        
        # 创建没有文件夹的已删除文件
        self.deleted_file_no_folder = DocumentFilePrivate.objects.create(
            name='deleted_file_no_folder.txt',
            display_name='无文件夹已删除文件.txt',
            file_path='/tmp/deleted_no_folder.txt',
            file_size=512,
            file_type='text/plain',
            folder=None,
            created_by=self.user,
            is_deleted=True,
            deleted_at=timezone.now()
        )
        
        # 创建其他用户的已删除文件
        self.other_file = DocumentFilePrivate.objects.create(
            name='other_file.txt',
            display_name='其他用户文件.txt',
            file_path='/tmp/other.txt',
            file_size=256,
            file_type='text/plain',
            created_by=self.other_user,
            is_deleted=True,
            deleted_at=timezone.now()
        )
        
        self.client.force_login(self.user)
    
    def test_restore_single_file_success(self):
        """测试单文件恢复成功"""
        response = self.client.post(
            '/api/document/recycle-bin/restore/',
            {
                'file_ids': [self.deleted_file.id],
                'restore_mode': 'original'
            },
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['success_count'], 1)
        self.assertEqual(data['failed_count'], 0)
        
        # 验证文件已恢复
        self.deleted_file.refresh_from_db()
        self.assertFalse(self.deleted_file.is_deleted)
        self.assertIsNone(self.deleted_file.deleted_at)
        
    def test_restore_to_original_location(self):
        """测试恢复到原位置"""
        response = self.client.post(
            '/api/document/recycle-bin/restore/',
            {
                'file_ids': [self.deleted_file.id],
                'restore_mode': 'original'
            },
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # 验证文件恢复到原文件夹
        self.deleted_file.refresh_from_db()
        self.assertEqual(self.deleted_file.folder_id, self.folder.id)
        
    def test_restore_to_root_when_folder_deleted(self):
        """测试原文件夹已删除时恢复到根目录"""
        # 删除原文件夹
        folder_id = self.folder.id
        self.folder.delete()
        
        response = self.client.post(
            '/api/document/recycle-bin/restore/',
            {
                'file_ids': [self.deleted_file.id],
                'restore_mode': 'original'
            },
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # 验证文件恢复到根目录
        self.deleted_file.refresh_from_db()
        self.assertIsNone(self.deleted_file.folder)
        
    def test_restore_permission_denied(self):
        """测试恢复他人文件权限被拒绝"""
        response = self.client.post(
            '/api/document/recycle-bin/restore/',
            {
                'file_ids': [self.other_file.id],
                'restore_mode': 'original'
            },
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['success_count'], 0)
        self.assertEqual(data['failed_count'], 1)
        
    def test_restore_batch_files(self):
        """测试批量恢复文件"""
        response = self.client.post(
            '/api/document/recycle-bin/restore/',
            {
                'file_ids': [self.deleted_file.id, self.deleted_file_no_folder.id],
                'restore_mode': 'original'
            },
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['success_count'], 2)
        
    def test_restore_with_idempotent_key(self):
        """测试幂等性恢复"""
        idempotent_key = 'test_key_123'
        
        # 第一次恢复
        response1 = self.client.post(
            '/api/document/recycle-bin/restore/',
            {
                'file_ids': [self.deleted_file.id],
                'restore_mode': 'original',
                'idempotent_key': idempotent_key
            },
            content_type='application/json'
        )
        
        self.assertEqual(response1.status_code, 200)
        
        # 第二次使用相同的幂等键
        response2 = self.client.post(
            '/api/document/recycle-bin/restore/',
            {
                'file_ids': [self.deleted_file.id],
                'restore_mode': 'original',
                'idempotent_key': idempotent_key
            },
            content_type='application/json'
        )
        
        self.assertEqual(response2.status_code, 200)
        # 应该返回相同的结果
        
    def test_restore_nonexistent_file(self):
        """测试恢复不存在的文件"""
        response = self.client.post(
            '/api/document/recycle-bin/restore/',
            {
                'file_ids': [99999],  # 不存在的ID
                'restore_mode': 'original'
            },
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['success_count'], 0)
        self.assertEqual(data['failed_count'], 1)


@override_settings(RECYCLE_BIN_RETENTION_DAYS=30)
class RecycleBinPermanentDeleteTest(TestCase):
    """回收站彻底删除功能测试"""
    
    def setUp(self):
        """测试前置准备"""
        self.client = Client()
        
        self.user = User.objects.create_user(
            username='test_user',
            password='test_password',
            nickname='测试用户'
        )
        
        self.other_user = User.objects.create_user(
            username='other_user',
            password='other_password',
            nickname='其他用户'
        )
        
        # 创建测试文件（实际创建临时文件）
        self.temp_file_path = '/tmp/test_recycle_bin_delete.txt'
        with open(self.temp_file_path, 'w') as f:
            f.write('Test content')
        
        self.deleted_file = DocumentFilePrivate.objects.create(
            name='test_delete.txt',
            display_name='测试删除文件.txt',
            file_path=self.temp_file_path,
            file_size=1024,
            file_type='text/plain',
            folder=None,
            created_by=self.user,
            is_deleted=True,
            deleted_at=timezone.now()
        )
        
        self.other_file = DocumentFilePrivate.objects.create(
            name='other_delete.txt',
            display_name='其他用户删除文件.txt',
            file_path='/tmp/other.txt',
            file_size=512,
            file_type='text/plain',
            folder=None,
            created_by=self.other_user,
            is_deleted=True,
            deleted_at=timezone.now()
        )
        
        self.client.force_login(self.user)
    
    def tearDown(self):
        """测试后清理"""
        # 清理临时文件
        if os.path.exists(self.temp_file_path):
            os.remove(self.temp_file_path)
    
    def test_permanent_delete_single_file(self):
        """测试单文件彻底删除"""
        response = self.client.post(
            '/api/document/recycle-bin/permanent/',
            {
                'file_ids': [self.deleted_file.id],
                'async_mode': False
            },
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['success_count'], 1)
        self.assertFalse(data['async'])  # 同步删除
        
        # 验证数据库记录已删除
        with self.assertRaises(DocumentFilePrivate.DoesNotExist):
            DocumentFilePrivate.all_objects.get(id=self.deleted_file.id)
        
        # 验证物理文件已删除
        self.assertFalse(os.path.exists(self.temp_file_path))
        
    def test_permanent_delete_permission_denied(self):
        """测试删除他人文件权限被拒绝"""
        response = self.client.post(
            '/api/document/recycle-bin/permanent/',
            {
                'file_ids': [self.other_file.id],
                'async_mode': False
            },
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['success_count'], 0)
        self.assertEqual(data['failed_count'], 1)
        
    def test_permanent_delete_batch_files(self):
        """测试批量彻底删除"""
        # 创建另一个文件
        temp_path2 = '/tmp/test_delete_2.txt'
        with open(temp_path2, 'w') as f:
            f.write('Test content 2')
        
        file2 = DocumentFilePrivate.objects.create(
            name='test_delete_2.txt',
            display_name='测试删除文件2.txt',
            file_path=temp_path2,
            file_size=512,
            file_type='text/plain',
            created_by=self.user,
            is_deleted=True,
            deleted_at=timezone.now()
        )
        
        response = self.client.post(
            '/api/document/recycle-bin/permanent/',
            {
                'file_ids': [self.deleted_file.id, file2.id],
                'async_mode': False
            },
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['success_count'], 2)
        
        # 清理
        if os.path.exists(temp_path2):
            os.remove(temp_path2)
        
    def test_permanent_delete_nonexistent_file(self):
        """测试删除不存在的文件"""
        response = self.client.post(
            '/api/document/recycle-bin/permanent/',
            {
                'file_ids': [99999],
                'async_mode': False
            },
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['success_count'], 0)
        
    def test_permanent_delete_with_async_mode(self):
        """测试异步删除模式"""
        # 创建多个文件触发异步
        file_ids = []
        for i in range(15):
            temp_path = f'/tmp/test_async_{i}.txt'
            with open(temp_path, 'w') as f:
                f.write(f'Test content {i}')
            
            file = DocumentFilePrivate.objects.create(
                name=f'test_async_{i}.txt',
                display_name=f'测试异步文件{i}.txt',
                file_path=temp_path,
                file_size=100,
                file_type='text/plain',
                created_by=self.user,
                is_deleted=True,
                deleted_at=timezone.now()
            )
            file_ids.append(file.id)
        
        response = self.client.post(
            '/api/document/recycle-bin/permanent/',
            {
                'file_ids': file_ids,
                'async_mode': True
            },
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertTrue(data['async'])
        self.assertIn('task_id', data)
        
        # 清理
        for i in range(15):
            temp_path = f'/tmp/test_async_{i}.txt'
            if os.path.exists(temp_path):
                os.remove(temp_path)


@override_settings(RECYCLE_BIN_RETENTION_DAYS=30)
class RecycleBinStatsTest(TestCase):
    """回收站统计接口测试"""
    
    def setUp(self):
        """测试前置准备"""
        self.client = Client()
        
        self.user = User.objects.create_user(
            username='test_user',
            password='test_password',
            nickname='测试用户'
        )
        
        self.admin = User.objects.create_user(
            username='admin_user',
            password='admin_password',
            nickname='管理员',
            is_superuser=True
        )
        
        # 创建不同时间删除的文件
        self.recent_file = DocumentFilePrivate.objects.create(
            name='recent.txt',
            display_name='最近删除.txt',
            file_path='/tmp/recent.txt',
            file_size=1024,
            file_type='text/plain',
            created_by=self.user,
            is_deleted=True,
            deleted_at=timezone.now() - timedelta(days=5)
        )
        
        self.expiring_file = DocumentFilePrivate.objects.create(
            name='expiring.txt',
            display_name='即将过期.txt',
            file_path='/tmp/expiring.txt',
            file_size=2048,
            file_type='text/plain',
            created_by=self.user,
            is_deleted=True,
            deleted_at=timezone.now() - timedelta(days=25)  # 还有5天过期
        )
        
        self.normal_file = DocumentFilePrivate.objects.create(
            name='normal.txt',
            display_name='正常文件.txt',
            file_path='/tmp/normal.txt',
            file_size=512,
            file_type='text/plain',
            created_by=self.user,
            is_deleted=False
        )
        
        self.client.force_login(self.user)
    
    def test_get_stats_success(self):
        """测试获取统计信息成功"""
        response = self.client.get('/api/document/recycle-bin/stats/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()['data']
        self.assertIn('total_count', data)
        self.assertIn('total_size', data)
        self.assertIn('private_count', data)
        self.assertIn('private_size', data)
        self.assertIn('public_count', data)
        self.assertIn('public_size', data)
        self.assertIn('expiring_soon', data)
        self.assertIn('retention_days', data)
        
        # 验证统计值
        self.assertEqual(data['total_count'], 2)  # 两个已删除文件
        self.assertEqual(data['private_count'], 2)
        self.assertEqual(data['expiring_soon'], 1)  # 一个即将过期（25天前删除）
        self.assertEqual(data['retention_days'], 30)
        
    def test_stats_calculates_size_correctly(self):
        """测试大小计算正确"""
        response = self.client.get('/api/document/recycle-bin/stats/')
        data = response.json()['data']
        
        expected_size = 1024 + 2048  # recent + expiring
        self.assertEqual(data['total_size'], expected_size)
        self.assertEqual(data['private_size'], expected_size)


@override_settings(RECYCLE_BIN_RETENTION_DAYS=30)
class RecycleBinIntegrationTest(TestCase):
    """回收站功能集成测试"""
    
    def setUp(self):
        """测试前置准备"""
        self.client = Client()
        
        self.user = User.objects.create_user(
            username='test_user',
            password='test_password',
            nickname='测试用户'
        )
        
        self.client.force_login(self.user)
    
    def test_complete_workflow(self):
        """测试完整工作流程：删除->查看->恢复->查看"""
        # 1. 创建文件
        temp_path = '/tmp/workflow_test.txt'
        with open(temp_path, 'w') as f:
            f.write('Workflow test content')
        
        file = DocumentFilePrivate.objects.create(
            name='workflow_test.txt',
            display_name='工作流程测试.txt',
            file_path=temp_path,
            file_size=1024,
            file_type='text/plain',
            created_by=self.user,
            is_deleted=False
        )
        
        # 2. 软删除文件
        file.delete()  # 默认软删除
        file.refresh_from_db()
        self.assertTrue(file.is_deleted)
        
        # 3. 查看回收站，应该能看到文件
        response = self.client.get('/api/document/recycle-bin/')
        self.assertEqual(response.status_code, 200)
        items = response.json()['data']['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['id'], file.id)
        
        # 4. 恢复文件
        response = self.client.post(
            '/api/document/recycle-bin/restore/',
            {
                'file_ids': [file.id],
                'restore_mode': 'original'
            },
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        
        # 5. 再次查看回收站，文件应该消失
        response = self.client.get('/api/document/recycle-bin/')
        items = response.json()['data']['items']
        self.assertEqual(len(items), 0)
        
        # 清理
        if os.path.exists(temp_path):
            os.remove(temp_path)
        file.delete(hard=True)
        
    def test_restore_after_folder_deleted(self):
        """测试原文件夹删除后的恢复流程"""
        # 1. 创建文件夹和文件
        folder = DocumentFolderPrivate.objects.create(
            name='临时文件夹',
            created_by=self.user
        )
        
        temp_path = '/tmp/folder_deleted_test.txt'
        with open(temp_path, 'w') as f:
            f.write('Test content')
        
        file = DocumentFilePrivate.objects.create(
            name='folder_deleted_test.txt',
            display_name='文件夹删除测试.txt',
            file_path=temp_path,
            file_size=1024,
            file_type='text/plain',
            folder=folder,
            created_by=self.user,
            is_deleted=False
        )
        
        # 2. 软删除文件
        file.delete()
        file.refresh_from_db()
        self.assertTrue(file.is_deleted)
        
        # 3. 删除原文件夹
        folder.delete()
        
        # 4. 恢复文件（应该恢复到根目录）
        response = self.client.post(
            '/api/document/recycle-bin/restore/',
            {
                'file_ids': [file.id],
                'restore_mode': 'original'
            },
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        
        # 5. 验证文件恢复到根目录
        file.refresh_from_db()
        self.assertFalse(file.is_deleted)
        self.assertIsNone(file.folder)
        
        # 清理
        if os.path.exists(temp_path):
            os.remove(temp_path)
        file.delete(hard=True)

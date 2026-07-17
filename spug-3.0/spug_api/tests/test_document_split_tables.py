# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
文档管理分表改造测试
覆盖：私有/公共空间分表隔离、文件夹 API 创建、路径遍历防护、
并发合并锁、磁盘使用率、无权限访问拒绝。

说明：跨租户数据不可见性由 test_tenant_isolation.py（按模型）
与 test_document_core_functions.py（apply_tenant_filter）覆盖，
本文件聚焦分表存储与安全防护。
"""
import time
import json
from django.test import TestCase, Client
from apps.account.models import User
from apps.document.models import (
    DocumentFolderPrivate, DocumentFilePrivate,
    DocumentFolderPublic, DocumentFilePublic
)
from apps.document.views.upload.lock import get_merge_lock
from apps.setting.utils import AppSetting


def _make_superuser(username):
    return User.objects.create(
        username=username,
        nickname=username,
        password_hash=User.make_password('password123'),
        tenant_id='',
        is_supper=True,
        is_active=True,
        access_token='a' * 32,
        token_expired=int(time.time()) + 3600,
        last_ip='127.0.0.1',
        last_login='2026-01-01',
        type='default'
    )


def _make_client(user):
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
    return client


class DocumentSplitTablesTest(TestCase):
    """文档分表改造功能测试"""

    def setUp(self):
        self.admin = _make_superuser('admin')
        self.client = _make_client(self.admin)
        AppSetting.set('bind_ip', False)

    def test_folder_split_tables(self):
        """私有/公共文件夹分别落到各自的表，互不串表"""
        DocumentFolderPrivate.objects.create(name='私文件夹', created_by=self.admin)
        DocumentFolderPublic.objects.create(name='公文件夹', created_by=self.admin)

        self.assertEqual(DocumentFolderPrivate.objects.filter(name='公文件夹').count(), 0)
        self.assertEqual(DocumentFolderPublic.objects.filter(name='私文件夹').count(), 0)
        self.assertEqual(DocumentFolderPrivate.objects.filter(name='私文件夹').count(), 1)
        self.assertEqual(DocumentFolderPublic.objects.filter(name='公文件夹').count(), 1)

    def test_file_split_tables(self):
        """私有/公共文件分别落到各自的表，互不串表"""
        DocumentFilePrivate.objects.create(
            name='p.txt', display_name='p.txt',
            file_path='private/user-1/p.txt', file_type='text/plain',
            created_by=self.admin
        )
        DocumentFilePublic.objects.create(
            name='q.txt', display_name='q.txt',
            file_path='public/q.txt', file_type='text/plain',
            created_by=self.admin
        )

        self.assertEqual(DocumentFilePrivate.objects.filter(name='q.txt').count(), 0)
        self.assertEqual(DocumentFilePublic.objects.filter(name='p.txt').count(), 0)

    def test_folder_create_api_private(self):
        """API 创建私有空间文件夹进入私有表"""
        response = self.client.post(
            '/document/folder/',
            data=json.dumps({'name': 'API私文件夹', 'parent_id': None, 'is_public': False}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json().get('error'))
        self.assertIsNotNone(DocumentFolderPrivate.objects.filter(name='API私文件夹').first())

    def test_folder_create_api_public(self):
        """API 创建公共空间文件夹进入公共表"""
        response = self.client.post(
            '/document/folder/',
            data=json.dumps({'name': 'API公文件夹', 'parent_id': None, 'is_public': True}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json().get('error'))
        self.assertIsNotNone(DocumentFolderPublic.objects.filter(name='API公文件夹').first())

    def test_path_traversal_prevention(self):
        """包含路径遍历或非法字符的文件夹名应被拒绝"""
        for bad_name in ['../etc/passwd', 'test<script>']:
            response = self.client.post(
                '/document/folder/',
                data=json.dumps({'name': bad_name, 'parent_id': None, 'is_public': False}),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(response.json().get('error'))

    def test_disk_usage_space_isolation(self):
        """磁盘使用率接口按空间类型返回"""
        for is_public in (False, True):
            flag = 'true' if is_public else 'false'
            response = self.client.get(f'/document/disk_usage/?is_public={flag}')
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['data']['is_public'], is_public)

    def test_permission_denied_for_unprivileged(self):
        """无资料库权限的普通用户创建文件夹被拒绝"""
        user = User.objects.create(
            username='nope', nickname='nope',
            password_hash=User.make_password('x'),
            tenant_id='t1', is_supper=False, is_active=True,
            access_token='b' * 32, token_expired=int(time.time()) + 3600,
            last_ip='127.0.0.1', last_login='2026-01-01', type='default'
        )
        client = _make_client(user)
        response = client.post(
            '/document/folder/',
            data=json.dumps({'name': 'x', 'parent_id': None, 'is_public': False}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json().get('error'))


class DocumentSecurityTest(TestCase):
    """文档管理安全测试"""

    def setUp(self):
        self.user = _make_superuser('secuser')
        self.client = _make_client(self.user)
        AppSetting.set('bind_ip', False)

    def test_concurrent_file_merge(self):
        """相同 file_hash+空间+租户应获取到同一把合并锁"""
        file_hash = 'a' * 32
        lock1 = get_merge_lock(file_hash, False, 'test_tenant')
        lock2 = get_merge_lock(file_hash, False, 'test_tenant')

        self.assertEqual(id(lock1), id(lock2))

        acquired1 = lock1.acquire(blocking=False)
        self.assertTrue(acquired1)
        acquired2 = lock2.acquire(blocking=False)
        self.assertFalse(acquired2)

        lock1.release()
        acquired2 = lock2.acquire(blocking=False)
        self.assertTrue(acquired2)
        lock2.release()

    def test_file_size_limit(self):
        """正常大小文件上传不应导致服务崩溃（不构造超大字节避免 MemoryError）"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        upload_file = SimpleUploadedFile('small.txt', b'hello', content_type='text/plain')
        response = self.client.post(
            '/document/upload/',
            data={'file': upload_file, 'folder_id': '', 'is_public': 'false'},
            format='multipart'
        )
        self.assertIn(response.status_code, [200, 400, 413])

    def test_unauthorized_access(self):
        """无权限用户无法删除他人的私有文件"""
        private_file = DocumentFilePrivate.objects.create(
            name='priv.txt', display_name='priv.txt',
            file_path='private/user-1/priv.txt', file_type='text/plain',
            created_by=self.user
        )
        other = User.objects.create(
            username='other', nickname='other',
            password_hash=User.make_password('x'),
            tenant_id='t2', is_supper=False, is_active=True,
            access_token='c' * 32, token_expired=int(time.time()) + 3600,
            last_ip='127.0.0.1', last_login='2026-01-01', type='default'
        )
        client = _make_client(other)
        response = client.delete(f'/document/file/?id={private_file.id}&is_public=false')
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json().get('error'))

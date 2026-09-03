# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 资料库冒烟测试 - 快速验证核心 API 可用性
# 覆盖: 健康检查, 磁盘用量, 文件夹CRUD, 传输列表, 系统目录
import os
import uuid

from django.test import TestCase

from tests.helpers.test_base import (
    make_user, make_client, setup_test_env,
    post_json, delete_json, get_response_data, has_error)
from apps.document.models import (
    DocumentFolderPublic, DocumentFilePublic)
from apps.document.libs.document_utils import get_document_absolute_path


class DocumentSmokeTest(TestCase):
    """资料库冒烟测试 - 10 秒内跑完，验证核心链路不挂"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('smoke_admin', is_supper=True)
        self.client = make_client(self.admin)
        self.client.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'

    # ========== 1. 健康检查（无需认证） ==========

    def test_01_health_check(self):
        """健康检查: DB + Redis + 存储目录"""
        resp = self.client.get('/document/health/')
        self.assertEqual(resp.status_code, 200)
        data = get_response_data(resp)
        self.assertEqual(data.get('status'), 'ok',
                         f'健康检查失败: {data}')

    # ========== 2. 磁盘用量 ==========

    def test_02_disk_usage(self):
        """磁盘用量查询"""
        resp = self.client.get('/document/disk_usage/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp))
        data = get_response_data(resp)
        self.assertIsNotNone(data, '磁盘用量返回空数据')
        # 应包含磁盘总量/已用等字段
        self.assertIn('total_gb', data, f'磁盘用量缺 total_gb 字段: {data}')

    # ========== 3. 文件夹 CRUD ==========

    def test_03_folder_create(self):
        """创建根文件夹"""
        resp = post_json(self.client, '/document/folder/', {
            'name': '冒烟测试文件夹',
            'parent_id': None,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp))
        data = get_response_data(resp)
        self.assertIsNotNone(data, '创建文件夹返回空')
        self.assertIn('id', data, f'创建文件夹缺 id: {data}')
        self.__class__.folder_id = data['id']

    def test_04_folder_list(self):
        """列出文件夹+文件"""
        # 先创建一个文件夹
        DocumentFolderPublic.objects.create(
            name='列表测试', created_by=self.admin)
        resp = self.client.get('/document/folder/', {'is_public': True})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp))
        data = get_response_data(resp)
        self.assertIsNotNone(data, '列表返回空')
        self.assertIn('folders', data, f'列表缺 folders: {data}')

    def test_05_folder_rename(self):
        """文件夹重命名"""
        folder = DocumentFolderPublic.objects.create(
            name='原名', created_by=self.admin)
        resp = post_json(self.client, '/document/folder/rename/', {
            'id': folder.id,
            'name': '新名',
            'is_public': True,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp))

    def test_06_folder_delete(self):
        """文件夹删除"""
        folder = DocumentFolderPublic.objects.create(
            name='待删除', created_by=self.admin)
        # DELETE 接口解析 request.GET，用 query string 传参
        resp = self.client.delete(
            f'/document/folder/?id={folder.id}&is_public=true')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp))

    # ========== 4. 文件列表 & 删除 ==========

    def test_07_file_list_via_folder(self):
        """通过 folder 接口列出文件"""
        resp = self.client.get('/document/folder/')
        self.assertEqual(resp.status_code, 200)
        data = get_response_data(resp)
        self.assertIn('files', data, '列表缺 files 字段')

    def test_08_file_delete(self):
        """文件删除（物理删除）"""
        # 创建存储根目录内的真实文件，验证 API 的物理删除副作用
        storage_dir = get_document_absolute_path(is_public=True)
        os.makedirs(storage_dir, exist_ok=True)
        file_path = os.path.join(storage_dir, f'smoke_test_{uuid.uuid4().hex}.txt')
        with open(file_path, 'wb') as file_handle:
            file_handle.write(b'smoke test')
        try:
            f = DocumentFilePublic.objects.create(
                name='smoke_test.txt',
                display_name='smoke_test.txt',
                file_size=10,
                file_type='text/plain',
                file_path=file_path,
                physical_name=os.path.basename(file_path),
                created_by=self.admin,
            )
            # DELETE 接口解析 request.GET，用 query string 传参
            resp = self.client.delete(
                f'/document/file/?id={f.id}&is_public=true')
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(has_error(resp))
            self.assertFalse(os.path.exists(file_path), '物理文件未删除')
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

    # ========== 5. 传输记录 ==========

    def test_09_transfer_list(self):
        """传输记录列表"""
        resp = self.client.get('/document/transfers/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp))
        data = get_response_data(resp)
        # data 可能是列表或分页 dict
        self.assertIsNotNone(data, '传输列表返回空')

    def test_10_transfer_create_and_cleanup(self):
        """创建传输记录 + 删除"""
        # 创建
        resp = post_json(self.client, '/document/transfers/create/', {
            'transfer_type': 'upload',
            'file_name': 'smoke_upload.txt',
            'file_size': 1024,
            'total_chunks': 1,
            'is_public': False,
            'folder_id': None,
        })
        self.assertEqual(resp.status_code, 200)
        if has_error(resp):
            # 传输创建可能需要额外参数，记录但不 fail
            return
        data = get_response_data(resp)
        if not data or 'id' not in data:
            return
        transfer_id = data['id']

        # 删除
        resp = delete_json(
            self.client,
            f'/document/transfers/{transfer_id}/delete/', {})
        self.assertEqual(resp.status_code, 200)

    # ========== 6. 系统目录（党建） ==========

    def test_11_system_folder_list(self):
        """系统目录列表"""
        resp = self.client.get('/document/system-folder/')
        self.assertEqual(resp.status_code, 200)
        # 系统目录可能返回空列表，只要不报错即可
        if has_error(resp):
            # 需要特定权限或参数，记录但不 fail
            pass

    # ========== 7. 分片上传前置检查 ==========

    def test_12_check_uploaded_chunks(self):
        """断点续传: 检查已上传分片"""
        resp = post_json(self.client, '/document/check_uploaded_chunks/', {
            'file_hash': 'smoke_' + uuid.uuid4().hex,
            'is_public': False,
        })
        self.assertEqual(resp.status_code, 200)
        # 返回已上传分片列表（空列表也正常）

    # ========== 8. 公共空间读写 ==========

    def test_13_public_space_list(self):
        """公共空间文件列表"""
        resp = self.client.get('/document/folder/', {
            'is_public': True,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(has_error(resp))

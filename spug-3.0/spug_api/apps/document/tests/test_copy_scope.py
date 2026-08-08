"""
党建文档复制物理路径作用域测试。

验证修复：system_folder=party_building_documents 时，复制产生的
新文件物理路径必须位于 storage/documents/party_building_documents/files，
而非普通 public 目录。

测试覆盖：
1. 党建单文件同步复制
2. 党建文件夹递归复制
3. 党建大文件异步复制（真实 Celery task 执行路径）
4. 普通 public 复制回归
5. 党建根目录和深层子目录目标
"""
import os
import time
import uuid
import hashlib
import shutil
import json

from django.test import TestCase, Client, override_settings
from django.conf import settings

from apps.account.models import User
from apps.document.models import (
    DocumentFilePublic,
    DocumentFolderPublic,
    DocumentSystemFolder,
    DocumentTransfer,
)
from apps.document.libs.document_utils import (
    get_document_absolute_path,
    PARTY_BUILDING_DOCUMENTS_SYSTEM_FOLDER,
)
from apps.document.tasks.async_copy import copy_file_async

PB_CODE = PARTY_BUILDING_DOCUMENTS_SYSTEM_FOLDER  # 'party_building_documents'


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


class CopyScopeTestBase(TestCase):
    """党建复制作用域测试基类。"""

    def setUp(self):
        self.user = self._make_user('admin', is_supper=True)
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.user.access_token
        self.client.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'
        # 创建党建根文件夹和系统目录绑定
        self.pb_root_folder = DocumentFolderPublic.objects.create(
            name='党建工作',
            parent=None,
            created_by=self.user,
        )
        self.pb_system_folder = DocumentSystemFolder.objects.create(
            code=PB_CODE,
            name='党建工作',
            folder=self.pb_root_folder,
        )
        self._cleanup_dirs = []

    def tearDown(self):
        for d in self._cleanup_dirs:
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)

    @staticmethod
    def _make_user(username, is_supper=False):
        return User.objects.create(
            username=username,
            nickname=username,
            password_hash='dummy',
            is_supper=is_supper,
            is_active=True,
            access_token=uuid.uuid4().hex,
            token_expired=int(time.time()) + 86400,
            last_ip='127.0.0.1',
            tenant_id='admin',
        )

    # -- path helpers --

    def _pb_root_dir(self):
        """党建根目录绝对路径（folder_id=None）。"""
        return get_document_absolute_path(
            is_public=True, system_folder=PB_CODE
        )

    def _pb_subdir(self, folder_id):
        """党建子目录绝对路径。"""
        return get_document_absolute_path(
            is_public=True, folder_id=folder_id, system_folder=PB_CODE
        )

    def _public_root_dir(self):
        """普通 public 根目录绝对路径。"""
        return get_document_absolute_path(is_public=True)

    def _public_subdir(self, folder_id):
        """普通 public 子目录绝对路径。"""
        return get_document_absolute_path(is_public=True, folder_id=folder_id)

    # -- file helpers --

    def _create_physical_file(self, dir_path, content=None):
        """在指定目录创建物理文件，返回 (filename, abs_path, sha256)。"""
        os.makedirs(dir_path, exist_ok=True)
        self._cleanup_dirs.append(dir_path)
        if content is None:
            content = b'test content ' + uuid.uuid4().hex.encode()
        filename = uuid.uuid4().hex
        abs_path = os.path.join(dir_path, filename)
        with open(abs_path, 'wb') as f:
            f.write(content)
        return filename, abs_path, _sha256(abs_path)

    def _create_pb_subfolder(self, name, parent=None):
        """创建党建子文件夹（必须挂在 pb_root_folder 下）。"""
        if parent is None:
            parent = self.pb_root_folder
        return DocumentFolderPublic.objects.create(
            name=name,
            parent=parent,
            created_by=self.user,
        )

    def _create_pb_file(self, folder, display_name, file_path, physical_name, size=None):
        """创建党建文件 DB 记录。"""
        if size is None:
            size = os.path.getsize(file_path)
        # name 用 UUID 保证唯一约束（name + folder）
        name = f'{uuid.uuid4().hex}{os.path.splitext(display_name)[1]}'
        return DocumentFilePublic.objects.create(
            name=name,
            display_name=display_name,
            physical_name=physical_name,
            file_path=file_path,
            file_size=size,
            file_type=display_name.rsplit('.', 1)[-1] if '.' in display_name else '',
            folder=folder,
            created_by=self.user,
        )

    def _create_public_folder(self, name, parent=None):
        """创建普通 public 文件夹。"""
        return DocumentFolderPublic.objects.create(
            name=name,
            parent=parent,
            created_by=self.user,
        )

    def _create_public_file(self, folder, display_name, file_path, physical_name, size=None):
        """创建普通 public 文件 DB 记录。"""
        if size is None:
            size = os.path.getsize(file_path)
        name = f'{uuid.uuid4().hex}{os.path.splitext(display_name)[1]}'
        return DocumentFilePublic.objects.create(
            name=name,
            display_name=display_name,
            physical_name=physical_name,
            file_path=file_path,
            file_size=size,
            file_type=display_name.rsplit('.', 1)[-1] if '.' in display_name else '',
            folder=folder,
            created_by=self.user,
        )


# ============================================================
# 1. 党建单文件同步复制
# ============================================================

class PartyBuildingSingleFileCopyTest(CopyScopeTestBase):
    """党建单文件同步复制：物理文件必须落入党建目录。"""

    def test_copy_pb_file_to_pb_root(self):
        """复制党建文件到党建根目录（folder_id=None）。"""
        # -- 创建源文件 --
        src_folder = self._create_pb_subfolder('src-folder')
        src_dir = self._pb_subdir(src_folder.id)
        phys_name, src_path, src_hash = self._create_physical_file(src_dir)
        src_file = self._create_pb_file(
            src_folder, 'report.pdf', src_path, phys_name
        )

        # -- 调用复制 API --
        resp = self.client.post('/document/file/copy/', data=json.dumps({
            'id': src_file.id,
            'folder_id': None,
            'is_public': True,
            'system_folder': PB_CODE,
        }), content_type='application/json')

        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertFalse(body.get('error'), body)

        # -- 校验新 DB 记录 --
        new_file = DocumentFilePublic.objects.exclude(id=src_file.id).filter(
            display_name='report.pdf'
        ).first()
        self.assertIsNotNone(new_file, '新文件记录未创建')

        # file_path 必须在党建目录
        pb_root = self._pb_root_dir()
        self.assertTrue(
            new_file.file_path.startswith(pb_root + os.sep),
            f'file_path 不在党建根目录: {new_file.file_path} (期望前缀: {pb_root})'
        )

        # -- 校验物理文件 --
        self.assertTrue(
            os.path.isfile(new_file.file_path),
            f'物理文件不存在: {new_file.file_path}'
        )
        self.assertEqual(
            _sha256(new_file.file_path), src_hash,
            '复制文件内容不一致'
        )

        # -- 校验 public 目录无残留 --
        public_root = self._public_root_dir()
        self.assertFalse(
            os.path.exists(os.path.join(public_root, new_file.physical_name)),
            'public 根目录存在党建文件副本（物理文件落入错误目录）'
        )

    def test_copy_pb_file_to_pb_subfolder(self):
        """复制党建文件到党建子目录。"""
        # -- 创建源文件 --
        src_folder = self._create_pb_subfolder('src-folder2')
        src_dir = self._pb_subdir(src_folder.id)
        phys_name, src_path, src_hash = self._create_physical_file(src_dir)
        src_file = self._create_pb_file(
            src_folder, 'data.xlsx', src_path, phys_name
        )

        # -- 创建目标党建子文件夹 --
        target_folder = self._create_pb_subfolder('target-sub')
        target_dir = self._pb_subdir(target_folder.id)

        # -- 调用复制 API --
        resp = self.client.post('/document/file/copy/', data=json.dumps({
            'id': src_file.id,
            'folder_id': target_folder.id,
            'is_public': True,
            'system_folder': PB_CODE,
        }), content_type='application/json')

        self.assertEqual(resp.status_code, 200, resp.content)

        new_file = DocumentFilePublic.objects.exclude(id=src_file.id).filter(
            display_name='data.xlsx'
        ).first()
        self.assertIsNotNone(new_file)

        # file_path 必须在党建子目录
        self.assertTrue(
            new_file.file_path.startswith(target_dir + os.sep),
            f'file_path 不在党建子目录: {new_file.file_path} (期望前缀: {target_dir})'
        )

        # 物理文件存在且内容一致
        self.assertTrue(os.path.isfile(new_file.file_path))
        self.assertEqual(_sha256(new_file.file_path), src_hash)

        # public 子目录无残留
        public_subdir = self._public_subdir(target_folder.id)
        self.assertFalse(
            os.path.exists(os.path.join(public_subdir, new_file.physical_name)),
            'public 子目录存在党建文件副本'
        )


# ============================================================
# 2. 党建文件夹递归复制
# ============================================================

class PartyBuildingFolderRecursiveCopyTest(CopyScopeTestBase):
    """党建文件夹递归复制：所有子文件 DB 路径和物理路径都在党建目录。"""

    def test_copy_pb_folder_with_subfolders(self):
        """复制党建文件夹（含多层子目录和文件）。"""
        # -- 创建源文件夹结构 --
        # src_root/
        #   file1.txt
        #   sub1/
        #     file2.txt
        #     sub2/
        #       file3.txt
        src_root = self._create_pb_subfolder('src-root')
        src_root_dir = self._pb_subdir(src_root.id)

        # file1.txt
        p1, fp1, h1 = self._create_physical_file(src_root_dir)
        f1 = self._create_pb_file(src_root, 'file1.txt', fp1, p1)

        # sub1
        sub1 = self._create_pb_subfolder('sub1', parent=src_root)
        sub1_dir = self._pb_subdir(sub1.id)
        p2, fp2, h2 = self._create_physical_file(sub1_dir)
        f2 = self._create_pb_file(sub1, 'file2.txt', fp2, p2)

        # sub2 (子子目录)
        sub2 = self._create_pb_subfolder('sub2', parent=sub1)
        sub2_dir = self._pb_subdir(sub2.id)
        p3, fp3, h3 = self._create_physical_file(sub2_dir)
        f3 = self._create_pb_file(sub2, 'file3.txt', fp3, p3)

        # -- 创建目标文件夹 --
        target_root = self._create_pb_subfolder('target-root')

        # -- 调用文件夹复制 API --
        resp = self.client.post('/document/folder/copy/', data=json.dumps({
            'id': src_root.id,
            'target_id': target_root.id,
            'is_public': True,
            'system_folder': PB_CODE,
        }), content_type='application/json')

        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertFalse(body.get('error'), body)

        # -- 校验所有新文件都在党建目录 --
        pb_root = self._pb_root_dir()
        new_files = DocumentFilePublic.objects.exclude(
            id__in=[f1.id, f2.id, f3.id]
        ).filter(display_name__in=['file1.txt', 'file2.txt', 'file3.txt'])

        self.assertEqual(new_files.count(), 3, f'应复制 3 个文件，实际 {new_files.count()}')

        for nf in new_files:
            self.assertTrue(
                nf.file_path.startswith(pb_root + os.sep),
                f'文件 {nf.display_name} 路径不在党建目录: {nf.file_path}'
            )
            self.assertTrue(
                os.path.isfile(nf.file_path),
                f'物理文件不存在: {nf.file_path}'
            )

        # -- 校验 public 目录无残留 --
        public_root = self._public_root_dir()
        for nf in new_files:
            self.assertFalse(
                nf.file_path.startswith(public_root + os.sep),
                f'文件 {nf.display_name} 路径错误落入 public 目录: {nf.file_path}'
            )


# ============================================================
# 3. 党建大文件异步复制
# ============================================================

@override_settings(DOCUMENT_ASYNC_COPY_THRESHOLD=1)
class PartyBuildingAsyncCopyTest(CopyScopeTestBase):
    """党建大文件异步复制：DocumentTransfer.file_path 正确 + Celery task 执行后状态正确。"""

    def test_async_copy_pb_file_to_pb_root(self):
        """异步复制党建文件到党建根目录。"""
        # -- 创建源文件 --
        src_folder = self._create_pb_subfolder('async-src')
        src_dir = self._pb_subdir(src_folder.id)
        phys_name, src_path, src_hash = self._create_physical_file(src_dir)
        src_file = self._create_pb_file(
            src_folder, 'large.pdf', src_path, phys_name
        )

        # -- 调用复制 API (会触发 async path) --
        resp = self.client.post('/document/file/copy/', data=json.dumps({
            'id': src_file.id,
            'folder_id': None,
            'is_public': True,
            'system_folder': PB_CODE,
        }), content_type='application/json')

        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertFalse(body.get('error'), body)

        # -- 校验 DocumentTransfer --
        transfer = DocumentTransfer.objects.first()
        self.assertIsNotNone(transfer, 'DocumentTransfer 未创建')

        pb_root = self._pb_root_dir()
        self.assertTrue(
            transfer.file_path.startswith(pb_root + os.sep),
            f'DocumentTransfer.file_path 不在党建目录: {transfer.file_path}'
        )

        # -- 执行真实 Celery task --
        # delay() 在非 eager 模式不会真正执行，手动 apply
        result = copy_file_async.apply(args=[transfer.id])

        # -- 校验 task 执行结果 --
        transfer.refresh_from_db()
        self.assertEqual(
            transfer.status, 'COMPLETED',
            f'异步复制未完成: status={transfer.status}, error={transfer.error_message}'
        )

        # -- 校验新 DB 文件记录 --
        new_file = DocumentFilePublic.objects.exclude(id=src_file.id).filter(
            display_name='large.pdf'
        ).first()
        self.assertIsNotNone(new_file, '异步复制后新文件记录未创建')
        self.assertTrue(
            new_file.file_path.startswith(pb_root + os.sep),
            f'异步复制文件路径不在党建目录: {new_file.file_path}'
        )

        # -- 校验物理文件 --
        self.assertTrue(
            os.path.isfile(new_file.file_path),
            f'异步复制物理文件不存在: {new_file.file_path}'
        )
        self.assertEqual(
            _sha256(new_file.file_path), src_hash,
            '异步复制文件内容不一致'
        )

        # -- 校验 public 目录无残留 --
        public_root = self._public_root_dir()
        self.assertFalse(
            new_file.file_path.startswith(public_root + os.sep),
            '异步复制文件错误落入 public 目录'
        )


# ============================================================
# 4. 普通 public 复制回归
# ============================================================

class PublicCopyRegressionTest(CopyScopeTestBase):
    """普通 public 复制回归：仍写入 public 目录。"""

    def test_copy_public_file_to_public_root(self):
        """复制普通 public 文件到 public 根目录。"""
        # -- 创建源文件 --
        src_folder = self._create_public_folder('pub-src')
        src_dir = self._public_subdir(src_folder.id)
        phys_name, src_path, src_hash = self._create_physical_file(src_dir)
        src_file = self._create_public_file(
            src_folder, 'pub-doc.pdf', src_path, phys_name
        )

        # -- 调用复制 API --
        resp = self.client.post('/document/file/copy/', data=json.dumps({
            'id': src_file.id,
            'folder_id': None,
            'is_public': True,
        }), content_type='application/json')

        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertFalse(body.get('error'), body)

        # -- 校验新 DB 记录 --
        new_file = DocumentFilePublic.objects.exclude(id=src_file.id).filter(
            display_name='pub-doc.pdf'
        ).first()
        self.assertIsNotNone(new_file)

        public_root = self._public_root_dir()
        self.assertTrue(
            new_file.file_path.startswith(public_root + os.sep),
            f'file_path 不在 public 根目录: {new_file.file_path}'
        )

        # -- 校验物理文件 --
        self.assertTrue(os.path.isfile(new_file.file_path))
        self.assertEqual(_sha256(new_file.file_path), src_hash)

        # -- 校验党建目录无残留 --
        pb_root = self._pb_root_dir()
        self.assertFalse(
            new_file.file_path.startswith(pb_root + os.sep),
            '普通 public 文件错误落入党建目录'
        )

    def test_copy_public_file_to_public_subfolder(self):
        """复制普通 public 文件到 public 子目录。"""
        src_folder = self._create_public_folder('pub-src2')
        src_dir = self._public_subdir(src_folder.id)
        phys_name, src_path, src_hash = self._create_physical_file(src_dir)
        src_file = self._create_public_file(
            src_folder, 'pub-data.xlsx', src_path, phys_name
        )

        target_folder = self._create_public_folder('pub-target')
        target_dir = self._public_subdir(target_folder.id)

        resp = self.client.post('/document/file/copy/', data=json.dumps({
            'id': src_file.id,
            'folder_id': target_folder.id,
            'is_public': True,
        }), content_type='application/json')

        self.assertEqual(resp.status_code, 200, resp.content)

        new_file = DocumentFilePublic.objects.exclude(id=src_file.id).filter(
            display_name='pub-data.xlsx'
        ).first()
        self.assertIsNotNone(new_file)

        self.assertTrue(
            new_file.file_path.startswith(target_dir + os.sep),
            f'file_path 不在 public 子目录: {new_file.file_path}'
        )
        self.assertTrue(os.path.isfile(new_file.file_path))
        self.assertEqual(_sha256(new_file.file_path), src_hash)

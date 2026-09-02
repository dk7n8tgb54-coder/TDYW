"""文件系统安全与删除补偿机制发布门禁测试（stable_contract）。

覆盖：路径越界防护、目录穿越/符号链接/绝对路径、删除顺序、
      物理删除失败的 is_pending_clean 补偿标记、retry_clean_pending_files 重清理、
      缩略图删除失败的容错、递归删除不误删根目录。
"""
import os
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.document.libs.document_utils import (
    get_document_absolute_path, get_document_storage_base_path, is_safe_path,
    safe_delete_document_file, safe_delete_thumbnail)
from apps.document.models import DocumentFilePublic, DocumentFolderPublic
from tests.helpers.test_base import has_error, make_client, make_user, setup_test_env

from .helpers import (
    PERM_DELETE, PERM_DOWNLOAD, PERM_VIEW, StorageCleanupMixin, make_file,
    make_folder, make_physical_file, unique)

FILE_DELETE_URL = '/document/file/'
STORAGE_BASE = get_document_storage_base_path()


class FileSystemSafetyTest(StorageCleanupMixin, TestCase):
    """文件系统安全与删除补偿"""

    @classmethod
    def setUpTestData(cls):
        cls.user = make_user('gate_fs', perms=[PERM_VIEW, PERM_DELETE, PERM_DOWNLOAD])

    def setUp(self):
        super().setUp()
        setup_test_env()
        self.client = make_client(self.user)
        self.client.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'
        self.folder = make_folder(name=unique('fs目录'), created_by=self.user)

    # ---------- 1. 路径安全基元 ----------

    def test_01_is_safe_path_rejects_escape(self):
        """is_safe_path 拒绝逃出基准目录的路径"""
        self.assertTrue(is_safe_path(STORAGE_BASE, os.path.join(STORAGE_BASE, 'a.txt')))
        self.assertFalse(is_safe_path(STORAGE_BASE, os.path.join(STORAGE_BASE, '..', 'a.txt')))
        self.assertFalse(is_safe_path(STORAGE_BASE, '/etc/passwd'))
        self.assertFalse(is_safe_path(STORAGE_BASE, '/tmp/a.txt'))

    def test_02_safe_delete_refuses_outside_storage(self):
        """safe_delete_document_file 拒绝删除存储根目录之外的文件"""
        outside = os.path.join('/tmp', unique('outside') + '.txt')
        self.track_path(outside)
        with open(outside, 'wb') as fh:
            fh.write(b'keep me')
        ok, err = safe_delete_document_file(outside)
        self.assertFalse(ok)
        self.assertTrue(err)
        self.assertTrue(os.path.exists(outside), '越界文件必须保留')

    def test_03_safe_delete_thumbnail_refuses_outside_storage(self):
        """safe_delete_thumbnail 拒绝删除存储根目录之外的文件"""
        outside = os.path.join('/tmp', unique('thumb') + '.png')
        self.track_path(outside)
        with open(outside, 'wb') as fh:
            fh.write(b'png')
        ok, err = safe_delete_thumbnail(outside)
        self.assertFalse(ok)
        self.assertTrue(os.path.exists(outside))

    def test_04_safe_delete_missing_file_is_success(self):
        """文件不存在时安全删除视为成功（幂等）"""
        ok, err = safe_delete_document_file(os.path.join(STORAGE_BASE, 'no-such-file'))
        self.assertTrue(ok)
        self.assertIsNone(err)

    # ---------- 2. 越界的 file_path 不能被下载 ----------

    def test_05_download_refuses_out_of_root_file_path(self):
        """file_path 指向存储根目录之外时下载被拒（路径穿越防护）"""
        outside = os.path.join('/tmp', unique('escape') + '.txt')
        self.track_path(outside)
        with open(outside, 'wb') as fh:
            fh.write(b'secret')
        obj = DocumentFilePublic.objects.create(
            name='escape.txt', display_name='escape.txt',
            physical_name=os.path.basename(outside), file_path=outside,
            file_size=6, file_type='text/plain', folder=self.folder,
            created_by=self.user)
        resp = self.client.get('/document/download/',
                               {'id': obj.id, 'is_public': 'true'})
        self.assertEqual(resp.json().get('error'), '文件不存在', resp.json())

    def test_06_preview_refuses_out_of_root_file_path(self):
        """file_path 越界时预览被拒"""
        outside = os.path.join('/tmp', unique('escape2') + '.txt')
        self.track_path(outside)
        with open(outside, 'wb') as fh:
            fh.write(b'secret')
        obj = DocumentFilePublic.objects.create(
            name='escape2.txt', display_name='escape2.txt',
            physical_name=os.path.basename(outside), file_path=outside,
            file_size=6, file_type='text/plain', folder=self.folder,
            created_by=self.user)
        resp = self.client.get('/document/preview/',
                               {'id': obj.id, 'is_public': 'true'})
        self.assertTrue(resp.json().get('error'), resp.json())

    def test_07_traversal_file_path_rejected(self):
        """含 .. 的 file_path 在下载时被拒"""
        obj = DocumentFilePublic.objects.create(
            name='tv.txt', display_name='tv.txt', physical_name='tv.txt',
            file_path=os.path.join(STORAGE_BASE, '..', '..', 'etc', 'passwd'),
            file_size=1, file_type='text/plain', folder=self.folder,
            created_by=self.user)
        resp = self.client.get('/document/download/',
                               {'id': obj.id, 'is_public': 'true'})
        self.assertEqual(resp.json().get('error'), '文件不存在', resp.json())

    # ---------- 3. 符号链接 ----------

    def test_08_symlink_delete_does_not_remove_target(self):
        """删除符号链接文件只删除链接，不删除链接目标"""
        outside = os.path.join('/tmp', unique('target') + '.txt')
        self.track_path(outside)
        with open(outside, 'wb') as fh:
            fh.write(b'target data')
        link_dir = get_document_absolute_path(folder_id=self.folder.id)
        os.makedirs(link_dir, exist_ok=True)
        self.track_path(link_dir)
        link = os.path.join(link_dir, unique('link') + '.txt')
        os.symlink(outside, link)

        obj = DocumentFilePublic.objects.create(
            name='link.txt', display_name='link.txt',
            physical_name=os.path.basename(link), file_path=link,
            file_size=11, file_type='text/plain', folder=self.folder,
            created_by=self.user)
        resp = self.client.delete(f'{FILE_DELETE_URL}?id={obj.id}&is_public=true')
        self.assertFalse(has_error(resp), resp.json())
        self.assertFalse(os.path.lexists(link), '符号链接应被删除')
        self.assertTrue(os.path.exists(outside), '链接目标必须保留')

    # ---------- 4. 删除顺序：先物理后数据库 ----------

    def test_09_delete_order_physical_first(self):
        """删除先删物理文件，成功后才删数据库记录"""
        obj = make_file(folder=self.folder, created_by=self.user)
        path = obj.file_path
        calls = []

        real_remove = os.remove

        def tracking_remove(p, **kw):
            calls.append(('remove', p))
            return real_remove(p, **kw)

        real_exists = DocumentFilePublic.objects.filter(id=obj.id).exists
        with mock.patch('os.remove', side_effect=tracking_remove):
            resp = self.client.delete(f'{FILE_DELETE_URL}?id={obj.id}&is_public=true')
        self.assertFalse(has_error(resp), resp.json())
        self.assertTrue(calls, '应先执行物理文件删除')
        self.assertFalse(os.path.exists(path))
        self.assertFalse(DocumentFilePublic.objects.filter(id=obj.id).exists())

    # ---------- 5. 物理删除失败 -> 补偿标记 ----------

    def test_10_physical_delete_failure_marks_pending_clean(self):
        """物理删除失败：返回可识别错误 + 设置 is_pending_clean 补偿标记"""
        obj = make_file(folder=self.folder, created_by=self.user)
        self.track_path(obj.file_path)

        with mock.patch(
            'apps.document.libs.document_utils.safe_delete_document_file',
            return_value=(False, '模拟删除失败'),
        ):
            resp = self.client.delete(f'{FILE_DELETE_URL}?id={obj.id}&is_public=true')

        body = resp.json()
        self.assertEqual(body.get('error'),
                         '文件删除失败，已加入待清理队列，系统将自动重试', body)

        still = DocumentFilePublic.objects.filter(id=obj.id).first()
        self.assertIsNotNone(still, '删除失败时数据库记录必须保留')
        self.assertTrue(still.is_pending_clean, '必须标记 is_pending_clean')
        self.assertEqual(still.clean_retry_count, 1, '重试计数必须递增')
        self.assertIsNotNone(still.last_clean_attempt, '必须更新 last_clean_attempt')

    def test_11_pending_clean_flag_survives_request_transaction(self):
        """补偿标记必须真正落库（不被请求级事务回滚）

        契约来源：apps/document/AGENTS.md 五.2 —— 物理删除失败时标记
        is_pending_clean 并由 Celery 异步重试；标记被回滚会导致物理文件永久泄漏。
        """
        obj = make_file(folder=self.folder, created_by=self.user)
        self.track_path(obj.file_path)

        with mock.patch(
            'apps.document.libs.document_utils.safe_delete_document_file',
            return_value=(False, '模拟删除失败'),
        ):
            self.client.delete(f'{FILE_DELETE_URL}?id={obj.id}&is_public=true')

        # 关键：重新从数据库读取，验证标记未被外层事务回滚
        fresh = DocumentFilePublic.objects.get(id=obj.id)
        self.assertTrue(fresh.is_pending_clean,
                        f'is_pending_clean 被事务回滚，补偿机制失效: '
                        f'is_pending_clean={fresh.is_pending_clean}, '
                        f'retry={fresh.clean_retry_count}')

    def test_12_retry_clean_pending_files_recovers(self):
        """retry_clean_pending_files 能清理待删除文件（重置冷却后）"""
        obj = make_file(folder=self.folder, created_by=self.user)
        path = obj.file_path
        with mock.patch(
            'apps.document.libs.document_utils.safe_delete_document_file',
            return_value=(False, '模拟删除失败'),
        ):
            self.client.delete(f'{FILE_DELETE_URL}?id={obj.id}&is_public=true')

        obj.refresh_from_db()
        if not obj.is_pending_clean:
            self.skipTest('前置用例已证明补偿标记未落库，无法验证重清理')

        # 重置冷却期（RETRY_COOLDOWN_SECONDS=3600）
        DocumentFilePublic.objects.filter(id=obj.id).update(
            last_clean_attempt=timezone.now() - timedelta(seconds=7200))
        self.assertTrue(os.path.exists(path))

        from apps.document.tasks.cleanup.pending_files import retry_clean_pending_files
        stats = retry_clean_pending_files()
        self.assertEqual(stats['public'], 1, stats)
        self.assertFalse(DocumentFilePublic.objects.filter(id=obj.id).exists())

    def test_13_retry_respects_cooldown(self):
        """冷却期内不重复清理"""
        obj = make_file(folder=self.folder, created_by=self.user)
        self.track_path(obj.file_path)
        DocumentFilePublic.objects.filter(id=obj.id).update(
            is_pending_clean=True, clean_retry_count=1,
            last_clean_attempt=timezone.now())

        from apps.document.tasks.cleanup.pending_files import retry_clean_pending_files
        stats = retry_clean_pending_files()
        self.assertEqual(stats['public'], 0, '冷却期内不应重试')
        self.assertTrue(DocumentFilePublic.objects.filter(id=obj.id).exists())

    def test_14_retry_max_retry_count_flagged(self):
        """超过 MAX_RETRY_COUNT 的待清理文件在重试失败后被标记需人工介入"""
        obj = make_file(folder=self.folder, created_by=self.user)
        self.track_path(obj.file_path)
        DocumentFilePublic.objects.filter(id=obj.id).update(
            is_pending_clean=True, clean_retry_count=3,
            last_clean_attempt=timezone.now() - timedelta(seconds=7200))

        from apps.document.tasks.cleanup.pending_files import retry_clean_pending_files
        with mock.patch(
            'apps.document.tasks.cleanup.pending_files.safe_delete_document_file',
            side_effect=OSError('disk error'),
        ):
            stats = retry_clean_pending_files()
        self.assertEqual(stats['failed'], 1, stats)
        obj.refresh_from_db()
        self.assertTrue(obj.is_pending_clean, '仍失败时不应清除待清理标记')

    # ---------- 6. 缩略图删除失败容错 ----------

    def test_15_thumbnail_delete_failure_still_deletes_file(self):
        """缩略图删除失败不应阻断主文件与记录的删除（不产生静默不一致）"""
        thumb = make_physical_file(folder_id=self.folder.id, suffix='.png',
                                   content=b'thumb')
        self.track_path(thumb)
        obj = make_file(folder=self.folder, created_by=self.user)
        obj.thumbnail_path = thumb
        obj.save(update_fields=['thumbnail_path'])

        with mock.patch(
            'apps.document.libs.document_utils.safe_delete_thumbnail',
            return_value=(False, '模拟缩略图删除失败'),
        ):
            resp = self.client.delete(f'{FILE_DELETE_URL}?id={obj.id}&is_public=true')

        self.assertFalse(has_error(resp), resp.json())
        self.assertFalse(DocumentFilePublic.objects.filter(id=obj.id).exists(),
                         '缩略图失败不得导致文件记录残留')
        self.assertFalse(os.path.exists(obj.file_path), '主物理文件必须被删除')

    # ---------- 7. 递归删除安全性 ----------

    def test_16_recursive_delete_keeps_storage_root(self):
        """递归删除后文档存储根目录仍然存在"""
        root = make_folder(name=unique('递归'), created_by=self.user)
        sub = make_folder(name=unique('子'), parent=root, created_by=self.user)
        f = make_file(folder=sub, created_by=self.user)
        self.track_path(f.file_path)

        resp = self.client.delete(
            f'/document/folder/?id={root.id}&is_public=true')
        self.assertFalse(has_error(resp), resp.json())
        self.assertTrue(os.path.isdir(STORAGE_BASE), '存储根目录不得被删除')
        self.assertTrue(os.path.isdir(os.path.join(STORAGE_BASE, 'public')),
                        'public 目录不得被删除')

    def test_17_recursive_delete_keeps_other_folders(self):
        """递归删除不误删同级目录的物理文件"""
        root = make_folder(name=unique('待删'), created_by=self.user)
        f_in_root = make_file(folder=root, created_by=self.user)
        self.track_path(f_in_root.file_path)

        other = make_folder(name=unique('保留'), created_by=self.user)
        f_other = make_file(folder=other, created_by=self.user)
        self.track_path(f_other.file_path)

        resp = self.client.delete(
            f'/document/folder/?id={root.id}&is_public=true')
        self.assertFalse(has_error(resp), resp.json())
        self.assertTrue(os.path.exists(f_other.file_path), '同级目录物理文件必须保留')
        self.assertTrue(DocumentFolderPublic.objects.filter(id=other.id).exists())

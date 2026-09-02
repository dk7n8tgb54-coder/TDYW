"""数据完整性、复制移动与审计发布门禁测试（stable_contract）。

覆盖：unique_key 自动计算与 update_fields 保护、循环引用与深度保护、
      文件/文件夹复制移动的 scope 校验与物理副作用、异步复制阈值与幂等、
      删除/移动/复制后的数据关联完整性、FILE_DELETE/FOLDER_DELETE 审计事件。
"""
import os

from django.test import TestCase

from apps.document.constants import DEFAULT_MAX_FOLDER_DEPTH
from apps.document.models import (
    DocumentFilePublic, DocumentFolderPublic, DocumentTransfer)
from apps.logs.models import AuditLog
from tests.helpers.test_base import (
    get_response_data, has_error, make_client, make_user, post_json, setup_test_env)

from .helpers import (
    PB, PERM_COPY, PERM_CREATE_FOLDER, PERM_DELETE, PERM_MOVE, PERM_RENAME,
    PERM_UPLOAD, PERM_VIEW, StorageCleanupMixin, bind_party_building, make_file,
    make_folder, unique)

ASYNC_THRESHOLD = 50 * 1024 * 1024
FILE_COPY_URL = '/document/file/copy/'
FILE_MOVE_URL = '/document/file/move/'
FOLDER_COPY_URL = '/document/folder/copy/'


class DataIntegrityTest(StorageCleanupMixin, TestCase):
    """数据完整性 / 复制移动 / 审计"""

    @classmethod
    def setUpTestData(cls):
        cls.user = make_user('gate_int', perms=[
            PERM_VIEW, PERM_UPLOAD, PERM_CREATE_FOLDER, PERM_RENAME,
            PERM_MOVE, PERM_COPY, PERM_DELETE])

    def setUp(self):
        super().setUp()
        setup_test_env()
        self.client = make_client(self.user)
        self.client.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'

    # ---------- 1. unique_key ----------

    def test_01_unique_key_auto_computed(self):
        """unique_key 在保存时自动计算"""
        folder = make_folder(created_by=self.user)
        self.assertTrue(folder.unique_key, 'unique_key 应自动计算')
        import hashlib
        expect = hashlib.md5(f'{folder.name}:ROOT'.encode('utf-8')).hexdigest()
        self.assertEqual(folder.unique_key, expect)

    def test_02_unique_key_updates_on_rename(self):
        """重命名后 unique_key 重新计算"""
        folder = make_folder(created_by=self.user)
        old = folder.unique_key
        folder.name = unique('改名')
        folder.save()
        self.assertNotEqual(folder.unique_key, old)

    def test_03_unique_key_preserved_with_update_fields(self):
        """使用 update_fields 更新时 unique_key 不会丢失"""
        folder = make_folder(created_by=self.user)
        before = folder.unique_key
        folder.name = unique('更新')
        folder.save(update_fields=['name'])
        folder.refresh_from_db()
        self.assertEqual(folder.name, folder.name)
        self.assertTrue(folder.unique_key, 'update_fields 更新后 unique_key 不应为空')
        self.assertNotEqual(folder.unique_key, before)

    def test_04_same_name_same_parent_conflicts(self):
        """同名同父目录的唯一约束生效"""
        parent = make_folder(created_by=self.user)
        name = unique('同名')
        DocumentFolderPublic.objects.create(name=name, parent=parent,
                                            created_by=self.user)
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DocumentFolderPublic.objects.create(
                    name=name, parent=parent, created_by=self.user)

    # ---------- 2. 循环引用与深度保护 ----------

    def test_05_circular_reference_safe(self):
        """循环引用时 get_full_path 安全返回（不无限递归）"""
        a = make_folder(created_by=self.user)
        b = make_folder(parent=a, created_by=self.user)
        DocumentFolderPublic.objects.filter(id=a.id).update(parent_id=b.id)
        a.refresh_from_db()
        path = a.get_full_path()
        self.assertIsInstance(path, str)
        self.assertIn(a.name, path)

    def test_06_depth_limit_protection(self):
        """超过 DEFAULT_MAX_FOLDER_DEPTH 时路径计算安全返回"""
        self.assertEqual(DEFAULT_MAX_FOLDER_DEPTH, 100)
        parent = None
        chain = []
        for _ in range(DEFAULT_MAX_FOLDER_DEPTH + 5):
            parent = make_folder(parent=parent, created_by=self.user)
            chain.append(parent)
        deepest = chain[-1]
        path = deepest.get_full_path()
        self.assertIsInstance(path, str)
        # 深度保护：参与拼接的层级不超过上限
        self.assertLessEqual(len(path.split('/')), DEFAULT_MAX_FOLDER_DEPTH)

    def test_07_deep_tree_list_does_not_crash(self):
        """深层级目录列表不崩溃"""
        parent = make_folder(created_by=self.user)
        for _ in range(20):
            parent = make_folder(parent=parent, created_by=self.user)
        resp = self.client.get('/document/folder/',
                               {'id': parent.id, 'is_public': 'true'})
        self.assertFalse(has_error(resp), resp.json())

    # ---------- 3. 文件移动 ----------

    def test_08_move_file_within_scope(self):
        """同 scope 内移动文件：物理文件迁移 + 数据库更新"""
        src = make_folder(created_by=self.user)
        dst = make_folder(created_by=self.user)
        obj = make_file(folder=src, created_by=self.user)
        old_path = obj.file_path

        resp = post_json(self.client, FILE_MOVE_URL,
                         {'id': obj.id, 'target_id': dst.id, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())
        obj.refresh_from_db()
        self.assertEqual(obj.folder_id, dst.id)
        self.assertNotEqual(obj.file_path, old_path, '物理路径应随移动变化')
        self.assertFalse(os.path.exists(old_path), '原物理路径应不存在')
        self.track_path(obj.file_path)
        self.assertTrue(os.path.exists(obj.file_path), '目标物理路径应存在')

    def test_09_move_file_to_root(self):
        """移动文件到根目录"""
        src = make_folder(created_by=self.user)
        obj = make_file(folder=src, created_by=self.user)
        resp = post_json(self.client, FILE_MOVE_URL,
                         {'id': obj.id, 'target_id': None, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())
        obj.refresh_from_db()
        self.assertIsNone(obj.folder_id)
        self.track_path(obj.file_path)
        self.assertTrue(os.path.exists(obj.file_path))

    def test_10_move_file_missing_target_rejected(self):
        """移动到不存在的目录被拒，源文件保持不变"""
        src = make_folder(created_by=self.user)
        obj = make_file(folder=src, created_by=self.user)
        old_path = obj.file_path
        resp = post_json(self.client, FILE_MOVE_URL,
                         {'id': obj.id, 'target_id': 99999999, 'is_public': True})
        self.assertTrue(has_error(resp), resp.json())
        obj.refresh_from_db()
        self.assertEqual(obj.folder_id, src.id)
        self.assertEqual(obj.file_path, old_path)
        self.track_path(old_path)

    # ---------- 4. 文件复制 ----------

    def test_11_copy_file_small_is_synchronous(self):
        """小于异步阈值的文件同步复制，副本物理文件存在"""
        src = make_folder(created_by=self.user)
        dst = make_folder(created_by=self.user)
        obj = make_file(folder=src, created_by=self.user, content=b'copy-me')
        self.track_path(obj.file_path)

        resp = post_json(self.client, FILE_COPY_URL,
                         {'id': obj.id, 'folder_id': dst.id, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())
        self.assertEqual(get_response_data(resp).get('status'), 'success')

        # 源文件保留
        obj.refresh_from_db()
        self.assertTrue(os.path.exists(obj.file_path), '源文件必须保留')
        # 副本存在
        copies = DocumentFilePublic.objects.filter(folder=dst)
        self.assertEqual(copies.count(), 1)
        self.track_path(copies.first().file_path)
        self.assertTrue(os.path.exists(copies.first().file_path))
        self.assertNotEqual(copies.first().file_path, obj.file_path)

    def test_12_copy_file_large_is_async(self):
        """大于等于异步阈值(50MB)的文件走异步复制"""
        src = make_folder(created_by=self.user)
        dst = make_folder(created_by=self.user)
        obj = make_file(folder=src, created_by=self.user)
        self.track_path(obj.file_path)
        DocumentFilePublic.objects.filter(id=obj.id).update(
            file_size=ASYNC_THRESHOLD + 1)

        resp = post_json(self.client, FILE_COPY_URL,
                         {'id': obj.id, 'folder_id': dst.id, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data.get('status'), 'pending', data)
        self.assertTrue(data.get('transfer_id'), '异步复制必须返回 transfer_id')

    def test_13_async_copy_task_is_idempotent(self):
        """异步复制任务基于 transfer_id 幂等：已完成不重复复制"""
        src = make_folder(created_by=self.user)
        dst = make_folder(created_by=self.user)
        obj = make_file(folder=src, created_by=self.user)
        self.track_path(obj.file_path)

        from apps.document.libs.document_utils import get_document_absolute_path
        target_dir = get_document_absolute_path(is_public=True, folder_id=dst.id)
        os.makedirs(target_dir, exist_ok=True)  # 视图层负责预建目录
        self.track_path(target_dir)
        target_path = os.path.join(target_dir, unique('copy') + '.txt')
        transfer = DocumentTransfer.objects.create(
            tenant_id=self.user.tenant_id, user=self.user, transfer_type='COPY',
            status='COPYING', file_name=obj.name, file_size=obj.file_size,
            file_path=target_path, is_public=True, folder_id=dst.id,
            source_file_id=obj.id, source_file_path=obj.file_path)

        from apps.document.tasks.async_copy import copy_file_async
        first = copy_file_async.apply(args=(transfer.id,)).get()
        copied = DocumentFilePublic.objects.filter(folder=dst).first()
        if copied:
            self.track_path(copied.file_path)
        self.assertEqual(first['status'], 'completed', first)

        # 标记完成后重复执行必须幂等
        DocumentTransfer.objects.filter(id=transfer.id).update(status='COMPLETED')
        second = copy_file_async.apply(args=(transfer.id,)).get()
        self.assertEqual(second['status'], 'completed')
        self.assertEqual(DocumentFilePublic.objects.filter(folder=dst).count(), 1,
                         '重复执行不得产生多个副本')

    def test_14_async_copy_canceled_is_skipped(self):
        """已取消的异步复制任务直接跳过"""
        src = make_folder(created_by=self.user)
        dst = make_folder(created_by=self.user)
        obj = make_file(folder=src, created_by=self.user)
        self.track_path(obj.file_path)
        transfer = DocumentTransfer.objects.create(
            tenant_id=self.user.tenant_id, user=self.user, transfer_type='COPY',
            status='CANCELED', file_name=obj.name, file_size=obj.file_size,
            file_path='', is_public=True, folder_id=dst.id,
            source_file_id=obj.id, source_file_path=obj.file_path)

        from apps.document.tasks.async_copy import copy_file_async
        result = copy_file_async.apply(args=(transfer.id,)).get()
        self.assertEqual(result['status'], 'canceled')
        self.assertEqual(DocumentFilePublic.objects.filter(folder=dst).count(), 0)

    def test_15_async_copy_missing_transfer_fails_explicitly(self):
        """传输记录不存在时异步复制返回可诊断失败"""
        from apps.document.tasks.async_copy import copy_file_async
        result = copy_file_async.apply(args=(99999999,)).get()
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result.get('error'))

    def test_16_copy_across_scope_rejected(self):
        """跨党建 scope 复制被拒绝"""
        pb_root = make_folder(created_by=self.user)
        bind_party_building(pb_root)
        normal = make_folder(created_by=self.user)
        obj = make_file(folder=normal, created_by=self.user)
        self.track_path(obj.file_path)

        resp = post_json(self.client, FILE_COPY_URL,
                         {'id': obj.id, 'folder_id': pb_root.id, 'is_public': True})
        self.assertTrue(has_error(resp), resp.json())
        self.assertEqual(DocumentFilePublic.objects.filter(folder=pb_root).count(), 0)

    def test_17_folder_copy_across_scope_rejected(self):
        """跨党建 scope 复制目录被拒绝"""
        pb_root = make_folder(created_by=self.user)
        bind_party_building(pb_root)
        normal = make_folder(created_by=self.user)
        resp = post_json(self.client, FOLDER_COPY_URL,
                         {'id': normal.id, 'target_id': pb_root.id, 'is_public': True})
        self.assertTrue(has_error(resp), resp.json())

    # ---------- 5. 审计事件 ----------

    def test_18_file_delete_audit_recorded(self):
        """文件删除记录 FILE_DELETE 审计事件"""
        obj = make_file(folder=None, created_by=self.user)
        self.track_path(obj.file_path)
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.delete(
                f'/document/file/?id={obj.id}&is_public=true')
        self.assertFalse(has_error(resp), resp.json())
        log = AuditLog.objects.filter(target_type='document', action='delete',
                                      target_id=str(obj.id)).first()
        self.assertIsNotNone(log, '文件删除必须记录审计日志')
        self.assertEqual(log.target_name, obj.name)

    def test_19_folder_delete_audit_recorded(self):
        """文件夹删除记录 FOLDER_DELETE 审计事件"""
        folder = make_folder(created_by=self.user)
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.delete(
                f'/document/folder/?id={folder.id}&is_public=true')
        self.assertFalse(has_error(resp), resp.json())
        log = AuditLog.objects.filter(target_type='document', action='delete',
                                      target_id=str(folder.id)).first()
        self.assertIsNotNone(log, '文件夹删除必须记录审计日志')

    def test_20_folder_create_audit_recorded(self):
        """创建文件夹记录 create 审计事件"""
        name = unique('审计目录')
        with self.captureOnCommitCallbacks(execute=True):
            resp = post_json(self.client, '/document/folder/',
                             {'name': name, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())
        folder_id = get_response_data(resp)['id']
        log = AuditLog.objects.filter(target_type='document', action='create',
                                      target_id=str(folder_id)).first()
        self.assertIsNotNone(log, '创建文件夹必须记录审计日志')

    # ---------- 6. 操作后数据关联完整性 ----------

    def test_21_move_folder_keeps_children_links(self):
        """移动文件夹后子层级关联完整"""
        a = make_folder(created_by=self.user)
        b = make_folder(created_by=self.user)
        child = make_folder(parent=a, created_by=self.user)
        f = make_file(folder=child, created_by=self.user)
        self.track_path(f.file_path)

        resp = post_json(self.client, '/document/folder/move/',
                         {'id': a.id, 'target_id': b.id, 'is_public': True})
        self.assertFalse(has_error(resp), resp.json())
        a.refresh_from_db()
        child.refresh_from_db()
        f.refresh_from_db()
        self.assertEqual(a.parent_id, b.id)
        self.assertEqual(child.parent_id, a.id)
        self.assertEqual(f.folder_id, child.id)

    def test_22_delete_folder_removes_orphan_files(self):
        """删除文件夹后不留孤儿文件记录"""
        root = make_folder(created_by=self.user)
        sub = make_folder(parent=root, created_by=self.user)
        f = make_file(folder=sub, created_by=self.user)
        self.track_path(f.file_path)
        self.client.delete(f'/document/folder/?id={root.id}&is_public=true')
        self.assertFalse(DocumentFilePublic.objects.filter(id=f.id).exists())
        self.assertEqual(
            DocumentFilePublic.objects.filter(folder__isnull=True).count(), 0)

    def test_23_failed_delete_leaves_no_half_state(self):
        """删除失败时不留下不可追踪的半成品：记录与物理文件保持一致"""
        obj = make_file(folder=self.folder, created_by=self.user) \
            if hasattr(self, 'folder') else make_file(created_by=self.user)
        self.track_path(obj.file_path)
        from unittest import mock
        with mock.patch(
            'apps.document.libs.document_utils.safe_delete_document_file',
            return_value=(False, '模拟失败'),
        ):
            self.client.delete(f'/document/file/?id={obj.id}&is_public=true')
        still = DocumentFilePublic.objects.filter(id=obj.id).first()
        self.assertIsNotNone(still)
        self.assertTrue(os.path.exists(still.file_path),
                        '删除失败时物理文件必须仍在，避免记录与文件不一致')

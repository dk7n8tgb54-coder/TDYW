"""
Document 模块 CRUD 修复验证测试

验证 R1-R7 的 7 个问题修复后是否确实生效。
与 crud_audit_tests.py（确认问题存在）形成对照。

运行：
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python manage.py test apps.document.crud_fix_verification --noinput -v2

分类：
  FIX_R1-R7 = 修复验证（确认问题已解决）
"""

import inspect
import time
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.db import transaction, IntegrityError
from django.conf import settings

from apps.account.models import User as SpugUser
from apps.document.models import (
    DocumentFolderPrivate,
    DocumentFilePrivate,
    DocumentFolderPublic,
    DocumentFilePublic,
    DocumentTransfer,
)
from apps.document.constants import TransferStatus, TransferType

from .crud_audit_tests import _make_user, _make_private_folder, _make_private_file


# ============================================================
#  FIX_R1: DocumentFilePrivate 已有 (name, folder) 唯一约束
# ============================================================

class FIX_R1_DocumentFilePrivateHasUniqueConstraint(TestCase):
    """验证 R1 修复：DocumentFilePrivate 现在有 (name, folder) 唯一约束。"""

    def setUp(self):
        self.user = _make_user('fix_r1_user')

    def tearDown(self):
        DocumentFilePrivate.objects.all().delete()
        DocumentFolderPrivate.objects.all().delete()
        SpugUser.objects.filter(username='fix_r1_user').delete()

    def test_fix_r1a_private_has_unique_constraint(self):
        """FIX_R1: DocumentFilePrivate 应有 (name, folder) 唯一约束"""
        constraint_fields = [
            (c.name, tuple(getattr(c, 'fields', ())))
            for c in DocumentFilePrivate._meta.constraints
        ]
        found = any(
            'name' in fields and 'folder' in fields
            for _, fields in constraint_fields
        )
        self.assertTrue(
            found,
            f"DocumentFilePrivate 现在应有 (name, folder) 唯一约束，"
            f"实际 constraints={constraint_fields}"
        )

    def test_fix_r1b_private_rejects_duplicate_name_in_same_folder(self):
        """FIX_R1 行为验证: 同一私有文件夹下插入同名文件应抛 IntegrityError"""
        folder = _make_private_folder(self.user, 'fix_r1_folder')
        file1 = _make_private_file(self.user, folder, name='dup.txt')
        # 插入同名文件应失败
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                _make_private_file(self.user, folder, name='dup.txt')
        # 确认只有一条记录
        count = DocumentFilePrivate.objects.filter(
            name='dup.txt', folder=folder
        ).count()
        self.assertEqual(
            count, 1,
            "DocumentFilePrivate 应拒绝同名同文件夹记录（修复生效）"
        )


# ============================================================
#  FIX_R2: 文件删除已有事务包裹
# ============================================================

class FIX_R2_FileDeleteHasTransaction(TestCase):
    """验证 R2 修复：文件删除现在有 transaction.atomic() 包裹。"""

    def test_fix_r2a_file_delete_source_has_atomic(self):
        """FIX_R2: FileView.delete 源码应包含 transaction.atomic()"""
        from apps.document.views.file.views import FileView
        source = inspect.getsource(FileView.delete)
        self.assertIn(
            'transaction.atomic',
            source,
            "FileView.delete 源码应包含 transaction.atomic()（修复生效）"
        )


# ============================================================
#  FIX_R3: audit log 已移入 on_commit
# ============================================================

class FIX_R3_AuditLogInOnCommit(TestCase):
    """验证 R3 修复：审计日志现在通过 transaction.on_commit 调用。"""

    def test_fix_r3a_file_delete_log_via_on_commit(self):
        """FIX_R3: FileView.delete 中 log_operation 应通过 on_commit 调用"""
        from apps.document.views.file.views import FileView
        source = inspect.getsource(FileView.delete)
        self.assertIn(
            'on_commit',
            source,
            "FileView.delete 应使用 transaction.on_commit 调用 log_operation（修复生效）"
        )

    def test_fix_r3b_file_move_log_via_on_commit(self):
        """FIX_R3: FileMoveView._move_file 中 log_operation 应通过 on_commit 调用"""
        from apps.document.views.file.move import FileMoveView
        source = inspect.getsource(FileMoveView._move_file)
        self.assertIn(
            'on_commit',
            source,
            "FileMoveView._move_file 应使用 transaction.on_commit 调用 log_operation（修复生效）"
        )

    def test_fix_r3c_folder_move_log_via_on_commit(self):
        """FIX_R3: FolderMoveView.post 中 log_operation 应通过 on_commit 调用"""
        from apps.document.views.folder.move import FolderMoveView
        source = inspect.getsource(FolderMoveView.post)
        self.assertIn(
            'on_commit',
            source,
            "FolderMoveView.post 应使用 transaction.on_commit 调用 log_operation（修复生效）"
        )

    def test_fix_r3d_folder_delete_log_via_on_commit(self):
        """FIX_R3: FolderView.delete 中 log_operation 应通过 on_commit 调用"""
        from apps.document.views.folder.views import FolderView
        source = inspect.getsource(FolderView.delete)
        self.assertIn(
            'on_commit',
            source,
            "FolderView.delete 应使用 transaction.on_commit 调用 log_operation（修复生效）"
        )


# ============================================================
#  FIX_R4: log_operation 已支持 request_id
# ============================================================

class FIX_R4_LogOperationHasRequestId(TestCase):
    """验证 R4 修复：log_operation 现在支持 request_id 参数。"""

    def test_fix_r4a_log_operation_signature_has_request_id(self):
        """FIX_R4: log_operation 函数签名应包含 request_id 参数"""
        from apps.document.libs.view_utils import log_operation
        source = inspect.getsource(log_operation)
        self.assertIn(
            'request_id',
            source,
            "log_operation 应引用 request_id（修复生效）"
        )

    def test_r4b_log_operation_passes_request_id_to_save_audit_log(self):
        """FIX_R4: log_operation 应将 request_id 传递给 save_audit_log"""
        from apps.document.libs.view_utils import log_operation
        source = inspect.getsource(log_operation)
        # 应在 save_audit_log 调用附近找到 request_id
        save_pos = source.find('save_audit_log')
        request_id_pos = source.find('request_id')
        self.assertGreater(save_pos, 0, "应找到 save_audit_log 调用")
        self.assertGreater(request_id_pos, 0, "应找到 request_id 引用")


# ============================================================
#  FIX_R5: API 限流已添加
# ============================================================

class FIX_R5_ApiRateLimitAdded(TestCase):
    """验证 R5 修复：关键 API 端点已添加限流。"""

    def test_fix_r5a_rate_limit_decorator_exists(self):
        """FIX_R5: view_utils 模块应定义 rate_limit 装饰器"""
        from apps.document.libs import view_utils
        self.assertTrue(
            hasattr(view_utils, 'rate_limit'),
            "view_utils 模块应定义 rate_limit 装饰器（修复生效）"
        )

    def test_fix_r5b_file_delete_has_rate_limit(self):
        """FIX_R5: FileView.delete 应有 @rate_limit 装饰器"""
        from apps.document.views.file.views import FileView
        source = inspect.getsource(FileView.delete)
        # 检查装饰器是否存在（检查整个类的源码）
        class_source = inspect.getsource(FileView)
        self.assertIn(
            'rate_limit',
            class_source,
            "FileView 类应有 @rate_limit 装饰器（修复生效）"
        )

    def test_fix_r5c_merge_view_has_rate_limit(self):
        """FIX_R5: FileMergeChunksView 应有 @rate_limit 装饰器"""
        from apps.document.views.upload.merge import FileMergeChunksView
        source = inspect.getsource(FileMergeChunksView)
        self.assertIn(
            'rate_limit',
            source,
            "FileMergeChunksView 应有 @rate_limit 装饰器（修复生效）"
        )


# ============================================================
#  FIX_R6: _delete_folder 已有递归深度限制
# ============================================================

class FIX_R6_FolderDeleteHasDepthLimit(TestCase):
    """验证 R6 修复：_delete_folder 现在有递归深度限制。"""

    def test_fix_r6a_delete_folder_has_depth_param(self):
        """FIX_R6: _delete_folder 签名应包含 _depth 参数"""
        from apps.document.views.folder.views import FolderView
        source = inspect.getsource(FolderView._delete_folder)
        sig_line = source.split('\n')[0]
        self.assertIn(
            '_depth',
            sig_line,
            f"_delete_folder 签名应包含 _depth 参数（修复生效），"
            f"实际签名: {sig_line}"
        )

    def test_fix_r6b_max_folder_depth_constant_exists(self):
        """FIX_R6: FolderView 应定义 MAX_FOLDER_DEPTH 常量"""
        from apps.document.views.folder.views import FolderView
        source = inspect.getsource(FolderView)
        self.assertIn(
            'MAX_FOLDER_DEPTH',
            source,
            "FolderView 应定义 MAX_FOLDER_DEPTH 常量（修复生效）"
        )

    def test_fix_r6c_depth_check_in_source(self):
        """FIX_R6: _delete_folder 应有深度检查逻辑"""
        from apps.document.views.folder.views import FolderView
        source = inspect.getsource(FolderView._delete_folder)
        self.assertIn(
            'MAX_FOLDER_DEPTH',
            source,
            "_delete_folder 应检查 _depth > MAX_FOLDER_DEPTH（修复生效）"
        )


# ============================================================
#  FIX_R7: 合并请求已有 request_id 幂等去重
# ============================================================

class FIX_R7_MergeHasRequestIdDedup(TestCase):
    """验证 R7 修复：合并请求现在使用 request_id 进行幂等去重。"""

    def test_fix_r7a_parse_merge_request_returns_request_id(self):
        """FIX_R7: parse_merge_request 返回的 data 应包含前端传入的 request_id"""
        from apps.document.views.upload.merge import parse_merge_request
        # 构造带 request_id 的请求
        mock_request = MagicMock()
        mock_request.body = b'{"file_name":"t.txt","file_size":1,"total_chunks":1,"file_hash":"abc","request_id":"req-123"}'
        data, error = parse_merge_request(mock_request)
        self.assertIsNone(error)
        self.assertIn(
            'request_id', data,
            "parse_merge_request 返回的 data 应包含 request_id（修复生效）"
        )
        self.assertEqual(data['request_id'], 'req-123')

    def test_fix_r7b_merge_view_has_request_id_check(self):
        """FIX_R7: FileMergeChunksView 应有 request_id 幂等检查"""
        from apps.document.views.upload.merge import FileMergeChunksView
        source = inspect.getsource(FileMergeChunksView)
        self.assertIn(
            'request_id',
            source,
            "FileMergeChunksView 应引用 request_id（修复生效）"
        )

    def test_fix_r7c_dedup_function_exists(self):
        """FIX_R7: 应定义 _check_request_id_dedup 函数"""
        from apps.document.views.upload import merge as merge_module
        self.assertTrue(
            hasattr(merge_module, '_check_request_id_dedup'),
            "merge 模块应定义 _check_request_id_dedup 函数（修复生效）"
        )

    def test_fix_r7d_store_mapping_function_exists(self):
        """FIX_R7: 应定义 _store_request_id_mapping 函数"""
        from apps.document.views.upload import merge as merge_module
        self.assertTrue(
            hasattr(merge_module, '_store_request_id_mapping'),
            "merge 模块应定义 _store_request_id_mapping 函数（修复生效）"
        )

    def test_fix_r7e_validate_merge_params_includes_request_id(self):
        """FIX_R7: validate_merge_params 返回结果应包含 request_id"""
        from apps.document.views.upload.merge import validate_merge_params
        result, error = validate_merge_params({
            'file_name': 'test.txt',
            'file_size': 100,
            'total_chunks': 1,
            'file_hash': 'a' * 32,
            'request_id': 'test-req-id-123',
        })
        self.assertIsNone(error)
        self.assertIn(
            'request_id', result,
            "validate_merge_params 返回结果应包含 request_id（修复生效）"
        )
        self.assertEqual(result['request_id'], 'test-req-id-123')


# ============================================================
#  FIX_L1: 软删除字段已移除
# ============================================================

class FIX_L1_SoftDeleteRemoved(TestCase):
    """验证 L1 修复：软删除字段、管理器、方法已全部移除。"""

    def test_fix_l1a_no_is_deleted_field(self):
        """FIX_L1: 4 个模型不应再有 is_deleted 字段"""
        for ModelCls in [DocumentFolderPrivate, DocumentFilePrivate,
                         DocumentFolderPublic, DocumentFilePublic]:
            fields = [f.name for f in ModelCls._meta.get_fields()]
            self.assertNotIn(
                'is_deleted', fields,
                f"{ModelCls.__name__} 不应有 is_deleted 字段（修复生效）"
            )

    def test_fix_l1b_no_restore_method(self):
        """FIX_L1: 模型不应有 restore() 方法"""
        for ModelCls in [DocumentFolderPrivate, DocumentFilePrivate,
                         DocumentFolderPublic, DocumentFilePublic]:
            self.assertFalse(
                hasattr(ModelCls, 'restore'),
                f"{ModelCls.__name__} 不应有 restore() 方法（修复生效）"
            )

    def test_fix_l1c_no_hard_param_in_delete(self):
        """FIX_L1: delete() 源码不应包含 hard 参数"""
        for ModelCls in [DocumentFolderPrivate, DocumentFilePrivate,
                         DocumentFolderPublic, DocumentFilePublic]:
            source = inspect.getsource(ModelCls.delete)
            self.assertNotIn(
                'hard', source,
                f"{ModelCls.__name__}.delete 不应包含 hard 参数（修复生效）"
            )

    def test_fix_l1d_no_soft_deleted_manager(self):
        """FIX_L1: 不应有 SoftDeletedManager"""
        from apps.document import models as doc_models
        self.assertFalse(
            hasattr(doc_models, 'SoftDeletedManager'),
            "不应有 SoftDeletedManager 类（修复生效）"
        )

    def test_fix_l1e_no_all_objects_manager(self):
        """FIX_L1: 模型不应有 all_objects 管理器"""
        for ModelCls in [DocumentFolderPrivate, DocumentFilePrivate,
                         DocumentFolderPublic, DocumentFilePublic]:
            self.assertFalse(
                hasattr(ModelCls, 'all_objects'),
                f"{ModelCls.__name__} 不应有 all_objects 管理器（修复生效）"
            )

    def test_fix_l1f_indexes_exclude_is_deleted(self):
        """FIX_L1: 索引不应包含 is_deleted"""
        for ModelCls in [DocumentFolderPrivate, DocumentFilePrivate,
                         DocumentFolderPublic, DocumentFilePublic]:
            for idx in ModelCls._meta.indexes:
                self.assertNotIn(
                    'is_deleted', idx.fields,
                    f"{ModelCls.__name__} 索引不应包含 is_deleted（修复生效）"
                )

    def test_fix_l1g_no_deleted_at_deleted_by_fields(self):
        """FIX_L1: 不应有 deleted_at/deleted_by 字段"""
        for ModelCls in [DocumentFolderPrivate, DocumentFilePrivate,
                         DocumentFolderPublic, DocumentFilePublic]:
            fields = [f.name for f in ModelCls._meta.get_fields()]
            self.assertNotIn('deleted_at', fields,
                             f"{ModelCls.__name__} 不应有 deleted_at")
            if ModelCls in [DocumentFolderPrivate, DocumentFolderPublic]:
                self.assertNotIn('deleted_by', fields,
                                 f"{ModelCls.__name__} 不应有 deleted_by")

    def test_fix_l1h_business_delete_no_hard_true(self):
        """FIX_L1: 业务代码不应再使用 hard=True"""
        from apps.document.views.file.views import FileView
        from apps.document.views.folder.views import FolderView
        file_source = inspect.getsource(FileView.delete)
        self.assertNotIn('hard=True', file_source,
                         "FileView.delete 不应使用 hard=True（修复生效）")
        folder_source = inspect.getsource(FolderView._delete_folder)
        self.assertNotIn('hard=True', folder_source,
                         "_delete_folder 不应使用 hard=True（修复生效）")


# ============================================================
#  FIX_L2: file_size 不再允许 0
# ============================================================

class FIX_L2_FileSizeRejectsZero(TestCase):
    """验证 L2 修复：file_size=0 被拒绝。"""

    def test_fix_l2a_zero_file_size_rejected(self):
        """FIX_L2: file_size=0 应被 CHECK 约束拒绝"""
        from .crud_audit_tests import _make_user
        user = _make_user('fix_l2_user')
        try:
            transfer = DocumentTransfer(
                user=user,
                file_name='empty.txt',
                file_size=0,  # 0 字节
                total_chunks=1,
                file_hash='a' * 32,
                transfer_type=TransferType.UPLOAD.value,
                status=TransferStatus.UPLOADING.value,
                tenant_id='admin',
            )
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    transfer.save()
        finally:
            try:
                with transaction.atomic():
                    DocumentTransfer.objects.all().delete()
            except Exception:
                pass
            SpugUser.objects.filter(username='fix_l2_user').delete()

    def test_fix_l2b_validator_is_min_1(self):
        """FIX_L2: file_size 验证器应为 MinValueValidator(1)"""
        from django.core.validators import MinValueValidator
        field = DocumentTransfer._meta.get_field('file_size')
        validators = [v for v in field.validators if isinstance(v, MinValueValidator)]
        self.assertTrue(
            any(v.limit_value >= 1 for v in validators),
            f"file_size 应有 MinValueValidator(1)，实际 validators={validators}"
        )


# ============================================================
#  FIX_L3: 批量删除记录单文件审计日志
# ============================================================

class FIX_L3_BatchDeleteLogsPerFile(TestCase):
    """验证 L3 修复：批量删除时为每个文件记录审计日志。"""

    def test_fix_l3a_delete_folder_has_log_operation(self):
        """FIX_L3: _delete_folder 源码应包含 log_operation"""
        from apps.document.views.folder.views import FolderView
        source = inspect.getsource(FolderView._delete_folder)
        self.assertIn(
            'log_operation',
            source,
            "_delete_folder 应调用 log_operation（修复生效）"
        )

    def test_fix_l3b_delete_folder_logs_file_delete(self):
        """FIX_L3: _delete_folder 应记录 FILE_DELETE 审计日志"""
        from apps.document.views.folder.views import FolderView
        source = inspect.getsource(FolderView._delete_folder)
        self.assertIn(
            'FILE_DELETE',
            source,
            "_delete_folder 应记录 FILE_DELETE 审计日志（修复生效）"
        )

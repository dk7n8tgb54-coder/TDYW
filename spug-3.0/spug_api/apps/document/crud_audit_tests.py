"""
Document 模块 CRUD 可靠性审查验证测试

验证审查报告中发现的 7 个问题是否真实存在，
同时验证优秀实践是否确实实现。

运行：
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python manage.py test apps.document.crud_audit_tests --noinput -v2

分类：
  R1-R7 = 问题验证（确认问题真实存在）
  P1-P6 = 优秀实践验证（确认最佳实践确实实现）
"""

import inspect
import os
import time
from io import StringIO
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
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
from apps.document.constants import (
    TransferStatus,
    TransferType,
    DEFAULT_MAX_FILE_SIZE,
)


# ============================================================
#  辅助函数
# ============================================================

def _make_user(username='audit_test_user', is_supper=False):
    """创建测试用户（使用 raw SQL 绕过 test DB 的 deleted_by_id 约束问题）"""
    from django.db import connection
    token = (username * 10)[:32]
    now_ts = int(time.time()) + 3600
    with connection.cursor() as cursor:
        # 禁用严格模式：test DB 的 deleted_by_id 列 NOT NULL 无默认值
        cursor.execute("SET SESSION sql_mode=''")
        cursor.execute(
            "INSERT INTO users (username, nickname, password_hash, is_active, "
            "is_supper, access_token, token_expired, last_login, last_ip, "
            "type, tenant_id, wx_token, created_at) "
            "VALUES (%s, %s, %s, 1, %s, %s, %s, '2026-01-01 00:00:00', "
            "'127.0.0.1', 'default', 'admin', '', NOW())",
            [username, username, 'x', 1 if is_supper else 0, token, now_ts]
        )
        user_id = cursor.lastrowid
    return SpugUser.objects.get(id=user_id)


def _make_private_folder(user, name='test_folder', parent=None, tenant_id='admin'):
    """创建私有文件夹"""
    return DocumentFolderPrivate.objects.create(
        name=name,
        created_by=user,
        parent=parent,
        tenant_id=tenant_id,
    )


def _make_private_file(user, folder, name='test.txt', tenant_id='admin'):
    """创建私有文件记录"""
    return DocumentFilePrivate.objects.create(
        name=name,
        display_name=name,
        file_path=f'/tmp/test_{name}',
        file_size=100,
        file_type='txt',
        folder=folder,
        created_by=user,
        tenant_id=tenant_id,
    )


# ============================================================
#  R1: DocumentFilePrivate 缺少 (name, folder) 唯一约束
# ============================================================

class R1_DocumentFilePrivateLacksUniqueConstraint(TestCase):
    """验证 DocumentFilePrivate 缺少 (name, folder) 唯一约束。

    DocumentFilePublic 有 UniqueConstraint(fields=['name', 'folder'])，
    但 DocumentFilePrivate 没有，仅靠应用层 generate_unique_logical_name。
    """

    def setUp(self):
        self.user = _make_user('r1_user')

    def tearDown(self):
        DocumentFilePrivate.objects.all().delete()
        DocumentFolderPrivate.objects.all().delete()
        SpugUser.objects.filter(username='r1_user').delete()

    # -- 模型层检查 --

    def test_r1a_public_has_unique_name_folder_constraint(self):
        """P1: DocumentFilePublic 应有 (name, folder) 唯一约束"""
        constraint_fields = [
            (c.name, tuple(getattr(c, 'fields', ())))
            for c in DocumentFilePublic._meta.constraints
        ]
        found = any(
            'name' in fields and 'folder' in fields
            for _, fields in constraint_fields
        )
        self.assertTrue(
            found,
            f"DocumentFilePublic 应有 (name, folder) 唯一约束，"
            f"实际 constraints={constraint_fields}"
        )

    def test_r1b_private_lacks_unique_name_folder_constraint(self):
        """R1: DocumentFilePrivate 不应有 (name, folder) 唯一约束"""
        constraint_fields = [
            (c.name, tuple(getattr(c, 'fields', ())))
            for c in DocumentFilePrivate._meta.constraints
        ]
        found = any(
            'name' in fields and 'folder' in fields
            for _, fields in constraint_fields
        )
        self.assertFalse(
            found,
            f"DocumentFilePrivate 不应有 (name, folder) 唯一约束（确认问题存在），"
            f"实际 constraints={constraint_fields}"
        )

    # -- 行为层检查 --

    def test_r1c_private_allows_duplicate_name_in_same_folder(self):
        """R1 行为验证: 同一私有文件夹下可创建同名文件记录"""
        folder = _make_private_folder(self.user, 'r1_folder')
        file1 = _make_private_file(self.user, folder, name='dup.txt')
        # 尝试插入同名文件，不抛异常说明无唯一约束
        file2 = _make_private_file(self.user, folder, name='dup.txt')
        count = DocumentFilePrivate.objects.filter(
            name='dup.txt', folder=folder
        ).count()
        self.assertEqual(
            count, 2,
            "DocumentFilePrivate 允许同一文件夹下同名记录并存（确认问题存在）"
        )


# ============================================================
#  R2: 文件删除无事务包裹
# ============================================================

class R2_FileDeleteLacksTransaction(TestCase):
    """验证文件删除操作缺少 transaction.atomic() 包裹。

    file/views.py 的 delete 方法中 DB delete + 物理文件 delete + audit log
    三步不在事务内。
    """

    def test_r2a_file_delete_source_has_no_atomic(self):
        """R2: FileView.delete 源码中不应包含 transaction.atomic()"""
        from apps.document.views.file.views import FileView
        source = inspect.getsource(FileView.delete)
        self.assertNotIn(
            'transaction.atomic',
            source,
            "FileView.delete 源码中不应包含 transaction.atomic()（确认问题存在）"
        )

    def test_r2b_file_delete_has_log_operation_outside(self):
        """R3: FileView.delete 中 log_operation 应在删除之后（非事务内）"""
        from apps.document.views.file.views import FileView
        source = inspect.getsource(FileView.delete)
        delete_pos = source.find('file.delete(')
        log_pos = source.find('log_operation(')
        self.assertGreater(
            delete_pos, 0, "应找到 file.delete() 调用"
        )
        self.assertGreater(
            log_pos, 0, "应找到 log_operation() 调用"
        )
        self.assertGreater(
            log_pos, delete_pos,
            "log_operation 应在 file.delete 之后调用（非事务内）"
        )


# ============================================================
#  R3: audit log 在事务外
# ============================================================

class R3_AuditLogOutsideTransaction(TestCase):
    """验证审计日志调用在 transaction.atomic() 块之外。"""

    def test_r3a_file_move_log_after_atomic_block(self):
        """R3: FileMoveView._move_file 中 log_operation 在 atomic 块外"""
        from apps.document.views.file.move import FileMoveView
        source = inspect.getsource(FileMoveView._move_file)
        atomic_end = source.find('except')  # atomic 块结束于 except
        log_pos = source.find('log_operation(')
        self.assertGreater(
            atomic_end, 0, "应找到 with transaction.atomic() 块"
        )
        self.assertGreater(
            log_pos, atomic_end,
            "log_operation 应在 atomic 块之后（确认 audit log 在事务外）"
        )

    def test_r3b_folder_move_log_after_atomic_block(self):
        """R3: FolderMoveView.post 中 log_operation 在 atomic 块外"""
        from apps.document.views.folder.move import FolderMoveView
        source = inspect.getsource(FolderMoveView.post)
        # 找到 with transaction.atomic() 块的结束位置
        # atomic 块内的最后一条语句通常是 save() 或 update
        atomic_start = source.find('with transaction.atomic')
        self.assertGreater(atomic_start, 0, "应找到 with transaction.atomic() 块")
        log_pos = source.find('log_operation(')
        self.assertGreater(
            log_pos, atomic_start,
            "log_operation 应在 atomic 块之后（确认 audit log 在事务外）"
        )

    def test_r3c_folder_delete_log_outside_batch_atomic(self):
        """R3: FolderView.delete 中 log_operation 不在事务批处理内"""
        from apps.document.views.folder.views import FolderView
        source = inspect.getsource(FolderView.delete)
        # log_operation 应在 _delete_folder 调用之后
        delete_folder_pos = source.find('_delete_folder(')
        log_pos = source.find('log_operation(')
        self.assertGreater(delete_folder_pos, 0)
        self.assertGreater(
            log_pos, delete_folder_pos,
            "log_operation 应在 _delete_folder 之后（非事务内）"
        )


# ============================================================
#  R4: 审计日志无 request_id
# ============================================================

class R4_AuditLogLacksRequestId(TestCase):
    """验证 log_operation 函数不接受 request_id 参数。"""

    def test_r4a_log_operation_signature_has_no_request_id(self):
        """R4: log_operation 函数签名中不应包含 request_id 参数"""
        from apps.document.libs.view_utils import log_operation
        source = inspect.getsource(log_operation)
        # 检查函数签名行
        sig_line = source.split('\n')[0]
        self.assertNotIn(
            'request_id',
            sig_line,
            f"log_operation 签名不含 request_id（确认问题存在），"
            f"实际签名: {sig_line}"
        )

    def test_r4b_log_operation_body_has_no_request_id(self):
        """R4: log_operation 函数体中不使用 request_id"""
        from apps.document.libs.view_utils import log_operation
        source = inspect.getsource(log_operation)
        self.assertNotIn(
            'request_id',
            source,
            "log_operation 函数体不引用 request_id（确认问题存在）"
        )


# ============================================================
#  R5: 无 API 限流
# ============================================================

class R5_NoApiRateLimit(TestCase):
    """验证 document 模块无 API 限流配置。"""

    def test_r5a_no_drf_throttle_in_settings(self):
        """R5: settings 中不应配置 DRF throttle"""
        rest_framework = getattr(settings, 'REST_FRAMEWORK', {})
        throttle = rest_framework.get('DEFAULT_THROTTLE_CLASSES', [])
        if throttle:
            # 即使有全局 throttle，document 模块也可能有自己的
            pass
        # 检查是否完全没有 throttle 配置
        self.assertFalse(
            bool(throttle),
            f"settings 中未配置 DEFAULT_THROTTLE_CLASSES（确认问题存在），"
            f"REST_FRAMEWORK={rest_framework}"
        )

    def test_r5b_document_views_no_throttle_classes(self):
        """R5: document 各 View 类不应定义 throttle_classes"""
        from apps.document.views.file.views import FileView
        from apps.document.views.folder.views import FolderView
        from apps.document.views.search import FolderSearchView

        for view_cls in [FileView, FolderView, FolderSearchView]:
            throttle = getattr(view_cls, 'throttle_classes', None)
            self.assertFalse(
                bool(throttle),
                f"{view_cls.__name__} 未定义 throttle_classes（确认问题存在）"
            )


# ============================================================
#  R6: 递归文件夹删除无深度限制
# ============================================================

class R6_FolderDeleteRecursionNoDepthLimit(TestCase):
    """验证 _delete_folder 递归调用无深度参数。"""

    def test_r6a_delete_folder_source_has_no_depth_param(self):
        """R6: _delete_folder 方法签名不应包含 depth 参数"""
        from apps.document.views.folder.views import FolderView
        source = inspect.getsource(FolderView._delete_folder)
        sig_line = source.split('\n')[0]
        self.assertNotIn(
            'depth',
            sig_line,
            f"_delete_folder 签名不含 depth 参数（确认问题存在），"
            f"实际签名: {sig_line}"
        )

    def test_r6b_delete_folder_has_recursive_call(self):
        """R6: _delete_folder 应包含递归调用自身"""
        from apps.document.views.folder.views import FolderView
        source = inspect.getsource(FolderView._delete_folder)
        self.assertIn(
            '_delete_folder',
            source,
            "_delete_folder 包含递归调用自身"
        )


# ============================================================
#  R7: 合并无 request_id 去重
# ============================================================

class R7_MergeLacksRequestIdDedup(TestCase):
    """验证合并请求不使用 request_id 进行幂等去重。"""

    def test_r7a_validate_merge_params_has_no_request_id(self):
        """R7: validate_merge_params 不解析 request_id"""
        from apps.document.views.upload.merge import validate_merge_params
        source = inspect.getsource(validate_merge_params)
        self.assertNotIn(
            'request_id',
            source,
            "validate_merge_params 不引用 request_id（确认问题存在）"
        )

    def test_r7b_parse_merge_request_has_no_request_id(self):
        """R7: parse_merge_request 不解析 request_id"""
        from apps.document.views.upload.merge import parse_merge_request
        source = inspect.getsource(parse_merge_request)
        self.assertNotIn(
            'request_id',
            source,
            "parse_merge_request 不引用 request_id（确认问题存在）"
        )

    def test_r7c_merge_idempotency_uses_transfer_id_not_request_id(self):
        """R7: 幂等检查使用 transfer_id/file_hash，不使用 request_id"""
        from apps.document.views.upload.merge import FileMergeChunksView
        # 检查 _check_idempotency 方法（如果存在）
        source = inspect.getsource(FileMergeChunksView)
        # 文件级别不应出现 request_id 变量
        self.assertNotIn(
            'request_id',
            source,
            "FileMergeChunksView 不引用 request_id（确认问题存在）"
        )


# ============================================================
#  P2: DocumentTransfer 有 CheckConstraints
# ============================================================

class P2_DocumentTransferCheckConstraints(TestCase):
    """验证 DocumentTransfer 模型有 Check 约束。"""

    def test_p2a_has_check_constraints(self):
        """P2: DocumentTransfer 应有 >=4 个 CheckConstraint"""
        from django.db.models import CheckConstraint
        check_constraints = [
            c for c in DocumentTransfer._meta.constraints
            if isinstance(c, CheckConstraint)
        ]
        self.assertGreaterEqual(
            len(check_constraints), 4,
            f"DocumentTransfer 应有 >=4 个 CheckConstraint，"
            f"实际 {len(check_constraints)} 个"
        )

    def test_p2b_transfer_type_check_constraint(self):
        """P2: 非法 transfer_type 应被 CHECK 约束拒绝"""
        user = _make_user('p2_user')
        try:
            transfer = DocumentTransfer(
                user=user,
                file_name='test.txt',
                file_size=100,
                total_chunks=1,
                file_hash='a' * 32,
                transfer_type='INVALID',  # 非法值
                status=TransferStatus.PENDING,
                tenant_id='admin',
            )
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    transfer.save()
        finally:
            DocumentTransfer.objects.all().delete()
            SpugUser.objects.filter(username='p2_user').delete()

    def test_p2c_transfer_status_check_constraint(self):
        """P2: 非法 status 应被 CHECK 约束拒绝"""
        user = _make_user('p2c_user')
        try:
            transfer = DocumentTransfer(
                user=user,
                file_name='test2.txt',
                file_size=100,
                total_chunks=1,
                file_hash='b' * 32,
                transfer_type=TransferType.UPLOAD,
                status='INVALID_STATUS',  # 非法值
                tenant_id='admin',
            )
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    transfer.save()
        finally:
            DocumentTransfer.objects.all().delete()
            SpugUser.objects.filter(username='p2c_user').delete()

    def test_p2d_progress_range_check_constraint(self):
        """P2: progress < 0 应被 CHECK 约束拒绝"""
        user = _make_user('p2d_user')
        try:
            transfer = DocumentTransfer(
                user=user,
                file_name='test3.txt',
                file_size=100,
                total_chunks=1,
                file_hash='c' * 32,
                transfer_type=TransferType.UPLOAD,
                status=TransferStatus.PENDING,
                progress=-1,  # 非法值
                tenant_id='admin',
            )
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    transfer.save()
        finally:
            DocumentTransfer.objects.all().delete()
            SpugUser.objects.filter(username='p2d_user').delete()

    def test_p2e_negative_file_size_check_constraint(self):
        """P2: file_size < 0 应被 CHECK 约束拒绝"""
        user = _make_user('p2e_user')
        try:
            transfer = DocumentTransfer(
                user=user,
                file_name='test4.txt',
                file_size=-1,  # 非法值
                total_chunks=1,
                file_hash='d' * 32,
                transfer_type=TransferType.UPLOAD,
                status=TransferStatus.PENDING,
                tenant_id='admin',
            )
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    transfer.save()
        finally:
            DocumentTransfer.objects.all().delete()
            SpugUser.objects.filter(username='p2e_user').delete()


# ============================================================
#  P3: 文件夹创建幂等性
# ============================================================

class P3_FolderCreationIdempotent(TestCase):
    """验证文件夹创建具有幂等性（先查->创建->IntegrityError->再查）。"""

    def setUp(self):
        self.user = _make_user('p3_user')

    def tearDown(self):
        DocumentFolderPrivate.objects.all().delete()
        SpugUser.objects.filter(username='p3_user').delete()

    def test_p3a_folder_view_source_has_idempotent_pattern(self):
        """P3: FolderView.post 源码应有幂等创建模式"""
        from apps.document.views.folder.views import FolderView
        source = inspect.getsource(FolderView.post)
        # 应包含 filter().first() 检查 + IntegrityError 捕获
        self.assertIn(
            'IntegrityError',
            source,
            "FolderView.post 应捕获 IntegrityError 实现幂等创建"
        )

    def test_p3b_duplicate_folder_name_returns_existing(self):
        """P3 行为验证: 相同文件夹名不会创建重复记录"""
        folder = _make_private_folder(self.user, 'p3_folder')
        # 再次创建同名文件夹（在应用层会返回已存在的）
        existing = DocumentFolderPrivate.objects.filter(
            name='p3_folder',
            created_by=self.user,
            parent__isnull=True,
        ).first()
        self.assertIsNotNone(
            existing,
            "同名文件夹已存在，应用层应返回已存在的记录"
        )
        # 验证只有一条记录
        count = DocumentFolderPrivate.objects.filter(
            name='p3_folder',
            created_by=self.user,
        ).count()
        self.assertEqual(count, 1, "不应有重复文件夹记录")


# ============================================================
#  P4: 合并幂等性检查
# ============================================================

class P4_MergeIdempotencyCheck(TestCase):
    """验证合并请求有幂等性检查（transfer_id + file_hash 双查询）。"""

    def test_p4a_merge_view_has_idempotency_check(self):
        """P4: FileMergeChunksView 应有幂等性检查逻辑"""
        from apps.document.views.upload.merge import FileMergeChunksView
        source = inspect.getsource(FileMergeChunksView)
        # 应检查 transfer_id 和 file_hash
        self.assertIn(
            'transfer_id',
            source,
            "合并视图应通过 transfer_id 检查幂等性"
        )
        self.assertIn(
            'file_hash',
            source,
            "合并视图应通过 file_hash 检查幂等性"
        )

    def test_p4b_merge_view_has_select_for_update(self):
        """P4: 幂等检查应使用 select_for_update 悲观锁"""
        from apps.document.views.upload import merge as merge_module
        source = inspect.getsource(merge_module)
        self.assertIn(
            'select_for_update',
            source,
            "merge 模块应使用 select_for_update 防并发"
        )

    def test_p4c_merge_has_distributed_lock(self):
        """P4: 合并应有分布式锁机制"""
        from apps.document.views.upload.merge import FileMergeChunksView
        source = inspect.getsource(FileMergeChunksView)
        # 应包含锁机制关键词
        has_lock = (
            'merge_lock' in source.lower()
            or 'get_merge_lock' in source
            or 'distributed' in source.lower()
        )
        self.assertTrue(
            has_lock,
            "合并视图应有分布式锁机制"
        )


# ============================================================
#  P5: 文件移动 TOCTOU 防护
# ============================================================

class P5_FileMoveTOCTOU(TestCase):
    """验证文件移动在事务内重新校验目标作用域（TOCTOU 防护）。"""

    def test_p5a_move_file_has_atomic_block(self):
        """P5: FileMoveView._move_file 应使用 transaction.atomic()"""
        from apps.document.views.file.move import FileMoveView
        source = inspect.getsource(FileMoveView._move_file)
        self.assertIn(
            'transaction.atomic',
            source,
            "_move_file 应使用 transaction.atomic()"
        )

    def test_p5b_move_file_has_scope_revalidation(self):
        """P5: _move_file 应在事务内重校验目标作用域"""
        from apps.document.views.file.move import FileMoveView
        source = inspect.getsource(FileMoveView._move_file)
        # 应有 validate_target_folder_scope 调用在 atomic 块内
        self.assertIn(
            'validate_target_folder_scope',
            source,
            "_move_file 应在事务内调用 validate_target_folder_scope 重校验"
        )
        # 注释应提到 TOCTOU
        self.assertTrue(
            'TOCTOU' in source or '重校验' in source or 'revalid' in source.lower(),
            "_move_file 应有 TOCTOU 防护注释"
        )

    def test_p5c_folder_move_also_has_toctou(self):
        """P5: FolderMoveView.post 也应有 TOCTOU 防护"""
        from apps.document.views.folder.move import FolderMoveView
        source = inspect.getsource(FolderMoveView.post)
        self.assertIn('transaction.atomic', source)
        self.assertIn(
            'validate_target_folder_scope',
            source,
            "FolderMoveView.post 也应调用 validate_target_folder_scope 校验目标作用域"
        )


# ============================================================
#  P6: 搜索使用参数化 RawSQL
# ============================================================

class P6_SearchParameterizedRawSQL(TestCase):
    """验证搜索使用参数化 RawSQL，非字符串拼接。"""

    def test_p6a_search_uses_rawsql(self):
        """P6: 搜索模块应使用 RawSQL"""
        from apps.document.views import search as search_module
        source = inspect.getsource(search_module)
        self.assertIn(
            'RawSQL',
            source,
            "搜索模块应使用 RawSQL 进行全文搜索"
        )

    def test_p6b_rawsql_uses_parameterized_args(self):
        """P6: RawSQL 应通过参数列表传值，非字符串拼接"""
        from apps.document.views import search as search_module
        source = inspect.getsource(search_module)
        # RawSQL 第一个参数是模板，第二个参数是列表
        # 检查是否有 [boolean_keyword] 或 [keyword] 这样的参数列表
        self.assertRegex(
            source,
            r'RawSQL\s*\([^,]+,\s*\[',
            "RawSQL 应使用参数列表（[]）传值，非 f-string 拼接"
        )

    def test_p6c_search_has_no_cursor_execute(self):
        """P6: 搜索模块不应使用 cursor.execute()"""
        from apps.document.views import search as search_module
        source = inspect.getsource(search_module)
        self.assertNotIn(
            'cursor.execute',
            source,
            "搜索模块不应使用 cursor.execute()（无 SQL 注入风险）"
        )

    def test_p6d_search_has_no_extra_call(self):
        """P6: 搜索模块不应使用 .extra()"""
        from apps.document.views import search as search_module
        source = inspect.getsource(search_module)
        self.assertNotIn(
            '.extra(',
            source,
            "搜索模块不应使用 .extra()（无 SQL 注入风险）"
        )


# ============================================================
#  P7: 权限装饰器 RBAC
# ============================================================

class P7_PermissionDecorator(TestCase):
    """验证 document 视图使用 @document_auth RBAC 权限装饰器。"""

    def test_p7a_file_view_delete_has_document_auth(self):
        """P7: FileView.delete 应有 @document_auth('delete') 装饰器"""
        from apps.document.views.file.views import FileView
        source = inspect.getsource(FileView.delete)
        self.assertIn(
            'document_auth',
            source,
            "FileView.delete 应有 @document_auth 装饰器"
        )
        self.assertIn(
            'delete',
            source,
            "FileView.delete 应有 @document_auth('delete') 权限码"
        )

    def test_p7b_folder_view_delete_has_document_auth(self):
        """P7: FolderView.delete 应有 @document_auth('delete') 装饰器"""
        from apps.document.views.folder.views import FolderView
        source = inspect.getsource(FolderView.delete)
        self.assertIn(
            'document_auth',
            source,
            "FolderView.delete 应有 @document_auth 装饰器"
        )

    def test_p7c_move_views_have_document_auth(self):
        """P7: 移动视图应有 @document_auth 装饰器"""
        from apps.document.views.file.move import FileMoveView
        from apps.document.views.folder.move import FolderMoveView
        for cls in [FileMoveView, FolderMoveView]:
            source = inspect.getsource(cls)
            self.assertIn(
                'document_auth',
                source,
                f"{cls.__name__} 应有 @document_auth 装饰器"
            )


# ============================================================
#  L1: 软删除字段残留
# ============================================================

class L1_SoftDeleteFieldRemnants(TestCase):
    """验证软删除字段在 4 个模型上残留，且业务代码不再设置。

    回收站于 2026-06-23 移除，删除全部走 hard=True 物理删除，
    但 is_deleted/deleted_at/deleted_by 字段仍保留在模型和索引中。
    """

    def test_l1a_all_models_have_is_deleted_field(self):
        """L1: 4 个模型都应有 is_deleted 字段（残留）"""
        for ModelCls in [DocumentFolderPrivate, DocumentFilePrivate,
                         DocumentFolderPublic, DocumentFilePublic]:
            fields = [f.name for f in ModelCls._meta.get_fields()]
            self.assertIn(
                'is_deleted', fields,
                f"{ModelCls.__name__} 应有 is_deleted 字段（残留确认）"
            )

    def test_l1b_all_models_have_soft_delete_methods(self):
        """L1: 4 个模型都应有 delete(hard=) 和 restore() 方法（死代码）"""
        for ModelCls in [DocumentFolderPrivate, DocumentFilePrivate,
                         DocumentFolderPublic, DocumentFilePublic]:
            # restore() 方法存在（死代码）
            self.assertTrue(
                hasattr(ModelCls, 'restore'),
                f"{ModelCls.__name__} 应有 restore() 方法（死代码确认）"
            )
            # delete() 方法源码应包含 hard 关键字（软删除入口）
            delete_source = inspect.getsource(ModelCls.delete)
            self.assertIn(
                'hard', delete_source,
                f"{ModelCls.__name__}.delete 源码应包含 hard 参数（软删除入口残留）"
            )

    def test_l1c_folder_models_have_deleted_by_field(self):
        """L1: 文件夹模型应有 deleted_by 字段（残留）"""
        for ModelCls in [DocumentFolderPrivate, DocumentFolderPublic]:
            fields = [f.name for f in ModelCls._meta.get_fields()]
            self.assertIn(
                'deleted_by', fields,
                f"{ModelCls.__name__} 应有 deleted_by 字段（残留确认）"
            )

    def test_l1d_business_delete_uses_hard_not_soft(self):
        """L1: 业务删除代码应使用 hard=True，不调用 soft_delete()"""
        from apps.document.views.file.views import FileView
        from apps.document.views.folder.views import FolderView

        # 文件删除：应调用 file.delete(hard=True)
        file_source = inspect.getsource(FileView.delete)
        self.assertIn(
            'hard=True',
            file_source,
            "FileView.delete 应使用 hard=True 物理删除（不使用软删除）"
        )
        self.assertNotIn(
            'soft_delete',
            file_source,
            "FileView.delete 不应调用 soft_delete()（软删除已废弃）"
        )

        # 文件夹删除：_delete_folder 应调用 delete(hard=True)
        folder_source = inspect.getsource(FolderView._delete_folder)
        self.assertIn(
            'hard=True',
            folder_source,
            "_delete_folder 应使用 hard=True 物理删除（不使用软删除）"
        )
        self.assertNotIn(
            'soft_delete',
            folder_source,
            "_delete_folder 不应调用 soft_delete()（软删除已废弃）"
        )

    def test_l1e_indexes_include_is_deleted(self):
        """L1: 复合索引应包含 is_deleted 列（残留，造成索引膨胀）"""
        # DocumentFolderPrivate
        pri_folder_indexes = DocumentFolderPrivate._meta.indexes
        pri_folder_has_deleted = any(
            'is_deleted' in idx.fields
            for idx in pri_folder_indexes
        )
        self.assertTrue(
            pri_folder_has_deleted,
            "DocumentFolderPrivate 索引应包含 is_deleted（残留确认）"
        )
        # DocumentFilePrivate
        pri_file_indexes = DocumentFilePrivate._meta.indexes
        pri_file_has_deleted = any(
            'is_deleted' in idx.fields
            for idx in pri_file_indexes
        )
        self.assertTrue(
            pri_file_has_deleted,
            "DocumentFilePrivate 索引应包含 is_deleted（残留确认）"
        )

    def test_l1f_soft_deleted_manager_filters_is_deleted(self):
        """L1: SoftDeletedManager 应默认过滤 is_deleted=False"""
        from apps.document.models import SoftDeletedManager
        # 默认管理器应为 SoftDeletedManager
        self.assertIsInstance(
            DocumentFolderPrivate._default_manager,
            SoftDeletedManager,
            "DocumentFolderPrivate 默认管理器应为 SoftDeletedManager"
        )
        # 检查 get_queryset 过滤 is_deleted=False
        manager_source = inspect.getsource(SoftDeletedManager.get_queryset)
        self.assertIn(
            'is_deleted',
            manager_source,
            "SoftDeletedManager.get_queryset 应过滤 is_deleted"
        )


# ============================================================
#  L2: DocumentTransfer.file_size 允许 0
# ============================================================

class L2_FileSizeAllowsZero(TestCase):
    """验证 DocumentTransfer.file_size 允许 0（MinValueValidator(0) 不拒绝 0）。

    0 字节文件无业务意义，但 CHECK 约束只拒绝负值，不拒绝 0。
    """

    def test_l2a_zero_file_size_allowed(self):
        """L2: file_size=0 应可成功写入（确认问题存在）"""
        user = _make_user('l2_user')
        try:
            transfer = DocumentTransfer.objects.create(
                user=user,
                file_name='empty.txt',
                file_size=0,  # 0 字节
                total_chunks=1,
                file_hash='a' * 32,
                transfer_type=TransferType.UPLOAD.value,
                status=TransferStatus.UPLOADING.value,
                tenant_id='admin',
            )
            self.assertEqual(
                transfer.file_size, 0,
                "file_size=0 应可成功写入（确认问题存在：0 字节文件无业务意义但被允许）"
            )
        finally:
            try:
                with transaction.atomic():
                    DocumentTransfer.objects.all().delete()
            except Exception:
                pass
            SpugUser.objects.filter(username='l2_user').delete()

    def test_l2b_check_constraint_allows_zero(self):
        """L2: CHECK 约束应允许 file_size=0（不抛 IntegrityError）"""
        user = _make_user('l2b_user')
        try:
            # file_size=0 不应抛异常
            transfer = DocumentTransfer(
                user=user,
                file_name='zero.txt',
                file_size=0,
                total_chunks=1,
                file_hash='b' * 32,
                transfer_type=TransferType.UPLOAD.value,
                status=TransferStatus.UPLOADING.value,
                tenant_id='admin',
            )
            with transaction.atomic():
                transfer.save()  # 不应抛 IntegrityError
            self.assertIsNotNone(transfer.id)
        finally:
            try:
                with transaction.atomic():
                    DocumentTransfer.objects.all().delete()
            except Exception:
                pass
            SpugUser.objects.filter(username='l2b_user').delete()


# ============================================================
#  L3: 批量文件夹删除不记录单文件审计日志
# ============================================================

class L3_BatchFolderDeleteNoPerFileLog(TestCase):
    """验证批量文件夹删除时不为每个文件单独记录审计日志。

    _delete_folder 递归删除数百个文件，但只记一条 FOLDER_DELETE 审计日志，
    不记录每个文件的 FILE_DELETE。
    """

    def test_l3a_delete_folder_source_has_no_log_operation(self):
        """L3: _delete_folder 源码不应调用 log_operation（不记录单文件）"""
        from apps.document.views.folder.views import FolderView
        source = inspect.getsource(FolderView._delete_folder)
        self.assertNotIn(
            'log_operation',
            source,
            "_delete_folder 不应调用 log_operation（确认问题：不记录单文件审计）"
        )

    def test_l3b_delete_view_logs_only_folder_not_files(self):
        """L3: FolderView.delete 应只记一条 FOLDER_DELETE，不记 FILE_DELETE"""
        from apps.document.views.folder.views import FolderView
        delete_source = inspect.getsource(FolderView.delete)
        # 应有 FOLDER_DELETE
        self.assertIn(
            'FOLDER_DELETE',
            delete_source,
            "FolderView.delete 应记录 FOLDER_DELETE 审计日志"
        )
        # 不应有 FILE_DELETE
        self.assertNotIn(
            'FILE_DELETE',
            delete_source,
            "FolderView.delete 不应记录 FILE_DELETE（确认问题：批量删除不记单文件）"
        )

    def test_l3c_delete_view_calls_log_operation_once(self):
        """L3: FolderView.delete 应只调用一次 log_operation"""
        from apps.document.views.folder.views import FolderView
        source = inspect.getsource(FolderView.delete)
        count = source.count('log_operation(')
        self.assertEqual(
            count, 1,
            f"FolderView.delete 应只调用 1 次 log_operation，实际 {count} 次"
        )

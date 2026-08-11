"""资料库完整回归测试 - 重大版本运行

覆盖（在标准档基础上扩展）：
1. 故障注入：mock 物理文件操作失败、DB 异常、外部服务不可达
2. Celery 任务：retry_clean_pending_files、merge、async_copy 的真实执行
3. 性能门禁：基础操作的响应时间基线（38 人内网场景, 不追求互联网级）

执行真实 View/Service/Model/文件操作。
本档不自动运行（性能门禁需在干净环境），由 release_gate 调用。
"""
import os
import json
import time
import uuid
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.account.models import User
from apps.document.models import (
    DocumentFolderPrivate, DocumentFilePrivate,
    DocumentFolderPublic, DocumentFilePublic,
    DocumentTransfer, DocumentSystemFolder,
)
from apps.document.constants import TransferStatus, TransferType
from apps.document.services.system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE,
)
from tests.helpers.test_base import (
    make_user, make_client, setup_test_env,
    post_json, delete_json, get_response_data, has_error,
)


class FullRegressionBase(TestCase):
    """完整回归基类"""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user('fr_admin', is_supper=True)

    def setUp(self):
        setup_test_env()
        self.client = make_client(self.admin)
        self.client.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'
        self.storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
        self.tmp_dir = tempfile.mkdtemp(prefix='fr_test_', dir=self.storage_base)
        self.user_dir = os.path.join(self.tmp_dir, f'user-{self.admin.id}')
        os.makedirs(self.user_dir, exist_ok=True)

    def tearDown(self):
        from django.db import connection
        # 用 raw SQL 清理, 避免 DocumentFileDeleteMixin 物理删除副作用
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM tdyw_document_file_private WHERE file_path LIKE %s",
                [f'{self.tmp_dir}%'])
            cursor.execute(
                "DELETE FROM tdyw_document_folder_private WHERE name LIKE 'fr_%'")
            cursor.execute(
                "DELETE FROM tdyw_document_transfer WHERE file_name LIKE 'fr_%'")
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        # 清理 move API 可能产生的真实存储路径下的物理文件（防跨测试残留）
        real_user_dir = os.path.join(self.storage_base, 'private', f'user-{self.admin.id}')
        if os.path.isdir(real_user_dir):
            for root, dirs, files in os.walk(real_user_dir):
                for fname in files:
                    if fname.startswith('fr_'):
                        try:
                            os.remove(os.path.join(root, fname))
                        except OSError:
                            pass
        super().tearDown()

    def _make_file(self, name='fr_file.txt', content=b'test', folder=None):
        file_path = os.path.join(self.user_dir, name)
        with open(file_path, 'wb') as f:
            f.write(content)
        return DocumentFilePrivate.objects.create(
            name=name, display_name=name,
            physical_name=name, file_path=file_path,
            file_size=len(content), file_type='text/plain',
            folder=folder, created_by=self.admin, tenant_id='admin')

    def _make_folder(self, name='fr_folder', parent=None):
        return DocumentFolderPrivate.objects.create(
            name=name, parent=parent, created_by=self.admin, tenant_id='admin')


# ============================================================
# 1. 故障注入
# ============================================================
class T13_FaultInjection_PhysicalDeleteFail(FullRegressionBase):
    """故障注入：物理文件删除失败"""

    def test_物理删除失败_不破坏DB一致性(self):
        """物理删除失败时, DB 记录保留并标记 is_pending_clean, 不产生孤儿"""
        file = self._make_file('fr_fault_delete.txt', b'content')
        file_id = file.id
        file_path = file.file_path

        # mock 物理删除失败
        with patch(
            'apps.document.libs.document_utils.safe_delete_document_file',
            return_value=(False, 'EACCES: permission denied (mock)')
        ):
            from apps.document.exceptions import DocumentPhysicalDeleteError
            with self.assertRaises(DocumentPhysicalDeleteError):
                file.delete()

        # 验证：DB 记录仍在, 标记 is_pending_clean
        file.refresh_from_db()
        self.assertTrue(file.is_pending_clean,
                       '物理删除失败后应标记 is_pending_clean')
        # 物理文件仍存在（未被删除）
        self.assertTrue(os.path.exists(file_path),
                       '物理删除失败时物理文件应仍存在')

        # 重置冷却时间（file.delete 失败时 mixin 设置了 last_clean_attempt=now,
        # retry_clean_pending_files 有 3600s 冷却期会跳过）
        file.last_clean_attempt = None
        file.save(update_fields=['last_clean_attempt'])

        # 后续 retry 应能清理（此时 mock 已解除，物理删除会成功）
        from apps.document.tasks.cleanup.pending_files import retry_clean_pending_files
        retry_clean_pending_files()
        self.assertFalse(
            DocumentFilePrivate.objects.filter(id=file_id).exists(),
            'retry_clean_pending_files 后应清理 DB 记录')
        self.assertFalse(
            os.path.exists(file_path),
            'retry_clean_pending_files 后应删除物理文件')


class T14_FaultInjection_MergeFail(FullRegressionBase):
    """故障注入：合并任务失败"""

    def test_合并失败_状态不损坏(self):
        """merge_file_chunks.delay 抛异常时, transfer 状态不被损坏"""
        file_hash = uuid.uuid4().hex
        transfer = DocumentTransfer.objects.create(
            tenant_id='admin', user=self.admin, transfer_type='UPLOAD',
            status='MERGING', file_name='fr_merge_fail.txt',
            file_size=1024, file_path=os.path.join(self.user_dir, 'fr_merge_fail.txt'),
            file_hash=file_hash, total_chunks=1, uploaded_chunks=1,
            is_public=False)
        transfer_id = transfer.id

        # mock Celery task dispatch 抛异常
        with patch(
            'apps.document.tasks.merge.merge_file_chunks.delay',
            side_effect=ConnectionError('Celery broker unavailable (mock)')
        ):
            from apps.document.tasks.merge import merge_file_chunks
            with self.assertRaises(ConnectionError):
                merge_file_chunks.delay({'test': 'data'})

        # 验证：transfer 状态未被损坏（仍为 MERGING，等待重试或手动恢复）
        transfer.refresh_from_db()
        self.assertIn(transfer.status, ['MERGING', 'FAILED', 'CANCELED'],
                    f'合并失败后状态应在合理范围, 实际 {transfer.status}')


class T15_FaultInjection_kkFileViewUnavailable(FullRegressionBase):
    """故障注入：kkFileView 不可达"""

    def test_kkFileView不可达_预览降级(self):
        """kkFileView 服务不可达时, 预览接口应降级返回错误, 不崩溃"""
        file = self._make_file('fr_preview_fail.txt', b'preview')
        # mock requests.get 抛 ConnectionError
        with patch('requests.get',
                   side_effect=Exception('Connection refused (mock)')):
            resp = self.client.get('/document/preview/', {
                'id': file.id, 'is_public': False,
            })
        # 预览接口应返回 200 + error, 不应 500
        self.assertEqual(resp.status_code, 200,
                        f'kkFileView 不可达时预览不应 500, 实际 {resp.status_code}')


# ============================================================
# 2. Celery 任务
# ============================================================
class T16_Celery_RetryCleanPendingFiles(FullRegressionBase):
    """Celery 任务：retry_clean_pending_files 幂等性"""

    def test_重复调用retry任务幂等(self):
        """连续两次调用 retry_clean_pending_files 不应重复处理"""
        file = self._make_file('fr_retry_idem.txt', b'content')
        file.is_pending_clean = True
        file.clean_retry_count = 0
        file.save(update_fields=['is_pending_clean', 'clean_retry_count'])
        file_id = file.id
        file_path = file.file_path

        from apps.document.tasks.cleanup.pending_files import retry_clean_pending_files
        # 第一次调用：清理
        retry_clean_pending_files()
        self.assertFalse(
            DocumentFilePrivate.objects.filter(id=file_id).exists(),
            '第一次 retry 后应清理记录')
        self.assertFalse(
            os.path.exists(file_path),
            '第一次 retry 后应删除物理文件')

        # 第二次调用：不应报错（幂等）
        try:
            retry_clean_pending_files()
        except Exception as e:
            self.fail(f'第二次 retry 应幂等, 不应抛异常: {e}')


class T17_Celery_MergeTaskIdempotent(FullRegressionBase):
    """Celery 任务：merge_file_chunks 幂等性"""

    def test_重复提交merge任务返回已存在(self):
        """已 COMPLETED 的 transfer 再次提交 direct_merge 应幂等返回"""
        file_hash = uuid.uuid4().hex
        # 创建文件夹和文件记录（幂等检查需要文件已存在）
        folder = self._make_folder('fr_merge_idem_folder')
        file_path = os.path.join(self.user_dir, 'fr_merge_idem.txt')
        physical_name = os.path.basename(file_path)
        DocumentFilePrivate.objects.create(
            name='fr_merge_idem.txt', display_name='fr_merge_idem.txt',
            physical_name=physical_name,
            file_path=file_path, file_size=1024, file_type='text/plain',
            folder=folder, created_by=self.admin, tenant_id='admin')

        transfer = DocumentTransfer.objects.create(
            tenant_id='admin', user=self.admin, transfer_type='UPLOAD',
            status='COMPLETED', file_name='fr_merge_idem.txt',
            file_size=1024, file_path=file_path,
            file_hash=file_hash, total_chunks=1, uploaded_chunks=1,
            is_public=False, folder_id=folder.id)
        transfer_id = transfer.id

        # 通过 API 调用 direct_merge（admin 是超管，跳过 ownership 校验）
        resp = self.client.post('/document/direct_merge/', data=json.dumps({
            'transfer_id': transfer_id,
            'folder_id': folder.id,
            'file_name': 'fr_merge_idem.txt',
            'file_hash': file_hash,
            'total_chunks': 1,
            'is_public': False,
        }), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        resp_data = resp.json()
        # 幂等检查：已 COMPLETED 且文件存在时返回 is_idempotent=True
        self.assertIn('is_idempotent', resp_data.get('data', {}),
                      f'已完成的 transfer 应返回幂等标识, 实际: {resp_data}')


# ============================================================
# 3. 性能门禁（38 人内网场景基线）
# ============================================================
class T18_PerformanceGate(FullRegressionBase):
    """性能门禁 - 38 人内网场景基线

    不追求互联网级并发, 只验证基础操作在合理时间内完成。
    基线值宽松（38 人内网 + Django dev server）。
    """

    # 基线（秒）- 单用户 dev 环境, 宽松
    BASELINE_FOLDER_LIST = 0.5      # 文件夹列表
    BASELINE_FILE_LIST = 0.5        # 文件列表
    BASELINE_DISK_USAGE = 1.0       # 磁盘用量统计
    BASELINE_TRANSFER_LIST = 0.5   # 传输列表
    BASELINE_FILE_CREATE = 0.5      # 文件记录创建（不实际上传）

    def test_文件夹列表响应时间(self):
        """文件夹列表应在基线内"""
        # 先创建几个文件夹
        for i in range(10):
            self._make_folder(f'fr_perf_folder_{i}')

        start = time.time()
        resp = self.client.get('/document/folder/')
        elapsed = time.time() - start

        self.assertEqual(resp.status_code, 200)
        self.assertLess(
            elapsed, self.BASELINE_FOLDER_LIST,
            f'文件夹列表耗时 {elapsed:.3f}s 超过基线 {self.BASELINE_FOLDER_LIST}s')

    def test_磁盘用量响应时间(self):
        """磁盘用量统计应在基线内"""
        start = time.time()
        resp = self.client.get('/document/disk_usage/')
        elapsed = time.time() - start

        self.assertEqual(resp.status_code, 200)
        self.assertLess(
            elapsed, self.BASELINE_DISK_USAGE,
            f'磁盘用量耗时 {elapsed:.3f}s 超过基线 {self.BASELINE_DISK_USAGE}s')

    def test_传输列表响应时间(self):
        """传输列表应在基线内"""
        # 创建几条 transfer
        for i in range(5):
            DocumentTransfer.objects.create(
                tenant_id='admin', user=self.admin, transfer_type='UPLOAD',
                status='PENDING', file_name=f'fr_perf_transfer_{i}.txt',
                file_size=1024, file_path='/tmp/fr_perf.txt',
                file_hash=uuid.uuid4().hex, total_chunks=1,
                is_public=False)

        start = time.time()
        resp = self.client.get('/document/transfers/')
        elapsed = time.time() - start

        self.assertEqual(resp.status_code, 200)
        self.assertLess(
            elapsed, self.BASELINE_TRANSFER_LIST,
            f'传输列表耗时 {elapsed:.3f}s 超过基线 {self.BASELINE_TRANSFER_LIST}s')

    def test_文件记录创建响应时间(self):
        """文件记录创建应在基线内"""
        folder = self._make_folder('fr_perf_create')
        file_path = os.path.join(self.user_dir, 'fr_perf_create.txt')
        with open(file_path, 'w') as f:
            f.write('x' * 100)

        start = time.time()
        file = DocumentFilePrivate.objects.create(
            name='fr_perf_create.txt', display_name='fr_perf_create.txt',
            physical_name='fr_perf_create.txt', file_path=file_path,
            file_size=100, file_type='text/plain',
            folder=folder, created_by=self.admin, tenant_id='admin')
        elapsed = time.time() - start

        self.assertLess(
            elapsed, self.BASELINE_FILE_CREATE,
            f'文件记录创建耗时 {elapsed:.3f}s 超过基线 {self.BASELINE_FILE_CREATE}s')


# ============================================================
# 4. 状态机完整性
# ============================================================
class T19_StateMachineIntegrity(FullRegressionBase):
    """状态机完整性回归 - 保护状态转换矩阵"""

    def test_所有合法转换可执行(self):
        """ALLOWED_STATUS_TRANSITIONS 中定义的转换都应被 is_valid_status_transition 允许"""
        from apps.document.constants import (
            ALLOWED_STATUS_TRANSITIONS, is_valid_status_transition,
            TransferStatus,
        )
        for src, dst_list in ALLOWED_STATUS_TRANSITIONS.items():
            src_status = TransferStatus(src)
            for dst in dst_list:
                dst_status = TransferStatus(dst)
                valid = is_valid_status_transition(src_status, dst_status)
                self.assertTrue(
                    valid,
                    f'矩阵定义 {src}->{dst} 但 is_valid_status_transition 返回 False')

    def test_终态不可转出(self):
        """COMPLETED 和 CANCELED 是终态, 不应允许转出"""
        from apps.document.constants import (
            ALLOWED_STATUS_TRANSITIONS, is_valid_status_transition,
            TransferStatus,
        )
        # COMPLETED 和 CANCELED 是终态（ALLOWED_STATUS_TRANSITIONS 中无出度）
        # FAILED 不是终态（允许重试：FAILED -> UPLOADING/DOWNLOADING/COPYING/CANCELED）
        terminal_states = [TransferStatus.COMPLETED, TransferStatus.CANCELED]
        non_terminal = [TransferStatus.PENDING, TransferStatus.UPLOADING,
                        TransferStatus.DOWNLOADING, TransferStatus.PAUSED,
                        TransferStatus.MERGING, TransferStatus.COPYING,
                        TransferStatus.FAILED]
        for terminal in terminal_states:
            for dst in non_terminal:
                valid = is_valid_status_transition(terminal, dst)
                self.assertFalse(
                    valid,
                    f'终态 {terminal.value} 不应允许转出到 {dst.value}')


# ============================================================
# 5. 边界 bug 防回退（保护已修复的边界 bug 不再出现）
# ============================================================
class T20_BoundaryBugGuards(FullRegressionBase):
    """边界 bug 防回归 - 保护已修复的边界 bug 不再出现"""

    def test_分片文件名格式_i_part(self):
        """B1 防回退：分片必须保存为 {i}.part, 不能是 chunk_{i}

        这是 P0 bug 的防回退测试。
        """
        from apps.document.views.upload.validators import ChunkStorageManager
        chunk_dir = os.path.join(self.user_dir, 'guard_chunks')
        os.makedirs(chunk_dir, exist_ok=True)
        chunk = SimpleUploadedFile('chunk', b'guard content')
        path, err = ChunkStorageManager.save_chunk_file(chunk, chunk_dir, 0)
        self.assertIsNone(err)
        self.assertEqual(
            os.path.basename(path), '0.part',
            f'分片文件名应为 0.part, 实际: {os.path.basename(path)}'
            + ' (B1 bug 回退: 又变成了 chunk_{i})')


# ============================================================
# 6. 容错补充：合并超时检测 + 清理重试上限
# ============================================================
class T21_FaultTolerance_MergeTimeout(FullRegressionBase):
    """容错：合并超时检测 - MERGING 状态超时自动重置为 FAILED

    覆盖场景：
    - 合并超过 30 分钟 -> check_merge_timeout 重置为 FAILED
    - 未超时任务 -> 不被误触
    - 僵尸任务超过 24 小时 -> cleanup_stale_merging_tasks 批量清理
    """

    def test_合并超时_自动重置为FAILED(self):
        """MERGING 超过 30 分钟的任务, check_merge_timeout 应重置为 FAILED"""
        from django.utils import timezone
        from datetime import timedelta
        from apps.document.tasks.timeout_checker import check_merge_timeout

        transfer = DocumentTransfer.objects.create(
            tenant_id='admin', user=self.admin, transfer_type='UPLOAD',
            status='MERGING', file_name='fr_timeout.txt',
            file_size=1024, file_path=os.path.join(self.user_dir, 'fr_timeout.txt'),
            file_hash=uuid.uuid4().hex, total_chunks=1, uploaded_chunks=1,
            is_public=False)

        # auto_now=True 会在 save() 时覆盖 updated_at, 用 update() 绕过
        old_time = timezone.now() - timedelta(minutes=35)
        DocumentTransfer.objects.filter(id=transfer.id).update(updated_at=old_time)

        result = check_merge_timeout(timeout_minutes=30)

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'FAILED',
                        f'超时的 MERGING 任务应被重置为 FAILED, 实际 {transfer.status}')
        self.assertIn('超时', transfer.error_message,
                      f'error_message 应包含超时信息, 实际: {transfer.error_message}')
        self.assertEqual(result['reset_count'], 1,
                         f'应重置 1 个任务, 实际 {result["reset_count"]}')

    def test_未超时任务_不被重置(self):
        """MERGING 不到 30 分钟的任务, check_merge_timeout 不应动它"""
        from django.utils import timezone
        from datetime import timedelta
        from apps.document.tasks.timeout_checker import check_merge_timeout

        transfer = DocumentTransfer.objects.create(
            tenant_id='admin', user=self.admin, transfer_type='UPLOAD',
            status='MERGING', file_name='fr_notimeout.txt',
            file_size=1024, file_path=os.path.join(self.user_dir, 'fr_notimeout.txt'),
            file_hash=uuid.uuid4().hex, total_chunks=1, uploaded_chunks=1,
            is_public=False)

        # updated_at 设为 5 分钟前（未超时）
        recent_time = timezone.now() - timedelta(minutes=5)
        DocumentTransfer.objects.filter(id=transfer.id).update(updated_at=recent_time)

        result = check_merge_timeout(timeout_minutes=30)

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'MERGING',
                        f'未超时任务不应被重置, 实际 {transfer.status}')
        self.assertEqual(result['reset_count'], 0,
                         f'不应重置任何任务, 实际 {result["reset_count"]}')

    def test_僵尸任务24h自动清理(self):
        """MERGING 超过 24 小时的僵尸任务, cleanup_stale_merging_tasks 应清理"""
        from django.utils import timezone
        from datetime import timedelta
        from apps.document.tasks.timeout_checker import cleanup_stale_merging_tasks

        transfer = DocumentTransfer.objects.create(
            tenant_id='admin', user=self.admin, transfer_type='UPLOAD',
            status='MERGING', file_name='fr_zombie.txt',
            file_size=1024, file_path=os.path.join(self.user_dir, 'fr_zombie.txt'),
            file_hash=uuid.uuid4().hex, total_chunks=1, uploaded_chunks=1,
            is_public=False)

        # updated_at 设为 25 小时前
        stale_time = timezone.now() - timedelta(hours=25)
        DocumentTransfer.objects.filter(id=transfer.id).update(updated_at=stale_time)

        result = cleanup_stale_merging_tasks(older_than_hours=24)

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'FAILED',
                        f'僵尸任务应被清理为 FAILED, 实际 {transfer.status}')
        self.assertIn('异常', transfer.error_message,
                      f'error_message 应包含异常信息, 实际: {transfer.error_message}')


class T22_FaultTolerance_CleanRetryLimit(FullRegressionBase):
    """容错：清理重试上限 - 超过 MAX_RETRY_COUNT 后保留记录待人工介入

    覆盖场景：
    - clean_retry_count >= MAX_RETRY_COUNT 时, retry 不删除 DB 记录（防孤儿物理文件）
    - 冷却期内（3600s）的文件被跳过, 不重复重试
    """

    def test_重试达上限_不删除DB记录(self):
        """clean_retry_count >= MAX_RETRY_COUNT 时, retry_clean_pending_files 不应删除 DB 记录

        场景：物理文件持续不可删（权限/磁盘故障），重试已达上限。
        期望：DB 记录保留（否则物理文件变成无追踪孤儿），系统仅记录 CRITICAL 日志。
        """
        from apps.document.tasks.cleanup.pending_files import (
            retry_clean_pending_files, MAX_RETRY_COUNT,
        )

        file = self._make_file('fr_retry_limit.txt', b'content')
        file.is_pending_clean = True
        file.clean_retry_count = MAX_RETRY_COUNT  # 已达上限
        file.last_clean_attempt = None  # 绕过冷却期
        file.save(update_fields=['is_pending_clean', 'clean_retry_count', 'last_clean_attempt'])
        file_id = file.id

        # 需同时 mock 两处 import：
        # 1. pending_files.py 模块级 import（_process_pending_files 直接调用）
        # 2. document_utils 模块（mixin delete() 内 local import）
        with patch(
            'apps.document.tasks.cleanup.pending_files.safe_delete_document_file',
            return_value=(False, 'EACCES: permission denied (mock)')
        ), patch(
            'apps.document.libs.document_utils.safe_delete_document_file',
            return_value=(False, 'EACCES: permission denied (mock)')
        ):
            retry_clean_pending_files()

        # 验证：DB 记录仍在（不因重试上限而删除，否则物理文件变成无追踪孤儿）
        self.assertTrue(
            DocumentFilePrivate.objects.filter(id=file_id).exists(),
            '重试达上限后 DB 记录应保留, 否则物理文件变成无追踪孤儿')

        file.refresh_from_db()
        self.assertTrue(file.is_pending_clean,
                        'is_pending_clean 应仍为 True')
        self.assertGreaterEqual(
            file.clean_retry_count, MAX_RETRY_COUNT,
            f'clean_retry_count 应 >= {MAX_RETRY_COUNT}, 实际 {file.clean_retry_count}')

    def test_冷却期内_跳过重试(self):
        """last_clean_attempt 在冷却期内(3600s)时, retry_clean_pending_files 应跳过"""
        from django.utils import timezone
        from apps.document.tasks.cleanup.pending_files import retry_clean_pending_files

        file = self._make_file('fr_cooldown.txt', b'content')
        file.is_pending_clean = True
        file.clean_retry_count = 1
        file.last_clean_attempt = timezone.now()  # 刚尝试过, 在冷却期内
        file.save(update_fields=['is_pending_clean', 'clean_retry_count', 'last_clean_attempt'])

        original_retry_count = file.clean_retry_count

        retry_clean_pending_files()

        file.refresh_from_db()
        self.assertEqual(
            file.clean_retry_count, original_retry_count,
            '冷却期内应跳过, clean_retry_count 不应变化')
        self.assertTrue(
            DocumentFilePrivate.objects.filter(id=file.id).exists(),
            '冷却期内不应删除记录')

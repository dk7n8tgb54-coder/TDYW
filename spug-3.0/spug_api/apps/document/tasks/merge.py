# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
文件合并 Celery 任务（生产级改进版）
- 添加Redis分布式锁（多Worker安全）
- 区分可重试/不可重试异常
- 完善的进度追踪和状态管理
"""
import logging
import os
import hashlib
import shutil
import traceback
import time
import json
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded, Retry
from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# 导入分布式锁
from apps.document.libs.celery_lock import RedisLock

# ============================================================================
# 常量定义（修复P2-1魔法数字）
# ============================================================================

# 进度更新间隔（每N个分片更新一次进度）
PROGRESS_UPDATE_INTERVAL = 10

# 文件复制缓冲区大小（8MB）
# 1MB 缓冲对大文件合并偏小，会增加 Python 层循环次数和系统调用压力；
# 调整为 8MB 可显著降低合并阶段 CPU 与系统调用开销。
# 如服务器内存稳定且压测收益明显，可进一步调整至 16MB。
# 注意：多个 merge worker 同时合并时会按倍数放大内存占用。
FILE_COPY_BUFFER_SIZE = 8 * 1024 * 1024

# Celery任务配置
CELERY_MAX_RETRIES = 3
CELERY_RETRY_DELAY_SECONDS = 60
CELERY_SOFT_TIME_LIMIT_SECONDS = 600  # 10分钟
CELERY_HARD_TIME_LIMIT_SECONDS = 900  # 15分钟

# 分布式锁超时时间（秒）
REDIS_LOCK_TIMEOUT_SECONDS = 900

# 锁获取失败后的重试等待时间（秒）
LOCK_RETRY_COUNTDOWN_SECONDS = 30

# 进度百分比范围
PROGRESS_MERGE_MIN = 30
PROGRESS_MERGE_MAX = 60
PROGRESS_VERIFY_SIZE = 65
PROGRESS_VERIFY_MD5 = 75
PROGRESS_CREATE_RECORD = 85
PROGRESS_CLEANUP = 95


class MergeTaskManager:
    """合并任务管理器 - 封装任务状态和文件操作"""

    def __init__(self, task_id, job_data, celery_task):
        self.task_id = task_id
        self.job_data = job_data
        self.celery_task = celery_task
        self.start_time = int(time.time())
        self.merge_task_id = f"{job_data['file_hash']}_{self.start_time}"
        self.merge_task_file = self._get_task_file_path()

        # 解包任务数据
        self.file_name = job_data['file_name']
        self.file_hash = job_data['file_hash']
        self.file_path = job_data['file_path']
        self.chunk_dir = job_data['chunk_dir']
        self.file_size = job_data['file_size']
        self.total_chunks = job_data['total_chunks']
        self.folder_id = job_data.get('folder_id')
        self.is_public = job_data.get('is_public', False)
        self.user_id = job_data['user_id']
        self.username = job_data.get('username', 'unknown')
        self.tenant_id = job_data.get('tenant_id', '')
        self.transfer_id = job_data.get('transfer_id')
        self.physical_name = job_data.get('physical_name', os.path.basename(self.file_path))
        self.logical_name = job_data.get('logical_name', self.physical_name)
        self.display_name = job_data.get('display_name', self.file_name)

    def _get_task_file_path(self):
        """获取任务文件路径"""
        return os.path.join(
            settings.BASE_DIR, 'storage', 'document_merge_tasks',
            f"{self.merge_task_id}.task"
        )

    def update_task_file(self, status, progress=0, message='', result=None):
        """更新任务文件状态"""
        try:
            task_data = {
                'status': status.lower(),
                'file_name': self.file_name,
                'file_hash': self.file_hash,
                'user': self.username,
                'is_public': self.is_public,
                'start_time': self.start_time,
                'task_id': self.task_id,
                'progress': progress,
                'message': message,
                'updated_at': time.time()
            }
            if result:
                task_data['result'] = result
            os.makedirs(os.path.dirname(self.merge_task_file), exist_ok=True)
            with open(self.merge_task_file, 'w') as f:
                f.write(json.dumps(task_data))
        except Exception as e:
            logger.warning(f'[Celery] Failed to update task file: {e}')

    def update_celery_state(self, state, progress, message):
        """更新Celery任务状态"""
        self.celery_task.update_state(state=state, meta={'progress': progress, 'message': message})

    def log_task_start(self):
        """记录任务开始日志"""
        logger.info(f'[Celery] ====== Starting merge task: job_id={self.task_id} ======')
        logger.info(f'[Celery] File: {self.file_name}, hash: {self.file_hash}')
        logger.info(f'[Celery] Total chunks: {self.total_chunks}, size: {self.file_size}')
        logger.info(f'[Celery] Chunk dir: {self.chunk_dir}')
        logger.info(f'[Celery] Target path: {self.file_path}')
        logger.info(f'[Celery] Merge task ID: {self.merge_task_id}')


class ChunkValidator:
    """分片验证器"""

    def __init__(self, task_manager):
        self.task_manager = task_manager

    def validate_environment(self):
        """验证环境（分片目录、目标目录可写性、路径安全校验）"""
        self.task_manager.update_celery_state('PROGRESS', 10, '验证环境')

        # 【优化8】路径安全校验：确保文件路径和分片目录在安全区域内
        document_storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
        chunk_base_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_chunks')
        
        from apps.document.libs.document_utils import is_safe_path
        
        if not is_safe_path(document_storage_base, self.task_manager.file_path):
            return False, f'非法目标文件路径: {self.task_manager.file_path}'

        if not is_safe_path(chunk_base_dir, self.task_manager.chunk_dir):
            return False, f'非法分片目录路径: {self.task_manager.chunk_dir}'

        # 检查分片目录是否存在
        if not os.path.exists(self.task_manager.chunk_dir):
            return False, f'分片目录不存在: {self.task_manager.chunk_dir}'

        # 检查目标目录是否可写
        target_dir = os.path.dirname(self.task_manager.file_path)
        if not os.access(target_dir, os.W_OK):
            return False, f'目标目录不可写: {target_dir}'

        return True, None

    def validate_chunk_integrity(self):
        """验证分片完整性"""
        self.task_manager.update_celery_state('PROGRESS', 20, '验证分片完整性')
        logger.info(f'[Celery] Checking chunk integrity: total_chunks={self.task_manager.total_chunks}')

        missing_chunks = []
        for i in range(self.task_manager.total_chunks):
            chunk_path = os.path.join(self.task_manager.chunk_dir, f"{i}.part")
            if not os.path.exists(chunk_path):
                missing_chunks.append(i)
                logger.warning(f'[Celery] Missing chunk: {i}')

        if missing_chunks:
            return False, f'缺少分片: {missing_chunks}'

        logger.info(f'[Celery] All chunks verified: {self.task_manager.total_chunks} chunks found')
        return True, None


class ChunkMerger:
    """分片合并器"""

    def __init__(self, task_manager):
        self.task_manager = task_manager
        # 合并期顺带计算的 MD5（仅全量 MD5 文件有值，供 verify_file_md5 直接比对）
        self.merged_md5 = None

    def merge_chunks(self):
        """合并分片文件

        优化（方案5.2）：对全量 MD5 文件，合并写入时同步 md5.update(data)，
        合并完成后直接得到 merged_md5，避免 verify 阶段二次全量读盘。
        对 sv1_ 抽样 MD5 文件，无法通过全量比对校验，跳过计算以节省 CPU。
        """
        self.task_manager.update_celery_state('PROGRESS', 30, '合并分片中')
        logger.info(f'[Celery] Starting chunk merge: target={self.task_manager.file_path}')

        # 仅全量 MD5 文件在合并期顺带计算 MD5
        compute_md5 = not self.task_manager.file_hash.startswith('sv1_')
        md5_hash = hashlib.md5() if compute_md5 else None

        try:
            with open(self.task_manager.file_path, 'wb+') as merged_file:
                logger.info(f'[Celery] Created target file: {self.task_manager.file_path}')
                for i in range(self.task_manager.total_chunks):
                    self._copy_chunk(merged_file, i, md5_hash)
                    self._update_merge_progress(i)

            # 合并完成后得到 merged_md5（仅全量 MD5 文件）
            if md5_hash is not None:
                self.merged_md5 = md5_hash.hexdigest()
                logger.info(f'[Celery] Merged MD5 computed during merge: {self.merged_md5}')

            logger.info(f'[Celery] Chunks merged successfully: {self.task_manager.file_path}')
            return True, None

        except (IOError, OSError) as e:
            error_msg = f'文件合并IO错误: {str(e)}'
            logger.error(f'[Celery] {error_msg}')
            return False, error_msg

    def _copy_chunk(self, merged_file, chunk_index, md5_hash=None):
        """复制单个分片到合并文件，顺带更新 MD5（若提供）

        用等价于 shutil.copyfileobj 的手动 read/write 循环替换原实现，
        以便在 write 后立即 md5.update(data)，无需二次读取。
        """
        chunk_path = os.path.join(self.task_manager.chunk_dir, f"{chunk_index}.part")
        try:
            with open(chunk_path, 'rb') as chunk_file:
                while True:
                    data = chunk_file.read(FILE_COPY_BUFFER_SIZE)
                    if not data:
                        break
                    merged_file.write(data)
                    if md5_hash is not None:
                        md5_hash.update(data)
        except (IOError, OSError) as e:
            raise RuntimeError(f'读取分片{chunk_index}失败: {str(e)}') from e

    def _update_merge_progress(self, current_index):
        """更新合并进度"""
        total = self.task_manager.total_chunks
        if (current_index + 1) % PROGRESS_UPDATE_INTERVAL == 0 or current_index == total - 1:
            progress = PROGRESS_MERGE_MIN + int((current_index + 1) / total * (PROGRESS_MERGE_MAX - PROGRESS_MERGE_MIN))
            self.task_manager.update_celery_state(
                'PROGRESS', progress, f'已合并 {current_index+1}/{total} 分片'
            )
            self.task_manager.update_task_file(
                'MERGING', progress, f'已合并 {current_index+1}/{total} 分片'
            )


class FileVerifier:
    """文件验证器"""

    def __init__(self, task_manager):
        self.task_manager = task_manager

    def verify_file_size(self):
        """验证文件大小"""
        self.task_manager.update_celery_state('PROGRESS', 65, '验证文件大小')

        actual_size = os.path.getsize(self.task_manager.file_path)
        if actual_size != self.task_manager.file_size:
            error_msg = f'文件大小不匹配: 期望 {self.task_manager.file_size}, 实际 {actual_size}'
            logger.error(f'[Celery] {error_msg}')
            return False, error_msg

        return True, None

    def verify_file_md5(self, merged_md5=None):
        """验证文件MD5

        优化（方案5.2）：优先使用合并期已计算的 merged_md5 直接比对，
        避免二次全量读盘。若 merged_md5 为 None（异常回退），重新读盘计算。
        """
        self.task_manager.update_celery_state('PROGRESS', PROGRESS_VERIFY_MD5, '验证文件MD5')

        file_hash = self.task_manager.file_hash

        # 抽样MD5只用于标识文件，不进行完整性校验
        if file_hash.startswith('sv1_'):
            logger.info(f'[Celery] Using sampling MD5, skipping full MD5 verification: {file_hash}')
            return True, None

        # 全量MD5校验
        try:
            if merged_md5 is not None:
                # 优先使用合并期已计算的 MD5，避免二次全量读盘
                logger.info(f'[Celery] Using merged MD5 from merge phase, skip re-read: {merged_md5}')
                computed_md5 = merged_md5
            else:
                # 回退：合并期未计算（理论不应发生），重新读盘计算
                logger.warning('[Celery] merged_md5 is None, fallback to full re-read')
                from apps.document.libs.document_utils import calculate_file_md5
                computed_md5 = calculate_file_md5(self.task_manager.file_path)

            if computed_md5 != file_hash:
                error_msg = '文件MD5校验失败，文件内容可能已被篡改'
                logger.error(f'[Celery] MD5 mismatch: expected={file_hash}, got={computed_md5}')
                return False, error_msg
            return True, None
        except Exception as e:
            # MD5计算异常需要重试
            raise


class FileRecordCreator:
    """文件记录创建器"""

    def __init__(self, task_manager):
        self.task_manager = task_manager

    def create_file_record(self, get_models_func, create_instance_func, get_mime_type_func):
        """创建文件记录"""
        self.task_manager.update_celery_state('PROGRESS', 85, '创建文件记录')
        logger.info(f'[Celery] Creating file record: is_public={self.task_manager.is_public}, folder_id={self.task_manager.folder_id}')

        try:
            FileModel, FolderModel = get_models_func(self.task_manager.is_public)
            logger.info(f'[Celery] Models loaded: FileModel={FileModel}, FolderModel={FolderModel}')
        except Exception as model_error:
            logger.error(f'[Celery] Failed to load models: {model_error}')
            raise

        # 获取文件夹
        folder = self._get_folder(FolderModel)

        # 获取用户
        from apps.account.models import User
        user = User.objects.filter(id=self.task_manager.user_id).first()
        logger.info(f'[Celery] Lookup results: folder={folder}, user={user}')

        if not user:
            error_msg = f'用户不存在: user_id={self.task_manager.user_id}'
            logger.error(f'[Celery] {error_msg}')
            return None, error_msg

        try:
            with transaction.atomic():
                new_file = self._create_file_instance(
                    FileModel, folder, user, create_instance_func, get_mime_type_func
                )
                logger.info(f'[Celery] File instance created: id={new_file.id if new_file else None}')
                return new_file, None
        except Exception as e:
            logger.error(f'[Celery] Database error: {e}')
            raise

    def _get_folder(self, FolderModel):
        """获取文件夹对象"""
        if not self.task_manager.folder_id:
            return None

        folder_query = FolderModel.objects.filter(pk=self.task_manager.folder_id).order_by()
        if not self.task_manager.is_public and self.task_manager.tenant_id:
            folder_query = folder_query.filter(tenant_id=self.task_manager.tenant_id)
        return folder_query.first()

    def _create_file_instance(self, FileModel, folder, user, create_instance_func, get_mime_type_func):
        """创建文件实例"""
        logger.info(f'[Celery] Creating file instance: physical_name={self.task_manager.physical_name}, logical_name={self.task_manager.logical_name}, display_name={self.task_manager.display_name}')

        new_file = create_instance_func(
            FileModel,
            name=self.task_manager.logical_name,
            display_name=self.task_manager.display_name,
            physical_name=self.task_manager.physical_name,
            folder=folder,
            file_path=self.task_manager.file_path,
            file_size=self.task_manager.file_size,
            file_type=get_mime_type_func(self.task_manager.file_name),
            created_by=user
        )

        # 【缩略图异步化】不再在 merge worker 中同步生成缩略图，
        # 改为投递 Celery 异步任务到 document.thumbnail 队列。
        # 使用 transaction.on_commit 保证：记录提交后才投递，
        # 避免任务查不到文件记录（_create_file_instance 处于
        # create_file_record 的 transaction.atomic() 块内）。
        # 缩略图生成耗时长（大图 Pillow 解码），剥离后合并任务可快速完成。
        file_id = new_file.id
        is_public = self.task_manager.is_public
        try:
            transaction.on_commit(
                lambda: _dispatch_thumbnail_task(file_id, is_public)
            )
        except Exception as e:
            logger.warning(
                f'[Celery] Failed to dispatch thumbnail task: file_id={file_id}, '
                f'is_public={is_public}, error={e}'
            )

        return new_file


class TransferStatusUpdater:
    """传输状态更新器"""

    def __init__(self, task_manager):
        self.task_manager = task_manager

    def update_status(self, status, **kwargs):
        """更新传输记录状态"""
        if not self.task_manager.transfer_id:
            return

        try:
            from apps.document.models import DocumentTransfer
            transfer = DocumentTransfer.objects.filter(id=self.task_manager.transfer_id).order_by().first()
            if transfer:
                transfer.status = status.value if hasattr(status, 'value') else status
                for key, value in kwargs.items():
                    setattr(transfer, key, value)
                transfer.save()
        except Exception as e:
            logger.error(f'[Celery] Failed to update transfer status: {e}')

    def mark_failed(self, error_message):
        """标记传输失败"""
        if self.task_manager.transfer_id:
            from apps.document.constants import TransferStatus
            self.update_status(TransferStatus.FAILED, error_message=error_message)


class CleanupManager:
    """清理管理器"""

    def __init__(self, task_manager):
        self.task_manager = task_manager

    def cleanup_on_error(self):
        """出错时清理文件"""
        try:
            if os.path.exists(self.task_manager.file_path):
                os.remove(self.task_manager.file_path)
                logger.info(f'[Celery] Cleaned up file on error: {self.task_manager.file_path}')
        except Exception as e:
            logger.warning(f'[Celery] Failed to cleanup file: {e}')

    def cleanup_chunks(self):
        """清理分片目录"""
        if os.path.exists(self.task_manager.chunk_dir):
            shutil.rmtree(self.task_manager.chunk_dir, ignore_errors=True)

    def cleanup_all(self):
        """清理所有临时文件"""
        self.cleanup_on_error()
        self.cleanup_chunks()


class MergePipeline:
    """合并流程管道 - 封装完整的合并流程"""

    def __init__(self, task_manager, celery_task):
        self.task_manager = task_manager
        self.celery_task = celery_task
        self.validator = ChunkValidator(task_manager)
        self.merger = ChunkMerger(task_manager)
        self.verifier = FileVerifier(task_manager)
        self.record_creator = FileRecordCreator(task_manager)
        self.status_updater = TransferStatusUpdater(task_manager)
        self.cleanup_manager = CleanupManager(task_manager)
        # 延迟导入避免循环依赖
        from apps.document.constants import TransferStatus
        self.TransferStatus = TransferStatus

    def _validate(self):
        """执行前置验证"""
        # 环境验证
        valid, error_msg = self.validator.validate_environment()
        if not valid:
            return self._handle_error(error_msg, 10, cleanup=False)

        # 分片完整性验证
        valid, error_msg = self.validator.validate_chunk_integrity()
        if not valid:
            return self._handle_error(error_msg, 20, cleanup=False)

        return True, None

    def _merge_and_verify(self, calculate_file_md5):
        """合并分片并验证"""
        self.status_updater.update_status(self._get_transfer_status('MERGING'))
        self.task_manager.update_task_file('MERGING', 30, '开始合并分片')

        # 合并分片
        valid, error_msg = self.merger.merge_chunks()
        if not valid:
            return self._handle_error(error_msg, 30, cleanup='file')

        # 验证文件大小
        valid, error_msg = self.verifier.verify_file_size()
        if not valid:
            return self._handle_error(error_msg, 65, cleanup='file')

        # 验证MD5（优先使用合并期已计算的 MD5，避免二次全量读盘）
        try:
            valid, error_msg = self.verifier.verify_file_md5(merged_md5=self.merger.merged_md5)
            if not valid:
                return self._handle_error(error_msg, 75, cleanup='all')
        except Exception:
            raise

        return True, None

    def _create_record(self, get_models, create_instance, get_mime_type):
        """创建文件记录"""
        new_file, error_msg = self.record_creator.create_file_record(
            get_models, create_instance, get_mime_type
        )
        if error_msg:
            return None, {'status': 'FAILED', 'error': error_msg, 'retryable': False}
        return new_file, None

    def _handle_error(self, error_msg, progress, cleanup=None):
        """处理错误"""
        self.task_manager.update_task_file('FAILED', progress, error_msg, result={'error': error_msg})
        if cleanup == 'file':
            self.cleanup_manager.cleanup_on_error()
        elif cleanup == 'all':
            self.cleanup_manager.cleanup_all()
        self.status_updater.mark_failed(error_msg)
        return False, {'status': 'FAILED', 'error': error_msg, 'retryable': False}

    def _finalize_success(self, new_file):
        """成功完成处理"""
        self.task_manager.update_celery_state('PROGRESS', PROGRESS_CLEANUP, '清理临时文件')
        self.cleanup_manager.cleanup_chunks()

        logger.info(f'[Celery] Merge task completed: job_id={self.task_manager.task_id}, file_id={new_file.id if new_file else None}')

        self.task_manager.update_task_file('SUCCESS', 100, '合并完成', result={
            'file_id': new_file.id if new_file else None,
            'file_name': self.task_manager.file_name,
            'file_size': self.task_manager.file_size
        })

        return {
            'status': 'SUCCESS',
            'file_id': new_file.id if new_file else None,
            'file_name': self.task_manager.file_name,
            'file_size': self.task_manager.file_size,
        }

    def _get_transfer_status(self, status_name):
        """获取传输状态枚举"""
        return getattr(self.TransferStatus, status_name)

    def execute(self, get_models, create_instance, get_mime_type, calculate_file_md5):
        """执行完整流程"""
        # 步骤1: 验证
        success, result = self._validate()
        if not success:
            return result

        # 步骤2: 合并和验证
        success, result = self._merge_and_verify(calculate_file_md5)
        if not success:
            return result

        # 步骤3: 创建记录
        new_file, result = self._create_record(get_models, create_instance, get_mime_type)
        if result:
            return result

        # 步骤4: 更新传输状态
        if self.task_manager.transfer_id and new_file:
            from django.utils import timezone as tz
            self.status_updater.update_status(
                self._get_transfer_status('COMPLETED'),
                file_path=new_file.file_path,
                progress=100,
                transferred_size=new_file.file_size,
                completed_at=tz.now()
            )

        # 步骤5: 完成
        return self._finalize_success(new_file)


def _update_transfer_status(transfer_id, status, **kwargs):
    """更新传输记录状态（兼容旧代码）"""
    if not transfer_id:
        return
    try:
        from apps.document.models import DocumentTransfer
        transfer = DocumentTransfer.objects.filter(id=transfer_id).order_by().first()
        if transfer:
            transfer.status = status.value if hasattr(status, 'value') else status
            for key, value in kwargs.items():
                setattr(transfer, key, value)
            transfer.save()
    except Exception as e:
        logger.error(f'[Celery] Failed to update transfer status: {e}')


def _cleanup_and_fail_transfer(transfer_id, error_message):
    """清理并标记传输失败（兼容旧代码）"""
    if transfer_id:
        from apps.document.constants import TransferStatus
        _update_transfer_status(transfer_id, TransferStatus.FAILED, error_message=error_message)


def _cleanup_on_error(file_path, chunk_dir):
    """出错时清理文件（兼容旧代码）"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f'[Celery] Cleaned up file on error: {file_path}')
    except Exception as e:
        logger.warning(f'[Celery] Failed to cleanup file: {e}')


def _dispatch_thumbnail_task(file_id, is_public):
    """
    投递缩略图异步生成任务（merge worker 用）

    独立成函数的原因：
    1. 避免在 transaction.on_commit 的 lambda 闭包中直接 import 任务模块
    2. 集中处理投递异常，任何情况下都不影响合并任务成功
    """
    try:
        from apps.document.tasks.thumbnail import generate_document_thumbnail
        generate_document_thumbnail.delay(file_id, is_public)
        logger.info(
            f'[Celery] Thumbnail task dispatched from merge: file_id={file_id}, '
            f'is_public={is_public}'
        )
    except Exception as e:
        logger.warning(
            f'[Celery] Failed to dispatch thumbnail task from merge: '
            f'file_id={file_id}, is_public={is_public}, error={e}'
        )


@shared_task(
    bind=True,
    max_retries=CELERY_MAX_RETRIES,
    default_retry_delay=CELERY_RETRY_DELAY_SECONDS,
    soft_time_limit=CELERY_SOFT_TIME_LIMIT_SECONDS,
    time_limit=CELERY_HARD_TIME_LIMIT_SECONDS,
    queue='document.merge',
)
def merge_file_chunks(self, job_data):
    """异步合并文件分片任务（生产级）"""
    job_id = self.request.id

    # 初始化
    task_manager = MergeTaskManager(job_id, job_data, self)
    task_manager.log_task_start()
    task_manager.update_task_file('STARTED', 5, '任务开始执行')

    # 分布式锁
    lock_key = f"merge_lock:{task_manager.file_hash}_{'public' if task_manager.is_public else 'private'}_{task_manager.tenant_id or 'default'}"
    lock_manager = RedisLock()

    if not lock_manager.acquire(lock_key, timeout=REDIS_LOCK_TIMEOUT_SECONDS):
        logger.warning(f'[Celery] Failed to acquire lock: {lock_key}')
        raise self.retry(countdown=LOCK_RETRY_COUNTDOWN_SECONDS)

    logger.info(f'[Celery] Lock acquired: {lock_key}')

    # 延迟导入
    from apps.document.constants import TransferStatus
    from apps.document.libs.document_utils import (
        get_mime_type, create_model_instance, calculate_file_md5,
        get_file_model, get_folder_model
    )

    def get_models(is_public):
        return get_file_model(is_public=is_public), get_folder_model(is_public=is_public)

    task_manager.update_celery_state('STARTED', 5, '开始合并任务')
    pipeline = MergePipeline(task_manager, self)
    cleanup_manager = CleanupManager(task_manager)
    status_updater = TransferStatusUpdater(task_manager)

    def handle_fatal_error(error_msg, cleanup_all=False):
        """处理致命错误"""
        logger.error(f'[Celery] {error_msg}: job_id={job_id}')
        task_manager.update_task_file('FAILED', 0, error_msg, result={'error': error_msg})
        if cleanup_all:
            cleanup_manager.cleanup_all()
        status_updater.mark_failed(error_msg)
        return {'status': 'FAILED', 'error': error_msg, 'retryable': False}

    try:
        return pipeline.execute(get_models, create_model_instance, get_mime_type, calculate_file_md5)

    except SoftTimeLimitExceeded:
        return handle_fatal_error('任务执行超时（软超时）', cleanup_all=True)

    except Retry:
        raise

    except MaxRetriesExceededError:
        return handle_fatal_error('任务重试次数耗尽', cleanup_all=True)

    except Exception as e:
        error_msg = str(e)
        logger.error(f'[Celery] Unexpected error: job_id={job_id}, error={error_msg}')
        logger.error(f'[Celery] Traceback: {traceback.format_exc()}')

        try:
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))
        except MaxRetriesExceededError:
            return handle_fatal_error(error_msg, cleanup_all=True)

    finally:
        lock_manager.release(lock_key)
        logger.info(f'[Celery] Lock released: {lock_key}')

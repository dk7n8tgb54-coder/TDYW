# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
异步文件复制 Celery 任务

用于大文件复制的后台执行，避免长时间占用 HTTP 请求线程。

流程：
1. 重新校验权限、租户和系统目录范围
2. 校验源文件及目标目录
3. 检查磁盘空间
4. 复制到目标目录临时文件（分块更新进度）
5. 校验目标大小
6. 原子改名为最终物理文件
7. 数据库事务创建复制记录
8. 标记完成
"""
import os
import shutil
import logging
from celery import shared_task
from django.db import transaction, IntegrityError
from django.conf import settings

from apps.document.models import DocumentTransfer, DocumentFilePrivate, DocumentFilePublic
from apps.document.constants import TransferStatus, TransferType
from apps.document.libs.document_utils import (
    get_file_model, get_folder_model, get_document_absolute_path, is_safe_path,
)
from apps.document.libs.naming_utils import generate_unique_logical_name
from libs.tenant_utils import apply_tenant_filter
from apps.document.services.conflict_service import (
    check_display_name_conflict, generate_unique_display_name,
)
from apps.document.services.system_folder_service import (
    validate_system_folder_context,
)
from apps.document.services.system_scope_validators import (
    validate_file_source_scope, validate_target_folder_scope,
)
from apps.document.views.base import create_model_instance, log_operation
from apps.account.models import User

logger = logging.getLogger(__name__)

# 分块大小（1MB）用于进度更新
COPY_CHUNK_SIZE = 1024 * 1024
# 进度更新间隔（每复制 5MB 更新一次进度）
PROGRESS_UPDATE_INTERVAL = 5 * 1024 * 1024


def _check_disk_space(target_dir, required_bytes):
    """检查磁盘剩余空间是否足够"""
    abs_target = os.path.abspath(target_dir)
    stat = os.statvfs(abs_target)
    free_bytes = stat.f_bavail * stat.f_frsize
    if free_bytes < required_bytes * 1.1:  # 留 10% 余量
        return False, f'磁盘空间不足，需要 {required_bytes / 1024 / 1024:.1f}MB，可用 {free_bytes / 1024 / 1024:.1f}MB'
    return True, None


def _copy_with_progress(source_path, temp_path, file_size, transfer_id):
    """
    分块复制文件并更新进度

    Args:
        source_path: 源文件路径
        temp_path: 临时文件路径
        file_size: 文件大小
        transfer_id: DocumentTransfer ID（用于更新进度）
    """
    copied = 0
    last_update = 0
    progress = 0

    with open(source_path, 'rb') as src, open(temp_path, 'wb') as dst:
        while True:
            # 检查取消状态
            if _check_cancelled(transfer_id):
                raise RuntimeError('复制任务已被取消')

            chunk = src.read(COPY_CHUNK_SIZE)
            if not chunk:
                break
            dst.write(chunk)
            copied += len(chunk)

            # 每 PROGRESS_UPDATE_INTERVAL 字节更新一次进度
            if copied - last_update >= PROGRESS_UPDATE_INTERVAL or copied == file_size:
                progress = int(copied * 100 / file_size) if file_size > 0 else 100
                _update_progress(transfer_id, progress, copied)
                last_update = copied

    # 验证复制后大小
    actual_size = os.path.getsize(temp_path)
    if actual_size != file_size:
        raise RuntimeError(
            f'复制后文件大小不匹配，期望 {file_size}，实际 {actual_size}'
        )

    return temp_path


def _check_cancelled(transfer_id):
    """检查任务是否被取消"""
    try:
        transfer = DocumentTransfer.objects.get(pk=transfer_id)
        return transfer.status == TransferStatus.CANCELED.value
    except DocumentTransfer.DoesNotExist:
        return True


def _update_progress(transfer_id, progress, transferred_size):
    """更新传输进度"""
    DocumentTransfer.objects.filter(pk=transfer_id).update(
        progress=progress,
        transferred_size=transferred_size,
    )


def _cleanup_temp_file(temp_path):
    """清理临时文件"""
    try:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
            logger.info('[AsyncCopy] Cleaned up temp file: %s', temp_path)
    except OSError as e:
        logger.warning('[AsyncCopy] Failed to cleanup temp file %s: %s', temp_path, e)


def _validate_copy_context(transfer):
    """
    重新校验权限、租户和系统目录范围

    Returns:
        (source_file, folder, FileModel, error_msg) 或 (None, None, None, error_msg)
    """
    is_public = transfer.is_public
    system_folder = transfer.system_folder or ''

    # 1. 校验系统目录上下文
    ok, err = validate_system_folder_context(system_folder if system_folder else None, is_public)
    if not ok:
        return None, None, None, err

    # 2. 重新加载用户（用于租户过滤）
    try:
        user = User.objects.get(pk=transfer.user_id)
    except User.DoesNotExist:
        return None, None, None, '用户不存在'

    # 3. 校验源文件
    FileModel = get_file_model(is_public=is_public)
    source_file = FileModel.objects.filter(pk=transfer.source_file_id).select_related('created_by').first()
    if not source_file:
        return None, None, None, '源文件不存在'

    # 租户过滤
    if not is_public:
        source_qs = apply_tenant_filter(
            FileModel.objects.filter(pk=transfer.source_file_id), user, strict_mode=True
        )
        if not source_qs.exists():
            return None, None, None, '无权访问源文件'

    # 4. 校验系统作用域
    scope_ok, scope_err = validate_file_source_scope(system_folder if system_folder else None, is_public, source_file)
    if not scope_ok:
        return None, None, None, scope_err

    # 5. 校验目标文件夹
    FolderModel = get_folder_model(is_public=is_public)
    folder = None
    if transfer.folder_id:
        folder = FolderModel.objects.filter(pk=transfer.folder_id).first()
        if not folder:
            return None, None, None, '目标文件夹不存在'
        if not is_public:
            folder_qs = apply_tenant_filter(
                FolderModel.objects.filter(pk=transfer.folder_id), user, strict_mode=True
            )
            if not folder_qs.exists():
                return None, None, None, '无权访问目标文件夹'

    # 6. 校验目标文件夹作用域
    if transfer.folder_id:
        target_ok, target_err = validate_target_folder_scope(
            system_folder if system_folder else None, is_public, transfer.folder_id, allow_root=True
        )
        if not target_ok:
            return None, None, None, target_err

    return source_file, folder, FileModel, None


def _execute_copy(transfer, source_file, folder, FileModel):
    """
    执行实际的文件复制

    Returns:
        (new_file, None) 或 (None, error_msg)
    """
    is_public = transfer.is_public
    system_folder = transfer.system_folder or ''
    target_path = transfer.file_path
    file_size = transfer.file_size or source_file.file_size or 0

    # 源文件路径
    source_path = transfer.source_file_path or source_file.file_path
    if not source_path or not os.path.exists(source_path):
        return None, '源文件物理路径不存在'

    # 路径安全校验
    document_storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
    if not is_safe_path(document_storage_base, source_path):
        return None, '源文件路径异常'
    if not is_safe_path(document_storage_base, target_path):
        return None, '目标文件路径异常'

    # 临时文件路径（同目录，确保原子 rename）
    temp_path = target_path + '.copying_tmp'

    try:
        # 检查磁盘空间
        target_dir = os.path.dirname(target_path)
        ok, err = _check_disk_space(target_dir, file_size)
        if not ok:
            return None, err

        # 更新状态为 COPYING
        DocumentTransfer.objects.filter(pk=transfer.id).update(
            status=TransferStatus.COPYING.value,
            progress=0,
            transferred_size=0,
        )

        # 分块复制（带进度更新）
        _copy_with_progress(source_path, temp_path, file_size, transfer.id)

        # 原子改名为最终文件
        os.replace(temp_path, target_path)
        logger.info('[AsyncCopy] File copied and renamed: %s -> %s', source_path, target_path)

    except RuntimeError as e:
        # 取消或大小不匹配
        _cleanup_temp_file(temp_path)
        _mark_failed(transfer.id, str(e))
        return None, str(e)
    except OSError as e:
        _cleanup_temp_file(temp_path)
        _mark_failed(transfer.id, f'文件复制失败: {e}')
        return None, f'文件复制失败: {e}'

    # 数据库事务创建记录
    try:
        new_file = _create_file_record(
            transfer, source_file, folder, FileModel, target_path
        )
        return new_file, None
    except IntegrityError as e:
        logger.error('[AsyncCopy] DB error creating file record: %s', e)
        _cleanup_physical(target_path)
        _mark_failed(transfer.id, '数据库写入失败')
        return None, '数据库写入失败'
    except Exception as e:
        logger.error('[AsyncCopy] Unexpected error: %s', e)
        _cleanup_physical(target_path)
        _mark_failed(transfer.id, str(e))
        return None, str(e)


def _create_file_record(transfer, source_file, folder, FileModel, target_path):
    """
    在事务内创建文件记录，处理冲突

    Returns:
        new_file 对象

    Raises:
        IntegrityError, ValueError
    """
    is_public = transfer.is_public
    user = transfer.user
    display_name = transfer.file_name
    conflict_action = transfer.conflict_action or ''
    physical_name = os.path.basename(target_path)

    try:
        user_obj = User.objects.get(pk=user.id)
    except User.DoesNotExist:
        raise ValueError('用户不存在')

    try:
        with transaction.atomic():
            # 重新检查冲突（排除源文件自身）
            existing = check_display_name_conflict(
                FileModel, display_name, folder, user_obj, is_public,
                exclude_id=source_file.id
            )

            final_display_name = display_name
            final_logical_name = generate_unique_logical_name(
                FileModel, display_name, folder, user_obj
            )

            if existing:
                if conflict_action == 'replace':
                    # 删除旧文件（事务提交后清理物理文件）
                    _old_path = existing.file_path
                    _old_thumb = existing.thumbnail_path or ''
                    existing.delete()
                    transaction.on_commit(
                        lambda p=_old_path, t=_old_thumb: _cleanup_deleted_file(p, t)
                    )
                elif conflict_action == 'keep':
                    # 生成唯一 display_name
                    final_display_name = generate_unique_display_name(
                        FileModel, display_name, folder, user_obj, is_public
                    )
                    final_logical_name = generate_unique_logical_name(
                        FileModel, final_display_name, folder, user_obj
                    )
                elif conflict_action == 'skip':
                    # skip：不创建记录，清理已复制的物理文件，标记完成
                    DocumentTransfer.objects.filter(pk=transfer.id).update(
                        status=TransferStatus.COMPLETED.value,
                        progress=100,
                        transferred_size=0,
                        error_message='跳过：目标位置已存在同名文件',
                    )
                    # 清理已复制的物理文件
                    transaction.on_commit(
                        lambda p=target_path: _cleanup_physical(p)
                    )
                    logger.info('[AsyncCopy] Skipped (conflict + skip action), transfer_id=%s', transfer.id)
                    return None
                else:
                    raise ValueError('目标位置已存在同名文件')

            # 创建文件记录
            new_file = create_model_instance(FileModel,
                name=final_logical_name,
                display_name=final_display_name,
                physical_name=physical_name,
                folder=folder,
                file_path=target_path,
                file_size=source_file.file_size,
                file_type=source_file.file_type,
                created_by=user_obj
            )

            # 标记传输完成
            DocumentTransfer.objects.filter(pk=transfer.id).update(
                status=TransferStatus.COMPLETED.value,
                progress=100,
                transferred_size=source_file.file_size or 0,
            )

            # 记录审计日志
            log_operation(
                action="FILE_COPY",
                user=user_obj,
                resource_type="FILE",
                resource_id=new_file.id,
                is_public=is_public,
                source_file_id=source_file.id,
                original_display_name=source_file.display_name or source_file.name,
                new_display_name=final_display_name,
                target_folder_id=folder.id if folder else None
            )

            return new_file

    except IntegrityError:
        raise
    except ValueError:
        raise
    except Exception as e:
        logger.error('[AsyncCopy] Error in _create_file_record: %s', e)
        raise


def _cleanup_physical(file_path):
    """清理已复制的物理文件"""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info('[AsyncCopy] Cleaned up physical file: %s', file_path)
    except OSError as e:
        logger.warning('[AsyncCopy] Failed to cleanup physical file %s: %s', file_path, e)


def _cleanup_deleted_file(file_path, thumbnail_path):
    """事务提交后清理被 replace 删除的文件物理文件"""
    for p in [file_path, thumbnail_path]:
        if p and os.path.exists(p):
            try:
                os.remove(p)
                logger.info('[AsyncCopy] Cleaned up deleted file: %s', p)
            except Exception as e:
                logger.warning('[AsyncCopy] Failed to cleanup %s: %s', p, e)


def _mark_failed(transfer_id, error_msg):
    """标记任务失败"""
    DocumentTransfer.objects.filter(pk=transfer_id).update(
        status=TransferStatus.FAILED.value,
        error_message=error_msg[:500] if error_msg else '复制失败',
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def copy_file_async(self, transfer_id):
    """
    异步复制文件任务

    Args:
        transfer_id: DocumentTransfer 记录 ID

    幂等性：
    - 通过 transfer_id 唯一标识任务
    - 任务开始时检查状态，如果已完成或已取消则直接返回
    - 重试时不会产生多个复制品
    """
    logger.info('[AsyncCopy] Task started, transfer_id=%s, task_id=%s', transfer_id, self.request.id)

    try:
        transfer = DocumentTransfer.objects.get(pk=transfer_id)
    except DocumentTransfer.DoesNotExist:
        logger.error('[AsyncCopy] Transfer record not found: %s', transfer_id)
        return {'status': 'failed', 'error': '传输记录不存在'}

    # 幂等检查：已完成或已取消则直接返回
    if transfer.status == TransferStatus.COMPLETED.value:
        logger.info('[AsyncCopy] Transfer already completed, skipping: %s', transfer_id)
        return {'status': 'completed', 'transfer_id': transfer_id}

    if transfer.status == TransferStatus.CANCELED.value:
        logger.info('[AsyncCopy] Transfer was canceled, skipping: %s', transfer_id)
        return {'status': 'canceled', 'transfer_id': transfer_id}

    # 更新 celery_task_id
    DocumentTransfer.objects.filter(pk=transfer_id).update(celery_task_id=self.request.id)

    # 重新校验权限、租户、作用域
    source_file, folder, FileModel, error = _validate_copy_context(transfer)
    if error:
        logger.error('[AsyncCopy] Validation failed: %s', error)
        _mark_failed(transfer_id, error)
        return {'status': 'failed', 'error': error}

    # 执行复制
    new_file, error = _execute_copy(transfer, source_file, folder, FileModel)
    if error:
        logger.error('[AsyncCopy] Copy failed: %s', error)
        return {'status': 'failed', 'error': error}

    if new_file is None:
        # skip 场景：无新文件记录但任务完成
        logger.info('[AsyncCopy] Copy skipped (conflict+skip), transfer_id=%s', transfer_id)
        return {'status': 'skipped', 'transfer_id': transfer_id}

    logger.info('[AsyncCopy] Copy completed successfully, transfer_id=%s, new_file_id=%s',
                transfer_id, new_file.id)
    return {'status': 'completed', 'transfer_id': transfer_id, 'file_id': new_file.id}

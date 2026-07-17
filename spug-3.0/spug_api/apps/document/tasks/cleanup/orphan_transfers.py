# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
清理任务 - 孤儿传输记录清理

【优化10】定时清理异常状态的传输记录，避免 transfer 表无限膨胀

清理规则：
1. PENDING 超过 24 小时且 file_hash 为空 -> 标记 CANCELED
2. UPLOADING 超过 24 小时且无分片更新 -> 标记 FAILED
3. MERGING 超时且 Celery task 不存在 -> 标记 FAILED
4. FAILED/CANCELED 超过保留期(7天) -> 删除记录 + 清理分片目录
"""
import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)

# 孤儿判定阈值
PENDING_TIMEOUT_HOURS = 24
UPLOADING_TIMEOUT_HOURS = 24
MERGING_TIMEOUT_HOURS = 2
FAILED_CANCELED_RETENTION_DAYS = 7


def _cleanup_pending_orphans(now, dry_run, stats):
    """PENDING 超过 24 小时且 file_hash 为空 -> CANCELED"""
    from apps.document.models import DocumentTransfer
    from apps.document.constants import TransferStatus

    cutoff = now - timedelta(hours=PENDING_TIMEOUT_HOURS)
    for transfer in DocumentTransfer.objects.filter(
        status=TransferStatus.PENDING.value,
        created_at__lte=cutoff,
        file_hash='',
    ):
        try:
            if dry_run:
                logger.info(f'[Cleanup][DryRun] 将标记 PENDING->CANCELED: id={transfer.id}, name={transfer.file_name}')
            else:
                transfer.status = TransferStatus.CANCELED.value
                transfer.error_message = '超时未开始上传，自动取消'
                transfer.save()
            stats['pending_canceled'] += 1
        except Exception as e:
            logger.error(f'[Cleanup] 标记 PENDING 超时记录失败: id={transfer.id}, error={e}')
            stats['errors'] += 1


def _cleanup_uploading_orphans(now, dry_run, stats):
    """UPLOADING 超过 24 小时且无更新 -> FAILED"""
    from apps.document.models import DocumentTransfer
    from apps.document.constants import TransferStatus

    cutoff = now - timedelta(hours=UPLOADING_TIMEOUT_HOURS)
    for transfer in DocumentTransfer.objects.filter(
        status=TransferStatus.UPLOADING.value,
        updated_at__lte=cutoff,
    ):
        try:
            if dry_run:
                logger.info(f'[Cleanup][DryRun] 将标记 UPLOADING->FAILED: id={transfer.id}, name={transfer.file_name}')
            else:
                transfer.status = TransferStatus.FAILED.value
                transfer.error_message = '上传超时无更新，自动标记失败'
                transfer.save()
            stats['uploading_failed'] += 1
        except Exception as e:
            logger.error(f'[Cleanup] 标记 UPLOADING 超时记录失败: id={transfer.id}, error={e}')
            stats['errors'] += 1


def _cleanup_merging_orphans(now, dry_run, stats):
    """MERGING 超时且 Celery task 不存在 -> FAILED"""
    from apps.document.models import DocumentTransfer
    from apps.document.constants import TransferStatus

    cutoff = now - timedelta(hours=MERGING_TIMEOUT_HOURS)
    for transfer in DocumentTransfer.objects.filter(
        status=TransferStatus.MERGING.value,
        updated_at__lte=cutoff,
    ):
        try:
            # 检查 Celery 任务是否还存在
            if transfer.celery_task_id:
                from apps.document.libs.celery_lock import redis_client
                task_exists = redis_client.exists(f'celery-task-meta-{transfer.celery_task_id}')
                if task_exists:
                    continue  # 任务还在，跳过

            if dry_run:
                logger.info(f'[Cleanup][DryRun] 将标记 MERGING->FAILED: id={transfer.id}, name={transfer.file_name}')
            else:
                transfer.status = TransferStatus.FAILED.value
                transfer.error_message = '合并任务超时或丢失，自动标记失败'
                transfer.save()
            stats['merging_failed'] += 1
        except Exception as e:
            logger.error(f'[Cleanup] 标记 MERGING 超时记录失败: id={transfer.id}, error={e}')
            stats['errors'] += 1


def _cleanup_old_transfers(now, dry_run, stats):
    """FAILED/CANCELED 超过保留期 -> 删除记录 + 清理分片目录"""
    from apps.document.models import DocumentTransfer
    from apps.document.constants import TransferStatus

    retention_cutoff = now - timedelta(days=FAILED_CANCELED_RETENTION_DAYS)
    for transfer in DocumentTransfer.objects.filter(
        status__in=[TransferStatus.FAILED.value, TransferStatus.CANCELED.value],
        updated_at__lte=retention_cutoff,
    ):
        try:
            # 清理分片目录
            if transfer.file_hash and not dry_run:
                if _cleanup_transfer_chunk_dir(transfer):
                    stats['chunk_dirs_cleaned'] += 1

            if dry_run:
                logger.info(f'[Cleanup][DryRun] 将删除旧传输记录: id={transfer.id}, name={transfer.file_name}')
            else:
                transfer.delete()
            stats['old_deleted'] += 1
        except Exception as e:
            logger.error(f'[Cleanup] 删除旧传输记录失败: id={transfer.id}, error={e}')
            stats['errors'] += 1


@shared_task(bind=True, soft_time_limit=1800, time_limit=3600, queue='document.cleanup')
def cleanup_orphan_transfers(self, dry_run=False):
    """
    清理孤儿传输记录

    Args:
        dry_run: 仅模拟运行，不实际修改

    Returns:
        dict: 清理统计
    """
    stats = {
        'pending_canceled': 0,
        'uploading_failed': 0,
        'merging_failed': 0,
        'old_deleted': 0,
        'chunk_dirs_cleaned': 0,
        'errors': 0,
    }

    now = timezone.now()

    # 1. PENDING 超过 24 小时且 file_hash 为空 -> CANCELED
    _cleanup_pending_orphans(now, dry_run, stats)

    # 2. UPLOADING 超过 24 小时且无更新 -> FAILED
    _cleanup_uploading_orphans(now, dry_run, stats)

    # 3. MERGING 超时且 Celery task 不存在 -> FAILED
    _cleanup_merging_orphans(now, dry_run, stats)

    # 4. FAILED/CANCELED 超过保留期 -> 删除记录 + 清理分片目录
    _cleanup_old_transfers(now, dry_run, stats)

    result = {'status': 'success', 'stats': stats, 'dry_run': dry_run}
    logger.info(f'[Cleanup] 孤儿传输记录清理完成: {result}')
    return result


def _cleanup_transfer_chunk_dir(transfer):
    """清理传输记录对应的分片目录"""
    import os
    import shutil
    try:
        from apps.document.libs.document_utils import get_chunk_dir_path, is_safe_path
        from django.contrib.auth import get_user_model
        from django.conf import settings as django_settings

        User = get_user_model()
        user = User.objects.filter(id=transfer.user_id).first()
        if not user:
            return False

        # 【P1修复】r mt ree 之前必须做路径安全校验，确保目标在 document_chunks 下
        chunk_base_dir = os.path.join(django_settings.BASE_DIR, 'storage', 'document_chunks')

        # 尝试带 transfer_id 的路径
        system_folder = getattr(transfer, 'system_folder', None) or None
        if transfer.id:
            chunk_dir = get_chunk_dir_path(
                transfer.file_hash, transfer.is_public, user,
                transfer_id=transfer.id,
                system_folder=system_folder,
            )
            if is_safe_path(chunk_base_dir, chunk_dir) and os.path.exists(chunk_dir):
                shutil.rmtree(chunk_dir, ignore_errors=True)
                return True

        # 回退到旧路径
        chunk_dir = get_chunk_dir_path(
            transfer.file_hash,
            transfer.is_public,
            user,
            system_folder=system_folder,
        )
        if is_safe_path(chunk_base_dir, chunk_dir) and os.path.exists(chunk_dir):
            shutil.rmtree(chunk_dir, ignore_errors=True)
            return True

        return False

    except Exception as e:
        logger.warning(f'[Cleanup] 清理分片目录失败: transfer_id={transfer.id}, error={e}')
        return False

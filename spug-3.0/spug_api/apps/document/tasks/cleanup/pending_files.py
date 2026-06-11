# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
清理任务 - 待清理文件重试
"""
import logging
import os
from celery import shared_task
from django.utils import timezone
from apps.document.exceptions import DocumentPhysicalDeleteError
from apps.document.libs.document_utils import safe_delete_document_file

logger = logging.getLogger(__name__)

RETRY_COOLDOWN_SECONDS = 3600
MAX_RETRY_COUNT = 3


def _process_pending_files(FileModel, space_name):
    """
    处理单个空间的待清理文件

    Args:
        FileModel: 文件模型类
        space_name: 空间名称（'private' / 'public'）

    Returns:
        tuple: (成功数, 失败数)
    """
    success = 0
    failed = 0

    pending_files = FileModel.objects.filter(is_pending_clean=True).order_by()
    for file in pending_files:
        # 跳过冷却期内的文件
        if file.last_clean_attempt and (timezone.now() - file.last_clean_attempt).seconds < RETRY_COOLDOWN_SECONDS:
            continue

        try:
            if os.path.exists(file.file_path):
                deleted, error = safe_delete_document_file(file.file_path)
                if not deleted:
                    logger.error(f'[Cleanup] 安全删除失败，文件路径异常: id={file.id}, path={file.file_path}, error={error}')

            file.delete(hard=True)
            success += 1
            logger.info(f'[Cleanup] 待清理{space_name}文件删除成功: id={file.id}')

        except DocumentPhysicalDeleteError as e:
            logger.warning(f'[Cleanup] 待清理{space_name}文件重试仍失败: id={file.id}, path={e.file_path}')
            if file.clean_retry_count >= MAX_RETRY_COUNT:
                logger.critical(f'[Cleanup] 文件id={file.id}删除失败超过{MAX_RETRY_COUNT}次，需人工介入')
            failed += 1

        except Exception as e:
            logger.error(f'[Cleanup] 待清理{space_name}文件删除失败: id={file.id}, error={e}')
            file.clean_retry_count += 1
            file.last_clean_attempt = timezone.now()

            if file.clean_retry_count >= MAX_RETRY_COUNT:
                logger.critical(f'[Cleanup] 文件id={file.id}删除失败超过{MAX_RETRY_COUNT}次，需人工介入')

            file.save(update_fields=['clean_retry_count', 'last_clean_attempt'])
            failed += 1

    return success, failed


@shared_task(bind=True, soft_time_limit=1800, time_limit=3600, queue='document.cleanup')
def retry_clean_pending_files():
    """
    【P0修复】重试清理标记为待清理的文件
    当物理文件删除失败时，会标记为待清理状态，由本任务定时重试
    """
    from apps.document.models import DocumentFilePrivate, DocumentFilePublic

    private_success, private_failed = _process_pending_files(DocumentFilePrivate, '私有')
    public_success, public_failed = _process_pending_files(DocumentFilePublic, '公共')

    stats = {
        'private': private_success,
        'public': public_success,
        'failed': private_failed + public_failed,
    }

    logger.info(f'[Cleanup] 待清理文件处理完成: {stats}')
    return stats

# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
清理任务 - 过期分片清理
"""
import logging
from celery import shared_task
from apps.document.services.chunk_cleanup_service import ChunkCleanupService

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=1800, time_limit=3600, queue='document.cleanup')
def cleanup_old_chunks(self, days=7):
    """
    清理过期分片文件

    Args:
        days: 保留天数，默认7天

    Returns:
        dict: 清理结果
    """
    logger.info(f'[Celery] Starting cleanup of chunks older than {days} days')

    service = ChunkCleanupService(days=days)
    return service.cleanup()

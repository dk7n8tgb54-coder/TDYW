# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
清理任务 - 待清理文件重试
"""
import logging
import os
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=1800, time_limit=3600, queue='document.cleanup')
def retry_clean_pending_files():
    """
    【P0修复】重试清理标记为待清理的文件
    当物理文件删除失败时，会标记为待清理状态，由本任务定时重试
    """
    from apps.document.models import DocumentFilePrivate, DocumentFilePublic
    
    stats = {'private': 0, 'public': 0, 'failed': 0}
    
    # 处理私有文件
    pending_private = DocumentFilePrivate.objects.filter(is_pending_clean=True)
    for file in pending_private:
        # 跳过最近1小时内已尝试的文件
        if file.last_clean_attempt and (timezone.now() - file.last_clean_attempt).seconds < 3600:
            continue
        
        try:
            if os.path.exists(file.file_path):
                os.remove(file.file_path)
            
            # 物理文件删除成功，删除数据库记录
            file.delete(hard=True)
            stats['private'] += 1
            logger.info(f'[Cleanup] 待清理私有文件删除成功: id={file.id}')
            
        except Exception as e:
            logger.error(f'[Cleanup] 待清理私有文件删除失败: id={file.id}, error={e}')
            file.clean_retry_count += 1
            file.last_clean_attempt = timezone.now()
            
            # 超过3次重试则告警
            if file.clean_retry_count >= 3:
                logger.critical(f'[Cleanup] 文件id={file.id}删除失败超过3次，需人工介入')
            
            file.save(update_fields=['clean_retry_count', 'last_clean_attempt'])
            stats['failed'] += 1
    
    # 处理公共文件
    pending_public = DocumentFilePublic.objects.filter(is_pending_clean=True)
    for file in pending_public:
        if file.last_clean_attempt and (timezone.now() - file.last_clean_attempt).seconds < 3600:
            continue
        
        try:
            if os.path.exists(file.file_path):
                os.remove(file.file_path)
            
            file.delete(hard=True)
            stats['public'] += 1
            logger.info(f'[Cleanup] 待清理公共文件删除成功: id={file.id}')
            
        except Exception as e:
            logger.error(f'[Cleanup] 待清理公共文件删除失败: id={file.id}, error={e}')
            file.clean_retry_count += 1
            file.last_clean_attempt = timezone.now()
            
            if file.clean_retry_count >= 3:
                logger.critical(f'[Cleanup] 文件id={file.id}删除失败超过3次，需人工介入')
            
            file.save(update_fields=['clean_retry_count', 'last_clean_attempt'])
            stats['failed'] += 1
    
    logger.info(f'[Cleanup] 待清理文件处理完成: {stats}')
    return stats

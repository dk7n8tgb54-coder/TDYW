# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
合并任务超时检测
【P2优化】防止任务卡在merging状态，确保数据库状态最终一致性
"""
import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from django.db import transaction

from apps.logs.audit import log_celery_audit

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=300, time_limit=600, queue='document.cleanup')
def check_merge_timeout(self, timeout_minutes=30):
    """
    检测合并超时的任务，重置为failed状态以便重试
    
    Args:
        timeout_minutes: 超时时间（分钟），默认30分钟
        
    Returns:
        dict: 处理结果
    """
    from apps.document.models import DocumentTransfer
    from apps.document.constants import TransferStatus
    
    logger.info(f'[TimeoutChecker] 开始检测合并超时任务（>{timeout_minutes}分钟）')
    
    try:
        # 计算超时时间点
        timeout_threshold = timezone.now() - timedelta(minutes=timeout_minutes)
        
        # 查找超时的合并任务
        # 【注意】使用updated_at字段，如果任务正在正常进行，updated_at会被更新
        timeout_tasks = DocumentTransfer.objects.filter(
            status=TransferStatus.MERGING.value,
            updated_at__lt=timeout_threshold
        ).select_related('user').order_by()
        
        timeout_count = timeout_tasks.count()
        if timeout_count == 0:
            logger.info('[TimeoutChecker] 未发现超时任务')
            return {
                'status': 'success',
                'timeout_count': 0,
                'reset_count': 0,
                'message': '未发现超时任务'
            }
        
        logger.warning(f'[TimeoutChecker] 发现 {timeout_count} 个超时任务')
        
        reset_count = 0
        errors = []
        
        for task in timeout_tasks:
            try:
                with transaction.atomic():
                    # 重新查询并加锁，防止并发修改
                    locked_task = DocumentTransfer.objects.select_for_update().get(
                        id=task.id,
                        status=TransferStatus.MERGING.value
                    )
                    
                    # 再次检查updated_at（双重检查）
                    if locked_task.updated_at >= timeout_threshold:
                        logger.info(f'[TimeoutChecker] 任务已被更新，跳过: transfer={task.id}')
                        continue
                    
                    # 重置为失败状态
                    old_status = locked_task.status
                    locked_task.status = TransferStatus.FAILED.value
                    locked_task.error_message = f'合并任务超时（{timeout_minutes}分钟），已重置为可重试状态'
                    locked_task.save(update_fields=['status', 'error_message', 'updated_at'])
                    
                    reset_count += 1
                    logger.warning(
                        f'[TimeoutChecker] 任务已重置: '
                        f'transfer={task.id}, '
                        f'file={task.file_name}, '
                        f'old_status={old_status}, '
                        f'updated_at={task.updated_at}'
                    )
                    
            except Exception as e:
                error_msg = f'处理任务 {task.id} 失败: {str(e)}'
                logger.error(f'[TimeoutChecker] {error_msg}')
                errors.append(error_msg)
        
        result = {
            'status': 'success',
            'timeout_count': timeout_count,
            'reset_count': reset_count,
            'errors': errors,
            'message': f'检测到 {timeout_count} 个超时任务，成功重置 {reset_count} 个'
        }
        
        logger.info(f'[TimeoutChecker] 检测完成: {result["message"]}')
        if reset_count > 0:
            log_celery_audit('update', 'document',
                             target_name='合并超时任务重置',
                             detail={'timeout_count': timeout_count, 'reset_count': reset_count})
        return result
        
    except Exception as e:
        error_msg = f'超时检测任务执行失败: {str(e)}'
        logger.error(f'[TimeoutChecker] {error_msg}')
        return {
            'status': 'error',
            'message': error_msg
        }


@shared_task(bind=True, soft_time_limit=180, time_limit=300, queue='document.cleanup')
def cleanup_stale_merging_tasks(self, older_than_hours=24):
    """
    清理长时间卡在merging状态的任务（超过24小时）
    这些任务被认为是"僵尸任务"，直接标记为失败
    
    Args:
        older_than_hours: 超过多少小时认为是僵尸任务，默认24小时
        
    Returns:
        dict: 处理结果
    """
    from apps.document.models import DocumentTransfer
    from apps.document.constants import TransferStatus
    
    logger.info(f'[TimeoutChecker] 开始清理僵尸合并任务（>{older_than_hours}小时）')
    
    try:
        stale_threshold = timezone.now() - timedelta(hours=older_than_hours)
        
        stale_tasks = DocumentTransfer.objects.filter(
            status=TransferStatus.MERGING.value,
            updated_at__lt=stale_threshold
        ).order_by()
        
        stale_count = stale_tasks.count()
        if stale_count == 0:
            return {
                'status': 'success',
                'stale_count': 0,
                'message': '未发现僵尸任务'
            }
        
        # 批量更新为失败状态
        updated = stale_tasks.update(
            status=TransferStatus.FAILED.value,
            error_message=f'合并任务异常（超过{older_than_hours}小时），系统自动清理',
            updated_at=timezone.now()
        )
        
        logger.warning(f'[TimeoutChecker] 已清理 {updated} 个僵尸任务')
        if updated > 0:
            log_celery_audit('update', 'document',
                             target_name='僵尸合并任务清理',
                             detail={'stale_count': stale_count, 'cleaned': updated})
        return {
            'status': 'success',
            'stale_count': stale_count,
            'updated': updated,
            'message': f'发现 {stale_count} 个僵尸任务，已清理 {updated} 个'
        }
        
    except Exception as e:
        error_msg = f'清理僵尸任务失败: {str(e)}'
        logger.error(f'[TimeoutChecker] {error_msg}')
        return {
            'status': 'error',
            'message': error_msg
        }

# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
清理任务 - 过期传输记录清理
"""
import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=1800, time_limit=3600, queue='document.cleanup')
def cleanup_expired_transfers(self, days=30):
    """
    清理过期传输记录
    
    Args:
        days: 保留天数，默认30天
        
    Returns:
        dict: 清理结果
    """
    from apps.document.models import DocumentTransfer
    from apps.document.constants import TransferStatus
    
    cutoff_date = timezone.now() - timedelta(days=days)
    
    try:
        # 删除过期的已完成/失败/取消记录
        expired_transfers = DocumentTransfer.objects.filter(
            status__in=[
                TransferStatus.COMPLETED.value,
                TransferStatus.FAILED.value,
                TransferStatus.CANCELED.value
            ],
            updated_at__lt=cutoff_date
        ).order_by()
        
        count = expired_transfers.count()
        expired_transfers.delete()
        
        result = {
            'status': 'success',
            'deleted_count': count,
            'cutoff_date': cutoff_date.isoformat()
        }
        
        logger.info(f'[Celery] Cleanup expired transfers completed: deleted={count}')
        return result
        
    except Exception as e:
        logger.error(f'[Celery] Cleanup expired transfers failed: {e}')
        return {'status': 'error', 'message': str(e)}

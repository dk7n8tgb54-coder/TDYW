# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
Celery任务定义 - 主入口
"""
import logging
from celery import shared_task
from django.conf import settings

from .queries import TransferQueryService
from .classifiers import TransferClassifier
from .deleters import BatchDeleteService
from .cleanup import ChunkCleanupService

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue='document.batch',
    time_limit=300,
    soft_time_limit=240,
)
def batch_delete_transfers(self, transfer_ids, request_user_id, request_tenant_id):
    """
    异步批量删除传输记录 - 生产优化版
    职责：流程编排，不处理具体业务逻辑
    """
    logger.info(
        f'[Celery] Batch delete start: '
        f'count={len(transfer_ids)}, tenant={request_tenant_id}'
    )

    # 1. 查询（查询层）
    transfers = TransferQueryService.fetch_by_ids(transfer_ids, request_tenant_id)

    # 2. 分类（分类层）
    deletable_transfers, skipped_ids = TransferClassifier.classify(transfers)

    # 3. 执行删除（删除层）
    delete_service = BatchDeleteService(
        batch_size=getattr(settings, 'DOCUMENT_BATCH_SIZE', 10),
        tenant_id=request_tenant_id
    )
    deleted_count, chunk_results = delete_service.execute(deletable_transfers)

    # 4. 构建结果
    result = {
        'deleted': deleted_count,
        'skipped': len(skipped_ids),
        'total': len(transfer_ids),
        'chunk_cleaned': ChunkCleanupService.count_cleaned(chunk_results),
    }

    logger.info(f'[Celery] Batch delete completed: {result}')
    return result


@shared_task(bind=True, max_retries=3, default_retry_delay=30, queue='document.batch')
def batch_cancel_transfers(self, transfer_ids, request_user_id, request_tenant_id):
    """
    异步批量取消传输（保持原实现，后续可同样拆分）
    """
    from apps.document.models import DocumentTransfer
    from apps.document.constants import TransferStatus, is_valid_status_transition
    from django.db import transaction

    logger.info(f'[Celery] Batch cancel transfers: count={len(transfer_ids)}, user={request_user_id}')

    updated_count = 0
    skipped_count = 0
    errors = []

    for transfer_id in transfer_ids:
        try:
            with transaction.atomic():
                transfer = DocumentTransfer.objects.select_for_update().get(id=transfer_id)

                if transfer.tenant_id != request_tenant_id:
                    skipped_count += 1
                    continue

                FINAL_STATES = [
                    TransferStatus.COMPLETED.value,
                    TransferStatus.FAILED.value,
                    TransferStatus.CANCELED.value
                ]
                if transfer.status in FINAL_STATES:
                    skipped_count += 1
                    continue

                try:
                    current_enum = TransferStatus(transfer.status)
                    if not is_valid_status_transition(current_enum, TransferStatus.CANCELED):
                        logger.warning(f'[Celery] 非法状态转换: {transfer.status} -> CANCELED')
                        skipped_count += 1
                        continue
                except ValueError:
                    logger.error(f'[Celery] 未知状态: {transfer.status}')
                    skipped_count += 1
                    continue

                # 清理分片文件
                if transfer.file_hash and transfer.total_chunks > 0:
                    try:
                        ChunkCleanupService.cleanup_safe(transfer)
                    except Exception as cleanup_error:
                        logger.warning(f'[Celery] Chunk cleanup failed for transfer {transfer_id}: {cleanup_error}')

                transfer.status = TransferStatus.CANCELED.value
                transfer.error_message = '用户主动取消'
                transfer.save()
                updated_count += 1

        except DocumentTransfer.DoesNotExist:
            skipped_count += 1
        except Exception as e:
            logger.error(f'[Celery] Failed to cancel transfer {transfer_id}: {e}')
            errors.append({'id': transfer_id, 'error': str(e)})
            skipped_count += 1

    result = {
        'updated': updated_count,
        'skipped': skipped_count,
        'total': len(transfer_ids),
        'errors': errors
    }

    logger.info(f'[Celery] Batch cancel completed: {result}')
    return result

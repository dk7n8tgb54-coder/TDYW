# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
删除逻辑层 - 处理批量删除和降级逻辑
"""
import logging
from typing import List, Tuple
from django.db import transaction
from django.conf import settings

from .queries import TransferQueryService
from .classifiers import TransferClassifier
from .cleanup import ChunkCleanupService

logger = logging.getLogger(__name__)


class BatchDeleteService:
    """批量删除服务 - 处理批量删除和降级逻辑"""

    def __init__(self, batch_size: int = 10, tenant_id: str = None):
        self.batch_size = batch_size
        self.tenant_id = tenant_id
        self.tenant_filter = tenant_id if tenant_id else ''

    def execute(self, transfers: List) -> Tuple[int, List[dict]]:
        """
        执行批量删除

        Returns:
            Tuple[int, List[dict]]: (删除数量, 分片清理结果列表)
        """
        if not transfers:
            return 0, []

        deleted_count = 0
        chunk_results = []

        # 分批处理
        for i in range(0, len(transfers), self.batch_size):
            batch = transfers[i:i + self.batch_size]
            batch_deleted, batch_chunks = self._delete_batch_with_fallback(batch)
            deleted_count += batch_deleted
            chunk_results.extend(batch_chunks)

        return deleted_count, chunk_results

    def _delete_batch_with_fallback(self, batch: List) -> Tuple[int, List[dict]]:
        """
        批量删除，失败时降级为单条删除
        """
        batch_ids = [t.id for t in batch]

        try:
            with transaction.atomic():
                deleted_count, matched_count = TransferQueryService.delete_and_count(
                    batch_ids, self.tenant_id
                )

                if deleted_count != matched_count:
                    logger.warning(
                        f'[Celery] Batch delete mismatch: '
                        f'deleted={deleted_count}, matched={matched_count}'
                    )

            # 事务外清理分片
            chunk_results = [
                ChunkCleanupService.cleanup_safe(t) for t in batch
            ]

            return deleted_count, chunk_results

        except Exception as e:
            logger.error(f'[Celery] Batch delete error: {e}')
            return self._delete_individually(batch)

    def _delete_individually(self, transfers: List) -> Tuple[int, List[dict]]:
        """
        单条删除降级处理
        """
        deleted_count = 0
        chunk_results = []
        failed_ids = []

        for transfer in transfers:
            try:
                with transaction.atomic():
                    valid_transfer = TransferQueryService.get_deletable_by_id(
                        transfer.id, self.tenant_id
                    )

                    if valid_transfer:
                        valid_transfer.delete()
                        deleted_count += 1
                        logger.info(f'[Celery] Single delete success: {transfer.id}')
                        chunk_results.append(ChunkCleanupService.cleanup_safe(transfer))
                    else:
                        logger.warning(f'[Celery] Skip delete (no permission): {transfer.id}')

            except Exception as e:
                logger.error(f'[Celery] Single delete failed: {transfer.id}, error: {e}')
                failed_ids.append(transfer.id)

        # 调度异步重试
        if failed_ids:
            self._schedule_retry(failed_ids)

        return deleted_count, chunk_results

    def _schedule_retry(self, failed_ids: List[int]):
        """
        调度异步重试（预留接口）

        TODO: 可扩展为发送到Celery延迟队列
        注意：此处延迟导入避免循环导入
        """
        logger.info(f'[Celery] Scheduled retry for {len(failed_ids)} failed deletions')

        if getattr(settings, 'DOCUMENT_ENABLE_RETRY_QUEUE', False):
            try:
                # 延迟导入避免循环导入
                from apps.document.tasks import batch_delete_transfers
                batch_delete_transfers.apply_async(
                    args=[failed_ids, None, self.tenant_id],
                    countdown=getattr(settings, 'DOCUMENT_RETRY_DELAY', 60)
                )
            except Exception as e:
                logger.error(f'[Celery] Failed to schedule retry: {e}')

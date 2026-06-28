# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
Cleanup task for expired document transfer records.

DocumentTransfer is a short-lived task table. Completed, failed, and canceled
records should be kept briefly for UI feedback and troubleshooting, then
deleted on a schedule so tdyw_document_transfer cannot grow forever.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=1800, time_limit=3600, queue='document.cleanup')
def cleanup_expired_transfers(self, days=None, batch_size=None, dry_run=False):
    """
    Delete terminal transfer records older than the retention window.

    Args:
        days: Retention days. Defaults to DOCUMENT_TRANSFER_RETENTION_DAYS.
        batch_size: Maximum records to delete per batch.
        dry_run: Count matching rows without deleting.

    Returns:
        dict: Cleanup statistics.
    """
    from apps.document.constants import TransferStatus
    from apps.document.models import DocumentTransfer
    from apps.document.tasks.cleanup.orphan_transfers import _cleanup_transfer_chunk_dir

    days = days if days is not None else getattr(settings, 'DOCUMENT_TRANSFER_RETENTION_DAYS', 30)
    batch_size = batch_size or getattr(settings, 'DOCUMENT_TRANSFER_CLEANUP_BATCH_SIZE', 1000)
    cutoff_date = timezone.now() - timedelta(days=days)
    terminal_statuses = [
        TransferStatus.COMPLETED.value,
        TransferStatus.FAILED.value,
        TransferStatus.CANCELED.value,
    ]

    try:
        expired_query = DocumentTransfer.objects.filter(
            status__in=terminal_statuses,
            updated_at__lt=cutoff_date,
        ).order_by()

        matched_count = expired_query.count()
        deleted_count = 0
        chunk_dirs_cleaned = 0

        if dry_run:
            result = {
                'status': 'success',
                'dry_run': True,
                'matched_count': matched_count,
                'deleted_count': 0,
                'chunk_dirs_cleaned': 0,
                'retention_days': days,
                'cutoff_date': cutoff_date.isoformat(),
            }
            logger.info(f'[Celery] Cleanup expired transfers dry-run: matched={matched_count}')
            return result

        while True:
            transfer_ids = list(expired_query.values_list('id', flat=True)[:batch_size])
            if not transfer_ids:
                break

            transfers = list(
                DocumentTransfer.objects
                .filter(id__in=transfer_ids)
                .select_related('user')
                .order_by()
            )

            for transfer in transfers:
                if transfer.file_hash and _cleanup_transfer_chunk_dir(transfer):
                    chunk_dirs_cleaned += 1

            deleted, _ = DocumentTransfer.objects.filter(id__in=transfer_ids).delete()
            deleted_count += deleted

        result = {
            'status': 'success',
            'dry_run': False,
            'matched_count': matched_count,
            'deleted_count': deleted_count,
            'chunk_dirs_cleaned': chunk_dirs_cleaned,
            'retention_days': days,
            'batch_size': batch_size,
            'cutoff_date': cutoff_date.isoformat(),
        }

        logger.info(
            '[Celery] Cleanup expired transfers completed: '
            f'matched={matched_count}, deleted={deleted_count}, '
            f'chunk_dirs_cleaned={chunk_dirs_cleaned}'
        )
        return result

    except Exception as e:
        logger.error(f'[Celery] Cleanup expired transfers failed: {e}', exc_info=True)
        return {'status': 'error', 'message': str(e)}

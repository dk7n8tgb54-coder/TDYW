# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

"""
审计日志定时任务
- cleanup_old_audit_logs：归档清理超过保留期的审计日志
  审计日志会持续增长，为避免 audit_logs 表过大拖慢查询和占用磁盘，
  定时删除超过保留期的记录。默认保留 180 天。
"""

import logging
from datetime import datetime, timedelta
from celery import shared_task

logger = logging.getLogger(__name__)

# 保留期下限（天），防止误传过小的 days 导致批量误删近期审计数据
MIN_RETENTION_DAYS = 30
# 单次删除上限，避免一次性删除过多导致长事务和主从延迟
DELETE_BATCH_SIZE = 5000


@shared_task(
    bind=True,
    soft_time_limit=1800,
    time_limit=3600,
    queue='default',
    name='apps.logs.tasks.cleanup_old_audit_logs',
)
def cleanup_old_audit_logs(self, days=180, dry_run=False):
    """清理超过保留期的审计日志

    AuditLog.created_at 是 CharField(max_length=20)，存 "YYYY-MM-DD HH:MM:SS" 格式
    （human_datetime 生成）。该格式字典序与时间序一致，可直接用字符串比较。

    Args:
        days: 保留天数，默认 180 天。小于 MIN_RETENTION_DAYS 会被钳制，避免误删近期数据。
        dry_run: 仅统计待删除数量，不实际删除（用于预演和验证）。

    Returns:
        dict: 清理结果 {status, deleted_count, cutoff_date, dry_run, total_before}
    """
    from apps.logs.models import AuditLog
    from libs.utils import human_datetime

    # 钳制保留期，防止误传过小参数导致批量误删近期审计数据
    days = max(int(days), MIN_RETENTION_DAYS)

    cutoff_dt = datetime.now() - timedelta(days=days)
    cutoff_str = human_datetime(cutoff_dt)  # "YYYY-MM-DD HH:MM:SS"

    try:
        total_before = AuditLog.objects.count()
        stale_qs = AuditLog.objects.filter(created_at__lt=cutoff_str).order_by()

        if dry_run:
            stale_count = stale_qs.count()
            logger.info(
                f'[AUDIT] cleanup dry-run: days={days} cutoff={cutoff_str} '
                f'would_delete={stale_count} total_before={total_before}'
            )
            return {
                'status': 'success',
                'deleted_count': stale_count,
                'cutoff_date': cutoff_str,
                'dry_run': True,
                'total_before': total_before,
            }

        # 分批删除，避免单次大事务导致长锁和主从延迟
        deleted_total = 0
        while True:
            batch_ids = list(
                stale_qs.values_list('id', flat=True)[:DELETE_BATCH_SIZE]
            )
            if not batch_ids:
                break
            _, info = AuditLog.objects.filter(id__in=batch_ids).delete()
            # info 形如 {'apps.logs.AuditLog': N}
            batch_deleted = info.get('apps.logs.AuditLog', len(batch_ids))
            deleted_total += batch_deleted
            logger.info(
                f'[AUDIT] cleanup batch: batch_deleted={batch_deleted} '
                f'total_deleted={deleted_total}'
            )

        logger.info(
            f'[AUDIT] cleanup completed: days={days} cutoff={cutoff_str} '
            f'deleted={deleted_total} total_before={total_before}'
        )
        return {
            'status': 'success',
            'deleted_count': deleted_total,
            'cutoff_date': cutoff_str,
            'dry_run': False,
            'total_before': total_before,
        }

    except Exception as e:
        logger.error(f'[AUDIT] cleanup failed: {e}')
        return {'status': 'error', 'message': str(e)}

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

"""
审计日志定时任务
- cleanup_old_audit_logs：归档清理超过保留期的审计日志
  审计日志会持续增长，为避免 audit_logs 表过大拖慢查询和占用磁盘，
  定时删除超过保留期的记录。默认保留 90 天。
- verify_audit_hash_chain：定时验证审计日志哈希链完整性
  对每个租户最近的审计日志进行哈希链校验，发现篡改时发送告警。
"""

import logging
from datetime import datetime, timedelta
from django.utils import timezone
from celery import shared_task

logger = logging.getLogger(__name__)

# 保留期下限（天），防止误传过小的 days 导致批量误删近期审计数据
MIN_RETENTION_DAYS = 90
# 单次删除上限，避免一次性删除过多导致长事务和主从延迟
DELETE_BATCH_SIZE = 5000


@shared_task(
    bind=True,
    soft_time_limit=1800,
    time_limit=3600,
    queue='default',
    name='apps.logs.tasks.cleanup_old_audit_logs',
)
def cleanup_old_audit_logs(self, days=90, dry_run=False):
    """清理超过保留期的审计日志

    AuditLog.created_at 已迁移为 DateTimeField，直接用 datetime 比较即可。
    默认保留 90 天。

    Args:
        days: 保留天数，默认 90 天。小于 MIN_RETENTION_DAYS 会被钳制，避免误删近期数据。
        dry_run: 仅统计待删除数量，不实际删除（用于预演和验证）。

    Returns:
        dict: 清理结果 {status, deleted_count, cutoff_date, dry_run, total_before}
    """
    from apps.logs.models import AuditLog

    # 钳制保留期，防止误传过小参数导致批量误删近期审计数据
    days = max(int(days), MIN_RETENTION_DAYS)

    cutoff_dt = timezone.now() - timedelta(days=days)
    # 用于日志展示的截止时间字符串
    cutoff_str = cutoff_dt.strftime('%Y-%m-%d %H:%M:%S')

    try:
        total_before = AuditLog.objects.count()
        stale_qs = AuditLog.objects.filter(created_at__lt=cutoff_dt).order_by()

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

        # R11 修复：记录清理操作的审计日志，使删除操作可追溯
        if deleted_total > 0:
            try:
                from apps.logs.audit import log_celery_audit
                log_celery_audit(
                    action='delete',
                    target_type='audit',
                    target_name='审计日志定期清理',
                    detail={
                        '操作': '清理过期审计日志',
                        '删除数量': deleted_total,
                        '截止时间': cutoff_str,
                        '保留天数': days,
                        '清理前总量': total_before,
                    },
                    tenant_id='default',
                    is_success=True,
                )
            except Exception:
                logger.warning('[AUDIT] 记录清理审计日志失败', exc_info=True)

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


# 每个租户哈希链验证的最近记录数
HASH_CHAIN_VERIFY_LIMIT = 5000


@shared_task(
    bind=True,
    soft_time_limit=600,
    time_limit=900,
    queue='default',
    name='apps.logs.tasks.verify_audit_hash_chain',
)
def verify_audit_hash_chain(self):
    """定时验证审计日志哈希链完整性

    对每个租户最近的审计日志进行哈希链校验。
    verify_hash_chain 的 has_prev 设计会跳过首条记录的 prev_hash 检查，
    因此 cleanup 删除链首不会误报，但中间删除（篡改）能被正确检测。

    Returns:
        dict: 验证结果 {status, tenants_checked, total_errors, details}
    """
    from apps.logs.models import AuditLog
    from apps.logs.hash_chain import verify_hash_chain

    try:
        tenant_ids = AuditLog.objects.exclude(
            tenant_id=''
        ).values_list('tenant_id', flat=True).distinct()

        total_errors = 0
        details = []

        for tenant_id in tenant_ids:
            logs = AuditLog.objects.filter(
                tenant_id=tenant_id
            ).order_by('id')[:HASH_CHAIN_VERIFY_LIMIT]

            result = verify_hash_chain(logs)
            if not result['valid']:
                total_errors += len(result['errors'])
                details.append({
                    'tenant_id': tenant_id,
                    'checked': result['checked'],
                    'errors': result['errors'][:5],
                    'broken_at': result.get('broken_at'),
                })
                logger.error(
                    f'[AUDIT] hash chain broken: tenant={tenant_id} '
                    f'checked={result["checked"]} errors={len(result["errors"])}'
                )

        if total_errors > 0:
            # 发送告警
            try:
                from libs.alert import send_alert
                send_alert(
                    title='审计日志哈希链验证异常',
                    message=f'发现 {total_errors} 处哈希链断裂，涉及 '
                            f'{len(details)} 个租户。详情: {details[:3]}',
                    level='critical',
                )
            except Exception:
                logger.warning('[AUDIT] 哈希链告警发送失败', exc_info=True)

        logger.info(
            f'[AUDIT] hash chain verify completed: '
            f'tenants_checked={len(list(tenant_ids))} total_errors={total_errors}'
        )

        return {
            'status': 'success',
            'tenants_checked': len(details) if total_errors else 0,
            'total_errors': total_errors,
            'details': details,
        }

    except Exception as e:
        logger.error(f'[AUDIT] hash chain verify failed: {e}')
        return {'status': 'error', 'message': str(e)}

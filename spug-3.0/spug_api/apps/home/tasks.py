# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""公告模块 Celery 异步任务"""
import logging
from celery import shared_task

from django.utils import timezone
from apps.home.models import Announcement, STATUS_PUBLISHED, STATUS_EXPIRED
from apps.logs.audit import log_celery_audit

logger = logging.getLogger(__name__)


@shared_task
def sync_announcement_status():
    """将超过生效结束时间且仍为已发布的公告置为已过期

    接口已实时计算 computed_status 兜底，本任务仅用于保持管理端存储状态准确。
    """
    now = timezone.now()
    updated = Announcement.objects.filter(
        is_deleted=False,
        status=STATUS_PUBLISHED,
        effective_end_at__gt='',          # 排除长期有效（空）
        effective_end_at__lt=now,         # 已到失效时间
    ).update(status=STATUS_EXPIRED)
    if updated > 0:
        log_celery_audit('update', 'home',
                         target_name='公告自动过期',
                         detail={'expired_count': updated})
    return updated


# ==================== 系统监控任务 ====================

@shared_task(bind=True, max_retries=1, default_retry_delay=60)
def check_disk_space(self):
    """每 10 分钟检查磁盘空间，超阈值告警"""
    import os
    import shutil
    from django.conf import settings

    paths = [
        ('documents', os.path.join(settings.BASE_DIR, 'storage', 'documents')),
        ('chunks', os.path.join(settings.BASE_DIR, 'storage', 'document_chunks')),
        ('media', settings.MEDIA_ROOT),
    ]
    for name, path in paths:
        if not os.path.exists(path):
            continue
        try:
            usage = shutil.disk_usage(path)
            percent = (usage.used / usage.total) * 100
            if percent > 90:
                from libs.alert import send_alert
                free_gb = usage.free / (1024 ** 3)
                send_alert(
                    title=f'磁盘空间告警: {name}',
                    message=f'路径: {path}\n使用率: {percent:.1f}%\n可用空间: {free_gb:.1f}GB',
                    level='error' if percent > 95 else 'warning',
                    source='disk',
                    alert_key=f'disk:{name}',
                )
        except Exception as e:
            logger.error(f'[DISK] 检查 {name} 失败: {e}')


@shared_task(bind=True, max_retries=1, default_retry_delay=60)
def collect_db_metrics(self):
    """每 5 分钟采集数据库关键指标，超阈值告警"""
    from django.db import connection
    from django.core.cache import cache

    try:
        with connection.cursor() as cursor:
            # 连接数
            cursor.execute("SHOW STATUS LIKE 'Threads_connected'")
            connected = int(cursor.fetchone()[1])

            cursor.execute("SHOW VARIABLES LIKE 'max_connections'")
            max_conn = int(cursor.fetchone()[1])

            conn_pct = (connected / max_conn * 100) if max_conn else 0

            # InnoDB buffer pool 命中率
            cursor.execute("SHOW STATUS LIKE 'Innodb_buffer_pool_read_requests'")
            read_requests = int(cursor.fetchone()[1])
            cursor.execute("SHOW STATUS LIKE 'Innodb_buffer_pool_reads'")
            reads = int(cursor.fetchone()[1])
            hit_rate = ((read_requests - reads) / read_requests * 100) if read_requests else 100

            # 慢查询累计数
            cursor.execute("SHOW STATUS LIKE 'Slow_queries'")
            slow_queries = int(cursor.fetchone()[1])

        # 告警判断
        from libs.alert import send_alert

        if conn_pct > 80:
            send_alert(
                title='数据库连接数告警',
                message=f'连接数: {connected}/{max_conn} ({conn_pct:.1f}%)\n建议检查长连接或调大 max_connections',
                level='error' if conn_pct > 90 else 'warning',
                source='db',
                alert_key='db:connections',
            )

        if hit_rate < 95:
            send_alert(
                title='InnoDB 缓冲池命中率低',
                message=f'命中率: {hit_rate:.1f}%\n建议增大 innodb_buffer_pool_size',
                level='warning',
                source='db',
                alert_key='db:buffer_pool_hit_rate',
            )

        # 缓存指标供 API 查询
        cache.set('metrics:db', {
            'connections': connected,
            'max_connections': max_conn,
            'connection_percent': round(conn_pct, 1),
            'buffer_pool_hit_rate': round(hit_rate, 1),
            'slow_queries': slow_queries,
        }, 300)  # 5 分钟缓存

    except Exception as e:
        logger.error(f'[DB] 指标采集失败: {e}')

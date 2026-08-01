# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License
"""告警监控模块 Celery 异步任务"""
import io
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=1, default_retry_delay=60)
def check_disk_space(self):
    """每 10 分钟检查磁盘空间，超阈值告警 + 趋势预警"""
    import os
    import shutil
    from django.conf import settings

    # 趋势预警阈值：预测 72 小时内满盘则发预警
    TREND_WARN_HOURS = 72
    # 至少 12 个数据点（10min/次 * 12 = 2 小时）才做预测
    MIN_POINTS_FOR_PREDICTION = 12

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

            # 趋势预测：记录指标 + 预测满盘时间
            from libs.trend import record_metric, get_trend, linear_slope, predict_time_to_threshold
            record_metric(f'disk:{name}', usage.used)

            trend = get_trend(f'disk:{name}', 24)
            if len(trend) >= MIN_POINTS_FOR_PREDICTION:
                slope = linear_slope(trend)
                hours = predict_time_to_threshold(usage.used, usage.total, slope)
                # 快照未触发(<90%)但趋势预测 72h 内会满
                if hours is not None and hours < TREND_WARN_HOURS and percent < 90:
                    from libs.alert import send_alert
                    free_gb = usage.free / (1024 ** 3)
                    send_alert(
                        title=f'磁盘空间趋势预警: {name}',
                        message=(
                            f'路径: {path}\n'
                            f'当前使用率: {percent:.1f}%（可用 {free_gb:.1f}GB）\n'
                            f'按近 24h 增长速率，预计 {hours:.0f} 小时后满盘\n'
                            f'建议提前清理或扩容'
                        ),
                        level='warning',
                        source='disk',
                        alert_key=f'disk:{name}:trend',  # 与快照告警分开去重
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


@shared_task(bind=True, max_retries=0)
def run_data_quality_check(self):
    """每周一 06:00 运行数据质量巡检，发现问题发告警"""
    from django.core.management import call_command

    try:
        output = io.StringIO()
        call_command('data_quality_check', stdout=output, no_color=True)
        result = output.getvalue()
        logger.info(f'[DataQuality] 巡检完成:\n{result}')
    except Exception as e:
        logger.error(f'[DataQuality] 巡检失败: {e}', exc_info=True)
        from libs.alert import send_alert
        send_alert(
            title='数据质量巡检执行失败',
            message=str(e),
            level='error',
            source='data_quality_check',
        )


@shared_task(bind=True, max_retries=0)
def cleanup_old_alerts(self):
    """每天 03:00 清理旧告警，防止 alerts 表无限增长

    清理策略：
    - 已处理告警（resolved）超过 90 天 -> 物理删除
    - 活跃告警（active）超过 180 天 -> 物理删除（可能是遗留未处理）
    - AlertRead 记录随 Alert CASCADE 自动删除
    """
    from datetime import timedelta
    from django.utils import timezone
    from apps.alert.models import Alert

    RESOLVED_RETENTION_DAYS = 90
    ACTIVE_RETENTION_DAYS = 180
    BATCH_SIZE = 1000
    MAX_ITERATIONS = 50  # 安全阀：最多删 5 万条

    try:
        now = timezone.now()
        resolved_cutoff = now - timedelta(days=RESOLVED_RETENTION_DAYS)
        active_cutoff = now - timedelta(days=ACTIVE_RETENTION_DAYS)

        total_deleted = 0
        iterations = 0

        # 先删已处理的旧告警
        while iterations < MAX_ITERATIONS:
            batch_ids = list(
                Alert.objects.filter(
                    status=Alert.STATUS_RESOLVED,
                    resolved_at__lt=resolved_cutoff,
                ).values_list('id', flat=True)[:BATCH_SIZE]
            )
            if not batch_ids:
                break
            # AlertRead FK CASCADE 自动删除
            Alert.objects.filter(id__in=batch_ids).delete()
            total_deleted += len(batch_ids)
            iterations += 1

        # 再删遗留的活跃旧告警
        while iterations < MAX_ITERATIONS * 2:
            batch_ids = list(
                Alert.objects.filter(
                    status=Alert.STATUS_ACTIVE,
                    created_at__lt=active_cutoff,
                ).values_list('id', flat=True)[:BATCH_SIZE]
            )
            if not batch_ids:
                break
            Alert.objects.filter(id__in=batch_ids).delete()
            total_deleted += len(batch_ids)
            iterations += 1

        if total_deleted > 0:
            logger.info(f'[CLEANUP] 清理旧告警 {total_deleted} 条')

    except Exception as e:
        logger.error(f'[CLEANUP] 清理旧告警失败: {e}', exc_info=True)

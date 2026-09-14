# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License
"""告警监控模块 Celery 异步任务"""
import io
import logging
import os
import shutil
import stat
import subprocess
from datetime import timedelta
from celery import shared_task

logger = logging.getLogger(__name__)

# check_disk_space 任务互斥锁：上一轮目录扫描未完成时不重复启动。
# TTL 兜底：持锁进程异常退出后锁自动过期，避免永久卡死后续采集。
DISK_CHECK_LOCK_KEY = 'lock:alert:check-disk-space'
DISK_CHECK_LOCK_TTL = 1800


def _walk_directory_bytes(path):
    """du 命令不存在时（如 Windows 开发环境）的纯 Python 兜底统计。

    与 du -s -B1 -x 语义对齐：不跟随符号链接、不跨文件系统、
    统计磁盘块占用而非表观大小。
    """
    top_dev = os.stat(path).st_dev
    total = 0
    for root, dirs, files in os.walk(path):
        # 跳过其他文件系统上的挂载点（du -x 语义）
        dirs[:] = [
            d for d in dirs
            if os.stat(os.path.join(root, d)).st_dev == top_dev
        ]
        for name in files:
            file_path = os.path.join(root, name)
            try:
                st = os.lstat(file_path)  # lstat 不跟随符号链接
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_dev != top_dev:
                continue
            blocks = getattr(st, 'st_blocks', None)
            total += blocks * 512 if blocks is not None else st.st_size
    return total


def _measure_directory_bytes(path, timeout):
    """统计目录自身实际占用字节（生产 Linux 优先 du -s -B1 -x）。

    - subprocess 参数数组调用，禁止 shell=True；
    - du 不跟随符号链接，-x 不跨越嵌套文件系统；
    - du 超时或非零退出抛异常，由调用方记录日志并跳过本轮写入，不得写 0。
    """
    try:
        proc = subprocess.run(
            ['du', '-s', '-B1', '-x', path],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return _walk_directory_bytes(path)
    if proc.returncode != 0:
        raise RuntimeError(f'du 退出码 {proc.returncode}: {(proc.stderr or "").strip()[:200]}')
    return int(proc.stdout.split()[0])


@shared_task(bind=True, max_retries=1, default_retry_delay=60)
def check_disk_space(self):
    """每 30 分钟采集存储目录实际占用趋势 + 文件系统满盘告警

    两类指标口径严格分离：
    - 目录占用（公开趋势曲线）：du 统计目录自身实际字节，公开指标键
      disk:documents / disk:chunks / disk:media；disk:total 为同一轮三类总和，
      仅在全部目录采集成功时写入，避免部分失败时形成虚假下降。
    - 文件系统容量（满盘快照告警 + 72h 趋势预警）：仍用 shutil.disk_usage，
      历史记录在内部键 fs-usage:<name>，不对外暴露，禁止与目录占用量混算。
    """
    from django.conf import settings
    from django.core.cache import cache
    from libs.trend import record_metric, get_trend, linear_slope, predict_time_to_threshold

    # 趋势预警阈值：预测 72 小时内满盘则发预警
    TREND_WARN_HOURS = 72
    # 至少 12 个数据点（30min/次 * 12 = 6 小时）才做预测
    MIN_POINTS_FOR_PREDICTION = 12

    storage_dirs = list(getattr(settings, 'ALERT_STORAGE_DIRS', []))
    du_timeout = int(getattr(settings, 'ALERT_DU_TIMEOUT_SECONDS', 300))

    try:
        lock_acquired = cache.add(DISK_CHECK_LOCK_KEY, '1', DISK_CHECK_LOCK_TTL)
    except Exception as e:
        logger.warning(f'[DISK] 任务锁检查失败（Redis 不可用），本轮降级为无锁执行: {e}')
        lock_acquired = True
    if not lock_acquired:
        logger.warning('[DISK] 上一轮磁盘检查尚未完成，跳过本轮采集')
        return {'skipped': True}

    result = {'directories': {}, 'failures': [], 'total': None}
    try:
        # ---- 第一部分：目录实际占用（公开趋势曲线） ----
        for name, path in storage_dirs:
            if not os.path.exists(path):
                logger.error(f'[DISK] 存储目录不存在，本轮跳过该目录: {name} -> {path}')
                result['failures'].append(name)
                continue
            try:
                size = _measure_directory_bytes(path, du_timeout)
            except Exception as e:
                logger.error(f'[DISK] 目录占用统计失败，本轮跳过该目录: {name} ({path}): {e}')
                result['failures'].append(name)
                continue
            result['directories'][name] = size
            record_metric(f'disk:{name}', size)

        # 任一目录失败则本轮不写 total，避免曲线出现虚假下降
        if storage_dirs and not result['failures']:
            total = sum(result['directories'].values())
            record_metric('disk:total', total)
            result['total'] = total

        # ---- 第二部分：文件系统容量告警（满盘快照 + 趋势预警） ----
        for name, path in storage_dirs:
            try:
                usage = shutil.disk_usage(path)
            except Exception as e:
                logger.error(f'[DISK] 文件系统容量检查失败: {name} ({path}): {e}')
                continue
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

            # 满盘预测使用内部文件系统指标（fs-usage:*），与公开目录曲线分离
            record_metric(f'fs-usage:{name}', usage.used)
            trend = get_trend(f'fs-usage:{name}', 24)
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
        return result
    finally:
        try:
            cache.delete(DISK_CHECK_LOCK_KEY)
        except Exception:
            pass


@shared_task(bind=True, max_retries=1, default_retry_delay=60)
def collect_db_metrics(self):
    """每 5 分钟采集数据库关键指标，超阈值告警"""
    from django.db import connection
    from django.utils import timezone
    from apps.alert.models import DbMetricSnapshot
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
        # 以带时间快照供运行指标窗口聚合，保留最近 15 分钟以上
        DbMetricSnapshot.objects.create(
            captured_at=timezone.now(),
            threads_connected=connected,
            slow_queries=slow_queries,
        )

    except Exception as e:
        logger.error(f'[DB] 指标采集失败: {e}')


def record_probe_sample(timestamp, success, http_status=None, duration_ms=0, error_type=''):
    """保存外部探活结果，并在连续失败三次/恢复时生成事件告警。"""
    from django.utils.dateparse import parse_datetime
    from django.utils import timezone
    from apps.alert.models import HealthProbeSample
    from apps.alert.metrics import to_storage_dt

    if isinstance(timestamp, str):
        # 探活日志时间戳为 UTC ISO8601；缺 offset 的按 UTC 解释
        timestamp = to_storage_dt(parse_datetime(timestamp), naive_is_utc=True)
    timestamp = timestamp or timezone.now()
    timestamp = to_storage_dt(timestamp)
    sample, created = HealthProbeSample.objects.get_or_create(
        timestamp=timestamp,
        defaults={
            'success': bool(success),
            'http_status': http_status,
            'duration_ms': max(0, int(duration_ms or 0)),
            'error_type': str(error_type or '')[:80],
        },
    )
    # flush_run_metrics 会重复扫描完整探活日志。历史样本已存在时不得再次
    # 触发“不可用/已恢复”事件，否则同一次恢复会随每轮聚合重复告警。
    if not created:
        return sample
    recent = list(HealthProbeSample.objects.filter(timestamp__lte=timestamp).order_by('-timestamp')[:4])
    failures = 0
    for item in recent:
        if item.success:
            break
        failures += 1
    from libs.alert import send_alert
    if failures >= 3 and not sample.success:
        send_alert(
            title='平台探活不可用',
            message=f'连续 {failures} 次探活失败，最近错误: {sample.error_type or sample.http_status or "未知"}',
            level='error', source='health_probe', alert_key='health_probe:unavailable',
        )
    elif sample.success and len(recent) > 1 and not recent[1].success:
        send_alert(
            title='平台探活已恢复', message='外部探活恢复成功', level='info',
            source='health_probe', alert_key=f'health_probe:recovered:{timestamp.isoformat()}',
        )
    return sample


@shared_task(bind=True, max_retries=0)
def flush_run_metrics(self, bucket_start=None):
    """聚合完整五分钟窗口；从最后窗口补算，重复执行使用唯一键幂等。"""
    from datetime import datetime
    from django.utils import timezone
    from apps.alert.metrics import aggregate_window, floor_window, WINDOW_SECONDS
    from apps.alert.models import RunMetric

    try:
        from apps.alert.metrics import ingest_probe_log
        ingest_probe_log()
        if bucket_start:
            if isinstance(bucket_start, str):
                bucket_start = datetime.fromisoformat(bucket_start.replace('Z', '+00:00'))
            buckets = [floor_window(bucket_start)]
        else:
            latest = floor_window(timezone.now()) - timedelta(seconds=WINDOW_SECONDS)
            last = RunMetric.objects.order_by('-bucket_start').values_list('bucket_start', flat=True).first()
            if last and last < latest:
                buckets = []
                current = last + timedelta(seconds=WINDOW_SECONDS)
                while current <= latest:
                    buckets.append(current)
                    current += timedelta(seconds=WINDOW_SECONDS)
            else:
                buckets = [latest]
        for bucket in buckets:
            aggregate_window(bucket)
        return len(buckets)
    except Exception as exc:
        logger.error('[RUN_METRICS] 聚合失败: %s', exc, exc_info=True)
        return 0


@shared_task(bind=True, max_retries=0)
def cleanup_run_metrics(self):
    """每天清理默认 30 天前运行指标及探活原始样本。"""
    from datetime import timedelta
    from django.utils import timezone
    from django.conf import settings
    from apps.alert.metrics import to_storage_dt
    from apps.alert.models import RunMetric, HealthProbeSample, DbMetricSnapshot

    retention = max(7, min(int(getattr(settings, 'RUN_METRICS_RETENTION_DAYS', 30)), 90))
    cutoff = to_storage_dt(timezone.now() - timedelta(days=retention))
    RunMetric.objects.filter(bucket_start__lt=cutoff).delete()
    HealthProbeSample.objects.filter(timestamp__lt=cutoff).delete()
    DbMetricSnapshot.objects.filter(captured_at__lt=cutoff).delete()


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

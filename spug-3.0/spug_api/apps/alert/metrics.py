"""运行指标采集与五分钟窗口聚合。所有采集失败均 fail-open。"""
import json
import logging
import os
from datetime import datetime, timezone as dt_timezone
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from .models import Alert, DbMetricSnapshot, HealthProbeSample, RunMetric

logger = logging.getLogger(__name__)
WINDOW_SECONDS = 300
SLOW_MS = 1000


def ingest_probe_log():
    """读取容器外探活 JSONL；文件不可读时保持现有数据并标记未知。"""
    path = Path(getattr(settings, 'RUN_METRICS_PROBE_LOG', '/var/log/tdyw/health-probe.jsonl'))
    if not path.exists():
        return 0
    created = 0
    try:
        with path.open('r', encoding='utf-8', errors='replace') as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                    timestamp = datetime.fromisoformat(str(item['timestamp']).replace('Z', '+00:00'))
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=dt_timezone.utc)
                    from .tasks import record_probe_sample
                    before = HealthProbeSample.objects.filter(timestamp=timestamp).exists()
                    record_probe_sample(timestamp, item.get('success'), item.get('http_status'), item.get('duration_ms'), item.get('error_type'))
                    was_created = not before
                    created += was_created
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue
    except OSError:
        logger.warning('[RUN_METRICS] probe log unavailable: %s', path)
    return created


def floor_window(value):
    value = value.astimezone(dt_timezone.utc)
    return value.replace(second=(value.second // WINDOW_SECONDS) * WINDOW_SECONDS, microsecond=0)


def record_business_error():
    """低频记录 HTTP 200 + error；Redis 故障不能影响业务响应。"""
    try:
        now = floor_window(timezone.now())
        cache_key = f'run-metrics:business:{now.isoformat()}'
        cache.add(cache_key, 0, 900)
        cache.incr(cache_key)
        cache.touch(cache_key, 900)
    except Exception:
        logger.debug('[RUN_METRICS] business error counter unavailable', exc_info=True)


def _log_paths():
    configured = getattr(settings, 'RUN_METRICS_NGINX_LOG', '/var/log/nginx/access.log')
    if not configured:
        return []
    path = Path(configured)
    paths = [path]
    paths.extend(sorted(path.parent.glob(f'{path.name}.*')))
    return [item for item in paths if item.exists() and item.is_file()]


def _iter_access_records(start, end):
    for path in _log_paths():
        try:
            with path.open('r', encoding='utf-8', errors='replace') as stream:
                for line in stream:
                    try:
                        item = json.loads(line)
                        raw_ts = item.get('timestamp')
                        ts = datetime.fromisoformat(raw_ts.replace('Z', '+00:00'))
                        if timezone.is_naive(ts):
                            ts = ts.replace(tzinfo=dt_timezone.utc)
                        if start <= ts < end:
                            yield item, ts
                    except (ValueError, TypeError, json.JSONDecodeError, AttributeError):
                        continue
        except OSError:
            logger.warning('[RUN_METRICS] access log unavailable: %s', path)


def _business_count(bucket):
    try:
        return int(cache.get(f'run-metrics:business:{bucket.isoformat()}') or 0)
    except Exception:
        return 0


def aggregate_window(bucket):
    end = bucket + timedelta(seconds=WINDOW_SECONDS)
    values = {
        'request_count': 0, 'api_request_count': 0, 'transfer_request_count': 0,
        'health_check_count': 0, 'websocket_handshake_count': 0,
        'client_error_count': 0, 'app_server_error_count': 0,
        'gateway_error_count': 0, 'business_error_count': _business_count(bucket),
        'slow_count': 0, 'total_ms': 0, 'max_ms': 0,
        'latency_le_200': 0, 'latency_le_500': 0, 'latency_le_1000': 0,
        'latency_le_3000': 0, 'latency_gt_3000': 0,
    }
    for item, _ in _iter_access_records(bucket, end):
        uri = str(item.get('uri') or '')
        if uri.startswith('/healthz') or uri == '/api/document/health/':
            values['health_check_count'] += 1
            continue
        category = item.get('category') or ('websocket' if uri.startswith('/api/ws/') else 'api')
        if category == 'websocket':
            values['websocket_handshake_count'] += 1
            continue
        if category == 'transfer':
            values['transfer_request_count'] += 1
        else:
            values['api_request_count'] += 1
        values['request_count'] += 1
        try:
            status = int(item.get('status'))
        except (TypeError, ValueError):
            status = 0
        try:
            duration = max(0, int(round(float(item.get('request_time') or 0) * 1000)))
        except (TypeError, ValueError):
            duration = 0
        if 400 <= status < 500:
            values['client_error_count'] += 1
        if status in (502, 503, 504):
            values['gateway_error_count'] += 1
        elif 500 <= status < 600:
            values['app_server_error_count'] += 1
        values['total_ms'] += duration
        values['max_ms'] = max(values['max_ms'], duration)
        if duration <= 200:
            values['latency_le_200'] += 1
        elif duration <= 500:
            values['latency_le_500'] += 1
        elif duration <= 1000:
            values['latency_le_1000'] += 1
        elif duration <= 3000:
            values['latency_le_3000'] += 1
        else:
            values['latency_gt_3000'] += 1
        if duration > SLOW_MS:
            values['slow_count'] += 1

    probes = list(HealthProbeSample.objects.filter(timestamp__gte=bucket, timestamp__lt=end))
    values['probe_count'] = len(probes)
    values['probe_success_count'] = sum(1 for item in probes if item.success)
    values['probe_total_ms'] = sum(item.duration_ms for item in probes)
    values['probe_max_ms'] = max((item.duration_ms for item in probes), default=0)
    snapshot = DbMetricSnapshot.objects.filter(captured_at__gte=bucket, captured_at__lt=end).order_by('-captured_at').first()
    values['db_threads_connected'] = snapshot.threads_connected if snapshot else None
    values['db_slow_queries'] = snapshot.slow_queries if snapshot else None
    celery_failures = Alert.objects.filter(
        source='celery', created_at__gte=bucket, created_at__lt=end
    ).count()
    values['celery_fail_count'] = celery_failures
    RunMetric.objects.update_or_create(bucket_start=bucket, defaults=values)
    return values


def health_state(metric):
    if not metric or metric.get('probe_count', 0) == 0:
        return 'unknown'
    if metric.get('probe_success_count', 0) == 0:
        return 'unavailable'
    errors = metric.get('app_server_error_count', 0) + metric.get('gateway_error_count', 0)
    if errors or metric.get('slow_count', 0):
        return 'degraded'
    return 'healthy'

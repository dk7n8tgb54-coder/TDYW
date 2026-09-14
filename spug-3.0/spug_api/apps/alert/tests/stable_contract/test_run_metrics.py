import json
import os
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.alert.metrics import (
    aggregate_window,
    floor_window,
    health_state,
    ingest_probe_log,
    to_local_naive,
    to_storage_dt,
)
from apps.alert.models import HealthProbeSample, RunMetric
from apps.alert.tasks import flush_run_metrics, record_probe_sample
from apps.utils.test_helpers import make_client, make_user, setup_test_env

UTC = dt_timezone.utc


def _disable_log_sources():
    """隔离容器内真实日志源，保证聚合只消费测试构造的数据。"""
    ctx = override_settings(
        RUN_METRICS_NGINX_LOG='',
        RUN_METRICS_PROBE_LOG='/nonexistent/health-probe.jsonl',
    )
    ctx.enable()
    return ctx


class RunMetricsContractTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False)
        self.addCleanup(lambda: os.path.exists(self.tmp.name) and os.unlink(self.tmp.name))
        self.bucket = timezone.now().replace(second=0, microsecond=0)
        self.bucket -= timedelta(minutes=self.bucket.minute % 5)

    def write(self, **values):
        self.tmp.write(json.dumps(values) + '\n')
        self.tmp.flush()

    @override_settings(RUN_METRICS_NGINX_LOG='')
    def test_window_upsert_and_unknown_without_probe(self):
        aggregate_window(self.bucket)
        aggregate_window(self.bucket)
        metric = RunMetric.objects.get(bucket_start=self.bucket)
        self.assertEqual(metric.request_count, 0)
        self.assertEqual(metric.probe_count, 0)

    @override_settings(RUN_METRICS_NGINX_LOG='')
    def test_gateway_error_and_probe_failure_are_aggregated(self):
        HealthProbeSample.objects.create(timestamp=self.bucket + timedelta(minutes=1), success=False, http_status=503)
        HealthProbeSample.objects.create(timestamp=self.bucket + timedelta(minutes=2), success=False, http_status=503)
        HealthProbeSample.objects.create(timestamp=self.bucket + timedelta(minutes=3), success=False, http_status=503)
        metric = aggregate_window(self.bucket)
        self.assertEqual(metric['probe_count'], 3)
        self.assertEqual(metric['probe_success_count'], 0)


class TimeTypeContractTest(TestCase):
    """时间类型契约：ORM 使用的 datetime 必须与 USE_TZ 配置一致。"""

    def test_use_tz_false_is_the_deployment_config(self):
        # 回归基线：生产/测试环境均为 USE_TZ=False + Asia/Shanghai
        self.assertFalse(settings.USE_TZ)
        self.assertEqual(settings.TIME_ZONE, 'Asia/Shanghai')

    def test_floor_window_returns_orm_safe_type(self):
        bucket = floor_window(timezone.now())
        self.assertTrue(timezone.is_naive(bucket))
        self.assertEqual(bucket.second, 0)
        self.assertEqual(bucket.microsecond, 0)

    def test_floor_window_instant_preserving_across_utc_input(self):
        aware_utc = datetime(2026, 9, 13, 10, 23, 17, tzinfo=UTC)
        bucket = floor_window(aware_utc)
        self.assertTrue(timezone.is_naive(bucket))
        self.assertEqual(bucket, datetime(2026, 9, 13, 18, 23))

    def test_to_storage_dt_converts_utc_to_local_naive(self):
        aware_utc = datetime(2026, 9, 13, 6, 0, tzinfo=UTC)
        self.assertEqual(to_storage_dt(aware_utc), datetime(2026, 9, 13, 14, 0))
        # naive 默认按本地时间解释（timezone.now() 语义）
        self.assertEqual(to_storage_dt(datetime(2026, 9, 13, 14, 0)), datetime(2026, 9, 13, 14, 0))
        # 日志中的 naive 时间戳按约定解释为 UTC
        self.assertEqual(
            to_storage_dt(datetime(2026, 9, 13, 6, 0), naive_is_utc=True),
            datetime(2026, 9, 13, 14, 0),
        )

    def test_to_storage_dt_keeps_aware_under_use_tz_true(self):
        with override_settings(USE_TZ=True):
            self.assertTrue(timezone.is_aware(to_storage_dt(datetime(2026, 9, 13, 6, 0, tzinfo=UTC))))
            self.assertTrue(timezone.is_aware(to_storage_dt(datetime(2026, 9, 13, 14, 0))))

    def test_to_local_naive_passes_naive_through(self):
        naive_local = datetime(2026, 9, 13, 18, 20)
        self.assertEqual(to_local_naive(naive_local), naive_local)


class FlushRunMetricsTest(TestCase):
    """USE_TZ=False 下聚合任务必须真实写入 RunMetric（回归：aware datetime 被 MySQL 拒绝）。"""

    def setUp(self):
        self.assertFalse(settings.USE_TZ)
        self._ctx = _disable_log_sources()
        self.addCleanup(self._ctx.disable)

    def test_flush_creates_runmetric_rows(self):
        created = flush_run_metrics()
        self.assertGreaterEqual(created, 1)
        row = RunMetric.objects.order_by('-bucket_start').first()
        self.assertIsNotNone(row)
        self.assertTrue(timezone.is_naive(row.bucket_start))

    def test_flush_is_idempotent_on_same_window(self):
        bucket = floor_window(timezone.now())
        flush_run_metrics(bucket_start=bucket.isoformat())
        flush_run_metrics(bucket_start=bucket.isoformat())
        self.assertEqual(RunMetric.objects.count(), 1)

    def test_flush_backfills_windows_from_last_bucket(self):
        anchor = floor_window(timezone.now()) - timedelta(minutes=15)
        RunMetric.objects.create(bucket_start=anchor)
        flush_run_metrics()
        buckets = list(RunMetric.objects.order_by('bucket_start').values_list('bucket_start', flat=True))
        self.assertEqual(buckets[0], anchor)
        # 从最后窗口起按 5 分钟步长连续补算到最新窗口，中间无缺口
        for earlier, later in zip(buckets, buckets[1:]):
            self.assertEqual(later - earlier, timedelta(seconds=300))

    def test_flush_with_explicit_bucket_start(self):
        bucket = floor_window(timezone.now()) - timedelta(minutes=5)
        created = flush_run_metrics(bucket_start=bucket.isoformat())
        self.assertEqual(created, 1)
        self.assertTrue(RunMetric.objects.filter(bucket_start=bucket).exists())


class ProbeLogIngestTest(TestCase):
    """探活日志（UTC ISO8601）必须正确落入 HealthProbeSample。"""

    def setUp(self):
        self.assertFalse(settings.USE_TZ)
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
        tmp.close()
        self.tmp_path = tmp.name
        self.addCleanup(lambda: os.path.exists(self.tmp_path) and os.unlink(self.tmp_path))
        ctx = override_settings(RUN_METRICS_PROBE_LOG=self.tmp_path)
        ctx.enable()
        self.addCleanup(ctx.disable)

    def _write(self, payload):
        with open(self.tmp_path, 'a', encoding='utf-8') as stream:
            stream.write((payload if isinstance(payload, str) else json.dumps(payload)) + '\n')

    def test_utc_iso8601_lines_ingest_as_local_naive(self):
        self._write({'timestamp': '2026-09-13T06:00:00Z', 'success': True, 'http_status': 200, 'duration_ms': 120, 'error_type': ''})
        self._write({'timestamp': '2026-09-13T06:00:30+00:00', 'success': False, 'http_status': 503, 'duration_ms': 8000, 'error_type': 'http_status'})
        self._write({'timestamp': '2026-09-13T06:01:00', 'success': True, 'http_status': 200, 'duration_ms': 90})
        self._write('not-json')
        created = ingest_probe_log()
        self.assertEqual(created, 3)
        self.assertEqual(HealthProbeSample.objects.count(), 3)
        first = HealthProbeSample.objects.get(timestamp=datetime(2026, 9, 13, 14, 0))
        self.assertTrue(first.success)
        self.assertEqual(first.duration_ms, 120)
        failed = HealthProbeSample.objects.get(timestamp=datetime(2026, 9, 13, 14, 0, 30))
        self.assertFalse(failed.success)
        self.assertEqual(failed.error_type, 'http_status')
        naive_line = HealthProbeSample.objects.get(timestamp=datetime(2026, 9, 13, 14, 1))
        self.assertTrue(naive_line.success)
        # 重复读取同一文件必须幂等
        self.assertEqual(ingest_probe_log(), 0)
        self.assertEqual(HealthProbeSample.objects.count(), 3)

    def test_record_probe_sample_accepts_utc_string(self):
        sample = record_probe_sample('2026-09-13T06:30:00Z', True, http_status=200, duration_ms=50)
        self.assertTrue(timezone.is_naive(sample.timestamp))
        self.assertEqual(sample.timestamp, datetime(2026, 9, 13, 14, 30))

    def test_record_probe_sample_defaults_to_config_now(self):
        sample = record_probe_sample(None, True)
        self.assertTrue(timezone.is_naive(sample.timestamp))
        self.assertLessEqual(sample.timestamp, timezone.now())

    @patch('libs.alert.send_alert')
    def test_reingesting_recovery_sample_does_not_repeat_alert(self, send_alert):
        failed_at = datetime(2026, 9, 13, 14, 0)
        recovered_at = failed_at + timedelta(minutes=1)
        record_probe_sample(failed_at, False, http_status=503)
        record_probe_sample(recovered_at, True, http_status=200)
        record_probe_sample(recovered_at, True, http_status=200)

        recovery_calls = [
            call for call in send_alert.call_args_list
            if call.kwargs.get('title') == '平台探活已恢复'
        ]
        self.assertEqual(len(recovery_calls), 1)


class HealthStateSemanticsTest(TestCase):
    """无数据=unknown；连续失败=unavailable；有成功探活且异常=degraded；正常=healthy。"""

    def test_no_probe_samples_is_unknown(self):
        self.assertEqual(health_state(None), 'unknown')
        self.assertEqual(health_state({'probe_count': 0, 'probe_success_count': 0}), 'unknown')

    def test_all_probe_failures_is_unavailable(self):
        self.assertEqual(health_state({'probe_count': 3, 'probe_success_count': 0}), 'unavailable')

    def test_success_with_errors_or_slow_is_degraded(self):
        base = {'probe_count': 2, 'probe_success_count': 2, 'slow_count': 0}
        self.assertEqual(health_state({**base, 'app_server_error_count': 1}), 'degraded')
        self.assertEqual(health_state({**base, 'gateway_error_count': 2}), 'degraded')
        self.assertEqual(health_state({**base, 'slow_count': 1}), 'degraded')

    def test_success_without_errors_is_healthy(self):
        self.assertEqual(health_state({'probe_count': 2, 'probe_success_count': 2, 'slow_count': 0}), 'healthy')


class AggregateWindowContentTest(TestCase):
    """聚合内容：访问日志（本地偏移 ISO8601）+ 探活样本混合场景。"""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False)
        tmp.close()
        self.tmp_path = tmp.name
        self.addCleanup(lambda: os.path.exists(self.tmp_path) and os.unlink(self.tmp_path))
        ctx = override_settings(RUN_METRICS_NGINX_LOG=self.tmp_path)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.bucket = timezone.now().replace(second=0, microsecond=0)

    def _write_line(self, **item):
        with open(self.tmp_path, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(item) + '\n')

    def _log_timestamp(self, local_naive, offset_seconds=0):
        # 模拟 nginx $time_iso8601：本地时区偏移的 ISO8601
        value = timezone.make_aware(local_naive + timedelta(seconds=offset_seconds))
        return value.isoformat()

    def test_slow_and_gateway_errors_are_degraded(self):
        local_ts = self.bucket + timedelta(minutes=1)
        # 状态语义：有成功探活样本时，错误/慢请求才体现为 degraded
        HealthProbeSample.objects.create(timestamp=self.bucket + timedelta(seconds=30), success=True, http_status=200, duration_ms=80)
        self._write_line(timestamp=self._log_timestamp(local_ts), uri='/api/app/x/', status=502, request_time=0.1, category='api')
        self._write_line(timestamp=self._log_timestamp(local_ts, 10), uri='/api/app/y/', status=200, request_time=1.8, category='api')
        values = aggregate_window(self.bucket)
        self.assertEqual(values['api_request_count'], 2)
        self.assertEqual(values['gateway_error_count'], 1)
        self.assertEqual(values['slow_count'], 1)
        self.assertEqual(values['max_ms'], 1800)
        self.assertEqual(health_state(values), 'degraded')

    def test_slow_and_errors_without_probes_stay_unknown(self):
        # 无探活样本时不得把异常流量误判为 degraded/healthy
        local_ts = self.bucket + timedelta(minutes=1)
        self._write_line(timestamp=self._log_timestamp(local_ts), uri='/api/app/x/', status=502, request_time=2.0, category='api')
        values = aggregate_window(self.bucket)
        self.assertEqual(values['gateway_error_count'], 1)
        self.assertEqual(values['slow_count'], 1)
        self.assertEqual(health_state(values), 'unknown')

    def test_mixed_probe_results_and_health_states(self):
        HealthProbeSample.objects.create(timestamp=self.bucket + timedelta(minutes=1), success=False, http_status=503)
        HealthProbeSample.objects.create(timestamp=self.bucket + timedelta(minutes=2), success=True, http_status=200, duration_ms=120)
        values = aggregate_window(self.bucket)
        self.assertEqual(values['probe_count'], 2)
        self.assertEqual(values['probe_success_count'], 1)
        self.assertGreater(values['probe_max_ms'], 0)
        self.assertEqual(health_state(values), 'healthy')

    def test_window_without_probes_stays_unknown(self):
        values = aggregate_window(self.bucket)
        self.assertEqual(values['probe_count'], 0)
        self.assertEqual(health_state(values), 'unknown')


class RunMetricViewContractTest(TestCase):
    """RunMetricView / RunMetricSummaryView 返回结构契约。"""

    def setUp(self):
        setup_test_env(self)
        self.assertFalse(settings.USE_TZ)
        self.user = make_user('runmetric_view', ['system.alert.view'])
        self.client = make_client(self.user)
        self._ctx = _disable_log_sources()
        self.addCleanup(self._ctx.disable)

    def test_empty_database_returns_unknown(self):
        trend = self.client.get('/alert/run-metrics/').json()['data']
        self.assertFalse(trend.get('error'))
        self.assertEqual(trend['state'], 'unknown')
        self.assertEqual(trend['items'], [])
        summary = self.client.get('/alert/run-metrics/summary/').json()['data']
        self.assertFalse(summary.get('error'))
        self.assertEqual(summary['state'], 'unknown')
        self.assertEqual(summary['items'], [])

    def test_trend_and_summary_structure_with_probe_data(self):
        bucket = floor_window(timezone.now())
        HealthProbeSample.objects.create(
            timestamp=bucket + timedelta(minutes=1), success=True, http_status=200, duration_ms=100,
        )
        self.assertEqual(flush_run_metrics(bucket_start=bucket.isoformat()), 1)
        trend = self.client.get('/alert/run-metrics/').json()['data']
        self.assertEqual(trend['hours'], 48)
        self.assertTrue(trend['items'])
        item = trend['items'][-1]
        for key in ('bucket_start', 'request_count', 'probe_count', 'probe_success_count',
                    'probe_success_rate', 'average_ms', 'p95_ms', 'state'):
            self.assertIn(key, item)
        self.assertEqual(item['probe_count'], 1)
        self.assertEqual(item['probe_success_rate'], 1.0)
        self.assertEqual(item['state'], 'healthy')
        self.assertEqual(trend['state'], 'healthy')
        self.assertEqual(trend['series'], trend['items'])

        summary = self.client.get('/alert/run-metrics/summary/').json()['data']
        self.assertEqual(summary['state'], 'healthy')
        self.assertEqual(len(summary['items']), 1)
        day = summary['items'][0]
        for key in ('date', 'request_count', 'system_error_count', 'slow_count',
                    'unavailable_windows', 'unknown_windows'):
            self.assertIn(key, day)
        self.assertEqual(day['date'], to_local_naive(bucket).date().isoformat())

    def test_trend_state_uses_latest_bucket_not_older_unknown_bucket(self):
        """当前状态不能被窗口内较早的缺失探活桶永久压成 unknown。"""
        old_bucket = floor_window(timezone.now() - timedelta(minutes=10))
        latest_bucket = old_bucket + timedelta(minutes=5)
        RunMetric.objects.create(bucket_start=old_bucket, request_count=10)
        HealthProbeSample.objects.create(
            timestamp=latest_bucket + timedelta(minutes=1), success=True,
            http_status=200, duration_ms=80,
        )
        self.assertEqual(flush_run_metrics(bucket_start=latest_bucket.isoformat()), 1)

        trend = self.client.get('/alert/run-metrics/', {'hours': 48}).json()['data']
        self.assertEqual(trend['items'][0]['state'], 'unknown')
        self.assertEqual(trend['items'][-1]['state'], 'healthy')
        self.assertEqual(trend['state'], 'healthy')

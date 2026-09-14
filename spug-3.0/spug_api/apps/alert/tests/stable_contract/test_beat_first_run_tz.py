import json
import os
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from apps.alert.metrics import floor_window
from apps.alert.models import HealthProbeSample, RunMetric
from apps.alert.tasks import flush_run_metrics
from libs.beat_tz_compat import (
    TZCompatDatabaseScheduler,
    TZCompatModelEntry,
    local_naive_to_utc_naive,
)

UTC = dt_timezone.utc


def _make_periodic_task(name, date_changed_local, last_run_at=None, every=300):
    """创建 PeriodicTask 并用 update() 固定 date_changed / last_run_at。

    date_changed 是 auto_now 字段，ORM save 会强制刷新为当前时间；
    queryset.update() 绕过 auto_now，用于构造确定性的首次调度场景。
    """
    interval = IntervalSchedule.objects.create(every=every, period=IntervalSchedule.SECONDS)
    task = PeriodicTask.objects.create(
        name=name, task='apps.alert.tasks.flush_run_metrics', interval=interval, enabled=True,
    )
    PeriodicTask.objects.filter(pk=task.pk).update(date_changed=date_changed_local, last_run_at=last_run_at)
    task.refresh_from_db()
    return task


class LocalNaiveToUtcNaiveTest(TestCase):
    """date_changed（Asia/Shanghai 本地 naive）→ UTC naive 的转换契约。"""

    def test_shanghai_wall_clock_becomes_utc_wall_clock(self):
        # 2026-09-14 14:00 上海 = 2026-09-14 06:00 UTC
        self.assertEqual(local_naive_to_utc_naive(datetime(2026, 9, 14, 14, 0)), datetime(2026, 9, 14, 6, 0))

    def test_conversion_preserves_instant(self):
        local_naive = datetime(2026, 9, 14, 14, 23, 45)
        expected_aware_utc = timezone.make_aware(local_naive).astimezone(UTC)
        self.assertEqual(local_naive_to_utc_naive(local_naive), expected_aware_utc.replace(tzinfo=None))

    def test_none_passthrough(self):
        self.assertIsNone(local_naive_to_utc_naive(None))

    def test_result_is_naive(self):
        self.assertTrue(timezone.is_naive(local_naive_to_utc_naive(datetime(2026, 9, 14, 14, 0))))


class FirstRunTZCompatEntryTest(TestCase):
    """ModelEntry 首次初始化契约：last_run_at 为空按本地口径转换，已有值不动。"""

    def test_new_task_last_run_at_converted_from_local_to_utc(self):
        # 旧实现直接把 14:00 本地当 14:00 UTC（= 22:00 本地，超前 8 小时）
        task = _make_periodic_task('tz-new', datetime(2026, 9, 14, 14, 0), last_run_at=None)
        entry = TZCompatModelEntry(task)
        self.assertTrue(timezone.is_naive(entry.last_run_at))
        self.assertEqual(entry.last_run_at, datetime(2026, 9, 14, 6, 0))

    def test_new_task_is_due_when_date_changed_is_old(self):
        # date_changed 在 10 分钟前 → 任务应立即到期（旧实现会把它当未来 8 小时后）
        stale = timezone.now() - timedelta(minutes=10)
        task = _make_periodic_task('tz-stale', stale, last_run_at=None)
        entry = TZCompatModelEntry(task)
        is_due, _ = entry.is_due()
        self.assertTrue(is_due)

    def test_fresh_task_next_run_close_to_interval_not_8_hours(self):
        # date_changed=现在 → 下次到期应接近 300 秒，而不是 ~28800 秒（8 小时）
        task = _make_periodic_task('tz-fresh', timezone.now(), last_run_at=None)
        entry = TZCompatModelEntry(task)
        is_due, next_time = entry.is_due()
        self.assertFalse(is_due)
        self.assertGreater(next_time, 0)
        self.assertLessEqual(next_time, 600)

    def test_existing_last_run_at_is_not_modified(self):
        # 已有 last_run_at（UTC naive，Beat 既有口径）的任务一个字节都不改
        task = _make_periodic_task(
            'tz-existing', datetime(2026, 9, 14, 14, 0), last_run_at=datetime(2026, 9, 14, 5, 0),
        )
        entry = TZCompatModelEntry(task)
        self.assertEqual(entry.last_run_at, datetime(2026, 9, 14, 5, 0))
        task.refresh_from_db()
        self.assertEqual(task.last_run_at, datetime(2026, 9, 14, 5, 0))

    def test_scheduler_wiring_uses_compat_entry(self):
        self.assertIs(TZCompatDatabaseScheduler.Entry, TZCompatModelEntry)

    def test_from_entry_install_path_converts_first_run(self):
        # CELERY_BEAT_SCHEDULE 经 update_from_dict → Entry.from_entry 安装的真实路径：
        # 安装只在库里创建行（last_run_at 保持 NULL），转换发生在条目构造时（内存）
        entry = TZCompatModelEntry.from_entry(
            'tz-from-entry', schedule=timedelta(seconds=300),
            task='apps.alert.tasks.flush_run_metrics',
        )
        self.assertIsNone(PeriodicTask.objects.get(name='tz-from-entry').last_run_at)
        self.assertEqual(
            entry.last_run_at, local_naive_to_utc_naive(entry.model.date_changed),
        )
        self.assertTrue(timezone.is_naive(entry.last_run_at))


class SyncAlertPeriodicTasksTest(TestCase):
    """sync_alert_periodic_tasks 契约：300 秒周期；重复执行不重置 last_run_at。"""

    def test_flush_interval_is_300_seconds(self):
        call_command('sync_alert_periodic_tasks')
        task = PeriodicTask.objects.get(name='flush-run-metrics')
        self.assertEqual(task.interval.every, 300)
        self.assertEqual(task.interval.period, IntervalSchedule.SECONDS)
        self.assertEqual(task.task, 'apps.alert.tasks.flush_run_metrics')
        self.assertTrue(task.enabled)

    def test_repeated_sync_preserves_last_run_at_and_count(self):
        call_command('sync_alert_periodic_tasks')
        PeriodicTask.objects.filter(name='flush-run-metrics').update(
            last_run_at=datetime(2026, 9, 14, 5, 0), total_run_count=7,
        )
        PeriodicTask.objects.filter(name='cleanup-run-metrics').update(
            last_run_at=datetime(2026, 9, 14, 5, 30), total_run_count=3,
        )
        call_command('sync_alert_periodic_tasks')
        flush_task = PeriodicTask.objects.get(name='flush-run-metrics')
        self.assertEqual(flush_task.last_run_at, datetime(2026, 9, 14, 5, 0))
        self.assertEqual(flush_task.total_run_count, 7)
        cleanup_task = PeriodicTask.objects.get(name='cleanup-run-metrics')
        self.assertEqual(cleanup_task.last_run_at, datetime(2026, 9, 14, 5, 30))
        self.assertEqual(cleanup_task.total_run_count, 3)

    def test_repeated_sync_keeps_interval_at_300(self):
        call_command('sync_alert_periodic_tasks')
        call_command('sync_alert_periodic_tasks')
        self.assertEqual(PeriodicTask.objects.get(name='flush-run-metrics').interval.every, 300)


class RepairPeriodicTaskLastRunTest(TestCase):
    """repair_periodic_task_last_run：幂等、可审计、只修 last_run_at 为空的启用任务。"""

    def call_repair(self, *args):
        out = []
        call_command('repair_periodic_task_last_run', *args, stdout=self._out)
        self._out.seek(0)
        return self._out.read()

    def setUp(self):
        from io import StringIO
        self._out = StringIO()

    def test_repairs_empty_last_run_at_with_utc_conversion(self):
        task = _make_periodic_task('repair-empty', datetime(2026, 9, 14, 14, 0), last_run_at=None)
        output = self.call_repair()
        task.refresh_from_db()
        self.assertEqual(task.last_run_at, datetime(2026, 9, 14, 6, 0))
        self.assertIn('repair-empty', output)
        self.assertIn('repaired: 1', output)

    def test_does_not_touch_existing_last_run_at(self):
        _make_periodic_task('repair-keep', datetime(2026, 9, 14, 14, 0), last_run_at=datetime(2026, 9, 14, 5, 0))
        output = self.call_repair()
        task = PeriodicTask.objects.get(name='repair-keep')
        self.assertEqual(task.last_run_at, datetime(2026, 9, 14, 5, 0))
        self.assertNotIn('repair-keep', output)
        self.assertIn('repaired: 0', output)

    def test_skips_disabled_tasks(self):
        interval = IntervalSchedule.objects.create(every=300, period=IntervalSchedule.SECONDS)
        task = PeriodicTask.objects.create(
            name='repair-disabled', task='apps.alert.tasks.flush_run_metrics',
            interval=interval, enabled=False,
        )
        PeriodicTask.objects.filter(pk=task.pk).update(date_changed=datetime(2026, 9, 14, 14, 0), last_run_at=None)
        self.call_repair()
        task.refresh_from_db()
        self.assertIsNone(task.last_run_at)

    def test_command_is_idempotent(self):
        _make_periodic_task('repair-idem', datetime(2026, 9, 14, 14, 0), last_run_at=None)
        self.assertIn('repaired: 1', self.call_repair())
        self.assertIn('repaired: 0', self.call_repair())
        task = PeriodicTask.objects.get(name='repair-idem')
        self.assertEqual(task.last_run_at, datetime(2026, 9, 14, 6, 0))

    def test_dry_run_does_not_write(self):
        _make_periodic_task('repair-dry', datetime(2026, 9, 14, 14, 0), last_run_at=None)
        output = self.call_repair('--dry-run')
        self.assertIn('repair-dry', output)
        self.assertIn('examined: 1', output)
        task = PeriodicTask.objects.get(name='repair-dry')
        self.assertIsNone(task.last_run_at)


class FlushRunMetricsProbeIngestTest(TestCase):
    """flush_run_metrics 端到端：导入探活日志 → HealthProbeSample → RunMetric。"""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
        tmp.close()
        self.tmp_path = tmp.name
        self.addCleanup(lambda: os.path.exists(self.tmp_path) and os.unlink(self.tmp_path))
        ctx = override_settings(RUN_METRICS_PROBE_LOG=self.tmp_path, RUN_METRICS_NGINX_LOG='')
        ctx.enable()
        self.addCleanup(ctx.disable)
        # 任务聚合"上一个完整 5 分钟窗口"，探活样本必须落在该窗口内
        self.bucket = floor_window(timezone.now()) - timedelta(seconds=300)

    def _write_probe(self, offset_seconds, **extra):
        # 探活日志时间戳为 UTC ISO8601（Z 结尾）：本地窗口时刻换算成 UTC 墙钟写入
        local_ts = self.bucket + timedelta(seconds=offset_seconds)
        utc_wall = timezone.make_aware(local_ts).astimezone(UTC).replace(tzinfo=None)
        payload = {'timestamp': utc_wall.isoformat().replace('+00:00', 'Z'), 'success': True,
                   'http_status': 200, 'duration_ms': 120, 'error_type': ''}
        payload.update(extra)
        with open(self.tmp_path, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(payload) + '\n')

    def test_flush_ingests_probe_log_and_writes_samples_and_metric(self):
        self._write_probe(60)
        self._write_probe(120, duration_ms=80)
        created = flush_run_metrics()
        self.assertGreaterEqual(created, 1)
        self.assertEqual(HealthProbeSample.objects.count(), 2)
        self.assertEqual(HealthProbeSample.objects.filter(success=True).count(), 2)
        metric = RunMetric.objects.get(bucket_start=self.bucket)
        self.assertEqual(metric.probe_count, 2)
        self.assertEqual(metric.probe_success_count, 2)
        self.assertEqual(metric.probe_max_ms, 120)

    @patch('libs.alert.send_alert')
    def test_flush_is_idempotent_on_repeated_runs(self, send_alert):
        self._write_probe(60)
        self.assertEqual(flush_run_metrics(), 1)
        self.assertEqual(flush_run_metrics(), 1)
        self.assertEqual(HealthProbeSample.objects.count(), 1)
        self.assertEqual(RunMetric.objects.filter(bucket_start=self.bucket).count(), 1)

# -*- coding: utf-8 -*-
"""磁盘趋势指标目录口径稳定契约。

公开趋势曲线 disk:documents / disk:chunks / disk:media 必须是目录自身实际
占用（du -s -B1 -x 统计），不得使用 shutil.disk_usage 的文件系统口径 ——
三个存储目录可能共用同一底层文件系统，后者导致三条曲线完全重合。
disk:total 为同一轮采集的精确总和，且仅在三组目录全部成功时写入；
目录缺失、du 失败/超时、任务重入均不得产生错误总计。
文件系统容量告警与满盘趋势预测仍使用 shutil.disk_usage，历史记录在
内部键 fs-usage:*，与公开目录曲线分离。
"""
import os
import shutil
import subprocess
import tempfile
import time
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django_redis import get_redis_connection

from apps.alert.models import Alert
from apps.alert.tasks import DISK_CHECK_LOCK_KEY, check_disk_space
from libs.trend import get_trend


def _clear_disk_metrics():
    """清理本契约相关的 Redis 趋势键（公开曲线 + 内部文件系统指标）"""
    conn = get_redis_connection()
    keys = list(conn.keys('metric:disk:*')) + list(conn.keys('metric:fs-usage:*'))
    if keys:
        conn.delete(*keys)


def _make_usage(used, total):
    """构造 shutil.disk_usage 返回值的 mock 对象"""
    usage = MagicMock()
    usage.used = used
    usage.total = total
    usage.free = total - used
    return usage


def _inject_history(metric_name, points):
    """按 (hours_ago, value) 注入历史趋势点"""
    conn = get_redis_connection()
    now = time.time()
    mapping = {f'{now - hours_ago * 3600}:{val}': now - hours_ago * 3600 for hours_ago, val in points}
    conn.zadd(f'metric:{metric_name}', mapping)


class CollectionConfigContractTest(TestCase):
    """采集配置契约：30 分钟周期 + 配置化存储目录"""

    def test_check_disk_space_beat_runs_every_30_minutes(self):
        from apps.alert.celery_beat_schedule import ALERT_BEAT_SCHEDULE
        entry = ALERT_BEAT_SCHEDULE['check-disk-space']
        self.assertEqual(entry['task'], 'apps.alert.tasks.check_disk_space')
        self.assertEqual(entry['schedule'], 1800.0)

    def test_alert_storage_dirs_config_contract(self):
        dirs = dict(settings.ALERT_STORAGE_DIRS)
        self.assertEqual(set(dirs), {'documents', 'chunks', 'media'})
        for path in dirs.values():
            self.assertTrue(os.path.isabs(path))
        self.assertEqual(dirs['media'], settings.MEDIA_ROOT)

    def test_du_timeout_config_contract(self):
        self.assertGreater(int(settings.ALERT_DU_TIMEOUT_SECONDS), 0)


class DirectoryTrendContractTest(TestCase):
    """真实目录扫描：三值不同、总和精确、与 shutil.disk_usage 口径无关"""

    def setUp(self):
        cache.delete(DISK_CHECK_LOCK_KEY)
        _clear_disk_metrics()
        Alert.objects.all().delete()
        self.base = tempfile.mkdtemp(prefix='disk_trend_')
        self.sizes = {'documents': 200_000, 'chunks': 40_000, 'media': 4_000}
        self.dirs = {}
        for name, size in self.sizes.items():
            path = os.path.join(self.base, name)
            os.makedirs(path)
            with open(os.path.join(path, 'blob.bin'), 'wb') as fh:
                fh.write(os.urandom(size))
            self.dirs[name] = path
        self.overrider = override_settings(
            ALERT_STORAGE_DIRS=[
                ('documents', self.dirs['documents']),
                ('chunks', self.dirs['chunks']),
                ('media', self.dirs['media']),
            ],
            ALERT_DU_TIMEOUT_SECONDS=60,
        )
        self.overrider.enable()

    def tearDown(self):
        self.overrider.disable()
        shutil.rmtree(self.base, ignore_errors=True)
        cache.delete(DISK_CHECK_LOCK_KEY)
        _clear_disk_metrics()

    def test_real_scan_records_three_distinct_values(self):
        """三个真实目录写入明显不同大小的文件：采集值各不相同且大于文件字节数（按块取整）"""
        result = check_disk_space()
        values = result['directories']
        self.assertEqual(len(values), 3)
        self.assertEqual(len(set(values.values())), 3)
        for name, size in self.sizes.items():
            self.assertGreater(values[name], size)
            points = get_trend(f'disk:{name}', 1)
            self.assertEqual(len(points), 1)
            self.assertEqual(points[0][1], float(values[name]))

    def test_total_equals_exact_sum_of_same_round(self):
        """disk:total 等于同一轮三个分类值的精确总和，且写入 Redis 曲线"""
        result = check_disk_space()
        expected = sum(result['directories'].values())
        self.assertEqual(result['total'], expected)
        points = get_trend('disk:total', 1)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0][1], float(expected))

    def test_identical_disk_usage_keeps_directory_curves_distinct(self):
        """即使 shutil.disk_usage 对所有路径返回完全相同结果，目录趋势依然不同"""
        fake_used = 10 * 1024 ** 3
        fake = _make_usage(used=fake_used, total=100 * 1024 ** 3)
        with patch('shutil.disk_usage', return_value=fake):
            result = check_disk_space()
        values = result['directories']
        self.assertEqual(len(values), 3)
        self.assertEqual(len(set(values.values())), 3)
        # 公开曲线不再是文件系统口径（10GB），而是目录真实占用
        for value in values.values():
            self.assertNotEqual(value, fake_used)
            self.assertLess(value, 1024 ** 3)


class DirectoryFailureContractTest(TestCase):
    """目录缺失 / du 失败 / du 超时 / 任务重入：不写入错误总计"""

    def setUp(self):
        cache.delete(DISK_CHECK_LOCK_KEY)
        _clear_disk_metrics()
        Alert.objects.all().delete()
        self.good_dir = tempfile.mkdtemp(prefix='disk_trend_good_')
        with open(os.path.join(self.good_dir, 'f.bin'), 'wb') as fh:
            fh.write(os.urandom(50_000))
        missing_parent = tempfile.mkdtemp(prefix='disk_trend_missing_')
        self.missing_dir = os.path.join(missing_parent, 'not_created')
        self.overrider = override_settings(
            ALERT_STORAGE_DIRS=[
                ('documents', self.good_dir),
                ('media', self.missing_dir),
            ],
            ALERT_DU_TIMEOUT_SECONDS=60,
        )
        self.overrider.enable()

    def tearDown(self):
        self.overrider.disable()
        shutil.rmtree(self.good_dir, ignore_errors=True)
        shutil.rmtree(os.path.dirname(self.missing_dir), ignore_errors=True)
        cache.delete(DISK_CHECK_LOCK_KEY)
        _clear_disk_metrics()

    def test_missing_dir_skips_total_but_records_others(self):
        """目录缺失：记日志并跳过，不写 0；成功目录正常记录；本轮不写 total"""
        conn = get_redis_connection()
        result = check_disk_space()
        self.assertIn('media', result['failures'])
        self.assertIsNone(result['total'])
        self.assertFalse(conn.exists('metric:disk:total'))
        # 成功目录正常记录
        points = get_trend('disk:documents', 1)
        self.assertEqual(len(points), 1)
        self.assertGreater(points[0][1], 0)
        # 失败目录不得写成 0
        self.assertEqual(get_trend('disk:media', 1), [])

    def test_du_timeout_skips_total(self):
        """du 超时：全部目录按失败处理，不写分类值也不写 total"""
        with patch('apps.alert.tasks.subprocess.run',
                   side_effect=subprocess.TimeoutExpired(cmd='du', timeout=0.1)):
            result = check_disk_space()
        self.assertEqual(set(result['failures']), {'documents', 'media'})
        self.assertIsNone(result['total'])
        self.assertFalse(get_redis_connection().exists('metric:disk:total'))
        self.assertEqual(get_trend('disk:documents', 1), [])

    def test_du_nonzero_exit_skips_total(self):
        """du 非零退出：按失败处理，不写 total"""
        proc = subprocess.CompletedProcess(args=['du'], returncode=1, stdout='', stderr='du: cannot access')
        with patch('apps.alert.tasks.subprocess.run', return_value=proc):
            result = check_disk_space()
        self.assertEqual(len(result['failures']), 2)
        self.assertIsNone(result['total'])
        self.assertFalse(get_redis_connection().exists('metric:disk:total'))

    def test_reentrant_run_skipped_while_lock_held(self):
        """任务重入：锁被持有时跳过本轮，不产生任何新采集点"""
        self.assertTrue(cache.add(DISK_CHECK_LOCK_KEY, '1', 60))
        try:
            result = check_disk_space()
            self.assertEqual(result, {'skipped': True})
            self.assertEqual(get_trend('disk:documents', 1), [])
            self.assertFalse(get_redis_connection().exists('metric:disk:total'))
        finally:
            cache.delete(DISK_CHECK_LOCK_KEY)
        # 锁释放后可正常采集：documents 记录成功；media 仍因目录缺失失败（本类固定场景）
        result = check_disk_space()
        self.assertNotIn('documents', result['failures'])
        self.assertEqual(len(get_trend('disk:documents', 1)), 1)
        self.assertEqual(result['failures'], ['media'])
        self.assertIsNone(result['total'])


class FilesystemAlertContractTest(TestCase):
    """满盘快照告警与 72h 趋势预警仍基于 shutil.disk_usage，与目录曲线分离"""

    def setUp(self):
        cache.delete(DISK_CHECK_LOCK_KEY)
        _clear_disk_metrics()
        Alert.objects.all().delete()
        self.fs_dir = tempfile.mkdtemp(prefix='disk_trend_fs_')
        self.overrider = override_settings(
            ALERT_STORAGE_DIRS=[('documents', self.fs_dir)],
            ALERT_DU_TIMEOUT_SECONDS=60,
        )
        self.overrider.enable()

    def tearDown(self):
        self.overrider.disable()
        shutil.rmtree(self.fs_dir, ignore_errors=True)
        cache.delete(DISK_CHECK_LOCK_KEY)
        _clear_disk_metrics()

    def test_snapshot_alert_over_90_uses_filesystem_usage(self):
        """>90% 快照告警使用文件系统口径；公开目录曲线仍是真实目录占用"""
        fake = _make_usage(used=95 * 1024 ** 3, total=100 * 1024 ** 3)
        with patch('shutil.disk_usage', return_value=fake), \
                patch('libs.alert.send_alert') as mock_alert:
            check_disk_space()
        alert_keys = [call.kwargs.get('alert_key') for call in mock_alert.call_args_list]
        self.assertIn('disk:documents', alert_keys)
        # 内部文件系统指标记录 fs used；公开目录曲线记录 du 真实目录占用
        fs_points = get_trend('fs-usage:documents', 1)
        self.assertEqual(fs_points[0][1], float(95 * 1024 ** 3))
        dir_points = get_trend('disk:documents', 1)
        self.assertLess(dir_points[0][1], 1024 ** 3)

    def test_trend_alert_predicted_full_within_72h(self):
        """文件系统口径 85% 且增长速率预测 72h 内满盘：触发趋势预警，不触发快照告警"""
        total = 100 * 1024 ** 3
        used = 85 * 1024 ** 3
        points = [(23 - i, (85 - (23 - i)) * 1024 ** 3) for i in range(24)]
        _inject_history('fs-usage:documents', points)
        fake = _make_usage(used=used, total=total)
        with patch('shutil.disk_usage', return_value=fake), \
                patch('libs.alert.send_alert') as mock_alert:
            check_disk_space()
        alert_keys = [call.kwargs.get('alert_key') for call in mock_alert.call_args_list]
        self.assertIn('disk:documents:trend', alert_keys)
        self.assertNotIn('disk:documents', alert_keys)

    def test_trend_prediction_ignores_public_directory_metric(self):
        """满盘预测只看内部 fs-usage 键：向公开曲线注入暴涨历史不会触发预警"""
        now = time.time()
        mapping = {
            f'{now - (23 - i) * 3600}:{(50 - (23 - i) * 3) * 1024 ** 3}': now - (23 - i) * 3600
            for i in range(24)
        }
        get_redis_connection().zadd('metric:disk:documents', mapping)
        fake = _make_usage(used=50 * 1024 ** 3, total=100 * 1024 ** 3)
        with patch('shutil.disk_usage', return_value=fake), \
                patch('libs.alert.send_alert') as mock_alert:
            check_disk_space()
        self.assertFalse(mock_alert.called)


class AlertTrendApiContractTest(TestCase):
    """/api/alert/trend/ 返回四条序列及正确标签"""

    def setUp(self):
        _clear_disk_metrics()

    def tearDown(self):
        _clear_disk_metrics()

    def test_api_returns_four_series_with_labels(self):
        from apps.utils.test_helpers import make_user, make_client

        user = make_user('trend_four_series', ['system.alert.view'])
        client = make_client(user)
        now = time.time()
        conn = get_redis_connection()
        for key, value in [
            ('disk:documents', 100),
            ('disk:chunks', 200),
            ('disk:media', 300),
            ('disk:total', 600),
        ]:
            conn.zadd(f'metric:{key}', {f'{now}:{value}': now})

        resp = client.get('/alert/trend/', {'hours': 24})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))
        series = body['data']['series']
        self.assertEqual(
            [s['name'] for s in series],
            ['disk:documents', 'disk:chunks', 'disk:media', 'disk:total'],
        )
        self.assertEqual(
            [s['label'] for s in series],
            ['文档存储', '分片存储', '媒体存储', '三类存储总计'],
        )
        self.assertEqual([s['points'][0]['value'] for s in series], [100.0, 200.0, 300.0, 600.0])

    def test_api_omits_total_until_first_successful_round(self):
        """disk:total 尚无数据时只返回已有分类序列，不报错"""
        from apps.utils.test_helpers import make_user, make_client

        user = make_user('trend_no_total', ['system.alert.view'])
        client = make_client(user)
        _inject_history('disk:documents', [(0, 100)])
        resp = client.get('/alert/trend/', {'hours': 24})
        body = resp.json()
        self.assertFalse(body.get('error'))
        series = body['data']['series']
        self.assertEqual([s['name'] for s in series], ['disk:documents'])

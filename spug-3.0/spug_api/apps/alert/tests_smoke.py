# -*- coding: utf-8 -*-
"""
告警监控模块测试

覆盖：
1. libs/trend.py 趋势计算工具（record/get_trend/linear_slope/predict）
2. apps/alert/tasks.py check_disk_space 趋势预警逻辑
3. libs/alert.py send_alert 限流去重
"""
import time
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.core.cache import cache
from django_redis import get_redis_connection

from libs.trend import (
    record_metric, get_trend, linear_slope, predict_time_to_threshold,
    _extract_value, METRIC_TTL,
)
from apps.alert.models import Alert


def _clear_metrics():
    """清理 Redis 中的 metric:* 键"""
    r = get_redis_connection()
    keys = r.keys('metric:*')
    if keys:
        r.delete(*keys)


class TrendRecordGetTest(TestCase):
    """record_metric / get_trend 基础读写"""

    def setUp(self):
        cache.clear()
        _clear_metrics()

    def test_record_and_get_basic(self):
        """写入 3 条指标后能正确读回"""
        record_metric('test:disk', 100)
        time.sleep(0.01)
        record_metric('test:disk', 200)
        time.sleep(0.01)
        record_metric('test:disk', 300)

        trend = get_trend('test:disk', 24)
        self.assertEqual(len(trend), 3)
        # 值应按写入顺序升序
        self.assertEqual(trend[0][1], 100)
        self.assertEqual(trend[1][1], 200)
        self.assertEqual(trend[2][1], 300)

    def test_get_trend_empty(self):
        """无数据时返回空列表"""
        trend = get_trend('nonexistent:metric', 24)
        self.assertEqual(trend, [])

    def test_record_float_value(self):
        """支持浮点数"""
        record_metric('test:float', 3.14)
        time.sleep(0.01)
        record_metric('test:float', 2.718)

        trend = get_trend('test:float', 24)
        self.assertEqual(len(trend), 2)
        self.assertAlmostEqual(trend[0][1], 3.14)
        self.assertAlmostEqual(trend[1][1], 2.718)

    def test_window_filters_old_data(self):
        """window_hours 只返回窗口内的数据"""
        r = get_redis_connection()
        # 写入一条 "当前" 的
        record_metric('test:window', 100)
        # 手动往 Redis 塞一条 48 小时前的数据
        key = 'metric:test:window'
        old_ts = time.time() - 48 * 3600
        r.zadd(key, {f'{old_ts}:999': old_ts})

        # 24h 窗口应该只返回 1 条
        trend_24 = get_trend('test:window', 24)
        self.assertEqual(len(trend_24), 1)
        self.assertEqual(trend_24[0][1], 100)

        # 72h 窗口应该返回 2 条
        trend_72 = get_trend('test:window', 72)
        self.assertEqual(len(trend_72), 2)


class TrendExtractValueTest(TestCase):
    """_extract_value 辅助函数"""

    def test_extract_normal(self):
        self.assertEqual(_extract_value('1700000000:12345'), 12345.0)

    def test_extract_float(self):
        self.assertEqual(_extract_value('1700000000:1.5'), 1.5)

    def test_extract_bytes(self):
        self.assertEqual(_extract_value(b'1700000000:999'), 999.0)

    def test_extract_invalid(self):
        self.assertIsNone(_extract_value('invalid'))
        self.assertIsNone(_extract_value(''))
        self.assertIsNone(_extract_value('1700000000:abc'))

    def test_extract_negative(self):
        self.assertEqual(_extract_value('1700000000:-50'), -50.0)


class LinearSlopeTest(TestCase):
    """linear_slope 线性回归"""

    def test_insufficient_points(self):
        """少于 3 个点返回 None"""
        self.assertIsNone(linear_slope([]))
        self.assertIsNone(linear_slope([(1, 1)]))
        self.assertIsNone(linear_slope([(1, 1), (2, 2)]))

    def test_positive_slope(self):
        """递增序列斜率为正"""
        points = [(i * 3600, i * 1000) for i in range(10)]
        slope = linear_slope(points)
        self.assertIsNotNone(slope)
        self.assertGreater(slope, 0)
        # 1 小时增长 1000 => slope = 1000/3600 bytes/s
        self.assertAlmostEqual(slope, 1000 / 3600, places=4)

    def test_negative_slope(self):
        """递减序列斜率为负"""
        points = [(i * 3600, 10000 - i * 1000) for i in range(10)]
        slope = linear_slope(points)
        self.assertIsNotNone(slope)
        self.assertLess(slope, 0)

    def test_flat_slope(self):
        """无变化时斜率为 0"""
        points = [(i * 3600, 5000) for i in range(5)]
        slope = linear_slope(points)
        self.assertEqual(slope, 0.0)

    def test_same_timestamp(self):
        """所有 timestamp 相同时返回 0（避免除零）"""
        points = [(1000, 1), (1000, 2), (1000, 3)]
        slope = linear_slope(points)
        self.assertEqual(slope, 0.0)


class PredictTimeToThresholdTest(TestCase):
    """predict_time_to_threshold 预测函数"""

    def test_no_slope(self):
        """斜率为 None 时返回 None"""
        self.assertIsNone(predict_time_to_threshold(50, 100, None))

    def test_zero_slope(self):
        """斜率为 0 时返回 None"""
        self.assertIsNone(predict_time_to_threshold(50, 100, 0))

    def test_negative_slope(self):
        """斜率为负（下降中）时返回 None"""
        self.assertIsNone(predict_time_to_threshold(50, 100, -1.0))

    def test_already_over(self):
        """已超阈值返回 0"""
        self.assertEqual(predict_time_to_threshold(110, 100, 1.0), 0.0)

    def test_predict_hours(self):
        """正常预测：100GB 总量，已用 50GB，增长 10GB/h => 5 小时后满"""
        # slope = 10GB/h => 10*1024^3 / 3600 bytes/s
        slope = (10 * 1024 ** 3) / 3600
        hours = predict_time_to_threshold(
            current=50 * 1024 ** 3,
            threshold=100 * 1024 ** 3,
            slope=slope,
        )
        self.assertAlmostEqual(hours, 5.0, places=1)

    def test_predict_zero_remaining(self):
        """current == threshold 返回 0"""
        self.assertEqual(predict_time_to_threshold(100, 100, 1.0), 0.0)


class CheckDiskSpaceTaskTest(TestCase):
    """check_disk_space 任务测试"""

    def setUp(self):
        cache.clear()
        _clear_metrics()
        # 清理已有告警避免干扰
        Alert.objects.all().delete()

    def _make_disk_usage(self, used, total):
        """构造 shutil.disk_usage mock 对象"""
        usage = MagicMock()
        usage.used = used
        usage.total = total
        usage.free = total - used
        return usage

    def _inject_history(self, metric_name, points):
        """往 Redis 注入历史趋势数据

        Args:
            metric_name: 指标名（如 'disk:documents'）
            points: list of (hours_ago, value) 元组
        """
        r = get_redis_connection()
        key = f'metric:{metric_name}'
        now = time.time()
        mapping = {}
        for hours_ago, val in points:
            ts = now - hours_ago * 3600
            mapping[f'{ts}:{val}'] = ts
        r.zadd(key, mapping)

    @patch('shutil.disk_usage')
    @patch('os.path.exists', return_value=True)
    def test_snapshot_alert_when_over_90(self, mock_exists, mock_du):
        """磁盘 >90% 触发快照告警"""
        from apps.alert.tasks import check_disk_space

        # 95% 使用率
        mock_du.return_value = self._make_disk_usage(used=95, total=100)

        check_disk_space()

        alerts = Alert.objects.filter(source='disk')
        self.assertTrue(alerts.exists())
        self.assertIn('磁盘空间告警', alerts.first().title)

    @patch('shutil.disk_usage')
    @patch('os.path.exists', return_value=True)
    def test_no_alert_when_healthy(self, mock_exists, mock_du):
        """磁盘 50% 无告警"""
        from apps.alert.tasks import check_disk_space

        mock_du.return_value = self._make_disk_usage(used=50, total=100)

        check_disk_space()

        self.assertFalse(Alert.objects.filter(source='disk').exists())

    @patch('shutil.disk_usage')
    @patch('os.path.exists', return_value=True)
    def test_trend_alert_predicted_full_within_72h(self, mock_exists, mock_du):
        """趋势预警：85% 使用率，但增长速率预测 72h 内满盘"""
        from apps.alert.tasks import check_disk_space

        total = 100 * 1024 ** 3  # 100GB
        used_85 = 85 * 1024 ** 3  # 85GB

        # 注入 24 小时的历史数据：每小时涨 1GB（24h 涨 24GB）
        # slope ≈ 1GB/h => 15GB 剩余 => 15h 后满 < 72h
        points = [(23 - i, (85 - (23 - i)) * 1024 ** 3) for i in range(24)]
        self._inject_history('disk:documents', points)

        # 当前 85%
        mock_du.return_value = self._make_disk_usage(used=used_85, total=total)

        check_disk_space()

        trend_alerts = Alert.objects.filter(
            source='disk', alert_key__endswith=':trend'
        )
        self.assertTrue(trend_alerts.exists())
        self.assertIn('趋势预警', trend_alerts.first().title)

    @patch('shutil.disk_usage')
    @patch('os.path.exists', return_value=True)
    def test_no_trend_alert_when_growth_slow(self, mock_exists, mock_du):
        """增长缓慢（>72h 才满）时不触发趋势预警"""
        from apps.alert.tasks import check_disk_space

        total = 100 * 1024 ** 3  # 100GB
        used_85 = 85 * 1024 ** 3  # 85GB，剩 15GB

        # 注入 24h 历史：每小时涨 0.1GB
        # slope ≈ 0.1GB/h => 15GB / 0.1 = 150h > 72h
        points = [(23 - i, (85 - (23 - i) * 0.1) * 1024 ** 3) for i in range(24)]
        self._inject_history('disk:documents', points)

        mock_du.return_value = self._make_disk_usage(used=used_85, total=total)

        check_disk_space()

        trend_alerts = Alert.objects.filter(
            source='disk', alert_key__endswith=':trend'
        )
        self.assertFalse(trend_alerts.exists())

    @patch('shutil.disk_usage')
    @patch('os.path.exists', return_value=True)
    def test_no_trend_alert_when_under_12_points(self, mock_exists, mock_du):
        """历史数据不足 12 个点时不做趋势预测"""
        from apps.alert.tasks import check_disk_space

        total = 100 * 1024 ** 3
        used_85 = 85 * 1024 ** 3

        # 只注入 5 个点（< 12）
        points = [(4 - i, (85 - (4 - i) * 5) * 1024 ** 3) for i in range(5)]
        self._inject_history('disk:documents', points)

        mock_du.return_value = self._make_disk_usage(used=used_85, total=total)

        check_disk_space()

        trend_alerts = Alert.objects.filter(
            source='disk', alert_key__endswith=':trend'
        )
        self.assertFalse(trend_alerts.exists())

    @patch('shutil.disk_usage')
    @patch('os.path.exists', return_value=True)
    def test_no_trend_alert_when_already_over_90(self, mock_exists, mock_du):
        """已 >90% 时不发趋势预警（快照告警已覆盖）"""
        from apps.alert.tasks import check_disk_space

        total = 100 * 1024 ** 3
        used_95 = 95 * 1024 ** 3

        # 注入快速增长历史
        points = [(23 - i, (95 - (23 - i) * 5) * 1024 ** 3) for i in range(24)]
        self._inject_history('disk:documents', points)

        mock_du.return_value = self._make_disk_usage(used=used_95, total=total)

        check_disk_space()

        trend_alerts = Alert.objects.filter(
            source='disk', alert_key__endswith=':trend'
        )
        # 快照告警应该触发，但趋势预警不应该
        snapshot_alerts = Alert.objects.filter(
            source='disk', alert_key='disk:documents'
        )
        self.assertTrue(snapshot_alerts.exists())
        self.assertFalse(trend_alerts.exists())

    @patch('shutil.disk_usage')
    @patch('os.path.exists', return_value=True)
    def test_trend_and_snapshot_alerts_independent_dedup(self, mock_exists, mock_du):
        """趋势预警和快照告警用不同 alert_key，互不抑制"""
        from apps.alert.tasks import check_disk_space

        total = 100 * 1024 ** 3
        used_91 = 91 * 1024 ** 3  # 91%，触发快照告警

        # 注入快速增长历史（预测 < 72h）
        points = [(23 - i, (91 - (23 - i) * 3) * 1024 ** 3) for i in range(24)]
        self._inject_history('disk:documents', points)

        mock_du.return_value = self._make_disk_usage(used=used_91, total=total)

        check_disk_space()

        # 快照告警应该存在
        snapshot = Alert.objects.filter(
            source='disk', alert_key='disk:documents'
        )
        self.assertTrue(snapshot.exists())

        # 趋势预警不应该存在（因为 percent >= 90，条件 percent < 90 不满足）
        trend = Alert.objects.filter(
            source='disk', alert_key='disk:documents:trend'
        )
        self.assertFalse(trend.exists())


class SendAlertDedupTest(TestCase):
    """send_alert 限流去重"""

    def setUp(self):
        cache.clear()
        Alert.objects.all().delete()

    def test_dedup_same_alert_key(self):
        """相同 alert_key 在冷却期内不重复"""
        from libs.alert import send_alert

        send_alert('测试', 'msg1', level='warning', source='disk', alert_key='disk:test')
        send_alert('测试', 'msg2', level='warning', source='disk', alert_key='disk:test')

        # 只产生 1 条 Alert
        self.assertEqual(Alert.objects.filter(alert_key='disk:test').count(), 1)

    def test_different_alert_key_both_sent(self):
        """不同 alert_key 都会发送"""
        from libs.alert import send_alert

        send_alert('A', 'msg', level='warning', source='disk', alert_key='disk:a')
        send_alert('B', 'msg', level='warning', source='disk', alert_key='disk:b')

        self.assertEqual(Alert.objects.filter(source='disk').count(), 2)


class AlertTrendAPITest(TestCase):
    """AlertTrendView API 测试"""

    def setUp(self):
        cache.clear()
        _clear_metrics()

    def _inject_history(self, metric_name, points):
        """往 Redis 注入历史趋势数据"""
        r = get_redis_connection()
        key = f'metric:{metric_name}'
        now = time.time()
        mapping = {}
        for hours_ago, val in points:
            ts = now - hours_ago * 3600
            mapping[f'{ts}:{val}'] = ts
        r.zadd(key, mapping)

    def test_trend_api_returns_data(self):
        """API 正确返回趋势数据"""
        from apps.utils.test_helpers import make_user, make_client

        user = make_user('trend_user', ['system.alert.view'])
        client = make_client(user)

        # 注入 6h 历史数据
        points = [(5 - i, (50 + i * 5) * 1024 ** 3) for i in range(6)]
        self._inject_history('disk:documents', points)

        resp = client.get('/alert/trend/', {'hours': 24})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))

        series = body['data']['series']
        self.assertEqual(body['data']['hours'], 24)

        # 应包含 disk:documents
        names = [s['name'] for s in series]
        self.assertIn('disk:documents', names)

        # 检查数据点
        doc_series = [s for s in series if s['name'] == 'disk:documents'][0]
        self.assertEqual(len(doc_series['points']), 6)
        # 第一个点 50GB，最后一个点 75GB
        self.assertAlmostEqual(doc_series['points'][0]['value'], 50 * 1024 ** 3)
        self.assertAlmostEqual(doc_series['points'][5]['value'], 75 * 1024 ** 3)

    def test_trend_api_empty_when_no_data(self):
        """无历史数据时返回空 series"""
        from apps.utils.test_helpers import make_user, make_client

        user = make_user('trend_empty', ['system.alert.view'])
        client = make_client(user)

        resp = client.get('/alert/trend/', {'hours': 24})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['series'], [])

    def test_trend_api_hours_clamped(self):
        """hours 参数被限制在 1-168"""
        from apps.utils.test_helpers import make_user, make_client

        user = make_user('trend_clamp', ['system.alert.view'])
        client = make_client(user)

        # hours=999 应被限制为 168
        resp = client.get('/alert/trend/', {'hours': 999})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['data']['hours'], 168)

    def test_trend_api_requires_permission(self):
        """无权限用户被拒绝"""
        from apps.utils.test_helpers import make_user, make_client

        user = make_user('trend_noperm', [])
        client = make_client(user)

        resp = client.get('/alert/trend/', {'hours': 24})
        body = resp.json()
        self.assertTrue(body.get('error'))

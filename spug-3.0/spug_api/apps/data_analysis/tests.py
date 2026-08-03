"""数据分析模块单元测试。

由于项目 Django test runner 存在迁移依赖问题，这些测试设计为独立可运行：
  docker exec -e PYTHONIOENCODING=utf-8 tdyw python manage.py test apps.data_analysis.tests --noinput

或在 dev 库上直接跑脚本：
  docker exec -e PYTHONIOENCODING=utf-8 tdyw python -m pytest apps/data_analysis/tests.py
"""
import datetime
from unittest.mock import patch, MagicMock

from django.test import RequestFactory, TestCase

from apps.data_analysis.services.common import (
    parse_date_range, make_range_filter, build_distribution, build_monthly_trend,
    build_meta, calc_rate,
)
from apps.data_analysis.services.cache import get_cache_scope, cache_key


class CommonUtilsTest(TestCase):
    """测试共享工具函数。"""

    def setUp(self):
        self.factory = RequestFactory()

    def test_parse_date_range_default(self):
        """不传日期时默认取最近 365 天。"""
        request = self.factory.get('/api/data-analysis/overview/')
        start, end, error = parse_date_range(request)
        self.assertIsNone(error)
        today = datetime.date.today()
        self.assertEqual(end, today)
        self.assertEqual((today - start).days, 364)

    def test_parse_date_range_custom(self):
        """自定义日期范围。"""
        request = self.factory.get(
            '/api/data-analysis/overview/',
            {'start_date': '2026-01-01', 'end_date': '2026-06-30'}
        )
        start, end, error = parse_date_range(request)
        self.assertIsNone(error)
        self.assertEqual(start, datetime.date(2026, 1, 1))
        self.assertEqual(end, datetime.date(2026, 6, 30))

    def test_parse_date_range_invalid_format(self):
        """日期格式错误。"""
        request = self.factory.get(
            '/api/data-analysis/overview/',
            {'start_date': '2026/01/01'}
        )
        start, end, error = parse_date_range(request)
        self.assertIsNotNone(error)
        self.assertIn('YYYY-MM-DD', error)

    def test_parse_date_range_start_after_end(self):
        """start 晚于 end。"""
        request = self.factory.get(
            '/api/data-analysis/overview/',
            {'start_date': '2026-06-30', 'end_date': '2026-01-01'}
        )
        start, end, error = parse_date_range(request)
        self.assertIsNotNone(error)
        self.assertIn('不能晚于', error)

    def test_parse_date_range_too_wide(self):
        """日期范围超过 366 天。"""
        request = self.factory.get(
            '/api/data-analysis/overview/',
            {'start_date': '2025-01-01', 'end_date': '2026-12-31'}
        )
        start, end, error = parse_date_range(request)
        self.assertIsNotNone(error)
        self.assertIn('不能超过', error)

    def test_make_range_filter_half_open(self):
        """半开区间 [start, end+1day)。"""
        start = datetime.date(2026, 1, 1)
        end = datetime.date(2026, 1, 31)
        q = make_range_filter(start, end, 'created_at')
        # Q 对象的 children 包含 (key, value) 元组
        children_dict = dict(q.children)
        self.assertIn('created_at__gte', children_dict)
        self.assertIn('created_at__lt', children_dict)
        # end+1day = 2026-02-01 00:00:00
        expected_end = datetime.datetime(2026, 2, 1, 0, 0, 0)
        self.assertEqual(children_dict['created_at__lt'], expected_end)

    def test_build_meta(self):
        """响应元数据格式。"""
        meta = build_meta(datetime.date(2026, 1, 1), datetime.date(2026, 6, 30))
        self.assertEqual(meta['start_date'], '2026-01-01')
        self.assertEqual(meta['end_date'], '2026-06-30')
        self.assertEqual(meta['timezone'], 'Asia/Shanghai')
        self.assertIn('generated_at', meta)

    def test_calc_rate(self):
        """百分比计算。"""
        self.assertEqual(calc_rate(1, 3), '33.3%')
        self.assertEqual(calc_rate(0, 0), '0.0%')
        self.assertEqual(calc_rate(3, 3), '100.0%')


class CacheScopeTest(TestCase):
    """测试缓存 scope 生成。"""

    def test_scope_super_user(self):
        """super 用户 scope 为 'all'。"""
        user = MagicMock()
        user.is_supper = True
        user.is_global_admin = False
        self.assertEqual(get_cache_scope(user), 'all')

    def test_scope_global_admin(self):
        """global admin scope 为 'all'。"""
        user = MagicMock()
        user.is_supper = False
        user.is_global_admin = True
        self.assertEqual(get_cache_scope(user), 'all')

    def test_scope_normal_user(self):
        """普通用户 scope 为 'tenant:{id}'。"""
        user = MagicMock()
        user.is_supper = False
        user.is_global_admin = False
        user.tenant_id = 'tdyw'
        self.assertEqual(get_cache_scope(user), 'tenant:tdyw')

    def test_cache_key_format(self):
        """缓存 key 格式。"""
        key = cache_key('overview', 'all', '2026-01-01', '2026-06-30')
        self.assertEqual(key, 'data_analysis:v1:overview:all:2026-01-01:2026-06-30')


class DistributionTest(TestCase):
    """测试分布构建。这里用 mock QuerySet 验证逻辑。"""

    def test_build_distribution_empty(self):
        """空 QuerySet 返回空列表。"""
        from apps.fault.models import FaultRecord
        qs = FaultRecord.objects.none()
        result = build_distribution(qs, 'fault_level')
        self.assertEqual(result, [])

    def test_build_monthly_trend_fills_missing_months(self):
        """月度趋势填充缺失月份。"""
        from apps.fault.models import FaultRecord
        qs = FaultRecord.objects.none()
        result = build_monthly_trend(
            qs, 'fault_date',
            datetime.date(2026, 1, 1), datetime.date(2026, 6, 30)
        )
        # 应有 6 个月
        self.assertEqual(len(result), 6)
        self.assertEqual(result[0]['month'], '2026-01')
        self.assertEqual(result[-1]['month'], '2026-06')
        # 每个月 count 应为 0（空 QuerySet）
        for item in result:
            self.assertEqual(item['count'], 0)

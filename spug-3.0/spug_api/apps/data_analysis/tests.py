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
    build_meta, calc_rate, MAX_RANGE_DAYS,
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

    def test_parse_date_range_long_range_allowed(self):
        """最大跨度内的长区间（约 3 年）应放行。"""
        request = self.factory.get(
            '/api/data-analysis/overview/',
            {'start_date': '2024-01-01', 'end_date': '2026-12-31'}
        )
        start, end, error = parse_date_range(request)
        self.assertIsNone(error)
        self.assertEqual(start, datetime.date(2024, 1, 1))
        self.assertEqual(end, datetime.date(2026, 12, 31))

    def test_parse_date_range_at_max_boundary(self):
        """刚好等于最大跨度（MAX_RANGE_DAYS 天，含起止）应放行。"""
        end = datetime.date.today()
        start = end - datetime.timedelta(days=MAX_RANGE_DAYS - 1)
        request = self.factory.get(
            '/api/data-analysis/overview/',
            {'start_date': start.isoformat(), 'end_date': end.isoformat()}
        )
        got_start, got_end, error = parse_date_range(request)
        self.assertIsNone(error)
        self.assertEqual(got_start, start)
        self.assertEqual(got_end, end)

    def test_parse_date_range_too_wide(self):
        """日期范围超过最大跨度。"""
        request = self.factory.get(
            '/api/data-analysis/overview/',
            {'start_date': '2020-01-01', 'end_date': '2026-12-31'}
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


class InterferenceAnalysisTest(TestCase):
    """干扰分析服务契约。

    旧的「干扰管理 -> 干扰统计」页面与 /api/interference/statistics/ 接口删除后，
    干扰统计统一由数据分析 - 干扰分析提供。这里锁定其输出契约，防止误删或改坏。
    """

    def setUp(self):
        from apps.utils.test_helpers import make_user
        self.user = make_user('da_interference_svc', [])
        self.start = datetime.date(2026, 8, 1)
        self.end = datetime.date(2026, 8, 31)

    def _create(self, model, flight_number, when):
        return model.objects.create(
            tenant_id=self.user.tenant_id,
            datetime=when, flight_number=flight_number,
            phenomenon='P', created_by=self.user)

    def test_counts_both_business_types(self):
        """两类记录分别统计，并给出总量。"""
        from apps.interference.models import (
            BridgeInterferenceRecord, AirInterferenceRecord)
        from apps.data_analysis.services.interference import get_interference_analysis

        self._create(BridgeInterferenceRecord, 'CA1234', '2026-08-01 10:00:00')
        self._create(BridgeInterferenceRecord, 'CA1235', '2026-08-01 11:00:00')
        self._create(AirInterferenceRecord, 'MU5678', '2026-08-02 14:30:00')

        data = get_interference_analysis(self.user, self.start, self.end)
        self.assertEqual(data['summary']['bridge_count'], 2)
        self.assertEqual(data['summary']['air_count'], 1)
        self.assertEqual(data['summary']['record_count'], 3)

    def test_returns_trends_per_business_type(self):
        """月度趋势按记录类型分列，不混合两类业务明细。"""
        from apps.interference.models import BridgeInterferenceRecord
        from apps.data_analysis.services.interference import get_interference_analysis

        self._create(BridgeInterferenceRecord, 'CA1234', '2026-08-01 10:00:00')

        data = get_interference_analysis(self.user, self.start, self.end)
        self.assertEqual(sorted(data['trends'].keys()),
                         ['air_monthly', 'bridge_monthly', 'record_monthly'])
        bridge = data['trends']['bridge_monthly']
        self.assertEqual(len(bridge), 1)
        self.assertEqual(bridge[0]['month'], '2026-08')
        self.assertEqual(bridge[0]['count'], 1)
        # 空中无记录，趋势仍补齐月份且计数为 0
        self.assertEqual(data['trends']['air_monthly'],
                         [{'month': '2026-08', 'count': 0}])

    def test_excludes_other_tenant_records(self):
        """租户隔离：其他租户的记录不计入统计。"""
        from apps.interference.models import BridgeInterferenceRecord
        from apps.data_analysis.services.interference import get_interference_analysis

        self._create(BridgeInterferenceRecord, 'CA1234', '2026-08-01 10:00:00')
        BridgeInterferenceRecord.objects.create(
            tenant_id='other-tenant',
            datetime='2026-08-03 09:00:00', flight_number='CZ9999',
            phenomenon='P', created_by=self.user)

        data = get_interference_analysis(self.user, self.start, self.end)
        self.assertEqual(data['summary']['bridge_count'], 1)
        self.assertEqual(data['summary']['record_count'], 1)

    def test_soft_deleted_records_excluded(self):
        """软删除记录不参与统计。"""
        from apps.interference.models import BridgeInterferenceRecord
        from apps.data_analysis.services.interference import get_interference_analysis

        record = self._create(BridgeInterferenceRecord, 'CA1234',
                              '2026-08-01 10:00:00')
        record.is_deleted = True
        record.save()

        data = get_interference_analysis(self.user, self.start, self.end)
        self.assertEqual(data['summary']['bridge_count'], 0)
        self.assertEqual(data['summary']['record_count'], 0)

    def test_legacy_dimensions_remain_available(self):
        """历史干扰记录仍返回上报及类型/频率/状态/部门分布。"""
        from apps.interference.models import Interference
        from apps.data_analysis.services.interference import get_interference_analysis

        Interference.objects.create(
            tenant_id=self.user.tenant_id,
            serial_number=1,
            frequency='108.5 MHz',
            report_dept='技术部',
            datetime='2026-08-04 09:00:00',
            coordinates='N39.9,E116.4',
            interference_type='信号干扰',
            phenomenon='P',
            is_reported='是',
            created_by=self.user,
        )

        data = get_interference_analysis(self.user, self.start, self.end)
        self.assertEqual(data['summary']['record_count'], 1)
        self.assertEqual(data['summary']['reported_count'], 1)
        self.assertEqual(data['summary']['unreported_count'], 0)
        self.assertEqual(data['distributions']['by_type'][0]['name'], '信号干扰')
        self.assertEqual(data['distributions']['by_frequency'][0]['name'], '108.5 MHz')
        self.assertEqual(data['distributions']['by_status'][0]['name'], 'draft')
        self.assertEqual(data['distributions']['by_report_department'][0]['name'], '技术部')

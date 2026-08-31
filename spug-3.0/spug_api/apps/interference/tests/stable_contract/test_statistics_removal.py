# -*- coding: utf-8 -*-
"""干扰统计页面下线后的稳定契约测试。

背景：旧的「干扰管理 -> 干扰统计」页面已删除，统计能力统一由
「数据分析 -> 干扰分析」（/data-analysis/interference/）提供。

覆盖：
1. 旧的 /interference/statistics/ 路由与 InterferenceStatisticsView 已移除；
2. 干扰管理统一汇总统计 /interference/summary/ 仍然可用——这正是
   interference.statistics.view 权限编码被保留的原因；
3. 数据分析 - 干扰分析接口不受影响，仍返回两类业务记录数与月度趋势。
"""
from django.test import TestCase
from django.urls import resolve, Resolver404

from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.interference.models import BridgeInterferenceRecord, AirInterferenceRecord


class InterferenceStatisticsViewRemovedTest(TestCase):
    """旧干扰统计页面的配套接口已下线。"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('stat_removed', [
            'interference.interference.view',
            'interference.statistics.view',
            'data_analysis.interference.view',
        ])
        self.client = make_client(self.user)

    def test_statistics_url_no_longer_resolved(self):
        """URLconf 中不再存在 /interference/statistics/。"""
        with self.assertRaises(Resolver404):
            resolve('/interference/statistics/')

    def test_statistics_view_removed(self):
        """views 模块中不再导出 InterferenceStatisticsView。"""
        from apps.interference import views as interference_views
        self.assertFalse(hasattr(interference_views, 'InterferenceStatisticsView'))

    def test_statistics_url_returns_404(self):
        """实际请求该地址返回 404，而不是 200 空数据。"""
        resp = self.client.get('/interference/statistics/')
        self.assertEqual(resp.status_code, 404)

    def test_business_summary_still_available(self):
        """统一汇总统计仍在，因此 interference.statistics.view 不能删除。"""
        BridgeInterferenceRecord.objects.create(
            tenant_id=self.user.tenant_id,
            datetime='2026-08-01 10:00:00', flight_number='CA1234',
            phenomenon='P', created_by=self.user)
        AirInterferenceRecord.objects.create(
            tenant_id=self.user.tenant_id,
            datetime='2026-08-02 14:30:00', flight_number='MU5678',
            phenomenon='P', created_by=self.user)

        resp = self.client.get('/interference/summary/')
        self.assertFalse(resp.json().get('error'), resp.json().get('error', ''))
        data = resp.json()['data']
        self.assertEqual(data['bridge_count'], 1)
        self.assertEqual(data['air_count'], 1)
        self.assertEqual(data['total_count'], 2)

    def test_summary_requires_statistics_permission(self):
        """汇总统计仍受 interference.statistics.view 保护。"""
        user = make_user('stat_removed_nopm', [])
        client = make_client(user)
        self.assertTrue(client.get('/interference/summary/').json().get('error'))


class DataAnalysisInterferenceUnaffectedTest(TestCase):
    """数据分析 - 干扰分析接口不受统计页面下线影响。"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('da_interference', ['data_analysis.interference.view'])
        self.client = make_client(self.user)

    def test_interference_analysis_returns_counts_and_trends(self):
        BridgeInterferenceRecord.objects.create(
            tenant_id=self.user.tenant_id,
            datetime='2026-08-01 10:00:00', flight_number='CA1234',
            phenomenon='P', created_by=self.user)
        AirInterferenceRecord.objects.create(
            tenant_id=self.user.tenant_id,
            datetime='2026-08-02 14:30:00', flight_number='MU5678',
            phenomenon='P', created_by=self.user)

        resp = self.client.get(
            '/data-analysis/interference/',
            {'start_date': '2026-07-01', 'end_date': '2026-08-31'},
        )
        self.assertFalse(resp.json().get('error'), resp.json().get('error', ''))
        data = resp.json()['data']

        # 记录数：两类分别统计并给出总量
        summary = data['summary']
        self.assertEqual(summary['bridge_count'], 1)
        self.assertEqual(summary['air_count'], 1)
        self.assertEqual(summary['record_count'], 2)

        # 月度趋势：按记录类型分列
        trends = data['trends']
        self.assertIn('bridge_monthly', trends)
        self.assertIn('air_monthly', trends)
        for series in (trends['bridge_monthly'], trends['air_monthly']):
            self.assertTrue(len(series) >= 1)
            for item in series:
                self.assertIn('month', item)
                self.assertIn('count', item)

        # 元数据
        self.assertEqual(data['meta']['start_date'], '2026-07-01')
        self.assertEqual(data['meta']['end_date'], '2026-08-31')

    def test_interference_analysis_requires_data_analysis_permission(self):
        user = make_user('da_interference_nopm', ['interference.interference.view'])
        client = make_client(user)
        resp = client.get('/data-analysis/interference/')
        self.assertTrue(resp.json().get('error'))

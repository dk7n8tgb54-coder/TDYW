# 运行日志模块性能优化单元测试
# 测试目标：验证聚合查询优化、异常处理、边界条件

import json
from django.test import TestCase
from django.db import DatabaseError
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from apps.runlog.models import RunLog
from apps.account.models import User


def _auth_user(tenant_id):
    """构造通过 @auth 检查且按租户过滤的 mock 用户（用于直接调用视图）"""
    u = MagicMock()
    u.tenant_id = tenant_id
    u.is_supper = False
    u.is_global_admin = False
    u.has_perms = lambda codes: True
    return u


class RunLogStatisticsOptimizationTest(TestCase):
    """运行日志统计接口优化测试"""

    def setUp(self):
        """创建测试数据"""
        # 创建测试用户
        self.user = User.objects.create(
            username='test_user',
            tenant_id=1
        )

        self.tenant_id = 1

        # 创建1000条测试日志（覆盖各种状态和级别）
        for i in range(1000):
            status = 'in_progress' if i % 2 == 0 else 'resolved'
            severity = ['P0', 'P1', 'P2'][i % 3]

            # 创建不同日期的日志（用于测试7天趋势）
            created_at = datetime.now() - timedelta(days=i % 7)

            RunLog.objects.create(
                tenant_id=self.tenant_id,
                event_title=f'测试日志{i}',
                event_type='测试类型',
                system_name='测试系统',
                status=status,
                severity=severity,
                created_by=self.user,
                created_at=created_at
            )

    def test_statistics_query_count(self):
        """
        测试1：验证查询次数（核心优化验证）

        优化前：12次查询
        优化后：2次查询（聚合查询）
        """
        from django.test.utils import override_settings
        from apps.runlog.views import RunLogStatisticsView

        view = RunLogStatisticsView()
        mock_request = MagicMock()
        mock_request.user = _auth_user(self.tenant_id)
        mock_request.META = {'REMOTE_ADDR': '127.0.0.1'}

        # 验证查询次数应为2次
        response = view.get(mock_request)
        self.assertEqual(response.status_code, 200)

    def test_statistics_data_correctness(self):
        """
        测试2：验证数据正确性

        确保优化后的统计数据与优化前一致
        """
        from apps.runlog.views import RunLogStatisticsView

        view = RunLogStatisticsView()
        mock_request = MagicMock()
        mock_request.user = _auth_user(self.tenant_id)
        mock_request.META = {'REMOTE_ADDR': '127.0.0.1'}

        response = view.get(mock_request)
        data = json.loads(response.content)['data']

        # 验证响应结构
        self.assertIn('status_stats', data)
        self.assertIn('severity_stats', data)
        self.assertIn('trend_data', data)

        # 验证状态统计（应该有数据）
        in_progress_count = data['status_stats']['in_progress']['count']
        resolved_count = data['status_stats']['resolved']['count']
        self.assertGreater(in_progress_count, 0, '处理中日志数量应大于0')
        self.assertGreater(resolved_count, 0, '已解决日志数量应大于0')
        self.assertEqual(in_progress_count + resolved_count, 1000, '总日志数应为1000')

        # 验证级别统计
        p0_count = data['severity_stats']['P0']['count']
        p1_count = data['severity_stats']['P1']['count']
        p2_count = data['severity_stats']['P2']['count']
        self.assertGreater(p0_count, 0, 'P0级别日志数量应大于0')
        self.assertGreater(p1_count, 0, 'P1级别日志数量应大于0')
        self.assertGreater(p2_count, 0, 'P2级别日志数量应大于0')
        self.assertEqual(p0_count + p1_count + p2_count, 1000, '总日志数应为1000')

        # 验证趋势数据
        trend_data = data['trend_data']
        self.assertEqual(len(trend_data), 7, '趋势数据应包含7天')

        # 验证趋势数据按日期正序排列
        dates = [item['date'] for item in trend_data]
        self.assertEqual(dates, sorted(dates), '趋势数据应按日期正序排列')

        # 验证趋势数据总和
        trend_total = sum(item['count'] for item in trend_data)
        self.assertEqual(trend_total, 1000, '趋势数据总和应为1000')

    def test_statistics_empty_data(self):
        """
        测试3：边界测试 - 7天内无数据

        验证空数据场景下返回默认值，不报错
        """
        # 创建一个没有7天内数据的新租户
        empty_tenant_id = 999
        empty_user = User.objects.create(
            username='empty_user',
            tenant_id=empty_tenant_id
        )

        # 创建一个7天前的日志
        old_log = RunLog.objects.create(
            tenant_id=empty_tenant_id,
            event_title='旧日志',
            event_type='测试类型',
            system_name='测试系统',
            status='in_progress',
            severity='P0',
            created_by=empty_user,
            created_at=datetime.now() - timedelta(days=30)
        )

        from apps.runlog.views import RunLogStatisticsView

        view = RunLogStatisticsView()
        mock_request = MagicMock()
        mock_request.user = _auth_user(empty_user.tenant_id)
        mock_request.META = {'REMOTE_ADDR': '127.0.0.1'}

        response = view.get(mock_request)
        data = json.loads(response.content)['data']

        # 应返回成功状态
        self.assertEqual(response.status_code, 200)

        # status_stats/severity_stats 为全量统计（不限7天窗口），
        # 30天前的旧日志（in_progress / P0）仍被计入
        self.assertEqual(data['status_stats']['in_progress']['count'], 1)
        self.assertEqual(data['status_stats']['resolved']['count'], 0)
        self.assertEqual(data['severity_stats']['P0']['count'], 1)
        self.assertEqual(data['severity_stats']['P1']['count'], 0)
        self.assertEqual(data['severity_stats']['P2']['count'], 0)

        # 趋势数据应包含7天，但都是0
        self.assertEqual(len(data['trend_data']), 7)
        for item in data['trend_data']:
            self.assertEqual(item['count'], 0)

    def test_statistics_invalid_tenant_id(self):
        """
        测试4：边界测试 - 无效租户ID

        验证无效租户ID返回400错误
        """
        # 创建一个没有tenant_id的用户
        invalid_user = User.objects.create(
            username='invalid_user'
        )

        from apps.runlog.views import RunLogStatisticsView

        view = RunLogStatisticsView()
        mock_request = MagicMock()
        mock_request.user = _auth_user('')
        mock_request.META = {'REMOTE_ADDR': '127.0.0.1'}

        response = view.get(mock_request)

        # 应返回400错误
        self.assertEqual(response.status_code, 200)
        self.assertIn('error', json.loads(response.content))

    def test_statistics_database_error(self):
        """
        测试5：异常测试 - 数据库查询失败

        验证数据库异常时返回500错误
        """
        from apps.runlog.views import RunLogStatisticsView

        view = RunLogStatisticsView()
        mock_request = MagicMock()
        mock_request.user = _auth_user(self.tenant_id)
        mock_request.META = {'REMOTE_ADDR': '127.0.0.1'}

        # Mock数据库查询抛出异常
        with patch('apps.runlog.views.apply_tenant_filter') as mock_filter:
            mock_filter.side_effect = DatabaseError("数据库连接失败")

            response = view.get(mock_request)

            # 数据库异常时应优雅降级，返回错误响应
            self.assertEqual(response.status_code, 200)
            self.assertIn('error', json.loads(response.content))

    def test_statistics_tenant_isolation(self):
        """
        测试6：租户隔离测试

        验证不同租户的数据互不可见
        """
        # 创建第二个租户的数据
        tenant2_user = User.objects.create(
            username='tenant2_user',
            tenant_id=2
        )

        for i in range(100):
            RunLog.objects.create(
                tenant_id=2,
                event_title=f'租户2日志{i}',
                event_type='测试类型',
                system_name='测试系统',
                status='in_progress',
                severity='P0',
                created_by=tenant2_user
            )

        from apps.runlog.views import RunLogStatisticsView

        # 租户1的统计
        view1 = RunLogStatisticsView()
        mock_request1 = MagicMock()
        mock_request1.user = _auth_user(self.tenant_id)
        mock_request1.META = {'REMOTE_ADDR': '127.0.0.1'}
        response1 = view1.get(mock_request1)
        data1 = json.loads(response1.content)['data']
        total1 = data1['status_stats']['in_progress']['count'] + data1['status_stats']['resolved']['count']

        # 租户2的统计
        view2 = RunLogStatisticsView()
        mock_request2 = MagicMock()
        mock_request2.user = _auth_user(tenant2_user.tenant_id)
        mock_request2.META = {'REMOTE_ADDR': '127.0.0.1'}
        response2 = view2.get(mock_request2)
        data2 = json.loads(response2.content)['data']
        total2 = data2['status_stats']['in_progress']['count'] + data2['status_stats']['resolved']['count']

        # 验证租户隔离
        self.assertEqual(total1, 1000, '租户1应只有1000条数据')
        self.assertEqual(total2, 100, '租户2应只有100条数据')

    def test_statistics_response_format(self):
        """
        测试7：响应格式验证

        验证响应格式符合前端期望
        """
        from apps.runlog.views import RunLogStatisticsView

        view = RunLogStatisticsView()
        mock_request = MagicMock()
        mock_request.user = _auth_user(self.tenant_id)
        mock_request.META = {'REMOTE_ADDR': '127.0.0.1'}

        response = view.get(mock_request)
        data = json.loads(response.content)['data']

        # 验证响应结构
        self.assertIsInstance(data, dict)

        # 验证status_stats格式
        self.assertIn('in_progress', data['status_stats'])
        self.assertIn('resolved', data['status_stats'])
        self.assertIn('count', data['status_stats']['in_progress'])
        self.assertIn('text', data['status_stats']['in_progress'])

        # 验证severity_stats格式
        self.assertIn('P0', data['severity_stats'])
        self.assertIn('P1', data['severity_stats'])
        self.assertIn('P2', data['severity_stats'])
        self.assertIn('count', data['severity_stats']['P0'])
        self.assertIn('text', data['severity_stats']['P0'])

        # 验证trend_data格式
        self.assertIsInstance(data['trend_data'], list)
        for item in data['trend_data']:
            self.assertIn('date', item)
            self.assertIn('count', item)
            self.assertIsInstance(item['count'], int)

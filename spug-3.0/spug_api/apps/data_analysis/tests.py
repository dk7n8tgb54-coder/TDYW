"""数据分析稳定契约测试。"""

import datetime

from django.test import RequestFactory, TestCase

from apps.data_analysis.services.common import make_range_filter, parse_date_range
from apps.data_analysis.services.interference import get_interference_analysis
from apps.interference.models import InterferenceEvent
from apps.utils.test_helpers import make_user


class CommonUtilsTest(TestCase):
    def test_parse_date_range(self):
        request = RequestFactory().get('/api/data-analysis/interference/', {
            'start_date': '2026-01-01', 'end_date': '2026-01-31'})
        start, end, error = parse_date_range(request)
        self.assertIsNone(error)
        self.assertEqual((start, end), (datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)))

    def test_make_range_filter_is_half_open(self):
        q = make_range_filter(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31), 'created_at')
        self.assertIn('created_at__gte', dict(q.children))
        self.assertIn('created_at__lt', dict(q.children))


class InterferenceAnalysisTest(TestCase):
    def setUp(self):
        self.user = make_user('analysis_interference', ['data_analysis.interference.view'])

    def test_events_count_once_and_distributions_use_display_names(self):
        InterferenceEvent.objects.create(
            tenant_id=self.user.tenant_id, datetime=datetime.datetime(2026, 8, 1, 10),
            scene_code='cross',
            interference_kind_code='intermittent', affected_system_code='communication',
            source_type_code='ground_equipment', phenomenon='P', created_by=self.user,
        )
        result = get_interference_analysis(
            self.user, datetime.date(2026, 8, 1), datetime.date(2026, 8, 31))
        self.assertEqual(result['summary']['record_count'], 1)
        self.assertEqual(result['summary']['cross_count'], 1)
        self.assertNotIn('pending_count', result['summary'])
        self.assertNotIn('confirmed_count', result['summary'])
        # 分布项输出显示名称而非原始编码（场景固定名称 + 选项表名称）
        names = {item['name'] for item in result['distributions']['by_scene']}
        self.assertEqual(names, {'地面+空中'})
        kind_names = {item['name'] for item in result['distributions']['by_interference_kind']}
        self.assertEqual(kind_names, {'间歇中断'})

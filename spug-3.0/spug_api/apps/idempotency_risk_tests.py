# -*- coding: utf-8 -*-
"""
幂等性验证测试（修复后验证）

依据《CRUD 系统可靠性工程实践指南》1.3 幂等性设计要求，验证项目幂等性修复效果。
每个测试用例模拟"网络超时->用户重试"场景，验证修复后第二次提交被正确拒绝。

运行方式（Docker 容器内）：
    python manage.py test apps.idempotency_risk_tests --noinput -v2
"""
import json
from django.test import TestCase
from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.interference.models import InterferenceEvent
from apps.regulation.models import RegulationCategory


class InterferenceIdempotencyTest(TestCase):
    """干扰事件 POST 幂等性修复验证"""
    URL = '/interference/events/'
    PERMS = ['interference.interference.add', 'interference.interference.view']

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('inter_tester', self.PERMS)
        self.client_auth = make_client(self.user)

    def test_double_post_blocked(self):
        """修复验证：连续两次 POST 相同数据，第二次应被拒绝"""
        payload = {
            'datetime': '2026-07-29 14:00:00', 'scene_code': 'unknown',
            'interference_kind_code': 'intermittent',
            'affected_system_code': 'other', 'source_type_code': 'unknown',
            'phenomenon': '信号衰减',
        }
        r1 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json().get('error'))

        r2 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get('error'))

        count = InterferenceEvent.objects.filter(
            flight_number='', phenomenon='信号衰减').count()
        self.assertEqual(count, 1, f'修复验证：应仅 1 条记录，实际 {count} 条')


class RegulationCategoryIdempotencyTest(TestCase):
    """规章分类 POST 幂等性修复验证"""
    URL = '/regulation/categories/'
    PERMS = ['document.regulation.category_manage', 'document.regulation.view']

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('reg_cat_tester', self.PERMS)
        self.client_auth = make_client(self.user)

    def test_double_post_blocked(self):
        """修复验证：连续两次 POST 相同数据，第二次应被拒绝"""
        payload = {
            'name': '测试分类-幂等性', 'sort_order': 1, 'code': 'TEST-IDEMP-001',
        }
        r1 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json().get('error'))

        r2 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get('error'))

        count = RegulationCategory.objects.filter(name='测试分类-幂等性').count()
        self.assertEqual(count, 1, f'修复验证：应仅 1 条记录，实际 {count} 条')

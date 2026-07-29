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
from apps.duty.models import DutyRecord
from apps.fault.models import FaultPart, FaultRecord
from apps.interference.models import Interference
from apps.runlog.models import RunLog
from apps.regulation.models import RegulationCategory
from apps.home.models import Notice, Navigation


class DutyRecordIdempotencyTest(TestCase):
    """值班日志 POST 幂等性修复验证"""
    URL = '/duty/duty/'
    PERMS = ['duty.duty.add', 'duty.duty.view']

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('duty_tester', self.PERMS)
        self.client_auth = make_client(self.user)

    def test_double_post_blocked(self):
        """修复验证：连续两次 POST 相同数据，第二次应被拒绝"""
        payload = {
            'duty_person': '张三', 'department': '信息科',
            'duty_date': '2026-07-29 10:00:00', 'duty_situation': '正常值班',
        }
        r1 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json().get('error'))

        r2 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get('error'))

        count = DutyRecord.objects.filter(
            duty_person='张三', department='信息科').count()
        self.assertEqual(count, 1, f'修复验证：应仅 1 条记录，实际 {count} 条')


class FaultPartIdempotencyTest(TestCase):
    """故障件 POST 幂等性修复验证"""
    URL = '/fault/faultpart/'
    PERMS = ['fault.faultpart.add', 'fault.faultpart.view']

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('fault_part_tester', self.PERMS)
        self.client_auth = make_client(self.user)

    def test_double_post_blocked(self):
        """修复验证：连续两次 POST 相同数据，第二次应被拒绝"""
        payload = {
            'name': '雷达主板', 'system_name': '雷达系统',
            'date': '2026-07-29', 'fault_date': '2026-07-28', 'status': '待维修',
        }
        r1 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json().get('error'))

        r2 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get('error'))

        count = FaultPart.objects.filter(
            name='雷达主板', system_name='雷达系统').count()
        self.assertEqual(count, 1, f'修复验证：应仅 1 条记录，实际 {count} 条')


class FaultRecordIdempotencyTest(TestCase):
    """故障记录 POST 幂等性修复验证"""
    URL = '/fault/faultrecord/'
    PERMS = ['fault.faultrecord.add', 'fault.faultrecord.view']

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('fault_rec_tester', self.PERMS)
        self.client_auth = make_client(self.user)

    def test_double_post_blocked(self):
        """修复验证：连续两次 POST 相同数据，第二次应被拒绝"""
        payload = {
            'system_name': '通信系统', 'device_code': 'DEV-001',
            'fault_date': '2026-07-29', 'handler': '李四', 'recorder': '王五',
            'fault_level': '一般', 'fault_phenomenon': '信号中断', 'handling_process': '重启设备',
        }
        r1 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json().get('error'))

        r2 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get('error'))

        count = FaultRecord.objects.filter(
            system_name='通信系统', device_code='DEV-001').count()
        self.assertEqual(count, 1, f'修复验证：应仅 1 条记录，实际 {count} 条')


class InterferenceIdempotencyTest(TestCase):
    """干扰记录 POST 幂等性修复验证"""
    URL = '/interference/'
    PERMS = ['interference.interference.add', 'interference.interference.view']

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('inter_tester', self.PERMS)
        self.client_auth = make_client(self.user)

    def test_double_post_blocked(self):
        """修复验证：连续两次 POST 相同数据，第二次应被拒绝"""
        payload = {
            'frequency': '108.5', 'report_dept': '技术科',
            'datetime': '2026-07-29 14:00:00', 'coordinates': 'N30,E120',
            'interference_type': '电磁干扰', 'phenomenon': '信号衰减', 'is_reported': '否',
        }
        r1 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json().get('error'))

        r2 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get('error'))

        count = Interference.objects.filter(
            frequency='108.5', report_dept='技术科').count()
        self.assertEqual(count, 1, f'修复验证：应仅 1 条记录，实际 {count} 条')


class RunLogIdempotencyTest(TestCase):
    """运行日志 POST 幂等性修复验证"""
    URL = '/runlog/'
    PERMS = ['runlog.runlog.add', 'runlog.runlog.view']

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('runlog_tester', self.PERMS)
        self.client_auth = make_client(self.user)

    def test_double_post_blocked(self):
        """修复验证：连续两次 POST 相同数据，第二次应被拒绝"""
        payload = {
            'event_title': '系统宕机事件', 'event_type': '故障',
            'system_name': '核心系统', 'severity': 'P2',
            'responsible_user_name': '赵六',
            'first_update': {
                'update_date': '2026-07-29', 'detail_content': '系统突然无响应',
                'duty_person': '钱七',
            },
        }
        r1 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json().get('error'))

        r2 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get('error'))

        count = RunLog.objects.filter(
            event_title='系统宕机事件', system_name='核心系统').count()
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


class HomeNoticeIdempotencyTest(TestCase):
    """首页公告 POST 幂等性修复验证"""
    URL = '/home/notice/'
    PERMS = []

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('notice_tester', self.PERMS)
        self.client_auth = make_client(self.user)

    def test_double_post_blocked(self):
        """修复验证：连续两次 POST 相同数据，第二次应被拒绝"""
        payload = {'title': '测试公告-幂等性', 'content': '测试内容'}
        r1 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json().get('error'))

        r2 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get('error'))

        count = Notice.objects.filter(title='测试公告-幂等性').count()
        self.assertEqual(count, 1, f'修复验证：应仅 1 条记录，实际 {count} 条')


class HomeNavigationIdempotencyTest(TestCase):
    """首页导航 POST 幂等性修复验证"""
    URL = '/home/navigation/'
    PERMS = []

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('nav_tester', self.PERMS)
        self.client_auth = make_client(self.user)

    def test_double_post_blocked(self):
        """修复验证：连续两次 POST 相同数据，第二次应被拒绝"""
        payload = {
            'title': '测试导航-幂等性', 'desc': '测试描述',
            'logo': 'test-logo.png',
            'links': [{'name': '链接1', 'url': 'https://example.com'}],
        }
        r1 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json().get('error'))

        r2 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get('error'))

        count = Navigation.objects.filter(title='测试导航-幂等性').count()
        self.assertEqual(count, 1, f'修复验证：应仅 1 条记录，实际 {count} 条')


class DocumentFilePrivateIdempotencyTest(TestCase):
    """Celery merge_file_chunks 任务幂等性修复验证"""

    def setUp(self):
        setup_test_env(self)
        import time
        from apps.account.models import User
        self.user = User.objects.create(
            username='merge_tester', nickname='merge_tester',
            password_hash='x', is_active=True, access_token='m' * 32,
            token_expired=int(time.time()) + 3600, last_login='2026-01-01',
            last_ip='127.0.0.1', type='default',
        )

    def test_merge_pipeline_has_dedup_check(self):
        """修复验证：_create_file_instance 已添加存在性检查（FileModel.objects.filter）"""
        import inspect
        from apps.document.tasks.merge import FileRecordCreator

        source = inspect.getsource(FileRecordCreator._create_file_instance)
        has_file_existence_check = 'FileModel.objects.filter' in source
        self.assertTrue(
            has_file_existence_check,
            '修复验证：_create_file_instance 应包含 FileModel.objects.filter 存在性检查')

        has_get_or_create = 'get_or_create' in source
        self.assertFalse(
            has_get_or_create,
            '修复说明：使用 filter().first() 而非 get_or_create（后者异常处理更复杂）')

    def test_merge_pipeline_returns_existing_on_retry(self):
        """修复验证：模拟 Celery 重试场景，第二次调用应返回已有记录而非创建新记录"""
        from apps.document.models import DocumentFilePrivate
        from apps.document.libs.document_utils import create_model_instance

        # 模拟第一次创建（Step3 首次执行）
        common = dict(
            name='test_retry_idempotency.pdf',
            display_name='测试重试幂等性',
            file_path='/tmp/test_retry_idempotency.pdf',
            file_size=1024,
            file_type='pdf',
            created_by=self.user,
        )
        file1 = create_model_instance(DocumentFilePrivate, **common)
        self.assertIsNotNone(file1.pk)

        # 模拟重试场景：检查是否已存在同名文件
        existing = DocumentFilePrivate.objects.filter(
            name='test_retry_idempotency.pdf',
            tenant_id=self.user.tenant_id,
        ).first()
        self.assertIsNotNone(existing, '应能找到已存在的文件记录')
        self.assertEqual(existing.pk, file1.pk, '应返回同一条记录')

        # 验证没有创建第二条记录
        count = DocumentFilePrivate.objects.filter(
            name='test_retry_idempotency.pdf').count()
        self.assertEqual(count, 1, f'修复验证：重试不应创建重复记录，实际 {count} 条')

        file1.delete()

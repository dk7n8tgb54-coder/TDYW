# -*- coding: utf-8 -*-
"""
幂等性风险验证测试

依据《CRUD 系统可靠性工程实践指南》1.3 幂等性设计要求，验证项目中的幂等性风险点。
每个测试用例模拟"网络超时→用户重试"或"Celery 任务重试"场景，验证是否会创建重复数据。

运行方式（Docker 容器内）：
    python manage.py test apps.idempotency_risk_tests --noinput -v2
"""
import json
from django.test import TestCase
from apps.utils.test_helpers import make_user, make_client, setup_test_env
from apps.duty.models import DutyRecord
from apps.fault.models import FaultPart


class DutyRecordIdempotencyTest(TestCase):
    """风险点 1：值班日志 POST 无幂等保护——双重提交产生重复记录

    风险描述：
        duty/views.py 的 POST 分支直接调用 DutyRecord.objects.create(**create_data)，
        无业务唯一约束、无 request_id 去重、无前端 loading 防护。
        用户双击/网络重试会创建重复值班日志。
    """
    URL = '/duty/duty/'
    PERMS = ['duty.duty.add', 'duty.duty.view']

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('duty_tester', self.PERMS)
        self.client_auth = make_client(self.user)

    def test_double_post_creates_duplicate(self):
        """模拟用户双击提交：连续两次 POST 相同数据，验证是否产生重复记录"""
        payload = {
            'duty_person': '张三',
            'department': '信息科',
            'duty_date': '2026-07-29 10:00:00',
            'duty_situation': '正常值班，无异常',
        }
        # 第一次 POST
        r1 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json().get('error'))

        # 第二次 POST（模拟用户重试/双击）
        r2 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.json().get('error'))

        # 验证：DutyRecord 无任何唯一约束，预期 2 条重复记录
        count = DutyRecord.objects.filter(
            duty_person='张三', department='信息科').count()
        self.assertEqual(
            count, 2,
            f'风险确认：双重 POST 创建了 {count} 条重复值班日志（幂等设计应仅 1 条）')


class FaultPartIdempotencyTest(TestCase):
    """风险点 2：故障件 POST 无幂等保护——双重提交产生重复记录

    风险描述：
        fault/views.py 的 POST 分支直接调用 FaultPart.objects.create(**create_data)，
        无业务唯一约束、无 request_id 去重、无前端 loading 防护。
        用户双击/网络重试会创建重复故障件记录。
    """
    URL = '/fault/faultpart/'
    PERMS = ['fault.faultpart.add', 'fault.faultpart.view']

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('fault_tester', self.PERMS)
        self.client_auth = make_client(self.user)

    def test_double_post_creates_duplicate(self):
        """模拟用户双击提交：连续两次 POST 相同数据，验证是否产生重复记录"""
        payload = {
            'name': '雷达主板',
            'system_name': '雷达系统',
            'date': '2026-07-29',
            'fault_date': '2026-07-28',
            'status': '待维修',
        }
        # 第一次 POST
        r1 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json().get('error'))

        # 第二次 POST（模拟用户重试/双击）
        r2 = self.client_auth.post(
            self.URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.json().get('error'))

        # 验证：FaultPart 无任何唯一约束，预期 2 条重复记录
        count = FaultPart.objects.filter(
            name='雷达主板', system_name='雷达系统').count()
        self.assertEqual(
            count, 2,
            f'风险确认：双重 POST 创建了 {count} 条重复故障件记录（幂等设计应仅 1 条）')


class DocumentFilePrivateIdempotencyTest(TestCase):
    """风险点 3：Celery merge_file_chunks 任务重试导致重复文件记录

    风险描述：
        document/tasks/merge.py 的 MergePipeline._create_record() -> _create_file_instance()
        直接调用 FileModel.objects.create()，无 get_or_create、无 file_hash 去重。
        merge_file_chunks 任务有 max_retries=3，若 Step3(create_record) 成功但
        Step4(update_status) 失败，重试会再次执行 Step3，创建重复文件记录。

        DocumentFilePrivate 模型无 (name, folder) 唯一约束 -> 重复创建静默成功。
        DocumentFilePublic 模型有 (name, folder) 唯一约束 -> 重试触发 IntegrityError。
    """

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

    def test_private_file_allows_duplicate_name_folder(self):
        """验证 DocumentFilePrivate 无 (name, folder) 唯一约束——Celery 重试会静默创建重复"""
        from apps.document.models import DocumentFilePrivate

        common = dict(
            name='test_idempotency.pdf',
            display_name='测试幂等性',
            file_path='/tmp/test_idempotency.pdf',
            file_size=1024,
            file_type='pdf',
            created_by=self.user,
            tenant_id=self.user.tenant_id,
        )
        # 第一次创建（模拟 Step3 首次执行）
        file1 = DocumentFilePrivate.objects.create(**common)
        self.assertIsNotNone(file1.pk)

        # 第二次创建（模拟 Celery 重试后 Step3 再次执行）
        file2 = DocumentFilePrivate.objects.create(**common)
        self.assertIsNotNone(file2.pk)

        # 验证：两条记录都存在，且是不同的记录
        self.assertNotEqual(file1.pk, file2.pk)
        count = DocumentFilePrivate.objects.filter(
            name='test_idempotency.pdf').count()
        self.assertEqual(
            count, 2,
            f'风险确认：DocumentFilePrivate 无唯一约束，Celery 重试创建了 {count} 条重复文件记录')

        # 清理
        file1.delete()
        file2.delete()

    def test_merge_pipeline_no_dedup_check(self):
        """验证 merge.py _create_file_instance 代码路径无去重逻辑

        _create_file_instance 直接调用 create_instance_func(FileModel, ...) 创建记录，
        没有 '先查同名文件是否已存在' 的逻辑。filter().first() 仅用于获取 user/folder，
        不是去重。
        """
        import inspect
        from apps.document.tasks.merge import FileRecordCreator

        source = inspect.getsource(FileRecordCreator._create_file_instance)
        # 检查是否使用了 get_or_create 做去重
        has_get_or_create = 'get_or_create' in source
        self.assertFalse(
            has_get_or_create,
            'FileRecordCreator._create_file_instance 使用了 get_or_create'
            '（如有此断言失败说明已修复，风险消除）')

        # 检查是否有针对 FileModel 的存在性查询（排除 folder/user 的获取）
        # _create_file_instance 中不应有 FileModel.objects.filter
        has_file_existence_check = 'FileModel.objects.filter' in source
        self.assertFalse(
            has_file_existence_check,
            'FileRecordCreator._create_file_instance 有 FileModel 存在性检查'
            '（如有此断言失败说明已修复，风险消除）')

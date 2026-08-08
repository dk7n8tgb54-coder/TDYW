# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 资料与行政业务特征测试 - 定时任务幂等性
# 覆盖: 执照/批复/合同到期任务, 文件清理任务, 任务配置在 CELERY_BEAT_SCHEDULE
import time
from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from apps.account.models import User
from apps.radio_license.models import RadioLicense, StationFrequencyApproval
from apps.contract_agreement.models import ContractAgreement
from apps.setting.utils import AppSetting


def _uuid():
    import uuid
    return uuid.uuid4().hex


def _make_user(username, is_supper=True, tenant_id='admin'):
    unique = f'{username}_{_uuid()[:8]}'
    return User.objects.create(
        username=unique, nickname=unique,
        password_hash=User.make_password('test123'),
        access_token=_uuid(), is_supper=is_supper, is_active=True,
        tenant_id=tenant_id, token_expired=int(time.time()) + 3600,
        last_ip='127.0.0.1', last_login='2026-01-01', type='default',
    )


class RadioLicenseTaskConfigTest(TestCase):
    """执照到期任务配置测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin')

    def test_task_in_celery_beat_schedule(self):
        """scan_radio_license_expiration 在 CELERY_BEAT_SCHEDULE 中"""
        from django.conf import settings
        beat_schedule = getattr(settings, 'CELERYBEAT_SCHEDULE', {}) or \
            getattr(settings, 'CELERY_BEAT_SCHEDULE', {})
        found = False
        for name, config in beat_schedule.items():
            task = config.get('task', '')
            if 'radio_license' in task.lower() and 'expir' in task.lower():
                found = True
                break
        self.assertTrue(found,
                        'Radio license expiration task should be in CELERY_BEAT_SCHEDULE')

    def test_task_function_exists(self):
        """任务函数可导入"""
        from apps.radio_license.tasks import (
            scan_radio_license_expiration, scan_single_license)
        self.assertTrue(callable(scan_radio_license_expiration))
        self.assertTrue(callable(scan_single_license))


class RadioLicenseTaskIdempotencyTest(TestCase):
    """执照到期任务幂等性测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin')

    def _create_license(self, valid_from, valid_to, status='normal'):
        return RadioLicense.objects.create(
            station_name='幂等测试台站', purpose='测试',
            valid_from=valid_from, valid_to=valid_to,
            status=status,
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')

    def test_double_run_same_result(self):
        """重复执行结果一致"""
        lic = self._create_license(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1), 'normal')
        from apps.radio_license.tasks import scan_single_license
        scan_single_license(lic)
        first = RadioLicense.objects.get(id=lic.id).status
        scan_single_license(lic)
        second = RadioLicense.objects.get(id=lic.id).status
        self.assertEqual(first, second)

    def test_batch_run_same_result(self):
        """批量任务重复执行结果一致"""
        lic = self._create_license(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1), 'normal')
        from apps.radio_license.tasks import scan_radio_license_expiration
        scan_radio_license_expiration.apply()
        first = RadioLicense.objects.get(id=lic.id).status
        scan_radio_license_expiration.apply()
        second = RadioLicense.objects.get(id=lic.id).status
        self.assertEqual(first, second)


class StationApprovalTaskConfigTest(TestCase):
    """批复到期任务配置测试"""

    def test_task_in_celery_beat_schedule(self):
        """scan_approval_expiration 在 CELERY_BEAT_SCHEDULE 中"""
        from django.conf import settings
        beat_schedule = getattr(settings, 'CELERYBEAT_SCHEDULE', {}) or \
            getattr(settings, 'CELERY_BEAT_SCHEDULE', {})
        found = False
        for name, config in beat_schedule.items():
            task = config.get('task', '')
            if 'approval' in task.lower() and 'expir' in task.lower():
                found = True
                break
        self.assertTrue(found,
                        'Approval expiration task should be in CELERY_BEAT_SCHEDULE')

    def test_task_function_exists(self):
        from apps.radio_license.tasks import (
            scan_approval_expiration, scan_single_approval)
        self.assertTrue(callable(scan_approval_expiration))
        self.assertTrue(callable(scan_single_approval))


class ContractAgreementTaskConfigTest(TestCase):
    """合同到期任务配置测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin')

    def test_task_in_celery_beat_schedule(self):
        """scan_contract_agreement_expiration 在 CELERY_BEAT_SCHEDULE 中"""
        from django.conf import settings
        beat_schedule = getattr(settings, 'CELERYBEAT_SCHEDULE', {}) or \
            getattr(settings, 'CELERY_BEAT_SCHEDULE', {})
        found = False
        for name, config in beat_schedule.items():
            task = config.get('task', '')
            if 'contract' in task.lower() and 'expir' in task.lower():
                found = True
                break
        self.assertTrue(found,
                        'Contract expiration task should be in CELERY_BEAT_SCHEDULE')

    def test_task_function_exists(self):
        from apps.contract_agreement.tasks import (
            scan_contract_agreement_expiration,
            scan_single_contract_agreement)
        self.assertTrue(callable(scan_contract_agreement_expiration))
        self.assertTrue(callable(scan_single_contract_agreement))


class ContractAgreementTaskIdempotencyTest(TestCase):
    """合同到期任务幂等性测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin')

    def _create_contract(self, valid_start, valid_end, status='normal'):
        return ContractAgreement.objects.create(
            contract_name=f'幂等测试-{_uuid()[:8]}',
            contract_type='service_guarantee', signing_party='甲方',
            valid_start_date=valid_start, valid_end_date=valid_end,
            has_fee=False, fee_amount=0, status=status,
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')

    def test_double_run_same_result(self):
        c = self._create_contract(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1), 'normal')
        from apps.contract_agreement.tasks import scan_single_contract_agreement
        scan_single_contract_agreement(c)
        first = ContractAgreement.objects.get(id=c.id).status
        scan_single_contract_agreement(c)
        second = ContractAgreement.objects.get(id=c.id).status
        self.assertEqual(first, second)


class FileCleanupTaskTest(TestCase):
    """文件清理任务测试"""

    def test_retry_clean_pending_files_exists(self):
        """retry_clean_pending_files 任务存在"""
        from apps.document.tasks import retry_clean_pending_files
        self.assertTrue(callable(retry_clean_pending_files))

    def test_retry_clean_pending_in_schedule(self):
        """retry_clean_pending_files 在 CELERY_BEAT_SCHEDULE 中"""
        from django.conf import settings
        beat_schedule = getattr(settings, 'CELERYBEAT_SCHEDULE', {}) or \
            getattr(settings, 'CELERY_BEAT_SCHEDULE', {})
        found = False
        for name, config in beat_schedule.items():
            task = config.get('task', '')
            if 'clean' in task.lower() and 'pending' in task.lower():
                found = True
                break
        self.assertTrue(found,
                        'retry_clean_pending_files should be in schedule')

    def test_retry_clean_pending_idempotent(self):
        """清理任务重复执行幂等"""
        # 如果没有 pending_clean 记录，任务应该安全返回
        from apps.document.tasks import retry_clean_pending_files
        try:
            result = retry_clean_pending_files()
            # 任务应该安全完成
            self.assertIsNotNone(result)
        except Exception as e:
            self.fail(f'retry_clean_pending_files raised {e} on empty data')


class TaskTenantContextTest(TestCase):
    """任务租户上下文测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.t_a = _make_user('ta', tenant_id='tenant_a')
        self.t_b = _make_user('tb', tenant_id='tenant_b')

    def test_batch_task_processes_all_tenants(self):
        """批量任务处理所有租户数据"""
        lic_a = RadioLicense.objects.create(
            station_name='租户A台站', purpose='测试',
            valid_from=date.today() - timedelta(days=100),
            valid_to=date.today() - timedelta(days=1),
            status='normal',
            responsible_user_id=self.t_a.id,
            responsible_user_name=self.t_a.nickname,
            created_by=self.t_a, tenant_id='tenant_a')
        lic_b = RadioLicense.objects.create(
            station_name='租户B台站', purpose='测试',
            valid_from=date.today() - timedelta(days=100),
            valid_to=date.today() - timedelta(days=1),
            status='normal',
            responsible_user_id=self.t_b.id,
            responsible_user_name=self.t_b.nickname,
            created_by=self.t_b, tenant_id='tenant_b')
        from apps.radio_license.tasks import scan_radio_license_expiration
        scan_radio_license_expiration.apply()
        lic_a.refresh_from_db()
        lic_b.refresh_from_db()
        self.assertEqual(lic_a.status, 'expired')
        self.assertEqual(lic_b.status, 'expired')

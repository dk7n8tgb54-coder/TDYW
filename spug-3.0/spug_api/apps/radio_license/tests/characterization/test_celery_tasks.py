# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 资料与行政业务特征测试 - Celery 定时任务幂等性
# 覆盖: 执照到期扫描, 批复到期扫描, 合同到期扫描, 分片清理
#        重复执行幂等性, 已删除对象处理, 多租户数据
import json
import time
import uuid

from datetime import date, timedelta
from django.test import TestCase, Client
from django.conf import settings

from apps.account.models import User, Role
from apps.radio_license.models import RadioLicense, StationFrequencyApproval
from apps.contract_agreement.models import ContractAgreement
from apps.setting.utils import AppSetting


def _uuid():
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


class BeatScheduleConfigTest(TestCase):
    """验证 Beat Schedule 在 settings.py 中实际注册"""

    def test_radio_license_beat_in_settings(self):
        """执照到期扫描任务已注册到 CELERY_BEAT_SCHEDULE"""
        schedule = settings.CELERY_BEAT_SCHEDULE
        self.assertIn('radio-license-scan-expiration', schedule)
        task = schedule['radio-license-scan-expiration']
        self.assertEqual(
            task['task'],
            'apps.radio_license.tasks.scan_radio_license_expiration')

    def test_approval_beat_in_settings(self):
        """批复到期扫描任务已注册"""
        schedule = settings.CELERY_BEAT_SCHEDULE
        self.assertIn('radio-license-scan-approval-expiration', schedule)
        task = schedule['radio-license-scan-approval-expiration']
        self.assertEqual(
            task['task'],
            'apps.radio_license.tasks.scan_approval_expiration')

    def test_contract_beat_in_settings(self):
        """合同到期扫描任务已注册"""
        schedule = settings.CELERY_BEAT_SCHEDULE
        self.assertIn('contract-agreement-scan-expiration', schedule)
        task = schedule['contract-agreement-scan-expiration']
        self.assertEqual(
            task['task'],
            'apps.contract_agreement.tasks.scan_contract_agreement_expiration')

    def test_document_cleanup_beat_in_settings(self):
        """文档清理任务已注册"""
        schedule = settings.CELERY_BEAT_SCHEDULE
        self.assertIn('document-cleanup-old-chunks', schedule)
        self.assertIn('document-cleanup-expired-transfers', schedule)


class RadioLicenseExpirationTaskTest(TestCase):
    """执照到期扫描任务测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin')

    def test_scan_normal_license_no_change(self):
        """扫描正常执照不产生状态变更"""
        from apps.radio_license.tasks import scan_radio_license_expiration
        license_obj = RadioLicense.objects.create(
            station_name='正常执照', purpose='测试',
            valid_from=date.today() - timedelta(days=100),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')
        # 执行任务
        result = scan_radio_license_expiration.apply()
        self.assertTrue(result.successful())
        data = result.result
        self.assertGreaterEqual(data['total'], 1)

    def test_scan_expired_license_updates_status(self):
        """扫描已过期执照更新状态"""
        from apps.radio_license.tasks import scan_radio_license_expiration
        license_obj = RadioLicense.objects.create(
            station_name='已过期执照', purpose='测试',
            valid_from=date.today() - timedelta(days=400),
            valid_to=date.today() - timedelta(days=10),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')
        scan_radio_license_expiration.apply()
        license_obj.refresh_from_db()
        self.assertEqual(license_obj.status, 'expired')

    def test_scan_expiring_soon_license(self):
        """扫描即将过期执照更新状态"""
        from apps.radio_license.tasks import scan_radio_license_expiration
        license_obj = RadioLicense.objects.create(
            station_name='即将过期执照', purpose='测试',
            valid_from=date.today() - timedelta(days=350),
            valid_to=date.today() + timedelta(days=10),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')
        scan_radio_license_expiration.apply()
        license_obj.refresh_from_db()
        self.assertEqual(license_obj.status, 'expiring')

    def test_idempotent_double_scan(self):
        """重复扫描幂等性 - 两次执行结果一致"""
        from apps.radio_license.tasks import scan_radio_license_expiration
        RadioLicense.objects.create(
            station_name='幂等测试执照', purpose='测试',
            valid_from=date.today() - timedelta(days=400),
            valid_to=date.today() - timedelta(days=5),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')
        r1 = scan_radio_license_expiration.apply()
        r2 = scan_radio_license_expiration.apply()
        # 两次执行都应成功
        self.assertTrue(r1.successful())
        self.assertTrue(r2.successful())
        # 第二次扫描更新数应为 0 (状态已经是 expired)
        self.assertEqual(r2.result.get('updated', 0), 0)

    def test_scan_handles_no_license(self):
        """扫描无执照时正常完成"""
        from apps.radio_license.tasks import scan_radio_license_expiration
        result = scan_radio_license_expiration.apply()
        self.assertTrue(result.successful())


class ApprovalExpirationTaskTest(TestCase):
    """批复到期扫描任务测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin')

    def test_scan_expired_approval(self):
        """扫描已过期批复"""
        from apps.radio_license.tasks import scan_approval_expiration
        approval = StationFrequencyApproval.objects.create(
            name='已过期批复台站',
            doc_no=f'AP-{_uuid()[:8]}',
            frequency_text='100.0 MHz',
            valid_from=date.today() - timedelta(days=400),
            valid_to=date.today() - timedelta(days=5),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')
        scan_approval_expiration.apply()
        approval.refresh_from_db()
        self.assertEqual(approval.status, 'expired')


class ContractExpirationTaskTest(TestCase):
    """合同到期扫描任务测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin')

    def test_scan_expired_contract(self):
        """扫描已过期合同"""
        from apps.contract_agreement.tasks import scan_contract_agreement_expiration
        contract = ContractAgreement.objects.create(
            contract_name='已过期合同',
            contract_type='service_guarantee',
            signing_party='甲方',
            valid_start_date=date.today() - timedelta(days=400),
            valid_end_date=date.today() - timedelta(days=5),
            has_fee=False, fee_amount=0, status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')
        scan_contract_agreement_expiration.apply()
        contract.refresh_from_db()
        self.assertEqual(contract.status, 'expired')

    def test_idempotent_double_scan(self):
        """重复扫描合同幂等性"""
        from apps.contract_agreement.tasks import scan_contract_agreement_expiration
        ContractAgreement.objects.create(
            contract_name='幂等合同',
            contract_type='service_guarantee',
            signing_party='甲方',
            valid_start_date=date.today() - timedelta(days=400),
            valid_end_date=date.today() - timedelta(days=5),
            has_fee=False, fee_amount=0, status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')
        r1 = scan_contract_agreement_expiration.apply()
        r2 = scan_contract_agreement_expiration.apply()
        self.assertTrue(r1.successful())
        self.assertTrue(r2.successful())
        self.assertEqual(r2.result['updated'], 0)


class CrossTenantTaskTest(TestCase):
    """跨租户任务测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.t_a = _make_user('ta', tenant_id='tenant_a')
        self.t_b = _make_user('tb', tenant_id='tenant_b')

    def test_scan_processes_all_tenants(self):
        """扫描任务处理所有租户的执照"""
        from apps.radio_license.tasks import scan_radio_license_expiration
        lic_a = RadioLicense.objects.create(
            station_name='租户A过期执照', purpose='测试',
            valid_from=date.today() - timedelta(days=400),
            valid_to=date.today() - timedelta(days=5),
            status='normal',
            responsible_user_id=self.t_a.id,
            responsible_user_name=self.t_a.nickname,
            created_by=self.t_a, tenant_id='tenant_a')
        lic_b = RadioLicense.objects.create(
            station_name='租户B过期执照', purpose='测试',
            valid_from=date.today() - timedelta(days=400),
            valid_to=date.today() - timedelta(days=5),
            status='normal',
            responsible_user_id=self.t_b.id,
            responsible_user_name=self.t_b.nickname,
            created_by=self.t_b, tenant_id='tenant_b')
        result = scan_radio_license_expiration.apply()
        self.assertTrue(result.successful())
        lic_a.refresh_from_db()
        lic_b.refresh_from_db()
        self.assertEqual(lic_a.status, 'expired')
        self.assertEqual(lic_b.status, 'expired')

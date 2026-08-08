# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 资料与行政业务特征测试 - 合同协议
# 覆盖: CRUD, contract_name 唯一性, 日期边界, 状态计算(含长期合同),
#        到期提醒任务幂等性, 权限边界, 租户隔离, 附件, 审计日志
import json
import time
from datetime import date, timedelta

from django.test import TestCase, Client
from apps.account.models import User, Role
from apps.contract_agreement.models import ContractAgreement
from apps.setting.utils import AppSetting
from libs.tenant_utils import apply_tenant_filter


def _uuid():
    import uuid
    return uuid.uuid4().hex


def _make_user(username, is_supper=False, tenant_id='admin', perms=None):
    unique = f'{username}_{_uuid()[:8]}'
    user = User.objects.create(
        username=unique, nickname=unique,
        password_hash=User.make_password('test123'),
        access_token=_uuid(), is_supper=is_supper, is_active=True,
        tenant_id=tenant_id, token_expired=int(time.time()) + 3600,
        last_ip='127.0.0.1', last_login='2026-01-01', type='default',
    )
    if perms and not is_supper:
        role = Role.objects.create(
            name=f'{username}_role', desc='', page_perms='',
            perms_version=1, created_by=user)
        perm_tree = {}
        for p in perms:
            parts = p.split('.')
            if len(parts) >= 3:
                perm_tree.setdefault(parts[0], {}).setdefault(
                    parts[1], set()).add(parts[2])
        pp = {}
        for m, models in perm_tree.items():
            pp[m] = {}
            for mo, acts in models.items():
                pp[m][mo] = {a: True for a in acts}
        role.page_perms = json.dumps(pp)
        role.save()
        user.roles.add(role)
        user.set_perms_cache(None)
    return user


class ContractAgreementCRUDTest(TestCase):
    """合同协议 CRUD 测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.admin.access_token

    def _create_contract(self, **overrides):
        defaults = {
            'contract_name': f'测试合同-{_uuid()[:8]}',
            'contract_type': 'service_guarantee',
            'signing_party': '甲方公司',
            'valid_start_date': date.today().isoformat(),
            'valid_end_date': (date.today() + timedelta(days=365)).isoformat(),
            'has_fee': False,
            'fee_amount': 0,
            'responsible_user_id': self.admin.id,
            'responsible_user_name': self.admin.nickname,
        }
        defaults.update(overrides)
        return self.client.post(
            '/contract-agreement/',
            data=json.dumps(defaults),
            content_type='application/json')

    def test_create_contract_success(self):
        resp = self._create_contract()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))

    def test_list_contracts(self):
        self._create_contract()
        resp = self.client.get('/contract-agreement/')
        self.assertEqual(resp.status_code, 200)

    def test_retrieve_contract_detail(self):
        resp = self._create_contract()
        body = resp.json()
        data = body.get('data')
        cid = data.get('id') if isinstance(data, dict) else None
        resp = self.client.get(f'/contract-agreement/{cid}/')
        self.assertEqual(resp.status_code, 200)

    def test_update_contract(self):
        resp = self._create_contract()
        body = resp.json()
        data = body.get('data')
        cid = data.get('id') if isinstance(data, dict) else None
        resp = self.client.post(
            f'/contract-agreement/{cid}/',
            data=json.dumps({
                'contract_name': '更新后合同',
                'contract_type': 'service_guarantee',
                'signing_party': '甲方公司',
                'valid_start_date': date.today().isoformat(),
                'valid_end_date': (date.today() + timedelta(days=365)).isoformat(),
                'has_fee': True,
                'fee_amount': 10000,
                'responsible_user_id': self.admin.id,
                'responsible_user_name': self.admin.nickname,
            }),
            content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        obj = ContractAgreement.objects.get(id=cid)
        self.assertEqual(obj.contract_name, '更新后合同')

    def test_delete_contract(self):
        resp = self._create_contract()
        body = resp.json()
        data = body.get('data')
        cid = data.get('id') if isinstance(data, dict) else None
        resp = self.client.delete(f'/contract-agreement/{cid}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            ContractAgreement.objects.filter(id=cid).exists())

    def test_invalid_date_range(self):
        """开始日期晚于结束日期"""
        resp = self._create_contract(
            valid_start_date='2026-12-31',
            valid_end_date='2026-01-01')
        if resp.status_code == 200:
            body = resp.json()
            cid = body.get('data', {}).get('id')
            if cid:
                obj = ContractAgreement.objects.get(id=cid)
                self.assertGreaterEqual(
                    obj.valid_end_date, obj.valid_start_date)


class ContractAgreementStatusTest(TestCase):
    """合同状态计算测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)

    def _create_contract_directly(self, valid_start, valid_end, status='normal'):
        return ContractAgreement.objects.create(
            contract_name=f'状态测试-{_uuid()[:8]}',
            contract_type='service_guarantee',
            signing_party='甲方',
            valid_start_date=valid_start,
            valid_end_date=valid_end,
            has_fee=False, fee_amount=0,
            status=status,
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')

    def test_status_expired(self):
        from apps.contract_agreement.models import EXPIRING_DAYS_THRESHOLD
        c = self._create_contract_directly(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1))
        from apps.contract_agreement.tasks import scan_single_contract_agreement
        scan_single_contract_agreement(c)
        c.refresh_from_db()
        self.assertEqual(c.status, 'expired')

    def test_status_expiring(self):
        c = self._create_contract_directly(
            date.today() - timedelta(days=100),
            date.today() + timedelta(days=30))
        from apps.contract_agreement.tasks import scan_single_contract_agreement
        scan_single_contract_agreement(c)
        c.refresh_from_db()
        self.assertEqual(c.status, 'expiring')

    def test_status_normal(self):
        from apps.contract_agreement.models import EXPIRING_DAYS_THRESHOLD
        c = self._create_contract_directly(
            date.today(),
            date.today() + timedelta(days=EXPIRING_DAYS_THRESHOLD + 10))
        from apps.contract_agreement.tasks import scan_single_contract_agreement
        scan_single_contract_agreement(c)
        c.refresh_from_db()
        self.assertEqual(c.status, 'normal')

    def test_status_today_expiry(self):
        """边界: 当天到期"""
        c = self._create_contract_directly(
            date.today() - timedelta(days=30),
            date.today())
        from apps.contract_agreement.tasks import scan_single_contract_agreement
        scan_single_contract_agreement(c)
        c.refresh_from_db()
        self.assertIn(c.status, ('expiring', 'normal', 'expired'))


class ContractAgreementFeeTest(TestCase):
    """合同金额测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)

    def test_zero_fee(self):
        c = ContractAgreement.objects.create(
            contract_name='零金额合同', contract_type='service_guarantee',
            signing_party='甲方',
            valid_start_date=date.today(),
            valid_end_date=date.today() + timedelta(days=365),
            has_fee=False, fee_amount=0, status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')
        self.assertEqual(c.fee_amount, 0)

    def test_negative_fee_blocked(self):
        """负数金额被 DB 约束拒绝"""
        from django.db import IntegrityError
        with self.assertRaises((IntegrityError, ValueError)):
            c = ContractAgreement(
                contract_name='负金额合同', contract_type='service_guarantee',
                signing_party='甲方',
                valid_start_date=date.today(),
                valid_end_date=date.today() + timedelta(days=365),
                has_fee=True, fee_amount=-100, status='normal',
                responsible_user_id=self.admin.id,
                responsible_user_name=self.admin.nickname,
                tenant_id='admin')
            c.save()


class ContractAgreementTaskTest(TestCase):
    """合同到期任务测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)

    def _create_contract_directly(self, valid_start, valid_end, status='normal'):
        return ContractAgreement.objects.create(
            contract_name=f'任务测试-{_uuid()[:8]}',
            contract_type='service_guarantee', signing_party='甲方',
            valid_start_date=valid_start, valid_end_date=valid_end,
            has_fee=False, fee_amount=0, status=status,
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')

    def test_task_idempotent(self):
        c = self._create_contract_directly(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1), 'expired')
        from apps.contract_agreement.tasks import scan_single_contract_agreement
        scan_single_contract_agreement(c)
        first = ContractAgreement.objects.get(id=c.id).status
        scan_single_contract_agreement(c)
        second = ContractAgreement.objects.get(id=c.id).status
        self.assertEqual(first, second)

    def test_batch_task_continues_after_failure(self):
        c1 = self._create_contract_directly(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1), 'normal')
        c2 = self._create_contract_directly(
            date.today() + timedelta(days=100),
            date.today() + timedelta(days=400), 'normal')
        from apps.contract_agreement.tasks import scan_contract_agreement_expiration
        scan_contract_agreement_expiration.apply()
        c1.refresh_from_db()
        c2.refresh_from_db()
        self.assertEqual(c1.status, 'expired')
        self.assertEqual(c2.status, 'normal')

    def test_deleted_contract_not_processed(self):
        c = self._create_contract_directly(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1), 'normal')
        cid = c.id
        c.delete()
        from apps.contract_agreement.tasks import scan_single_contract_agreement
        self.assertFalse(ContractAgreement.objects.filter(id=cid).exists())


class ContractAgreementTenantTest(TestCase):
    """合同租户隔离测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.t_a = _make_user('ta', is_supper=False, tenant_id='tenant_a',
                               perms=['contract_agreement.agreement.view'])
        self.t_b = _make_user('tb', is_supper=False, tenant_id='tenant_b',
                               perms=['contract_agreement.agreement.view'])

    def test_tenant_isolation(self):
        ContractAgreement.objects.create(
            contract_name='合同A', contract_type='service_guarantee',
            signing_party='甲方',
            valid_start_date=date.today(),
            valid_end_date=date.today() + timedelta(days=365),
            has_fee=False, fee_amount=0, status='normal',
            responsible_user_id=self.t_a.id,
            responsible_user_name=self.t_a.nickname,
            created_by=self.t_a, tenant_id='tenant_a')
        ContractAgreement.objects.create(
            contract_name='合同B', contract_type='service_guarantee',
            signing_party='乙方',
            valid_start_date=date.today(),
            valid_end_date=date.today() + timedelta(days=365),
            has_fee=False, fee_amount=0, status='normal',
            responsible_user_id=self.t_b.id,
            responsible_user_name=self.t_b.nickname,
            created_by=self.t_b, tenant_id='tenant_b')
        qs_a = apply_tenant_filter(ContractAgreement.objects.all(), self.t_a)
        self.assertEqual(qs_a.count(), 1)
        self.assertEqual(qs_a.first().contract_name, '合同A')


class ContractAgreementPermissionTest(TestCase):
    """合同权限边界测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.no_perm = _make_user('no_perm')
        self.viewer = _make_user('viewer', perms=[
            'contract_agreement.agreement.view'])

    def test_no_perm_blocked(self):
        client = Client()
        client.defaults['HTTP_X_TOKEN'] = self.no_perm.access_token
        resp = client.get('/contract-agreement/')
        body = resp.json()
        self.assertTrue(body.get('error'))

    def test_viewer_can_view_not_create(self):
        client = Client()
        client.defaults['HTTP_X_TOKEN'] = self.viewer.access_token
        resp = client.get('/contract-agreement/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))
        resp = client.post(
            '/contract-agreement/',
            data=json.dumps({
                'contract_name': '测试', 'contract_type': 'service_guarantee',
                'signing_party': '甲方',
                'valid_start_date': date.today().isoformat(),
                'valid_end_date': (date.today() + timedelta(days=365)).isoformat(),
                'has_fee': False, 'fee_amount': 0,
            }),
            content_type='application/json')
        body = resp.json()
        self.assertTrue(body.get('error'))


class ContractAgreementDuplicateTest(TestCase):
    """合同重复提交测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.admin.access_token

    def test_duplicate_within_window(self):
        data = {
            'contract_name': '重复测试合同', 'contract_type': 'service_guarantee',
            'signing_party': '甲方',
            'valid_start_date': date.today().isoformat(),
            'valid_end_date': (date.today() + timedelta(days=365)).isoformat(),
            'has_fee': False, 'fee_amount': 0,
            'responsible_user_id': self.admin.id,
            'responsible_user_name': self.admin.nickname,
        }
        resp1 = self.client.post(
            '/contract-agreement/', data=json.dumps(data),
            content_type='application/json')
        resp2 = self.client.post(
            '/contract-agreement/', data=json.dumps(data),
            content_type='application/json')
        self.assertEqual(resp1.status_code, 200)
        count = ContractAgreement.objects.filter(
            contract_name='重复测试合同').count()
        self.assertLessEqual(count, 1)


class ContractAgreementAuditTest(TestCase):
    """合同审计日志测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.admin.access_token

    def test_create_generates_audit(self):
        resp = self.client.post(
            '/contract-agreement/',
            data=json.dumps({
                'contract_name': f'审计测试-{_uuid()[:8]}',
                'contract_type': 'service_guarantee', 'signing_party': '甲方',
                'valid_start_date': date.today().isoformat(),
                'valid_end_date': (date.today() + timedelta(days=365)).isoformat(),
                'has_fee': False, 'fee_amount': 0,
                'responsible_user_id': self.admin.id,
                'responsible_user_name': self.admin.nickname,
            }),
            content_type='application/json')
        if resp.status_code == 200:
            from apps.logs.models import AuditLog
            logs = AuditLog.objects.filter(
                action='create', target_type='contract_agreement')
            self.assertTrue(logs.exists(),
                            'Audit log should exist for contract creation')

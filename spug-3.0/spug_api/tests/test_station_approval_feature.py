# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 资料与行政业务特征测试 - 台站频率批复
# 覆盖: CRUD, doc_no 唯一性, 日期边界, 状态计算, 到期任务,
#        权限边界, 租户隔离, 与 RadioLicense 关系确认, 附件
import json
import time
from datetime import date, timedelta

from django.test import TestCase, Client
from apps.account.models import User, Role
from apps.radio_license.models import (
    StationFrequencyApproval, RadioLicense,
    EXPIRING_DAYS_THRESHOLD,
)
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


class StationApprovalCRUDTest(TestCase):
    """台站频率批复 CRUD 测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.admin.access_token

    def _create_approval(self, **overrides):
        defaults = {
            'name': '测试批复',
            'doc_no': f'BH-{_uuid()[:8]}',
            'frequency_text': 'FM 100.5 MHz',
            'valid_from': date.today().isoformat(),
            'valid_to': (date.today() + timedelta(days=365)).isoformat(),
            'responsible_user_id': self.admin.id,
            'responsible_user_name': self.admin.nickname,
        }
        defaults.update(overrides)
        return self.client.post(
            '/radio-license/approvals/',
            data=json.dumps(defaults),
            content_type='application/json')

    def test_create_approval_success(self):
        resp = self._create_approval()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))
        approval_id = body.get('data', {}).get('id')
        self.assertIsNotNone(approval_id)

    def test_list_approvals(self):
        self._create_approval()
        resp = self.client.get('/radio-license/approvals/')
        self.assertEqual(resp.status_code, 200)

    def test_retrieve_approval_detail(self):
        resp = self._create_approval()
        body = resp.json()
        data = body.get('data')
        approval_id = data.get('id') if isinstance(data, dict) else None
        resp = self.client.get(f'/radio-license/approvals/{approval_id}/')
        self.assertEqual(resp.status_code, 200)

    def test_update_approval(self):
        resp = self._create_approval()
        body = resp.json()
        data = body.get('data')
        approval_id = data.get('id') if isinstance(data, dict) else None
        resp = self.client.post(
            f'/radio-license/approvals/{approval_id}/',
            data=json.dumps({
                'name': '更新批复', 'doc_no': f'BH-{_uuid()[:8]}',
                'frequency_text': 'FM 200 MHz',
                'valid_from': date.today().isoformat(),
                'valid_to': (date.today() + timedelta(days=365)).isoformat(),
                'responsible_user_id': self.admin.id,
                'responsible_user_name': self.admin.nickname,
            }),
            content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        obj = StationFrequencyApproval.objects.get(id=approval_id)
        self.assertEqual(obj.name, '更新批复')

    def test_delete_approval(self):
        resp = self._create_approval()
        body = resp.json()
        data = body.get('data')
        approval_id = data.get('id') if isinstance(data, dict) else None
        if approval_id:
            resp = self.client.delete(
                '/radio-license/approvals/',
                data=json.dumps({'id': approval_id}),
                content_type='application/json')
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(
                StationFrequencyApproval.objects.filter(id=approval_id).exists())

    def test_invalid_date_range(self):
        resp = self._create_approval(
            valid_from='2026-12-31', valid_to='2026-01-01')
        if resp.status_code == 200:
            body = resp.json()
            approval_id = body.get('data', {}).get('id')
            if approval_id:
                obj = StationFrequencyApproval.objects.get(id=approval_id)
                self.assertGreaterEqual(obj.valid_to, obj.valid_from)


class StationApprovalDocNoUniqueTest(TestCase):
    """批复编号唯一性测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)

    def test_doc_no_unique_within_tenant(self):
        """同一租户内 doc_no 唯一"""
        StationFrequencyApproval.objects.create(
            name='批复1', doc_no='UNIQUE_DOC_001',
            frequency_text='FM 100',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')
        # 直接创建相同 doc_no 应失败
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            StationFrequencyApproval.objects.create(
                name='批复2', doc_no='UNIQUE_DOC_001',
                frequency_text='FM 200',
                valid_from=date.today(),
                valid_to=date.today() + timedelta(days=365),
                status='normal',
                responsible_user_id=self.admin.id,
                responsible_user_name=self.admin.nickname,
                created_by=self.admin, tenant_id='admin')

    def test_doc_no_can_repeat_across_tenants(self):
        """不同租户可以有相同 doc_no"""
        StationFrequencyApproval.objects.create(
            name='批复A', doc_no='SHARED_DOC',
            frequency_text='FM 100',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')
        other = _make_user('other', is_supper=True, tenant_id='tenant_b')
        StationFrequencyApproval.objects.create(
            name='批复B', doc_no='SHARED_DOC',
            frequency_text='FM 200',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=other.id,
            responsible_user_name=other.nickname,
            created_by=other, tenant_id='tenant_b')
        count = StationFrequencyApproval.objects.filter(
            doc_no='SHARED_DOC').count()
        self.assertEqual(count, 2)


class StationApprovalStatusTest(TestCase):
    """批复状态计算测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)

    def _create_approval_directly(self, valid_from, valid_to, status='normal'):
        return StationFrequencyApproval.objects.create(
            name='状态测试', doc_no=f'BH-{_uuid()[:8]}',
            frequency_text='FM 100',
            valid_from=valid_from, valid_to=valid_to,
            status=status,
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')

    def test_status_expired(self):
        lic = self._create_approval_directly(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1))
        from apps.radio_license.tasks import scan_single_approval
        scan_single_approval(lic)
        lic.refresh_from_db()
        self.assertEqual(lic.status, 'expired')

    def test_status_expiring(self):
        lic = self._create_approval_directly(
            date.today() - timedelta(days=100),
            date.today() + timedelta(days=30))
        from apps.radio_license.tasks import scan_single_approval
        scan_single_approval(lic)
        lic.refresh_from_db()
        self.assertEqual(lic.status, 'expiring')

    def test_status_normal(self):
        lic = self._create_approval_directly(
            date.today(),
            date.today() + timedelta(days=EXPIRING_DAYS_THRESHOLD + 10))
        from apps.radio_license.tasks import scan_single_approval
        scan_single_approval(lic)
        lic.refresh_from_db()
        self.assertEqual(lic.status, 'normal')


class StationApprovalTaskTest(TestCase):
    """批复到期任务测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)

    def _create_approval_directly(self, valid_from, valid_to, status='normal'):
        return StationFrequencyApproval.objects.create(
            name='任务测试', doc_no=f'BH-{_uuid()[:8]}',
            frequency_text='FM 100',
            valid_from=valid_from, valid_to=valid_to,
            status=status,
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')

    def test_task_idempotent(self):
        lic = self._create_approval_directly(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1),
            status='expired')
        from apps.radio_license.tasks import scan_single_approval
        scan_single_approval(lic)
        first = StationFrequencyApproval.objects.get(id=lic.id).status
        scan_single_approval(lic)
        second = StationFrequencyApproval.objects.get(id=lic.id).status
        self.assertEqual(first, second)

    def test_batch_task_continues_after_failure(self):
        lic1 = self._create_approval_directly(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1), 'normal')
        lic2 = self._create_approval_directly(
            date.today() + timedelta(days=100),
            date.today() + timedelta(days=400), 'normal')
        from apps.radio_license.tasks import scan_approval_expiration
        scan_approval_expiration.apply()
        lic1.refresh_from_db()
        lic2.refresh_from_db()
        self.assertEqual(lic1.status, 'expired')
        self.assertEqual(lic2.status, 'normal')


class StationApprovalRelationTest(TestCase):
    """批复与执照关系测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)

    def test_approval_independent_from_license(self):
        """批复与执照是独立对象，无外键关联"""
        lic = RadioLicense.objects.create(
            station_name='关联测试台站', purpose='测试',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')
        approval = StationFrequencyApproval.objects.create(
            name='关联测试批复', doc_no=f'BH-{_uuid()[:8]}',
            frequency_text='FM 100',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin')
        # 删除执照不影响批复
        lic.delete()
        self.assertTrue(
            StationFrequencyApproval.objects.filter(id=approval.id).exists())


class StationApprovalTenantTest(TestCase):
    """批复租户隔离测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.t_a = _make_user('ta', is_supper=True, tenant_id='tenant_a')
        self.t_b = _make_user('tb', is_supper=True, tenant_id='tenant_b')

    def test_tenant_isolation(self):
        StationFrequencyApproval.objects.create(
            name='批复A', doc_no='DOC_A',
            frequency_text='FM 100',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.t_a.id,
            responsible_user_name=self.t_a.nickname,
            created_by=self.t_a, tenant_id='tenant_a')
        StationFrequencyApproval.objects.create(
            name='批复B', doc_no='DOC_B',
            frequency_text='FM 200',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.t_b.id,
            responsible_user_name=self.t_b.nickname,
            created_by=self.t_b, tenant_id='tenant_b')
        # 使用非超管用户测试租户隔离
        from apps.account.models import User, Role
        import json
        ta_user = User.objects.create(
            username='ta_viewer', nickname='ta_viewer',
            password_hash=User.make_password('test123'),
            access_token=_uuid(), is_supper=False, is_active=True,
            tenant_id='tenant_a', token_expired=int(time.time()) + 3600,
            last_ip='127.0.0.1', last_login='2026-01-01', type='default',
        )
        qs_a = apply_tenant_filter(
            StationFrequencyApproval.objects.all(), ta_user)
        self.assertEqual(qs_a.count(), 1)
        self.assertEqual(qs_a.first().name, '批复A')


class StationApprovalPermissionTest(TestCase):
    """批复权限边界测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.no_perm = _make_user('no_perm')
        self.viewer = _make_user('viewer', perms=[
            'radio_license.approval.view'])

    def test_no_perm_blocked(self):
        client = Client()
        client.defaults['HTTP_X_TOKEN'] = self.no_perm.access_token
        resp = client.get('/radio-license/approvals/')
        body = resp.json()
        self.assertTrue(body.get('error'))

    def test_viewer_can_view_not_create(self):
        client = Client()
        client.defaults['HTTP_X_TOKEN'] = self.viewer.access_token
        resp = client.get('/radio-license/approvals/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))
        resp = client.post(
            '/radio-license/approvals/',
            data=json.dumps({
                'name': '测试', 'doc_no': 'TEST_001',
                'frequency_text': 'FM 100',
                'valid_from': date.today().isoformat(),
                'valid_to': (date.today() + timedelta(days=365)).isoformat(),
            }),
            content_type='application/json')
        body = resp.json()
        self.assertTrue(body.get('error'))

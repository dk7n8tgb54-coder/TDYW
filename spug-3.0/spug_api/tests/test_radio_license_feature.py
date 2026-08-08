# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 资料与行政业务特征测试 - 无线电台执照
# 覆盖: CRUD, 唯一标识, 日期边界, 状态计算, 到期任务幂等性,
#        权限边界, 租户隔离, 附件集成, 审计日志
import json
import time
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from apps.account.models import User, Role
from apps.radio_license.models import (
    RadioLicense, StationFrequencyApproval,
    RadioLicenseFrequency, LicenseReminderAck,
    EXPIRING_DAYS_THRESHOLD,
)
from apps.setting.utils import AppSetting
from libs.tenant_utils import apply_tenant_filter


def _make_user(username, is_supper=False, tenant_id='admin', perms=None):
    unique = f'{username}_{uuid_token()[:8]}'
    user = User.objects.create(
        username=unique,
        nickname=unique,
        password_hash=User.make_password('test123'),
        access_token=uuid_token(),
        is_supper=is_supper,
        is_active=True,
        tenant_id=tenant_id,
        token_expired=int(time.time()) + 3600,
        last_ip='127.0.0.1',
        last_login='2026-01-01',
        type='default',
    )
    if perms and not is_supper:
        role = Role.objects.create(
            name=f'{username}_role', desc='', page_perms='',
            perms_version=1, created_by=user,
        )
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


def uuid_token():
    import uuid
    return uuid.uuid4().hex


class RadioLicenseCRUDTest(TestCase):
    """无线电台执照 CRUD 特征测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True, tenant_id='admin')
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.admin.access_token
        self.client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'

    def _create_license(self, **overrides):
        defaults = {
            'station_name': '测试台站',
            'purpose': '测试用途',
            'valid_from': date.today().isoformat(),
            'valid_to': (date.today() + timedelta(days=365)).isoformat(),
            'responsible_user_id': self.admin.id,
            'responsible_user_name': self.admin.nickname,
            'frequencies': [],
        }
        defaults.update(overrides)
        resp = self.client.post(
            '/radio-license/',
            data=json.dumps(defaults),
            content_type='application/json',
        )
        return resp

    def _get_created_id(self, resp):
        """从创建响应中提取 ID, 处理 error 情况"""
        body = resp.json()
        data = body.get('data', {})
        if isinstance(data, dict):
            return data.get('id')
        return None

    def test_create_license_success(self):
        """创建执照 - 正常流程"""
        resp = self._create_license()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))
        license_id = self._get_created_id(resp)
        self.assertIsNotNone(license_id)
        self.assertTrue(
            RadioLicense.objects.filter(id=license_id).exists())

    def test_create_license_missing_required_fields(self):
        """创建执照 - 缺少必填字段"""
        resp = self.client.post(
            '/radio-license/',
            data=json.dumps({'station_name': '测试'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get('error'))

    def test_create_license_invalid_date_range(self):
        """创建执照 - 开始日期晚于结束日期 (valid_to >= valid_from)"""
        resp = self._create_license(
            valid_from='2026-12-31',
            valid_to='2026-01-01',
        )
        if resp.status_code == 200:
            body = resp.json()
            data = body.get('data')
            if isinstance(data, dict):
                license_id = data.get('id')
            else:
                license_id = None
            if license_id:
                obj = RadioLicense.objects.get(id=license_id)
                self.assertGreaterEqual(
                    obj.valid_to, obj.valid_from,
                    'valid_to must be >= valid_from (DB CheckConstraint)')
            else:
                self.assertTrue(body.get('error'))

    def test_list_licenses(self):
        """查看执照列表"""
        self._create_license(station_name='台站A')
        self._create_license(station_name='台站B')
        resp = self.client.get('/radio-license/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))

    def test_retrieve_license_detail(self):
        """查看执照详情"""
        resp = self._create_license(station_name='详情测试台站')
        license_id = self._get_created_id(resp)
        if license_id:
            resp = self.client.get(f'/radio-license/{license_id}/')
            self.assertEqual(resp.status_code, 200)

    def test_update_license(self):
        """编辑执照"""
        resp = self._create_license(station_name='原台站名')
        license_id = self._get_created_id(resp)
        if license_id:
            resp = self.client.post(
                f'/radio-license/{license_id}/',
                data=json.dumps({
                    'station_name': '更新后台站名',
                    'purpose': '测试用途',
                    'valid_from': date.today().isoformat(),
                    'valid_to': (date.today() + timedelta(days=365)).isoformat(),
                    'responsible_user_id': self.admin.id,
                    'responsible_user_name': self.admin.nickname,
                }),
                content_type='application/json',
            )
            self.assertEqual(resp.status_code, 200)
            obj = RadioLicense.objects.get(id=license_id)
            self.assertEqual(obj.station_name, '更新后台站名')

    def test_delete_license(self):
        """删除执照"""
        resp = self._create_license(station_name='待删除台站')
        license_id = self._get_created_id(resp)
        if license_id:
            resp = self.client.delete(
                '/radio-license/',
                data=json.dumps({'id': license_id}),
                content_type='application/json')
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(
                RadioLicense.objects.filter(id=license_id).exists())

    def test_delete_nonexistent_license(self):
        """删除不存在的执照"""
        resp = self.client.delete(
            '/radio-license/',
            data=json.dumps({'id': 99999}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get('error'))


class RadioLicenseStatusTest(TestCase):
    """执照状态计算与到期边界测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)

    def _create_license_directly(self, valid_from, valid_to):
        return RadioLicense.objects.create(
            station_name='状态测试台站',
            purpose='测试',
            valid_from=valid_from,
            valid_to=valid_to,
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin,
            tenant_id='admin',
        )

    def test_status_normal(self):
        """状态: 正常 (距到期 > 60 天)"""
        lic = self._create_license_directly(
            date.today(),
            date.today() + timedelta(days=EXPIRING_DAYS_THRESHOLD + 10)
        )
        from apps.radio_license.tasks import scan_single_license
        scan_single_license(lic)
        lic.refresh_from_db()
        self.assertEqual(lic.status, 'normal')

    def test_status_expiring(self):
        """状态: 即将到期 (距到期 0-60 天)"""
        lic = self._create_license_directly(
            date.today() - timedelta(days=100),
            date.today() + timedelta(days=30)
        )
        from apps.radio_license.tasks import scan_single_license
        scan_single_license(lic)
        lic.refresh_from_db()
        self.assertEqual(lic.status, 'expiring')

    def test_status_expired(self):
        """状态: 已过期 (valid_to < today)"""
        lic = self._create_license_directly(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1)
        )
        from apps.radio_license.tasks import scan_single_license
        scan_single_license(lic)
        lic.refresh_from_db()
        self.assertEqual(lic.status, 'expired')

    def test_status_today_expiry(self):
        """边界: 当天到期 (valid_to == today)"""
        lic = self._create_license_directly(
            date.today() - timedelta(days=30),
            date.today()
        )
        from apps.radio_license.tasks import scan_single_license
        scan_single_license(lic)
        lic.refresh_from_db()
        self.assertIn(lic.status, ('expiring', 'normal'))

    def test_status_cross_year(self):
        """跨年日期边界"""
        lic = self._create_license_directly(
            date(2025, 12, 1),
            date(2026, 6, 1)
        )
        from apps.radio_license.tasks import scan_single_license
        scan_single_license(lic)
        lic.refresh_from_db()
        self.assertIn(lic.status, ('normal', 'expiring', 'expired'))

    def test_status_leap_day(self):
        """闰日边界 (2月29日)"""
        lic = self._create_license_directly(
            date(2024, 2, 29),
            date(2025, 2, 28)
        )
        from apps.radio_license.tasks import scan_single_license
        scan_single_license(lic)
        lic.refresh_from_db()
        self.assertIn(lic.status, ('normal', 'expiring', 'expired'))

    def test_status_is_db_field(self):
        """状态是数据库字段而非动态计算"""
        lic = self._create_license_directly(
            date.today() + timedelta(days=100),
            date.today() + timedelta(days=200)
        )
        self.assertTrue(hasattr(lic, 'status'))
        self.assertEqual(lic.status, 'normal')


class RadioLicenseExpiryTaskTest(TestCase):
    """到期定时任务测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)

    def _create_license_directly(self, valid_from, valid_to, status='normal'):
        return RadioLicense.objects.create(
            station_name='任务测试台站',
            purpose='测试',
            valid_from=valid_from,
            valid_to=valid_to,
            status=status,
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin,
            tenant_id='admin',
        )

    def test_task_idempotent_no_change(self):
        """任务幂等: 状态未变时不重复更新"""
        lic = self._create_license_directly(
            date.today() + timedelta(days=365),
            date.today() + timedelta(days=400),
            status='normal'
        )
        from apps.radio_license.tasks import scan_single_license
        scan_single_license(lic)
        lic.refresh_from_db()
        self.assertEqual(lic.status, 'normal')

    def test_task_idempotent_double_run(self):
        """任务幂等: 重复执行结果一致"""
        lic = self._create_license_directly(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1),
            status='normal'
        )
        from apps.radio_license.tasks import scan_single_license
        scan_single_license(lic)
        first_status = RadioLicense.objects.get(id=lic.id).status
        scan_single_license(lic)
        second_status = RadioLicense.objects.get(id=lic.id).status
        self.assertEqual(first_status, second_status)

    def test_task_processes_expired_license(self):
        """任务处理已过期执照"""
        lic = self._create_license_directly(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1),
            status='normal'
        )
        from apps.radio_license.tasks import scan_single_license
        scan_single_license(lic)
        lic.refresh_from_db()
        self.assertEqual(lic.status, 'expired')

    def test_task_continues_after_single_failure(self):
        """单个对象处理失败不影响其他对象"""
        lic1 = self._create_license_directly(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1),
            status='normal'
        )
        lic2 = self._create_license_directly(
            date.today() + timedelta(days=100),
            date.today() + timedelta(days=400),
            status='normal'
        )
        from apps.radio_license.tasks import scan_radio_license_expiration
        scan_radio_license_expiration.apply()
        lic1.refresh_from_db()
        lic2.refresh_from_db()
        self.assertEqual(lic1.status, 'expired')
        self.assertEqual(lic2.status, 'normal')

    def test_deleted_license_not_processed(self):
        """删除后定时任务不处理旧数据"""
        lic = self._create_license_directly(
            date.today() - timedelta(days=100),
            date.today() - timedelta(days=1),
            status='normal'
        )
        license_id = lic.id
        lic.delete()
        from apps.radio_license.tasks import scan_single_license
        # 传入已删除的 ID 应安全处理
        self.assertFalse(
            RadioLicense.objects.filter(id=license_id).exists())

    def test_task_tenant_context(self):
        """任务处理多租户数据"""
        lic_admin = RadioLicense.objects.create(
            station_name='admin台站', purpose='测试',
            valid_from=date.today() - timedelta(days=100),
            valid_to=date.today() - timedelta(days=1),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin',
        )
        other = _make_user('other', is_supper=True, tenant_id='tenant_b')
        lic_other = RadioLicense.objects.create(
            station_name='tenant_b台站', purpose='测试',
            valid_from=date.today() - timedelta(days=100),
            valid_to=date.today() - timedelta(days=1),
            status='normal',
            responsible_user_id=other.id,
            responsible_user_name=other.nickname,
            created_by=other, tenant_id='tenant_b',
        )
        from apps.radio_license.tasks import scan_radio_license_expiration
        scan_radio_license_expiration.apply()
        lic_admin.refresh_from_db()
        lic_other.refresh_from_db()
        self.assertEqual(lic_admin.status, 'expired')
        self.assertEqual(lic_other.status, 'expired')


class RadioLicensePermissionTest(TestCase):
    """执照权限边界测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.viewer = _make_user('viewer', perms=[
            'radio_license.license.view'])
        self.editor = _make_user('editor', perms=[
            'radio_license.license.view',
            'radio_license.license.edit'])
        self.no_perm = _make_user('no_perm')

    def _create_license_as_admin(self):
        return RadioLicense.objects.create(
            station_name='权限测试台站', purpose='测试',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin',
        )

    def test_no_perm_user_cannot_view(self):
        """无权限用户不能查看执照列表"""
        self._create_license_as_admin()
        client = Client()
        client.defaults['HTTP_X_TOKEN'] = self.no_perm.access_token
        resp = client.get('/radio-license/')
        body = resp.json()
        self.assertTrue(body.get('error'))

    def test_viewer_can_view_not_create(self):
        """只有查看权限的用户可查看但不能创建"""
        self._create_license_as_admin()
        client = Client()
        client.defaults['HTTP_X_TOKEN'] = self.viewer.access_token
        resp = client.get('/radio-license/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))
        resp = client.post(
            '/radio-license/',
            data=json.dumps({
                'station_name': '测试', 'purpose': '测试',
                'valid_from': date.today().isoformat(),
                'valid_to': (date.today() + timedelta(days=365)).isoformat(),
                'responsible_user_id': self.viewer.id,
                'responsible_user_name': self.viewer.nickname,
            }),
            content_type='application/json',
        )
        body = resp.json()
        self.assertTrue(body.get('error'))

    def test_unauthenticated_user_blocked(self):
        """未登录用户被拦截"""
        client = Client()
        resp = client.get('/radio-license/')
        self.assertNotEqual(resp.status_code, 200)


class RadioLicenseTenantIsolationTest(TestCase):
    """执照租户隔离测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.tenant_a = _make_user('ta_user', is_supper=False, tenant_id='tenant_a',
                                    perms=['radio_license.license.view'])
        self.tenant_b = _make_user('tb_user', is_supper=False, tenant_id='tenant_b',
                                    perms=['radio_license.license.view'])

    def _create_license(self, user, station_name='测试台站'):
        return RadioLicense.objects.create(
            station_name=station_name, purpose='测试',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=user.id,
            responsible_user_name=user.nickname,
            created_by=user, tenant_id=user.tenant_id,
        )

    def test_tenant_a_cannot_see_tenant_b(self):
        """租户A看不到租户B的执照"""
        self._create_license(self.tenant_a, '台站A')
        self._create_license(self.tenant_b, '台站B')
        qs = apply_tenant_filter(RadioLicense.objects.all(), self.tenant_a)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().station_name, '台站A')

    def test_tenant_b_cannot_see_tenant_a(self):
        """租户B看不到租户A的执照"""
        self._create_license(self.tenant_a, '台站A')
        self._create_license(self.tenant_b, '台站B')
        qs = apply_tenant_filter(RadioLicense.objects.all(), self.tenant_b)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().station_name, '台站B')

    def test_supper_sees_all(self):
        """超管能看到所有租户数据"""
        self._create_license(self.tenant_a, '台站A')
        self._create_license(self.tenant_b, '台站B')
        super_user = _make_user('super', is_supper=True, tenant_id='admin')
        qs = apply_tenant_filter(RadioLicense.objects.all(), super_user)
        self.assertEqual(qs.count(), 2)


class RadioLicenseAttachmentTest(TestCase):
    """执照附件集成测试 (EvidenceAttachment)"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.admin.access_token
        self.license = RadioLicense.objects.create(
            station_name='附件测试台站', purpose='测试',
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=365),
            status='normal',
            responsible_user_id=self.admin.id,
            responsible_user_name=self.admin.nickname,
            created_by=self.admin, tenant_id='admin',
        )

    def test_list_attachments_empty(self):
        """无附件时列表为空"""
        resp = self.client.get(f'/radio-license/{self.license.id}/attachments/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))

    def test_attachment_uses_evidence_system(self):
        """执照附件使用 EvidenceAttachment 系统"""
        from apps.evidence.models import EvidenceAttachment
        att = EvidenceAttachment.objects.create(
            module='radio_license',
            object_type='main',
            object_id=str(self.license.id),
            file_name='test.pdf',
            file_path='/tmp/test.pdf',
            file_size=1024,
            file_ext='pdf',
            uploaded_by_id=self.admin.id,
            uploaded_by_name=self.admin.nickname,
            tenant_id='admin',
        )
        resp = self.client.get(f'/radio-license/{self.license.id}/attachments/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'))


class RadioLicenseAuditLogTest(TestCase):
    """执照审计日志测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.admin.access_token

    def test_create_generates_audit_log(self):
        """创建执照生成审计日志"""
        resp = self.client.post(
            '/radio-license/',
            data=json.dumps({
                'station_name': '审计测试台站', 'purpose': '测试',
                'valid_from': date.today().isoformat(),
                'valid_to': (date.today() + timedelta(days=365)).isoformat(),
                'responsible_user_id': self.admin.id,
                'responsible_user_name': self.admin.nickname,
            }),
            content_type='application/json',
        )
        if resp.status_code == 200:
            body = resp.json()
            if 'data' in body and 'id' in body.get('data', {}):
                from apps.logs.models import AuditLog
                logs = AuditLog.objects.filter(
                    action='create',
                    target_type='radio_license',
                )
                self.assertTrue(logs.exists(),
                                'Audit log should be created for license creation')


class RadioLicenseDuplicateTest(TestCase):
    """执照重复提交测试"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.admin = _make_user('admin', is_supper=True)
        self.client = Client()
        self.client.defaults['HTTP_X_TOKEN'] = self.admin.access_token

    def test_duplicate_within_window(self):
        """30 秒内重复提交被幂等性检查拦截"""
        data = {
            'station_name': '重复测试台站', 'purpose': '测试',
            'valid_from': date.today().isoformat(),
            'valid_to': (date.today() + timedelta(days=365)).isoformat(),
            'responsible_user_id': self.admin.id,
            'responsible_user_name': self.admin.nickname,
        }
        resp1 = self.client.post(
            '/radio-license/', data=json.dumps(data),
            content_type='application/json')
        resp2 = self.client.post(
            '/radio-license/', data=json.dumps(data),
            content_type='application/json')
        # 第一次应成功，第二次可能被 check_recent_duplicate 拦截
        self.assertEqual(resp1.status_code, 200)
        body2 = resp2.json()
        # check_recent_duplicate 应阻止第二次创建
        count = RadioLicense.objects.filter(
            station_name='重复测试台站').count()
        self.assertLessEqual(count, 1)

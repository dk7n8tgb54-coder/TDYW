# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
Radio license expiration scan tests.

The reminder history table has been removed. The scanner only maintains
RadioLicense.status; popup reminders are queried in real time and acknowledged
through LicenseReminderAck.

台站频率批复测试覆盖（2026-09 第一轮改造后）：状态边界、全局共享数据范围、
CRUD 权限、即时状态、附件 object_type 隔离、批复删除级联软删附件。
主动提醒（popup/ack/badge）与责任人已移除，相关端点应返回 404。
"""
import json
import tempfile
from datetime import date, timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, Client, override_settings

from apps.account.models import User, Role
from apps.radio_license.models import (
    RadioLicense, EXPIRING_DAYS_THRESHOLD,
    StationFrequencyApproval,
)
from apps.radio_license.tasks import (
    calculate_license_status, scan_single_license, scan_single_approval,
)
from apps.evidence.models import EvidenceAttachment
from apps.evidence.attachment_service import AttachmentService


# ============================================================
# 测试辅助
# ============================================================

def _make_user(username, is_supper=False, tenant_id='default', is_active=True):
    import time
    token = (username * 10)[:32]
    return User.objects.create(
        username=username, nickname=username, password_hash='x',
        is_active=is_active, is_supper=is_supper, access_token=token,
        token_expired=int(time.time()) + 3600, last_login='2026-01-01',
        last_ip='127.0.0.1', type='default', tenant_id=tenant_id,
    )


def _grant_perms(user, perms):
    """perms: list of (module, page, [perm_keys])"""
    perm_dict = {}
    for module, page, keys in perms:
        perm_dict.setdefault(module, {}).setdefault(page, []).extend(keys)
    role = Role.objects.create(
        name=f'role_{user.username}',
        page_perms=json.dumps(perm_dict),
        created_by=user,
    )
    user.roles.add(role)
    user.set_perms_cache()
    return role


def _make_client(user):
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    return client


def _approval_perms(*keys):
    """构造批复相关权限列表，keys 缺省给 view。"""
    keys = list(keys) or ['view']
    perms = [('radio_license', 'approval', keys)]
    return perms


def _make_approval(user, **kwargs):
    """直接创建一条批复记录（责任人字段已移除）。"""
    defaults = {
        'tenant_id': getattr(user, 'tenant_id', 'default'),
        'name': f'批复-{user.username}',
        'doc_no': f'DOC-{user.username}',
        'frequency_text': '100MHz',
        'valid_from': date.today() - timedelta(days=365),
        'valid_to': date.today() + timedelta(days=30),
        'status': 'normal',
        'created_by': user,
    }
    defaults.update(kwargs)
    return StationFrequencyApproval.objects.create(**defaults)


# ============================================================
# 既有执照测试
# ============================================================


class CalculateLicenseStatusTests(TestCase):
    """Status calculation uses the shared 60-day threshold."""

    def test_60_days_is_expiring(self):
        today = date(2026, 6, 22)
        status, days_left = calculate_license_status(today + timedelta(days=60), today)
        self.assertEqual(status, 'expiring')
        self.assertEqual(days_left, 60)

    def test_0_days_is_expiring(self):
        today = date(2026, 6, 22)
        status, days_left = calculate_license_status(today, today)
        self.assertEqual(status, 'expiring')
        self.assertEqual(days_left, 0)

    def test_61_days_is_normal(self):
        today = date(2026, 6, 22)
        status, days_left = calculate_license_status(today + timedelta(days=61), today)
        self.assertEqual(status, 'normal')
        self.assertEqual(days_left, 61)

    def test_expired(self):
        today = date(2026, 6, 22)
        status, days_left = calculate_license_status(today - timedelta(days=1), today)
        self.assertEqual(status, 'expired')
        self.assertEqual(days_left, -1)

    def test_threshold_is_60(self):
        self.assertEqual(EXPIRING_DAYS_THRESHOLD, 60)


class ScanSingleLicenseTests(TestCase):
    """Single-license scan updates status without creating reminder logs."""

    def setUp(self):
        self.user = User.objects.create(
            username='test_responsible',
            nickname='test_responsible',
            password_hash='x',
            is_active=True,
            access_token='test_token_xxxxxxxx',
            tenant_id='test_tenant',
        )
        self.today = date(2026, 6, 22)
        self.license = RadioLicense.objects.create(
            tenant_id='test_tenant',
            station_name='test_station',
            purpose='test',
            valid_from=self.today - timedelta(days=335),
            valid_to=self.today + timedelta(days=30),
            responsible_user_id=self.user.id,
            responsible_user_name=self.user.nickname,
            status='normal',
            created_by=self.user,
        )

    def test_expiring_updates_status(self):
        result = scan_single_license(self.license, today=self.today)

        self.assertEqual(result, {
            'status': 'expiring',
            'days_left': 30,
            'updated': True,
        })
        self.license.refresh_from_db()
        self.assertEqual(self.license.status, 'expiring')

    def test_same_status_rescan_is_not_updated(self):
        scan_single_license(self.license, today=self.today)
        result = scan_single_license(self.license, today=self.today)

        self.assertEqual(result['status'], 'expiring')
        self.assertEqual(result['days_left'], 30)
        self.assertFalse(result['updated'])

    def test_expired_updates_status(self):
        RadioLicense.objects.filter(pk=self.license.id).update(
            valid_to=self.today - timedelta(days=5)
        )
        self.license.refresh_from_db()

        result = scan_single_license(self.license, today=self.today)

        self.assertEqual(result, {
            'status': 'expired',
            'days_left': -5,
            'updated': True,
        })
        self.license.refresh_from_db()
        self.assertEqual(self.license.status, 'expired')

    def test_normal_status_does_not_change_when_already_normal(self):
        RadioLicense.objects.filter(pk=self.license.id).update(
            valid_to=self.today + timedelta(days=100),
            status='normal',
        )
        self.license.refresh_from_db()

        result = scan_single_license(self.license, today=self.today)

        self.assertEqual(result, {
            'status': 'normal',
            'days_left': 100,
            'updated': False,
        })
        self.license.refresh_from_db()
        self.assertEqual(self.license.status, 'normal')


# ============================================================
# 台站频率批复 - 状态扫描
# ============================================================


class ScanSingleApprovalTests(TestCase):
    """批复单条扫描：状态边界与即时更新。"""

    def setUp(self):
        self.user = _make_user('approval_responsible', tenant_id='t_a')
        self.today = date(2026, 6, 22)
        self.approval = _make_approval(
            self.user,
            tenant_id='t_a',
            valid_to=self.today + timedelta(days=100),
            status='normal',
        )

    def test_61_days_is_normal(self):
        approval = _make_approval(
            self.user, tenant_id='t_a',
            doc_no='DOC-61',
            valid_to=self.today + timedelta(days=61),
            status='normal',
        )
        result = scan_single_approval(approval, today=self.today)
        self.assertEqual(result['status'], 'normal')
        self.assertEqual(result['days_left'], 61)
        self.assertFalse(result['updated'])

    def test_60_days_is_expiring_and_updates(self):
        approval = _make_approval(
            self.user, tenant_id='t_a',
            doc_no='DOC-60',
            valid_to=self.today + timedelta(days=60),
            status='normal',
        )
        result = scan_single_approval(approval, today=self.today)
        self.assertEqual(result['status'], 'expiring')
        self.assertEqual(result['days_left'], 60)
        self.assertTrue(result['updated'])
        approval.refresh_from_db()
        self.assertEqual(approval.status, 'expiring')

    def test_0_days_is_expiring(self):
        approval = _make_approval(
            self.user, tenant_id='t_a',
            doc_no='DOC-0',
            valid_to=self.today,
            status='normal',
        )
        result = scan_single_approval(approval, today=self.today)
        self.assertEqual(result['status'], 'expiring')
        self.assertEqual(result['days_left'], 0)

    def test_expired_minus_1(self):
        approval = _make_approval(
            self.user, tenant_id='t_a',
            doc_no='DOC-M1',
            valid_to=self.today - timedelta(days=1),
            status='normal',
        )
        result = scan_single_approval(approval, today=self.today)
        self.assertEqual(result['status'], 'expired')
        self.assertEqual(result['days_left'], -1)
        approval.refresh_from_db()
        self.assertEqual(approval.status, 'expired')

    def test_same_status_not_updated(self):
        approval = _make_approval(
            self.user, tenant_id='t_a',
            doc_no='DOC-SAME',
            valid_to=self.today + timedelta(days=30),
            status='expiring',
        )
        result = scan_single_approval(approval, today=self.today)
        self.assertFalse(result['updated'])


# ============================================================
# 台站频率批复 - CRUD 全局数据范围与校验
# ============================================================


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class StationFrequencyApprovalCRUDTests(TestCase):
    """批复 CRUD：跨租户全局共享、doc_no 重复、日期校验、即时状态。

    2026-09 第一轮改造：批复不再按租户隔离，拥有 approval 权限的用户
    跨租户可见可管；新增仍记录创建人 tenant_id 但不限制后续可见性。
    """

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        # 租户 A 的用户
        self.user_a = _make_user('a_user', tenant_id='tenant_a')
        _grant_perms(self.user_a, _approval_perms('view', 'add', 'edit', 'del')
                     + [('radio_license', 'attachment', ['upload', 'download', 'delete'])])
        self.client_a = _make_client(self.user_a)
        # 租户 B 的用户
        self.user_b = _make_user('b_user', tenant_id='tenant_b')
        _grant_perms(self.user_b, _approval_perms('view', 'add', 'edit', 'del'))
        self.client_b = _make_client(self.user_b)

    # ---- 列表：全局共享 ----

    def test_list_returns_all_tenants_for_permitted_user(self):
        """拥有 approval.view 的用户跨租户看到全部批复。"""
        _make_approval(self.user_a, tenant_id='tenant_a')
        _make_approval(self.user_b, tenant_id='tenant_b', doc_no='DOC-B')
        resp = self.client_a.get('/radio-license/approvals/')
        body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(body.get('error'))
        records = body['data']['records']
        self.assertEqual(len(records), 2)
        self.assertEqual(
            {r['tenant_id'] for r in records}, {'tenant_a', 'tenant_b'})
        # 另一租户用户看到的也是同一份全量
        resp_b = self.client_b.get('/radio-license/approvals/')
        self.assertEqual(len(resp_b.json()['data']['records']), 2)

    # ---- 创建 ----

    def test_create_success_and_immediate_status(self):
        today = date.today()
        payload = {
            'name': '批复1',
            'doc_no': 'APP-001',
            'frequency_text': '88-108 MHz',
            'valid_from': str(today - timedelta(days=10)),
            'valid_to': str(today + timedelta(days=5)),
            'remark': '',
        }
        resp = self.client_a.post(
            '/radio-license/approvals/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        approval = StationFrequencyApproval.objects.get(doc_no='APP-001')
        # 仍记录创建人租户
        self.assertEqual(approval.tenant_id, 'tenant_a')
        self.assertEqual(approval.created_by, self.user_a)
        # 即时扫描：5 天内到期应为 expiring
        self.assertEqual(approval.status, 'expiring')

    def test_create_already_expired_gets_expired_status(self):
        today = date.today()
        payload = {
            'name': '已过期批复',
            'doc_no': 'APP-EXP',
            'frequency_text': '100 MHz',
            'valid_from': str(today - timedelta(days=400)),
            'valid_to': str(today - timedelta(days=10)),
        }
        resp = self.client_a.post(
            '/radio-license/approvals/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        approval = StationFrequencyApproval.objects.get(doc_no='APP-EXP')
        self.assertEqual(approval.status, 'expired')

    def test_create_doc_no_duplicated_in_same_tenant_allowed(self):
        """文件编号允许重复。"""
        _make_approval(self.user_a, tenant_id='tenant_a', doc_no='DUP-1')
        today = date.today()
        payload = {
            'name': '重复编号',
            'doc_no': 'DUP-1',
            'frequency_text': '1 MHz',
            'valid_from': str(today),
            'valid_to': str(today + timedelta(days=100)),
        }
        resp = self.client_a.post(
            '/radio-license/approvals/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(
            StationFrequencyApproval.objects.filter(
                tenant_id='tenant_a', doc_no='DUP-1').count(),
            2,
        )

    def test_create_valid_from_after_valid_to_rejected(self):
        today = date.today()
        payload = {
            'name': '日期非法',
            'doc_no': 'BAD-DATE',
            'frequency_text': '1 MHz',
            'valid_from': str(today + timedelta(days=10)),
            'valid_to': str(today),
        }
        resp = self.client_a.post(
            '/radio-license/approvals/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        body = resp.json()
        self.assertTrue(body.get('error'))

    # ---- 编辑 ----

    def test_edit_changes_valid_to_and_immediate_status(self):
        today = date.today()
        approval = _make_approval(
            self.user_a, tenant_id='tenant_a',
            doc_no='EDIT-1',
            valid_to=today + timedelta(days=100),
            status='normal',
        )
        payload = {
            'id': approval.id,
            'name': approval.name,
            'doc_no': approval.doc_no,
            'frequency_text': approval.frequency_text,
            'valid_from': str(approval.valid_from),
            'valid_to': str(today - timedelta(days=5)),  # 续期后过期
        }
        resp = self.client_a.post(
            '/radio-license/approvals/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        approval.refresh_from_db()
        self.assertEqual(approval.status, 'expired')

    def test_edit_doc_no_duplicated_allowed(self):
        """编辑时可以把文件编号改成已有编号（允许重复）。"""
        _make_approval(self.user_a, tenant_id='tenant_a', doc_no='DUP-A')
        approval2 = _make_approval(self.user_a, tenant_id='tenant_a', doc_no='DUP-B')
        today = date.today()
        payload = {
            'id': approval2.id,
            'name': approval2.name,
            'doc_no': 'DUP-A',  # 改成已存在的编号
            'frequency_text': approval2.frequency_text,
            'valid_from': str(approval2.valid_from),
            'valid_to': str(today + timedelta(days=100)),
        }
        resp = self.client_a.post(
            '/radio-license/approvals/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        approval2.refresh_from_db()
        self.assertEqual(approval2.doc_no, 'DUP-A')

    def test_edit_cross_tenant_allowed_with_edit_perm(self):
        """跨租户编辑：tenant B 用户可编辑 tenant A 的批复。"""
        approval_a = _make_approval(self.user_a, tenant_id='tenant_a', doc_no='A-EDIT')
        today = date.today()
        payload = {
            'id': approval_a.id,
            'name': 'B用户改名',
            'doc_no': 'A-EDIT',
            'frequency_text': '1 MHz',
            'valid_from': str(today),
            'valid_to': str(today + timedelta(days=100)),
        }
        resp = self.client_b.post(
            '/radio-license/approvals/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        approval_a.refresh_from_db()
        self.assertEqual(approval_a.name, 'B用户改名')
        # tenant_id 保持创建租户，不被编辑者改写
        self.assertEqual(approval_a.tenant_id, 'tenant_a')

    # ---- 详情 ----

    def test_detail_computed_status_realtime(self):
        today = date.today()
        approval = _make_approval(
            self.user_a, tenant_id='tenant_a',
            doc_no='DETAIL-1',
            valid_to=today + timedelta(days=10),
            status='normal',  # 缓存状态错误，但接口应实时计算
        )
        resp = self.client_a.get(f'/radio-license/approvals/{approval.id}/')
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['computed_status'], 'expiring')
        self.assertEqual(body['data']['days_left'], 10)

    def test_detail_cross_tenant_allowed(self):
        """跨租户详情可见。"""
        approval_b = _make_approval(self.user_b, tenant_id='tenant_b', doc_no='CROSS-D')
        resp = self.client_a.get(f'/radio-license/approvals/{approval_b.id}/')
        body = resp.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['doc_no'], 'CROSS-D')

    # ---- 删除 ----

    def test_delete_cross_tenant_allowed_with_del_perm(self):
        """跨租户删除：tenant B 用户可删除 tenant A 的批复，附件联动软删。"""
        approval_a = _make_approval(self.user_a, tenant_id='tenant_a', doc_no='DEL-A')
        EvidenceAttachment.objects.create(
            tenant_id='tenant_a', module='radio_license', object_type='approval',
            object_id=str(approval_a.id), file_name='a.pdf',
            file_path='radio_license/tenant_a/202601/approval_1/a.pdf',
            file_size=10, file_ext='.pdf', file_hash_sha256='x',
            uploaded_by_id=self.user_a.id, uploaded_by_name=self.user_a.nickname,
        )
        resp = self.client_b.delete(f'/radio-license/approvals/?id={approval_a.id}')
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        self.assertFalse(StationFrequencyApproval.objects.filter(pk=approval_a.id).exists())
        att = EvidenceAttachment.objects.all_with_deleted().get(object_id=str(approval_a.id))
        self.assertTrue(att.is_deleted)

    def test_delete_cascade_soft_delete_attachments(self):
        """批复删除：附件软删（跨租户匹配）。"""
        approval = _make_approval(self.user_a, tenant_id='tenant_a', doc_no='DEL-CAS')
        # 写入一条未软删的附件
        EvidenceAttachment.objects.create(
            tenant_id='tenant_a', module='radio_license', object_type='approval',
            object_id=str(approval.id), file_name='a.pdf',
            file_path='radio_license/tenant_a/202601/approval_1/a.pdf',
            file_size=10, file_ext='.pdf', file_hash_sha256='x',
            uploaded_by_id=self.user_a.id, uploaded_by_name=self.user_a.nickname,
        )

        resp = self.client_a.delete(f'/radio-license/approvals/?id={approval.id}')
        body = resp.json()
        self.assertFalse(body.get('error'), body)

        # 批复物理删除
        self.assertFalse(StationFrequencyApproval.objects.filter(pk=approval.id).exists())
        # 附件被软删（is_deleted=True），记录保留
        att = EvidenceAttachment.objects.all_with_deleted().get(object_id=str(approval.id))
        self.assertTrue(att.is_deleted)

    # ---- 状态筛选：列表 status 实时转换 ----

    def test_list_status_filter_expiring(self):
        today = date.today()
        # expiring
        _make_approval(self.user_a, tenant_id='tenant_a', doc_no='EX-1',
                       valid_to=today + timedelta(days=10))
        # normal
        _make_approval(self.user_a, tenant_id='tenant_a', doc_no='EX-2',
                       valid_to=today + timedelta(days=200))
        # expired
        _make_approval(self.user_a, tenant_id='tenant_a', doc_no='EX-3',
                       valid_to=today - timedelta(days=5))

        resp = self.client_a.get('/radio-license/approvals/?status=expiring')
        body = resp.json()
        self.assertFalse(body.get('error'))
        records = body['data']['records']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['doc_no'], 'EX-1')
        self.assertEqual(records[0]['computed_status'], 'expiring')

    # ---- 权限分支 ----

    def test_add_only_cannot_edit(self):
        """只有 add 权限的用户走编辑分支被拒绝。"""
        user_add = _make_user('add_only', tenant_id='tenant_a')
        _grant_perms(user_add, _approval_perms('view', 'add'))
        client_add = _make_client(user_add)
        approval = _make_approval(self.user_a, tenant_id='tenant_a', doc_no='EDIT-CHK')
        today = date.today()
        payload = {
            'id': approval.id,
            'name': approval.name,
            'doc_no': approval.doc_no,
            'frequency_text': approval.frequency_text,
            'valid_from': str(approval.valid_from),
            'valid_to': str(today + timedelta(days=100)),
        }
        resp = client_add.post(
            '/radio-license/approvals/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        body = resp.json()
        self.assertTrue(body.get('error'))

    def test_edit_only_cannot_add(self):
        """只有 edit 权限的用户走新增分支被拒绝。"""
        user_edit = _make_user('edit_only', tenant_id='tenant_a')
        _grant_perms(user_edit, _approval_perms('view', 'edit'))
        client_edit = _make_client(user_edit)
        today = date.today()
        payload = {
            'name': '编辑无新增',
            'doc_no': 'EDIT-NO-ADD',
            'frequency_text': '1 MHz',
            'valid_from': str(today),
            'valid_to': str(today + timedelta(days=100)),
        }
        resp = client_edit.post(
            '/radio-license/approvals/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        body = resp.json()
        self.assertTrue(body.get('error'))

    def test_view_only_cannot_edit_or_delete_cross_tenant(self):
        """仅 view 权限用户跨租户编辑/删除被后端拒绝（不能只靠前端隐藏按钮）。"""
        user_view_b = _make_user('view_only_b', tenant_id='tenant_b')
        _grant_perms(user_view_b, _approval_perms('view'))
        client_view_b = _make_client(user_view_b)
        approval_a = _make_approval(self.user_a, tenant_id='tenant_a', doc_no='VO-A')
        today = date.today()
        payload = {
            'id': approval_a.id,
            'name': '越权改名',
            'doc_no': 'VO-A',
            'frequency_text': approval_a.frequency_text,
            'valid_from': str(approval_a.valid_from),
            'valid_to': str(today + timedelta(days=100)),
        }
        resp = client_view_b.post(
            '/radio-license/approvals/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertTrue(resp.json().get('error'))
        resp = client_view_b.delete(f'/radio-license/approvals/?id={approval_a.id}')
        self.assertTrue(resp.json().get('error'))
        approval_a.refresh_from_db()
        self.assertEqual(approval_a.name, approval_a.name)
        self.assertTrue(
            StationFrequencyApproval.objects.filter(pk=approval_a.id).exists())

    # ---- 已移除的提醒/责任人端点 ----

    def test_removed_reminder_and_responsible_endpoints_return_404(self):
        """popup/ack/责任人候选端点已下线，请求应 404；badge 已恢复为全局只读统计。"""
        approval = _make_approval(self.user_a, tenant_id='tenant_a', doc_no='GONE-1')
        resp = self.client_a.get('/radio-license/approvals/reminders/popup/')
        self.assertEqual(resp.status_code, 404)
        resp = self.client_a.post(
            '/radio-license/approvals/reminders/ack/',
            data=json.dumps({'approval_id': approval.id}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)
        # badge 恢复：全局只读统计，无个人提醒语义（2026-09 第二轮）
        resp = self.client_a.get('/radio-license/approvals/badge/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        self.assertIn('count', body.get('data', {}))
        resp = self.client_a.get('/radio-license/approvals/responsible-users/')
        self.assertEqual(resp.status_code, 404)


# ============================================================
# 台站频率批复 - 附件 object_type 隔离
# ============================================================


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class StationFrequencyApprovalAttachmentTests(TestCase):
    """附件 object_type 隔离与桥接视图校验。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('att_user', tenant_id='t_att')
        _grant_perms(self.user, _approval_perms('view', 'add', 'edit', 'del')
                     + [('radio_license', 'attachment', ['upload', 'download', 'delete'])])
        self.client = _make_client(self.user)

    def test_list_only_returns_approval_attachments(self):
        """批复附件列表不应返回同租户执照附件。"""
        approval = _make_approval(self.user, tenant_id='t_att', doc_no='ATT-1')
        # 批复附件
        EvidenceAttachment.objects.create(
            tenant_id='t_att', module='radio_license', object_type='approval',
            object_id=str(approval.id), file_name='a.pdf',
            file_path='radio_license/t_att/202601/approval_1/a.pdf',
            file_size=10, file_ext='.pdf', file_hash_sha256='h1',
            uploaded_by_id=self.user.id, uploaded_by_name=self.user.nickname,
        )
        # 执照附件（同租户、同 module，但 object_type 不同）
        EvidenceAttachment.objects.create(
            tenant_id='t_att', module='radio_license', object_type='license',
            object_id=str(approval.id), file_name='b.pdf',
            file_path='radio_license/t_att/202601/license_1/b.pdf',
            file_size=10, file_ext='.pdf', file_hash_sha256='h2',
            uploaded_by_id=self.user.id, uploaded_by_name=self.user.nickname,
        )
        resp = self.client.get(f'/radio-license/approvals/{approval.id}/attachments/')
        body = resp.json()
        self.assertFalse(body.get('error'))
        data = body['data']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['file_name'], 'a.pdf')

    def test_list_attachment_count_aggregates_correctly(self):
        """列表 attachment_count 批量聚合正确，且只统计 approval 类型。"""
        approval = _make_approval(self.user, tenant_id='t_att', doc_no='ATT-CNT')
        for i in range(3):
            EvidenceAttachment.objects.create(
                tenant_id='t_att', module='radio_license', object_type='approval',
                object_id=str(approval.id), file_name=f'a{i}.pdf',
                file_path=f'radio_license/t_att/202601/approval_{approval.id}/a{i}.pdf',
                file_size=10, file_ext='.pdf', file_hash_sha256=f'h{i}',
                uploaded_by_id=self.user.id, uploaded_by_name=self.user.nickname,
            )
        # 一条 license 类型附件，不应计入批复数
        EvidenceAttachment.objects.create(
            tenant_id='t_att', module='radio_license', object_type='license',
            object_id=str(approval.id), file_name='lic.pdf',
            file_path=f'radio_license/t_att/202601/license_{approval.id}/lic.pdf',
            file_size=10, file_ext='.pdf', file_hash_sha256='hl',
            uploaded_by_id=self.user.id, uploaded_by_name=self.user.nickname,
        )
        resp = self.client.get('/radio-license/approvals/')
        records = resp.json()['data']['records']
        target = [r for r in records if r['doc_no'] == 'ATT-CNT'][0]
        self.assertEqual(target['attachment_count'], 3)

    def test_cannot_delete_license_attachment_via_approval_endpoint(self):
        """批复附件删除接口不能删除 license 类型附件。"""
        approval = _make_approval(self.user, tenant_id='t_att', doc_no='ATT-X')
        license_att = EvidenceAttachment.objects.create(
            tenant_id='t_att', module='radio_license', object_type='license',
            object_id=str(approval.id), file_name='lic.pdf',
            file_path=f'radio_license/t_att/202601/license_{approval.id}/lic.pdf',
            file_size=10, file_ext='.pdf', file_hash_sha256='hl',
            uploaded_by_id=self.user.id, uploaded_by_name=self.user.nickname,
        )
        resp = self.client.delete(
            f'/radio-license/approvals/attachments/?id={license_att.id}'
        )
        body = resp.json()
        self.assertTrue(body.get('error'))
        # 附件未被删除
        license_att.refresh_from_db()
        self.assertFalse(license_att.is_deleted)

    def test_delete_approval_attachment_records_correct_audit(self):
        """批复附件删除证据事件 object_type 必须是 approval，不能是 license。"""
        approval = _make_approval(self.user, tenant_id='t_att', doc_no='ATT-AUD')
        att = EvidenceAttachment.objects.create(
            tenant_id='t_att', module='radio_license', object_type='approval',
            object_id=str(approval.id), file_name='a.pdf',
            file_path=f'radio_license/t_att/202601/approval_{approval.id}/a.pdf',
            file_size=10, file_ext='.pdf', file_hash_sha256='ha',
            uploaded_by_id=self.user.id, uploaded_by_name=self.user.nickname,
        )
        # mock 物理文件删除，避免测试需要真实文件
        with patch.object(
            AttachmentService, '_remove_physical_file', return_value=None,
        ):
            resp = self.client.delete(
                f'/radio-license/approvals/attachments/?id={att.id}'
            )
        body = resp.json()
        self.assertFalse(body.get('error'), body)

        # 检查证据事件
        from apps.evidence.models import EvidenceEvent
        events = EvidenceEvent.objects.filter(
            module='radio_license', object_type='approval',
            object_id=str(approval.id), event_type='delete',
        )
        self.assertEqual(events.count(), 1)
        self.assertIn('a.pdf', events.first().event_title)
        # 确保没有误写 license 类型
        self.assertFalse(
            EvidenceEvent.objects.filter(
                module='radio_license', object_type='license',
                object_id=str(approval.id),
            ).exists()
        )


# ============================================================
# 无线电台执照 - 菜单红点（个人口径：只统计本人负责且未 ack）
# ============================================================

class RadioLicenseBadgeTests(TestCase):
    """执照 badge 与批复 badge 同口径：responsible_user_id=当前用户 且当前周期未 ack。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('badge_owner', tenant_id='t_badge')
        _grant_perms(self.user, [('radio_license', 'license', ['view'])])
        self.client = _make_client(self.user)

    def _make_license(self, **kwargs):
        defaults = {
            'tenant_id': 't_badge',
            'station_name': 'badge_station',
            'purpose': 'test',
            'valid_from': date.today() - timedelta(days=365),
            'valid_to': date.today() + timedelta(days=30),
            'responsible_user_id': self.user.id,
            'responsible_user_name': self.user.nickname,
            'status': 'normal',
            'created_by': self.user,
        }
        defaults.update(kwargs)
        return RadioLicense.objects.create(**defaults)

    def test_badge_only_counts_own_responsible(self):
        """同租户内别人负责的到期执照不进我的红点计数。"""
        today = date.today()
        self._make_license(station_name='MINE', valid_to=today + timedelta(days=10))
        other = _make_user('other_owner', tenant_id='t_badge')
        _grant_perms(other, [('radio_license', 'license', ['view'])])
        self._make_license(
            station_name='OTHERS', responsible_user_id=other.id,
            responsible_user_name=other.nickname, valid_to=today - timedelta(days=5),
        )

        resp = self.client.get('/radio-license/badge/')
        data = resp.json()['data']
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['expiring_count'], 1)
        self.assertEqual(data['expired_count'], 0)

        # 纯查看者（有查看权限但无负责记录）看到 0
        viewer = _make_user('pure_viewer', tenant_id='t_badge')
        _grant_perms(viewer, [('radio_license', 'license', ['view'])])
        resp = _make_client(viewer).get('/radio-license/badge/')
        self.assertEqual(resp.json()['data']['count'], 0)

        # other 只看到自己负责的那条过期执照
        other_client = _make_client(other)
        resp = other_client.get('/radio-license/badge/')
        data = resp.json()['data']
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['expired_count'], 1)

    def test_ack_excludes_from_badge(self):
        """点已处理后本周期不再计数，续期（valid_to 变化）后重新计数。"""
        today = date.today()
        lic = self._make_license(station_name='ACK-ME', valid_to=today + timedelta(days=10))

        resp = self.client.get('/radio-license/badge/')
        self.assertEqual(resp.json()['data']['count'], 1)

        self.client.post(
            '/radio-license/reminders/ack/',
            data=json.dumps({'license_id': lic.id}),
            content_type='application/json',
        )
        resp = self.client.get('/radio-license/badge/')
        self.assertEqual(resp.json()['data']['count'], 0)

        lic.valid_to = today + timedelta(days=20)
        lic.save()
        resp = self.client.get('/radio-license/badge/')
        self.assertEqual(resp.json()['data']['count'], 1)

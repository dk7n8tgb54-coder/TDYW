# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""上线门禁第五组：权限矩阵与租户隔离（后端接口逐项验证）。

权限编码：
- radio_license.license.view/add/edit/del
- radio_license.approval.view/add/edit/del
- radio_license.attachment.upload/download/delete

覆盖：无 view 权限访问列表/详情/提醒/徽标、仅 add 不能编辑、仅 edit 不能新增、
无 del 不能删除、无 upload/download 不能执行附件操作、
跨租户读写删下载全部隔离、责任人下拉不泄露其他租户用户、超管行为。
"""
import json
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.account.models import User
from apps.evidence.models import EvidenceAttachment
from apps.radio_license.models import RadioLicense, StationFrequencyApproval
from apps.radio_license.tests.release_gate import (
    _make_user, _grant_perms, _make_client,
    TENANT_A, TENANT_B, rg_license_payload, rg_approval_payload,
    rg_make_license, rg_make_approval,
)


def _perms(*items):
    """构造权限列表，items 形如 ('license', 'view') / ('attachment', 'upload')。"""
    grouped = {}
    for page, key in items:
        grouped.setdefault(page, []).append(key)
    return [('radio_license', page, keys) for page, keys in grouped.items()]


class LicensePermissionMatrixTests(TestCase):
    """执照权限矩阵（后端真实校验，非前端按钮隐藏）。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.today = date.today()
        # 数据属主：全权限
        self.owner = _make_user('rg_pm_owner', tenant_id=TENANT_A)
        _grant_perms(self.owner, _perms(
            ('license', 'view'), ('license', 'add'), ('license', 'edit'), ('license', 'del'),
            ('attachment', 'upload'), ('attachment', 'download'), ('attachment', 'delete')))
        self.owner_client = _make_client(self.owner)
        self.lic = rg_make_license(self.owner, station_name='RG-PM台站',
                                   valid_to=self.today + timedelta(days=10))
        resp = self.owner_client.post(
            f'/radio-license/{self.lic.id}/attachments/',
            {'file': SimpleUploadedFile('RG-PM附件.pdf', b'%PDF-1.4')})
        assert not resp.json().get('error'), resp.json()
        self.att = EvidenceAttachment.objects.get(file_name='RG-PM附件.pdf')

    def _user_with(self, *items, username='rg_pm_user'):
        user = _make_user(username, tenant_id=TENANT_A)
        if items:
            _grant_perms(user, _perms(*items))
        return user, _make_client(user)

    # ---- 无 view 权限 ----

    def test_no_view_cannot_access_list_detail_reminder_badge(self):
        cases = [
            ('rg_pm_nv_none', []),
            ('rg_pm_nv_add', [('license', 'add')]),
            ('rg_pm_nv_edit', [('license', 'edit')]),
        ]
        for username, items in cases:
            user, client = self._user_with(*items, username=username)
            body = client.get('/radio-license/').json()
            self.assertEqual(body.get('error'), '权限拒绝', f'{username} 无 view 访问列表: {body}')
            body = client.get(f'/radio-license/{self.lic.id}/').json()
            self.assertEqual(body.get('error'), '权限拒绝')
            body = client.get('/radio-license/reminders/popup/').json()
            self.assertEqual(body.get('error'), '权限拒绝')
            body = client.get('/radio-license/badge/').json()
            self.assertEqual(body.get('error'), '权限拒绝')
            body = client.get('/radio-license/responsible-users/').json()
            self.assertEqual(body.get('error'), '权限拒绝')

    # ---- add / edit 互斥 ----

    def test_add_only_cannot_edit(self):
        user, client = self._user_with(('license', 'view'), ('license', 'add'),
                                       username='rg_pm_addonly')
        payload = rg_license_payload(self.owner)
        payload['id'] = self.lic.id
        body = client.post('/radio-license/', data=json.dumps(payload),
                           content_type='application/json').json()
        self.assertTrue(body.get('error'), '仅 add 权限不应能编辑')
        self.lic.refresh_from_db()
        self.assertEqual(self.lic.station_name, 'RG-PM台站')

    def test_edit_only_cannot_add(self):
        user, client = self._user_with(('license', 'view'), ('license', 'edit'),
                                       username='rg_pm_editonly')
        payload = rg_license_payload(self.owner, station_name='RG-PM-越权新增')
        body = client.post('/radio-license/', data=json.dumps(payload),
                           content_type='application/json').json()
        self.assertTrue(body.get('error'), '仅 edit 权限不应能新增')
        self.assertFalse(RadioLicense.objects.filter(station_name='RG-PM-越权新增').exists())

    def test_add_only_can_add(self):
        user, client = self._user_with(('license', 'view'), ('license', 'add'),
                                       username='rg_pm_addok')
        payload = rg_license_payload(self.owner, station_name='RG-PM-新增OK',
                                     responsible_user_id=user.id)
        body = client.post('/radio-license/', data=json.dumps(payload),
                           content_type='application/json').json()
        self.assertFalse(body.get('error'), body)

    # ---- 无 del ----

    def test_no_del_cannot_delete(self):
        user, client = self._user_with(('license', 'view'), ('license', 'edit'),
                                       username='rg_pm_nodel')
        body = client.delete(f'/radio-license/?id={self.lic.id}').json()
        self.assertEqual(body.get('error'), '权限拒绝')
        self.assertTrue(RadioLicense.objects.filter(pk=self.lic.id).exists())

    # ---- 附件权限 ----

    def test_no_upload_cannot_upload(self):
        user, client = self._user_with(('license', 'view'), ('attachment', 'download'),
                                       username='rg_pm_noupload')
        resp = client.post(
            f'/radio-license/{self.lic.id}/attachments/',
            {'file': SimpleUploadedFile('RG-无上传.pdf', b'%PDF-1.4')})
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        self.assertFalse(EvidenceAttachment.objects.filter(file_name='RG-无上传.pdf').exists())

    def test_no_download_cannot_download(self):
        user, client = self._user_with(('license', 'view'), ('attachment', 'upload'),
                                       username='rg_pm_nodl')
        body = client.get(f'/radio-license/attachments/{self.att.id}/download/').json()
        self.assertEqual(body.get('error'), '权限拒绝')

    def test_no_delete_cannot_delete_attachment(self):
        user, client = self._user_with(('license', 'view'), ('attachment', 'upload'),
                                       username='rg_pm_nodelatt')
        body = client.delete(f'/radio-license/attachments/?id={self.att.id}').json()
        self.assertEqual(body.get('error'), '权限拒绝')
        self.att.refresh_from_db()
        self.assertFalse(self.att.is_deleted)

    def test_view_only_can_list_attachments_but_not_operate(self):
        user, client = self._user_with(('license', 'view'), username='rg_pm_viewonly')
        body = client.get(f'/radio-license/{self.lic.id}/attachments/').json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(len(body['data']), 1)
        resp = client.post(
            f'/radio-license/{self.lic.id}/attachments/',
            {'file': SimpleUploadedFile('RG-只读上传.pdf', b'%PDF-1.4')})
        self.assertEqual(resp.json().get('error'), '权限拒绝')


class ApprovalPermissionMatrixTests(TestCase):
    """批复权限矩阵。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.today = date.today()
        self.owner = _make_user('rg_apm_owner', tenant_id=TENANT_A)
        _grant_perms(self.owner, _perms(
            ('approval', 'view'), ('approval', 'add'), ('approval', 'edit'), ('approval', 'del'),
            ('attachment', 'upload'), ('attachment', 'download'), ('attachment', 'delete')))
        self.owner_client = _make_client(self.owner)
        self.ap = rg_make_approval(self.owner, doc_no='RG-APM',
                                   valid_to=self.today + timedelta(days=10))

    def _user_with(self, *items, username='rg_apm_user'):
        user = _make_user(username, tenant_id=TENANT_A)
        if items:
            _grant_perms(user, _perms(*items))
        return user, _make_client(user)

    def test_no_view_cannot_access_list_detail_reminder_badge(self):
        user, client = self._user_with(('approval', 'add'), username='rg_apm_nv')
        body = client.get('/radio-license/approvals/').json()
        self.assertEqual(body.get('error'), '权限拒绝')
        body = client.get(f'/radio-license/approvals/{self.ap.id}/').json()
        self.assertEqual(body.get('error'), '权限拒绝')
        body = client.get('/radio-license/approvals/reminders/popup/').json()
        self.assertEqual(body.get('error'), '权限拒绝')
        body = client.get('/radio-license/approvals/badge/').json()
        self.assertEqual(body.get('error'), '权限拒绝')
        body = client.get('/radio-license/approvals/responsible-users/').json()
        self.assertEqual(body.get('error'), '权限拒绝')

    def test_add_only_cannot_edit(self):
        user, client = self._user_with(('approval', 'view'), ('approval', 'add'),
                                       username='rg_apm_addonly')
        payload = rg_approval_payload(self.owner, doc_no='RG-APM')
        payload['id'] = self.ap.id
        body = client.post('/radio-license/approvals/', data=json.dumps(payload),
                           content_type='application/json').json()
        self.assertTrue(body.get('error'))

    def test_edit_only_cannot_add(self):
        user, client = self._user_with(('approval', 'view'), ('approval', 'edit'),
                                       username='rg_apm_editonly')
        payload = rg_approval_payload(self.owner, doc_no='RG-APM-越权')
        body = client.post('/radio-license/approvals/', data=json.dumps(payload),
                           content_type='application/json').json()
        self.assertTrue(body.get('error'))
        self.assertFalse(
            StationFrequencyApproval.objects.filter(doc_no='RG-APM-越权').exists())

    def test_no_del_cannot_delete(self):
        user, client = self._user_with(('approval', 'view'), ('approval', 'edit'),
                                       username='rg_apm_nodel')
        body = client.delete(f'/radio-license/approvals/?id={self.ap.id}').json()
        self.assertEqual(body.get('error'), '权限拒绝')
        self.assertTrue(StationFrequencyApproval.objects.filter(pk=self.ap.id).exists())

    def test_attachment_upload_without_approval_view_rejected(self):
        """仅有附件上传权限、无 approval.view 的用户不能通过批复端点上传。"""
        user, client = self._user_with(('attachment', 'upload'),
                                       username='rg_apm_uponly')
        resp = client.post(
            f'/radio-license/approvals/{self.ap.id}/attachments/',
            {'file': SimpleUploadedFile('RG-APM-无view.pdf', b'%PDF-1.4')})
        body = resp.json()
        self.assertTrue(body.get('error'))


class TenantIsolationTests(TestCase):
    """跨租户读写删下载下载全隔离 + 责任人列表 + 超管行为。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.today = date.today()
        self.user_a = _make_user('rg_ti_a', tenant_id=TENANT_A)
        _grant_perms(self.user_a, _perms(
            ('license', 'view'), ('license', 'add'), ('license', 'edit'), ('license', 'del'),
            ('approval', 'view'), ('approval', 'add'), ('approval', 'edit'), ('approval', 'del'),
            ('attachment', 'upload'), ('attachment', 'download'), ('attachment', 'delete')))
        self.client_a = _make_client(self.user_a)
        self.user_b = _make_user('rg_ti_b', tenant_id=TENANT_B)
        _grant_perms(self.user_b, _perms(
            ('license', 'view'), ('license', 'add'), ('license', 'edit'), ('license', 'del'),
            ('approval', 'view'), ('approval', 'add'), ('approval', 'edit'), ('approval', 'del'),
            ('attachment', 'upload'), ('attachment', 'download'), ('attachment', 'delete')))
        self.client_b = _make_client(self.user_b)
        # 租户 A 的数据
        self.lic_a = rg_make_license(self.user_a, station_name='RG-TI-A执照',
                                     valid_to=self.today + timedelta(days=10))
        self.ap_a = rg_make_approval(self.user_a, doc_no='RG-TI-A',
                                     valid_to=self.today + timedelta(days=10))
        resp = self.client_a.post(
            f'/radio-license/{self.lic_a.id}/attachments/',
            {'file': SimpleUploadedFile('RG-TI-A附件.pdf', b'%PDF-1.4')})
        assert not resp.json().get('error')
        self.att_a = EvidenceAttachment.objects.get(file_name='RG-TI-A附件.pdf')
        # 租户 B 的数据
        self.lic_b = rg_make_license(self.user_b, station_name='RG-TI-B执照',
                                     tenant_id=TENANT_B,
                                     valid_to=self.today + timedelta(days=10))
        self.ap_b = rg_make_approval(self.user_b, doc_no='RG-TI-B', tenant_id=TENANT_B,
                                     valid_to=self.today + timedelta(days=10))

    def test_tenant_b_cannot_read_tenant_a(self):
        body = self.client_b.get('/radio-license/').json()
        # 租户 B 只能看到自己的记录，看不到 A 的
        self.assertEqual([r['station_name'] for r in body['data']['records']],
                         ['RG-TI-B执照'])
        body = self.client_b.get(f'/radio-license/{self.lic_a.id}/').json()
        self.assertTrue(body.get('error'))
        body = self.client_b.get('/radio-license/approvals/').json()
        self.assertEqual(len(body['data']['records']), 1)  # 只有自己的 RG-TI-B
        body = self.client_b.get(f'/radio-license/approvals/{self.ap_a.id}/').json()
        self.assertTrue(body.get('error'))

    def test_tenant_b_cannot_modify_tenant_a(self):
        payload = rg_license_payload(self.user_b, station_name='RG-TI-篡改')
        payload['id'] = self.lic_a.id
        body = self.client_b.post('/radio-license/', data=json.dumps(payload),
                                  content_type='application/json').json()
        self.assertTrue(body.get('error'))
        self.lic_a.refresh_from_db()
        self.assertEqual(self.lic_a.station_name, 'RG-TI-A执照')
        payload = rg_approval_payload(self.user_b, doc_no='RG-TI-篡改')
        payload['id'] = self.ap_a.id
        body = self.client_b.post('/radio-license/approvals/', data=json.dumps(payload),
                                  content_type='application/json').json()
        self.assertTrue(body.get('error'))

    def test_tenant_b_cannot_delete_tenant_a(self):
        body = self.client_b.delete(f'/radio-license/?id={self.lic_a.id}').json()
        self.assertTrue(body.get('error'))
        self.assertTrue(RadioLicense.objects.filter(pk=self.lic_a.id).exists())
        body = self.client_b.delete(f'/radio-license/approvals/?id={self.ap_a.id}').json()
        self.assertTrue(body.get('error'))
        self.assertTrue(StationFrequencyApproval.objects.filter(pk=self.ap_a.id).exists())

    def test_tenant_b_cannot_download_tenant_a_attachment(self):
        body = self.client_b.get(
            f'/radio-license/attachments/{self.att_a.id}/download/').json()
        self.assertTrue(body.get('error'))
        body = self.client_b.get(
            f'/radio-license/approvals/attachments/{self.att_a.id}/download/').json()
        self.assertTrue(body.get('error'))

    def test_tenant_b_cannot_see_tenant_a_reminders(self):
        """popup 只返回本租户本人负责的记录。"""
        # user_b 负责自己的执照，但不应看到 A 的
        body = self.client_b.get('/radio-license/reminders/popup/').json()
        names = [r['station_name'] for r in body['data']['records']]
        self.assertEqual(names, ['RG-TI-B执照'])
        body = self.client_b.get('/radio-license/approvals/reminders/popup/').json()
        doc_nos = [r['doc_no'] for r in body['data']['records']]
        self.assertEqual(doc_nos, ['RG-TI-B'])

    def test_responsible_users_isolated_by_tenant(self):
        body = self.client_a.get('/radio-license/responsible-users/').json()
        ids = [u['id'] for u in body['data']]
        self.assertIn(self.user_a.id, ids)
        self.assertNotIn(self.user_b.id, ids, '执照责任人列表不得泄露其他租户用户')
        body = self.client_b.get('/radio-license/approvals/responsible-users/').json()
        ids = [u['id'] for u in body['data']]
        self.assertIn(self.user_b.id, ids)
        self.assertNotIn(self.user_a.id, ids, '批复责任人列表不得泄露其他租户用户')

    def test_responsible_users_exclude_disabled_and_soft_deleted(self):
        """禁用用户、软删用户不得出现在责任人下拉。"""
        from django.utils import timezone
        disabled = _make_user('rg_ti_disabled', tenant_id=TENANT_A, is_active=False)
        deleted = _make_user('rg_ti_deleted', tenant_id=TENANT_A)
        User.objects.filter(pk=deleted.id).update(deleted_by=self.user_a)
        body = self.client_a.get('/radio-license/responsible-users/').json()
        ids = [u['id'] for u in body['data']]
        self.assertNotIn(disabled.id, ids, '禁用用户不得出现在责任人列表')
        self.assertNotIn(deleted.id, ids, '软删用户不得出现在责任人列表')

    def test_superuser_cross_tenant_behavior(self):
        """超管跨租户可见是明确设计；但不得绕过存在性与软删除校验。"""
        supper = _make_user('rg_ti_supper', is_supper=True, tenant_id='rg_supper')
        _grant_perms(supper, _perms(
            ('license', 'view'), ('license', 'add'), ('license', 'edit'), ('license', 'del'),
            ('attachment', 'download')))
        client = _make_client(supper)
        # 跨租户列表可见（设计如此）
        body = client.get('/radio-license/').json()
        names = {r['station_name'] for r in body['data']['records']}
        self.assertIn('RG-TI-A执照', names)
        self.assertIn('RG-TI-B执照', names)
        # 不存在的记录仍报错
        body = client.get('/radio-license/999999/').json()
        self.assertTrue(body.get('error'))
        # 软删除附件不可下载（软删除校验不被权限绕过）
        EvidenceAttachment.objects.filter(pk=self.att_a.id).update(is_deleted=True)
        body = client.get(f'/radio-license/attachments/{self.att_a.id}/download/').json()
        self.assertTrue(body.get('error'), '超管不得下载已软删除附件')


class ResponsibleUserLeakTests(TestCase):
    """责任人列表泄露专项（执照 + 批复两个端点）。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user_a = _make_user('rg_leak_a', tenant_id=TENANT_A)
        _grant_perms(self.user_a, _perms(('license', 'view'), ('approval', 'view')))
        self.client_a = _make_client(self.user_a)
        self.user_b = _make_user('rg_leak_b', tenant_id=TENANT_B)
        _grant_perms(self.user_b, _perms(('license', 'view'), ('approval', 'view')))

    def test_both_responsible_user_endpoints_do_not_leak(self):
        for path in ('/radio-license/responsible-users/',
                     '/radio-license/approvals/responsible-users/'):
            body = self.client_a.get(path).json()
            self.assertFalse(body.get('error'), body)
            usernames = [u['username'] for u in body['data']]
            self.assertIn('rg_leak_a', usernames)
            self.assertNotIn('rg_leak_b', usernames, f'{path} 泄露了其他租户用户')
            # 不返回敏感字段
            for u in body['data']:
                self.assertEqual(sorted(u.keys()), ['id', 'nickname', 'username'])

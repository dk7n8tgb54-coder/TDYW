# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""台站频率批复全局数据范围（跨租户）行为测试（2026-09 第一轮改造）。

业务规则：
- 批复对拥有 radio_license.approval.* 权限的用户全局共享，tenant_id 仅作来源归属；
- 附件跨租户访问前必须通过「附件存在 + module/object_type 匹配 + 父批复存在」校验；
- 新附件归属父批复租户（owner_tenant_id），预览令牌绑定附件真实租户；
- 无权限用户由后端独立拒绝；其他模块附件不被公开。

覆盖：跨租户可见性一致性、无权限拒绝、伪造附件 ID、跨模块附件、
license 类型附件、附件计数、preview_token 租户绑定、软删附件拒绝。
"""
import json
import os
import tempfile
from datetime import date, timedelta

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.evidence.models import EvidenceAttachment
from apps.evidence.attachment_service import AttachmentService
from apps.radio_license.models import StationFrequencyApproval
from apps.radio_license.tests.release_gate import (
    _make_user, _grant_perms, _make_client,
    TENANT_A, TENANT_B, FULL_APPROVAL_PERMS, FULL_ATTACHMENT_PERMS,
    rg_make_approval,
)


def _pdf(name='RG-全局附件.pdf', content=b'%PDF-1.4 global scope test'):
    return SimpleUploadedFile(name, content, content_type='application/pdf')


def _extract_preview_token(preview_url):
    import base64
    from urllib.parse import urlparse, parse_qs
    encoded = preview_url.split('onlinePreview?url=')[1]
    inner = base64.b64decode(encoded).decode('utf-8')
    return parse_qs(urlparse(inner).query)['preview_token'][0]


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(prefix='rg_global_media_'),
    KKFILEVIEW_API_URL='http://kkfileview.test:8012',
    KKFILEVIEW_SERVER_URL='http://kkfileview-internal:8012',
)
class ApprovalGlobalScopeTests(TestCase):
    """批复跨租户可见性与附件安全闸门。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.today = date.today()
        # 租户 A 数据属主：全权限
        self.owner_a = _make_user('rg_gs_owner_a', tenant_id=TENANT_A)
        _grant_perms(self.owner_a, FULL_APPROVAL_PERMS + FULL_ATTACHMENT_PERMS)
        self.client_a = _make_client(self.owner_a)
        # 租户 B 用户：仅 view（用于验证只读可见性与越权写拒绝）
        self.viewer_b = _make_user('rg_gs_viewer_b', tenant_id=TENANT_B)
        _grant_perms(self.viewer_b, [('radio_license', 'approval', ['view'])])
        self.client_viewer_b = _make_client(self.viewer_b)
        # 租户 B 用户：全权限（跨租户读附件 + 上传 + 删除）
        self.admin_b = _make_user('rg_gs_admin_b', tenant_id=TENANT_B)
        _grant_perms(self.admin_b, FULL_APPROVAL_PERMS + FULL_ATTACHMENT_PERMS)
        self.client_admin_b = _make_client(self.admin_b)
        # 无任何权限的用户
        self.no_perm = _make_user('rg_gs_noperm', tenant_id=TENANT_B)
        self.client_no_perm = _make_client(self.no_perm)

        # 租户 A 的批复 + 附件
        self.ap_a = rg_make_approval(self.owner_a, doc_no='RG-GS-A',
                                     valid_to=self.today + timedelta(days=10))
        resp = self.client_a.post(
            f'/radio-license/approvals/{self.ap_a.id}/attachments/',
            {'file': _pdf('RG-GS-A附件.pdf')})
        assert not resp.json().get('error'), resp.json()
        self.att_a = EvidenceAttachment.objects.get(file_name='RG-GS-A附件.pdf')

    # ---- 可见性 ----

    def test_all_permitted_tenants_see_identical_approval_list(self):
        """不同租户、均拥有 approval.view 的用户看到相同的全部批复。"""
        ap_b = rg_make_approval(self.admin_b, doc_no='RG-GS-B', tenant_id=TENANT_B,
                                valid_to=self.today + timedelta(days=300))
        body_a = self.client_a.get('/radio-license/approvals/').json()
        body_b = self.client_admin_b.get('/radio-license/approvals/').json()
        body_view = self.client_viewer_b.get('/radio-license/approvals/').json()
        doc_nos_a = sorted(r['doc_no'] for r in body_a['data']['records'])
        doc_nos_b = sorted(r['doc_no'] for r in body_b['data']['records'])
        doc_nos_view = sorted(r['doc_no'] for r in body_view['data']['records'])
        self.assertEqual(doc_nos_a, ['RG-GS-A', 'RG-GS-B'])
        self.assertEqual(doc_nos_a, doc_nos_b)
        self.assertEqual(doc_nos_a, doc_nos_view)
        # 附件计数跨租户可见
        target = [r for r in body_view['data']['records'] if r['doc_no'] == 'RG-GS-A'][0]
        self.assertEqual(target['attachment_count'], 1)

    def test_no_view_perm_rejected_for_list_detail_attachments(self):
        """无 approval.view 的用户访问列表、详情、附件均被后端拒绝。"""
        body = self.client_no_perm.get('/radio-license/approvals/').json()
        self.assertEqual(body.get('error'), '权限拒绝')
        body = self.client_no_perm.get(
            f'/radio-license/approvals/{self.ap_a.id}/').json()
        self.assertEqual(body.get('error'), '权限拒绝')
        body = self.client_no_perm.get(
            f'/radio-license/approvals/{self.ap_a.id}/attachments/').json()
        self.assertEqual(body.get('error'), '权限拒绝')
        resp = self.client_no_perm.get(
            f'/radio-license/approvals/attachments/{self.att_a.id}/download/')
        self.assertTrue(resp.json().get('error'))
        body = self.client_no_perm.get(
            f'/radio-license/approvals/attachments/{self.att_a.id}/preview-url/').json()
        self.assertTrue(body.get('error'))

    # ---- 附件安全闸门 ----

    def test_forged_attachment_id_rejected(self):
        """伪造（不存在）的附件 ID 拒绝且不泄露信息。"""
        body = self.client_admin_b.get(
            '/radio-license/approvals/attachments/999999/download/').json()
        self.assertEqual(body.get('error'), '附件不存在或无权限访问')
        body = self.client_admin_b.get(
            '/radio-license/approvals/attachments/999999/preview-url/').json()
        self.assertEqual(body.get('error'), '附件不存在或无权限访问')

    def test_cross_module_attachment_via_approval_endpoints_rejected(self):
        """其他模块（合同/协作任务）附件不得通过批复附件端点访问。"""
        contract_att, error = AttachmentService.upload(
            file=SimpleUploadedFile('RG-GS合同.pdf', b'%PDF-1.4 cross'),
            user=self.owner_a, module='contract_agreement', object_type='agreement',
            object_id='800001',
        )
        self.assertIsNone(error, error)
        for url in (
            f'/radio-license/approvals/attachments/{contract_att.id}/download/',
            f'/radio-license/approvals/attachments/{contract_att.id}/preview-url/',
        ):
            body = self.client_admin_b.get(url).json()
            self.assertEqual(body.get('error'), '附件不存在或无权限访问', url)
        resp = self.client_admin_b.delete(
            f'/radio-license/approvals/attachments/?id={contract_att.id}')
        self.assertEqual(resp.json().get('error'), '附件不存在或无权限访问')
        contract_att.refresh_from_db()
        self.assertFalse(contract_att.is_deleted)

    def test_license_type_attachment_via_approval_endpoints_rejected(self):
        """module 相同但 object_type=license 的附件不得通过批复附件端点访问。"""
        license_att, error = AttachmentService.upload(
            file=SimpleUploadedFile('RG-GS执照.pdf', b'%PDF-1.4 license'),
            user=self.owner_a, module='radio_license', object_type='license',
            object_id='800002',
        )
        self.assertIsNone(error, error)
        body = self.client_admin_b.get(
            f'/radio-license/approvals/attachments/{license_att.id}/download/').json()
        self.assertEqual(body.get('error'), '附件不存在或无权限访问')
        resp = self.client_admin_b.delete(
            f'/radio-license/approvals/attachments/?id={license_att.id}')
        self.assertEqual(resp.json().get('error'), '附件不存在或无权限访问')
        license_att.refresh_from_db()
        self.assertFalse(license_att.is_deleted)

    def test_attachment_with_missing_parent_rejected(self):
        """附件指向的父批复不存在（脏数据）时拒绝访问。"""
        orphan_att, error = AttachmentService.upload(
            file=SimpleUploadedFile('RG-GS孤儿.pdf', b'%PDF-1.4 orphan'),
            user=self.owner_a, module='radio_license', object_type='approval',
            object_id='990001',
        )
        self.assertIsNone(error, error)
        self.assertFalse(
            StationFrequencyApproval.objects.filter(pk=990001).exists())
        body = self.client_admin_b.get(
            f'/radio-license/approvals/attachments/{orphan_att.id}/download/').json()
        self.assertEqual(body.get('error'), '附件不存在或无权限访问')

    # ---- 跨租户写操作 ----

    def test_cross_tenant_upload_uses_parent_approval_tenant(self):
        """跨租户上传的新附件使用父批复 tenant_id 而非上传人租户。"""
        resp = self.client_admin_b.post(
            f'/radio-license/approvals/{self.ap_a.id}/attachments/',
            {'file': _pdf('RG-GS-B上传.pdf')})
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        att = EvidenceAttachment.objects.get(file_name='RG-GS-B上传.pdf')
        self.assertEqual(att.tenant_id, TENANT_A)
        self.assertEqual(att.uploaded_by_id, self.admin_b.id)
        # 物理路径落在父批复租户段下
        self.assertTrue(att.file_path.startswith(os.path.join('radio_license', TENANT_A)))

    def test_cross_tenant_delete_attachment_and_cascade(self):
        """跨租户删除批复附件（软删），以及删除批复联动软删全部附件。"""
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client_admin_b.delete(
                f'/radio-license/approvals/attachments/?id={self.att_a.id}'
                f'&delete_reason=跨租户清理')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.att_a.refresh_from_db()
        self.assertTrue(self.att_a.is_deleted)
        self.assertEqual(self.att_a.delete_reason, '跨租户清理')

        # 再上传两条附件后跨租户删除批复
        resp = self.client_a.post(
            f'/radio-license/approvals/{self.ap_a.id}/attachments/',
            {'file': _pdf('RG-GS-A2.pdf')})
        self.assertFalse(resp.json().get('error'), resp.json())
        resp = self.client_admin_b.delete(
            f'/radio-license/approvals/?id={self.ap_a.id}')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertFalse(
            StationFrequencyApproval.objects.filter(pk=self.ap_a.id).exists())
        remaining = EvidenceAttachment.objects.all_with_deleted().filter(
            module='radio_license', object_type='approval',
            object_id=str(self.ap_a.id))
        self.assertTrue(remaining.exists())
        self.assertTrue(all(att.is_deleted for att in remaining))

    # ---- 预览令牌 ----

    def test_preview_token_binds_attachment_real_tenant(self):
        """预览令牌绑定附件真实租户，跨租户回调一致可用；kkFileView 回调成功。"""
        body = self.client_admin_b.get(
            f'/radio-license/approvals/attachments/{self.att_a.id}/preview-url/').json()
        self.assertFalse(body.get('error'), body)
        token = _extract_preview_token(body['data']['preview_url'])
        resp = self.client_admin_b.get(
            f'/radio-license/approvals/attachments/{self.att_a.id}/preview-file/'
            f'?preview_token={token}')
        self.assertEqual(resp.status_code, 200)

    def test_soft_deleted_attachment_rejected_cross_tenant(self):
        """软删除后的批复附件跨租户同样拒绝（不因 skip_tenant_filter 放开软删校验）。"""
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client_a.delete(
                f'/radio-license/approvals/attachments/?id={self.att_a.id}')
        self.assertFalse(resp.json().get('error'), resp.json())
        body = self.client_admin_b.get(
            f'/radio-license/approvals/attachments/{self.att_a.id}/download/').json()
        self.assertEqual(body.get('error'), '附件不存在或无权限访问')
        body = self.client_admin_b.get(
            f'/radio-license/approvals/{self.ap_a.id}/attachments/').json()
        self.assertEqual([a['file_name'] for a in body['data']], [])

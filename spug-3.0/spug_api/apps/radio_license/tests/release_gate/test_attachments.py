# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""上线门禁 E 组：附件和证据闭环测试。

覆盖：上传/列表/下载/预览/删除全链路（真实物理文件），
执照附件与批复附件隔离、跨模块越权、跨租户越权、软删除校验、
文件类型/大小/空文件/路径穿越文件名、preview_token 伪造与过期、
物理文件生命周期、执照/批复删除级联、证据包 ZIP。
"""
import io
import json
import os
import tempfile
import zipfile as zipfile_mod
from datetime import date, timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.evidence.models import EvidenceAttachment, EvidenceEvent
from apps.evidence.attachment_preview_token import generate_attachment_preview_token
from apps.evidence.attachment_service import AttachmentService
from apps.radio_license.models import RadioLicense, StationFrequencyApproval
from apps.radio_license.tests.release_gate import (
    _make_user, _grant_perms, _make_client,
    TENANT_A, TENANT_B, FULL_LICENSE_PERMS, FULL_APPROVAL_PERMS,
    FULL_ATTACHMENT_PERMS, rg_make_license, rg_make_approval,
)


def _pdf(name='RG测试文件.pdf', content=b'%PDF-1.4 RG release gate test file'):
    return SimpleUploadedFile(name, content, content_type='application/pdf')


def _extract_preview_token(preview_url):
    """从 kkFileView 预览 URL（base64 编码内层 URL）提取 preview_token。"""
    import base64
    from urllib.parse import urlparse, parse_qs
    encoded = preview_url.split('onlinePreview?url=')[1]
    inner = base64.b64decode(encoded).decode('utf-8')
    return parse_qs(urlparse(inner).query)['preview_token'][0]


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(prefix='rg_media_'),
    KKFILEVIEW_API_URL='http://kkfileview.test:8012',
    KKFILEVIEW_SERVER_URL='http://kkfileview-internal:8012',
)
class LicenseAttachmentLifecycleTests(TestCase):
    """E1 执照附件全链路：上传、列表、下载、预览、删除。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_att_admin', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS + FULL_ATTACHMENT_PERMS)
        self.client = _make_client(self.user)
        self.lic = rg_make_license(self.user, station_name='RG-ATT台站')

    def _upload(self, lic_id=None, file=None):
        return self.client.post(
            f'/radio-license/{lic_id or self.lic.id}/attachments/',
            {'file': file or _pdf()},
        )

    def test_upload_list_download_delete_full_lifecycle(self):
        # 上传
        resp = self._upload()
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        att = EvidenceAttachment.objects.get(file_name='RG测试文件.pdf')
        self.assertEqual(att.tenant_id, TENANT_A)
        self.assertEqual(att.module, 'radio_license')
        self.assertEqual(att.object_type, 'license')
        self.assertEqual(att.object_id, str(self.lic.id))
        self.assertEqual(att.file_size, len(b'%PDF-1.4 RG release gate test file'))
        self.assertTrue(att.file_hash_sha256)
        # 物理文件存在
        full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
        self.assertTrue(os.path.exists(full_path))
        # 列表
        body = self.client.get(f'/radio-license/{self.lic.id}/attachments/').json()
        self.assertFalse(body.get('error'), body)
        self.assertEqual(len(body['data']), 1)
        self.assertEqual(body['data'][0]['file_name'], 'RG测试文件.pdf')
        self.assertTrue(body['data'][0]['previewable'])
        # 下载（attachment 方式）
        resp = self.client.get(f'/radio-license/attachments/{att.id}/download/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('attachment', resp['Content-Disposition'])
        # 下载（inline 方式）
        resp = self.client.get(f'/radio-license/attachments/{att.id}/download/?inline=1')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('inline', resp['Content-Disposition'])
        # 预览 URL
        body = self.client.get(f'/radio-license/attachments/{att.id}/preview-url/').json()
        self.assertFalse(body.get('error'), body)
        self.assertIn('preview_url', body['data'])
        # 预览文件（无 x-token，模拟 kkFileView 回调）
        preview_token = _extract_preview_token(body['data']['preview_url'])
        resp = self.client.get(
            f'/radio-license/attachments/{att.id}/preview-file/?preview_token={preview_token}')
        self.assertEqual(resp.status_code, 200)
        # 删除：软删除 + 事务提交后删物理文件
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.delete(
                f'/radio-license/attachments/?id={att.id}&delete_reason=RG清理')
        self.assertFalse(resp.json().get('error'))
        att.refresh_from_db()
        self.assertTrue(att.is_deleted)
        self.assertEqual(att.delete_reason, 'RG清理')
        self.assertFalse(os.path.exists(full_path), '物理文件应在事务提交后删除')
        # 删除后列表排除、下载拒绝
        body = self.client.get(f'/radio-license/{self.lic.id}/attachments/').json()
        self.assertEqual(len(body['data']), 0)
        body = self.client.get(f'/radio-license/attachments/{att.id}/download/').json()
        self.assertTrue(body.get('error'))
        # 重复删除拒绝
        body = self.client.delete(f'/radio-license/attachments/?id={att.id}').json()
        self.assertTrue(body.get('error'))

    def test_upload_unsupported_extension_rejected(self):
        resp = self._upload(file=SimpleUploadedFile('RG恶意.exe', b'MZ'))
        body = resp.json()
        self.assertTrue(body.get('error'), body)
        self.assertFalse(
            EvidenceAttachment.objects.filter(file_name='RG恶意.exe').exists())

    def test_upload_oversize_rejected(self):
        big = SimpleUploadedFile('RG超大.pdf', b'x' * (50 * 1024 * 1024 + 1))
        resp = self._upload(file=big)
        body = resp.json()
        self.assertTrue(body.get('error'), body)
        self.assertFalse(EvidenceAttachment.objects.filter(file_name='RG超大.pdf').exists())

    def test_upload_empty_file_behavior(self):
        """空文件上传：记录行为（当前实现允许，size=0）。"""
        resp = self._upload(file=SimpleUploadedFile('RG空文件.pdf', b''))
        body = resp.json()
        if not body.get('error'):
            att = EvidenceAttachment.objects.get(file_name='RG空文件.pdf')
            self.assertEqual(att.file_size, 0)

    def test_upload_path_traversal_filename_sanitized(self):
        resp = self._upload(file=SimpleUploadedFile('../../RG穿越.pdf', b'%PDF-1.4'))
        body = resp.json()
        self.assertFalse(body.get('error'), body)
        att = EvidenceAttachment.objects.filter(
            object_id=str(self.lic.id), is_deleted=False).first()
        self.assertIsNotNone(att)
        # 存储路径不含目录穿越片段，物理路径必须仍在 MEDIA_ROOT 内
        from django.conf import settings
        self.assertNotIn('..', att.file_path)
        full_path = os.path.realpath(os.path.join(settings.MEDIA_ROOT, att.file_path))
        self.assertTrue(full_path.startswith(os.path.realpath(settings.MEDIA_ROOT)))
        self.assertTrue(os.path.exists(full_path))

    def test_upload_to_nonexistent_license_rejected(self):
        resp = self._upload(lic_id=999999)
        self.assertTrue(resp.json().get('error'))

    def test_upload_missing_file_param_rejected(self):
        resp = self.client.post(f'/radio-license/{self.lic.id}/attachments/')
        self.assertTrue(resp.json().get('error'))

    def test_upload_failure_leaves_no_db_record(self):
        """E9 校验失败时不得留下数据库成功记录。"""
        before = EvidenceAttachment.objects.count()
        self._upload(file=SimpleUploadedFile('RG坏类型.bat', b'x'))
        self.assertEqual(EvidenceAttachment.objects.count(), before)

    def test_download_missing_physical_file_returns_error(self):
        """物理文件丢失时下载应报错，而非返回损坏内容。"""
        resp = self._upload()
        att = EvidenceAttachment.objects.get(file_name='RG测试文件.pdf')
        from django.conf import settings
        full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
        os.remove(full_path)
        body = self.client.get(f'/radio-license/attachments/{att.id}/download/').json()
        self.assertTrue(body.get('error'))
        # 数据库记录仍在（下载失败不删除记录）
        att.refresh_from_db()
        self.assertFalse(att.is_deleted)


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(prefix='rg_media_'),
    KKFILEVIEW_API_URL='http://kkfileview.test:8012',
    KKFILEVIEW_SERVER_URL='http://kkfileview-internal:8012',
)
class AttachmentIsolationTests(TestCase):
    """E2/E3 附件越权访问：跨租户、跨对象类型、跨模块。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user_a = _make_user('rg_iso_a', tenant_id=TENANT_A)
        _grant_perms(self.user_a, FULL_LICENSE_PERMS + FULL_APPROVAL_PERMS + FULL_ATTACHMENT_PERMS)
        self.client_a = _make_client(self.user_a)
        self.user_b = _make_user('rg_iso_b', tenant_id=TENANT_B)
        _grant_perms(self.user_b, FULL_LICENSE_PERMS + FULL_APPROVAL_PERMS + FULL_ATTACHMENT_PERMS)
        self.client_b = _make_client(self.user_b)
        self.today = date.today()
        self.lic_a = rg_make_license(self.user_a, station_name='RG-ISO-A执照')
        self.ap_a = rg_make_approval(self.user_a, doc_no='RG-ISO-A批复')
        # 租户 A 执照附件 + 批复附件（真实文件）
        resp = self.client_a.post(
            f'/radio-license/{self.lic_a.id}/attachments/', {'file': _pdf('RG-A执照附件.pdf')})
        self.assertFalse(resp.json().get('error'), resp.json())
        resp = self.client_a.post(
            f'/radio-license/approvals/{self.ap_a.id}/attachments/', {'file': _pdf('RG-A批复附件.pdf')})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.lic_att = EvidenceAttachment.objects.get(file_name='RG-A执照附件.pdf')
        self.ap_att = EvidenceAttachment.objects.get(file_name='RG-A批复附件.pdf')

    def test_license_list_excludes_approval_attachments(self):
        body = self.client_a.get(f'/radio-license/{self.lic_a.id}/attachments/').json()
        names = [a['file_name'] for a in body['data']]
        self.assertEqual(names, ['RG-A执照附件.pdf'])

    def test_approval_list_excludes_license_attachments(self):
        body = self.client_a.get(f'/radio-license/approvals/{self.ap_a.id}/attachments/').json()
        names = [a['file_name'] for a in body['data']]
        self.assertEqual(names, ['RG-A批复附件.pdf'])

    def test_cross_tenant_download_rejected(self):
        body = self.client_b.get(f'/radio-license/attachments/{self.lic_att.id}/download/').json()
        self.assertTrue(body.get('error'))
        body = self.client_b.get(
            f'/radio-license/approvals/attachments/{self.ap_att.id}/download/').json()
        self.assertTrue(body.get('error'))

    def test_cross_tenant_upload_rejected(self):
        resp = self.client_b.post(
            f'/radio-license/{self.lic_a.id}/attachments/', {'file': _pdf('RG-B越权.pdf')})
        self.assertTrue(resp.json().get('error'))
        resp = self.client_b.post(
            f'/radio-license/approvals/{self.ap_a.id}/attachments/', {'file': _pdf('RG-B越权.pdf')})
        self.assertTrue(resp.json().get('error'))
        self.assertFalse(EvidenceAttachment.objects.filter(file_name='RG-B越权.pdf').exists())

    def test_cross_tenant_delete_rejected(self):
        resp = self.client_b.delete(f'/radio-license/attachments/?id={self.lic_att.id}')
        self.assertTrue(resp.json().get('error'))
        self.lic_att.refresh_from_db()
        self.assertFalse(self.lic_att.is_deleted)

    def test_cross_tenant_preview_url_rejected(self):
        body = self.client_b.get(
            f'/radio-license/attachments/{self.lic_att.id}/preview-url/').json()
        self.assertTrue(body.get('error'))

    def test_license_endpoint_cannot_delete_approval_attachment(self):
        """执照附件删除端点不得删除批复附件（对象类型隔离）。"""
        resp = self.client_a.delete(f'/radio-license/attachments/?id={self.ap_att.id}')
        body = resp.json()
        self.assertTrue(body.get('error'),
                        '执照删除端点删除批复附件应被拒绝，实际返回: %s' % body)
        self.ap_att.refresh_from_db()
        self.assertFalse(self.ap_att.is_deleted)

    def test_license_endpoint_cannot_download_approval_attachment(self):
        """执照附件下载端点不得下载批复附件（对象类型隔离）。"""
        resp = self.client_a.get(f'/radio-license/attachments/{self.ap_att.id}/download/')
        try:
            body = resp.json()
        except Exception:
            self.fail('执照下载端点返回了批复附件的文件流（越权下载成功）')
        self.assertTrue(body.get('error'),
                        '执照下载端点下载批复附件应被拒绝，实际返回: %s' % body)

    def test_license_endpoint_cannot_preview_approval_attachment(self):
        """执照预览端点不得为批复附件签发预览令牌。"""
        body = self.client_a.get(
            f'/radio-license/attachments/{self.ap_att.id}/preview-url/').json()
        self.assertTrue(body.get('error'),
                        '执照预览端点为批复附件签发令牌应被拒绝，实际返回: %s' % body)


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(prefix='rg_media_'),
    KKFILEVIEW_API_URL='http://kkfileview.test:8012',
    KKFILEVIEW_SERVER_URL='http://kkfileview-internal:8012',
)
class PreviewTokenSecurityTests(TestCase):
    """E5 preview_token：伪造、过期、对象不匹配、软删除后预览。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_token_user', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS + FULL_ATTACHMENT_PERMS)
        self.client = _make_client(self.user)
        self.lic = rg_make_license(self.user, station_name='RG-TOKEN台站')
        resp = self.client.post(
            f'/radio-license/{self.lic.id}/attachments/', {'file': _pdf('RG-TOKEN.pdf')})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.att = EvidenceAttachment.objects.get(file_name='RG-TOKEN.pdf')
        body = self.client.get(
            f'/radio-license/attachments/{self.att.id}/preview-url/').json()
        self.preview_token = _extract_preview_token(body['data']['preview_url'])

    def test_valid_token_serves_file_without_x_token(self):
        resp = self.client.get(
            f'/radio-license/attachments/{self.att.id}/preview-file/?preview_token={self.preview_token}')
        self.assertEqual(resp.status_code, 200)

    def test_forged_token_rejected(self):
        resp = self.client.get(
            f'/radio-license/attachments/{self.att.id}/preview-file/?preview_token=forged-token-abc')
        body = resp.json()
        self.assertTrue(body.get('error'))
        self.assertIn('无效或已过期', body['error'])

    def test_expired_token_rejected(self):
        with patch('apps.evidence.attachment_preview_token.ATTACHMENT_PREVIEW_TOKEN_MAX_AGE', -1):
            resp = self.client.get(
                f'/radio-license/attachments/{self.att.id}/preview-file/?preview_token={self.preview_token}')
        body = resp.json()
        self.assertTrue(body.get('error'))
        self.assertIn('无效或已过期', body['error'])

    def test_token_attachment_id_mismatch_rejected(self):
        # 用附件 A 的令牌访问另一个附件 ID
        other = rg_make_license(self.user, station_name='RG-TOKEN-其他执照')
        resp = self.client.post(
            f'/radio-license/{other.id}/attachments/', {'file': _pdf('RG-TOKEN-其他.pdf')})
        att2 = EvidenceAttachment.objects.get(file_name='RG-TOKEN-其他.pdf')
        resp = self.client.get(
            f'/radio-license/attachments/{att2.id}/preview-file/?preview_token={self.preview_token}')
        body = resp.json()
        self.assertTrue(body.get('error'))
        self.assertIn('不匹配', body['error'])

    def test_token_object_binding_tamper_rejected(self):
        """令牌绑定信息被篡改（签名失效）应拒绝。"""
        tampered = self.preview_token[:-2] + ('aa' if self.preview_token[-2:] != 'aa' else 'bb')
        resp = self.client.get(
            f'/radio-license/attachments/{self.att.id}/preview-file/?preview_token={tampered}')
        self.assertTrue(resp.json().get('error'))

    def test_missing_token_rejected(self):
        resp = self.client.get(f'/radio-license/attachments/{self.att.id}/preview-file/')
        self.assertTrue(resp.json().get('error'))

    def test_soft_deleted_attachment_preview_rejected(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(f'/radio-license/attachments/?id={self.att.id}')
        resp = self.client.get(
            f'/radio-license/attachments/{self.att.id}/preview-file/?preview_token={self.preview_token}')
        body = resp.json()
        self.assertTrue(body.get('error'))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='rg_media_'))
class ObjectDeletionCascadeTests(TestCase):
    """E7 删除执照/批复后的附件与关联数据级联行为。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_casc_user', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS + FULL_APPROVAL_PERMS + FULL_ATTACHMENT_PERMS)
        self.client = _make_client(self.user)

    def test_delete_license_cascades_everything(self):
        from apps.radio_license.models import (
            RadioLicenseFrequency, LicenseReminderAck,
        )
        lic = rg_make_license(self.user, station_name='RG-CASC-执照')
        RadioLicenseFrequency.objects.create(
            tenant_id=TENANT_A, license=lic, frequency_value=100.5,
            frequency_unit='MHz', created_by=self.user)
        LicenseReminderAck.objects.create(
            tenant_id=TENANT_A, license=lic, user_id=self.user.id,
            user_name=self.user.nickname, ack_valid_to=lic.valid_to)
        resp = self.client.post(
            f'/radio-license/{lic.id}/attachments/', {'file': _pdf('RG-CASC执照附件.pdf')})
        self.assertFalse(resp.json().get('error'), resp.json())
        att = EvidenceAttachment.objects.get(file_name='RG-CASC执照附件.pdf')
        from django.conf import settings
        full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
        self.assertTrue(os.path.exists(full_path))

        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.delete(f'/radio-license/?id={lic.id}')
        self.assertFalse(resp.json().get('error'))
        # 执照、频率、ack 物理删除
        self.assertFalse(RadioLicense.objects.filter(pk=lic.id).exists())
        self.assertFalse(RadioLicenseFrequency.objects.filter(license_id=lic.id).exists())
        self.assertFalse(LicenseReminderAck.objects.filter(license_id=lic.id).exists())
        # 附件软删除 + 物理文件删除
        att.refresh_from_db()
        self.assertTrue(att.is_deleted)
        self.assertFalse(os.path.exists(full_path))

    def test_delete_approval_cascades(self):
        from apps.radio_license.models import StationFrequencyApprovalReminderAck
        ap = rg_make_approval(self.user, doc_no='RG-CASC-批复')
        StationFrequencyApprovalReminderAck.objects.create(
            tenant_id=TENANT_A, approval=ap, user_id=self.user.id,
            user_name=self.user.nickname, ack_valid_to=ap.valid_to)
        resp = self.client.post(
            f'/radio-license/approvals/{ap.id}/attachments/', {'file': _pdf('RG-CASC批复附件.pdf')})
        self.assertFalse(resp.json().get('error'), resp.json())
        att = EvidenceAttachment.objects.get(file_name='RG-CASC批复附件.pdf')

        resp = self.client.delete(f'/radio-license/approvals/?id={ap.id}')
        self.assertFalse(resp.json().get('error'))
        # 批复、ack 物理删除
        self.assertFalse(
            StationFrequencyApproval.objects.filter(pk=ap.id).exists())
        self.assertFalse(
            StationFrequencyApprovalReminderAck.objects.filter(approval_id=ap.id).exists())
        # 附件软删除，记录保留
        att.refresh_from_db()
        self.assertTrue(att.is_deleted)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='rg_media_'))
class EvidencePackageTests(TestCase):
    """E8 证据包 ZIP：内容、文件名、权限与错误处理。"""

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user = _make_user('rg_pkg_user', tenant_id=TENANT_A)
        _grant_perms(self.user, FULL_LICENSE_PERMS + FULL_ATTACHMENT_PERMS)
        self.client = _make_client(self.user)
        self.lic = rg_make_license(self.user, station_name='RG-PKG台站')
        resp = self.client.post(
            f'/radio-license/{self.lic.id}/attachments/', {'file': _pdf('RG-PKG附件.pdf')})
        self.assertFalse(resp.json().get('error'), resp.json())

    def test_package_zip_content_and_names(self):
        resp = self.client.get(f'/radio-license/evidence/package/?id={self.lic.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/zip')
        content = b''.join(resp.streaming_content)
        with zipfile_mod.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            self.assertIn('object_snapshot.json', names)
            self.assertIn('evidence_events.json', names)
            self.assertIn('audit_logs.json', names)
            self.assertIn('hashes.json', names)
            self.assertIn('verify.txt', names)
            snapshot = json.loads(zf.read('object_snapshot.json'))
            self.assertEqual(snapshot['license']['station_name'], 'RG-PKG台站')
            hashes = json.loads(zf.read('hashes.json'))
            # 哈希清单只包含未删除附件
            att_names = [a['file_name'] for a in hashes['attachments']]
            self.assertEqual(att_names, ['RG-PKG附件.pdf'])
            self.assertTrue(hashes['attachments'][0]['sha256'])

    def test_package_missing_id_param(self):
        body = self.client.get('/radio-license/evidence/package/').json()
        self.assertTrue(body.get('error'))

    def test_package_nonexistent_license(self):
        body = self.client.get('/radio-license/evidence/package/?id=999999').json()
        self.assertTrue(body.get('error'))

    def test_package_cross_tenant_rejected(self):
        b_user = _make_user('rg_pkg_tenantb', tenant_id=TENANT_B)
        _grant_perms(b_user, FULL_LICENSE_PERMS)
        resp = _make_client(b_user).get(
            f'/radio-license/evidence/package/?id={self.lic.id}')
        body = resp.json()
        self.assertTrue(body.get('error'))


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(prefix='rg_media_'),
    KKFILEVIEW_API_URL='http://kkfileview.test:8012',
    KKFILEVIEW_SERVER_URL='http://kkfileview-internal:8012',
)
class LicenseAttachmentOwnershipTests(TestCase):
    """F-01~F-04 修复验证：执照附件端点专用归属校验与证据事件。

    覆盖：同租户跨模块附件（合同/协作任务/批复）通过执照附件端点的
    下载/删除/预览全部拒绝；绑定信息不匹配的 preview_token 拒绝；
    软删除后全端点拒绝；删除证据事件使用删除前快照且内容完整；
    重复删除不产生重复证据事件；物理文件删除失败时软删除状态仍正确。
    """

    def setUp(self):
        from apps.setting.utils import AppSetting
        AppSetting.set('bind_ip', False)
        self.user_a = _make_user('rg_own_a', tenant_id=TENANT_A)
        _grant_perms(self.user_a, FULL_LICENSE_PERMS + FULL_ATTACHMENT_PERMS)
        self.client_a = _make_client(self.user_a)
        self.lic_a = rg_make_license(self.user_a, station_name='RG-OWN执照')
        resp = self.client_a.post(
            f'/radio-license/{self.lic_a.id}/attachments/',
            {'file': _pdf('RG-OWN执照附件.pdf')})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.lic_att = EvidenceAttachment.objects.get(file_name='RG-OWN执照附件.pdf')
        self.lic_att_full_path = os.path.join(settings.MEDIA_ROOT, self.lic_att.file_path)

    def _make_foreign_attachment(self, module, object_type, name, object_id='900001'):
        """通过真实上传代码路径创建其他模块附件（同租户）。"""
        att, error = AttachmentService.upload(
            file=SimpleUploadedFile(name, b'%PDF-1.4 cross-module'),
            user=self.user_a, module=module, object_type=object_type,
            object_id=object_id,
        )
        self.assertIsNone(error, error)
        return att

    def _make_cross_module_attachments(self):
        contract = self._make_foreign_attachment(
            'contract_agreement', 'agreement', 'RG-OWN合同附件.pdf')
        coop = self._make_foreign_attachment(
            'coop_task', 'delivery', 'RG-OWN协作附件.pdf')
        approval = self._make_foreign_attachment(
            'radio_license', 'approval', 'RG-OWN批复附件.pdf', object_id='900002')
        return contract, coop, approval

    # ---------- F-01 下载越权 ----------

    def test_download_cross_module_attachments_rejected(self):
        for att in self._make_cross_module_attachments():
            resp = self.client_a.get(
                f'/radio-license/attachments/{att.id}/download/')
            body = resp.json()
            self.assertEqual(body.get('error'), '附件不存在或无权限访问',
                             f'附件 {att.file_name} 越权下载应被拒绝')
            # 附件记录不得被任何方式改动
            att.refresh_from_db()
            self.assertFalse(att.is_deleted)

    def test_download_inline_cross_module_attachment_rejected(self):
        contract, _, _ = self._make_cross_module_attachments()
        resp = self.client_a.get(
            f'/radio-license/attachments/{contract.id}/download/?inline=1')
        self.assertEqual(resp.json().get('error'), '附件不存在或无权限访问')

    def test_download_own_license_attachment_still_works(self):
        """合法执照附件（含 inline）不受新校验影响。"""
        resp = self.client_a.get(
            f'/radio-license/attachments/{self.lic_att.id}/download/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('attachment', resp['Content-Disposition'])
        resp = self.client_a.get(
            f'/radio-license/attachments/{self.lic_att.id}/download/?inline=1')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('inline', resp['Content-Disposition'])

    # ---------- F-02 删除越权 ----------

    def test_delete_cross_module_attachments_rejected(self):
        for att in self._make_cross_module_attachments():
            resp = self.client_a.delete(
                f'/radio-license/attachments/?id={att.id}&delete_reason=越权删除')
            self.assertTrue(resp.json().get('error'),
                            f'附件 {att.file_name} 越权删除应被拒绝')
            att.refresh_from_db()
            self.assertFalse(att.is_deleted, '被越权删除的附件不得被软删除')
            self.assertEqual(att.delete_reason, '', '删除原因不得被写入')

    # ---------- F-03 预览越权 ----------

    def test_preview_url_cross_module_attachments_rejected(self):
        for att in self._make_cross_module_attachments():
            body = self.client_a.get(
                f'/radio-license/attachments/{att.id}/preview-url/').json()
            self.assertEqual(body.get('error'), '附件不存在或无权限访问',
                             f'附件 {att.file_name} 越权预览签发应被拒绝')
            self.assertFalse(body.get('data'), '拒绝响应不得携带预览数据')

    def _make_bound_token(self, **overrides):
        """生成合法签名的 preview_token，默认绑定当前执照附件，可覆盖绑定项。"""
        data = dict(
            attachment_id=self.lic_att.id,
            user_id=self.user_a.id,
            tenant_id=TENANT_A,
            module='radio_license',
            object_type='license',
            object_id=str(self.lic_a.id),
        )
        data.update(overrides)
        return generate_attachment_preview_token(**data)

    def test_preview_file_binding_mismatch_tokens_rejected(self):
        """伪造绑定信息的合法签名 token：module/object_type/tenant_id 不匹配均拒绝。"""
        wrong_module = self._make_bound_token(
            module='contract_agreement', object_type='agreement', object_id='900001')
        wrong_object_type = self._make_bound_token(
            object_type='approval', object_id='900002')
        wrong_tenant = self._make_bound_token(tenant_id=TENANT_B)
        for name, token in [('module不匹配', wrong_module),
                            ('object_type不匹配', wrong_object_type),
                            ('tenant_id不匹配', wrong_tenant)]:
            resp = self.client_a.get(
                f'/radio-license/attachments/{self.lic_att.id}/preview-file/'
                f'?preview_token={token}')
            body = resp.json()
            # 本项目 API 约定 HTTP 200 + error 字段，不能以状态码判断拒绝
            self.assertTrue(body.get('error'), f'{name} 的令牌应被拒绝: {body}')
            self.assertFalse(body.get('data'), f'{name} 的令牌不得返回文件数据')

    # ---------- 软删除后全端点拒绝 ----------

    def test_soft_deleted_attachment_all_endpoints_rejected(self):
        body = self.client_a.get(
            f'/radio-license/attachments/{self.lic_att.id}/preview-url/').json()
        old_token = _extract_preview_token(body['data']['preview_url'])
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client_a.delete(
                f'/radio-license/attachments/?id={self.lic_att.id}')
        self.assertFalse(resp.json().get('error'))
        # 下载
        body = self.client_a.get(
            f'/radio-license/attachments/{self.lic_att.id}/download/').json()
        self.assertEqual(body.get('error'), '附件不存在或无权限访问')
        # 预览 URL 签发
        body = self.client_a.get(
            f'/radio-license/attachments/{self.lic_att.id}/preview-url/').json()
        self.assertEqual(body.get('error'), '附件不存在或无权限访问')
        # 旧令牌预览回调
        resp = self.client_a.get(
            f'/radio-license/attachments/{self.lic_att.id}/preview-file/'
            f'?preview_token={old_token}')
        self.assertTrue(resp.json().get('error'))
        # 重复删除
        resp = self.client_a.delete(
            f'/radio-license/attachments/?id={self.lic_att.id}')
        self.assertTrue(resp.json().get('error'))

    # ---------- F-04 证据事件 ----------

    def test_evidence_event_written_with_full_pre_delete_snapshot(self):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client_a.delete(
                f'/radio-license/attachments/?id={self.lic_att.id}'
                f'&delete_reason=门禁清理')
        self.assertFalse(resp.json().get('error'))
        # 数据库记录已软删除
        self.lic_att.refresh_from_db()
        self.assertTrue(self.lic_att.is_deleted)
        self.assertEqual(self.lic_att.delete_reason, '门禁清理')
        self.assertEqual(self.lic_att.deleted_by_id, self.user_a.id)
        # 物理文件已清理
        self.assertFalse(os.path.exists(self.lic_att_full_path))
        # 证据事件存在且字段完整
        ev = EvidenceEvent.objects.filter(
            tenant_id=TENANT_A, module='radio_license', object_type='license',
            object_id=str(self.lic_a.id), event_type='delete').first()
        self.assertIsNotNone(ev, '附件删除必须写入证据事件（F-04 死代码修复）')
        self.assertEqual(ev.actor_user_id, self.user_a.id)
        self.assertEqual(ev.actor_username, self.user_a.username)
        self.assertTrue(ev.event_title)
        snapshot = json.loads(ev.object_snapshot)
        self.assertEqual(snapshot['attachment_id'], self.lic_att.id)
        self.assertEqual(snapshot['file_name'], 'RG-OWN执照附件.pdf')
        self.assertEqual(snapshot['file_hash_sha256'], self.lic_att.file_hash_sha256)
        self.assertEqual(snapshot['module'], 'radio_license')
        self.assertEqual(snapshot['object_type'], 'license')
        self.assertEqual(snapshot['object_id'], str(self.lic_a.id))
        self.assertEqual(snapshot['tenant_id'], TENANT_A)
        self.assertEqual(snapshot['delete_reason'], '门禁清理')

    def test_repeat_delete_no_duplicate_evidence_event(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client_a.delete(
                f'/radio-license/attachments/?id={self.lic_att.id}')
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client_a.delete(
                f'/radio-license/attachments/?id={self.lic_att.id}')
        self.assertTrue(resp.json().get('error'))
        count = EvidenceEvent.objects.filter(
            tenant_id=TENANT_A, module='radio_license', object_type='license',
            object_id=str(self.lic_a.id), event_type='delete').count()
        self.assertEqual(count, 1, '重复删除不得产生重复证据事件')

    def test_physical_file_delete_failure_keeps_soft_delete_state(self):
        """物理文件删除失败时：DB 软删除保持正确，文件保留并留下可追踪错误日志。"""
        with patch(
            'apps.evidence.attachment_service.AttachmentService._remove_physical_file',
            return_value='附件文件删除失败，请稍后重试',
        ):
            with self.assertLogs('apps.evidence.attachment_service', level='ERROR'):
                with self.captureOnCommitCallbacks(execute=True):
                    resp = self.client_a.delete(
                        f'/radio-license/attachments/?id={self.lic_att.id}')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.lic_att.refresh_from_db()
        self.assertTrue(self.lic_att.is_deleted, '物理删除失败不得影响软删除状态')
        self.assertTrue(os.path.exists(self.lic_att_full_path),
                        '删除失败时物理文件应保留以便补偿重试')

    def test_legal_attachment_evidence_event_not_written_for_failed_delete(self):
        """越权删除被拒绝时不写任何证据事件。"""
        contract, _, _ = self._make_cross_module_attachments()
        before = EvidenceEvent.objects.filter(event_type='delete').count()
        self.client_a.delete(
            f'/radio-license/attachments/?id={contract.id}&delete_reason=越权')
        self.assertEqual(
            EvidenceEvent.objects.filter(event_type='delete').count(), before)

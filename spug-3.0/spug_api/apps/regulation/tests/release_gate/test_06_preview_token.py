"""R-06 下载、预览与令牌安全（P0/P1 安全契约）。

覆盖用户要求：
- PDF/图片原生预览返回正确 Content-Type、Content-Length、inline disposition
- Office/文本在 kkFileView 配置完整时返回正确预览地址
- kkFileView 未配置时返回明确降级错误，不得 500
- 下载权限与预览权限分别验证
- 缺少 / 过期 / 篡改 / 错误附件 ID / 错误规章 ID / 错误 module / object_type 的令牌必须失败
- 已软删除附件、文件不存在、file_path 越界时不得返回文件内容
- 不能通过修改 URL 中的规章 ID 读取其他规章附件
"""
import base64
import os
import time
from unittest.mock import patch
from urllib.parse import quote

from django.conf import settings
from django.core.signing import TimestampSigner, b62_encode

from apps.evidence.attachment_preview_token import (
    generate_attachment_preview_token, validate_attachment_preview_token,
)
from apps.regulation.models import RegulationAttachment
from .base import RegulationGateTestCase


def _decode_kk_url(resp):
    """还原 kkFileView 预览地址中的 base64 回源 URL。"""
    encoded = resp.json()['data']['preview_url'].split('url=', 1)[1]
    return base64.b64decode(encoded).decode('utf-8')


class DownloadBehaviourTests(RegulationGateTestCase):
    """R-06-01 下载响应头与内容

    ⚠️ test_download_audit_event_recorded 为 defect_reproduction（REG-AUDIT-001，P1）：
    action='download_attachment' 不在 audit_action_valid 白名单内，审计事件被静默丢弃。
    """

    def setUp(self):
        super().setUp()
        self.content = b'%PDF-1.4 download-body'
        self.att = self.make_attachment_record(self.regulation, 'dl.pdf', self.content)

    def test_download_default_is_attachment_disposition(self):
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/download/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('attachment', resp['Content-Disposition'])
        self.assertEqual(resp['Content-Type'], 'application/octet-stream')
        self.assertEqual(int(resp['Content-Length']), len(self.content))
        self.assertEqual(b''.join(resp.streaming_content), self.content)

    def test_inline_pdf_returns_pdf_content_type(self):
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/download/?inline=1')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('inline', resp['Content-Disposition'])
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertEqual(int(resp['Content-Length']), len(self.content))

    def test_inline_image_returns_image_content_type(self):
        content = b'\x89PNG\r\n\x1a\nimagebody'
        att = self.make_attachment_record(self.regulation, 'img.png', content)
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{att.id}/download/?inline=1')
        self.assertEqual(resp['Content-Type'], 'image/png')
        self.assertEqual(int(resp['Content-Length']), len(content))

    def test_filename_present_in_disposition(self):
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/download/')
        self.assertIn('filename=', resp['Content-Disposition'])
        self.assertIn('UTF-8', resp['Content-Disposition'])

    def test_download_audit_event_recorded(self):
        self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/download/')
        from apps.logs.models import AuditLog
        log = AuditLog.objects.filter(
            target_type='regulation', action='download_attachment',
            target_id=str(self.regulation.id)).first()
        self.assertIsNotNone(log, '下载附件应产生 download_attachment 审计事件')
        self.assertEqual(log.username, self.downloader.username)

    def test_download_missing_physical_file_returns_business_error(self):
        os.remove(os.path.join(self._tmp_storage, self.att.file_path))
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/download/')
        self.assertEqual(resp.json()['error'], '文件不存在')
        self.assertEqual(resp.status_code, 200, '缺失文件不得产生 500')

    def test_download_path_traversal_record_returns_business_error(self):
        """file_path 越界的附件记录不得泄漏区域外文件内容"""
        secret = os.path.join(self._tmp_storage, 'secret.txt')
        with open(secret, 'wb') as fh:
            fh.write(b'TOP-SECRET')
        att = self.make_attachment_record(
            self.regulation, 'evil.pdf', b'x',
            file_path='regulation/../../secret.txt')
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{att.id}/download/')
        self.assertEqual(resp.json()['error'], '文件不存在')
        self.assertNotIn(b'TOP-SECRET', resp.content)
        self.assertTrue(os.path.exists(secret))

    def test_soft_deleted_attachment_not_downloadable(self):
        RegulationAttachment.objects.filter(pk=self.att.pk).update(is_deleted=True)
        resp = self.downloader_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/download/')
        self.assertEqual(resp.json()['error'], '附件不存在')
        self.assertNotIn(self.content, resp.content)


class PreviewUrlTests(RegulationGateTestCase):
    """R-06-02 预览地址生成与 kkFileView 降级"""

    def setUp(self):
        super().setUp()
        self.att = self.make_attachment_record(self.regulation, 'pv.pdf', b'%PDF-1.4 pv')

    def test_pdf_uses_native_preview(self):
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/preview-url/')
        data = resp.json()['data']
        self.assertEqual(data['preview_type'], 'native')
        self.assertIn('preview_token=', data['preview_url'])
        self.assertIn('/preview-file/', data['preview_url'])
        self.assertNotIn('x-token', data['preview_url'])

    def test_image_uses_native_preview(self):
        att = self.make_attachment_record(self.regulation, 'pv.png', b'\x89PNG')
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{att.id}/preview-url/')
        self.assertEqual(resp.json()['data']['preview_type'], 'native')

    def test_office_uses_kkfileview_when_configured(self):
        att = self.make_attachment_record(self.regulation, 'pv.docx', b'PK\x03\x04')
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{att.id}/preview-url/')
        data = resp.json()['data']
        self.assertEqual(resp.json()['error'], '')
        self.assertEqual(data['preview_type'], 'kkfileview')
        self.assertIn('onlinePreview', data['preview_url'])
        decoded = _decode_kk_url(resp)
        self.assertIn('fullfilename=', decoded)
        self.assertIn('/preview-file/', decoded)
        self.assertIn('preview_token=', decoded)

    def test_kkfileview_callback_url_points_to_server_not_browser_host(self):
        """回源地址必须使用 KKFILEVIEW_SERVER_URL（容器可达），不能用浏览器地址"""
        att = self.make_attachment_record(self.regulation, 'pv4.docx', b'PK\x03\x04')
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{att.id}/preview-url/')
        decoded = _decode_kk_url(resp)
        self.assertTrue(decoded.startswith(settings.KKFILEVIEW_SERVER_URL),
                        '回源地址应指向 KKFILEVIEW_SERVER_URL')

    def test_kkfileview_url_uses_stored_name_as_cache_key(self):
        att = self.make_attachment_record(self.regulation, 'pv2.docx', b'PK\x03\x04')
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{att.id}/preview-url/')
        self.assertIn('fullfilename=%s' % quote(att.stored_name), _decode_kk_url(resp),
                      'kkFileView 缓存键应使用 stored_name')

    def test_kkfileview_unconfigured_returns_graceful_error(self):
        """kkFileView 未配置时返回明确降级错误，不得 500"""
        att = self.make_attachment_record(self.regulation, 'pv3.docx', b'PK\x03\x04')
        original_api = 'KKFILEVIEW_API_URL'
        del original_api
        with patch('apps.regulation.views.settings.KKFILEVIEW_API_URL', ''), \
                patch('apps.regulation.views.settings.KKFILEVIEW_SERVER_URL', ''):
            resp = self.viewer_client.get(
                f'/regulation/{self.regulation.id}/attachments/{att.id}/preview-url/')
        self.assertEqual(resp.status_code, 200, 'kkFileView 未配置不得 500')
        self.assertIn('未配置', resp.json()['error'])

    def test_preview_requires_only_view_permission(self):
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/preview-url/')
        self.assertEqual(resp.json()['error'], '')

    def test_soft_deleted_attachment_not_previewable(self):
        RegulationAttachment.objects.filter(pk=self.att.pk).update(is_deleted=True)
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/preview-url/')
        self.assertEqual(resp.json()['error'], '附件不存在')


class PreviewFileTokenTests(RegulationGateTestCase):
    """R-06-03 预览令牌安全"""

    def setUp(self):
        super().setUp()
        self.content = b'%PDF-1.4 preview-secret-body'
        self.att = self.make_attachment_record(self.regulation, 'tk.pdf', self.content)

    def _preview(self, token, att_id=None, reg_id=None):
        att_id = att_id or self.att.id
        reg_id = reg_id or self.regulation.id
        return self.viewer_client.get(
            f'/regulation/{reg_id}/attachments/{att_id}/preview-file/?preview_token={token}')

    def test_valid_token_streams_file(self):
        token = self.preview_token(self.viewer_client, self.regulation.id, self.att.id)
        resp = self._preview(token)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('inline', resp['Content-Disposition'])
        self.assertEqual(b''.join(resp.streaming_content), self.content)

    def test_missing_token_rejected(self):
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/preview-file/')
        self.assertEqual(resp.json()['error'], '缺少 preview_token 参数')

    def test_invalid_signature_rejected(self):
        resp = self._preview('garbage-token-value')
        self.assertEqual(resp.json()['error'], '预览令牌无效或已过期')
        self.assertNotIn(self.content, resp.content)

    def test_tampered_token_rejected(self):
        token = self.preview_token(self.viewer_client, self.regulation.id, self.att.id)
        tampered = token[:-3] + ('abc' if not token.endswith('abc') else 'xyz')
        resp = self._preview(tampered)
        self.assertEqual(resp.json()['error'], '预览令牌无效或已过期')
        self.assertNotIn(self.content, resp.content)

    def test_expired_token_rejected(self):
        signer = TimestampSigner()
        data = f'{self.att.id}:{self.viewer.id}::regulation:regulation:{self.regulation.id}'
        old_ts = b62_encode(int(time.time()) - 400)
        expired = f'{data}:{old_ts}:{signer.signature(f"{data}:{old_ts}")}'
        self.assertIsNone(validate_attachment_preview_token(expired),
                          '超过 300 秒的令牌应失效')
        resp = self._preview(expired)
        self.assertEqual(resp.json()['error'], '预览令牌无效或已过期')
        self.assertNotIn(self.content, resp.content)

    def test_token_for_other_attachment_rejected(self):
        other = self.make_attachment_record(self.regulation2, 'other.pdf', b'OTHER-BODY')
        token = self.preview_token(self.viewer_client, self.regulation2.id, other.id)
        resp = self._preview(token, att_id=self.att.id, reg_id=self.regulation.id)
        self.assertEqual(resp.json()['error'], '预览令牌与请求附件不匹配')
        self.assertNotIn(b'OTHER-BODY', resp.content)

    def test_token_with_wrong_regulation_id_rejected(self):
        token = generate_attachment_preview_token(
            attachment_id=self.att.id, user_id=self.viewer.id, tenant_id='',
            module='regulation', object_type='regulation',
            object_id=str(self.regulation2.id))
        resp = self._preview(token)
        self.assertEqual(resp.json()['error'], '预览令牌无效')
        self.assertNotIn(self.content, resp.content)

    def test_token_with_wrong_module_rejected(self):
        token = generate_attachment_preview_token(
            attachment_id=self.att.id, user_id=self.viewer.id, tenant_id='',
            module='evidence', object_type='regulation',
            object_id=str(self.regulation.id))
        resp = self._preview(token)
        self.assertEqual(resp.json()['error'], '预览令牌无效')

    def test_token_with_wrong_object_type_rejected(self):
        token = generate_attachment_preview_token(
            attachment_id=self.att.id, user_id=self.viewer.id, tenant_id='',
            module='regulation', object_type='contract',
            object_id=str(self.regulation.id))
        resp = self._preview(token)
        self.assertEqual(resp.json()['error'], '预览令牌无效')

    def test_tampering_url_regulation_id_cannot_read_other_attachment(self):
        other = self.make_attachment_record(self.regulation2, 'tk2.pdf', b'OTHER-REG-BODY')
        token = self.preview_token(self.viewer_client, self.regulation2.id, other.id)
        resp = self._preview(token, att_id=other.id, reg_id=self.regulation.id)
        self.assertNotEqual(resp.json()['error'], '')
        self.assertNotIn(b'OTHER-REG-BODY', resp.content)

    def test_soft_deleted_attachment_token_denied(self):
        token = self.preview_token(self.viewer_client, self.regulation.id, self.att.id)
        RegulationAttachment.objects.filter(pk=self.att.pk).update(is_deleted=True)
        resp = self._preview(token)
        self.assertEqual(resp.json()['error'], '附件不存在')
        self.assertNotIn(self.content, resp.content)

    def test_missing_physical_file_token_denied(self):
        token = self.preview_token(self.viewer_client, self.regulation.id, self.att.id)
        os.remove(os.path.join(self._tmp_storage, self.att.file_path))
        resp = self._preview(token)
        self.assertEqual(resp.json()['error'], '文件不存在')

    def test_traversal_file_path_token_denied(self):
        secret = os.path.join(self._tmp_storage, 'preview-secret.txt')
        with open(secret, 'wb') as fh:
            fh.write(b'PREVIEW-TOP-SECRET')
        att = self.make_attachment_record(self.regulation, 'tr.pdf', b'x',
                                          file_path='regulation/../../preview-secret.txt')
        token = self.preview_token(self.viewer_client, self.regulation.id, att.id)
        resp = self._preview(token, att_id=att.id)
        self.assertEqual(resp.json()['error'], '文件不存在')
        self.assertNotIn(b'PREVIEW-TOP-SECRET', resp.content)

    def test_x_token_in_url_rejected_on_preview_endpoint(self):
        resp = self.viewer_client.get(
            f'/regulation/{self.regulation.id}/attachments/{self.att.id}/preview-file/'
            f'?x-token={self.viewer.access_token}')
        self.assertEqual(resp.status_code, 401)

    def test_middleware_matches_api_prefixed_preview_path(self):
        """生产环境经 nginx 的 /api/ 前缀路径必须命中 preview 鉴权白名单"""
        from libs.middleware import AuthenticationMiddleware
        self.assertTrue(AuthenticationMiddleware._is_attachment_preview_endpoint(
            '/api/regulation/1/attachments/2/preview-file/'))
        self.assertTrue(AuthenticationMiddleware._is_attachment_preview_endpoint(
            '/regulation/1/attachments/2/preview-file/'))
        self.assertFalse(AuthenticationMiddleware._is_attachment_preview_endpoint(
            '/api/regulation/1/attachments/2/download/'))

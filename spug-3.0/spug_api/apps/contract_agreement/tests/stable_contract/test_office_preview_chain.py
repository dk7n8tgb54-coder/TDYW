# -*- coding: utf-8 -*-
"""kkFileView Office 文档预览链路稳定契约测试（覆盖遗留观察项 3b）。

与 test_attachments.py 中用 override_settings 伪造 kkFileView 地址的用例不同，
本测试**使用容器真实配置**（KKFILEVIEW_API_URL / KKFILEVIEW_SERVER_URL / ALLOWED_HOSTS），
验证"配置正确性"而不只是"代码逻辑正确性"：

1. preview-url 返回的地址以真实 KKFILEVIEW_API_URL 开头且含 onlinePreview；
2. 内嵌回源 file_url 以真实 KKFILEVIEW_SERVER_URL 开头、回调路径/令牌/文件名齐全；
3. KKFILEVIEW_SERVER_URL 的主机名已在 ALLOWED_HOSTS 中（防 DisallowedHost 静默断链）；
4. 用真实令牌机制回调 preview-file 能拿到与上传一致的文件字节。

说明：kkFileView 服务的存活与 LibreOffice 转换不在本测试范围（依赖外部进程），
由 E2E CA017（真实浏览器加载 kkFileView 预览页）与回源连通性巡检覆盖。
"""
import io
import zipfile
from unittest import skipUnless
from urllib.parse import urlparse, parse_qs, unquote

from django.conf import settings

from .base import ContractTestCase, make_agreement, upload_file

KK_CONFIGURED = bool(
    getattr(settings, 'KKFILEVIEW_API_URL', '')
    and getattr(settings, 'KKFILEVIEW_SERVER_URL', '')
)


def build_minimal_docx():
    """构造一个 LibreOffice 可打开的最小合法 docx（ZIP 容器 + 三要素）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            '[Content_Types].xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>')
        zf.writestr(
            '_rels/.rels',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>'
            '</Relationships>')
        zf.writestr(
            'word/document.xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>kkfileview chain test</w:t></w:r></w:p></w:body>'
            '</w:document>')
    return buf.getvalue()


@skipUnless(KK_CONFIGURED, '容器未配置 KKFILEVIEW_API_URL/SERVER_URL，跳过真实链路测试')
class OfficePreviewChainTest(ContractTestCase):
    """docx 上传 → preview-url（真实配置）→ 回调文件流一致

    基类 ContractTestCase 已为本次运行分配独立 MEDIA_ROOT，无需额外覆盖。
    """

    DOCX_BYTES = build_minimal_docx()

    def setUp(self):
        super().setUp()
        ag = make_agreement(self.user, contract_name='Office预览链路合同')
        up = self.upload(ag.id, upload_file('链路测试.docx', self.DOCX_BYTES,
                                            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'))
        self.assertNoError(up, 'docx 应上传成功')
        self.att_id = up['data']['id']

    def _fetch_preview_url(self):
        body = self.get_json(f'{self.URL}attachments/{self.att_id}/preview-url/')
        self.assertNoError(body, f'真实配置下 preview-url 应成功: {body}')
        return body['data']['preview_url']

    def test_preview_url_uses_real_api_url(self):
        preview_url = self._fetch_preview_url()
        api_url = settings.KKFILEVIEW_API_URL
        self.assertTrue(preview_url.startswith(api_url),
                        f'preview_url 应以真实 KKFILEVIEW_API_URL({api_url}) 开头: {preview_url}')
        self.assertIn('onlinePreview?url=', preview_url)

    def test_embedded_file_url_uses_real_server_url(self):
        from urllib.parse import urlparse, parse_qs
        from base64 import b64decode
        preview_url = self._fetch_preview_url()
        encoded = parse_qs(urlparse(preview_url).query)['url'][0]
        file_url = b64decode(encoded).decode('utf-8')

        server_url = settings.KKFILEVIEW_SERVER_URL
        self.assertTrue(file_url.startswith(server_url),
                        f'回源 file_url 应以真实 KKFILEVIEW_SERVER_URL({server_url}) 开头: {file_url}')
        self.assertIn(f'/api/contract-agreement/attachments/{self.att_id}/preview-file/', file_url)
        self.assertIn('preview_token=', file_url)
        self.assertIn('fullfilename=', file_url)

    def test_server_url_host_in_allowed_hosts(self):
        """回源主机必须在 ALLOWED_HOSTS 中，否则 kkFileView 回调被 Django 拒绝（静默断链）。"""
        server_url = settings.KKFILEVIEW_SERVER_URL
        host = urlparse(server_url).hostname
        allowed = settings.ALLOWED_HOSTS
        self.assertTrue(
            host in allowed or '*' in allowed,
            f'KKFILEVIEW_SERVER_URL 主机名 {host!r} 不在 ALLOWED_HOSTS({allowed}) 中，'
            f'kkFileView 回源将被 DisallowedHost 拒绝')

    def test_callback_returns_uploaded_bytes(self):
        """用真实令牌机制回调 preview-file，必须流式返回与上传一致的文件字节。"""
        from urllib.parse import urlparse, parse_qs
        from base64 import b64decode
        preview_url = self._fetch_preview_url()
        encoded = parse_qs(urlparse(preview_url).query)['url'][0]
        file_url = b64decode(encoded).decode('utf-8')

        parsed = urlparse(file_url)
        token = parse_qs(parsed.query)['preview_token'][0]
        filename = unquote(parse_qs(parsed.query)['fullfilename'][0])
        self.assertTrue(filename, 'fullfilename 应为物理文件名')

        # file_url 中的 /api 前缀是 nginx 层映射；Django URLconf 挂载在 /contract-agreement/ 下
        path = parsed.path[len('/api'):] if parsed.path.startswith('/api') else parsed.path
        resp = self.client.get(path, {'preview_token': token})
        self.assertEqual(resp.status_code, 200, f'回调应返回 200: {resp.status_code}')
        body = b''.join(resp.streaming_content) if resp.streaming else resp.content
        self.assertEqual(body, self.DOCX_BYTES, '回调返回的字节应与上传的 docx 完全一致')

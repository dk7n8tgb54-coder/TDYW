"""下载、预览与预览令牌发布门禁测试（stable_contract）。

覆盖：下载内容与响应头、文本读取、图片/PDF 预览、kkFileView 配置、
      preview_token 有效/过期/伪造/跨文件/跨作用域、二进制响应不被误判。
"""
import base64
import os

from django.conf import settings
from django.test import Client, TestCase

from apps.document.libs.preview_token import (
    PREVIEW_TOKEN_MAX_AGE, generate_preview_token, validate_preview_token)
from apps.document.models import DocumentFilePublic
from tests.helpers.test_base import (
    get_response_data, has_error, make_client, make_user, setup_test_env)

from .helpers import (
    PB, PB_VIEW, PERM_DOWNLOAD, PERM_UPLOAD, PERM_VIEW, StorageCleanupMixin,
    bind_party_building, make_file, make_folder, unique)


class DownloadPreviewTokenTest(StorageCleanupMixin, TestCase):
    """下载 / 预览 / 预览令牌"""

    @classmethod
    def setUpTestData(cls):
        # 同时具备普通与党建查看权限，确保作用域校验能被触达
        cls.user = make_user('gate_dl', perms=[PERM_VIEW, PERM_UPLOAD,
                                               PERM_DOWNLOAD, PB_VIEW])

    def setUp(self):
        super().setUp()
        setup_test_env()
        self.client = make_client(self.user)
        self.client.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'
        self.folder = make_folder(name=unique('下载目录'), created_by=self.user)

    # ---------- 1. 下载 ----------

    def test_01_download_content_and_headers(self):
        """下载返回正确内容、文件名与 Content-Type"""
        obj = make_file(folder=self.folder, created_by=self.user,
                        name=unique('下载') + '.txt', content=b'gate-download-payload')
        self.track_path(obj.file_path)
        resp = self.client.get('/document/download/',
                               {'id': obj.id, 'is_public': 'true'})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('application/json', resp['Content-Type'],
                         '下载不应返回 JSON')
        body = b''.join(resp.streaming_content) if resp.streaming else resp.content
        self.assertEqual(body, b'gate-download-payload')
        self.assertIn('attachment', resp.get('Content-Disposition', ''))
        # 中文文件名按 RFC 5987 做百分号编码
        from urllib.parse import quote
        self.assertIn(quote(obj.display_name), resp.get('Content-Disposition', ''))
        self.assertIn("filename*=UTF-8''", resp.get('Content-Disposition', ''),
                      '必须提供 RFC 5987 文件名，兼容非 ASCII 文件名')

    def test_02_download_missing_file(self):
        """下载不存在的记录返回明确错误"""
        resp = self.client.get('/document/download/',
                               {'id': 99999999, 'is_public': 'true'})
        self.assertEqual(resp.json().get('error'), '文件不存在', resp.json())

    def test_03_download_when_physical_file_gone(self):
        """物理文件已丢失时下载返回明确错误"""
        obj = make_file(folder=self.folder, created_by=self.user)
        os.remove(obj.file_path)
        resp = self.client.get('/document/download/',
                               {'id': obj.id, 'is_public': 'true'})
        self.assertEqual(resp.json().get('error'), '文件不存在', resp.json())

    def test_04_binary_response_is_not_misread_as_error(self):
        """二进制下载响应不会被判定为业务错误"""
        payload = b'\x89PNG\r\n\x1a\n' + os.urandom(64)
        obj = make_file(folder=self.folder, created_by=self.user,
                        name=unique('bin') + '.bin', content=payload)
        self.track_path(obj.file_path)
        resp = self.client.get('/document/download/',
                               {'id': obj.id, 'is_public': 'true'})
        self.assertEqual(resp.status_code, 200)
        body = b''.join(resp.streaming_content) if resp.streaming else resp.content
        self.assertEqual(body, payload)

    # ---------- 2. 文本内容 ----------

    def test_05_text_content_reading(self):
        """文本内容接口正确读取 UTF-8 文本"""
        obj = make_file(folder=self.folder, created_by=self.user,
                        name=unique('文本') + '.txt', content='中文内容ABC'.encode('utf-8'))
        self.track_path(obj.file_path)
        resp = self.client.get('/document/text_content/',
                               {'id': obj.id, 'is_public': 'true'})
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data['content'], '中文内容ABC')

    def test_06_text_content_oversize_rejected(self):
        """超过文本预览上限被拒"""
        obj = make_file(folder=self.folder, created_by=self.user,
                        name=unique('大文本') + '.txt', content=b'x' * (2 * 1024 * 1024 + 1))
        self.track_path(obj.file_path)
        resp = self.client.get('/document/text_content/',
                               {'id': obj.id, 'is_public': 'true'})
        self.assertTrue(has_error(resp), '超大文本应被拒绝')

    # ---------- 3. 预览 ----------

    def test_07_preview_pdf_inline(self):
        """PDF 预览以 inline 方式返回"""
        obj = make_file(folder=self.folder, created_by=self.user,
                        name=unique('doc') + '.pdf', content=b'%PDF-1.4 fake')
        obj.file_type = 'application/pdf'
        obj.save(update_fields=['file_type'])
        self.track_path(obj.file_path)
        resp = self.client.get('/document/preview/',
                               {'id': obj.id, 'is_public': 'true'})
        self.assertEqual(resp.status_code, 200)
        if 'application/json' in resp['Content-Type']:
            self.assertFalse(has_error(resp), resp.json())
        else:
            self.assertIn('application/pdf', resp['Content-Type'])

    def test_08_preview_unsupported_type_rejected(self):
        """不支持预览的类型返回明确错误"""
        obj = make_file(folder=self.folder, created_by=self.user,
                        name=unique('unknown') + '.zip', content=b'zzz')
        obj.file_type = 'application/zip'
        obj.save(update_fields=['file_type'])
        self.track_path(obj.file_path)
        resp = self.client.get('/document/preview/',
                               {'id': obj.id, 'is_public': 'true'})
        self.assertTrue(has_error(resp), resp.json())

    # ---------- 4. kkFileView 配置 ----------

    def test_09_office_preview_url_uses_configured_endpoints(self):
        """Office 预览 URL 使用浏览器地址 + 容器回源地址"""
        obj = make_file(folder=self.folder, created_by=self.user,
                        name=unique('报告') + '.docx', content=b'PK\x03\x04 fake')
        self.track_path(obj.file_path)
        resp = self.client.get('/document/office_preview_url/',
                               {'id': obj.id, 'is_public': 'true'})
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        url = data['preview_url']
        self.assertTrue(url.startswith(settings.KKFILEVIEW_API_URL),
                        f'浏览器地址应以 KKFILEVIEW_API_URL 开头: {url}')
        b64 = url.split('url=')[-1]
        inner = base64.b64decode(b64).decode('utf-8')
        self.assertTrue(inner.startswith(settings.KKFILEVIEW_SERVER_URL),
                        f'回源地址应以 KKFILEVIEW_SERVER_URL 开头: {inner}')
        self.assertIn('preview_token=', inner, '回源 URL 必须带预览令牌')

    def test_10_office_preview_url_rejects_non_office(self):
        """非 Office 文件不生成 kkFileView 预览 URL"""
        obj = make_file(folder=self.folder, created_by=self.user,
                        name=unique('普通') + '.txt', content=b'plain')
        self.track_path(obj.file_path)
        resp = self.client.get('/document/office_preview_url/',
                               {'id': obj.id, 'is_public': 'true'})
        self.assertTrue(has_error(resp), resp.json())

    # ---------- 5. 预览令牌 ----------

    def test_11_preview_token_generated(self):
        """生成预览令牌"""
        obj = make_file(folder=self.folder, created_by=self.user)
        self.track_path(obj.file_path)
        resp = self.client.get('/document/preview_token/',
                               {'id': obj.id, 'is_public': 'true'})
        self.assertFalse(has_error(resp), resp.json())
        self.assertTrue(get_response_data(resp)['preview_token'])

    def test_12_preview_token_roundtrip(self):
        """令牌可在无会话场景下通过校验（kkFileView 回源依赖此能力）"""
        obj = make_file(folder=self.folder, created_by=self.user)
        self.track_path(obj.file_path)
        token = generate_preview_token(
            obj.id, self.user.id, self.user.tenant_id, True, '')
        payload = validate_preview_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload['file_id'], obj.id)
        self.assertEqual(payload['user_id'], self.user.id)

    def test_13_preview_token_expired_rejected(self):
        """过期令牌被拒"""
        obj = make_file(folder=self.folder, created_by=self.user)
        self.track_path(obj.file_path)
        token = generate_preview_token(
            obj.id, self.user.id, self.user.tenant_id, True, '')
        self.assertIsNone(validate_preview_token(token, max_age=-1),
                          '过期令牌必须失效')
        self.assertEqual(PREVIEW_TOKEN_MAX_AGE, 300)

    def test_14_preview_token_forged_rejected(self):
        """伪造令牌被拒"""
        obj = make_file(folder=self.folder, created_by=self.user)
        self.track_path(obj.file_path)
        token = generate_preview_token(
            obj.id, self.user.id, self.user.tenant_id, True, '')
        forged = token[:-3] + 'AAA'
        self.assertIsNone(validate_preview_token(forged))

    def test_15_preview_token_cannot_be_used_for_other_file(self):
        """A 文件的令牌不能用于预览 B 文件"""
        a = make_file(folder=self.folder, created_by=self.user)
        b = make_file(folder=self.folder, created_by=self.user)
        self.track_path(a.file_path)
        self.track_path(b.file_path)
        token = generate_preview_token(
            a.id, self.user.id, self.user.tenant_id, True, '')

        anon = Client()
        anon.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'
        resp = anon.get('/document/preview/',
                        {'id': b.id, 'is_public': 'true', 'preview_token': token})
        body = resp.json() if 'application/json' in resp['Content-Type'] else {}
        self.assertEqual(body.get('error'), '预览令牌与请求文件不匹配', body)

    def test_16_preview_token_scope_mismatch_rejected(self):
        """普通作用域令牌不能用于党建作用域请求"""
        pb_root = make_folder(name=unique('党建根'), created_by=self.user)
        bind_party_building(pb_root)
        obj = make_file(folder=self.folder, created_by=self.user)
        self.track_path(obj.file_path)
        token = generate_preview_token(
            obj.id, self.user.id, self.user.tenant_id, True, '')

        anon = Client()
        anon.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'
        resp = anon.get('/document/preview/',
                        {'id': obj.id, 'is_public': 'true',
                         'system_folder': PB, 'preview_token': token})
        body = resp.json() if 'application/json' in resp['Content-Type'] else {}
        self.assertTrue(body.get('error'), body)
        self.assertIn('作用域', body.get('error', ''))

    def test_17_preview_token_valid_can_download(self):
        """有效令牌可在无 X-Token 场景下预览（kkFileView 回源主链路）"""
        obj = make_file(folder=self.folder, created_by=self.user,
                        name=unique('令牌') + '.txt', content=b'token-ok')
        self.track_path(obj.file_path)
        resp = self.client.get('/document/preview_token/',
                               {'id': obj.id, 'is_public': 'true'})
        token = get_response_data(resp)['preview_token']

        anon = Client()
        anon.defaults['HTTP_X_REAL_IP'] = '127.0.0.1'
        resp2 = anon.get('/document/preview/',
                         {'id': obj.id, 'is_public': 'true', 'preview_token': token})
        self.assertEqual(resp2.status_code, 200)
        if 'application/json' in resp2['Content-Type']:
            self.assertFalse(has_error(resp2), resp2.json())
        else:
            body = b''.join(resp2.streaming_content) if resp2.streaming else resp2.content
            self.assertEqual(body, b'token-ok')

    def test_18_preview_does_not_leak_pb_file(self):
        """预览不能越权访问党建文件"""
        pb_root = make_folder(name=unique('党建根'), created_by=self.user)
        bind_party_building(pb_root)
        pb_file = make_file(folder=pb_root, created_by=self.user)
        self.track_path(pb_file.file_path)
        resp = self.client.get('/document/preview/',
                               {'id': pb_file.id, 'is_public': 'true'})
        self.assertTrue(resp.json().get('error'), resp.json())

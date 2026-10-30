# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""ONLYOFFICE 在线编辑的真实行为测试

覆盖（验收范围 1/2）：
- 编辑配置：需有效编辑会话+编制角色；config 含 JWT 签名与 oo-editor-file
  取文件地址；未配置编辑服务时降级 editor_available=false。
- DS 取文件：editor_token 自认证（无 x-token），令牌绑定手册+修订号；
  伪造/跨手册/旧修订拒绝。
- DS 回调（官方 JSON 协议）：JWT 必需（Authorization: Bearer）；JWT 载荷
  为权威 body；users 数组归属账号；角色/会话/归档校验；回调 key 必须
  等于会话当前签发 key（迟到/旧编辑实例回调拒绝）；同一编辑实例连续
  forcesave 可继续保存；重复回调按内容哈希幂等；文件仅允许从本服务
  编辑器下载通道取回，大小受限。
"""
import base64
import datetime
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from django.conf import settings as dj_settings
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.institution import storage
from apps.institution.models import (Manual, ManualDraft, ManualEditSession,
                                     ManualFile, ManualOperationLog)
from apps.institution.onlyoffice_jwt import sign_payload, verify_token
from apps.institution.tests.base import (
    PERM_DRAFT, delete_json, get_data, has_error, make_client, make_user,
)
from apps.institution.views_draft import build_editor_token
from apps.institution.tests.characterization.test_manual_draft import (
    DraftWorkflowBase,
)

TEST_SECRET = 'unit-test-onlyoffice-secret'


def _docx(content):
    return b'PK\x03\x04 ' + content


def _bare_client():
    return Client()


def _bare_manual():
    return Manual.objects.create(
        name='另一本手册', code='OT-001',
        owner_type=Manual.OWNER_SECTION, owner_name='乙科室', tenant_id='deptA')


class _StubDocServer:
    """本地桩：模拟 DS 回调中 url 指向的文件下载源（可配置字节/状态码）"""

    def __init__(self, payload=_docx(b'callback-content'), status=200):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if outer.status != 200:
                    self.send_response(outer.status)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Type',
                                 'application/vnd.openxmlformats-officedocument'
                                 '.wordprocessingml.document')
                self.send_header('Content-Length', str(len(outer.payload)))
                self.end_headers()
                self.wfile.write(outer.payload)

            def log_message(self, *args):
                pass

        self.payload = payload
        self.status = status
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class OnlyOfficeJwtTests(TestCase):
    """HS256 最小实现的签名/校验行为"""

    def test_sign_verify_roundtrip(self):
        token = sign_payload({'a': 1, 'b': ['x']}, TEST_SECRET)
        self.assertEqual(verify_token(token, TEST_SECRET), {'a': 1, 'b': ['x']})

    def test_wrong_secret_rejected(self):
        token = sign_payload({'a': 1}, TEST_SECRET)
        self.assertIsNone(verify_token(token, 'other-secret'))

    def test_tampered_payload_rejected(self):
        token = sign_payload({'status': 6}, TEST_SECRET)
        header, payload, sig = token.split('.')
        tampered = json.loads(base64.urlsafe_b64decode(payload + '=='))
        tampered['status'] = 1
        forged_payload = base64.urlsafe_b64encode(
            json.dumps(tampered).encode()).rstrip(b'=').decode()
        self.assertIsNone(verify_token(f'{header}.{forged_payload}.{sig}', TEST_SECRET))

    def test_alg_none_downgrade_rejected(self):
        header = base64.urlsafe_b64encode(
            json.dumps({'alg': 'none', 'typ': 'JWT'}).encode()).rstrip(b'=').decode()
        payload = base64.urlsafe_b64encode(b'{"status": 6}').rstrip(b'=').decode()
        self.assertIsNone(verify_token(f'{header}.{payload}.', TEST_SECRET))

    def test_non_dict_header_or_payload_rejected(self):
        """header/payload 段为 JSON 标量或数组：返回 None 而非抛 AttributeError"""
        scalar_header = base64.urlsafe_b64encode(b'2').rstrip(b'=').decode()
        list_header = base64.urlsafe_b64encode(b'[1]').rstrip(b'=').decode()
        payload = base64.urlsafe_b64encode(b'{"status": 6}').rstrip(b'=').decode()
        self.assertIsNone(verify_token(f'{scalar_header}.{payload}.AA', TEST_SECRET))
        self.assertIsNone(verify_token(f'{list_header}.{payload}.AA', TEST_SECRET))
        scalar_payload = base64.urlsafe_b64encode(b'2').rstrip(b'=').decode()
        good_header = base64.urlsafe_b64encode(
            json.dumps({'alg': 'HS256'}).encode()).rstrip(b'=').decode()
        self.assertIsNone(
            verify_token(f'{good_header}.{scalar_payload}.AA', TEST_SECRET))


@override_settings(ONLYOFFICE_DOCS_URL='http://onlyoffice:80',
                   ONLYOFFICE_JWT_SECRET=TEST_SECRET,
                   ONLYOFFICE_PUBLIC_BASE_URL='http://tdyw')
class EditorConfigTests(DraftWorkflowBase):
    """编辑配置端点：会话/角色/状态校验与 config 组装"""

    def setUp(self):
        super().setUp()
        self.session_key = ''
        self._set_password()
        self._add_file()

    def _get_config(self, client=None):
        client = client or self.editor_client
        return client.get(
            f'/institution/manuals/{self.manual.id}/draft/editor-config/'
            f'?session_key={self.session_key}')

    def start_session(self):
        resp = self._start_session()
        self.assertFalse(has_error(resp), resp.content)
        self.session_key = get_data(resp)['session_key']

    def test_config_requires_session(self):
        resp = self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/draft/editor-config/')
        self.assertTrue(has_error(resp))

    def test_config_happy_path_with_signed_jwt(self):
        self.start_session()
        resp = self._get_config()
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertTrue(data['editor_available'])
        self.assertEqual(data['editor_type'], 'onlyoffice')
        self.assertIn('/web-apps/apps/api/documents/api.js', data['editor_api_url'])
        draft = self._main_draft()
        self.assertTrue(data['document_key'].startswith(
            f"oo-{self.manual.id}-f{self.file_id}-r{draft.revision}-"))
        # JWT 可被我们的校验器验证且 document.key 一致
        payload = verify_token(data['token'], TEST_SECRET)
        self.assertIsNotNone(payload)
        self.assertEqual(payload['document']['key'], data['document_key'])
        self.assertEqual(payload['editorConfig']['user']['id'],
                         str(self.editor.id))
        # 取文件地址指向编辑器专用通道，携带 token
        self.assertIn('/attachments/oo-editor-file/?token=',
                      data['config']['document']['url'])
        self.assertIn('/attachments/oo-editor-callback/',
                      data['config']['editorConfig']['callbackUrl'])
        self.assertTrue(data['config']['document']['permissions']['edit'])
        # document key 记录到会话（迟到回调防护的比对基准）
        session = ManualEditSession.objects.get(session_key=self.session_key)
        self.assertEqual(session.current_doc_key, data['document_key'])

    def test_config_reissue_rotates_doc_key(self):
        """同会话重新取配置换 key：旧编辑实例回调将因 key 不匹配被拒"""
        self.start_session()
        key1 = get_data(self._get_config())['document_key']
        key2 = get_data(self._get_config())['document_key']
        self.assertNotEqual(key1, key2)
        session = ManualEditSession.objects.get(session_key=self.session_key)
        self.assertEqual(session.current_doc_key, key2)

    def test_config_requires_edit_role(self):
        self.start_session()
        outsider = make_user('o2', tenant_id='deptA', perms=[PERM_DRAFT])
        resp = make_client(outsider).get(
            f'/institution/manuals/{self.manual.id}/draft/editor-config/'
            f'?session_key={self.session_key}')
        self.assertTrue(has_error(resp))

    def test_config_unconfigured_degrades(self):
        self.start_session()
        with override_settings(ONLYOFFICE_DOCS_URL='', ONLYOFFICE_JWT_SECRET=''):
            resp = self._get_config()
        self.assertFalse(has_error(resp), resp.content)
        self.assertFalse(get_data(resp)['editor_available'])

    def test_config_archived_manual_rejected(self):
        self.start_session()
        self.manual.status = 'archived'
        self.manual.save(update_fields=['status'])
        resp = self._get_config()
        self.assertTrue(has_error(resp))
        self.assertIn('归档', resp.json()['error'])


@override_settings(ONLYOFFICE_DOCS_URL='http://onlyoffice:80',
                   ONLYOFFICE_JWT_SECRET=TEST_SECRET,
                   ONLYOFFICE_PUBLIC_BASE_URL='http://tdyw')
class OoEditorFileTests(DraftWorkflowBase):
    """DS 取文件：editor_token 自认证与绑定校验"""

    def setUp(self):
        super().setUp()
        self._set_password()
        self._add_file()
        resp = self._start_session()
        self.session_key = get_data(resp)['session_key']
        config = get_data(self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/draft/editor-config/'
            f'?session_key={self.session_key}'))
        self.editor_file_token = config['config']['document']['url'].split('token=')[1]
        self.draft = self._main_draft()
        self.file_entry = ManualFile.objects.get(pk=self.file_id)
        self.file_path = (f'/institution/manuals/{self.manual.id}/'
                          f'files/{self.file_id}/attachments/oo-editor-file/')

    def _get_file(self, token):
        # DS 请求不携带 x-token：用裸 Client 模拟
        return _bare_client().get(f'{self.file_path}?token={token}')

    def test_download_with_valid_token_without_x_token(self):
        resp = self._get_file(self.editor_file_token)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.streaming)

    def test_download_without_token_rejected(self):
        self.assertEqual(_bare_client().get(self.file_path).status_code, 403)

    def test_download_tampered_token_rejected(self):
        resp = self._get_file(self.editor_file_token[:-4] + 'aaaa')
        self.assertEqual(resp.status_code, 403)

    def test_download_token_bound_to_manual(self):
        other = _bare_manual()
        token = build_editor_token(other, self.file_entry, self.draft, self.editor)
        self.assertEqual(self._get_file(token).status_code, 403)

    def test_download_token_bound_to_file(self):
        """令牌与 URL 中的文件 ID 交叉核对：同一制度下换成别的文件即拒"""
        other_file = ManualFile.objects.create(
            manual=self.manual, display_name='另一份.docx', sort_order=9)
        token = build_editor_token(
            self.manual, other_file, self.draft, self.editor)
        self.assertEqual(self._get_file(token).status_code, 403)

    def test_download_stale_revision_rejected(self):
        """令牌签发后草稿被保存过（修订号变化）→ 拒绝，DS 须重取配置"""
        resp = self._save_draft(self.session_key, self.draft.revision)
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(self._get_file(self.editor_file_token).status_code, 409)


@override_settings(ONLYOFFICE_DOCS_URL='http://onlyoffice:80',
                   ONLYOFFICE_JWT_SECRET=TEST_SECRET)
class OoEditorCallbackTests(DraftWorkflowBase):
    """DS 保存回调（JSON 协议）：JWT/归属/会话/迟到防护/幂等"""

    def setUp(self):
        super().setUp()
        self._set_password()
        self._add_file()
        resp = self._start_session()
        self.session_key = get_data(resp)['session_key']
        self.draft = self._main_draft()
        self.file_entry = ManualFile.objects.get(pk=self.file_id)
        self.callback_path = (
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'attachments/oo-editor-callback/')
        self._stub = None
        self._base_patcher = None

    def tearDown(self):
        self._stop_base_patcher()
        if self._stub:
            self._stub.stop()
        super().tearDown()

    def _start_stub(self, payload=_docx(b'callback-content'), status=200):
        """启动文件桩并把 ONLYOFFICE_DOCS_URL 指向它（真实 requests 下载；

        协议中回调 url 指向 DS 自身缓存文件，故白名单来源 = DS origin）
        """
        self._stub = _StubDocServer(payload=payload, status=status)
        self._stop_base_patcher()
        self._base_patcher = patch.object(
            dj_settings, 'ONLYOFFICE_DOCS_URL', self._stub.base_url)
        self._base_patcher.start()
        return self._stub

    def _stop_base_patcher(self):
        if self._base_patcher:
            self._base_patcher.stop()
            self._base_patcher = None

    def _issue_config(self):
        """走真实配置端点签发 document key（写入会话 current_doc_key）"""
        config = get_data(self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/draft/editor-config/'
            f'?session_key={self.session_key}'))
        return config['document_key']

    def _current_key(self):
        return ManualEditSession.objects.get(
            session_key=self.session_key).current_doc_key

    def _post_callback(self, body, sign=True, token_override=None,
                       content_type='application/json'):
        headers = {}
        if sign:
            token = token_override or sign_payload(body, TEST_SECRET)
            headers['HTTP_AUTHORIZATION'] = f'Bearer {token}'
        return self.editor_client.post(
            self.callback_path, data=json.dumps(body),
            content_type=content_type, **headers)

    def _save_body(self, doc_key, url, status=6, users=None):
        return {
            'key': doc_key,
            'status': status,
            'url': url,
            'users': users if users is not None else [f'uid-{self.editor.id}'],
        }

    # -- 协议与认证 --

    def test_callback_without_jwt_rejected(self):
        body = self._save_body('oo-1-r1-00000000', 'http://x/y.docx')
        resp = self._post_callback(body, sign=False)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._main_draft().revision, 1)

    def test_callback_with_forged_jwt_rejected(self):
        body = self._save_body('oo-1-r1-00000000', 'http://x/y.docx')
        resp = self._post_callback(body, token_override=sign_payload(body, 'wrong'))
        self.assertEqual(resp.status_code, 403)

    def test_callback_non_json_rejected(self):
        resp = self.editor_client.post(self.callback_path, data=b'not-json',
                                       content_type='text/plain')
        self.assertEqual(resp.status_code, 400)

    def test_callback_status_mismatch_between_body_and_jwt(self):
        body = self._save_body('oo-1-r1-00000000', 'http://x/y.docx', status=6)
        signed = dict(body, status=1)
        resp = self._post_callback(
            body, token_override=sign_payload(signed, TEST_SECRET))
        self.assertEqual(resp.status_code, 400)

    def test_callback_config_token_replay_rejected(self):
        """编辑配置 token（合法签名、载荷无 status）重放到回调端点：403

        防"持有效编辑会话者用 config token 冒充回调凭证、以未签名 body
        全权注入内容/伪造归属"的绕过。
        """
        stub = self._start_stub()
        doc_key = self._issue_config()
        url = f'{stub.base_url}/docs/{doc_key}.docx'
        body = self._save_body(doc_key, url)
        config_token = sign_payload(
            {'document': {'key': doc_key},
             'editorConfig': {'callbackUrl': 'x'}},
            TEST_SECRET)
        resp = self._post_callback(body, token_override=config_token)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._main_draft().revision, 1)

    def test_callback_payload_without_status_rejected(self):
        """载荷不含 status 的任何合法签名（非回调语义）一律 403"""
        body = self._save_body('oo-1-r1-00000000', 'http://x/y.docx')
        resp = self._post_callback(
            body, token_override=sign_payload({'foo': 'bar'}, TEST_SECRET))
        self.assertEqual(resp.status_code, 403)

    def test_callback_body_fields_ignored_without_payload_users(self):
        """载荷缺 users 时不得回退读未签名 body（归属账号只认签名）"""
        stub = self._start_stub()
        doc_key = self._issue_config()
        url = f'{stub.base_url}/docs/{doc_key}.docx'
        body = self._save_body(doc_key, url)  # body 有完整 users，载荷没有
        resp = self._post_callback(
            body, token_override=sign_payload({'status': 6}, TEST_SECRET))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._main_draft().revision, 1)

    def test_callback_key_read_from_signed_payload(self):
        """回调 key 以签名为准：载荷带旧 key、body 伪造当前 key 也被拒"""
        stub = self._start_stub()
        old_key = self._issue_config()
        self._issue_config()  # 轮换 key（模拟重取配置）
        url = f'{stub.base_url}/docs/{old_key}.docx'
        payload = self._save_body(old_key, url)
        body = dict(payload, key=self._current_key())
        resp = self._post_callback(
            body, token_override=sign_payload(payload, TEST_SECRET))
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self._main_draft().revision, 1)

    def test_callback_url_read_from_signed_payload(self):
        """url 以签名为准：body 指向站外地址不能改变白名单内的取回目标"""
        stub = self._start_stub()
        doc_key = self._issue_config()
        url = f'{stub.base_url}/docs/{doc_key}.docx'
        payload = self._save_body(doc_key, url)
        body = dict(payload, url='http://evil.example/steal.docx')
        resp = self._post_callback(
            body, token_override=sign_payload(payload, TEST_SECRET))
        self.assertEqual(resp.json(), {'error': 0})
        self.assertEqual(self._main_draft().revision, 2)

    def test_callback_scalar_jwt_header_rejected_not_500(self):
        """header 段为 JSON 标量的伪造 token：403 而非 500（端点匿名可达）"""
        body = self._save_body('oo-1-r1-00000000', 'http://x/y.docx')
        resp = self._post_callback(body, token_override='Mg.eyJhIjoxfQ.AA')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._main_draft().revision, 1)

    # -- 状态机 --

    def test_status_1_heartbeat_ignored(self):
        doc_key = self._issue_config()
        resp = self._post_callback(self._save_body(doc_key, 'http://x/y.docx',
                                                   status=1))
        self.assertEqual(resp.json(), {'error': 0})
        self.assertEqual(self._main_draft().revision, 1)

    def test_status_6_saves_and_increments_revision(self):
        stub = self._start_stub()
        doc_key = self._issue_config()
        url = f'{stub.base_url}/docs/{doc_key}.docx'
        resp = self._post_callback(self._save_body(doc_key, url))
        self.assertEqual(resp.json(), {'error': 0})
        draft = self._main_draft()
        self.assertEqual(draft.revision, 2)
        # 回调保存的显示名=手册名（回调协议不带文件名，不得透出系统生成名）
        # 回调保存的草稿显示名 = 文件条目显示名（不再回退手册名）
        self.assertEqual(draft.original_name, self.file_entry.display_name)
        saved = storage.resolve_absolute_path(draft.file_path)
        with open(saved, 'rb') as f:
            self.assertEqual(f.read(), stub.payload)
        self.assertTrue(ManualOperationLog.objects.filter(
            manual=self.manual, action='save_draft',
            detail__contains='onlyoffice_callback').exists())

    def test_successive_forcesave_same_key_saves_again(self):
        """同一编辑实例多次 forcesave（key 不变）均可保存（内容有变化）"""
        stub = self._start_stub()
        doc_key = self._issue_config()
        url = f'{stub.base_url}/docs/{doc_key}.docx'
        self._post_callback(self._save_body(doc_key, url))
        stub.payload = _docx(b'callback-content-v2')
        self._post_callback(self._save_body(doc_key, url))
        self.assertEqual(self._main_draft().revision, 3)

    def test_duplicate_callback_content_idempotent(self):
        """重复回调（同内容）：内容哈希一致不重复保存，修订号不再递增"""
        stub = self._start_stub()
        doc_key = self._issue_config()
        url = f'{stub.base_url}/docs/{doc_key}.docx'
        self._post_callback(self._save_body(doc_key, url))
        resp = self._post_callback(self._save_body(doc_key, url, status=2))
        self.assertEqual(resp.json(), {'error': 0})
        self.assertEqual(self._main_draft().revision, 2)

    # -- 越权与状态防护 --

    def test_callback_users_empty_rejected(self):
        stub = self._start_stub()
        doc_key = self._issue_config()
        url = f'{stub.base_url}/docs/{doc_key}.docx'
        resp = self._post_callback(self._save_body(doc_key, url, users=[]))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._main_draft().revision, 1)

    def test_callback_without_session_rejected(self):
        stub = self._start_stub()
        doc_key = self._issue_config()
        delete_json(self.editor_client,
                    f'/institution/manuals/{self.manual.id}/draft/session/',
                    {'session_key': self.session_key})
        url = f'{stub.base_url}/docs/{doc_key}.docx'
        resp = self._post_callback(self._save_body(doc_key, url))
        self.assertEqual(resp.status_code, 403)

    def test_callback_role_revoked_rejected(self):
        stub = self._start_stub()
        doc_key = self._issue_config()
        self.manual.edit_roles.clear()
        url = f'{stub.base_url}/docs/{doc_key}.docx'
        resp = self._post_callback(self._save_body(doc_key, url))
        self.assertEqual(resp.status_code, 403)

    def test_callback_archived_manual_rejected(self):
        stub = self._start_stub()
        doc_key = self._issue_config()
        self.manual.status = 'archived'
        self.manual.save(update_fields=['status'])
        url = f'{stub.base_url}/docs/{doc_key}.docx'
        resp = self._post_callback(self._save_body(doc_key, url))
        self.assertEqual(resp.status_code, 409)

    def test_session_expired_callback_rejected(self):
        stub = self._start_stub()
        doc_key = self._issue_config()
        ManualEditSession.objects.filter(session_key=self.session_key).update(
            expires_at=timezone.now() - datetime.timedelta(seconds=1))
        url = f'{stub.base_url}/docs/{doc_key}.docx'
        resp = self._post_callback(self._save_body(doc_key, url))
        self.assertEqual(resp.status_code, 403)

    # -- 迟到回调防护（key 与会话比对）--

    def test_stale_editor_instance_callback_rejected(self):
        """编辑器重开后 key 轮换：旧实例的迟到回调不得覆盖新内容"""
        stub = self._start_stub()
        old_key = self._issue_config()
        new_key = self._issue_config()  # 模拟用户重开编辑器/多标签重取配置
        self.assertNotEqual(old_key, new_key)
        url = f'{stub.base_url}/docs/{old_key}.docx'
        resp = self._post_callback(self._save_body(old_key, url))
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self._main_draft().revision, 1)

    # -- 回调文件下载地址白名单 --

    def test_callback_url_outside_ds_origin_rejected(self):
        """url 不在文档服务来源内 → 拒绝（防任意 URL 取回/SSRF）"""
        self._issue_config()
        body = self._save_body(
            self._current_key(), 'http://evil.example/steal.docx')
        resp = self._post_callback(body)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._main_draft().revision, 1)

    def test_callback_url_file_scheme_rejected(self):
        """file:// 等非 http(s) scheme 一律拒绝"""
        self._issue_config()
        body = self._save_body(
            self._current_key(), 'file:///etc/passwd')
        resp = self._post_callback(body)
        self.assertEqual(resp.status_code, 400)

    def test_callback_whitelist_unconfigured_fail_closed(self):
        """DS 来源未配置时 fail-closed：任何 url 都拒绝"""
        self._issue_config()
        self._start_stub()
        self._stop_base_patcher()
        patcher = patch.object(dj_settings, 'ONLYOFFICE_DOCS_URL', '')
        patcher.start()
        self.addCleanup(patcher.stop)
        body = self._save_body(
            self._current_key(), f'{self._stub.base_url}/docs/x.docx')
        resp = self._post_callback(body)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._main_draft().revision, 1)

    def test_callback_download_oversized_rejected(self):
        """回调文件超过大小上限：拒绝落盘（缩小上限避免真实传 100MB）"""
        stub = self._start_stub(payload=_docx(b'x' * 4096))
        doc_key = self._issue_config()
        url = f'{stub.base_url}/docs/{doc_key}.docx'
        with patch.object(storage, 'MAX_FILE_SIZE', 1024):
            resp = self._post_callback(self._save_body(doc_key, url))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._main_draft().revision, 1)

    def test_callback_download_oversized_no_tmp_leak(self):
        """超限下载不残留 oo_cb_ 临时文件（delete=False 泄漏防护）"""
        def oo_tmp_files():
            return {n for n in os.listdir(tempfile.gettempdir())
                    if n.startswith('oo_cb_')}
        before = oo_tmp_files()
        stub = self._start_stub(payload=_docx(b'x' * 4096))
        doc_key = self._issue_config()
        url = f'{stub.base_url}/docs/{doc_key}.docx'
        with patch.object(storage, 'MAX_FILE_SIZE', 1024):
            resp = self._post_callback(self._save_body(doc_key, url))
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(oo_tmp_files() - before)

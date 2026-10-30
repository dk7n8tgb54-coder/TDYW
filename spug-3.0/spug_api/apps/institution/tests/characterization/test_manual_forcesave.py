# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""「保存并结束编辑」落盘确认链路的真实行为测试

覆盖：
- forcesave 端点：需该文件有效编辑会话与编制角色；响应携带请求时刻
  草稿修订号作为前端轮询基线；未配置编辑服务整体拒绝。
- DS Command Service 调用：POST {c: forcesave, key: 会话当前 doc_key}，
  body token 与 Authorization Bearer 均为合法 JWT（可被 verify_token
  校验且载荷含 c/key）；error 0 -> requested，error 4（无修改）->
  no_changes，error 1（key 不存在）与其他码 -> 业务错误不冒充成功。
- 端点回退：/command 404（DS 8.1 等旧版）自动改用
  /coauthoring/CommandService.ashx 并缓存。
- 基址推导：显式 ONLYOFFICE_COMMAND_BASE_URL 优先；ONLYOFFICE_DOCS_URL
  为相对路径时取 ONLYOFFICE_PUBLIC_BASE_URL + 该路径。
- 全链路：forcesave 受理（requested）后，DS 按官方协议回调 status=2，
  草稿修订号推进——即前端轮询确认的落盘标志；会话在确认前撤销则
  回调被拒（内容不落盘），验证"先确认后撤销"的必要性。
"""
import json
from unittest.mock import patch

from django.conf import settings as dj_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.institution import editor_services
from apps.institution.models import ManualEditSession
from apps.institution.onlyoffice_jwt import sign_payload, verify_token
from apps.institution.tests.base import (
    PERM_DRAFT, get_data, has_error, make_client, make_user, post_json,
)
from apps.institution.tests.characterization.test_manual_draft import (
    DraftWorkflowBase,
)
from apps.institution.tests.characterization.test_manual_editor import (
    TEST_SECRET, _StubDocServer, _docx,
)

COMMAND_BASE = 'http://ds-command.test'


class _FakeCommandResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data if data is not None else {'error': 0}

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


@override_settings(ONLYOFFICE_DOCS_URL='http://onlyoffice:80',
                   ONLYOFFICE_JWT_SECRET=TEST_SECRET,
                   ONLYOFFICE_PUBLIC_BASE_URL='http://tdyw',
                   ONLYOFFICE_COMMAND_BASE_URL=COMMAND_BASE)
class ForceSaveViewTests(DraftWorkflowBase):
    """forcesave 端点：会话/角色校验与 DS 命令映射"""

    def setUp(self):
        super().setUp()
        self._set_password()
        self._add_file()
        self._command_base_patcher = patch.object(
            editor_services, '_command_endpoint_cache', None)
        self._command_base_patcher.start()
        self.addCleanup(self._command_base_patcher.stop)
        resp = self._start_session()
        self.assertFalse(has_error(resp), resp.content)
        self.session_key = get_data(resp)['session_key']
        # 走真实配置端点签发 document key（写入会话 current_doc_key）
        self.doc_key = get_data(self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/draft/editor-config/'
            f'?session_key={self.session_key}'))['document_key']
        self.path = (
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'draft/forcesave/')

    def _post_forcesave(self, client=None, session_key=None):
        client = client or self.editor_client
        return post_json(client, self.path, {
            'session_key': session_key if session_key is not None
            else self.session_key})

    def _patch_ds(self, responses):
        return patch.object(
            editor_services.requests_lib, 'post', side_effect=responses)

    def test_requires_session(self):
        resp = post_json(self.editor_client, self.path, {'session_key': ''})
        self.assertTrue(has_error(resp))
        self.assertIn('会话', resp.json()['error'])
        resp = post_json(self.editor_client, self.path,
                         {'session_key': 'not-exist'})
        self.assertTrue(has_error(resp))

    def test_requires_edit_role(self):
        outsider = make_user('fs-out', tenant_id='deptA', perms=[PERM_DRAFT])
        resp = self._post_forcesave(client=make_client(outsider))
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])

    def test_happy_path_requested_with_signed_command(self):
        captured = {}

        def fake_post(url, **kwargs):
            captured['url'] = url
            captured['kwargs'] = kwargs
            return _FakeCommandResponse(data={'error': 0, 'key': self.doc_key})

        with self._patch_ds(fake_post):
            resp = self._post_forcesave()
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(data['forcesave'], 'requested')
        # 修订号基线 = 请求时刻草稿修订号（前端轮询越过它即确认落盘）
        self.assertEqual(data['revision'],
                         self._main_draft().revision)
        # 命令请求面向 DS Command Service，c/key 与会话 doc_key 一致
        self.assertEqual(captured['url'], f'{COMMAND_BASE}/command')
        body = captured['kwargs']['json']
        self.assertEqual(body['c'], 'forcesave')
        self.assertEqual(body['key'], self.doc_key)
        # body token 与 Authorization Bearer 均为可校验 JWT，载荷含 c/key
        payload = verify_token(body['token'], TEST_SECRET)
        self.assertIsNotNone(payload)
        self.assertEqual(payload['c'], 'forcesave')
        self.assertEqual(payload['key'], self.doc_key)
        auth_header = captured['kwargs']['headers']['Authorization']
        self.assertTrue(auth_header.startswith('Bearer '))
        self.assertIsNotNone(
            verify_token(auth_header[len('Bearer '):], TEST_SECRET))

    def test_no_changes_reports_immediately(self):
        with self._patch_ds(lambda *a, **k: _FakeCommandResponse(
                data={'error': 4, 'key': self.doc_key})):
            resp = self._post_forcesave()
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['forcesave'], 'no_changes')

    def test_key_not_found_is_business_error(self):
        """error 1（文档键不存在）不得冒充成功：返回业务错误保留重试"""
        with self._patch_ds(lambda *a, **k: _FakeCommandResponse(
                data={'error': 1, 'key': self.doc_key})):
            resp = self._post_forcesave()
        self.assertTrue(has_error(resp))
        self.assertIn('无法受理', resp.json()['error'])

    def test_ds_unreachable_is_business_error(self):
        import requests as requests_lib
        with self._patch_ds(
                lambda *a, **k: (_ for _ in ()).throw(
                    requests_lib.ConnectionError('boom'))):
            resp = self._post_forcesave()
        self.assertTrue(has_error(resp))
        self.assertIn('失败', resp.json()['error'])

    def test_command_endpoint_fallback_and_cache(self):
        """/command 404（旧版 DS）自动改用 ashx 端点并缓存后续请求"""
        urls = []

        def fake_post(url, **kwargs):
            urls.append(url)
            if url.endswith('/command'):
                return _FakeCommandResponse(status_code=404)
            return _FakeCommandResponse(data={'error': 0})

        with self._patch_ds(fake_post):
            resp = self._post_forcesave()
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(
            urls, [f'{COMMAND_BASE}/command',
                   f'{COMMAND_BASE}/coauthoring/CommandService.ashx'])
        with self._patch_ds(fake_post):
            resp = self._post_forcesave()
        self.assertFalse(has_error(resp), resp.content)
        # 缓存生效：第二次请求直达 ashx，不再先试 /command
        self.assertEqual(urls[-1],
                         f'{COMMAND_BASE}/coauthoring/CommandService.ashx')

    def test_unconfigured_service_rejected(self):
        with override_settings(ONLYOFFICE_DOCS_URL='',
                               ONLYOFFICE_JWT_SECRET=''):
            resp = self._post_forcesave()
        self.assertTrue(has_error(resp))
        self.assertIn('未配置', resp.json()['error'])
        # 未发起任何命令请求
        session = ManualEditSession.objects.get(session_key=self.session_key)
        self.assertTrue(session.current_doc_key)

    def test_archived_manual_rejected(self):
        self.manual.status = 'archived'
        self.manual.save(update_fields=['status'])
        resp = self._post_forcesave()
        self.assertTrue(has_error(resp))
        self.assertIn('归档', resp.json()['error'])


class CommandBaseUrlTests(TestCase):
    """Command Service 基址推导（纯函数行为）"""

    def test_explicit_override_wins(self):
        with override_settings(ONLYOFFICE_COMMAND_BASE_URL='http://ds:80/',
                               ONLYOFFICE_DOCS_URL='/onlyoffice',
                               ONLYOFFICE_PUBLIC_BASE_URL='http://tdyw'):
            self.assertEqual(editor_services.command_base_url(), 'http://ds:80')

    def test_relative_docs_url_uses_public_base(self):
        with override_settings(ONLYOFFICE_COMMAND_BASE_URL='',
                               ONLYOFFICE_DOCS_URL='/onlyoffice',
                               ONLYOFFICE_PUBLIC_BASE_URL='http://tdyw'):
            self.assertEqual(editor_services.command_base_url(),
                             'http://tdyw/onlyoffice')

    def test_absolute_docs_url_used_directly(self):
        with override_settings(ONLYOFFICE_COMMAND_BASE_URL='',
                               ONLYOFFICE_DOCS_URL='http://onlyoffice:80',
                               ONLYOFFICE_PUBLIC_BASE_URL=''):
            self.assertEqual(editor_services.command_base_url(),
                             'http://onlyoffice:80')

    def test_unresolvable_returns_empty(self):
        with override_settings(ONLYOFFICE_COMMAND_BASE_URL='',
                               ONLYOFFICE_DOCS_URL='/onlyoffice',
                               ONLYOFFICE_PUBLIC_BASE_URL=''):
            self.assertEqual(editor_services.command_base_url(), '')


@override_settings(ONLYOFFICE_DOCS_URL='http://onlyoffice:80',
                   ONLYOFFICE_JWT_SECRET=TEST_SECRET,
                   ONLYOFFICE_PUBLIC_BASE_URL='http://tdyw',
                   ONLYOFFICE_COMMAND_BASE_URL=COMMAND_BASE)
class ForceSaveCallbackChainTests(DraftWorkflowBase):
    """forcesave -> DS 回调落盘 -> 修订号推进 的确认链路"""

    def setUp(self):
        super().setUp()
        self._set_password()
        self._add_file()
        self._command_base_patcher = patch.object(
            editor_services, '_command_endpoint_cache', None)
        self._command_base_patcher.start()
        self.addCleanup(self._command_base_patcher.stop)
        resp = self._start_session()
        self.assertFalse(has_error(resp), resp.content)
        self.session_key = get_data(resp)['session_key']
        self.doc_key = get_data(self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/draft/editor-config/'
            f'?session_key={self.session_key}'))['document_key']
        self.path = (
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'draft/forcesave/')
        self.callback_path = (
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'attachments/oo-editor-callback/')

    def test_requested_then_callback_advances_revision(self):
        """受理后 DS 按协议回调 status=2：修订号推进（轮询确认的落盘标志）"""
        stub = _StubDocServer(payload=_docx(b'forcesaved-content'))
        self.addCleanup(stub.stop)
        # 与既有回调测试同口径：把 ONLYOFFICE_DOCS_URL 指向桩主机，
        # 使回调文件下载白名单包含桩来源；命令基址显式配置不受影响
        base_patcher = patch.object(
            dj_settings, 'ONLYOFFICE_DOCS_URL', stub.base_url)
        base_patcher.start()
        self.addCleanup(base_patcher.stop)
        with patch.object(editor_services.requests_lib, 'post',
                          return_value=_FakeCommandResponse(
                              data={'error': 0, 'key': self.doc_key})):
            resp = post_json(self.editor_client, self.path,
                             {'session_key': self.session_key})
        self.assertFalse(has_error(resp), resp.content)
        baseline = get_data(resp)['revision']
        self.assertEqual(self._main_draft().revision, baseline)
        # DS 受理 forcesave 后向 callbackUrl 发送 status=2 回调
        body = {
            'key': self.doc_key, 'status': 2,
            'url': f'{stub.base_url}/cache/{self.doc_key}.docx',
            'users': [f'uid-{self.editor.id}'],
        }
        cb = self.editor_client.post(
            self.callback_path, data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {sign_payload(body, TEST_SECRET)}')
        self.assertEqual(cb.json(), {'error': 0})
        self.assertEqual(self._main_draft().revision, baseline + 1)
        # 会话 doc_key 未变：同一编辑实例的后续回调仍被接受
        self.assertEqual(
            ManualEditSession.objects.get(
                session_key=self.session_key).current_doc_key,
            self.doc_key)

    def test_revoke_before_callback_rejects_save(self):
        """会话撤销先于落盘确认：迟到回调被拒、内容不落盘（先确认后撤销）"""
        stub = _StubDocServer(payload=_docx(b'lost-content'))
        self.addCleanup(stub.stop)
        # 直接撤销会话（未走确认流）
        delete = self.editor_client.delete(
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'draft/session/', data=json.dumps(
                {'session_key': self.session_key}),
            content_type='application/json')
        self.assertFalse(has_error(delete), delete.content)
        baseline = self._main_draft().revision
        body = {
            'key': self.doc_key, 'status': 2,
            'url': f'{stub.base_url}/cache/{self.doc_key}.docx',
            'users': [f'uid-{self.editor.id}'],
        }
        cb = self.editor_client.post(
            self.callback_path, data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {sign_payload(body, TEST_SECRET)}')
        self.assertEqual(cb.status_code, 403)
        self.assertEqual(self._main_draft().revision, baseline)

    def test_foreign_revision_advance_then_callback_still_lands(self):
        """他处保存先推进修订号：同 key 回调仍在会话活跃时落盘

        前端落盘确认链路的复核轮依赖该后端行为：修订号被其他保存路径
        （如同账号其他页签的 multipart 保存）推进后，同一编辑实例的
        forcesave 回调（同会话同 key）不会被误拒——内容照常落盘、修订号
        单调递增（最后写入者落盘）；前端据此以"再次 forcesave 复核到
        no_changes"区分他处推进与本次回调落盘，不冒充保存成功。
        """
        stub = _StubDocServer(payload=_docx(b'forcesaved-content'))
        self.addCleanup(stub.stop)
        base_patcher = patch.object(
            dj_settings, 'ONLYOFFICE_DOCS_URL', stub.base_url)
        base_patcher.start()
        self.addCleanup(base_patcher.stop)
        with patch.object(editor_services.requests_lib, 'post',
                          return_value=_FakeCommandResponse(
                              data={'error': 0, 'key': self.doc_key})):
            resp = post_json(self.editor_client, self.path,
                             {'session_key': self.session_key})
        self.assertFalse(has_error(resp), resp.content)
        baseline = get_data(resp)['revision']
        # 同账号其他页签的 multipart 保存先推进修订号（baseline -> +1）
        upload = SimpleUploadedFile('other-tab.docx', b'PK\x03\x04 other-tab')
        mp = self.editor_client.post(
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'draft/save/',
            {'file': upload, 'session_key': self.session_key,
             'revision': baseline})
        self.assertFalse(has_error(mp), mp.content)
        self.assertEqual(self._main_draft().revision, baseline + 1)
        # 同一编辑实例的 forcesave 回调随后到达：同 key 同会话仍被接受，
        # 修订号再 +1（绝不因他处推进而虚增或误拒）
        body = {
            'key': self.doc_key, 'status': 2,
            'url': f'{stub.base_url}/cache/{self.doc_key}.docx',
            'users': [f'uid-{self.editor.id}'],
        }
        cb = self.editor_client.post(
            self.callback_path, data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {sign_payload(body, TEST_SECRET)}')
        self.assertEqual(cb.json(), {'error': 0})
        self.assertEqual(self._main_draft().revision, baseline + 2)

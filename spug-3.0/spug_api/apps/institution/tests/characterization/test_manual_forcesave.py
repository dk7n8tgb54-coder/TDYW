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
- DS Command Service 端点：10.0 专用 /command 直连（应用层不再兼容
  8.1 等旧版 ashx 端点），非 JSON 应答按失败处理不冒充成功。
- 基址推导：显式 ONLYOFFICE_COMMAND_BASE_URL 优先；ONLYOFFICE_DOCS_URL
  为相对路径时取 ONLYOFFICE_PUBLIC_BASE_URL + 该路径。
- 全链路：forcesave 受理（requested）后，DS 按官方协议回调 status=2，
  草稿修订号推进——即前端轮询确认的落盘标志；会话撤销与 DS 收尾回调
  的时序契约由 discard 参数表达（缺省 true 丢弃收尾回调；
  discard=false 受控放行同一 current_doc_key 的收尾 status-2/6 回调，
  防线全保留）。
"""
import hashlib
import json
from unittest.mock import patch

from django.conf import settings as dj_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.institution import editor_services
from apps.institution.models import ManualEditSession
from apps.institution.onlyoffice_jwt import sign_payload, verify_token
from apps.institution.tests.base import (
    PERM_DRAFT, get_data, has_error, make_client, make_grant, make_user,
    post_json, put_json,
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

    def test_command_endpoint_direct_10(self):
        """10.0 专用：仅请求 /command，无旧版 ashx 回退"""
        urls = []

        def fake_post(url, **kwargs):
            urls.append(url)
            return _FakeCommandResponse(data={'error': 0})

        with self._patch_ds(fake_post):
            resp = self._post_forcesave()
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(urls, [f'{COMMAND_BASE}/command'])

    def test_command_non_json_response_is_error(self):
        """非 JSON 应答（如网关错误页）按失败处理，不冒充成功"""
        with self._patch_ds(lambda *a, **k: _FakeCommandResponse(
                status_code=502, data=ValueError('not json'))):
            resp = self._post_forcesave()
        self.assertTrue(has_error(resp))
        self.assertIn('响应异常', resp.json()['error'])

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

    def test_default_revoke_discards_final_callback(self):
        """缺省撤销（discard=true）丢弃收尾回调：迟到回调被拒、内容不落盘

        新不变量（2026-10-30 修订原「撤销先于落盘则回调拒绝」单义钉死）：
        会话撤销端点的 discard 参数缺省为 true——"不保存并退出"的显式
        丢弃意图不被收尾回调推翻；只有"保存并结束编辑"确认成功后的撤销
        显式携带 discard=false 才受控放行收尾回调（见
        FinalCallbackAllowanceTests）。
        """
        stub = _StubDocServer(payload=_docx(b'lost-content'))
        self.addCleanup(stub.stop)
        # 直接撤销会话（未走确认流；不携带 discard = 缺省 true）
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



@override_settings(ONLYOFFICE_DOCS_URL='http://onlyoffice:80',
                   ONLYOFFICE_JWT_SECRET=TEST_SECRET,
                   ONLYOFFICE_PUBLIC_BASE_URL='http://tdyw',
                   ONLYOFFICE_COMMAND_BASE_URL=COMMAND_BASE)
class FinalCallbackRaceTests(DraftWorkflowBase):
    """缺陷复现（defect_reproduction）：会话撤销早于 DS 收尾回调

    真实复现记录（2026-10-30，dev 主实例 ONLYOFFICE 10.0.0 Build 169）：
    前端「保存并结束编辑」确认成功后撤销会话并销毁编辑器，DS 在编辑器
    关闭时补发一次收尾 status-2 回调（实测约晚 1 秒到达），此时会话已
    撤销 -> 403 拒绝（实测日志 WARNING [InstitutionEditor] callback
    without active session，payload 含 "notmodified":true）。两种变体：

    - benign：notmodified=true（无新内容）-> 拒绝无损失；
    - 丢失：回调携带新内容（哈希 != 当前草稿）-> 拒绝即最后一次修改
      丢失，重开后 document key 已轮换，丢失不可恢复。

    本组钉住缺省撤销（discard 缺省 true）的丢弃语义作为对照基线；
    discard=false 的受控放行见 FinalCallbackAllowanceTests。
    """

    def setUp(self):
        super().setUp()
        self._set_password()
        self._add_file()
        resp = self._start_session()
        self.assertFalse(has_error(resp), resp.content)
        self.session_key = get_data(resp)['session_key']
        self.doc_key = get_data(self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/draft/editor-config/'
            f'?session_key={self.session_key}'))['document_key']
        self.session_path = (
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'draft/session/')
        self.callback_path = (
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'attachments/oo-editor-callback/')

    def _revoke(self, extra=None):
        body = {'session_key': self.session_key}
        if extra:
            body.update(extra)
        return self.editor_client.delete(
            self.session_path, data=json.dumps(body),
            content_type='application/json')

    def _send_final_callback(self, stub, status=2, extra_payload=None):
        body = {
            'key': self.doc_key, 'status': status,
            'url': f'{stub.base_url}/cache/{self.doc_key}.docx',
            'users': [f'uid-{self.editor.id}'],
        }
        if extra_payload:
            body.update(extra_payload)
        return self.editor_client.post(
            self.callback_path, data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {sign_payload(body, TEST_SECRET)}')

    def _stub(self, payload):
        """本地桩 + 白名单放行（把 ONLYOFFICE_DOCS_URL 指向桩主机，
        与既有回调测试同口径；命令基址显式配置不受影响）"""
        stub = _StubDocServer(payload=payload)
        self.addCleanup(stub.stop)
        docs_patcher = patch.object(
            dj_settings, 'ONLYOFFICE_DOCS_URL', stub.base_url)
        docs_patcher.start()
        self.addCleanup(docs_patcher.stop)
        return stub


    def test_benign_notmodified_callback_rejected_without_loss(self):
        """benign 变体：撤销后收尾回调 notmodified=true -> 403（无损失）"""
        # 桩提供与当前草稿一致的内容：即使放行也会被内容哈希幂等跳过
        stub = self._stub(_docx(b'draft-base'))
        self.assertFalse(has_error(self._revoke()), 'revoke failed')
        baseline = self._main_draft().revision
        cb = self._send_final_callback(stub, extra_payload={'notmodified': True})
        self.assertEqual(cb.status_code, 403)
        self.assertEqual(self._main_draft().revision, baseline)

    def test_new_content_callback_rejected_after_revoke_loses_last_edit(self):
        """丢失变体：撤销后收尾回调携带新内容 -> 403，最后一次修改丢失"""
        stub = self._stub(_docx(b'last-minute-edit'))
        self.assertFalse(has_error(self._revoke()), 'revoke failed')
        draft_before = self._main_draft()
        baseline = draft_before.revision
        old_hash = draft_before.file_hash
        cb = self._send_final_callback(stub)
        # 现状：回调被 403 拒绝，新内容不落盘——若该回调承载用户在
        # forcesave 复核之后、编辑器销毁之前的最后输入，即数据丢失
        self.assertEqual(cb.status_code, 403)
        draft_after = self._main_draft()
        self.assertEqual(draft_after.revision, baseline)
        self.assertEqual(draft_after.file_hash, old_hash)


@override_settings(ONLYOFFICE_DOCS_URL='http://onlyoffice:80',
                   ONLYOFFICE_JWT_SECRET=TEST_SECRET,
                   ONLYOFFICE_PUBLIC_BASE_URL='http://tdyw',
                   ONLYOFFICE_COMMAND_BASE_URL=COMMAND_BASE)
class FinalCallbackAllowanceTests(DraftWorkflowBase):
    """discard=false 撤销的收尾回调受控放行（防线全部保留）

    契约（2026-10-30）：「保存并结束编辑」确认成功后的撤销显式携带
    discard=false，本编辑实例（同一 current_doc_key）的收尾
    status-2/6 回调允许落盘——修复"确认成功到编辑器销毁之间的最后
    一次输入因收尾回调被拒而丢失"。防线：回调 JWT 有效；payload key
    == 该已撤销会话 current_doc_key；该会话仍是该文件最新一条会话
    记录（撤销后重开新会话则旧回调照旧拒绝）；回调时刻仍有
    can_edit_file（编制授权+负责人）且手册未归档；落盘仍走行锁修订号
    复核 + 内容哈希幂等跳过。
    """

    def setUp(self):
        super().setUp()
        self._set_password()
        self._add_file()
        resp = self._start_session()
        self.assertFalse(has_error(resp), resp.content)
        self.session_key = get_data(resp)['session_key']
        self.doc_key = get_data(self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/draft/editor-config/'
            f'?session_key={self.session_key}'))['document_key']
        self.session_path = (
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'draft/session/')
        self.callback_path = (
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'attachments/oo-editor-callback/')

    def _revoke(self, discard=None):
        body = {'session_key': self.session_key}
        if discard is not None:
            body['discard'] = discard
        return self.editor_client.delete(
            self.session_path, data=json.dumps(body),
            content_type='application/json')

    def _send_final_callback(self, stub, status=2, doc_key=None,
                             users=None, extra_payload=None):
        body = {
            'key': doc_key if doc_key is not None else self.doc_key,
            'status': status,
            'url': f'{stub.base_url}/cache/{self.doc_key}.docx',
            'users': users if users is not None else [f'uid-{self.editor.id}'],
        }
        if extra_payload:
            body.update(extra_payload)
        return self.editor_client.post(
            self.callback_path, data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {sign_payload(body, TEST_SECRET)}')

    def _stub(self, payload):
        """本地桩 + 白名单放行（把 ONLYOFFICE_DOCS_URL 指向桩主机，
        与既有回调测试同口径；命令基址显式配置不受影响）"""
        stub = _StubDocServer(payload=payload)
        self.addCleanup(stub.stop)
        docs_patcher = patch.object(
            dj_settings, 'ONLYOFFICE_DOCS_URL', stub.base_url)
        docs_patcher.start()
        self.addCleanup(docs_patcher.stop)
        return stub


    def test_new_content_final_callback_lands_after_discard_false(self):
        """discard=false 撤销后收尾回调携带新内容：落盘推进修订号"""
        stub = self._stub(_docx(b'final-callback-content'))
        self.assertFalse(has_error(self._revoke(discard=False)),
                         'revoke failed')
        baseline = self._main_draft().revision
        cb = self._send_final_callback(stub)
        self.assertEqual(cb.json(), {'error': 0}, cb.content)
        draft = self._main_draft()
        self.assertEqual(draft.revision, baseline + 1)
        # 落盘内容即回调携带内容（最后一次修改不再丢失）
        expected = hashlib.sha256(_docx(b'final-callback-content')).hexdigest()
        self.assertEqual(draft.file_hash, expected)

    def test_same_content_final_callback_idempotent_after_discard_false(self):
        """discard=false 撤销后同内容收尾回调：内容哈希幂等跳过（不虚增）"""
        stub = self._stub(_docx(b'already-lands-content'))
        # 会话仍活跃时的 forcesave 回调先落盘（修订号 1 -> 2）
        cb = self._send_final_callback(stub)
        self.assertEqual(cb.json(), {'error': 0}, cb.content)
        self.assertEqual(self._main_draft().revision, 2)
        # 撤销（discard=false）后 DS 补发同内容收尾回调：幂等跳过
        self.assertFalse(has_error(self._revoke(discard=False)),
                         'revoke failed')
        cb = self._send_final_callback(stub)
        self.assertEqual(cb.json(), {'error': 0}, cb.content)
        self.assertEqual(self._main_draft().revision, 2)

    def test_notmodified_true_with_different_bytes_logged_no_repeat_bump(self):
        """缺陷 B 观测增强（零行为变化）：notmodified=true 但字节哈希不等

        DS 自我声明无新修改却交付与已落盘草稿不同的字节（DS 组装不确定
        性，dev 实测该形态被当新内容虚增修订号）——记 warning 供根因
        定位（含 key/revision/双哈希前 12 位/notmodified 值）；落盘判定
        仍以内容哈希为唯一权威，行为与无观测时完全一致（差异内容照常
        落盘推进修订号）；同字节重放仍幂等跳过，不重复虚增。
        """
        content = _docx(b'notmodified-anomaly-content')
        stub = self._stub(content)
        self.assertFalse(has_error(self._revoke(discard=False)),
                         'revoke failed')
        before = self._main_draft()
        baseline = before.revision
        landed_prefix = (before.file_hash or '')[:12]
        incoming_prefix = hashlib.sha256(content).hexdigest()[:12]
        with self.assertLogs('apps.institution.editor_services',
                             level='WARNING') as captured:
            cb = self._send_final_callback(stub,
                                           extra_payload={'notmodified': True})
        self.assertEqual(cb.json(), {'error': 0}, cb.content)
        # 行为与无观测时一致：字节不同仍按新内容落盘推进修订号
        draft = self._main_draft()
        self.assertEqual(draft.revision, baseline + 1)
        self.assertEqual(draft.file_hash, hashlib.sha256(content).hexdigest())
        # warning 记录了全部关联字段（key/revision/双哈希前 12 位/notmodified）
        matching = [line for line in captured.output
                    if 'notmodified=true' in line]
        self.assertEqual(len(matching), 1, captured.output)
        self.assertIn(f'key={self.doc_key}', matching[0])
        self.assertIn(f'revision={baseline}', matching[0])
        self.assertIn(f'landed_hash={landed_prefix}', matching[0])
        self.assertIn(f'incoming_hash={incoming_prefix}', matching[0])
        self.assertIn('notmodified=True', matching[0])
        # 同字节重放（现与已落盘内容一致）：幂等跳过，不重复虚增修订号
        cb = self._send_final_callback(stub,
                                       extra_payload={'notmodified': True})
        self.assertEqual(cb.json(), {'error': 0}, cb.content)
        self.assertEqual(self._main_draft().revision, baseline + 1)

    def test_status6_final_callback_lands_after_discard_false(self):
        """discard=false 同样放行收尾 status-6 回调（关闭且有修改）"""
        stub = self._stub(_docx(b'status6-final-content'))
        self.assertFalse(has_error(self._revoke(discard=False)),
                         'revoke failed')
        baseline = self._main_draft().revision
        cb = self._send_final_callback(stub, status=6)
        self.assertEqual(cb.json(), {'error': 0}, cb.content)
        self.assertEqual(self._main_draft().revision, baseline + 1)

    def test_explicit_discard_true_still_rejects_final_callback(self):
        """显式 discard=true 与缺省同口径：收尾回调拒绝、内容不落盘"""
        stub = self._stub(_docx(b'must-be-discarded'))
        self.assertFalse(has_error(self._revoke(discard=True)),
                         'revoke failed')
        baseline = self._main_draft().revision
        cb = self._send_final_callback(stub)
        self.assertEqual(cb.status_code, 403)
        self.assertEqual(self._main_draft().revision, baseline)

    def test_final_callback_rejected_after_same_user_reopens_session(self):
        """撤销后本人重开新会话：旧实例收尾回调照旧拒绝（防陈旧实例）"""
        stub = self._stub(_docx(b'stale-instance-content'))
        self.assertFalse(has_error(self._revoke(discard=False)),
                         'revoke failed')
        # 本人重开：新会话行 + 重新签发新 document key
        resp = self._start_session()
        self.assertFalse(has_error(resp), resp.content)
        new_key = get_data(self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/draft/editor-config/'
            f'?session_key={get_data(resp)["session_key"]}'))['document_key']
        self.assertNotEqual(new_key, self.doc_key)
        baseline = self._main_draft().revision
        cb = self._send_final_callback(stub)
        self.assertEqual(cb.status_code, 409)
        self.assertEqual(self._main_draft().revision, baseline)

    def test_final_callback_rejected_after_other_user_reopens_session(self):
        """撤销后他人成为负责人并开启新会话：旧实例收尾回调照旧拒绝（防陈旧实例）"""
        stub = self._stub(_docx(b'stale-vs-other-content'))
        self.assertFalse(has_error(self._revoke(discard=False)),
                         'revoke failed')
        other = make_user('other-ed', tenant_id='deptC', perms=[PERM_DRAFT])
        make_grant(self.manual, other, can_edit=True)
        # 负责人独占：他人接手须经所有者改派（负责人变更同时撤销会话）
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'assignment/', {'owner_id': other.id, 'note': '接手'})
        self.assertFalse(has_error(resp), resp.content)
        resp = self._start_session(client=make_client(other))
        self.assertFalse(has_error(resp), resp.content)
        baseline = self._main_draft().revision
        cb = self._send_final_callback(stub)
        self.assertEqual(cb.status_code, 403)
        self.assertEqual(self._main_draft().revision, baseline)

    def test_final_callback_with_rotated_key_rejected_after_discard_false(self):
        """discard=false 只放行会话最终签发 key：轮换后的旧 key 照旧拒绝"""
        stub = self._stub(_docx(b'old-tab-content'))
        # 同会话重新取配置 -> key 轮换（多标签场景，旧标签持旧 key）
        rotated_key = get_data(self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/draft/editor-config/'
            f'?session_key={self.session_key}'))['document_key']
        self.assertNotEqual(rotated_key, self.doc_key)
        self.assertFalse(has_error(self._revoke(discard=False)),
                         'revoke failed')
        baseline = self._main_draft().revision
        cb = self._send_final_callback(stub, doc_key=self.doc_key)
        self.assertEqual(cb.status_code, 403)
        self.assertEqual(self._main_draft().revision, baseline)
        # 轮换后的最终 key 收尾回调仍受控放行（同一编辑实例语义以最终
        # 签发 key 为准）
        cb = self._send_final_callback(stub, doc_key=rotated_key)
        self.assertEqual(cb.json(), {'error': 0}, cb.content)
        self.assertEqual(self._main_draft().revision, baseline + 1)

    def test_final_callback_rejected_after_password_reset_revocation(self):
        """密码重置批量撤销：收尾回调必须被丢弃（不置放行标记）"""
        stub = self._stub(_docx(b'after-reset-content'))
        # 重置密码使全部有效会话失效（revoke_manual_sessions 批量路径）
        resp = put_json(self.manager_client,
                        f'/institution/manuals/{self.manual.id}/password/',
                        {'password': 'edit-pass-2'})
        self.assertFalse(has_error(resp), resp.content)
        baseline = self._main_draft().revision
        cb = self._send_final_callback(stub)
        self.assertEqual(cb.status_code, 403)
        self.assertEqual(self._main_draft().revision, baseline)

    def test_final_callback_rejected_when_edit_grant_lost(self):
        """回调时刻编制授权已丧失：discard=false 也不得放行"""
        stub = self._stub(_docx(b'role-lost-content'))
        self.assertFalse(has_error(self._revoke(discard=False)),
                         'revoke failed')
        from apps.institution.models import ManualAuthorization
        ManualAuthorization.objects.filter(
            manual=self.manual, account=self.editor).update(can_edit=False)
        baseline = self._main_draft().revision
        cb = self._send_final_callback(stub)
        self.assertEqual(cb.status_code, 403)
        self.assertEqual(self._main_draft().revision, baseline)

    def test_final_callback_rejected_on_archived_manual(self):
        """回调时刻手册已归档：discard=false 也不得放行"""
        stub = self._stub(_docx(b'archived-content'))
        self.assertFalse(has_error(self._revoke(discard=False)),
                         'revoke failed')
        self.manual.status = 'archived'
        self.manual.save(update_fields=['status'])
        baseline = self._main_draft().revision
        cb = self._send_final_callback(stub)
        self.assertEqual(cb.status_code, 409)
        self.assertEqual(self._main_draft().revision, baseline)

    def test_final_callback_rejected_for_foreign_users_claim(self):
        """users 声明与会话账号不符：discard=false 也不得放行"""
        stub = self._stub(_docx(b'foreign-claim-content'))
        self.assertFalse(has_error(self._revoke(discard=False)),
                         'revoke failed')
        stranger = make_user('stranger', tenant_id='deptD', perms=[PERM_DRAFT])
        baseline = self._main_draft().revision
        cb = self._send_final_callback(stub, users=[f'uid-{stranger.id}'])
        self.assertEqual(cb.status_code, 403)
        self.assertEqual(self._main_draft().revision, baseline)

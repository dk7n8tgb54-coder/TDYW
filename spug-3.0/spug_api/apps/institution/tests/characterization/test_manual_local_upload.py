# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""本机编辑（下载草稿 → Word/WPS 编辑 → 上传保存）与 ONLYOFFICE 迟到回调的真实行为测试

覆盖（本机编辑降级能力恢复，2026-10-31）：
- 基线修订号保护：上传必须提交下载草稿时的基线修订号；服务端草稿已被
  推进（基线过期）时按修订号冲突拒绝，新草稿内容不被覆盖；拒绝后会话
  仍有效可继续保存（前端不清会话、可重试的服务端语义基础）。
- forcesave 确认 → 记录基线 → 本机上传完整链路：回调落盘推进修订号
  （forcesave 确认链的等价物）后，以推进后的修订号为基线上传成功。
- 旧编辑器实例的迟到回调不得覆盖本机上传结果：切到本机编辑以重取编辑
  配置轮换 document key（服务端认可的失效方式，会话保留），旧 key 的
  收尾/forcesave 回调因 key 与会话 current_doc_key 不符被 409 拒绝，
  草稿内容保持为本机上传的文件——绝不依赖隐藏 iframe 或前端模式状态。

全部断言走 test client 真实请求链路；回调文件经本地 HTTP 桩真实下载
（requests），物理文件系统 patch 到临时目录。
"""
import json
from unittest.mock import patch

from django.conf import settings as dj_settings
from django.test import override_settings

from apps.institution import storage
from apps.institution.models import ManualDraft, ManualEditSession
from apps.institution.onlyoffice_jwt import sign_payload
from apps.institution.tests.base import get_data, has_error, post_json
from apps.institution.tests.characterization.test_manual_draft import (
    DraftWorkflowBase,
)
from apps.institution.tests.characterization.test_manual_editor import (
    TEST_SECRET, _StubDocServer, _docx,
)


@override_settings(ONLYOFFICE_DOCS_URL='http://onlyoffice:80',
                   ONLYOFFICE_JWT_SECRET=TEST_SECRET,
                   ONLYOFFICE_PUBLIC_BASE_URL='http://tdyw')
class LocalUploadContractTests(DraftWorkflowBase):
    """本机上传（multipart draft/save）与旧编辑实例迟到回调的攻防"""

    def setUp(self):
        super().setUp()
        self._set_password()
        self._add_file()
        # 文件级会话（与前端一致走 files/<fid>/draft/session/）
        resp = post_json(
            self.editor_client,
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'draft/session/', {'password': 'edit-pass-1'})
        self.assertFalse(has_error(resp), resp.content)
        self.session_key = get_data(resp)['session_key']
        self.file_entry = self.manual.files.get(pk=self.file_id)
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

    def _stop_base_patcher(self):
        if self._base_patcher:
            self._base_patcher.stop()
            self._base_patcher = None

    def _issue_file_config(self):
        """走文件级配置端点签发 document key（写会话 current_doc_key）"""
        resp = self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'draft/editor-config/?session_key={self.session_key}')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)['document_key']

    def _current_key(self):
        return ManualEditSession.objects.get(
            session_key=self.session_key).current_doc_key

    def _upload_local(self, revision, name='local-edited.docx',
                      content=b'PK\x03\x04 local-upload'):
        """本机编辑上传（multipart draft/save，revision=下载时基线）"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        upload = SimpleUploadedFile(name, content)
        return self.editor_client.post(
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'draft/save/',
            {'file': upload, 'session_key': self.session_key,
             'revision': revision})

    def _start_stub(self, payload):
        self._stub = _StubDocServer(payload=payload)
        self._stop_base_patcher()
        self._base_patcher = patch.object(
            dj_settings, 'ONLYOFFICE_DOCS_URL', self._stub.base_url)
        self._base_patcher.start()
        return self._stub

    def _post_callback(self, doc_key, url, status=2):
        body = {'key': doc_key, 'status': status, 'url': url,
                'users': [f'uid-{self.editor.id}']}
        token = sign_payload(body, TEST_SECRET)
        return self.editor_client.post(
            self.callback_path, data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}')

    def _assert_draft_content(self, expected):
        draft = ManualDraft.objects.get(file=self.file_entry)
        with open(storage.resolve_absolute_path(draft.file_path), 'rb') as f:
            self.assertEqual(f.read(), expected)
        return draft

    def test_local_upload_with_baseline_succeeds_and_advances_revision(self):
        """基线修订号一致：本机上传成功、修订号推进、会话保留可继续保存"""
        self._issue_file_config()  # 在线编辑配置签发（key 与本机上传并存）
        resp = self._upload_local(revision=1, content=_docx(b'local-v1'))
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(data['revision'], 2)
        self._assert_draft_content(_docx(b'local-v1'))
        # 会话未被上传消耗：仍有效，可携带新基线继续本机编辑-上传
        resp = self._upload_local(revision=2, content=_docx(b'local-v2'))
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revision'], 3)

    def test_stale_baseline_upload_rejected_and_content_preserved(self):
        """基线过期（草稿已被推进）：上传拒绝、内容不被覆盖、会话仍有效"""
        self._issue_file_config()
        resp = self._upload_local(revision=1, content=_docx(b'local-v1'))
        self.assertFalse(has_error(resp), resp.content)
        # 以过期基线（r1，服务端已是 r2）再次上传：修订号冲突拒绝
        resp = self._upload_local(revision=1, content=_docx(b'stale-overwrite'))
        self.assertTrue(has_error(resp))
        self.assertIn('草稿已被其他会话更新', resp.json()['error'])
        # 新草稿内容不被覆盖
        draft = self._assert_draft_content(_docx(b'local-v1'))
        self.assertEqual(draft.revision, 2)
        # 会话仍有效：重新下载取得新基线（r2）后可成功上传
        resp = self._upload_local(revision=2, content=_docx(b'local-v2'))
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revision'], 3)

    def test_forcesave_confirm_then_local_upload_with_advanced_baseline(self):
        """在线编辑期间下载 → forcesave 确认落盘（回调推进修订号）→ 以
        推进后的基线上传成功"""
        doc_key = self._issue_file_config()
        stub = self._start_stub(_docx(b'confirmed-by-forcesave'))
        resp = self._post_callback(doc_key, f'{stub.base_url}/docs/{doc_key}.docx')
        self.assertEqual(resp.json(), {'error': 0})
        self.assertEqual(
            ManualDraft.objects.get(file=self.file_entry).revision, 2)
        # 基线=确认落盘后的修订号 r2：本机上传成功
        resp = self._upload_local(revision=2, content=_docx(b'local-v2'))
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revision'], 3)
        self._assert_draft_content(_docx(b'local-v2'))

    def test_old_editor_key_callback_cannot_overwrite_local_upload(self):
        """切换本机编辑（轮换 document key）后，旧编辑实例的迟到回调
        不得覆盖本机上传的草稿"""
        old_key = self._issue_file_config()
        # 切到本机编辑的服务端失效方式：重取编辑配置即轮换 key（会话保留）
        new_key = self._issue_file_config()
        self.assertNotEqual(old_key, new_key)
        self.assertEqual(self._current_key(), new_key)
        # 本机上传成功（r1 → r2，内容 A）
        content_a = _docx(b'local-upload-content')
        resp = self._upload_local(revision=1, content=content_a)
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revision'], 2)
        # 旧编辑实例的迟到收尾回调（status 2，内容 B ≠ A）：key 不符 409
        stub = self._start_stub(_docx(b'stale-editor-content'))
        resp = self._post_callback(
            old_key, f'{stub.base_url}/docs/{old_key}.docx')
        self.assertEqual(resp.status_code, 409)
        # 草稿内容保持为本机上传结果，修订号不推进
        draft = self._assert_draft_content(content_a)
        self.assertEqual(draft.revision, 2)
        # 新 key（若重新进入在线编辑）的回调不受影响：正常落盘
        resp = self._post_callback(
            new_key, f'{stub.base_url}/docs/{new_key}.docx')
        self.assertEqual(resp.json(), {'error': 0})
        draft = ManualDraft.objects.get(file=self.file_entry)
        self.assertEqual(draft.revision, 3)

    def test_local_upload_session_survives_callback_then_upload(self):
        """回调落盘与本机上传交错时单写会话持续有效（修订号行锁串行化）"""
        doc_key = self._issue_file_config()
        stub = self._start_stub(_docx(b'callback-content'))
        resp = self._post_callback(doc_key, f'{stub.base_url}/docs/{doc_key}.docx')
        self.assertEqual(resp.json(), {'error': 0})
        resp = self._upload_local(revision=2, content=_docx(b'local-v2'))
        self.assertFalse(has_error(resp), resp.content)
        # 同一编辑实例的后续 forcesave 回调（同 key）仍可落盘（修订号行锁
        # 串行化，不因本机上传过而失效）
        stub.payload = _docx(b'callback-content-v2')
        resp = self._post_callback(doc_key, f'{stub.base_url}/docs/{doc_key}.docx')
        self.assertEqual(resp.json(), {'error': 0})
        self.assertEqual(
            ManualDraft.objects.get(file=self.file_entry).revision, 4)

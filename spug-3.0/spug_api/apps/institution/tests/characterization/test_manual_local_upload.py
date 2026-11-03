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
- 整份草稿替换（2026-11-01 详情页信息层级调整配套，后端无新增接口）：
  以服务端当前草稿修订号直接上传即整份替换草稿（**不要求先调用
  draft/download**，下载只是用户取得基线修订号的动作）；过期修订号按
  '草稿已被其他会话更新'拒绝、内容不被覆盖且不使会话失效；替换后再次
  发布只追加新版本，既有版本快照的字节/哈希与预览/下载一律不变。

全部断言走 test client 真实请求链路；回调文件经本地 HTTP 桩真实下载
（requests），物理文件系统 patch 到临时目录。
"""
import hashlib
import json
import os
from unittest.mock import patch

from django.conf import settings as dj_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.institution import storage
from apps.institution.models import (ManualDraft, ManualEditSession,
                                     ManualVersion, ManualVersionFile)
from apps.institution.onlyoffice_jwt import sign_payload
from apps.institution.tests.base import get_data, has_error, post_json
from apps.institution.tests.characterization.test_manual_draft import (
    DraftWorkflowBase,
)
from apps.institution.tests.characterization.test_manual_editor import (
    TEST_SECRET, _StubDocServer, _docx,
)
from apps.institution.tests.characterization.test_preview_cache_key import (
    parse_preview,
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


@override_settings(ONLYOFFICE_DOCS_URL='http://onlyoffice:80',
                   ONLYOFFICE_JWT_SECRET=TEST_SECRET,
                   ONLYOFFICE_PUBLIC_BASE_URL='http://tdyw',
                   KKFILEVIEW_API_URL='/kkfileview',
                   KKFILEVIEW_SERVER_URL='http://tdyw-test')
class WholeDraftReplacementTests(DraftWorkflowBase):
    """整份草稿替换（本机上传语义）：无下载前置 / 修订号冲突 / 发布不可变

    接口未新增：本机编辑上传复用 multipart `draft/save/` 与既有 会话+修订号
    保护——只要提交服务端当前草稿修订号，整份草稿即被替换，**不需要先调用
    `draft/download/`**（"下载"只承担让用户拿到基线的产品职责，服务端不校验
    下载前置）。已发布版本快照绝不因草稿替换而改写：替换后再次发布只追加
    新版本号，旧版本快照的物理字节、入库存哈希与预览/下载入口保持可用。
    """

    def setUp(self):
        super().setUp()
        self._set_password()
        self._add_file()
        self.file_entry = self.manual.files.get(pk=self.file_id)
        # 版本快照基线：首次发布（发布前置=无活跃编辑会话）
        self.v1 = self._publish('第一版')
        self.snapshot = self.v1.files.get(manual_file_id=self.file_id)
        self.snapshot_bytes = self._read_file(self.snapshot.file_path)
        self.snapshot_hash = self._sha256(self.snapshot_bytes)
        # 起草基线：服务端当前草稿修订号（files/create 从 1 起，发布不改修订号）
        resp = post_json(
            self.editor_client,
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'draft/session/', {'password': 'edit-pass-1'})
        self.assertFalse(has_error(resp), resp.content)
        self.session_key = get_data(resp)['session_key']
        self.baseline = ManualDraft.objects.get(file=self.file_entry).revision

    # ---- 夹具助手 ---------------------------------------------------------

    def _ensure_handoff(self):
        """发布前由文件负责人经真实接口提交编制（预期成功发布夹具）

        本套件发布人=manager（手册所有者），文件负责人=editor，故新增/
        内容变化后的发布需 editor 的有效提交（调用方须先退出编辑会话）。
        """
        if self.file_entry.owner_id in (None, self.manager.id):
            return
        post_json(
            self.editor_client,
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'submit/', {})

    def _publish(self, note):
        self._ensure_handoff()
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/publish/',
            {'change_note': note})
        self.assertFalse(has_error(resp), resp.content)
        self.manual.refresh_from_db()
        return ManualVersion.objects.get(pk=get_data(resp)['id'])

    def _upload_local(self, revision, content, name='local-edited.docx'):
        """本机编辑上传（multipart draft/save，revision=服务端当前基线）"""
        return self.editor_client.post(
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'draft/save/',
            {'file': SimpleUploadedFile(name, content),
             'session_key': self.session_key, 'revision': revision})

    def _exit_session(self, discard=True):
        resp = self.editor_client.delete(
            f'/institution/manuals/{self.manual.id}/files/{self.file_id}/'
            f'draft/session/',
            data=json.dumps({'session_key': self.session_key,
                             'discard': discard}),
            content_type='application/json')
        self.assertFalse(has_error(resp), resp.content)

    def _draft_and_bytes(self):
        draft = ManualDraft.objects.get(file=self.file_entry)
        return draft, self._read_file(draft.file_path)

    def _draft_dir_hashes(self):
        """该制度 drafts/ 目录现存文件的哈希集合（残留/误写断言用）"""
        rel_dir = os.path.dirname(
            ManualDraft.objects.get(file=self.file_entry).file_path)
        abs_dir = storage.resolve_absolute_path(rel_dir)
        return {self._sha256(self._read_file(os.path.join(rel_dir, name)))
                for name in os.listdir(abs_dir)}

    @staticmethod
    def _read_file(rel_path):
        with open(storage.resolve_absolute_path(rel_path), 'rb') as f:
            return f.read()

    @staticmethod
    def _sha256(content):
        return hashlib.sha256(content).hexdigest()

    # ---- 行为用例 ---------------------------------------------------------

    def test_upload_current_revision_without_download_replaces_only_draft(self):
        """无下载前置：以服务端当前修订号直接上传 -> 仅草稿变更"""
        content = _docx(b'local-replace-v1')
        resp = self._upload_local(self.baseline, content)
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revision'], self.baseline + 1)
        draft, draft_bytes = self._draft_and_bytes()
        self.assertEqual(draft_bytes, content)
        self.assertEqual(draft.revision, self.baseline + 1)
        self.assertEqual(draft.file_hash, self._sha256(content))
        # 版本维度零变更：数量 / 当前生效版 / 快照行 / 物理文件字节与哈希
        self.assertEqual(
            ManualVersion.objects.filter(manual=self.manual).count(), 1)
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.current_version_id, self.v1.id)
        snapshot = ManualVersionFile.objects.get(pk=self.snapshot.pk)
        self.assertEqual(self._read_file(snapshot.file_path),
                         self.snapshot_bytes)
        self.assertEqual(snapshot.file_hash, self.snapshot_hash)
        self.assertEqual(snapshot.display_name, '正文.docx')
        # 草稿内容变更属真实内容工作：修订轮重新开启（发布时刚关闭）
        self.file_entry.refresh_from_db()
        self.assertTrue(self.file_entry.revision_open)

    def test_stale_revision_rejected_without_side_effects_and_session_survives(
            self):
        """过期修订号：拒绝且草稿/版本不变、会话仍有效（冲突不使会话失效）"""
        content = _docx(b'local-replace-v1')
        resp = self._upload_local(self.baseline, content)
        self.assertFalse(has_error(resp), resp.content)
        draft, draft_bytes = self._draft_and_bytes()
        self.assertEqual(draft.revision, self.baseline + 1)
        self.assertEqual(draft_bytes, content)
        stale = _docx(b'stale-overwrite')
        resp = self._upload_local(self.baseline, stale)
        self.assertTrue(has_error(resp))
        self.assertIn('草稿已被其他会话更新', resp.json()['error'])
        # 草稿内容与修订号不变、版本快照不变、过期上传无残留文件
        draft, draft_bytes = self._draft_and_bytes()
        self.assertEqual(draft_bytes, content)
        self.assertEqual(draft.revision, self.baseline + 1)
        self.assertEqual(self._read_file(self.snapshot.file_path),
                         self.snapshot_bytes)
        self.assertEqual(
            ManualVersion.objects.filter(manual=self.manual).count(), 1)
        self.assertNotIn(self._sha256(stale), self._draft_dir_hashes())
        # 会话仍有效：会话行未撤销，凭最新基线可继续保存
        session = ManualEditSession.objects.get(session_key=self.session_key)
        self.assertIsNone(session.revoked_at)
        resp = self._upload_local(draft.revision, _docx(b'local-replace-v2'))
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revision'], self.baseline + 2)

    def test_publish_after_replacement_appends_version_and_history_immutable(
            self):
        """替换后再发布：追加新版本，历史版本快照不可变且仍可预览/下载"""
        replacement = _docx(b'local-replace-v1')
        resp = self._upload_local(self.baseline, replacement)
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revision'], self.baseline + 1)
        self._exit_session()  # 发布前置：无活跃编辑会话
        v2 = self._publish('第二版')
        self.assertEqual(v2.version_no, self.v1.version_no + 1)
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.current_version_id, v2.id)
        # 新版本快照 = 替换后的草稿内容
        new_snapshot = v2.files.get(manual_file_id=self.file_id)
        self.assertEqual(self._read_file(new_snapshot.file_path), replacement)
        self.assertEqual(new_snapshot.file_hash, self._sha256(replacement))
        # 历史版本（v1）快照行与物理文件字节/哈希不变
        old_snapshot = ManualVersionFile.objects.get(pk=self.snapshot.pk)
        self.assertEqual(old_snapshot.file_hash, self.snapshot_hash)
        self.assertEqual(self._read_file(old_snapshot.file_path),
                         self.snapshot_bytes)
        # 旧版本仍可下载：响应体字节与发布时的快照字节一致
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/versions/{self.v1.id}/'
            f'files/{old_snapshot.id}/download/')
        self.assertEqual(resp.status_code, 200)
        body = (b''.join(resp.streaming_content) if resp.streaming
                else resp.content)
        self.assertEqual(body, self.snapshot_bytes)
        # 旧版本仍可预览：kkFileView 地址的缓存键仍是该快照的存储名
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/versions/{self.v1.id}/'
            f'files/{old_snapshot.id}/preview-url/')
        self.assertFalse(has_error(resp), resp.content)
        preview = get_data(resp)
        self.assertEqual(preview['file_name'], '正文.docx')
        self.assertEqual(preview['preview_type'], 'kkfileview')
        _, query = parse_preview(preview['preview_url'])
        self.assertEqual(query['fullfilename'][0],
                         storage.stored_filename(old_snapshot.file_path))
        # 版本清单：v1 不再是生效版、v2 生效（历史版本不被改写或下线）
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/versions/')
        self.assertFalse(has_error(resp), resp.content)
        by_no = {row['version_no']: row for row in get_data(resp)['items']}
        self.assertFalse(by_no[self.v1.version_no]['is_current'])
        self.assertTrue(by_no[v2.version_no]['is_current'])

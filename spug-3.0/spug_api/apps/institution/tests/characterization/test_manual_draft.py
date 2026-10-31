# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""编辑密码、单写会话、草稿保存与 .doc 转换的真实行为测试

关键验收语义：
- 只存密码哈希；失败次数限制；重置密码使旧会话失效。
- 同一时间每本手册只有一个可写会话（不同账号拒绝、同账号续用）。
- 草稿保存重新校验角色、会话与修订序号；迟到/旧修订不得覆盖。
- .doc 原稿保留，转换失败给明确反馈且不影响预览下载。
"""
import os
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from apps.institution import storage
from apps.institution.models import (Manual, ManualAuthorization, ManualDraft,
                                     ManualEditSession, ManualOriginal)
from apps.institution.tests.base import (
    ALL_PERMS, PERM_CONFIG, PERM_DOWNLOAD, PERM_DRAFT, PERM_VIEW,
    delete_json, get_data, has_error, make_client, make_grant, make_user,
    post_json, put_json, setup_test_env,
)

RTF_AS_DOC = (b'{\\rtf1\\ansi\\deff0 {\\fonttbl {\\f0 Times;}}'
              b'\\f0 \\fs24 Chapter One: Introduction\\par}')


class DraftWorkflowBase(TestCase):
    """公共流程：管理者（=手册所有者）建手册 -> 新增制度文件并指派编制者

    授权夹具（2026-10-31）：manager 为手册所有者；editor 持 can_edit
    授权且为文件负责人（负责人独占编辑）。
    """

    def setUp(self):
        setup_test_env()
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(storage, 'get_institution_storage_base',
                               return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.manager = make_user('mgr', tenant_id='deptA', perms=ALL_PERMS)
        self.manager_client = make_client(self.manager)
        self.manual = Manual.objects.create(
            name='科室操作手册', code='CZ-001',
            org_type=Manual.OWNER_SECTION, org_name='甲科室',
            owner=self.manager, tenant_id='deptA')
        self.editor = make_user('editor', tenant_id='deptB',
                                perms=[PERM_DRAFT, PERM_DOWNLOAD, PERM_VIEW])
        make_grant(self.manual, self.editor, can_view=True, can_edit=True)
        self.editor_client = make_client(self.editor)
        self.file_id = None

    def _add_file(self, name='原稿.docx', content=b'PK\x03\x04 draft-base',
                  owner=None):
        """新增制度文件：条目+原稿+草稿一次创建（草稿修订号从 1 起）

        默认指派 editor 为文件负责人（会话/保存等写路径要求负责人独占）。
        """
        upload = SimpleUploadedFile(name, content)
        payload = {'file': upload,
                   'owner_id': str((owner or self.editor).id)}
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/create/', payload)
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.file_id = data['id']
        return data

    def _main_file_id(self):
        file_entry = self.manual.files.filter(
            is_removed=False).order_by('sort_order', 'id').first()
        self.assertIsNotNone(file_entry)
        return file_entry.id

    def _main_draft(self):
        """主文件草稿（测试夹具通常只建一份文件；多文件用例请按 file_id 取）"""
        return ManualDraft.objects.get(file_id=self._main_file_id())

    def _upload_original(self, name='原稿.docx', content=b'PK\x03\x04 draft-base'):
        """向主文件上传候选原稿（不建草稿）；要求文件已存在"""
        upload = SimpleUploadedFile(name, content)
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self._main_file_id()}/originals/upload/',
            {'file': upload})
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)['id']

    def _create_draft(self, original_id=None):
        body = {'original_id': original_id} if original_id else {}
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.file_id or self._main_file_id()}/draft/create/', body)
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _set_password(self, password='edit-pass-1'):
        resp = put_json(self.manager_client,
                        f'/institution/manuals/{self.manual.id}/password/',
                        {'password': password})
        self.assertFalse(has_error(resp), resp.content)

    def _start_session(self, client=None, password='edit-pass-1'):
        client = client or self.editor_client
        resp = post_json(client,
                         f'/institution/manuals/{self.manual.id}/draft/session/',
                         {'password': password})
        return resp

    def _save_draft(self, session_key, revision, client=None,
                    name='saved.docx', content=b'PK\x03\x04 saved'):
        client = client or self.editor_client
        upload = SimpleUploadedFile(name, content)
        return client.post(
            f'/institution/manuals/{self.manual.id}/draft/save/',
            {'file': upload, 'session_key': session_key, 'revision': revision})


class EditPasswordTests(DraftWorkflowBase):
    def test_password_stored_as_hash_only(self):
        self._set_password('plain-secret')
        self.manual.refresh_from_db()
        self.assertNotIn('plain-secret', self.manual.password_hash)
        self.assertTrue(self.manual.password_hash)

    def test_wrong_password_rejected_and_locked_after_fails(self):
        self._set_password()
        self._add_file()
        for i in range(5):
            resp = self._start_session(password=f'wrong-{i}')
            self.assertTrue(has_error(resp))
            self.assertIn('错误', resp.json()['error'])
        # 第 6 次即使密码正确也被锁定
        resp = self._start_session(password='edit-pass-1')
        self.assertTrue(has_error(resp))
        self.assertIn('分钟', resp.json()['error'])
        self.manual.refresh_from_db()
        self.assertIsNotNone(self.manual.password_locked_until)

    def test_no_password_configured_rejected(self):
        self._add_file()
        resp = self._start_session(password='whatever')
        self.assertTrue(has_error(resp))
        self.assertIn('尚未设置', resp.json()['error'])

    def test_password_reset_revokes_sessions(self):
        """重置密码使既有编辑会话失效；保存被拒"""
        self._set_password()
        self._add_file()
        resp = self._start_session()
        session_key = get_data(resp)['session_key']
        # 重置密码
        put_json(self.manager_client,
                 f'/institution/manuals/{self.manual.id}/password/',
                 {'password': 'new-pass-2'})
        resp = self._save_draft(session_key, 1)
        self.assertTrue(has_error(resp))
        self.assertIn('失效', resp.json()['error'])
        # 新密码可重新开启会话
        resp = self._start_session(password='new-pass-2')
        self.assertFalse(has_error(resp), resp.content)


class EditSessionTests(DraftWorkflowBase):
    def setUp(self):
        super().setUp()
        self._set_password()
        self._add_file()

    def test_session_requires_edit_grant_and_ownership(self):
        """无授权者不能开会话（页面权限满足也不行）"""
        outsider = make_user('o', tenant_id='deptA', perms=[PERM_DRAFT])
        resp = self._start_session(make_client(outsider))
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])

    def test_session_requires_correct_password(self):
        resp = self._start_session(password='nope')
        self.assertTrue(has_error(resp))

    def test_single_writer_other_user_rejected(self):
        """负责人独占编辑：同手册其他持编制授权账号不能开该文件的会话"""
        resp = self._start_session()
        self.assertFalse(has_error(resp), resp.content)
        editor2 = make_user('editor2', tenant_id='deptC', perms=[PERM_DRAFT])
        make_grant(self.manual, editor2, can_edit=True)
        resp = self._start_session(make_client(editor2))
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])

    def test_same_user_resumes_same_session(self):
        resp1 = self._start_session()
        key1 = get_data(resp1)['session_key']
        resp2 = self._start_session()
        key2 = get_data(resp2)['session_key']
        self.assertEqual(key1, key2)

    def test_release_session_allows_owner_to_restart(self):
        resp = self._start_session()
        key = get_data(resp)['session_key']
        resp = delete_json(self.editor_client,
                           f'/institution/manuals/{self.manual.id}/draft/session/',
                           {'session_key': key})
        self.assertFalse(has_error(resp), resp.content)
        resp = self._start_session()
        self.assertFalse(has_error(resp), resp.content)

    def test_expired_session_rejected(self):
        resp = self._start_session()
        key = get_data(resp)['session_key']
        ManualEditSession.objects.filter(session_key=key).update(
            expires_at=timezone.now() - timedelta(seconds=1))
        resp = self._save_draft(key, 1)
        self.assertTrue(has_error(resp))
        self.assertIn('过期', resp.json()['error'])

    def test_grant_revoked_mid_session_save_denied(self):
        """编制授权撤销后既有会话不能再保存（页面权限保留）"""
        resp = self._start_session()
        key = get_data(resp)['session_key']
        ManualAuthorization.objects.filter(
            manual=self.manual, account=self.editor).update(can_edit=False)
        resp = self._save_draft(key, 1)
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])


class DraftSaveTests(DraftWorkflowBase):
    def setUp(self):
        super().setUp()
        self._set_password()
        self.file_data = self._add_file()
        self.original_id = ManualOriginal.objects.filter(
            file_id=self.file_data['id']).latest('id').id

    def test_create_draft_from_docx(self):
        data = self._add_file('原稿.docx')
        draft_data = data['draft']
        self.assertEqual(draft_data['revision'], 1)
        draft = ManualDraft.objects.get(file_id=self.file_id)
        self.assertTrue(draft.file_path.startswith('drafts/'))
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(draft.file_path)))
        # 显示名=用户原稿名（不带存储后缀）；存储路径仍唯一
        self.assertEqual(draft_data['file_name'], '原稿.docx')
        self.assertEqual(draft.original_name, '原稿.docx')
        self.assertIn('_', draft.file_path.rsplit('/', 1)[-1])
        # 原稿文件保持原样
        original = ManualOriginal.objects.get(pk=self.original_id)
        abs_orig = storage.resolve_absolute_path(original.file_path)
        with open(abs_orig, 'rb') as f:
            self.assertEqual(f.read(), b'PK\x03\x04 draft-base')

    def test_create_draft_requires_original(self):
        empty = Manual.objects.create(
            name='空手册', code='K-001', org_type=Manual.OWNER_SECTION,
            org_name='乙科室', owner=self.manager, tenant_id='deptA')
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{empty.id}/draft/create/', {})
        self.assertTrue(has_error(resp))
        self.assertIn('还没有文件', resp.json()['error'])

    def test_save_requires_session_and_revision(self):
        # 无会话
        resp = self._save_draft('', 1)
        self.assertTrue(has_error(resp))
        # 修订序号不匹配（旧标签页/迟到保存）
        resp2 = self._start_session()
        key = get_data(resp2)['session_key']
        resp = self._save_draft(key, 999)
        self.assertTrue(has_error(resp))
        self.assertIn('已被其他会话更新', resp.json()['error'])
        self.assertEqual(self._main_draft().revision, 1)

    def test_save_ok_revision_increments(self):
        resp = self._start_session()
        key = get_data(resp)['session_key']
        resp = self._save_draft(key, 1, name='v2.docx', content=b'PK\x03\x04 v2')
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(data['revision'], 2)
        draft = self._main_draft()
        self.assertEqual(draft.revision, 2)
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(draft.file_path)))
        # 上传保存的显示名=上传文件名本身（非带随机后缀的存储名）
        self.assertEqual(draft.original_name, 'v2.docx')
        # 旧会话续用可继续保存（滑动续期）
        resp = self._save_draft(key, 2, name='v3.docx', content=b'PK\x03\x04 v3')
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revision'], 3)

    def test_save_replaces_old_draft_file_and_cleans_it(self):
        """草稿替换：旧物理文件在事务提交后清理，drafts/ 不留孤儿文件"""
        draft1 = self._main_draft()
        path1 = storage.resolve_absolute_path(draft1.file_path)
        self.assertTrue(os.path.exists(path1))
        resp = self._start_session()
        key = get_data(resp)['session_key']
        with self.captureOnCommitCallbacks(execute=True):
            resp = self._save_draft(key, draft1.revision,
                                    name='v2.docx', content=b'PK\x03\x04 v2')
        self.assertFalse(has_error(resp), resp.content)
        draft2 = self._main_draft()
        self.assertNotEqual(draft1.file_path, draft2.file_path)
        self.assertFalse(os.path.exists(path1))
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(draft2.file_path)))

    def test_save_reject_non_docx(self):
        resp = self._start_session()
        key = get_data(resp)['session_key']
        resp = self._save_draft(key, 1, name='x.txt', content=b'text')
        self.assertTrue(has_error(resp))
        self.assertIn('.docx', resp.json()['error'])

    def test_draft_download_and_detail_require_edit_role(self):
        resp = self.editor_client.get(f'/institution/manuals/{self.manual.id}/draft/')
        self.assertFalse(has_error(resp), resp.content)
        resp = self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/draft/download/')
        self.assertEqual(resp.status_code, 200)
        # 无角色者不可见草稿
        insider = make_user('in', tenant_id='deptA',
                            perms=[PERM_DRAFT, PERM_DOWNLOAD])
        resp = make_client(insider).get(
            f'/institution/manuals/{self.manual.id}/draft/')
        self.assertTrue(has_error(resp))
        resp = make_client(insider).get(
            f'/institution/manuals/{self.manual.id}/draft/download/')
        self.assertTrue(has_error(resp))


class DocConversionTests(DraftWorkflowBase):
    """容器内真实 LibreOffice 转换：.doc 原稿保留 + 生成 .docx 工作副本"""

    def test_doc_original_preserved_and_draft_converted(self):
        data = self._add_file('第一章.doc', RTF_AS_DOC)
        self.assertEqual(data['draft']['revision'], 1)
        original = ManualOriginal.objects.filter(manual=self.manual).latest('id')
        abs_orig = storage.resolve_absolute_path(original.file_path)
        with open(abs_orig, 'rb') as f:
            before = f.read()
        self.assertEqual(before, RTF_AS_DOC)
        # .doc 原稿的草稿显示名=原稿主体名 + .docx 扩展名
        self.assertEqual(data['draft']['file_name'], '第一章.docx')
        draft = self._main_draft()
        self.assertTrue(draft.file_path.startswith('drafts/'))
        self.assertEqual(draft.original_name, '第一章.docx')
        # 原稿字节不变
        with open(abs_orig, 'rb') as f:
            self.assertEqual(f.read(), before)

    def test_doc_conversion_failure_clear_feedback(self):
        """损坏的 .doc：文件条目与原稿保留，草稿建立失败给明确提示，
        不影响原稿预览/下载，也不产生可发布草稿"""
        data = self._add_file('broken.doc', b'\x00\x01not-a-word-file')
        self.assertIn('转换', data['draft_error'])
        self.assertIsNone(data['draft'])
        original = ManualOriginal.objects.filter(manual=self.manual).latest('id')
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(original.file_path)))
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/originals/{original.id}/preview-url/')
        self.assertFalse(has_error(resp), resp.content)

    def test_draft_create_denied_without_role(self):
        file_id = self._add_file()['id']
        insider = make_user('in', tenant_id='deptA', perms=[PERM_DRAFT])
        resp = post_json(make_client(insider),
                         f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/create/',
                         {})
        self.assertTrue(has_error(resp))

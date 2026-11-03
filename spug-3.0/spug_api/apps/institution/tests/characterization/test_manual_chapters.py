# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""旧章节分工（遗留只读）与操作记录的真实行为测试

关键验收语义（2026-10-29 章节分工已由文件分工替代，见
test_manual_file_assignment.py）：
- 旧 ManualChapter 记录保留可读，供人工核对；写接口（新增/编辑/删除/
  进度）全部关闭并返回明确业务错误，绝不删除或改写旧记录。
- 负责人身份不授予超出手册编制角色的编辑权（以文件分工沿用同一不变量）。
- 操作记录时间线对可见者开放，记录动作、账号与时间。
"""
import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.institution import storage
from apps.institution.models import Manual, ManualChapter, ManualOperationLog
from apps.institution.tests.base import (
    ALL_PERMS, PERM_DRAFT, PERM_VIEW, delete_json, get_data, has_error,
    make_client, make_grant, make_user, post_json, put_json, setup_test_env,
)


class ChapterTestsBase(TestCase):
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
            name='SMS手册', code='SMS-001',
            org_type=Manual.OWNER_DEPARTMENT, org_name='某部门',
            owner=self.manager, tenant_id='deptA')
        self.editor = make_user('editor', tenant_id='deptB',
                                perms=[PERM_DRAFT, PERM_VIEW])
        make_grant(self.manual, self.editor, can_view=True, can_edit=True)
        self.editor_client = make_client(self.editor)
        self.viewer = make_user('viewer', tenant_id='deptZ',
                                perms=[PERM_VIEW])
        make_grant(self.manual, self.viewer, can_view=True)
        self.viewer_client = make_client(self.viewer)


class LegacyChapterReadonlyTests(ChapterTestsBase):
    """旧章节分工：清单可读；写接口关闭；记录保留供人工核对"""

    def _seed(self, title='第一章'):
        return ManualChapter.objects.create(manual=self.manual, title=title)

    def test_list_visible_to_view_grant(self):
        self._seed('第一章')
        self._seed('第二章')
        resp = self.viewer_client.get(
            f'/institution/manuals/{self.manual.id}/chapters/')
        self.assertFalse(has_error(resp), resp.content)
        titles = [x['title'] for x in get_data(resp)]
        self.assertEqual(titles, ['第一章', '第二章'])

    def test_create_closed(self):
        resp = post_json(self.editor_client,
                         f'/institution/manuals/{self.manual.id}/chapters/create/',
                         {'title': '新章节'})
        self.assertTrue(has_error(resp))
        self.assertIn('文件分工', resp.json()['error'])
        self.assertEqual(ManualChapter.objects.filter(manual=self.manual).count(), 0)

    def test_update_and_delete_closed_and_records_kept(self):
        chapter = self._seed('旧标题')
        resp = put_json(self.editor_client,
                        f'/institution/manuals/{self.manual.id}/chapters/{chapter.id}/',
                        {'title': '新标题'})
        self.assertTrue(has_error(resp))
        resp = delete_json(self.editor_client,
                           f'/institution/manuals/{self.manual.id}/chapters/{chapter.id}/')
        self.assertTrue(has_error(resp))
        chapter.refresh_from_db()
        self.assertEqual(chapter.title, '旧标题')

    def test_progress_closed(self):
        chapter = self._seed('第三章')
        resp = post_json(self.editor_client,
                         f'/institution/manuals/{self.manual.id}/chapters/{chapter.id}/progress/',
                         {'progress': 'submitted'})
        self.assertTrue(has_error(resp))
        chapter.refresh_from_db()
        self.assertIsNone(chapter.submitted_at)
        self.assertFalse(ManualOperationLog.objects.filter(
            manual=self.manual, action='chapter_update').exists())

    def test_chapter_owner_without_edit_grant_cannot_save_draft(self):
        """负责人身份不授予草稿编辑权（文件分工沿用同一不变量：还须
        持手册 can_edit 授权）"""
        owner = make_user('owner', tenant_id='deptC',
                          perms=['institution.manual.draft_edit'])
        ManualChapter.objects.create(
            manual=self.manual, title='第五章', owner=owner)
        upload = SimpleUploadedFile('orig.docx', b'PK\x03\x04 docx')
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/create/',
            {'file': upload, 'owner_id': str(self.editor.id)})
        self.assertFalse(has_error(resp), resp.content)
        put_json(self.manager_client,
                 f'/institution/manuals/{self.manual.id}/password/',
                 {'password': 'pass-1234'})
        resp = post_json(make_client(owner),
                         f'/institution/manuals/{self.manual.id}/draft/session/',
                         {'password': 'pass-1234'})
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])


class OperationLogTests(ChapterTestsBase):
    def _seed_actions(self):
        upload = SimpleUploadedFile('orig.docx', b'PK\x03\x04 docx')
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/create/',
            {'file': upload, 'owner_id': str(self.editor.id)})
        self.assertFalse(has_error(resp), resp.content)
        file_id = get_data(resp)['id']
        put_json(self.manager_client,
                 f'/institution/manuals/{self.manual.id}/password/',
                 {'password': 'pass-1234'})
        resp = post_json(self.editor_client,
                         f'/institution/manuals/{self.manual.id}/draft/session/',
                         {'password': 'pass-1234'})
        session = get_data(resp)
        upload = SimpleUploadedFile('saved.docx', b'PK\x03\x04 saved')
        resp = self.editor_client.post(
            f'/institution/manuals/{self.manual.id}/draft/save/',
            {'file': upload, 'session_key': session['session_key'],
             'revision': session['revision']})
        self.assertFalse(has_error(resp), resp.content)
        # 发布前退出编辑会话（活跃会话阻断整套发布）
        delete_json(self.editor_client,
                    f'/institution/manuals/{self.manual.id}/draft/session/',
                    {'session_key': session['session_key']})
        # 发布交接：文件负责人须提交编制后发布人才能整套发布
        post_json(self.editor_client,
                  f'/institution/manuals/{self.manual.id}/files/'
                  f'{file_id}/submit/', {})
        publisher = make_user('pub', tenant_id='deptC',
                              perms=['institution.manual.publish'])
        make_grant(self.manual, publisher, can_publish=True)
        resp = post_json(make_client(publisher),
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': '首版发布'})
        self.assertFalse(has_error(resp), resp.content)

    def test_timeline_records_key_actions_with_account(self):
        self._seed_actions()
        resp = self.viewer_client.get(
            f'/institution/manuals/{self.manual.id}/operation-logs/')
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        actions = [x['action'] for x in data['items']]
        # create 动作在 test_manual_crud.test_create_manual_with_roles 已钉死；
        # 本时间线覆盖由 API 触发的后续关键动作
        for expected in ('file_add', 'session_start', 'save_draft', 'publish'):
            self.assertIn(expected, actions, f'缺少动作 {expected}: {actions}')
        publish_log = next(x for x in data['items'] if x['action'] == 'publish')
        self.assertTrue(publish_log['user_name'])

    def test_timeline_denied_to_outsider(self):
        outsider = make_user('o', tenant_id='deptA', perms=[PERM_VIEW])
        resp = make_client(outsider).get(
            f'/institution/manuals/{self.manual.id}/operation-logs/')
        self.assertTrue(has_error(resp))

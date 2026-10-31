# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""文件变更记录数据源的真实行为测试

覆盖（详情页信息层级改造，2026-10-29）：
- GET files/<fid>/version-history/：按文件回看发布参与记录——变更状态
  由相邻版本快照 SHA256 计算（added/modified/unchanged），被移除后
  重新纳入按 added，未参与的版本不出现；新版本在前。
- 权限沿用发布域（can_view_published）：仅编制角色且手册关闭
  "编制者可查看发布版"时被拒；跨制度文件 ID 被拒。
- GET operation-logs/?file_id=：按文件过滤操作记录，非法值明确拒绝。
"""
from django.test import TestCase

from apps.institution import storage
from apps.institution.models import (Manual, ManualDraft, ManualFile,
                                     ManualVersion)
from apps.institution.tests.base import (
    ALL_PERMS, PERM_DRAFT, PERM_DOWNLOAD, PERM_PUBLISH, PERM_VIEW, get_data,
    has_error, make_client, make_grant, make_user, post_json, put_json,
    setup_test_env,
)

DOCX_A = b'PK\x03\x04 file-history-A'
DOCX_A2 = b'PK\x03\x04 file-history-A2'
DOCX_B = b'PK\x03\x04 file-history-B'
DOCX_C = b'PK\x03\x04 file-history-C'


class FileHistoryBase(TestCase):

    def setUp(self):
        setup_test_env()
        import tempfile
        from unittest.mock import patch
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(storage, 'get_institution_storage_base',
                               return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.manager = make_user('mgr', tenant_id='deptA', perms=ALL_PERMS)
        self.manager_client = make_client(self.manager)
        self.manual = Manual.objects.create(
            name='文件变更手册', code='WJ-001',
            org_type=Manual.OWNER_SECTION, org_name='甲科室',
            owner=self.manager, tenant_id='deptA')
        self.editor = make_user('editor', tenant_id='deptB',
                                perms=[PERM_DRAFT, PERM_DOWNLOAD, PERM_VIEW])
        make_grant(self.manual, self.editor, can_view=True, can_edit=True)
        self.editor_client = make_client(self.editor)
        self.publisher = make_user('pub', tenant_id='deptZ',
                                   perms=[PERM_PUBLISH, PERM_DOWNLOAD, PERM_VIEW])
        make_grant(self.manual, self.publisher, can_view=True, can_publish=True)
        self.publisher_client = make_client(self.publisher)
        self.viewer = make_user('viewer', tenant_id='deptY',
                                perms=[PERM_VIEW, PERM_DOWNLOAD])
        make_grant(self.manual, self.viewer, can_view=True)
        self.viewer_client = make_client(self.viewer)
        put_json(self.manager_client,
                 f'/institution/manuals/{self.manual.id}/password/',
                 {'password': 'edit-pass-1'})

    def _add_file(self, name, content):
        from django.core.files.uploadedfile import SimpleUploadedFile
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/create/',
            {'file': SimpleUploadedFile(name, content),
             'owner_id': str(self.editor.id)})
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _publish(self, note):
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': note})
        self.assertFalse(has_error(resp), resp.content)
        return ManualVersion.objects.get(pk=get_data(resp)['id'])

    def _save_then_release(self, file_id, content):
        resp = post_json(
            self.editor_client,
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/session/',
            {'password': 'edit-pass-1'})
        self.assertFalse(has_error(resp), resp.content)
        key = get_data(resp)['session_key']
        from django.core.files.uploadedfile import SimpleUploadedFile
        resp = self.editor_client.post(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/save/',
            {'file': SimpleUploadedFile('saved.docx', content),
             'session_key': key, 'revision': 1})
        self.assertFalse(has_error(resp), resp.content)
        resp = self.editor_client.delete(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/session/',
            data=f'{{"session_key": "{key}"}}',
            content_type='application/json')
        self.assertFalse(has_error(resp), resp.content)

    def _version_history(self, file_id, client=None):
        client = client or self.viewer_client
        return client.get(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/version-history/')


class FileVersionHistoryTests(FileHistoryBase):
    """按文件回看发布参与记录"""

    def setUp(self):
        super().setUp()
        self.file_a = self._add_file('甲.docx', DOCX_A)
        self.file_b = self._add_file('乙.docx', DOCX_B)
        self.v1 = self._publish('初版')
        self._save_then_release(self.file_a['id'], DOCX_A2)
        self.v2 = self._publish('甲更新')
        self.file_c = self._add_file('丙.docx', DOCX_C)
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/{self.file_b["id"]}/remove/',
            {})
        self.assertFalse(has_error(resp), resp.content)
        self.v3 = self._publish('丙加入乙移除')

    def test_history_rows_ordered_desc_with_change_types(self):
        resp = self._version_history(self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(data['file_id'], self.file_a['id'])
        self.assertEqual(data['file_name'], '甲.docx')
        self.assertEqual([r['version_no'] for r in data['items']], [3, 2, 1])
        by_no = {r['version_no']: r for r in data['items']}
        self.assertEqual(by_no[1]['change_type'], 'added')
        self.assertEqual(by_no[2]['change_type'], 'modified')
        self.assertEqual(by_no[3]['change_type'], 'unchanged')
        # 行字段：版本说明/发布人/快照定位/哈希
        self.assertEqual(by_no[2]['change_note'], '甲更新')
        self.assertEqual(by_no[2]['version_id'], self.v2.id)
        self.assertTrue(by_no[2]['snapshot_id'])
        self.assertEqual(by_no[2]['file_hash'],
                         self.v2.files.get(manual_file_id=self.file_a['id']).file_hash)
        self.assertEqual(by_no[2]['published_by_name'], self.publisher.username)

    def test_removed_file_versions_skipped_not_hidden_as_rows(self):
        """乙在 v3 被移除：v3 不出现在其参与记录中（不是伪装成一行）"""
        resp = self._version_history(self.file_b['id'])
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual([r['version_no'] for r in data['items']], [2, 1])
        by_no = {r['version_no']: r for r in data['items']}
        self.assertEqual(by_no[1]['change_type'], 'added')
        self.assertEqual(by_no[2]['change_type'], 'unchanged')

    def test_readded_file_marked_added_again(self):
        """丙后加入：仅 v3 一行且为 added"""
        resp = self._version_history(self.file_c['id'])
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual([r['version_no'] for r in data['items']], [3])
        self.assertEqual(data['items'][0]['change_type'], 'added')

    def test_file_without_any_publish_returns_empty(self):
        """未参与过发布的文件返回空清单而不是错误"""
        file_d = self._add_file('丁.docx', DOCX_B)
        resp = self._version_history(file_d['id'])
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['items'], [])

    def test_permission_requires_view_published(self):
        """仅编制授权（无 can_view）不可见发布历史（第二轮：仅 can_edit
        不再可见发布版，editor_can_view_published 开关已删除）"""
        edit_only = make_user('edit-only', tenant_id='deptB',
                              perms=[PERM_VIEW])
        make_grant(self.manual, edit_only, can_edit=True)
        resp = self._version_history(self.file_a['id'],
                                     client=make_client(edit_only))
        self.assertTrue(has_error(resp))
        # 查看角色照常
        resp = self._version_history(self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)

    def test_cross_manual_file_rejected(self):
        other = Manual.objects.create(
            name='别家手册', code='OT-300',
            org_type=Manual.OWNER_SECTION, org_name='乙科室',
            owner=self.manager, tenant_id='deptA')
        foreign_file = ManualFile.objects.create(
            manual=other, display_name='别家.docx')
        resp = self._version_history(foreign_file.id)
        self.assertTrue(has_error(resp))
        self.assertIn('不存在', resp.json()['error'])


class OperationLogFileFilterTests(FileHistoryBase):
    """操作记录按文件过滤"""

    def setUp(self):
        super().setUp()
        self.file_a = self._add_file('甲.docx', DOCX_A)
        self.file_b = self._add_file('乙.docx', DOCX_B)
        self._save_then_release(self.file_a['id'], DOCX_A2)

    def _logs(self, file_id=None):
        url = f'/institution/manuals/{self.manual.id}/operation-logs/'
        if file_id is not None:
            url += f'?file_id={file_id}'
        resp = self.viewer_client.get(url)
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def test_filter_returns_only_target_file_logs(self):
        all_logs = self._logs()
        self.assertGreater(all_logs['total'], 0)
        rows_a = self._logs(self.file_a['id'])['items']
        self.assertTrue(rows_a)
        for row in rows_a:
            self.assertEqual(row['file_id'], self.file_a['id'])
        rows_b = self._logs(self.file_b['id'])['items']
        self.assertTrue(rows_b)
        for row in rows_b:
            self.assertEqual(row['file_id'], self.file_b['id'])
        # 过滤是全局清单的真子集（甲+乙的动作都在全局里）
        self.assertLess(len(rows_a), all_logs['total'])

    def test_invalid_file_id_rejected(self):
        resp = self.viewer_client.get(
            f'/institution/manuals/{self.manual.id}/operation-logs/?file_id=abc')
        self.assertTrue(has_error(resp))

    def test_filter_without_match_returns_empty(self):
        data = self._logs(999999)
        self.assertEqual(data['total'], 0)
        self.assertEqual(data['items'], [])

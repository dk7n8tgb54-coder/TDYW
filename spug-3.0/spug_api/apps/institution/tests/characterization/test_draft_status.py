# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""草稿状态总览（draft-status）的真实行为测试（2026-10-29）

验收口径（草稿状态展示任务后端部分，全部经 test client 真实请求链路）：
- 逐份文件"草稿 vs 当前生效版本"关系由服务端按快照 SHA256 哈希判定：
  一致 / 已修改未发布 / 新增 / 等待首次发布 / 缺草稿 / 暂不能确认。
- 同内容重新保存（修订号+1 但哈希相同）不是待发布变化——内容变化
  以哈希为准，不得按修订号推断。
- 整套待发布变化包括 文件移除 / 改名 / 顺序调整。
- 发布后保留的草稿与新生效版一致（unchanged）；再次修改后回到 modified。
- 编辑会话占用（含未完成同步）与草稿文件缺失 = unconfirmed，绝不冒充
  "无变化"；缺草稿附 draft_recovery 提示。
- 权限：编制角色与发布角色可读；仅查看角色拒绝（不得因此看到草稿信息）。
"""
import json
import os

from apps.institution import storage
from apps.institution.models import ManualDraft
from apps.institution.tests.base import (
    PERM_DOWNLOAD, PERM_VIEW, get_data, has_error, make_client, make_user,
    post_json)
from apps.institution.tests.characterization.test_manual_multi_files import (
    DOCX)
from apps.institution.tests.characterization.test_version_changes import (
    VersionChangesTestBase)


class DraftStatusApiTests(VersionChangesTestBase):
    """draft-status 接口：关系判定 / 摘要 / 权限"""

    def _status(self, client=None):
        resp = (client or self.manager_client).get(
            f'/institution/manuals/{self.manual.id}/draft-status/')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _item(self, status, file_id):
        return next(x for x in status['items'] if x['file_id'] == file_id)

    # ------------------------------------------------------------------
    # 首次发布 / 发布后一致 / 修改

    def test_awaiting_first_publish_before_any_version(self):
        """从未发布：全部文件=等待首次发布；无生效版本；待发布变化为真"""
        status = self._status()
        self.assertFalse(status['has_current_version'])
        self.assertIsNone(status['current_version_no'])
        self.assertEqual(status['removed_items'], [])
        for row in status['items']:
            self.assertEqual(row['status'], 'awaiting_first_publish')
            self.assertTrue(row['has_draft'])
        s = status['summary']
        self.assertEqual(s['awaiting_first_publish'], 2)
        self.assertFalse(s['has_current_version'])
        self.assertTrue(s['has_pending_changes'])
        self.assertFalse(s['consistent'])
        self.assertTrue(s['determinable'])

    def test_after_publish_retained_drafts_are_unchanged(self):
        """发布后草稿保留：与新生效版一致，整套摘要=无待发布变化"""
        self._publish('v1')
        status = self._status()
        self.assertTrue(status['has_current_version'])
        self.assertEqual(status['current_version_no'], 1)
        for row in status['items']:
            self.assertEqual(row['status'], 'unchanged')
            self.assertFalse(row['renamed'])
        s = status['summary']
        self.assertEqual(s['unchanged'], 2)
        self.assertEqual(s['modified'], 0)
        self.assertFalse(s['has_pending_changes'])
        self.assertTrue(s['consistent'])
        self.assertTrue(s['determinable'])

    def test_republish_makes_modified_draft_consistent_again(self):
        """修改后发布 v2：曾修改的草稿保留下来，显示为与 v2 一致"""
        self._publish('v1')
        self._modify_file(self.file_a['id'], DOCX + b'-a-v2')
        status = self._status()
        self.assertEqual(self._item(status, self.file_a['id'])['status'],
                         'modified')
        self.assertEqual(status['summary']['modified'], 1)
        self._publish('v2')
        status = self._status()
        self.assertEqual(self._item(status, self.file_a['id'])['status'],
                         'unchanged')
        self.assertTrue(status['summary']['consistent'])
        self.assertEqual(status['current_version_no'], 2)

    def test_modified_draft_counts_pending_change(self):
        """保存新内容（哈希变化）：modified；整套摘要非一致"""
        self._publish('v1')
        self._modify_file(self.file_a['id'], DOCX + b'-a-new')
        status = self._status()
        row = self._item(status, self.file_a['id'])
        self.assertEqual(row['status'], 'modified')
        self.assertEqual(row['draft_revision'],
                         ManualDraft.objects.get(
                             file_id=self.file_a['id']).revision)
        other = self._item(status, self.file_b['id'])
        self.assertEqual(other['status'], 'unchanged')
        s = status['summary']
        self.assertEqual(s['modified'], 1)
        self.assertEqual(s['unchanged'], 1)
        self.assertTrue(s['has_pending_changes'])
        self.assertFalse(s['consistent'])

    def test_same_content_resave_is_not_a_change(self):
        """同内容重存（修订号+1、哈希不变）：不是待发布变化——内容以哈希
        判定；但真实的内容工作会把该文件置回"修订进行中"（显式状态），
        整套不再声明"一致"，也不计入待发布变化"""
        self._publish('v1')
        draft = ManualDraft.objects.get(file_id=self.file_a['id'])
        revision_before = draft.revision
        resp = self._start_session(file_id=self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        key = get_data(resp)['session_key']
        resp = self._save(self.editor_client, self.file_a['id'], key,
                          revision_before, name='re-saved.docx',
                          content=DOCX + b'-a')
        self.assertFalse(has_error(resp), resp.content)
        self.editor_client.delete(
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.file_a["id"]}/draft/session/',
            data=json.dumps({'session_key': key}),
            content_type='application/json')
        draft.refresh_from_db()
        self.assertEqual(draft.revision, revision_before + 1)
        status = self._status()
        self.assertEqual(self._item(status, self.file_a['id'])['status'],
                         'unchanged')
        s = status['summary']
        self.assertFalse(s['has_pending_changes'])
        self.assertFalse(s['consistent'])
        self.assertEqual(s['revising'], 1)

    # ------------------------------------------------------------------
    # 结构性变化：新增 / 移除 / 改名 / 排序

    def test_added_file_pending_until_publish(self):
        """发布后新增文件：added；进入生效版本前一直算待发布变化"""
        self._publish('v1')
        self._add_file('丙.docx', DOCX + b'-c')
        status = self._status()
        added = [x for x in status['items'] if x['status'] == 'added']
        self.assertEqual([x['name'] for x in added], ['丙.docx'])
        s = status['summary']
        self.assertEqual(s['added'], 1)
        self.assertTrue(s['has_pending_changes'])
        self.assertFalse(s['consistent'])

    def test_removed_file_listed_in_removed_items(self):
        """移除文件：退出 items、进入 removed_items，并计入待发布变化"""
        self._publish('v1')
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/'
                         f'{self.file_a["id"]}/remove/', {})
        self.assertFalse(has_error(resp), resp.content)
        status = self._status()
        self.assertEqual([x['file_id'] for x in status['items']],
                         [self.file_b['id']])
        removed = status['removed_items']
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0]['name'], '甲.docx')
        self.assertEqual(removed[0]['from_version_no'], 1)
        self.assertEqual(removed[0]['file_id'], self.file_a['id'])
        s = status['summary']
        self.assertEqual(s['removed'], 1)
        self.assertTrue(s['has_pending_changes'])
        self.assertFalse(s['consistent'])

    def test_rename_flags_pending_change_without_content_change(self):
        """改名（内容哈希不变）：行内 renamed=True 且计为待发布变化"""
        self._publish('v1')
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/'
                         f'{self.file_a["id"]}/rename/',
                         {'name': '甲-新名.docx'})
        self.assertFalse(has_error(resp), resp.content)
        status = self._status()
        row = self._item(status, self.file_a['id'])
        self.assertTrue(row['renamed'])
        self.assertEqual(row['name'], '甲-新名.docx')
        self.assertEqual(row['current_name'], '甲.docx')
        self.assertEqual(row['status'], 'unchanged')
        s = status['summary']
        self.assertEqual(s['renamed'], 1)
        self.assertTrue(s['has_pending_changes'])
        self.assertFalse(s['consistent'])

    def test_reorder_flags_pending_change(self):
        """调整顺序：summary.reordered=True 并计为待发布变化"""
        self._publish('v1')
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/'
                         f'{self.file_b["id"]}/move/', {'position': 1})
        self.assertFalse(has_error(resp), resp.content)
        status = self._status()
        self.assertTrue(status['summary']['reordered'])
        self.assertTrue(status['summary']['has_pending_changes'])
        self.assertFalse(status['summary']['consistent'])
        # 文件内容关系不受排序影响：仍为一致
        for row in status['items']:
            self.assertEqual(row['status'], 'unchanged')
            self.assertFalse(row['renamed'])

    def test_structure_changes_cleared_after_republish(self):
        """改名+排序发布后：与新版一致，renamed/reordered 复位"""
        self._publish('v1')
        post_json(self.manager_client,
                  f'/institution/manuals/{self.manual.id}/files/'
                  f'{self.file_a["id"]}/rename/', {'name': '甲-新名.docx'})
        post_json(self.manager_client,
                  f'/institution/manuals/{self.manual.id}/files/'
                  f'{self.file_b["id"]}/move/', {'position': 1})
        self._publish('v2 结构调整')
        status = self._status()
        self.assertFalse(status['summary']['reordered'])
        self.assertEqual(status['summary']['renamed'], 0)
        self.assertTrue(status['summary']['consistent'])
        self.assertFalse(status['summary']['has_pending_changes'])

    # ------------------------------------------------------------------
    # 异常状态：缺草稿 / 会话占用 / 草稿文件缺失

    def test_missing_draft_reported_with_recovery_hint(self):
        """缺草稿：no_draft + draft_recovery 提示；绝不归入一致/无变化"""
        self._publish('v1')
        ManualDraft.objects.get(file_id=self.file_b['id']).delete()
        status = self._status()
        row = self._item(status, self.file_b['id'])
        self.assertEqual(row['status'], 'no_draft')
        self.assertFalse(row['has_draft'])
        self.assertIsNone(row['draft_revision'])
        self.assertEqual(row['draft_recovery']['source'], 'current_version')
        s = status['summary']
        self.assertEqual(s['no_draft'], 1)
        self.assertFalse(s['consistent'])
        self.assertTrue(s['determinable'])

    def test_active_session_marks_unconfirmed_not_unchanged(self):
        """编辑会话占用（保存回调可能未完成）：unconfirmed，不算无变化"""
        self._publish('v1')
        resp = self._start_session(file_id=self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        status = self._status()
        row = self._item(status, self.file_a['id'])
        self.assertEqual(row['status'], 'unconfirmed')
        self.assertEqual(row['unconfirmed_reason'], 'session_busy')
        # is_mine 相对请求者：管理者查看编辑者的会话为他人占用
        self.assertFalse(row['session']['is_mine'])
        self.assertTrue(row['session']['user_name'])
        editor_status = self._status(self.editor_client)
        self.assertTrue(
            self._item(editor_status, self.file_a['id'])['session']['is_mine'])
        s = status['summary']
        self.assertEqual(s['unconfirmed'], 1)
        self.assertEqual(s['unchanged'], 1)
        self.assertFalse(s['determinable'])
        self.assertFalse(s['consistent'])
        # 退出会话后状态恢复可确认
        self.editor_client.delete(
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.file_a["id"]}/draft/session/',
            data=json.dumps({'session_key': get_data(resp)['session_key']}),
            content_type='application/json')
        status = self._status()
        self.assertEqual(self._item(status, self.file_a['id'])['status'],
                         'unchanged')
        self.assertTrue(status['summary']['consistent'])

    def test_missing_draft_file_marks_unconfirmed(self):
        """草稿物理文件缺失：unconfirmed/draft_missing，不显示可发布"""
        self._publish('v1')
        draft = ManualDraft.objects.get(file_id=self.file_a['id'])
        os.remove(storage.resolve_absolute_path(draft.file_path))
        status = self._status()
        row = self._item(status, self.file_a['id'])
        self.assertEqual(row['status'], 'unconfirmed')
        self.assertEqual(row['unconfirmed_reason'], 'draft_missing')
        s = status['summary']
        self.assertEqual(s['unconfirmed'], 1)
        self.assertFalse(s['consistent'])
        self.assertFalse(s['determinable'])

    def test_modified_content_behind_session_stays_unconfirmed(self):
        """占用优先：会话进行中时即使草稿哈希已变化也显示 unconfirmed"""
        self._publish('v1')
        self._modify_file(self.file_a['id'], DOCX + b'-a-new')
        self._start_session(file_id=self.file_a['id'])
        status = self._status()
        row = self._item(status, self.file_a['id'])
        self.assertEqual(row['status'], 'unconfirmed')
        self.assertEqual(status['summary']['modified'], 0)

    # ------------------------------------------------------------------
    # 权限：编制/发布可读；仅查看拒绝

    def test_editor_and_publisher_can_read_status(self):
        self._publish('v1')
        for client in (self.editor_client, self.publisher_client,
                       self.manager_client):
            status = self._status(client)
            self.assertEqual(len(status['items']), 2)

    def test_view_only_role_cannot_read_status(self):
        """仅查看角色被拒绝：不得经由本接口看到草稿信息"""
        self._publish('v1')
        resp = self.viewer_client.get(
            f'/institution/manuals/{self.manual.id}/draft-status/')
        self.assertTrue(has_error(resp))
        # 无手册角色的账号（仅模块页面权限）同样拒绝
        outsider = make_user('out', tenant_id='deptA',
                             perms=[PERM_VIEW, PERM_DOWNLOAD])
        resp = make_client(outsider).get(
            f'/institution/manuals/{self.manual.id}/draft-status/')
        self.assertTrue(has_error(resp))

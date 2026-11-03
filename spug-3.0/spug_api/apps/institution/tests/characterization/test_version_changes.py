# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""版本与发布体验优化的真实行为测试（2026-10-29）

验收清单（《版本与发布 UX 优化任务》）后端部分：
- 首次/部分修改/新增/移除后的整套发布：版本永远包含全部未移除文件，
  变更状态（added/modified/unchanged/removed）由服务端按相邻版本快照
  哈希计算，前端不推断。
- latest_changed_version_no / latest_changed_at / previous_version_no 只读字段。
- 当前版本下载内容哈希与快照一致；历史版本下载不受后续草稿保存影响。
- 发布预检（publish-preview）分组（变更/未修改/新增/移除/受阻）与权限。
- 无角色者不能读取当前/历史版本文件；受阻计划下真实发布仍被拒绝。
"""
import hashlib
import json as _json
import os

from apps.institution import storage
from apps.institution.models import (ManualDraft, ManualFile,
                                     ManualVersion, ManualVersionFile)
from apps.institution.tests.base import (
    PERM_DOWNLOAD, PERM_VIEW, get_data, has_error, make_client, make_user,
    post_json)
from apps.institution.tests.characterization.test_manual_multi_files import (
    DOCX, MultiFileBase)


class VersionChangesTestBase(MultiFileBase):
    """版本对比/发布预检共用夹具：两份文件（负责人=editor）+ 密码 + 助手"""

    def setUp(self):
        super().setUp()
        self.file_a = self._add_file('甲.docx', DOCX + b'-a', owner=self.editor)
        self.file_b = self._add_file('乙.docx', DOCX + b'-b', owner=self.editor)
        self._set_password()

    def _ensure_handoff(self, actor=None):
        """发布前由各文件负责人经真实接口提交编制（发布交接夹具）

        仅用于"预期发布成功"的用例：blocked 用例直接调用 publish/预览
        以走真实阻断路径。提交失败不在此断言（可能是有会话/缺草稿等），
        此时真实发布会自然失败并暴露问题。owner==actor 的文件无需提交。
        """
        actor = actor or self.publisher
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        for row in get_data(resp):
            owner_id = row['assignment']['owner_id']
            if not owner_id or owner_id == actor.id:
                continue
            owner = ManualFile.objects.get(pk=row['id']).owner
            post_json(
                make_client(owner),
                f'/institution/manuals/{self.manual.id}/files/'
                f'{row["id"]}/submit/', {})

    def _publish(self, note='发布'):
        self._ensure_handoff()
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': note})
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _modify_file(self, file_id, content):
        """编辑者保存新草稿内容并退出会话（推进修订号）"""
        resp = self._start_session(file_id=file_id)
        self.assertFalse(has_error(resp), resp.content)
        key = get_data(resp)['session_key']
        revision = get_data(self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/'))['revision']
        resp = self._save(self.editor_client, file_id, key, revision,
                          content=content)
        self.assertFalse(has_error(resp), resp.content)
        self.editor_client.delete(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/session/',
            data=_json.dumps({'session_key': key}),
            content_type='application/json')

    def _download(self, version_id, snapshot_id, client=None):
        resp = (client or self.viewer_client).get(
            f'/institution/manuals/{self.manual.id}/versions/{version_id}/'
            f'files/{snapshot_id}/download/')
        self.assertEqual(resp.status_code, 200)
        return b''.join(resp.streaming_content)


class VersionChangeStatusTests(VersionChangesTestBase):
    """版本文件清单的变更状态计算（服务端权威）"""

    def _version_files(self, version_id, client=None):
        resp = (client or self.viewer_client).get(
            f'/institution/manuals/{self.manual.id}/versions/{version_id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def test_first_publish_contains_all_files_with_added_status(self):
        version = self._publish('首次发布')
        self.assertEqual(version['version_no'], 1)
        self.assertEqual(len(version['files']), 2)
        data = self._version_files(version['id'])
        self.assertIsNone(data['previous_version_no'])
        self.assertEqual(len(data['items']), 2)
        self.assertEqual(data['removed_items'], [])
        for row in data['items']:
            self.assertEqual(row['change_type'], 'added')
            self.assertTrue(row['is_changed_from_previous'])
            self.assertEqual(row['latest_changed_version_no'], 1)
            self.assertIsNotNone(row['latest_changed_at'])

    def test_publish_after_partial_edit_still_contains_all_files(self):
        v1 = self._publish('v1')
        self._modify_file(self.file_a['id'], DOCX + b'-a-new')
        v2 = self._publish('只改甲')
        self.assertEqual(v2['version_no'], 2)
        data = self._version_files(v2['id'])
        # 版本仍包含全部两份文件（整套发布，不缺未修改的乙）
        self.assertEqual(len(data['items']), 2)
        self.assertEqual(data['previous_version_no'], 1)
        names = {r['file_name']: r for r in data['items']}
        self.assertEqual(names['甲.docx']['change_type'], 'modified')
        self.assertEqual(names['乙.docx']['change_type'], 'unchanged')
        self.assertFalse(names['乙.docx']['is_changed_from_previous'])
        # 甲的最近变更= v2；乙沿用，最近变更仍= v1
        self.assertEqual(names['甲.docx']['latest_changed_version_no'], 2)
        self.assertEqual(names['乙.docx']['latest_changed_version_no'], 1)
        v1_data = self._version_files(v1['id'])
        self.assertEqual(
            {r['file_name']: r['change_type'] for r in v1_data['items']},
            {'甲.docx': 'added', '乙.docx': 'added'})

    def test_added_file_status_in_later_version(self):
        v1 = self._publish('v1')
        self._add_file('丙.docx', DOCX + b'-c')
        v2 = self._publish('新增丙')
        data = self._version_files(v2['id'])
        names = {r['file_name']: r for r in data['items']}
        self.assertEqual(len(data['items']), 3)
        self.assertEqual(names['丙.docx']['change_type'], 'added')
        self.assertEqual(names['丙.docx']['latest_changed_version_no'], 2)
        self.assertEqual(names['甲.docx']['change_type'], 'unchanged')
        self.assertEqual(names['甲.docx']['latest_changed_version_no'], 1)
        self.assertIsNotNone(names['甲.docx']['latest_changed_at'])
        self.assertIsNotNone(self._version_files(v1['id']))

    def test_removed_file_listed_not_hidden(self):
        self._publish('v1')
        v1 = ManualVersion.objects.get(manual=self.manual, version_no=1)
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/'
                         f'{self.file_a["id"]}/remove/', {})
        self.assertFalse(has_error(resp), resp.content)
        v2 = self._publish('v2 移除甲')
        data = self._version_files(v2['id'])
        # 新版本快照只含乙，但移除结果必须显式可见
        self.assertEqual([r['file_name'] for r in data['items']], ['乙.docx'])
        self.assertEqual(data['previous_version_no'], 1)
        removed = data['removed_items']
        self.assertEqual(len(removed), 1)
        row = removed[0]
        self.assertEqual(row['name'], '甲.docx')
        self.assertEqual(row['change_type'], 'removed')
        self.assertEqual(row['previous_version_id'], v1.id)
        v1_snap = v1.files.get(manual_file_id=self.file_a['id'])
        self.assertEqual(row['previous_snapshot_id'], v1_snap.id)
        self.assertEqual(row['file_hash'], v1_snap.file_hash)
        # 历史版本清单不受影响：v1 仍完整展示两份文件
        v1_data = self._version_files(v1.id)
        self.assertEqual(len(v1_data['items']), 2)
        self.assertEqual(v1_data['removed_items'], [])

    def test_latest_changed_walks_version_chain(self):
        self._publish('v1')
        self._modify_file(self.file_a['id'], DOCX + b'-a2')
        self._publish('v2 改甲')
        self._modify_file(self.file_b['id'], DOCX + b'-b2')
        v3 = self._publish('v3 改乙')
        data = self._version_files(v3['id'])
        names = {r['file_name']: r for r in data['items']}
        self.assertEqual(names['甲.docx']['latest_changed_version_no'], 2)
        self.assertEqual(names['乙.docx']['latest_changed_version_no'], 3)
        # v2 清单里乙的最近变更仍是 v1
        v2 = ManualVersion.objects.get(manual=self.manual, version_no=2)
        v2_names = {r['file_name']: r
                    for r in self._version_files(v2.id)['items']}
        self.assertEqual(v2_names['乙.docx']['latest_changed_version_no'], 1)

    def test_download_bytes_match_snapshot_hash(self):
        self._modify_file(self.file_a['id'], DOCX + b'-a-new')
        v2 = self._publish('v2')
        data = self._version_files(v2['id'])
        row = next(r for r in data['items'] if r['file_name'] == '甲.docx')
        content = self._download(v2['id'], row['id'])
        self.assertEqual(
            hashlib.sha256(content).hexdigest(), row['file_hash'])

    def test_history_download_unaffected_by_later_draft_saves(self):
        v1 = self._publish('v1')
        data = self._version_files(v1['id'])
        row = next(r for r in data['items'] if r['file_name'] == '甲.docx')
        v1_bytes = self._download(v1['id'], row['id'])
        self.assertEqual(
            hashlib.sha256(v1_bytes).hexdigest(), row['file_hash'])
        # 后续继续编辑草稿（含推进修订号）不得影响 v1 下载内容
        self._modify_file(self.file_a['id'], DOCX + b'-a-changed-later')
        content = self._download(v1['id'], row['id'])
        self.assertEqual(content, v1_bytes)

    def test_outsider_cannot_read_version_files_or_snapshots(self):
        v1 = self._publish('v1')
        outsider = make_user('out', tenant_id='deptA', perms=[PERM_VIEW])
        client = make_client(outsider)
        resp = client.get(
            f'/institution/manuals/{self.manual.id}/versions/{v1["id"]}/files/')
        self.assertTrue(has_error(resp))
        snapshot_id = ManualVersionFile.objects.filter(
            version_id=v1['id']).first().id
        resp = client.get(
            f'/institution/manuals/{self.manual.id}/versions/{v1["id"]}/'
            f'files/{snapshot_id}/download/')
        self.assertTrue(has_error(resp))
        # 仅下载权限、无手册角色者同样拒绝
        downloader = make_user('dl', tenant_id='deptA',
                               perms=[PERM_VIEW, PERM_DOWNLOAD])
        resp = make_client(downloader).get(
            f'/institution/manuals/{self.manual.id}/versions/{v1["id"]}/'
            f'files/{snapshot_id}/download/')
        self.assertTrue(has_error(resp))

    def test_removed_file_entry_keeps_original_and_can_reenter(self):
        """移除文件的条目与 ID 保留（供回退重新纳入），不物理删除"""
        self._publish('v1')
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/'
                         f'{self.file_a["id"]}/remove/', {})
        self.assertFalse(has_error(resp), resp.content)
        entry = ManualFile.objects.get(pk=self.file_a['id'])
        self.assertTrue(entry.is_removed)
        self.assertIsNotNone(entry.removed_at)


class PublishPreviewTests(VersionChangesTestBase):
    """发布前预检：分组发布计划与权限"""

    def _preview(self, client=None):
        resp = (client or self.publisher_client).get(
            f'/institution/manuals/{self.manual.id}/publish-preview/')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def test_preview_before_any_version_all_added(self):
        # 首发交接：负责人（editor）先行提交编制，预览才可发布
        self._ensure_handoff()
        plan = self._preview()
        self.assertIsNone(plan['current_version_no'])
        self.assertEqual(len(plan['added']), 2)
        self.assertEqual(plan['changed'], [])
        self.assertEqual(plan['unchanged'], [])
        self.assertEqual(plan['removed'], [])
        self.assertEqual(plan['blocked'], [])
        self.assertEqual(plan['blocker_summary'], {})
        self.assertTrue(plan['can_publish'])
        # 行内交接字段：发布人非负责人时该文件必须已提交
        for row in plan['added']:
            self.assertEqual(row['owner_id'], self.editor.id)
            self.assertEqual(row['submission']['state'], 'submitted')
            self.assertFalse(row['publisher_is_owner'])
            self.assertTrue(row['submission_required'])

    def test_preview_groups_change_unchanged_added_removed(self):
        self._publish('v1')
        self._modify_file(self.file_a['id'], DOCX + b'-a-new')
        self._add_file('丙.docx', DOCX + b'-c')
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/'
                         f'{self.file_b["id"]}/remove/', {})
        self.assertFalse(has_error(resp), resp.content)
        self._ensure_handoff()
        plan = self._preview()
        self.assertEqual(plan['current_version_no'], 1)
        self.assertEqual([r['name'] for r in plan['changed']], ['甲.docx'])
        self.assertEqual(plan['changed'][0]['change_type'], 'modified')
        self.assertEqual([r['name'] for r in plan['added']], ['丙.docx'])
        self.assertEqual([r['name'] for r in plan['removed']], ['乙.docx'])
        self.assertEqual(plan['removed'][0]['from_version_no'], 1)
        self.assertEqual(plan['unchanged'], [])
        self.assertEqual(plan['blocked'], [])
        self.assertTrue(plan['can_publish'])

    def test_preview_unchanged_group_after_republish_same_content(self):
        self._publish('v1')
        plan = self._preview()
        # 未做任何编辑：两份文件都进入 unchanged（继续纳入新版本）
        self.assertEqual(
            sorted(r['name'] for r in plan['unchanged']), ['乙.docx', '甲.docx'])
        for row in plan['unchanged']:
            self.assertEqual(row['change_type'], 'unchanged')
            self.assertEqual(row['draft_hash'], row['current_hash'])

    def test_preview_blocked_groups_and_publish_rejected(self):
        self._publish('v1')
        # 乙无草稿、甲缺物理文件、丙会话占用
        ManualDraft.objects.get(file_id=self.file_b['id']).delete()
        draft_a = ManualDraft.objects.get(file_id=self.file_a['id'])
        os.remove(storage.resolve_absolute_path(draft_a.file_path))
        self._add_file('丙.docx', DOCX + b'-c', owner=self.editor)
        c_file = ManualFile.objects.get(
            manual=self.manual, display_name='丙.docx')
        resp = self._start_session(file_id=c_file.id)
        self.assertFalse(has_error(resp), resp.content)
        plan = self._preview()
        reasons = {r['name']: r['reason'] for r in plan['blocked']}
        self.assertEqual(reasons['丙.docx'], 'session_busy')
        self.assertEqual(reasons['乙.docx'], 'no_draft')
        self.assertEqual(reasons['甲.docx'], 'draft_missing')
        self.assertFalse(plan['can_publish'])
        # 预检受阻不是放行凭证：真实发布仍被服务端拒绝，版本不产生
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': '受阻仍尝试发布'})
        self.assertTrue(has_error(resp))
        self.assertFalse(
            ManualVersion.objects.filter(
                manual=self.manual, version_no=2).exists())

    def test_preview_requires_publish_role(self):
        resp = self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/publish-preview/')
        self.assertTrue(has_error(resp))
        resp = self.viewer_client.get(
            f'/institution/manuals/{self.manual.id}/publish-preview/')
        self.assertTrue(has_error(resp))

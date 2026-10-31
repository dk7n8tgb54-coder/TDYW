# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""修订状态（revision_open）与发布轮次的真实行为测试（2026-10-30）

验收口径（"发布后修订状态"任务，全部经 test client 真实请求链路）：
- 首次上传直接发布：上传即建草稿工作副本，核对后首次发布。
- 发布成功结束本轮修订：工作副本保留（记录与物理文件均在），但不再
  以"未发布草稿"名义出现（consistent/synced），提交编制记录随发布
  被消费（回到未提交），草稿 base_version 指向新版本、初始来源引用解除。
- 发布失败（快照制作失败/受阻）不结束修订：修订状态、草稿、旧生效版本
  全部保持原状。
- 「开始修订」是真实状态动作：开启修订并原样复用现有工作副本（不复制
  新快照）；已有进行中的修订幂等返回（继续编辑，绝不覆盖）；工作副本
  缺失/损坏/与生效基线不一致时需明确确认后从当前生效快照修复，绝不
  静默改用初始来源。
- 无内容/结构变化拒绝重复发布（首次发布除外）；仅开启修订不构成变化；
  结构变化（改名/排序/移除）无需内容修改即可发布。
- 存量数据保守回填：只有"当前生效快照哈希一致 + 无活跃会话"的文件
  才翻转修订已结束，其余一律保持进行中，不丢失未发布修改或编辑会话。
- 批量分工：逐文件校验归属，全成功或全失败；改派/清空负责人后旧负责人
  的提交编制不再显示为有效提交；发布结束修订后提交不再误报为下一轮交接。
"""
import importlib
import json
import os
from unittest.mock import patch

from django.apps import apps as real_apps
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.institution import storage
from apps.institution.models import (Manual, ManualDraft, ManualEditSession,
                                     ManualFile, ManualOperationLog,
                                     ManualVersion)
from apps.institution.tests.base import (get_data, has_error, make_grant,
                                         post_json)
from apps.institution.tests.characterization.test_manual_multi_files import (
    DOCX)
from apps.institution.tests.characterization.test_version_changes import (
    VersionChangesTestBase)

REVISION_START = '/institution/manuals/{id}/files/{fid}/revision/start/'
BATCH_ASSIGNMENT = '/institution/manuals/{id}/files/batch-assignment/'


class PublishRoundEndTests(VersionChangesTestBase):
    """发布结束修订轮：工作副本保留、状态复位、提交消费、引用正确"""

    def _files_rows(self):
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        return {x['id']: x for x in get_data(resp)}

    def test_first_publish_ends_round_and_keeps_working_copies(self):
        """首次上传直接发布：发布后修订结束、工作副本保留、引用正确"""
        # 上传即建草稿（修订进行中），核对后直接首发
        for row in self._files_rows().values():
            self.assertTrue(row['revision_open'])
            self.assertIsNotNone(row['draft'])
        version = self._publish('首次发布')
        rows = self._files_rows()
        for file_id, row in rows.items():
            self.assertFalse(row['revision_open'])
            draft = row['draft']
            self.assertIsNotNone(draft)
            self.assertTrue(draft['file_hash'])
            self.assertEqual(draft['base_version_no'], 1)
            self.assertIsNone(draft['source_original_id'])
            self.assertEqual(row['submission']['state'], 'none')
            # 工作副本物理文件仍在（发布不删除工作副本）
            self.assertTrue(os.path.exists(storage.resolve_absolute_path(
                ManualDraft.objects.get(file_id=file_id).file_path)))
        self.assertEqual(version['files'].__len__(), 2)
        # 状态摘要：已生效、无未发布修改、无修订进行中
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/draft-status/')
        summary = get_data(resp)['summary']
        self.assertTrue(summary['consistent'])
        self.assertEqual(summary['revising'], 0)
        self.assertFalse(summary['has_pending_changes'])

    def test_publish_failure_keeps_revision_drafts_and_old_version(self):
        """快照制作失败：修订状态、草稿、旧生效版本全部保持原状"""
        self._publish('v1')
        self._modify_file(self.file_a['id'], DOCX + b'-a-new')
        rows_before = self._files_rows()
        with patch('apps.institution.services.shutil.copyfile',
                   side_effect=OSError('disk error')):
            resp = post_json(self.publisher_client,
                             f'/institution/manuals/{self.manual.id}/publish/',
                             {'change_note': '应失败'})
        self.assertTrue(has_error(resp))
        self.assertFalse(ManualVersion.objects.filter(
            manual=self.manual, version_no=2).exists())
        rows_after = self._files_rows()
        for file_id, row in rows_after.items():
            self.assertEqual(row['revision_open'],
                             rows_before[file_id]['revision_open'])
            self.assertEqual(row['draft'], rows_before[file_id]['draft'])
        self.assertTrue(rows_after[self.file_a['id']]['revision_open'])

    def test_republish_without_changes_rejected(self):
        """无内容/结构变化：预检不可发布、真实发布拒绝，不产生新版本"""
        self._publish('v1')
        resp = self.publisher_client.get(
            f'/institution/manuals/{self.manual.id}/publish-preview/')
        plan = get_data(resp)
        self.assertFalse(plan['can_publish'])
        self.assertFalse(plan['has_changes'])
        self.assertFalse(plan['first_publish'])
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': '重复发布'})
        self.assertTrue(has_error(resp))
        self.assertIn('无需重复发布', resp.json()['error'])
        self.assertFalse(ManualVersion.objects.filter(
            manual=self.manual, version_no=2).exists())

    def test_open_revision_alone_is_not_publishable(self):
        """仅开始修订（无内容变化）：修订进行中但不构成发布理由"""
        self._publish('v1')
        resp = post_json(self.editor_client, REVISION_START.format(
            id=self.manual.id, fid=self.file_a['id']), {})
        self.assertFalse(has_error(resp), resp.content)
        self.assertFalse(has_error(resp), resp.content)
        self.assertTrue(get_data(resp)['started'])
        resp = self.publisher_client.get(
            f'/institution/manuals/{self.manual.id}/publish-preview/')
        plan = get_data(resp)
        self.assertFalse(plan['can_publish'])
        self.assertFalse(plan['has_changes'])
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': '仅开启修订'})
        self.assertTrue(has_error(resp))
        # 修订状态在摘要中独立呈现，不冒充一致也不冒充待发布变化
        status = get_data(self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/draft-status/'))
        self.assertEqual(status['summary']['revising'], 1)
        self.assertFalse(status['summary']['consistent'])
        self.assertFalse(status['summary']['has_pending_changes'])
        self.assertTrue(status['items'][0]['revision_open'])

    def test_content_change_after_start_publishes_and_ends_round(self):
        """修订中修改一份文件：整套发布仍含全部文件，发布结束全部修订"""
        self._publish('v1')
        post_json(self.editor_client, REVISION_START.format(
            id=self.manual.id, fid=self.file_a['id']), {})
        self._modify_file(self.file_a['id'], DOCX + b'-a-v2')
        version = self._publish('v2 只改甲')
        self.assertEqual(version['version_no'], 2)
        self.assertEqual(len(version['files']), 2)
        snap_b = next(s for s in version['files']
                      if s['manual_file_id'] == self.file_b['id'])
        self.assertEqual(snap_b['file_hash'],
                         ManualDraft.objects.get(
                             file_id=self.file_b['id']).file_hash)
        rows = self._files_rows()
        self.assertFalse(rows[self.file_a['id']]['revision_open'])
        self.assertFalse(rows[self.file_b['id']]['revision_open'])
        self.assertEqual(rows[self.file_a['id']]['draft']['base_version_no'], 2)

    def test_structural_change_publishes_without_content_edit(self):
        """改名（无内容变化）是待发布变化，允许发布"""
        self._publish('v1')
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/'
                         f'{self.file_a["id"]}/rename/',
                         {'name': '甲-新名.docx'})
        self.assertFalse(has_error(resp), resp.content)
        version = self._publish('改名发布')
        self.assertEqual(version['version_no'], 2)
        names = {s['manual_file_id']: s['file_name'] for s in version['files']}
        self.assertEqual(names[self.file_a['id']], '甲-新名.docx')

    def test_reorder_and_remove_publish_without_content_edit(self):
        """排序与移除属于结构变化，无内容修改也可发布"""
        self._publish('v1')
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/'
                         f'{self.file_b["id"]}/move/', {'position': 1})
        self.assertFalse(has_error(resp), resp.content)
        version = self._publish('排序发布')
        self.assertEqual([s['file_name'] for s in version['files']],
                         ['乙.docx', '甲.docx'])
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/'
                         f'{self.file_b["id"]}/remove/', {})
        self.assertFalse(has_error(resp), resp.content)
        version = self._publish('移除乙')
        self.assertEqual([s['file_name'] for s in version['files']],
                         ['甲.docx'])

    def test_deprecate_reopens_revision_and_republish_first_semantics(self):
        """废止后全部文件回到修订进行中；重新发布按首次发布语义放行"""
        self._publish('v1')
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/deprecate/', {})
        self.assertFalse(has_error(resp), resp.content)
        for row in self._files_rows().values():
            self.assertTrue(row['revision_open'])
        version = self._publish('重新发布')
        self.assertEqual(version['version_no'], 2)
        for row in self._files_rows().values():
            self.assertFalse(row['revision_open'])


class StartRevisionTests(VersionChangesTestBase):
    """开始修订：复用工作副本 / 幂等 / 修复路径"""

    def _start(self, fid, confirm_repair=False, client=None):
        return post_json(
            client or self.editor_client,
            REVISION_START.format(id=self.manual.id, fid=fid),
            {'confirm_repair': confirm_repair} if confirm_repair else {})

    def test_start_reuses_working_copy_without_new_snapshot(self):
        """开始修订原样启用现有工作副本：修订号/哈希/路径不变，无新版本"""
        self._publish('v1')
        draft_before = ManualDraft.objects.get(file_id=self.file_a['id'])
        resp = self._start(self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertTrue(data['started'])
        self.assertFalse(data['needs_repair'])
        draft_after = ManualDraft.objects.get(file_id=self.file_a['id'])
        self.assertEqual(draft_after.revision, draft_before.revision)
        self.assertEqual(draft_after.file_hash, draft_before.file_hash)
        self.assertEqual(draft_after.file_path, draft_before.file_path)
        self.assertEqual(ManualVersion.objects.filter(
            manual=self.manual).count(), 1)
        row = next(x for x in get_data(self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/files/'))
            if x['id'] == self.file_a['id'])
        self.assertTrue(row['revision_open'])
        # 操作记录留下真实的开始修订动作
        self.assertTrue(ManualOperationLog.objects.filter(
            manual=self.manual, file_id=self.file_a['id'],
            action='revision_start').exists())

    def test_start_is_idempotent_when_revision_already_open(self):
        """已有进行中的修订：返回 resumed 直接复用，绝不覆盖工作副本"""
        self._publish('v1')
        self._modify_file(self.file_a['id'], DOCX + b'-a-new')
        draft_before = ManualDraft.objects.get(file_id=self.file_a['id'])
        resp = self._start(self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertTrue(data['resumed'])
        self.assertFalse(data['needs_repair'])
        draft_after = ManualDraft.objects.get(file_id=self.file_a['id'])
        self.assertEqual(draft_after.revision, draft_before.revision)
        self.assertEqual(draft_after.file_hash, draft_before.file_hash)

    def test_start_repair_missing_draft_from_current_version(self):
        """工作副本记录缺失：needs_repair 明确提示，确认后从生效快照修复"""
        self._publish('v1')
        snap_hash = ManualVersion.objects.get(
            manual=self.manual, version_no=1).files.get(
            manual_file_id=self.file_a['id']).file_hash
        ManualDraft.objects.get(file_id=self.file_a['id']).delete()
        resp = self._start(self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertTrue(data['needs_repair'])
        self.assertEqual(data['reason'], 'draft_missing')
        self.assertEqual(data['draft_recovery']['source'], 'current_version')
        self.assertIn('v1', data['message'])
        # 未确认前不产生任何草稿
        self.assertFalse(ManualDraft.objects.filter(
            file_id=self.file_a['id']).exists())
        # 确认修复：草稿自快照重建（哈希=快照），修订开启
        resp = self._start(self.file_a['id'], confirm_repair=True)
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertTrue(data['repaired'])
        draft = ManualDraft.objects.get(file_id=self.file_a['id'])
        self.assertEqual(draft.file_hash, snap_hash)
        # 草稿行已被删除：修复按新草稿从修订号 1 重新起算
        self.assertEqual(draft.revision, 1)
        self.assertEqual(draft.base_version.version_no, 1)
        self.assertIsNone(draft.source_original)
        self.assertTrue(os.path.exists(storage.resolve_absolute_path(
            draft.file_path)))
        self.assertTrue(ManualOperationLog.objects.filter(
            manual=self.manual, file_id=self.file_a['id'],
            action='repair_draft').exists())

    def test_start_repair_corrupt_draft_file(self):
        """工作副本物理文件损坏（缺失）：确认后从生效快照修复"""
        self._publish('v1')
        draft = ManualDraft.objects.get(file_id=self.file_a['id'])
        os.remove(storage.resolve_absolute_path(draft.file_path))
        resp = self._start(self.file_a['id'])
        data = get_data(resp)
        self.assertTrue(data['needs_repair'])
        self.assertEqual(data['reason'], 'draft_corrupt')
        resp = self._start(self.file_a['id'], confirm_repair=True)
        self.assertFalse(has_error(resp), resp.content)
        self.assertTrue(get_data(resp)['repaired'])
        snap_hash = ManualVersion.objects.get(
            manual=self.manual, version_no=1).files.get(
            manual_file_id=self.file_a['id']).file_hash
        self.assertEqual(
            ManualDraft.objects.get(file_id=self.file_a['id']).file_hash,
            snap_hash)

    def test_start_repair_baseline_mismatch_never_uses_original(self):
        """修订已结束但工作副本与基线不一致（异常态）：确认后以生效快照
        修复，绝不静默改用初始来源原稿"""
        # 先让生效快照与初始原稿内容不同（发布前修改过一轮）
        self._modify_file(self.file_a['id'], DOCX + b'-a-v1')
        self._publish('v1')
        # 制造异常态：草稿内容再次变化（修订被保存置开启），随后状态被
        # 外力关闭——真实流程不会出现，仅验证开始修订的防御与修复来源
        self._modify_file(self.file_a['id'], DOCX + b'-unpublished-work')
        ManualFile.objects.filter(pk=self.file_a['id']).update(
            revision_open=False)
        resp = self._start(self.file_a['id'])
        data = get_data(resp)
        self.assertTrue(data['needs_repair'])
        self.assertEqual(data['reason'], 'baseline_mismatch')
        self.assertIn('不一致', data['message'])
        # 未确认不覆盖：工作副本仍是未发布修改的内容
        modified_hash = ManualDraft.objects.get(
            file_id=self.file_a['id']).file_hash
        resp = self._start(self.file_a['id'], confirm_repair=True)
        self.assertFalse(has_error(resp), resp.content)
        draft = ManualDraft.objects.get(file_id=self.file_a['id'])
        snap_hash = ManualVersion.objects.get(
            manual=self.manual, version_no=1).files.get(
            manual_file_id=self.file_a['id']).file_hash
        self.assertEqual(draft.file_hash, snap_hash)
        self.assertNotEqual(draft.file_hash, modified_hash)
        # 修复来源是生效快照而不是初始原稿：初始原稿内容与快照不同
        original = draft.file.originals.order_by('id').first()
        self.assertIsNotNone(original)
        self.assertNotEqual(original.file_hash, snap_hash)
        self.assertNotEqual(draft.file_hash, original.file_hash)
        self.assertIsNone(draft.source_original)

    def test_repair_revokes_active_sessions(self):
        """修复替换工作副本前使该文件编辑会话失效，旧会话不能再保存"""
        self._publish('v1')
        draft = ManualDraft.objects.get(file_id=self.file_a['id'])
        os.remove(storage.resolve_absolute_path(draft.file_path))
        resp = self._start_session(file_id=self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        session_key = get_data(resp)['session_key']
        resp = self._start(self.file_a['id'], confirm_repair=True)
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(ManualEditSession.objects.filter(
            file_id=self.file_a['id'], revoked_at__isnull=True).count(), 0)
        revision = ManualDraft.objects.get(file_id=self.file_a['id']).revision
        resp = self.editor_client.post(
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.file_a["id"]}/draft/save/',
            {'file': SimpleUploadedFile('late.docx', DOCX),
             'session_key': session_key, 'revision': revision})
        self.assertTrue(has_error(resp))

    def test_start_revision_requires_edit_role(self):
        """开始修订是编制域动作：发布者/仅查看者被拒绝"""
        self._publish('v1')
        for client in (self.publisher_client, self.viewer_client):
            resp = self._start(self.file_a['id'], client=client)
            self.assertTrue(has_error(resp))

    def test_start_revision_rejected_for_archived_manual(self):
        self._publish('v1')
        self.manual.status = 'archived'
        self.manual.save(update_fields=['status'])
        resp = self._start(self.file_a['id'])
        self.assertTrue(has_error(resp))


class BatchAssignmentTests(VersionChangesTestBase):
    """批量分工：原子性、权限、逐文件归属校验、提交状态联动"""

    def _batch(self, file_ids, owner_id, note='', client=None):
        return post_json(
            client or self.manager_client,
            BATCH_ASSIGNMENT.format(id=self.manual.id),
            {'file_ids': file_ids, 'owner_id': owner_id, 'note': note})

    def _rows(self):
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        return {x['id']: x for x in get_data(resp)}

    def test_batch_assign_updates_all_selected_files(self):
        resp = self._batch([self.file_a['id'], self.file_b['id']],
                           self.editor.id, note='共同编制')
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(data['count'], 2)
        rows = self._rows()
        for fid in (self.file_a['id'], self.file_b['id']):
            self.assertEqual(rows[fid]['assignment']['owner_id'], self.editor.id)
            self.assertEqual(rows[fid]['assignment']['note'], '共同编制')
        # 每份文件一条操作记录（batch 标记）
        logs = ManualOperationLog.objects.filter(
            manual=self.manual, action='file_assign')
        self.assertEqual(logs.count(), 2)
        self.assertTrue(all(json.loads(l.detail).get('batch')
                            for l in logs))

    def test_batch_clear_owner(self):
        self._batch([self.file_a['id'], self.file_b['id']], self.editor.id)
        resp = self._batch([self.file_a['id'], self.file_b['id']], None)
        self.assertFalse(has_error(resp), resp.content)
        rows = self._rows()
        for fid in (self.file_a['id'], self.file_b['id']):
            self.assertIsNone(rows[fid]['assignment']['owner_id'])
            self.assertEqual(rows[fid]['assignment']['owner_name'], '')

    def test_batch_atomic_when_foreign_file_included(self):
        """任一文件不属于该制度：整批拒绝，已选文件一个都不改"""
        other = Manual.objects.create(
            name='别家手册', code='BM-FGN',
            org_type=Manual.OWNER_DEPARTMENT, org_name='别的部门',
            owner=self.manager, tenant_id='deptA')
        make_grant(other, self.editor, can_edit=True)
        upload = SimpleUploadedFile('别家.docx', DOCX + b'-foreign')
        resp = self.manager_client.post(
            f'/institution/manuals/{other.id}/files/create/',
            {'file': upload})
        self.assertFalse(has_error(resp), resp.content)
        foreign_id = get_data(resp)['id']
        resp = self._batch([self.file_a['id'], foreign_id],
                           self.editor.id, note='x')
        self.assertTrue(has_error(resp))
        rows = self._rows()
        # 整批拒绝：file_a 保持创建时指派的负责人与分工说明，一字不改
        self.assertEqual(rows[self.file_a['id']]['assignment']['owner_id'],
                         self.editor.id)
        self.assertEqual(rows[self.file_a['id']]['assignment']['note'], '')
        # 外部手册的文件同样未被改动
        resp = self.manager_client.get(
            f'/institution/manuals/{other.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        self.assertIsNone(get_data(resp)[0]['assignment']['owner_id'])

    def test_batch_rejects_empty_or_invalid_ids(self):
        for bad in ([], ['abc'], [self.file_a['id'], 'x']):
            resp = self._batch(bad, self.editor.id)
            self.assertTrue(has_error(resp))

    def test_batch_note_length_and_owner_validation(self):
        resp = self._batch([self.file_a['id']], self.editor.id, note='x' * 501)
        self.assertTrue(has_error(resp))
        resp = self._batch([self.file_a['id']], 999999)
        self.assertTrue(has_error(resp))

    def test_batch_requires_assignment_permission(self):
        """批量分工与单文件同口径：发布者/仅查看者拒绝"""
        for client in (self.publisher_client, self.viewer_client):
            resp = self._batch([self.file_a['id']], self.editor.id,
                               client=client)
            self.assertTrue(has_error(resp))

    def test_batch_reassignment_resets_submission(self):
        """改派后旧负责人的提交不再显示为有效提交（批量路径）"""
        self._batch([self.file_a['id']], self.editor.id)
        resp = post_json(self.editor_client,
                         f'/institution/manuals/{self.manual.id}/files/'
                         f'{self.file_a["id"]}/submit/', {})
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(
            self._rows()[self.file_a['id']]['submission']['state'],
            'submitted')
        resp = self._batch([self.file_a['id']], self.editor2.id, note='移交')
        self.assertFalse(has_error(resp), resp.content)
        row = self._rows()[self.file_a['id']]
        self.assertEqual(row['assignment']['owner_id'], self.editor2.id)
        self.assertEqual(row['submission']['state'], 'none')
        # 历史操作记录保留：提交与改派记录都在
        actions = set(ManualOperationLog.objects.filter(
            manual=self.manual, file_id=self.file_a['id'])
            .values_list('action', flat=True))
        self.assertLessEqual({'file_submit', 'file_assign'}, actions)


class SubmissionSemanticsTests(VersionChangesTestBase):
    """提交编制与修订轮/改派的联动（单文件接口路径）"""

    def _submit(self, fid, client=None):
        return post_json(client or self.editor_client,
                         f'/institution/manuals/{self.manual.id}/files/'
                         f'{fid}/submit/', {})

    def _assign(self, fid, owner_id, note=''):
        return post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/'
                         f'{fid}/assignment/', {'owner_id': owner_id,
                                                'note': note})

    def _rows(self):
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        return {x['id']: x for x in get_data(resp)}

    def test_reassign_resets_submission_same_owner_keeps(self):
        data = self._add_file('分工.docx')
        resp = self._assign(data['id'], self.editor.id, note='初分工')
        self.assertFalse(has_error(resp), resp.content)
        resp = self._submit(data['id'])
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(
            self._rows()[data['id']]['submission']['state'], 'submitted')
        # 负责人未变、仅修改说明：提交保留
        resp = self._assign(data['id'], self.editor.id, note='补充说明')
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(
            self._rows()[data['id']]['submission']['state'], 'submitted')
        # 改派：提交回到未提交
        resp = self._assign(data['id'], self.editor2.id, note='改派')
        self.assertFalse(has_error(resp), resp.content)
        row = self._rows()[data['id']]
        self.assertEqual(row['submission']['state'], 'none')

    def test_clear_owner_resets_submission(self):
        data = self._add_file('清空.docx')
        self._assign(data['id'], self.editor.id)
        resp = self._submit(data['id'])
        self.assertFalse(has_error(resp), resp.content)
        resp = self._assign(data['id'], None)
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(
            self._rows()[data['id']]['submission']['state'], 'none')

    def test_publish_consumes_submission_not_carried_to_next_round(self):
        """发布结束修订轮后提交被消费，不得误显示为下一轮的有效交接"""
        self._set_password()
        resp = self._submit(self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(
            self._rows()[self.file_a['id']]['submission']['state'],
            'submitted')
        self._publish('v1')
        row = self._rows()[self.file_a['id']]
        self.assertEqual(row['submission']['state'], 'none')
        self.assertIsNone(row['submission']['submitted_at'])
        # 新一轮修订中重新提交再次有效
        self._modify_file(self.file_a['id'], DOCX + b'-a-round2')
        resp = self._submit(self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(
            self._rows()[self.file_a['id']]['submission']['state'],
            'submitted')


class RevisionBackfillMigrationTests(VersionChangesTestBase):
    """迁移 0006 保守回填规则的直接验证

    测试库已应用 0006（AddField default=True）。这里用 ORM 把文件置回
    "修订进行中"，再以真实 apps 注册表调用迁移模块的回填函数，验证
    只有「当前生效快照哈希一致 + 无活跃会话」的文件被翻转为已结束。
    """

    def _run_backfill(self):
        module = importlib.import_module(
            'apps.institution.migrations.0006_revision_open')
        module._backfill_revision_open(real_apps, None)

    def test_backfill_only_closes_matching_published_files(self):
        self._publish('v1')
        ManualFile.objects.update(revision_open=True)
        # 文件乙：制造哈希不一致（保守保持进行中）
        draft_b = ManualDraft.objects.get(file_id=self.file_b['id'])
        draft_b.file_hash = 'diff' + '0' * 60
        draft_b.save(update_fields=['file_hash'])
        self._run_backfill()
        self.assertFalse(ManualFile.objects.get(
            pk=self.file_a['id']).revision_open)
        self.assertTrue(ManualFile.objects.get(
            pk=self.file_b['id']).revision_open)

    def test_backfill_keeps_files_with_active_sessions(self):
        self._publish('v1')
        ManualFile.objects.update(revision_open=True)
        self._set_password()
        resp = self._start_session(file_id=self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        self._run_backfill()
        # 有活跃会话（可能携带未同步内容）：保守保持修订进行中
        self.assertTrue(ManualFile.objects.get(
            pk=self.file_a['id']).revision_open)
        self.assertFalse(ManualFile.objects.get(
            pk=self.file_b['id']).revision_open)

    def test_backfill_keeps_files_absent_from_current_version(self):
        """当前版本不含的文件（后加入）不翻转，保持进行中"""
        self._publish('v1')
        new_file = self._add_file('丙.docx', DOCX + b'-c')
        ManualFile.objects.update(revision_open=True)
        self._run_backfill()
        self.assertTrue(ManualFile.objects.get(pk=new_file['id']).revision_open)
        self.assertFalse(ManualFile.objects.get(
            pk=self.file_a['id']).revision_open)

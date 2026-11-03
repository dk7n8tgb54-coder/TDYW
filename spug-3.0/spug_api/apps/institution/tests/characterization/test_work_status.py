# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度列表工作状态（work_status）的真实行为测试（2026-10-29）

验收口径（列表页"打开即知下一步"，全部经 test client 真实请求链路）：
- 列表接口按手册下发 work_status，状态由服务端按 草稿哈希 vs 生效版
  快照哈希 与 文件新增/移除/改名/排序 计算，与 draft-status 整套摘要
  同口径（一致性钉死），前端不得以修订号/"有草稿"推断。
- 状态覆盖：已同步 / 待首次发布 / 待发布变化 / 编辑中（会话占用，含
  未完成同步）/ 缺少草稿 / 状态无法确认（草稿文件缺失）/ 未上传文件。
- 权限：编制/发布角色与管理者可见；仅查看角色 work_status=None
  （不得经列表泄漏草稿信息）。
- 文件变更记录：已移除文件仍可经版本快照/文件历史查阅；
  快照按保留策略清理后 version-history 行带 is_cleaned。
"""
import json
import os

from django.utils import timezone

from apps.institution import storage
from apps.institution.models import Manual, ManualDraft, ManualVersionFile
from apps.institution.tests.base import get_data, has_error, post_json
from apps.institution.tests.characterization.test_manual_multi_files import (
    DOCX)
from apps.institution.tests.characterization.test_version_changes import (
    VersionChangesTestBase)


class ManualListWorkStatusTests(VersionChangesTestBase):
    """列表接口 work_status：状态判定 / 与 draft-status 同口径 / 权限"""

    def _row(self, client=None):
        """列表中本手册的行数据"""
        resp = (client or self.manager_client).get('/institution/manuals/')
        self.assertFalse(has_error(resp), resp.content)
        items = get_data(resp)['items']
        return next(x for x in items if x['id'] == self.manual.id)

    def _ws(self, client=None):
        row = self._row(client)
        self.assertIsNotNone(row['work_status'])
        return row['work_status']

    # VersionChangesTestBase 已就绪 手册+两份文件+编辑密码（edit-pass-1）

    # ------------------------------------------------------------------
    # 状态判定

    def test_no_files_manual_reports_no_files(self):
        """未上传任何文件：no_files，不冒充已同步"""
        manual = self._make_bare_manual()
        resp = self.manager_client.get('/institution/manuals/')
        self.assertFalse(has_error(resp), resp.content)
        row = next(x for x in get_data(resp)['items']
                   if x['id'] == manual.id)
        self.assertEqual(row['work_status']['status'], 'no_files')
        self.assertEqual(row['work_status']['total_files'], 0)

    def test_awaiting_first_publish_before_any_version(self):
        """从未发布：awaiting_first_publish（即使草稿齐备）"""
        ws = self._ws()
        self.assertEqual(ws['status'], 'awaiting_first_publish')
        self.assertFalse(ws['has_current_version'])
        self.assertIsNone(ws['current_version_no'])
        self.assertEqual(ws['awaiting_first_publish'], 2)
        self.assertTrue(ws['has_pending_changes'])

    def test_synced_after_publish_without_changes(self):
        """发布后未改动：synced + 摘要一致（发布后保留的草稿=unchanged）"""
        self._publish('v1')
        ws = self._ws()
        self.assertEqual(ws['status'], 'synced')
        self.assertTrue(ws['consistent'])
        self.assertFalse(ws['has_pending_changes'])
        self.assertEqual(ws['current_version_no'], 1)

    def test_modified_draft_reports_pending_changes(self):
        """发布后修改一份草稿：pending_changes（modified=1）"""
        self._publish('v1')
        self._modify_file(self.file_a['id'], DOCX + b'-a-new')
        ws = self._ws()
        self.assertEqual(ws['status'], 'pending_changes')
        self.assertEqual(ws['modified'], 1)
        self.assertFalse(ws['consistent'])

    def test_added_file_reports_pending_change(self):
        """发布后新增文件：pending_changes（added=1）"""
        self._publish('v1')
        self._add_file('丙.docx', DOCX + b'-c')
        ws = self._ws()
        self.assertEqual(ws['status'], 'pending_changes')
        self.assertEqual(ws['added'], 1)

    def test_removed_file_reports_pending_change(self):
        """发布后移除文件：pending_changes（removed=1，结构性变化）"""
        self._publish('v1')
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.file_b["id"]}/remove/', {})
        self.assertFalse(has_error(resp), resp.content)
        ws = self._ws()
        self.assertEqual(ws['status'], 'pending_changes')
        self.assertEqual(ws['removed'], 1)
        self.assertFalse(ws['consistent'])

    def test_rename_reports_pending_change(self):
        """发布后改名（内容未变）：pending_changes（renamed=1）"""
        self._publish('v1')
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.file_a["id"]}/rename/', {'name': '甲-新名.docx'})
        self.assertFalse(has_error(resp), resp.content)
        ws = self._ws()
        self.assertEqual(ws['status'], 'pending_changes')
        self.assertEqual(ws['renamed'], 1)

    def test_reorder_reports_pending_change(self):
        """发布后调整顺序：pending_changes（reordered=True）"""
        self._publish('v1')
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.file_b["id"]}/move/', {'position': 1})
        self.assertFalse(has_error(resp), resp.content)
        ws = self._ws()
        self.assertEqual(ws['status'], 'pending_changes')
        self.assertTrue(ws['reordered'])

    def test_active_session_reports_editing(self):
        """编辑会话占用（含未完成同步）：editing，状态不可确认"""
        self._publish('v1')
        resp = self._start_session(file_id=self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        ws = self._ws()
        self.assertEqual(ws['status'], 'editing')
        self.assertEqual(ws['session_busy'], 1)
        self.assertEqual(ws['unconfirmed'], 1)
        self.assertFalse(ws['determinable'])
        self.assertFalse(ws['consistent'])
        # 退出会话后回到已同步
        self.editor_client.delete(
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.file_a["id"]}/draft/session/',
            data=json.dumps({'session_key': get_data(resp)['session_key']}),
            content_type='application/json')
        self.assertEqual(self._ws()['status'], 'synced')

    def test_missing_draft_reports_missing_draft(self):
        """缺草稿：missing_draft，绝不归入已同步"""
        self._publish('v1')
        ManualDraft.objects.get(file_id=self.file_b['id']).delete()
        ws = self._ws()
        self.assertEqual(ws['status'], 'missing_draft')
        self.assertEqual(ws['no_draft'], 1)
        self.assertFalse(ws['consistent'])

    def test_missing_draft_file_reports_unverifiable(self):
        """草稿物理文件缺失（非会话原因）：unverifiable，不显示已同步"""
        self._publish('v1')
        draft = ManualDraft.objects.get(file_id=self.file_a['id'])
        os.remove(storage.resolve_absolute_path(draft.file_path))
        ws = self._ws()
        self.assertEqual(ws['status'], 'unverifiable')
        self.assertEqual(ws['unconfirmed'], 1)
        self.assertFalse(ws['determinable'])

    def test_summary_matches_draft_status_endpoint(self):
        """批量结果与 draft-status 接口 summary 完全一致（防口径漂移）"""
        self._publish('v1')
        self._modify_file(self.file_a['id'], DOCX + b'-a-new')
        self._add_file('丙.docx', DOCX + b'-c')
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/draft-status/')
        self.assertFalse(has_error(resp), resp.content)
        summary = get_data(resp)['summary']
        ws = self._ws()
        for key, value in summary.items():
            self.assertEqual(ws[key], value, f'summary.{key} 漂移')

    # ------------------------------------------------------------------
    # 权限：编制/发布/管理可见；仅查看不下发

    def test_editor_and_publisher_receive_work_status(self):
        self._publish('v1')
        for client in (self.editor_client, self.publisher_client):
            row = self._row(client)
            self.assertIsNotNone(row['work_status'])
            self.assertEqual(row['work_status']['status'], 'synced')

    def test_view_only_role_gets_null_work_status(self):
        """仅查看角色：work_status=None（列表不泄漏草稿状态）"""
        self._publish('v1')
        row = self._row(self.viewer_client)
        self.assertIsNone(row['work_status'])

    # ------------------------------------------------------------------

    def _make_bare_manual(self):
        return Manual.objects.create(
            name='空手册', code='BM-EMPTY',
            org_type=Manual.OWNER_DEPARTMENT, org_name='某部门',
            owner=self.manager, tenant_id='deptA')


class RemovedFileHistoryTests(VersionChangesTestBase):
    """已移除文件的可发现性与清理快照的 is_cleaned 标记"""

    def test_removed_file_version_history_accessible(self):
        """已移除文件的 version-history 仍可查（发布参与历史不丢）

        version-history 属发布域（can_view_published）：所有者不自动可见
        发布版，由持 can_view 授权的发布者查询。
        """
        self._publish('v1')
        post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.file_b["id"]}/remove/', {})
        resp = self.publisher_client.get(
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.file_b["id"]}/version-history/')
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(data['file_id'], self.file_b['id'])
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['version_no'], 1)
        self.assertFalse(data['items'][0]['is_cleaned'])

    def test_cleaned_snapshot_marked_in_version_history(self):
        """快照按保留策略清理后：version-history 行 is_cleaned=True

        物理删除只能经保留策略入口（默认未启用），这里直接置
        cleaned_at 模拟清理完成后的元数据状态（与 retention 流程落库
        结果一致），验证 version-history 消费端能看到清理标记。
        """
        self._publish('v1')
        # 发布后 self.manual 实例的 current_version_id 已过期，从库重取
        manual = Manual.objects.get(pk=self.manual.id)
        snap = ManualVersionFile.objects.get(
            version_id=manual.current_version_id,
            manual_file_id=self.file_a['id'])
        snap.cleaned_at = snap.cleaned_at or timezone.now()
        snap.save(update_fields=['cleaned_at'])
        resp = self.publisher_client.get(
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.file_a["id"]}/version-history/')
        self.assertFalse(has_error(resp), resp.content)
        items = get_data(resp)['items']
        row = next(x for x in items if x['snapshot_id'] == snap.id)
        self.assertTrue(row['is_cleaned'])

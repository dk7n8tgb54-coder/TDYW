# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""文件分工与提交待发布核对的真实行为测试（2026-10-29，2026-11-03 修订）

覆盖（《制度管理模块设计方案》文件分工节 + 2026-10-31 授权模型改造 +
2026-11-03 固定快照交接）：
- 文件分工：新增文件时指定负责人（**不携带 owner_id=默认手册所有者，
  显式空串=owner_id 空，回退手册所有者为有效负责人**）、assignment
  接口改派/清空、文件清单行下发负责人与提交状态。
- 权限：分工业务门禁=手册所有者/平台超管；被指派负责人必须持有该
  手册 can_edit 编制资格；负责人身份+授权才有编辑权；跨制度文件 ID
  拒绝；**提交放行口径=仅该文件有效负责人本人**（手册所有者/平台超管
  不得代提交）。
- 提交：仅有效负责人、需无活跃会话且“保存并结束编辑”后复制独立
  不可变快照；提交后内容写路径冻结（撤回/退回后才能继续修改）；
  重复 pending 拒绝且原记录不变。
- 发布交接：publish-preview 各分组行携带交接字段；新增/变化文件发布人
  ≠有效负责人时必须有当前有效 pending 快照才可发布。
- 旧章节数据：ManualChapter 记录保留可读，写接口全部关闭且不删改记录。
"""
import json
import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.institution import storage
from apps.institution.models import (Manual, ManualChapter, ManualDraft,
                                     ManualEditSession, ManualFile,
                                     ManualOperationLog, ManualSubmission,
                                     ManualVersion)
from apps.institution.tests.base import (
    ALL_PERMS, PERM_DRAFT, PERM_DOWNLOAD, PERM_PUBLISH,
    PERM_UPLOAD, PERM_VIEW,
    delete_json, get_data, has_error, make_client, make_grant, make_user,
    post_json, put_json, setup_test_env,
)

DOCX = b'PK\x03\x04 file-assignment-docx'
# files/create 的 owner_id 三态：未传字段=默认手册所有者；
# _UNSET 表示"不携带字段"，None 表示"显式空串（未分配）"
_UNSET = object()


class FileAssignmentBase(TestCase):
    """管理者（=手册所有者）+ 两名编制者 + 一名发布者 + 查看者；手册就绪"""

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
            name='部门管理手册', code='BM-001',
            org_type=Manual.OWNER_DEPARTMENT, org_name='某部门',
            owner=self.manager, tenant_id='deptA')
        self.editor = make_user('editor', tenant_id='deptB',
                                perms=[PERM_DRAFT, PERM_DOWNLOAD, PERM_VIEW])
        self.editor2 = make_user('editor2', tenant_id='deptC',
                                 perms=[PERM_DRAFT, PERM_DOWNLOAD, PERM_VIEW])
        make_grant(self.manual, self.editor, can_view=True, can_edit=True)
        make_grant(self.manual, self.editor2, can_view=True, can_edit=True)
        self.publisher = make_user('pub', tenant_id='deptZ',
                                   perms=[PERM_PUBLISH, PERM_DOWNLOAD,
                                          PERM_VIEW])
        make_grant(self.manual, self.publisher, can_view=True, can_publish=True)
        self.viewer = make_user('viewer', tenant_id='deptY',
                                perms=[PERM_VIEW])
        make_grant(self.manual, self.viewer, can_view=True)
        self.manager_client = make_client(self.manager)
        self.editor_client = make_client(self.editor)
        self.editor2_client = make_client(self.editor2)
        self.publisher_client = make_client(self.publisher)
        self.viewer_client = make_client(self.viewer)
        self.file_seq = 0

    def _set_password(self, password='edit-pass-1'):
        resp = put_json(self.manager_client,
                        f'/institution/manuals/{self.manual.id}/password/',
                        {'password': password})
        self.assertFalse(has_error(resp), resp.content)
        return password

    def _add_file(self, name=None, owner=_UNSET, note=''):
        """新增制度文件；owner 传账号=指定负责人，传 None=显式未分配，
        不传=默认手册所有者（与 files/create 的 owner_id 三态一致）"""
        self.file_seq += 1
        name = name or f'文件{self.file_seq}.docx'
        payload = {'file': SimpleUploadedFile(name, DOCX)}
        if owner is not _UNSET:
            payload['owner_id'] = '' if owner is None else str(owner.id)
        if note:
            payload['note'] = note
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/create/', payload)
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _files_list(self, client=None):
        client = client or self.manager_client
        resp = client.get(f'/institution/manuals/{self.manual.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _assign(self, client, file_id, owner_id=None, note=''):
        return post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/{file_id}/assignment/',
            {'owner_id': owner_id, 'note': note})

    def _submit(self, client, file_id):
        return post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/{file_id}/submit/',
            {})

    def _start_session(self, client, file_id, password='edit-pass-1'):
        return post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/session/',
            {'password': password})

    def _save(self, client, file_id, session_key, revision,
              name='saved.docx', content=DOCX):
        return client.post(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/save/',
            {'file': SimpleUploadedFile(name, content),
             'session_key': session_key, 'revision': revision})


class AssignmentTests(FileAssignmentBase):
    """分工：新增时指定 / 改派 / 清空（未分配）/ 清单下发"""

    def test_create_with_owner_sets_assignment(self):
        data = self._add_file('操作规程.docx', owner=self.editor,
                              note='负责正文编制')
        self.assertEqual(data['assignment']['owner_id'], self.editor.id)
        self.assertEqual(data['assignment']['owner_name'], self.editor.username)
        self.assertEqual(data['assignment']['note'], '负责正文编制')
        self.assertFalse(data['assignment']['is_mine'])
        entry = ManualFile.objects.get(pk=data['id'])
        self.assertEqual(entry.owner_id, self.editor.id)
        self.assertEqual(entry.assigned_by_id, self.manager.id)
        self.assertIsNotNone(entry.assigned_at)

    def test_create_without_owner_defaults_to_manual_owner(self):
        """不携带 owner_id = 默认手册所有者（新增文件默认由所有者负责）"""
        data = self._add_file('附录.docx')
        self.assertEqual(data['assignment']['owner_id'], self.manager.id)
        self.assertEqual(data['assignment']['owner_name'],
                         self.manager.username)
        entry = ManualFile.objects.get(pk=data['id'])
        self.assertEqual(entry.owner_id, self.manager.id)
        self.assertEqual(entry.assigned_by_id, self.manager.id)

    def test_create_with_explicit_empty_owner_is_unassigned(self):
        """显式携带空串：owner_id 为空（有效负责人回退手册所有者）

        2026-11-03 有效负责人判定：owner_id 为空时回退 Manual.owner，
        因此清单仍下发 owner_id=None/owner_assigned=false，但该文件由
        手册所有者作为有效负责人参与提交/发布判定。
        """
        data = self._add_file('显式未分配.docx', owner=None)
        self.assertIsNone(data['assignment']['owner_id'])
        self.assertEqual(data['assignment']['owner_name'], '')
        self.assertIsNone(ManualFile.objects.get(pk=data['id']).owner_id)
        self.assertEqual(data['assignment']['effective_owner_id'],
                         self.manager.id)
        self.assertFalse(data['assignment']['owner_assigned'])

    def test_assign_by_owner_and_reassign(self):
        """分工业务门禁=手册所有者（或平台超管）：编制授权不足以分工"""
        data = self._add_file('甲.docx', owner=None)
        # 仅持编制授权的账号不能分工
        resp = self._assign(self.editor_client, data['id'],
                            owner_id=self.editor2.id, note='由乙编制')
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])
        self.assertIsNone(ManualFile.objects.get(pk=data['id']).owner_id)
        # 所有者指定
        resp = self._assign(self.manager_client, data['id'],
                            owner_id=self.editor2.id, note='由乙编制')
        self.assertFalse(has_error(resp), resp.content)
        body = get_data(resp)
        self.assertEqual(body['assignment']['owner_id'], self.editor2.id)
        # 所有者改派
        resp = self._assign(self.manager_client, data['id'],
                            owner_id=self.editor.id, note='改由甲编制')
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['assignment']['owner_id'], self.editor.id)
        # 操作记录
        self.assertTrue(ManualOperationLog.objects.filter(
            manual=self.manual, file_id=data['id'],
            action='file_assign').exists())

    def test_assign_requires_can_edit_qualification(self):
        """被指派账号必须持有该手册 can_edit 编制资格"""
        data = self._add_file('资格.docx', owner=None)
        # 无任何授权的账号被拒
        outsider = make_user('no-grant', tenant_id='deptW', perms=[PERM_VIEW])
        resp = self._assign(self.manager_client, data['id'],
                            owner_id=outsider.id)
        self.assertTrue(has_error(resp))
        self.assertIn('编制资格', resp.json()['error'])
        # 仅有 can_view 授权的账号同样被拒
        viewer = make_user('view-grant', tenant_id='deptW', perms=[PERM_VIEW])
        make_grant(self.manual, viewer, can_view=True)
        resp = self._assign(self.manager_client, data['id'],
                            owner_id=viewer.id)
        self.assertTrue(has_error(resp))
        self.assertIn('编制资格', resp.json()['error'])
        self.assertIsNone(ManualFile.objects.get(pk=data['id']).owner_id)

    def test_clear_owner_becomes_unassigned(self):
        data = self._add_file('乙.docx', owner=self.editor)
        resp = self._assign(self.manager_client, data['id'],
                            owner_id=None, note='')
        self.assertFalse(has_error(resp), resp.content)
        body = get_data(resp)
        self.assertIsNone(body['assignment']['owner_id'])
        self.assertEqual(body['assignment']['owner_name'], '')
        entry = ManualFile.objects.get(pk=data['id'])
        self.assertIsNone(entry.owner_id)
        self.assertEqual(entry.assign_note, '')

    def test_assign_invalid_owner_rejected(self):
        data = self._add_file('丙.docx')
        resp = self._assign(self.manager_client, data['id'], owner_id=9999999)
        self.assertTrue(has_error(resp))

    def test_assign_denied_for_view_only_grant(self):
        data = self._add_file('丁.docx', owner=None)
        resp = self._assign(self.viewer_client, data['id'],
                            owner_id=self.editor.id)
        self.assertTrue(has_error(resp))
        self.assertIsNone(ManualFile.objects.get(pk=data['id']).owner_id)

    def test_assign_cross_manual_file_rejected(self):
        other = Manual.objects.create(
            name='其他手册', owner=self.manager, tenant_id='deptA')
        other_file = ManualFile.objects.create(
            manual=other, display_name='别册.docx')
        data = self._add_file('本册.docx')
        resp = self._assign(self.manager_client, data['id'],
                            owner_id=self.editor.id)
        self.assertFalse(has_error(resp), resp.content)
        # 把其他制度的文件 ID 塞进本制度路由：明确拒绝，不得误改
        resp = self._assign(self.manager_client, other_file.id,
                            owner_id=self.editor.id)
        self.assertTrue(has_error(resp))
        other_file.refresh_from_db()
        self.assertIsNone(other_file.owner_id)

    def test_list_rows_carry_assignment_submission_gated_by_workspace(self):
        data = self._add_file('清单.docx', owner=self.editor)
        self._set_password()
        resp = self._start_session(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        # 工作区可见者（编制/发布/所有者）：submission 在，含草稿修订号
        row = {x['id']: x for x in self._files_list(self.editor_client)}[data['id']]
        self.assertEqual(row['submission']['state'], 'none')
        self.assertEqual(row['submission']['draft_revision'], 1)
        # 仅查看授权：assignment 可见（负责人是责任信息），submission/draft 不下发
        row = {x['id']: x for x in self._files_list(self.viewer_client)}[data['id']]
        self.assertEqual(row['assignment']['owner_id'], self.editor.id)
        self.assertNotIn('submission', row)
        self.assertIsNone(row['draft'])

    def test_submission_state_is_mine_from_request_user(self):
        data = self._add_file('我的.docx', owner=self.editor)
        row = {x['id']: x for x in self._files_list(self.editor_client)}[data['id']]
        self.assertTrue(row['assignment']['is_mine'])
        row = {x['id']: x for x in self._files_list(self.editor2_client)}[data['id']]
        self.assertFalse(row['assignment']['is_mine'])


class OwnerPermissionTests(FileAssignmentBase):
    """编制资格与负责人独占编辑（2026-10-31 授权模型改造）"""

    def test_owner_without_edit_grant_cannot_edit(self):
        """负责人必持编制授权：无 can_edit 授权者既不能被指派也不能编辑"""
        outsider = make_user('owner', tenant_id='deptW', perms=[PERM_VIEW])
        data = self._add_file('仅查看负责人.docx')
        resp = self._assign(self.manager_client, data['id'],
                            owner_id=outsider.id)
        self.assertTrue(has_error(resp))
        self.assertIn('编制资格', resp.json()['error'])
        self._set_password()
        # 直接构造的负责人（绕过 API）同样不能开启会话
        ManualFile.objects.filter(pk=data['id']).update(owner_id=outsider.id)
        resp = self._start_session(make_client(outsider), data['id'])
        self.assertTrue(has_error(resp))

    def test_owner_can_submit_with_view_page_perm_only(self):
        """有效负责人完成编制后可提交（要求“保存并结束编辑”后固定快照）

        2026-11-03：提交不再写 ManualFile 旧列，而是创建 ManualSubmission
        独立快照；页面 view 权限 + 负责人身份即放行（提交是交接，不要求
        draft_edit 页面码）。
        """
        owner = make_user('owner2', tenant_id='deptW', perms=[PERM_VIEW])
        make_grant(self.manual, owner, can_view=True, can_edit=True)
        data = self._add_file('提交.docx', owner=owner)
        resp = self._submit(make_client(owner), data['id'])
        self.assertFalse(has_error(resp), resp.content)
        body = get_data(resp)
        self.assertEqual(body['submission']['state'], 'submitted')
        self.assertEqual(body['submission']['status'], 'pending')
        submission = ManualSubmission.objects.get(file_id=data['id'])
        self.assertEqual(submission.draft_revision,
                         body['submission']['submission_revision'])
        self.assertEqual(submission.submitted_by_id, owner.id)
        self.assertIsNotNone(submission.submitted_at)
        self.assertTrue(submission.file_path.startswith('submissions/'))

    def test_only_file_owner_can_submit(self):
        """放行口径=仅文件负责人：手册所有者/平台超管/其他编制授权均不得代提交"""
        data = self._add_file('越权提交.docx', owner=self.editor)
        for client, message in (
                (self.viewer_client, '负责人'),
                (self.editor2_client, '负责人'),
                (self.manager_client, '负责人')):
            resp = self._submit(client, data['id'])
            self.assertTrue(has_error(resp), resp.content)
            self.assertIn(message, resp.json()['error'])
        self.assertFalse(ManualSubmission.objects.filter(
            file_id=data['id']).exists())
        # 平台超管同样不得代提交
        admin = make_user('root', is_supper=True, tenant_id='root')
        resp = self._submit(make_client(admin), data['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('负责人', resp.json()['error'])
        self.assertFalse(ManualSubmission.objects.filter(
            file_id=data['id']).exists())
        # 负责人本人提交成功：创建 pending 固定快照
        resp = self._submit(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        submission = ManualSubmission.objects.get(file_id=data['id'])
        self.assertEqual(submission.status, ManualSubmission.STATUS_PENDING)

    def test_unassigned_file_falls_back_to_manual_owner(self):
        """owner_id 为空：回退 Manual.owner 为有效负责人（可提交）

        2026-11-03 有效负责人判定；真正的 unassigned 是显式负责人与手册
        所有者都为空（由 test_submission_snapshot 独立手册场景覆盖）。
        """
        data = self._add_file('未分配提交.docx', owner=None)
        row = self._files_list()
        target = {x['id']: x for x in row}[data['id']]
        self.assertIsNone(target['assignment']['owner_id'])
        self.assertEqual(target['assignment']['effective_owner_id'],
                         self.manager.id)
        resp = self._submit(self.manager_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(
            ManualSubmission.objects.get(file_id=data['id']).status,
            ManualSubmission.STATUS_PENDING)

    def test_submit_cross_manual_file_rejected(self):
        other = Manual.objects.create(name='别册手册', owner=self.manager,
                                      tenant_id='deptA')
        other_file = ManualFile.objects.create(
            manual=other, display_name='别册.docx',
            owner=self.editor)
        resp = self._submit(self.editor_client, other_file.id)
        self.assertTrue(has_error(resp))

    def test_reassignment_revokes_active_sessions(self):
        """改派/清空负责人撤销该文件活跃会话，旧负责人不能再保存"""
        data = self._add_file('改派.docx', owner=self.editor)
        self._set_password()
        resp = self._start_session(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        session_key = get_data(resp)['session_key']
        # 改派给 editor2：旧负责人会话被撤销
        resp = self._assign(self.manager_client, data['id'],
                            owner_id=self.editor2.id)
        self.assertFalse(has_error(resp), resp.content)
        detail = json.loads(ManualOperationLog.objects.filter(
            manual=self.manual, file_id=data['id'],
            action='file_assign').latest('id').detail)
        self.assertGreaterEqual(detail.get('revoked_sessions', 0), 1)
        self.assertIsNotNone(ManualEditSession.objects.get(
            session_key=session_key).revoked_at)
        # 旧负责人已非负责人：负责人独占拒绝（早于会话校验）
        resp = self._save(self.editor_client, data['id'], session_key, 1,
                          content=DOCX + b'-late')
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])
        # 新负责人可开启会话
        resp = self._start_session(self.editor2_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)


class SubmitValidationTests(FileAssignmentBase):
    """提交编制的业务校验"""

    def _prepare(self, name='校验.docx'):
        data = self._add_file(name, owner=self.editor)
        self._set_password()
        return data

    def test_submit_rejected_without_draft(self):
        data = self._add_file('无草稿.docx', owner=self.editor)
        # 直接构造无草稿条目：临时目录 patch 下用真空条目不可行（create 即建草稿），
        # 改为清空草稿文件路径模拟"无效草稿"
        ManualDraft.objects.filter(file_id=data['id']).update(file_path='')
        resp = self._submit(self.editor_client, data['id'])
        self.assertTrue(has_error(resp))
        self.assertFalse(ManualSubmission.objects.filter(
            file_id=data['id']).exists())

    def test_submit_rejected_with_active_session(self):
        data = self._prepare()
        resp = self._start_session(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        resp = self._submit(self.editor_client, data['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('会话', resp.json()['error'])

    def test_submit_rejected_for_archived_manual(self):
        data = self._prepare()
        Manual.objects.filter(pk=self.manual.id).update(
            status=Manual.STATUS_ARCHIVED)
        resp = self._submit(self.editor_client, data['id'])
        self.assertTrue(has_error(resp))

    def test_duplicate_submit_rejected_state_unchanged(self):
        """有效重复提交拒绝：原 pending 记录/修订号不变"""
        data = self._prepare()
        resp = self._submit(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        first = ManualSubmission.objects.get(file_id=data['id'])
        resp = self._submit(self.editor_client, data['id'])
        self.assertTrue(has_error(resp), resp.content)
        self.assertIn('该文件已有待发布人核对的提交，请勿重复提交',
                      resp.json()['error'])
        first.refresh_from_db()
        self.assertEqual(first.status, ManualSubmission.STATUS_PENDING)
        self.assertEqual(ManualSubmission.objects.filter(
            file_id=data['id']).count(), 1)

    def test_resubmit_after_draft_change_updates_revision_and_time(self):
        """提交后冻结；撤回修改再提交创建新快照行（旧行保留）"""
        data = self._prepare()
        resp = self._submit(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        first = ManualSubmission.objects.get(file_id=data['id'])
        # 冻结期间不能直接保存；先撤回
        resp = self._start_session(self.editor_client, data['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('已提交待发布核对', resp.json()['error'])
        resp = post_json(
            self.editor_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{data["id"]}/submit/withdraw/', {})
        self.assertFalse(has_error(resp), resp.content)
        first.refresh_from_db()
        self.assertEqual(first.status, ManualSubmission.STATUS_WITHDRAWN)
        resp = self._start_session(self.editor_client, data['id'])
        session_key = get_data(resp)['session_key']
        resp = self._save(self.editor_client, data['id'], session_key, 1,
                          content=DOCX + b'-v2')
        self.assertFalse(has_error(resp), resp.content)
        delete_json(self.editor_client,
                    f'/institution/manuals/{self.manual.id}/files/{data["id"]}/draft/session/',
                    {'session_key': session_key})
        resp = self._submit(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        second = ManualSubmission.objects.get(
            file_id=data['id'], status=ManualSubmission.STATUS_PENDING)
        self.assertNotEqual(second.id, first.id)
        self.assertEqual(second.draft_revision, 2)


class SubmissionInvalidationTests(FileAssignmentBase):
    """提交后内容写路径冻结；撤回/退回后旧快照作废，重提产生新行"""

    def _submitted_file(self, name='失效.docx'):
        data = self._add_file(name, owner=self.editor)
        self._set_password()
        resp = self._submit(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        return data

    def _row(self, file_id, client=None):
        client = client or self.manager_client
        return {x['id']: x for x in self._files_list(client)}[file_id]

    def _withdraw(self, data):
        resp = post_json(
            self.editor_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{data["id"]}/submit/withdraw/', {})
        self.assertFalse(has_error(resp), resp.content)
        return resp

    def test_save_after_submit_is_frozen(self):
        """提交后保存/开启编辑会话均被冻结拒绝；待核对快照不变"""
        data = self._submitted_file()
        submission = ManualSubmission.objects.get(file_id=data['id'])
        resp = self._start_session(self.editor_client, data['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('已提交待发布核对', resp.json()['error'])
        submission.refresh_from_db()
        self.assertEqual(submission.status,
                         ManualSubmission.STATUS_PENDING)
        self.assertEqual(submission.draft_revision, 1)
        self.assertEqual(self._row(data['id'])['submission']['state'],
                         'submitted')

    def test_content_change_after_submit_requires_withdraw(self):
        """提交后即使真实验证会话也不能保存；撤回后才能修改并重提"""
        data = self._submitted_file('重建.docx')
        self._withdraw(data)
        resp = self._start_session(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        session_key = get_data(resp)['session_key']
        resp = self._save(self.editor_client, data['id'], session_key, 1,
                          name='重建-改.docx',
                          content=DOCX + b'-after-submit')
        self.assertFalse(has_error(resp), resp.content)
        delete_json(self.editor_client,
                    f'/institution/manuals/{self.manual.id}/files/{data["id"]}/draft/session/',
                    {'session_key': session_key})
        resp = self._submit(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        row = self._row(data['id'])
        self.assertEqual(row['submission']['state'], 'submitted')
        self.assertEqual(row['submission']['draft_revision'], 2)

    def test_rollback_after_submit_rejected_until_withdrawn(self):
        """存在 pending 提交时整套回退整体拒绝；撤回后才可回退"""
        data = self._submitted_file('回退.docx')
        # 首版发布消费首份提交；开始新一轮修订后再提交形成 pending
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': '首版'})
        self.assertFalse(has_error(resp), resp.content)
        version_id = ManualVersion.objects.filter(
            manual=self.manual).order_by('-version_no').first().id
        resp = post_json(
            self.editor_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{data["id"]}/revision/start/', {})
        self.assertFalse(has_error(resp), resp.content)
        resp = self._submit(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/draft/from-version/',
            {'version_id': version_id})
        self.assertTrue(has_error(resp))
        self.assertIn('已提交待发布核对', resp.json()['error'])
        self._withdraw(data)
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/draft/from-version/',
            {'version_id': version_id})
        self.assertFalse(has_error(resp), resp.content)
        row = self._row(data['id'])
        self.assertEqual(row['submission']['state'], 'none')
        self.assertEqual(row['submission']['status'], 'withdrawn')

    def test_resubmit_restores_valid_state(self):
        """撤回后修改并重新提交：新 pending 生效，旧行状态保留"""
        data = self._submitted_file('再提交.docx')
        first = ManualSubmission.objects.get(file_id=data['id'])
        self._withdraw(data)
        resp = self._start_session(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        session_key = get_data(resp)['session_key']
        resp = self._save(self.editor_client, data['id'], session_key, 1,
                          content=DOCX + b'-again')
        self.assertFalse(has_error(resp), resp.content)
        delete_json(self.editor_client,
                    f'/institution/manuals/{self.manual.id}/files/{data["id"]}/draft/session/',
                    {'session_key': session_key})
        resp = self._submit(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        row = self._row(data['id'])
        self.assertEqual(row['submission']['state'], 'submitted')
        second = ManualSubmission.objects.get(
            file_id=data['id'], status=ManualSubmission.STATUS_PENDING)
        self.assertNotEqual(second.id, first.id)
        self.assertEqual(second.draft_revision, 2)
        first.refresh_from_db()
        self.assertEqual(first.status, ManualSubmission.STATUS_WITHDRAWN)


class PublishPlanAssignmentTests(FileAssignmentBase):
    """发布交接（2026-11-01）：预检行携带交接字段；未完成交接阻断发布"""

    HANDOFF_KEYS = ('owner_id', 'owner_name', 'submission',
                    'publisher_is_owner', 'submission_required',
                    'content_changed')

    def _preview(self):
        resp = self.publisher_client.get(
            f'/institution/manuals/{self.manual.id}/publish-preview/')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _publish(self, note='发布'):
        return post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': note})

    def _version_dir_files(self):
        root = os.path.join(self._tmp.name, 'versions')
        found = []
        for dirpath, _, filenames in os.walk(root):
            found.extend(os.path.join(dirpath, name) for name in filenames)
        return found

    def test_plan_rows_carry_handoff_fields(self):
        submitted = self._add_file('已提交.docx', owner=self.editor,
                                   note='甲编制')
        resp = self._submit(self.editor_client, submitted['id'])
        self.assertFalse(has_error(resp), resp.content)
        pending = self._add_file('未提交.docx', owner=self.editor2)
        plan = self._preview()
        added = {r['file_id']: r for r in plan['added']}
        row = added[submitted['id']]
        for key in self.HANDOFF_KEYS:
            self.assertIn(key, row)
        self.assertEqual(row['owner_id'], self.editor.id)
        self.assertEqual(row['owner_name'], self.editor.username)
        self.assertEqual(row['submission']['state'], 'submitted')
        self.assertEqual(row['submission']['submitted_by_name'],
                         self.editor.username)
        self.assertFalse(row['publisher_is_owner'])
        self.assertTrue(row['submission_required'])
        self.assertTrue(row['content_changed'])
        # 未提交文件进入 blocked：交接阻断（不再只是核对信息）
        blocked = {r['file_id']: r for r in plan['blocked']}
        self.assertIn(pending['id'], blocked)
        pending_row = blocked[pending['id']]
        for key in self.HANDOFF_KEYS:
            self.assertIn(key, pending_row)
        self.assertEqual(pending_row['reason'], 'submission_pending')
        self.assertIn('等待负责人', pending_row['message'])
        self.assertIn(self.editor2.username, pending_row['message'])
        self.assertEqual(pending_row['submission']['state'], 'none')
        self.assertEqual(plan['blocker_summary'], {'submission_pending': 1})
        self.assertFalse(plan['can_publish'])

    def test_unsubmitted_file_blocks_publish(self):
        """未提交阻断真实发布：无新版本、无快照残留"""
        self._add_file('未提交也发布.docx', owner=self.editor)
        plan = self._preview()
        self.assertEqual(plan['blocked'][0]['reason'], 'submission_pending')
        self.assertFalse(plan['can_publish'])
        resp = self._publish('无提交标记也发布')
        self.assertTrue(has_error(resp))
        self.assertIn('存在未完成的提交待发布核对', resp.json()['error'])
        self.assertIn('等待负责人', resp.json()['error'])
        self.assertFalse(ManualVersion.objects.filter(
            manual=self.manual).exists())
        self.assertEqual(self._version_dir_files(), [])

    def test_blocked_row_still_carries_handoff_fields(self):
        """既有受阻原因行（会话占用）同样携带交接字段（前端统一取键）"""
        data = self._add_file('受阻.docx', owner=self.editor2)
        self._set_password()
        resp = self._start_session(self.editor2_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        plan = self._preview()
        self.assertEqual(len(plan['blocked']), 1)
        blocked = plan['blocked'][0]
        for key in self.HANDOFF_KEYS:
            self.assertIn(key, blocked)
        self.assertEqual(blocked['reason'], 'session_busy')
        self.assertEqual(blocked['owner_name'], self.editor2.username)
        self.assertEqual(blocked['submission']['state'], 'none')
        self.assertFalse(blocked['content_changed'])
        self.assertFalse(blocked['submission_required'])
        self.assertIn('session', blocked)


class LegacyChapterRecordTests(FileAssignmentBase):
    """旧章节分工：记录保留可读，写接口全部关闭"""

    def setUp(self):
        super().setUp()
        self.chapter = ManualChapter.objects.create(
            manual=self.manual, title='第一章 总则',
            owner=self.editor, owner_name=self.editor.username,
            note='旧章节记录', sort_order=1)

    def test_list_returns_legacy_records(self):
        resp = self.viewer_client.get(
            f'/institution/manuals/{self.manual.id}/chapters/')
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['title'], '第一章 总则')

    def test_write_endpoints_closed_and_records_kept(self):
        base = f'/institution/manuals/{self.manual.id}/chapters'
        resp = post_json(self.manager_client, f'{base}/create/',
                         {'title': '新章节'})
        self.assertTrue(has_error(resp))
        resp = put_json(self.manager_client, f'{base}/{self.chapter.id}/',
                        {'title': '改章节'})
        self.assertTrue(has_error(resp))
        resp = delete_json(self.manager_client, f'{base}/{self.chapter.id}/')
        self.assertTrue(has_error(resp))
        # 旧记录原样保留（人工核对完成前绝不删除或改写）
        self.chapter.refresh_from_db()
        self.assertEqual(self.chapter.title, '第一章 总则')
        self.assertEqual(ManualChapter.objects.filter(
            manual=self.manual).count(), 1)
        self.assertFalse(ManualOperationLog.objects.filter(
            manual=self.manual, action='chapter_update').exists())

    def test_legacy_records_survive_file_assignment_flow(self):
        data = self._add_file('分工.docx', owner=self.editor)
        resp = self._submit(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        self.assertTrue(ManualChapter.objects.filter(
            pk=self.chapter.id).exists())


class AssignmentOwnerOptionsTests(FileAssignmentBase):
    """负责人候选接口（2026-10-31 授权模型改造后口径）

    - 业务门禁与分工写路径一致：手册所有者或平台超管（仅页面权限
      不再放行无授权调用者）；
    - 候选=手册所有者（即使无 can_edit 授权行，所有者按对象范围自动
      具备编辑资格）+ 持有该手册 can_edit 编制授权的启用账号（与
      _resolve_assignee 的校验口径一致；跨租户账号可作负责人是预期）；
    - 按 id 去重，只返回 id + name（昵称，空则账号名）最小字段。
    """

    def _owners(self, client):
        return client.get(
            f'/institution/manuals/{self.manual.id}/assignment-owners/')

    def test_account_user_list_still_denies_assignment_perm_user(self):
        """根因固化：账号管理清单仍要求 system.account.view，制度分工
        权限不放行（候选接口绝不以放宽账号接口为手段）"""
        # 测试内路径不含 /api 前缀（nginx 重写后；前端实际请求 /api/account/user/）
        resp = self.editor_client.get('/account/user/')
        self.assertTrue(has_error(resp))
        self.assertEqual(resp.json()['error'], '权限拒绝')

    def test_owner_gets_owner_and_can_edit_holders_as_candidates(self):
        """核心回归：所有者可取候选；候选含所有者本人 + 持 can_edit 的启用账号"""
        resp = self._owners(self.manager_client)
        self.assertFalse(has_error(resp), resp.content)
        rows = get_data(resp)
        by_id = {r['id']: r for r in rows}
        # 候选含跨租户授权账号（本模块授权与 tenant 无关的不变量）
        self.assertIn(self.editor.id, by_id)
        self.assertEqual(by_id[self.editor.id]['name'], self.editor.nickname)
        self.assertIn(self.editor2.id, by_id)
        # 手册所有者本人即使无 can_edit 授权行也在候选（可作为文件负责人）
        self.assertIn(self.manager.id, by_id)
        self.assertEqual(by_id[self.manager.id]['name'], self.manager.nickname)
        # 仅 can_view / can_publish 授权或无授权账号不在候选
        self.assertNotIn(self.viewer.id, by_id)
        self.assertNotIn(self.publisher.id, by_id)
        outsider = make_user('no-grant', tenant_id='deptW', perms=[PERM_DRAFT])
        self.assertNotIn(outsider.id, by_id)
        # 仅返回最小字段（ID+显示名），不回传账号管理字段
        for row in rows:
            self.assertEqual(set(row.keys()), {'id', 'name'})
        # 去重：所有者同时持 can_edit 授权行时只出现一次
        make_grant(self.manual, self.manager, can_edit=True)
        rows = get_data(self._owners(self.manager_client))
        self.assertEqual(len([r for r in rows if r['id'] == self.manager.id]), 1)

    def test_platform_admin_gets_candidates_for_any_manual(self):
        """平台超管（is_supper）对任意手册可取候选（"制度管理员"码已废除）"""
        admin = make_user('inst-admin', is_supper=True, tenant_id='deptA')
        resp = self._owners(make_client(admin))
        self.assertFalse(has_error(resp), resp.content)
        self.assertIn(self.editor.id, [r['id'] for r in get_data(resp)])

    def test_page_perm_without_owner_or_admin_denied(self):
        """页面权限满足但非所有者/管理员：与分工写接口同口径拒绝"""
        # 持 draft_edit 页面权限的编制授权账号：到达业务门后拒绝
        resp = self._owners(self.editor_client)
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])
        # 仅持 upload 页面权限（新增文件路径）同样拒绝
        uploader = make_user('upl-only', tenant_id='deptA',
                             perms=[PERM_UPLOAD, PERM_VIEW])
        resp = self._owners(make_client(uploader))
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])

    def test_inactive_account_not_candidate_and_rejected_as_owner(self):
        """停用账号不进候选，写接口同样拒绝（口径一致）"""
        self.editor2.is_active = False
        self.editor2.save()
        resp = self._owners(self.manager_client)
        self.assertFalse(has_error(resp), resp.content)
        self.assertNotIn(self.editor2.id,
                         [r['id'] for r in get_data(resp)])
        data = self._add_file('停用.docx')
        resp = self._assign(self.manager_client, data['id'],
                            owner_id=self.editor2.id)
        self.assertTrue(has_error(resp))


class OwnerFileManagementExemptionTests(FileAssignmentBase):
    """第二轮权限模型：无任何 institution 页面码的所有者可用文件管理
    写路径（manual_auth 对象级豁免：所有者不需要角色权限）"""

    def test_owner_without_page_perm_manages_files(self):
        owner = make_user('bare-owner', tenant_id='deptA')
        # 超管把手册移交给无页面码账号（当前所有者或超管可移交）
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/owner/',
            {'account_id': owner.id})
        self.assertFalse(has_error(resp), resp.content)
        client = make_client(owner)
        # 新增制度文件（upload 门）
        resp = client.post(
            f'/institution/manuals/{self.manual.id}/files/create/',
            {'file': SimpleUploadedFile('裸.docx', DOCX)})
        self.assertFalse(has_error(resp), resp.content)
        file_id = get_data(resp)['id']
        # 分工（draft_edit 门）
        resp = post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/{file_id}/'
            f'assignment/', {'owner_id': self.editor.id, 'note': '分工'})
        self.assertFalse(has_error(resp), resp.content)
        # 改名（draft_edit 门）
        resp = post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/{file_id}/rename/',
            {'name': '改名.docx'})
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(ManualFile.objects.get(pk=file_id).display_name,
                         '改名.docx')
        # 负责人候选（draft_edit|upload 门）
        resp = client.get(
            f'/institution/manuals/{self.manual.id}/assignment-owners/')
        self.assertFalse(has_error(resp), resp.content)
        self.assertIn(self.editor.id, [r['id'] for r in get_data(resp)])


class MultiFileParallelAssignmentTests(FileAssignmentBase):
    """多文件并行：分工与提交按文件独立，互不影响"""

    def test_assignment_and_submission_are_per_file(self):
        first = self._add_file('第一份.docx', owner=self.editor)
        second = self._add_file('第二份.docx', owner=self.editor2)
        self._set_password()
        # 提交第一份不影响第二份
        resp = self._submit(self.editor_client, first['id'])
        self.assertFalse(has_error(resp), resp.content)
        rows = {x['id']: x for x in self._files_list()}
        self.assertEqual(rows[first['id']]['submission']['state'], 'submitted')
        self.assertEqual(rows[second['id']]['submission']['state'], 'none')
        self.assertEqual(rows[second['id']]['assignment']['owner_id'],
                         self.editor2.id)
        # 第二份会话占用不影响第一份提交状态
        resp = self._start_session(self.editor2_client, second['id'])
        self.assertFalse(has_error(resp), resp.content)
        rows = {x['id']: x for x in self._files_list()}
        self.assertEqual(rows[first['id']]['submission']['state'], 'submitted')
        self.assertEqual(rows[second['id']]['submission']['state'], 'none')
        # 第一份已提交：冻结期间改派被拒，第二份分工不受影响
        resp = self._assign(self.manager_client, first['id'],
                            owner_id=self.editor2.id, note='改派')
        self.assertTrue(has_error(resp))
        self.assertIn('已提交待发布核对', resp.json()['error'])
        rows = {x['id']: x for x in self._files_list()}
        self.assertEqual(rows[first['id']]['assignment']['owner_id'],
                         self.editor.id)
        self.assertEqual(rows[second['id']]['assignment']['owner_id'],
                         self.editor2.id)
        self.assertEqual(rows[first['id']]['submission']['state'], 'submitted')
        # 撤回后才可改派：旧快照作废（记录保留），第二份仍不受影响
        resp = post_json(
            self.editor_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{first["id"]}/submit/withdraw/', {})
        self.assertFalse(has_error(resp), resp.content)
        resp = self._assign(self.manager_client, first['id'],
                            owner_id=self.editor2.id, note='改派')
        self.assertFalse(has_error(resp), resp.content)
        rows = {x['id']: x for x in self._files_list()}
        self.assertEqual(rows[first['id']]['assignment']['owner_id'],
                         self.editor2.id)
        self.assertEqual(rows[second['id']]['assignment']['owner_id'],
                         self.editor2.id)
        self.assertEqual(rows[first['id']]['submission']['state'], 'none')
        self.assertEqual(rows[first['id']]['submission']['status'], 'withdrawn')

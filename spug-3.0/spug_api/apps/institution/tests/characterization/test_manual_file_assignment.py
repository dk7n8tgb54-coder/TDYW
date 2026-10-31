# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""文件分工与提交编制的真实行为测试（2026-10-29，替代旧章节分工）

覆盖（《制度管理模块设计方案》文件分工节 + 2026-10-31 授权模型改造）：
- 文件分工：新增文件时指定负责人、assignment 接口改派/清空（未分配）、
  文件清单行下发负责人与提交状态（草稿域信息按工作区可见口径门控）。
- 权限：分工业务门禁=手册所有者/制度管理员（2026-10-31 起）；被指派
  负责人必须持有该手册 can_edit 编制资格；负责人身份+授权才有编辑权；
  跨制度文件 ID 拒绝；提交编制放行口径=文件负责人/手册所有者/制度管理员。
- 提交编制：记录提交时草稿修订号与时间；无有效草稿、活跃编辑会话、
  归档手册拒绝；草稿再次保存/重建/回退后提交状态失效（不得显示已完成）；
  可重复提交；改派/清空撤销在途编辑会话。
- 发布核对：publish-preview 各分组行携带负责人与提交状态，但提交与否
  不新增发布阻断（现有整套发布校验保持不变）。
- 旧章节数据：ManualChapter 记录保留可读，写接口全部关闭且不删改记录。
"""
import json
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.institution import storage
from apps.institution.models import (Manual, ManualChapter, ManualDraft,
                                     ManualEditSession, ManualFile,
                                     ManualOperationLog, ManualVersion)
from apps.institution.tests.base import (
    ALL_PERMS, PERM_ADMIN, PERM_DRAFT, PERM_DOWNLOAD, PERM_PUBLISH,
    PERM_UPLOAD, PERM_VIEW,
    delete_json, get_data, has_error, make_client, make_grant, make_user,
    post_json, put_json, setup_test_env,
)

DOCX = b'PK\x03\x04 file-assignment-docx'


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

    def _add_file(self, name=None, owner=None, note=''):
        self.file_seq += 1
        name = name or f'文件{self.file_seq}.docx'
        payload = {'file': SimpleUploadedFile(name, DOCX)}
        if owner:
            payload['owner_id'] = str(owner.id)
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

    def test_create_without_owner_is_unassigned(self):
        data = self._add_file('附录.docx')
        self.assertIsNone(data['assignment']['owner_id'])
        self.assertEqual(data['assignment']['owner_name'], '')
        self.assertIsNone(ManualFile.objects.get(pk=data['id']).owner_id)

    def test_assign_by_owner_and_reassign(self):
        """分工业务门禁=手册所有者（或制度管理员）：编制授权不足以分工"""
        data = self._add_file('甲.docx')
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
        data = self._add_file('资格.docx')
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
        data = self._add_file('丁.docx')
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
        """负责人完成编制后可提交（提交是状态交接，不要求 draft_edit
        页面权限；编制资格由授权行承载）"""
        owner = make_user('owner2', tenant_id='deptW', perms=[PERM_VIEW])
        make_grant(self.manual, owner, can_view=True, can_edit=True)
        data = self._add_file('提交.docx', owner=owner)
        resp = self._submit(make_client(owner), data['id'])
        self.assertFalse(has_error(resp), resp.content)
        body = get_data(resp)
        self.assertEqual(body['submission']['state'], 'submitted')
        self.assertEqual(body['submission']['submission_revision'], 1)
        entry = ManualFile.objects.get(pk=data['id'])
        self.assertEqual(entry.submitted_by_id, owner.id)
        self.assertIsNotNone(entry.submitted_at)

    def test_non_assignee_cannot_submit(self):
        """放行口径=文件负责人/手册所有者/制度管理员：编制资格（非负责人）
        与仅查看授权均不可提交"""
        data = self._add_file('越权提交.docx', owner=self.editor)
        resp = self._submit(self.viewer_client, data['id'])
        self.assertTrue(has_error(resp))
        entry = ManualFile.objects.get(pk=data['id'])
        self.assertIsNone(entry.submitted_at)
        # 编制授权（非负责人）不可提交：负责人独占编辑后提交随负责人走
        resp = self._submit(self.editor2_client, data['id'])
        self.assertTrue(has_error(resp))
        # 手册所有者可代为提交
        resp = self._submit(self.manager_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        self.assertIsNotNone(
            ManualFile.objects.get(pk=data['id']).submitted_at)

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
        self.assertIsNone(ManualFile.objects.get(pk=data['id']).submitted_at)

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

    def test_resubmit_overwrites_revision_and_time(self):
        data = self._prepare()
        resp = self._submit(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        first_at = ManualFile.objects.get(pk=data['id']).submitted_at
        # 保存推进修订号后退出会话再提交：以最新修订号覆盖
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
        entry = ManualFile.objects.get(pk=data['id'])
        self.assertEqual(entry.submission_revision, 2)
        self.assertGreater(entry.submitted_at, first_at)


class SubmissionInvalidationTests(FileAssignmentBase):
    """提交后草稿再次变化：提交状态必须失效，不得继续显示已完成"""

    def _submitted_file(self, name='失效.docx'):
        data = self._add_file(name, owner=self.editor)
        self._set_password()
        resp = self._submit(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        return data

    def _row(self, file_id, client=None):
        client = client or self.manager_client
        return {x['id']: x for x in self._files_list(client)}[file_id]

    def test_save_after_submit_marks_stale(self):
        data = self._submitted_file()
        resp = self._start_session(self.editor_client, data['id'])
        session_key = get_data(resp)['session_key']
        resp = self._save(self.editor_client, data['id'], session_key, 1,
                          content=DOCX + b'-changed')
        self.assertFalse(has_error(resp), resp.content)
        row = self._row(data['id'])
        self.assertEqual(row['submission']['state'], 'stale')
        # 提交痕迹保留（何时由谁提交过），但不再是"有效提交"
        self.assertEqual(row['submission']['submission_revision'], 1)
        self.assertEqual(row['submission']['draft_revision'], 2)

    def test_rebuild_from_original_after_submit_marks_stale(self):
        data = self._submitted_file('重建.docx')
        original_id = ManualDraft.objects.get(file_id=data['id']).source_original_id
        # 重建是内容写路径：负责人独占，由文件负责人执行
        resp = post_json(
            self.editor_client,
            f'/institution/manuals/{self.manual.id}/files/{data["id"]}/draft/create/',
            {'original_id': original_id})
        self.assertFalse(has_error(resp), resp.content)
        row = self._row(data['id'])
        self.assertEqual(row['submission']['state'], 'stale')
        self.assertEqual(row['submission']['draft_revision'], 2)

    def test_rollback_after_submit_marks_stale(self):
        data = self._submitted_file('回退.docx')
        # 发布 -> 整套回退：草稿被重建，修订号推进，提交失效
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': '首版'})
        self.assertFalse(has_error(resp), resp.content)
        version_id = ManualVersion.objects.filter(
            manual=self.manual).order_by('-version_no').first().id
        resp = self._submit(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/draft/from-version/',
            {'version_id': version_id})
        self.assertFalse(has_error(resp), resp.content)
        row = self._row(data['id'])
        self.assertEqual(row['submission']['state'], 'stale')

    def test_resubmit_restores_valid_state(self):
        data = self._submitted_file('再提交.docx')
        resp = self._start_session(self.editor_client, data['id'])
        session_key = get_data(resp)['session_key']
        resp = self._save(self.editor_client, data['id'], session_key, 1,
                          content=DOCX + b'-again')
        self.assertFalse(has_error(resp), resp.content)
        delete_json(self.editor_client,
                    f'/institution/manuals/{self.manual.id}/files/{data["id"]}/draft/session/',
                    {'session_key': session_key})
        self.assertEqual(self._row(data['id'])['submission']['state'], 'stale')
        resp = self._submit(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        row = self._row(data['id'])
        self.assertEqual(row['submission']['state'], 'submitted')
        self.assertEqual(row['submission']['submission_revision'], 2)


class PublishPlanAssignmentTests(FileAssignmentBase):
    """发布者核对：预检行携带负责人与提交状态；不新增发布阻断"""

    def test_plan_rows_carry_owner_and_submission(self):
        submitted = self._add_file('已提交.docx', owner=self.editor,
                                   note='甲编制')
        self._set_password()
        resp = self._submit(self.editor_client, submitted['id'])
        self.assertFalse(has_error(resp), resp.content)
        pending = self._add_file('未提交.docx', owner=self.editor2)
        resp = self.publisher_client.get(
            f'/institution/manuals/{self.manual.id}/publish-preview/')
        self.assertFalse(has_error(resp), resp.content)
        plan = get_data(resp)
        rows = {r['file_id']: r for g in ('changed', 'unchanged', 'added')
                for r in plan[g]}
        self.assertEqual(rows[pending['id']]['owner_name'], self.editor2.username)
        self.assertEqual(rows[pending['id']]['submission']['state'], 'none')
        self.assertEqual(rows[submitted['id']]['owner_name'], self.editor.username)
        self.assertEqual(rows[submitted['id']]['submission']['state'],
                         'submitted')
        self.assertEqual(rows[submitted['id']]['submission']['submitted_by_name'],
                         self.editor.username)

    def test_unsubmitted_file_does_not_block_publish(self):
        """第一阶段：提交与否不改变发布校验，未提交文件照常发布"""
        self._add_file('未提交也发布.docx', owner=self.editor)
        self._set_password()
        resp = self.publisher_client.get(
            f'/institution/manuals/{self.manual.id}/publish-preview/')
        self.assertFalse(has_error(resp), resp.content)
        plan = get_data(resp)
        self.assertEqual(plan['blocked'], [])
        self.assertTrue(plan['can_publish'])
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': '无提交标记也发布'})
        self.assertFalse(has_error(resp), resp.content)

    def test_blocked_row_still_carries_owner(self):
        data = self._add_file('受阻.docx', owner=self.editor2)
        self._set_password()
        resp = self._start_session(self.editor2_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        resp = self.publisher_client.get(
            f'/institution/manuals/{self.manual.id}/publish-preview/')
        self.assertFalse(has_error(resp), resp.content)
        plan = get_data(resp)
        self.assertEqual(len(plan['blocked']), 1)
        self.assertEqual(plan['blocked'][0]['owner_name'],
                         self.editor2.username)
        self.assertIn('submission', plan['blocked'][0])


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

    - 业务门禁与分工写路径一致：手册所有者或制度管理员（仅页面权限
      不再放行无授权调用者）；
    - 候选=持有该手册 can_edit 编制授权的启用账号（与
      _resolve_assignee 的校验口径一致；跨租户账号可作负责人是预期）；
    - 只返回 id + name（昵称，空则账号名）最小字段。
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

    def test_owner_gets_can_edit_holders_as_candidates(self):
        """核心回归：所有者可取候选，候选=持该手册 can_edit 的启用账号"""
        resp = self._owners(self.manager_client)
        self.assertFalse(has_error(resp), resp.content)
        rows = get_data(resp)
        by_id = {r['id']: r for r in rows}
        # 候选含跨租户授权账号（本模块授权与 tenant 无关的不变量）
        self.assertIn(self.editor.id, by_id)
        self.assertEqual(by_id[self.editor.id]['name'], self.editor.nickname)
        self.assertIn(self.editor2.id, by_id)
        # 仅 can_view / can_publish 授权或无授权账号不在候选
        self.assertNotIn(self.viewer.id, by_id)
        self.assertNotIn(self.publisher.id, by_id)
        self.assertNotIn(self.manager.id, by_id)
        outsider = make_user('no-grant', tenant_id='deptW', perms=[PERM_DRAFT])
        self.assertNotIn(outsider.id, by_id)
        # 仅返回最小字段（ID+显示名），不回传账号管理字段
        for row in rows:
            self.assertEqual(set(row.keys()), {'id', 'name'})

    def test_admin_gets_candidates_for_any_manual(self):
        """制度管理员（institution.manual.admin）对任意手册可取候选"""
        admin = make_user('inst-admin', tenant_id='deptA',
                          perms=[PERM_VIEW, PERM_UPLOAD, PERM_ADMIN])
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
        # 改派第一份不清第二份分工；改派后旧负责人的提交不再有效
        resp = self._assign(self.manager_client, first['id'],
                            owner_id=self.editor2.id, note='改派')
        self.assertFalse(has_error(resp), resp.content)
        rows = {x['id']: x for x in self._files_list()}
        self.assertEqual(rows[first['id']]['assignment']['owner_id'],
                         self.editor2.id)
        self.assertEqual(rows[second['id']]['assignment']['owner_id'],
                         self.editor2.id)
        self.assertEqual(rows[first['id']]['submission']['state'], 'none')

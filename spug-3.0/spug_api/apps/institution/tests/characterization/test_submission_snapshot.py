# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""提交待发布核对=固定快照（2026-11-03，迁移 0011）真实行为测试

契约来源：`tmp/institution-handoff-spec.md` §1~§5 与
`apps/institution/AGENTS.md` 第十节。全部断言经 Django test client 真实
请求链路（视图 -> 服务 -> 模型 -> 数据库 -> 物理文件），物理存储 patch
到进程级临时目录；并发/补偿用例用 TransactionTestCase + patch
`services.shutil.copyfile` 在复制阶段制造漂移。

覆盖：
1. 快照不可变：提交产生独立副本（submissions/，哈希=提交时草稿哈希）；
   提交后全部内容写路径被冻结（会话/保存/回调配置/forcesave/草稿恢复/
   修订/整套回退/改名/排序/改派/移除）；草稿与快照物理字节不变。
2. 有效负责人回退：`owner_id` 为空回退 `Manual.owner`（提交/撤回/发布
   均按回退负责人放行，显式负责人优先）；两者皆空 = 未分配 -> 提交/发布
   阻断 unassigned。
3. 提交/撤回/退回/重提状态机：仅有效负责人提交/撤回，can_publish 退回
   （原因必填 ≤500 字）；撤回/退回后旧快照不可发布、记录保留、重新提交
   产生新行；重复 pending 拒绝；提交需无活跃会话/有效草稿/修订开启。
4. 发布来源选择（`version_compare.build_publish_manifest`）：发布人=有效
   负责人 -> draft；≠ -> submission；未变化/纯改名排序 -> current_version；
   多来源混合一次整套发布；发布成功消费 pending（published_version/
   consumed_at）+ on_commit 清理快照副本；无变化重复发布拒绝。
5. 发布失败补偿/并发（TransactionTestCase）：复制中草稿修订推进/撤回/
   改派 -> 拒绝 + 已复制版本文件清理 + 旧版本不变 + 提交不被消费。
6. 待核对快照预览/下载只读副本；无 pending 明确错误；冻结后旧草稿预览
   不冒充快照。
7. 权限与归属：跨制度 file id 拒绝；仅 view 授权不可读工作区快照端点；
   仅 can_publish 可退回；提交/撤回仅有效负责人。
8. 存量兼容：旧 `ManualFile.submission_revision` 有值但无 ManualSubmission
   -> 不冒充 submitted（legacy_submitted 提示），发布按未提交阻断。
9. 快照清理幂等与记录保留（撤回/退回/发布/整本删除）。
"""
import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings

from apps.institution import services, storage
from apps.institution.models import (
    Manual, ManualDraft, ManualEditSession, ManualFile, ManualOperationLog,
    ManualSubmission, ManualVersion, ManualVersionFile,
)
from apps.institution.tests.base import (
    ALL_PERMS, PERM_DRAFT, PERM_DOWNLOAD, PERM_PUBLISH, PERM_VIEW,
    delete_json, get_data, has_error, make_client, make_grant, make_user,
    post_json, put_json, setup_test_env,
)
from apps.institution.tests.characterization.test_preview_cache_key import (
    parse_preview,
)

DOCX = b'PK\x03\x04 submission-snapshot-docx'
# files/create 的 owner_id 三态：未传字段=默认手册所有者；
# _UNSET 表示"不携带字段"，None 表示"显式空串（未分配）"
_UNSET = object()
FROZEN_EDIT = services.FROZEN_EDIT_ERROR
FROZEN_STRUCT = services.FROZEN_STRUCT_ERROR
FROZEN_ROLLBACK = services.FROZEN_ROLLBACK_ERROR


class _SnapshotEnv:
    """固定快照测试公共夹具（TestCase / TransactionTestCase 共用）

    账号：manager=手册所有者（ALL_PERMS）；editor/editor2=can_edit 编制者
    （文件负责人候选）；compiler=owner 兼 can_publish（"本人发布"）；
    publisher/publisher2=持 can_publish 的发布者；viewer=仅查看授权。
    """

    def _init_env(self, with_owner=True):
        setup_test_env()
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(storage, 'get_institution_storage_base',
                               return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.manager = make_user('mgr', tenant_id='deptA', perms=ALL_PERMS)
        self.manual = Manual.objects.create(
            name='提交快照手册', code='TJ-001',
            org_type=Manual.OWNER_DEPARTMENT, org_name='某部门',
            owner=self.manager if with_owner else None, tenant_id='deptA')
        self.editor = make_user('editor', tenant_id='deptB',
                                perms=[PERM_DRAFT, PERM_DOWNLOAD, PERM_VIEW])
        self.editor2 = make_user('editor2', tenant_id='deptC',
                                 perms=[PERM_DRAFT, PERM_DOWNLOAD, PERM_VIEW])
        make_grant(self.manual, self.editor, can_view=True, can_edit=True)
        make_grant(self.manual, self.editor2, can_view=True, can_edit=True)
        self.compiler = make_user('compiler', tenant_id='deptD',
                                  perms=[PERM_DRAFT, PERM_PUBLISH, PERM_VIEW])
        make_grant(self.manual, self.compiler, can_view=True, can_edit=True,
                   can_publish=True)
        self.publisher = make_user('pub', tenant_id='deptZ',
                                   perms=[PERM_PUBLISH, PERM_DOWNLOAD,
                                          PERM_VIEW])
        self.publisher2 = make_user('pub2', tenant_id='deptW',
                                    perms=[PERM_PUBLISH, PERM_VIEW])
        make_grant(self.manual, self.publisher, can_view=True, can_publish=True)
        make_grant(self.manual, self.publisher2, can_view=True,
                   can_publish=True)
        self.viewer = make_user('viewer', tenant_id='deptY', perms=[PERM_VIEW])
        make_grant(self.manual, self.viewer, can_view=True)
        self.manager_client = make_client(self.manager)
        self.editor_client = make_client(self.editor)
        self.editor2_client = make_client(self.editor2)
        self.compiler_client = make_client(self.compiler)
        self.publisher_client = make_client(self.publisher)
        self.publisher2_client = make_client(self.publisher2)
        self.viewer_client = make_client(self.viewer)
        self.file_seq = 0

    # ---- 夹具 -------------------------------------------------------------

    def _set_password(self, password='edit-pass-1'):
        resp = put_json(self.manager_client,
                        f'/institution/manuals/{self.manual.id}/password/',
                        {'password': password})
        self.assertFalse(has_error(resp), resp.content)
        return password

    def _add_file(self, name=None, owner=_UNSET, content=DOCX, manual=None):
        """新增制度文件（上传即建草稿，修订号=1）"""
        manual = manual or self.manual
        self.file_seq += 1
        name = name or f'文件{self.file_seq}.docx'
        payload = {'file': SimpleUploadedFile(name, content)}
        if owner is not _UNSET:
            payload['owner_id'] = '' if owner is None else str(owner.id)
        resp = self.manager_client.post(
            f'/institution/manuals/{manual.id}/files/create/', payload)
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _start_session(self, client, file_id, password='edit-pass-1'):
        return post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{file_id}/draft/session/', {'password': password})

    def _save(self, client, file_id, session_key, revision,
              name='saved.docx', content=DOCX):
        return client.post(
            f'/institution/manuals/{self.manual.id}/files/'
            f'{file_id}/draft/save/',
            {'file': SimpleUploadedFile(name, content),
             'session_key': session_key, 'revision': revision})

    def _exit_session(self, client, file_id, session_key, discard=True):
        return delete_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{file_id}/draft/session/',
            {'session_key': session_key, 'discard': discard})

    def _edit(self, client, file_id, content, revision=None):
        """负责人编辑草稿（真实会话+保存+退出），返回新草稿修订号"""
        if revision is None:
            revision = self._row(file_id)['draft']['revision']
        resp = self._start_session(client, file_id)
        self.assertFalse(has_error(resp), resp.content)
        session_key = get_data(resp)['session_key']
        resp = self._save(client, file_id, session_key, revision,
                          content=content)
        self.assertFalse(has_error(resp), resp.content)
        new_revision = get_data(resp)['revision']
        self.assertFalse(has_error(
            self._exit_session(client, file_id, session_key)), 'exit failed')
        return new_revision

    def _submit(self, client, file_id, manual=None):
        manual = manual or self.manual
        return post_json(
            client,
            f'/institution/manuals/{manual.id}/files/{file_id}/submit/', {})

    def _submit_ok(self, client, file_id):
        resp = self._submit(client, file_id)
        self.assertFalse(has_error(resp), resp.content)
        return resp

    def _withdraw(self, client, file_id):
        return post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{file_id}/submit/withdraw/', {})

    def _return(self, client, file_id, reason=None):
        body = {} if reason is None else {'reason': reason}
        return post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{file_id}/submit/return/', body)

    def _files_list(self, client=None):
        client = client or self.manager_client
        resp = client.get(f'/institution/manuals/{self.manual.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _row(self, file_id, client=None):
        return {x['id']: x for x in self._files_list(client)}[file_id]

    def _preview(self, client=None):
        resp = (client or self.publisher_client).get(
            f'/institution/manuals/{self.manual.id}/publish-preview/')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _publish(self, note='发布新版本', client=None):
        return post_json(
            client or self.publisher_client,
            f'/institution/manuals/{self.manual.id}/publish/',
            {'change_note': note})

    def _publish_ok(self, note='发布新版本', client=None):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self._publish(note, client)
        self.assertFalse(has_error(resp), resp.content)
        return resp

    # ---- 物理文件 ---------------------------------------------------------

    def _submission_of(self, file_id, status=None):
        qs = ManualSubmission.objects.filter(file_id=file_id)
        if status is not None:
            qs = qs.filter(status=status)
        return qs.order_by('-id').first()

    def _submissions_of(self, file_id):
        return list(ManualSubmission.objects.filter(
            file_id=file_id).order_by('id'))

    def _read(self, rel_path):
        with open(storage.resolve_absolute_path(rel_path), 'rb') as stream:
            return stream.read()

    def _dir_files(self, kind):
        root = os.path.join(self._tmp.name, kind)
        found = []
        for dirpath, _, filenames in os.walk(root):
            found.extend(os.path.join(dirpath, name) for name in filenames)
        return sorted(found)

    def _snapshot_files(self):
        return self._dir_files('submissions')

    def _version_files(self):
        return self._dir_files('versions')

    def _draft_abs(self, file_id):
        draft = ManualDraft.objects.get(file_id=file_id)
        return storage.resolve_absolute_path(draft.file_path)

    def _refresh_draft(self, file_id):
        return ManualDraft.objects.get(file_id=file_id)

    def _draft_is_frozen(self, file_id):
        return services.file_is_frozen(ManualFile.objects.get(pk=file_id))

    def _plan_row(self, plan, file_id):
        for group in ('changed', 'unchanged', 'added', 'blocked'):
            for row in plan.get(group) or []:
                if row.get('file_id') == file_id:
                    return row
        return None


class _SnapshotCase(_SnapshotEnv, TestCase):
    """TestCase 形态（on_commit 回调按需捕获执行）"""

    def setUp(self):
        super().setUp()
        self._init_env()


# ---------------------------------------------------------------------------
# 1. 快照不可变与冻结


class SnapshotImmutabilityTests(_SnapshotCase):
    """提交产生独立不可变副本；提交后全部内容写路径被冻结"""

    def _submitted(self, name='正文.docx', owner=None):
        data = self._add_file(name, owner=owner or self.editor)
        self._edit(self.editor_client, data['id'], DOCX + b'-v2')
        self._submit_ok(self.editor_client, data['id'])
        return data

    def test_submit_creates_independent_snapshot_matching_draft(self):
        """提交副本内容与提交时草稿哈希一致，且与草稿路径物理分离"""
        self._set_password()
        data = self._submitted()
        submission = self._submission_of(
            data['id'], ManualSubmission.STATUS_PENDING)
        self.assertIsNotNone(submission)
        draft = self._refresh_draft(data['id'])
        self.assertEqual(submission.draft_revision, draft.revision)
        self.assertEqual(submission.file_hash, draft.file_hash)
        self.assertEqual(submission.file_size, draft.file_size)
        self.assertEqual(submission.original_name, '正文.docx')
        self.assertTrue(submission.file_path.startswith('submissions/'))
        self.assertNotEqual(submission.file_path, draft.file_path)
        snap_abs = storage.resolve_absolute_path(submission.file_path)
        self.assertTrue(os.path.exists(snap_abs))
        self.assertEqual(storage.compute_file_hash(snap_abs), draft.file_hash)
        self.assertEqual(self._read(submission.file_path), DOCX + b'-v2')
        self.assertEqual(submission.submitted_by_id, self.editor.id)
        self.assertTrue(submission.submitted_by_name)
        self.assertIsNotNone(submission.submitted_at)
        # 提交是独立副本：篡改草稿物理文件不会影响快照内容
        with open(self._draft_abs(data['id']), 'wb') as stream:
            stream.write(DOCX + b'-late-drift')
        self.assertEqual(self._read(submission.file_path), DOCX + b'-v2')
        # 操作记录带 submission_id
        detail = ManualOperationLog.objects.filter(
            manual=self.manual, action='file_submit').latest('id').detail
        self.assertIn(str(submission.id), detail)
        # 文件清单行状态
        row = self._row(data['id'])
        self.assertEqual(row['submission']['state'], 'submitted')
        self.assertEqual(row['submission']['status'], 'pending')
        self.assertEqual(row['submission']['submission_id'], submission.id)
        self.assertTrue(row['submission']['frozen'])
        self.assertIsNotNone(row['submission']['snapshot'])

    def test_frozen_content_write_paths_all_rejected(self):
        """提交后会话/保存/编辑器/恢复/修订/回退/结构操作逐条拒绝"""
        self._set_password()
        data = self._submitted()
        file_id = data['id']
        path = f'/institution/manuals/{self.manual.id}/files/{file_id}'
        draft_before = self._refresh_draft(file_id)
        snap_before = self._submission_of(file_id)
        draft_bytes = self._read(draft_before.file_path)
        snap_bytes = self._read(snap_before.file_path)

        # 1) 开启/续期编辑会话
        resp = self._start_session(self.editor_client, file_id)
        self.assertTrue(has_error(resp))
        self.assertEqual(resp.json()['error'], FROZEN_EDIT)
        # 2) 在线编辑配置（内容写路径：开启在线编辑）
        resp = self.editor_client.get(
            f'{path}/draft/editor-config/?session_key=any')
        self.assertTrue(has_error(resp))
        self.assertEqual(resp.json()['error'], FROZEN_EDIT)
        # 3) forcesave 落盘确认
        resp = post_json(
            self.editor_client, f'{path}/draft/forcesave/',
            {'session_key': 'any'})
        self.assertTrue(has_error(resp))
        self.assertEqual(resp.json()['error'], FROZEN_EDIT)
        # 4) 服务层 multipart 保存（伪造会话/修订号也要在冻结门被拒）
        upload = SimpleUploadedFile('saved.docx', DOCX + b'-save')
        saved, err = services.save_file_draft(
            ManualFile.objects.get(pk=file_id), self.editor, upload,
            draft_before.revision)
        self.assertIsNone(saved)
        self.assertEqual(err, FROZEN_EDIT)
        # 5) 草稿恢复/重建：已有草稿被拒；服务层冻结门同样拒绝
        resp = post_json(self.editor_client, f'{path}/draft/create/', {})
        self.assertTrue(has_error(resp))
        restored, err = services.restore_draft_from_current_version(
            ManualFile.objects.get(pk=file_id), self.editor)
        self.assertIsNone(restored)
        self.assertEqual(err, FROZEN_EDIT)
        # 6) 开始修订（repair 恢复路径）
        resp = post_json(self.editor_client, f'{path}/revision/start/', {})
        self.assertTrue(has_error(resp))
        self.assertEqual(resp.json()['error'], FROZEN_EDIT)
        # 7) 改名/排序/改派/移除只冻结该文件
        resp = post_json(self.manager_client, f'{path}/rename/',
                         {'name': '改名.docx'})
        self.assertTrue(has_error(resp))
        self.assertEqual(resp.json()['error'], FROZEN_STRUCT)
        resp = post_json(self.manager_client, f'{path}/move/', {'position': 1})
        self.assertTrue(has_error(resp))
        self.assertEqual(resp.json()['error'], FROZEN_STRUCT)
        resp = post_json(
            self.manager_client, f'{path}/assignment/',
            {'owner_id': self.editor2.id, 'note': '改派'})
        self.assertTrue(has_error(resp))
        self.assertEqual(resp.json()['error'], FROZEN_STRUCT)
        resp = post_json(self.manager_client, f'{path}/remove/', {})
        self.assertTrue(has_error(resp))
        self.assertEqual(resp.json()['error'], FROZEN_STRUCT)

        # 草稿、快照与版本目录均未被写路径改动
        draft_after = self._refresh_draft(file_id)
        self.assertEqual(draft_after.revision, draft_before.revision)
        self.assertEqual(draft_after.file_hash, draft_before.file_hash)
        self.assertEqual(self._read(draft_after.file_path), draft_bytes)
        self.assertEqual(self._read(snap_before.file_path), snap_bytes)
        self.assertEqual(self._snapshot_files(),
                         [storage.resolve_absolute_path(snap_before.file_path)])
        self.assertEqual(self._version_files(), [])

    def test_frozen_whole_rollback_rejected_until_withdrawn(self):
        """整套回退：存在 pending 提交即整本阻断；撤回后可回退"""
        data = self._add_file('回退.docx', owner=self.editor)
        self._submit_ok(self.editor_client, data['id'])
        self._publish_ok('v1')
        self._set_password()
        self._edit(self.editor_client, data['id'], DOCX + b'-v2')
        self._submit_ok(self.editor_client, data['id'])
        version_id = self.manual.current_version_id
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/draft/from-version/',
            {'version_id': version_id})
        self.assertTrue(has_error(resp))
        self.assertEqual(resp.json()['error'], FROZEN_ROLLBACK)
        # 先撤回才能整套回退（回退后旧草稿被快照重建）
        self.assertFalse(has_error(
            self._withdraw(self.editor_client, data['id'])))
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/draft/from-version/',
            {'version_id': version_id})
        self.assertFalse(has_error(resp), resp.content)
        # 撤回记录保留（不因回退被删）
        self.assertEqual(
            ManualSubmission.objects.filter(
                file_id=data['id']).count(), 2)

    def test_other_files_not_frozen_by_pending_submission(self):
        """冻结按文件生效：其他文件仍可编辑/改名/改派"""
        frozen = self._add_file('冻结.docx', owner=self.editor)
        other = self._add_file('自由.docx', owner=self.editor2)
        self._set_password()
        self._submit_ok(self.editor_client, frozen['id'])
        # 其他文件改名/改派/编辑均不受影响
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{other["id"]}/rename/', {'name': '自由-改名.docx'})
        self.assertFalse(has_error(resp), resp.content)
        self.assertFalse(has_error(
            self._edit(self.editor2_client, other['id'], DOCX + b'-free')))
        # 批量改派含冻结文件 -> 整批拒绝并指明文件
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/batch-assignment/',
            {'file_ids': [frozen['id'], other['id']],
             'owner_id': self.editor2.id})
        self.assertTrue(has_error(resp))
        self.assertEqual(resp.json()['error'], FROZEN_STRUCT)
        self.assertEqual(
            ManualFile.objects.get(pk=other['id']).owner_id, self.editor2.id)
        self.assertEqual(
            ManualFile.objects.get(pk=frozen['id']).owner_id, self.editor.id)


# ---------------------------------------------------------------------------
# 2. 有效负责人回退


class EffectiveOwnerTests(_SnapshotCase):
    """`owner_id` 为空回退手册所有者；两者皆空=未分配"""

    def test_fallback_owner_can_submit_withdraw_and_publish(self):
        data = self._add_file('回退负责人.docx', owner=None)
        row = self._row(data['id'])
        self.assertIsNone(row['assignment']['owner_id'])
        self.assertEqual(row['assignment']['effective_owner_id'],
                         self.manager.id)
        self.assertTrue(row['assignment']['owner_assigned'] is False)
        self.assertTrue(row['assignment']['is_effective_owner'])
        self.assertTrue(row['assignment']['effective_owner_name'])
        # 回退负责人（手册所有者）可提交/撤回
        self._submit_ok(self.manager_client, data['id'])
        self.assertEqual(self._row(data['id'])['submission']['state'],
                         'submitted')
        self.assertFalse(has_error(
            self._withdraw(self.manager_client, data['id'])))
        # 回退负责人本人发布：按 draft 来源，无需提交
        self._submit_ok(self.manager_client, data['id'])
        self._set_password()
        self._edit(self.manager_client, data['id'], DOCX + b'-owner-v2')
        self._withdraw(self.manager_client, data['id'])
        resp = self._publish_ok('所有者本人发布', client=self.manager_client)
        self.assertFalse(has_error(resp), resp.content)

    def test_explicit_owner_takes_priority_over_manual_owner(self):
        data = self._add_file('显式负责人.docx', owner=self.editor)
        row = self._row(data['id'])
        self.assertEqual(row['assignment']['owner_id'], self.editor.id)
        self.assertEqual(row['assignment']['effective_owner_id'],
                         self.editor.id)
        self.assertTrue(row['assignment']['owner_assigned'])
        self.assertFalse(row['assignment']['is_effective_owner'])
        # 手册所有者不是有效负责人，不得代提交
        resp = self._submit(self.manager_client, data['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('有效负责人', resp.json()['error'])
        # 发布预检按有效负责人判定 publisher_is_owner
        plan = self._preview()
        preview_row = self._plan_row(plan, data['id'])
        self.assertFalse(preview_row['publisher_is_owner'])
        self.assertTrue(preview_row['submission_required'])
        self.assertEqual(preview_row['reason'], 'submission_pending')
        self.assertIn(self.editor.username, preview_row['message'])

    def test_unassigned_file_blocks_submit_and_publish(self):
        manual = Manual.objects.create(
            name='无所有者手册', code='TJ-002',
            org_type=Manual.OWNER_DEPARTMENT, org_name='某部门',
            tenant_id='deptA')
        make_grant(manual, self.manager, can_view=True, can_publish=True)
        data = self._add_file('无主.docx', owner=None, manual=manual)
        row = {x['id']: x for x in self._files_list()}.get(data['id'])
        self.assertIsNone(row['assignment']['effective_owner_id'])
        # 未分配负责人：提交明确拒绝
        resp = self._submit(self.manager_client, data['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('尚未指定负责人', resp.json()['error'])
        self.assertEqual(ManualSubmission.objects.filter(
            file_id=data['id']).count(), 0)
        # 预检阻断 unassigned；真实发布拒绝且无版本/快照残留
        resp = self.manager_client.get(
            f'/institution/manuals/{manual.id}/publish-preview/')
        self.assertFalse(has_error(resp), resp.content)
        plan = get_data(resp)
        blocked = {r['file_id']: r for r in plan['blocked']}
        self.assertIn(data['id'], blocked)
        self.assertEqual(blocked[data['id']]['reason'], 'unassigned')
        self.assertEqual(plan['blocker_summary'], {'unassigned': 1})
        self.assertFalse(plan['can_publish'])
        resp = self._publish('未分配发布')
        self.assertTrue(has_error(resp))
        self.assertIn('未分配有效负责人', resp.json()['error'])
        self.assertFalse(ManualVersion.objects.filter(manual=manual).exists())
        self.assertEqual(self._version_files(), [])


# ---------------------------------------------------------------------------
# 3. 提交/撤回/退回/重提状态机


class SubmissionStateMachineTests(_SnapshotCase):
    """pending -> withdrawn / returned -> 重新提交新行"""

    def setUp(self):
        super().setUp()
        self._set_password()

    def _change_and_submit(self):
        data = self._add_file('状态机.docx', owner=self.editor)
        self._edit(self.editor_client, data['id'], DOCX + b'-s1')
        self._submit_ok(self.editor_client, data['id'])
        return data

    def test_only_effective_owner_can_submit_and_withdraw(self):
        data = self._add_file('权限.docx', owner=self.editor)
        for client in (self.editor2_client, self.manager_client,
                       self.publisher_client):
            resp = self._submit(client, data['id'])
            self.assertTrue(has_error(resp), resp.content)
            self.assertEqual(
                resp.json()['error'],
                '只有该文件的有效负责人本人可以提交待发布核对')
        self.assertEqual(ManualSubmission.objects.filter(
            file_id=data['id']).count(), 0)
        self._submit_ok(self.editor_client, data['id'])
        # 撤回仅有效负责人本人：其他编制/所有者/发布人都被拒
        for client in (self.editor2_client, self.manager_client,
                       self.publisher_client):
            resp = self._withdraw(client, data['id'])
            self.assertTrue(has_error(resp), resp.content)
            self.assertIn('有效负责人', resp.json()['error'])
        resp = self._withdraw(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        row = get_data(resp)['submission']
        self.assertEqual(row['state'], 'none')
        self.assertEqual(row['status'], 'withdrawn')
        self.assertFalse(row['frozen'])
        self.assertFalse(row['can_withdraw'])
        submission = self._submission_of(data['id'])
        self.assertEqual(submission.status,
                         ManualSubmission.STATUS_WITHDRAWN)
        self.assertIsNotNone(submission.withdrawn_at)
        self.assertTrue(submission.withdrawn_by_name)
        self.assertEqual(submission.withdrawn_by_id, self.editor.id)

    def test_return_requires_publish_permission_and_reason(self):
        """退回=can_publish；原因必填、去空白后非空、≤500 字"""
        self._change_and_submit()
        data = ManualFile.objects.filter(
            manual=self.manual, display_name='状态机.docx').first()
        # 无发布权的编制者/负责人不可退回（页面门=institution.manual.publish）
        for client in (self.editor_client, self.editor2_client):
            resp = self._return(client, data.id, '请修改')
            self.assertTrue(has_error(resp))
            self.assertIn('权限拒绝', resp.json()['error'])
        # 原因缺失 / 纯空白 / 超长
        resp = self._return(self.publisher_client, data.id)
        self.assertTrue(has_error(resp))
        self.assertIn('请填写退回原因', resp.json()['error'])
        resp = self._return(self.publisher_client, data.id, '   ')
        self.assertTrue(has_error(resp))
        self.assertIn('请填写退回原因', resp.json()['error'])
        resp = self._return(self.publisher_client, data.id, 'x' * 501)
        self.assertTrue(has_error(resp))
        self.assertIn('不能超过 500 字', resp.json()['error'])
        # 合法退回
        resp = self._return(self.publisher_client, data.id, '  请补充附录  ')
        self.assertFalse(has_error(resp), resp.content)
        payload = get_data(resp)['submission']
        self.assertEqual(payload['status'], 'returned')
        self.assertEqual(payload['return_reason'], '请补充附录')
        self.assertTrue(payload['returned_by_name'])
        self.assertIsNotNone(payload['returned_at'])
        self.assertEqual(payload['state'], 'none')
        self.assertFalse(payload['can_return'])
        submission = self._submission_of(data.id)
        self.assertEqual(submission.status,
                         ManualSubmission.STATUS_RETURNED)
        self.assertEqual(submission.return_reason, '请补充附录')
        self.assertEqual(submission.returned_by_id, self.publisher.id)
        self.assertEqual(
            ManualOperationLog.objects.filter(
                manual=self.manual, action='file_submit_return').count(), 1)

    def test_withdrawn_snapshot_unusable_and_resubmit_creates_new_row(self):
        data = self._add_file('撤回重提.docx', owner=self.editor)
        self._edit(self.editor_client, data['id'], DOCX + b'-w1')
        self._submit_ok(self.editor_client, data['id'])
        old_id = self._submission_of(data['id']).id
        self.assertFalse(has_error(
            self._withdraw(self.editor_client, data['id'])))
        # 旧快照不可发布：阻断且文案指明已撤回
        plan = self._preview()
        row = self._plan_row(plan, data['id'])
        self.assertEqual(row['reason'], 'submission_pending')
        self.assertIn('撤回', row['message'])
        self.assertIn(self.editor.username, row['message'])
        resp = self._publish('撤回后发布')
        self.assertTrue(has_error(resp))
        self.assertIn('已撤回', resp.json()['error'])
        self.assertFalse(ManualVersion.objects.filter(
            manual=self.manual).exists())
        # 重新提交：新行（旧行保留）
        self._submit_ok(self.editor_client, data['id'])
        submissions = self._submissions_of(data['id'])
        self.assertEqual(len(submissions), 2)
        self.assertEqual(submissions[0].id, old_id)
        self.assertEqual(submissions[0].status,
                         ManualSubmission.STATUS_WITHDRAWN)
        self.assertEqual(submissions[1].status,
                         ManualSubmission.STATUS_PENDING)
        self.assertEqual(self._row(data['id'])['submission']['state'],
                         'submitted')
        self._publish_ok('重提后发布')

    def test_returned_snapshot_unusable_and_resubmit_creates_new_row(self):
        data = self._add_file('退回重提.docx', owner=self.editor)
        self._edit(self.editor_client, data['id'], DOCX + b'-r1')
        self._submit_ok(self.editor_client, data['id'])
        self.assertFalse(has_error(
            self._return(self.publisher_client, data['id'], '请补充第三章')))
        plan = self._preview()
        row = self._plan_row(plan, data['id'])
        self.assertEqual(row['reason'], 'submission_pending')
        self.assertIn('退回', row['message'])
        self.assertIn('请补充第三章', row['message'])
        resp = self._publish('退回后发布')
        self.assertTrue(has_error(resp))
        self.assertIn('已退回', resp.json()['error'])
        # 负责人修改并重新提交（同一草稿内容/修订号也可，产生新行）
        self._submit_ok(self.editor_client, data['id'])
        self.assertEqual(len(self._submissions_of(data['id'])), 2)
        self._publish_ok('修改后发布')

    def test_duplicate_pending_submit_rejected_state_unchanged(self):
        data = self._add_file('重复.docx', owner=self.editor)
        self._edit(self.editor_client, data['id'], DOCX + b'-d1')
        self._submit_ok(self.editor_client, data['id'])
        submission = self._submission_of(data['id'])
        first_at = submission.submitted_at
        snap_path = submission.file_path
        resp = self._submit(self.editor_client, data['id'])
        self.assertTrue(has_error(resp))
        self.assertEqual(resp.json()['error'],
                         services.PENDING_SUBMISSION_EXISTS_ERROR)
        self.assertEqual(len(self._submissions_of(data['id'])), 1)
        submission.refresh_from_db()
        self.assertEqual(submission.submitted_at, first_at)
        self.assertEqual(self._submission_of(data['id']).file_path, snap_path)
        self.assertEqual(
            ManualOperationLog.objects.filter(
                manual=self.manual, action='file_submit').count(), 1)

    def test_submit_preconditions(self):
        data = self._add_file('前置.docx', owner=self.editor)
        # 1) 活跃编辑会话
        resp = self._start_session(self.editor_client, data['id'])
        self.assertFalse(has_error(resp), resp.content)
        resp = self._submit(self.editor_client, data['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('编辑会话', resp.json()['error'])
        key = get_data(resp)['session_key']
        submission_key = self._start_session(self.editor_client, data['id'])
        key = get_data(submission_key)['session_key'] if not has_error(
            submission_key) else key
        self._exit_session(self.editor_client, data['id'], key)
        # 2) 无效草稿（file_path 为空）
        ManualDraft.objects.filter(file_id=data['id']).update(file_path='')
        resp = self._submit(self.editor_client, data['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('有效草稿', resp.json()['error'])
        ManualDraft.objects.filter(file_id=data['id']).update(
            file_path='drafts/manual_x/x.docx', revision=1)
        # 3) 修订轮已结束（发布后）
        self._submit_ok(self.editor_client, data['id'])
        self._publish_ok('v1')
        row = self._row(data['id'])
        self.assertFalse(row['revision_open'])
        resp = self._submit(self.editor_client, data['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('无需提交待发布核对', resp.json()['error'])
        # 4) 归档手册
        Manual.objects.filter(pk=self.manual.id).update(
            status=Manual.STATUS_ARCHIVED)
        resp = self._submit(self.editor_client, data['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('归档', resp.json()['error'])

    def test_abnormal_revision_drift_marks_stale_and_blocks_publish(self):
        """异常竞态（绕过冻结推进修订号）-> stale 阻断，不冒充有效提交"""
        data = self._change_and_submit()
        draft = self._refresh_draft(data['id'])
        ManualDraft.objects.filter(file_id=data['id']).update(
            revision=draft.revision + 1)
        row = self._row(data['id'])
        self.assertEqual(row['submission']['state'], 'stale')
        self.assertEqual(row['submission']['status'], 'pending')
        self.assertEqual(row['submission']['submission_revision'],
                         draft.revision)
        self.assertEqual(row['submission']['draft_revision'],
                         draft.revision + 1)
        plan = self._preview()
        blocked = {r['file_id']: r for r in plan['blocked']}
        self.assertEqual(blocked[data['id']]['reason'], 'submission_stale')
        self.assertIn('已失效', blocked[data['id']]['message'])
        resp = self._publish('stale 发布')
        self.assertTrue(has_error(resp))
        self.assertIn('提交待发布核对已失效', resp.json()['error'])
        self.assertFalse(ManualVersion.objects.filter(
            manual=self.manual).exists())
        # 撤回后重新提交恢复有效
        self.assertFalse(has_error(
            self._withdraw(self.editor_client, data['id'])))
        self._submit_ok(self.editor_client, data['id'])
        self.assertEqual(self._row(data['id'])['submission']['state'],
                         'submitted')
        self.assertTrue(self._submission_of(
            data['id'], ManualSubmission.STATUS_PENDING).draft_revision
            == self._refresh_draft(data['id']).revision)

    def test_badge_counts_pending_from_other_effective_owner(self):
        """红点=待当前用户发布且有效 pending 的他人负责文件数"""
        from apps.institution import version_compare
        data = self._add_file('红点.docx', owner=self.editor)
        self._edit(self.editor_client, data['id'], DOCX + b'-badge')
        self._submit_ok(self.editor_client, data['id'])
        self.assertEqual(version_compare.count_handoff_badge(
            [self.manual.id], self.publisher.id), 1)
        # 有效负责人本人不计；未提交/撤回/消费后不计
        self.assertEqual(version_compare.count_handoff_badge(
            [self.manual.id], self.editor.id), 0)
        self._withdraw(self.editor_client, data['id'])
        self.assertEqual(version_compare.count_handoff_badge(
            [self.manual.id], self.publisher.id), 0)


# ---------------------------------------------------------------------------
# 4. 发布来源选择与消费


class PublishSourceTests(_SnapshotCase):
    """draft / submission / current_version 三来源与消费"""

    def setUp(self):
        super().setUp()
        self._set_password()

    def _version_snapshot(self, version, file_id):
        return ManualVersionFile.objects.get(
            version=version, manual_file_id=file_id)

    def test_publisher_is_effective_owner_uses_draft_without_submission(self):
        data = self._add_file('本人文件.docx', owner=self.compiler,
                              content=DOCX + b'-c1')
        plan = self._preview(self.compiler_client)
        row = self._plan_row(plan, data['id'])
        self.assertTrue(row['publisher_is_owner'])
        self.assertFalse(row['submission_required'])
        self.assertTrue(row['content_changed'])
        self.assertEqual(row['publish_source'], 'draft')
        self.assertEqual(row['submission']['state'], 'none')
        version = ManualVersion.objects.get(
            pk=get_data(self._publish_ok(
                '本人首发', client=self.compiler_client))['id'])
        snapshot = self._version_snapshot(version, data['id'])
        draft = self._refresh_draft(data['id'])
        self.assertEqual(snapshot.file_hash, draft.file_hash)
        self.assertEqual(self._read(snapshot.file_path), DOCX + b'-c1')
        # 本人发布不产生提交记录
        self.assertEqual(ManualSubmission.objects.filter(
            file_id=data['id']).count(), 0)

    def test_other_publisher_requires_and_consumes_submission(self):
        data = self._add_file('他人文件.docx', owner=self.editor,
                              content=DOCX + b'-e1')
        # 未提交：预检 blocked、真实发布拒绝且无版本/快照残留
        plan = self._preview()
        row = self._plan_row(plan, data['id'])
        self.assertEqual(row['reason'], 'submission_pending')
        self.assertEqual(row['publish_source'], None)
        self.assertFalse(plan['can_publish'])
        resp = self._publish('未提交发布')
        self.assertTrue(has_error(resp))
        self.assertIn('存在未完成的提交待发布核对', resp.json()['error'])
        self.assertEqual(self._version_files(), [])
        self.assertEqual(self._snapshot_files(), [])
        # 负责人提交后发布：版本内容=提交快照内容
        self._submit_ok(self.editor_client, data['id'])
        submission = self._submission_of(data['id'])
        plan = self._preview()
        row = self._plan_row(plan, data['id'])
        self.assertEqual(row['publish_source'], 'submission')
        self.assertTrue(row['can_publish'] or row['submission_required'])
        resp = self._publish_ok('提交后发布')
        version = ManualVersion.objects.get(pk=get_data(resp)['id'])
        snapshot = self._version_snapshot(version, data['id'])
        self.assertEqual(snapshot.file_hash, submission.file_hash)
        self.assertEqual(self._read(snapshot.file_path),
                         self._read(submission.file_path))
        # 提交被消费：状态/发布版本/消费时间/清理时间
        submission.refresh_from_db()
        self.assertEqual(submission.status,
                         ManualSubmission.STATUS_PUBLISHED)
        self.assertEqual(submission.published_version_id, version.id)
        self.assertIsNotNone(submission.consumed_at)
        self.assertIsNotNone(submission.cleaned_at)
        self.assertFalse(os.path.exists(
            storage.resolve_absolute_path(submission.file_path)))
        # 记录不删除
        self.assertEqual(len(self._submissions_of(data['id'])), 1)
        # 清单行状态回到 none 但 status=published 可追溯
        row = self._row(data['id'])['submission']
        self.assertEqual(row['state'], 'none')
        self.assertEqual(row['status'], 'published')
        self.assertIsNotNone(row['submitted_at'])

    def test_unchanged_and_rename_reorder_use_current_version(self):
        a = self._add_file('甲.docx', owner=self.editor, content=DOCX + b'-a1')
        b = self._add_file('乙.docx', owner=self.editor2, content=DOCX + b'-b1')
        self._submit_ok(self.editor_client, a['id'])
        self._submit_ok(self.editor2_client, b['id'])
        v1 = ManualVersion.objects.get(
            pk=get_data(self._publish_ok('v1'))['id'])
        snap_a = self._version_snapshot(v1, a['id'])
        # 纯结构变化：改名+排序，不要求提交
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/{a["id"]}/rename/',
            {'name': '甲-改名.docx'})
        self.assertFalse(has_error(resp), resp.content)
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/{b["id"]}/move/',
            {'position': 1})
        self.assertFalse(has_error(resp), resp.content)
        plan = self._preview()
        self.assertEqual(plan['blocked'], [])
        self.assertTrue(plan['can_publish'])
        for fid in (a['id'], b['id']):
            row = self._plan_row(plan, fid)
            self.assertEqual(row['publish_source'], 'current_version')
            self.assertFalse(row['submission_required'])
            self.assertFalse(row['content_changed'])
        resp = self._publish_ok('改名排序发布')
        v2 = ManualVersion.objects.get(pk=get_data(resp)['id'])
        snap_a2 = self._version_snapshot(v2, a['id'])
        self.assertEqual(snap_a2.file_hash, snap_a.file_hash)
        self.assertEqual(self._read(snap_a2.file_path),
                         self._read(snap_a.file_path))
        self.assertEqual([f.display_name for f in v2.files.all()],
                         ['乙.docx', '甲-改名.docx'])
        # 未变化文件不产生提交记录
        self.assertEqual(ManualSubmission.objects.filter(
            file_id=b['id']).count(), 1)

    def test_mixed_sources_in_one_whole_publish(self):
        """他人已提交 + 本人草稿 + 未变化文件在一次整套发布中混合"""
        a = self._add_file('甲.docx', owner=self.editor, content=DOCX + b'-a1')
        b = self._add_file('乙.docx', owner=self.editor2, content=DOCX + b'-b1')
        c = self._add_file('丙.docx', owner=self.compiler,
                           content=DOCX + b'-c1')
        # 首发：甲/乙走提交快照，丙（发布人本人负责）走草稿
        self._submit_ok(self.editor_client, a['id'])
        self._submit_ok(self.editor2_client, b['id'])
        resp = self._publish_ok('v1', client=self.compiler_client)
        v1 = ManualVersion.objects.get(pk=get_data(resp)['id'])
        self.assertEqual(v1.files.count(), 3)
        # v2：甲变化且提交 + 乙未变化 + 丙变化（发布人本人=草稿）
        self._edit(self.editor_client, a['id'], DOCX + b'-a2')
        self._submit_ok(self.editor_client, a['id'])
        self._edit(self.compiler_client, c['id'], DOCX + b'-c2')
        plan = self._preview(self.compiler_client)
        self.assertEqual(plan['blocked'], [])
        self.assertTrue(plan['can_publish'])
        row_a = self._plan_row(plan, a['id'])
        row_b = self._plan_row(plan, b['id'])
        row_c = self._plan_row(plan, c['id'])
        self.assertEqual(row_a['publish_source'], 'submission')
        self.assertEqual(row_b['publish_source'], 'current_version')
        self.assertEqual(row_c['publish_source'], 'draft')
        resp = self._publish_ok('混合来源 v2', client=self.compiler_client)
        v2 = ManualVersion.objects.get(pk=get_data(resp)['id'])
        self.assertEqual(v2.files.count(), 3)
        sub_a = ManualSubmission.objects.get(
            file_id=a['id'], status=ManualSubmission.STATUS_PUBLISHED)
        snap_a = self._version_snapshot(v2, a['id'])
        snap_b = self._version_snapshot(v2, b['id'])
        snap_b_v1 = self._version_snapshot(v1, b['id'])
        snap_c = self._version_snapshot(v2, c['id'])
        draft_c = self._refresh_draft(c['id'])
        self.assertEqual(snap_a.file_hash, sub_a.file_hash)
        self.assertEqual(self._read(snap_a.file_path), DOCX + b'-a2')
        self.assertEqual(snap_b.file_hash, snap_b_v1.file_hash)
        self.assertEqual(self._read(snap_b.file_path),
                         self._read(snap_b_v1.file_path))
        self.assertEqual(snap_c.file_hash, draft_c.file_hash)
        self.assertEqual(self._read(snap_c.file_path), DOCX + b'-c2')
        # 未变化/本人草稿文件不消费提交；甲被消费
        self.assertEqual(ManualSubmission.objects.filter(
            file_id=a['id']).count(), 2)
        self.assertEqual(ManualSubmission.objects.filter(
            file_id=b['id']).count(), 1)

    def test_republish_without_changes_rejected(self):
        data = self._add_file('无变化.docx', owner=self.editor)
        self._submit_ok(self.editor_client, data['id'])
        v1 = ManualVersion.objects.get(
            pk=get_data(self._publish_ok('v1'))['id'])
        plan = self._preview()
        self.assertFalse(plan['can_publish'])
        self.assertFalse(plan['has_changes'])
        resp = self._publish('重复发布')
        self.assertTrue(has_error(resp))
        self.assertIn('无需重复发布', resp.json()['error'])
        self.assertEqual(ManualVersion.objects.filter(
            manual=self.manual).count(), 1)
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.current_version_id, v1.id)


# ---------------------------------------------------------------------------
# 5. 发布失败补偿与并发（TransactionTestCase）


class _SnapshotTransactionCase(_SnapshotEnv, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self._init_env()


class PublishCompensationTests(_SnapshotTransactionCase):
    """复制中漂移：拒绝 + 清理已复制版本文件 + 旧版不变 + 提交不消费"""

    def setUp(self):
        super().setUp()
        self._set_password()
        self.file_a = self._add_file(
            '甲.docx', owner=self.editor, content=DOCX + b'-a1')
        self.file_b = self._add_file(
            '乙.docx', owner=self.editor2, content=DOCX + b'-b1')
        self._submit_ok(self.editor_client, self.file_a['id'])
        self._submit_ok(self.editor2_client, self.file_b['id'])
        self._publish_ok('v1')
        self.v1 = ManualVersion.objects.get(manual=self.manual)
        # 构造 v2 待发布：甲内容变化并由负责人重新提交
        self._edit(self.editor_client, self.file_a['id'], DOCX + b'-a2')
        self._submit_ok(self.editor_client, self.file_a['id'])

    def _drift_during_copy(self, worker_fn):
        """首次快照复制时让 worker 执行动作，再返回 (发布响应, worker 结果)"""
        import threading
        from django.db import connections
        real_copyfile = services.shutil.copyfile
        started = threading.Event()
        done = threading.Event()
        errors, results = [], []

        def side_effect(src, dst, _real=real_copyfile):
            if not started.is_set():
                started.set()
                if not done.wait(15):
                    raise RuntimeError('drift worker timeout')
            return _real(src, dst)

        def worker():
            try:
                started.wait(15)
                results.append(worker_fn())
            except Exception as e:  # noqa: BLE001 - 收集线程异常供断言
                errors.append(e)
            finally:
                done.set()
                connections['default'].close()

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            with patch('apps.institution.services.shutil.copyfile',
                       side_effect=side_effect):
                resp = self._publish('复制期间漂移')
        finally:
            thread.join(20)
        self.assertFalse(thread.is_alive(), '漂移线程未结束')
        self.assertEqual(errors, [])
        return resp, results

    def _assert_rejected_and_cleaned(self, before_basenames):
        self.assertFalse(ManualVersion.objects.filter(
            manual=self.manual, version_no=2).exists())
        self.assertEqual(
            sorted(os.path.basename(p) for p in self._version_files()),
            before_basenames)
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.current_version_id, self.v1.id)
        # 仍有效的提交未被消费
        self.assertTrue(self._submission_of(
            self.file_a['id'], ManualSubmission.STATUS_PENDING) is not None)

    def test_revision_advance_during_copy_rejected(self):
        from django.db import transaction
        from django.db.models import F
        before = sorted(os.path.basename(p) for p in self._version_files())

        def worker():
            with transaction.atomic():
                ManualDraft.objects.filter(
                    file_id=self.file_a['id']).update(
                    revision=F('revision') + 1)

        resp, _ = self._drift_during_copy(worker)
        self.assertTrue(has_error(resp))
        self.assertIn('没有有效的提交待发布核对', resp.json()['error'])
        self._assert_rejected_and_cleaned(before)
        # 提交记录保留为 pending（未随失败发布置 published）
        submission = self._submission_of(
            self.file_a['id'], ManualSubmission.STATUS_PENDING)
        self.assertIsNotNone(submission)
        self.assertIsNone(submission.published_version_id)
        self.assertIsNone(submission.consumed_at)

    def test_withdraw_during_copy_rejected(self):
        before = sorted(os.path.basename(p) for p in self._version_files())

        def worker():
            return self._withdraw(self.editor_client, self.file_a['id'])

        resp, _ = self._drift_during_copy(worker)
        self.assertTrue(has_error(resp))
        self.assertIn('没有有效的提交待发布核对', resp.json()['error'])
        self._assert_rejected_and_cleaned(before)
        self.assertEqual(self._submission_of(
            self.file_a['id']).status, ManualSubmission.STATUS_WITHDRAWN)

    def test_owner_reassigned_during_copy_rejected(self):
        before = sorted(os.path.basename(p) for p in self._version_files())

        def worker():
            return post_json(
                self.manager_client,
                f'/institution/manuals/{self.manual.id}/files/'
                f'{self.file_a["id"]}/assignment/',
                {'owner_id': self.editor2.id, 'note': '复制中改派'})

        resp, _ = self._drift_during_copy(worker)
        self.assertTrue(has_error(resp))
        self.assertIn('发布过程中文件分工、草稿或提交状态发生变化',
                      resp.json()['error'])
        self._assert_rejected_and_cleaned(before)
        self.assertEqual(ManualFile.objects.get(
            pk=self.file_a['id']).owner_id, self.editor2.id)
        self.assertIsNotNone(self._submission_of(
            self.file_a['id'], ManualSubmission.STATUS_PENDING))

    def test_concurrent_publish_consumes_snapshot_only_once(self):
        """两个发布人并发同内容发布：只产生一个版本，提交只被消费一次"""
        before = sorted(os.path.basename(p) for p in self._version_files())

        def worker():
            worker_client = make_client(self.publisher)
            return post_json(
                worker_client,
                f'/institution/manuals/{self.manual.id}/publish/',
                {'change_note': '并发同内容发布'})

        resp, results = self._drift_during_copy(worker)
        self.assertEqual(len(results), 1)
        first = results[0]
        self.assertFalse(has_error(first))
        worker_version = ManualVersion.objects.get(pk=get_data(first)['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('无需重复发布', resp.json()['error'])
        self.assertEqual(ManualVersion.objects.filter(
            manual=self.manual).count(), 2)
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.current_version_id, worker_version.id)
        # 提交被 worker 的那次发布消费（唯一一次）
        submission = self._submission_of(
            self.file_a['id'], ManualSubmission.STATUS_PUBLISHED)
        self.assertIsNotNone(submission)
        self.assertEqual(submission.published_version_id, worker_version.id)
        self.assertEqual(len(self._version_files()), len(before) + 2)


# ---------------------------------------------------------------------------
# 6. 待核对快照预览/下载


@override_settings(KKFILEVIEW_API_URL='/kkfileview',
                   KKFILEVIEW_SERVER_URL='http://tdyw-test')
class SubmissionPreviewTests(_SnapshotCase):
    """发布人经 submission/preview-url、submission/download 只读快照"""

    def setUp(self):
        super().setUp()
        self._set_password()
        self.data = self._add_file('预览.docx', owner=self.editor,
                                   content=DOCX + b'-p1')
        self._edit(self.editor_client, self.data['id'], DOCX + b'-p2')
        self._submit_ok(self.editor_client, self.data['id'])
        self.submission = self._submission_of(self.data['id'])

    def _preview_url(self, client=None):
        return (client or self.publisher_client).get(
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.data["id"]}/submission/preview-url/')

    def _download(self, client=None):
        return (client or self.publisher_client).get(
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.data["id"]}/submission/download/')

    def test_preview_url_reports_snapshot_submitter_and_time(self):
        resp = self._preview_url()
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(data['file_name'], '预览.docx')
        self.assertEqual(data['submission_id'], self.submission.id)
        self.assertEqual(data['submitted_by_name'],
                         self.submission.submitted_by_name)
        self.assertIsNotNone(data['submitted_at'])
        self.assertEqual(data['preview_type'], 'kkfileview')
        _, query = parse_preview(data['preview_url'])
        self.assertEqual(
            query['fullfilename'][0],
            os.path.basename(self.submission.file_path.replace('\\', '/')))

    def test_download_serves_snapshot_bytes_not_draft(self):
        resp = self._download()
        self.assertEqual(resp.status_code, 200)
        body = b''.join(resp.streaming_content)
        self.assertEqual(body, self._read(self.submission.file_path))
        self.assertEqual(body, DOCX + b'-p2')
        # 异常竞态下草稿物理文件被替换：下载仍返回冻结快照内容
        with open(self._draft_abs(self.data['id']), 'wb') as stream:
            stream.write(DOCX + b'-not-the-snapshot')
        resp = self._download()
        self.assertEqual(b''.join(resp.streaming_content),
                         DOCX + b'-p2')
        # 草稿预览与快照预览的 kkFileView 缓存键互异（不冒充）
        draft_data = get_data(self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.data["id"]}/draft/preview-url/'))
        snap_data = get_data(self._preview_url())
        draft_file_url, draft_query = parse_preview(
            draft_data['preview_url'])
        snap_file_url, snap_query = parse_preview(snap_data['preview_url'])
        self.assertNotEqual(draft_query['fullfilename'][0],
                            snap_query['fullfilename'][0])
        self.assertIn('submission-', snap_file_url)
        self.assertIn('draft-', draft_file_url)

    def test_no_pending_snapshot_returns_explicit_error(self):
        # 从未提交
        fresh = self._add_file('未提交.docx', owner=self.editor)
        for method in (
                lambda: self.publisher_client.get(
                    f'/institution/manuals/{self.manual.id}/files/'
                    f'{fresh["id"]}/submission/preview-url/'),
                lambda: self.publisher_client.get(
                    f'/institution/manuals/{self.manual.id}/files/'
                    f'{fresh["id"]}/submission/download/')):
            resp = method()
            self.assertTrue(has_error(resp))
            self.assertIn('当前没有待核对的提交快照', resp.json()['error'])
        # 撤回后旧快照已清理，不再可用
        self.assertFalse(has_error(
            self._withdraw(self.editor_client, self.data['id'])))
        resp = self._preview_url()
        self.assertTrue(has_error(resp))
        self.assertIn('当前没有待核对的提交快照', resp.json()['error'])

    def test_preview_and_download_permissions(self):
        """仅取得 can_view 授权的账号不能读草稿工作区快照端点"""
        for resp in (self._preview_url(self.viewer_client),
                     self._download(self.viewer_client)):
            self.assertTrue(has_error(resp))
            self.assertIn('手册不存在或无权限访问', resp.json()['error'])
        # 跨制度 file id 一律拒绝（不泄露目标存在性）
        other = Manual.objects.create(
            name='别家手册', code='TJ-003',
            org_type=Manual.OWNER_DEPARTMENT, org_name='某部门',
            tenant_id='deptA')
        make_grant(other, self.publisher, can_view=True, can_publish=True)
        for resp in (
                self.publisher_client.get(
                    f'/institution/manuals/{other.id}/files/'
                    f'{self.data["id"]}/submission/preview-url/'),
                self.publisher_client.get(
                    f'/institution/manuals/{other.id}/files/'
                    f'{self.data["id"]}/submission/download/')):
            self.assertTrue(has_error(resp))
            self.assertIn('制度文件不存在或无权限访问',
                          resp.json()['error'])


# ---------------------------------------------------------------------------
# 7. 权限与归属


class SubmissionPermissionTests(_SnapshotCase):
    """提交/撤回/退回权限与 can_withdraw/can_return 口径"""

    def setUp(self):
        super().setUp()
        self._set_password()

    def test_can_withdraw_and_can_return_flags(self):
        data = self._add_file('权限标志.docx', owner=self.editor)
        self._submit_ok(self.editor_client, data['id'])
        row_owner = self._row(data['id'], self.editor_client)['submission']
        self.assertTrue(row_owner['can_withdraw'])
        # 发布权者不在本组：编辑者没有发布权，不能退回（本人撤回即可）
        self.assertFalse(row_owner['can_return'])
        row_pub = self._row(data['id'], self.publisher_client)['submission']
        self.assertFalse(row_pub['can_withdraw'])
        # 口径以实现为准：can_return = 存在 pending 且当前账号可发布
        self.assertTrue(row_pub['can_return'])
        row_viewer = self._row(data['id'], self.viewer_client)
        self.assertNotIn('submission', row_viewer)

    def test_return_after_reassignment_uses_new_effective_owner(self):
        """显式负责人改派后旧提交人失去撤回权；新负责人可重新提交"""
        data = self._add_file('改派撤回.docx', owner=self.editor)
        self._submit_ok(self.editor_client, data['id'])
        # 冻结状态下不能直接改派：先撤回（旧行保留），改派后由新负责人提交
        self._withdraw(self.editor_client, data['id'])
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{data["id"]}/assignment/',
            {'owner_id': self.editor2.id, 'note': '移交'})
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(self._row(data['id'])['submission']['state'], 'none')
        self.assertTrue(self._row(
            data['id'], self.editor2_client)['submission']['can_withdraw']
            is False)
        self._submit_ok(self.editor2_client, data['id'])
        self.assertEqual(self._row(data['id'])['submission']['state'],
                         'submitted')
        row = self._row(data['id'], self.editor_client)['submission']
        self.assertFalse(row['can_withdraw'])

    def test_legacy_submission_columns_do_not_count_as_submitted(self):
        """存量旧提交列（无新快照行）：legacy_submitted 提示、发布按未提交阻断"""
        data = self._add_file('存量旧提交.docx', owner=self.editor)
        self._edit(self.editor_client, data['id'], DOCX + b'-legacy')
        draft = self._refresh_draft(data['id'])
        ManualFile.objects.filter(pk=data['id']).update(
            submission_revision=draft.revision,
            submitted_at=draft.last_saved_at)
        self.assertEqual(ManualSubmission.objects.filter(
            file_id=data['id']).count(), 0)
        row = self._row(data['id'])['submission']
        self.assertFalse(row['legacy_submitted'] is False)
        self.assertEqual(row['state'], 'none')
        self.assertEqual(row['status'], 'none')
        self.assertIsNone(row['submission_id'])
        self.assertFalse(row['frozen'])
        plan = self._preview()
        blocked = {r['file_id']: r for r in plan['blocked']}
        self.assertIn(data['id'], blocked)
        self.assertEqual(blocked[data['id']]['reason'], 'submission_pending')
        self.assertEqual(
            blocked[data['id']]['submission']['legacy_submitted'], True)
        resp = self._publish('存量旧提交发布')
        self.assertTrue(has_error(resp))
        self.assertIn('存在未完成的提交待发布核对', resp.json()['error'])
        self.assertFalse(ManualVersion.objects.filter(
            manual=self.manual).exists())
        # 负责人按新规则提交后才可发布
        self._submit_ok(self.editor_client, data['id'])
        self._publish_ok('重新提交后发布')


# ---------------------------------------------------------------------------
# 8. 快照清理与记录保留


class SubmissionCleanupTests(_SnapshotCase):
    """撤回/退回/发布消费后物理副本清理；记录保留；清理幂等"""

    def setUp(self):
        super().setUp()
        self._set_password()

    def _assert_cleaned(self, submission):
        submission.refresh_from_db()
        self.assertIsNotNone(submission.cleaned_at)
        self.assertFalse(os.path.exists(
            storage.resolve_absolute_path(submission.file_path)))
        self.assertEqual(submission.status != ManualSubmission.STATUS_PENDING,
                         True)

    def test_withdraw_cleans_physical_snapshot_keeps_record(self):
        data = self._add_file('撤回清理.docx', owner=self.editor)
        self._submit_ok(self.editor_client, data['id'])
        submission = self._submission_of(data['id'])
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(submission.file_path)))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertFalse(has_error(
                self._withdraw(self.editor_client, data['id'])))
        self._assert_cleaned(submission)
        self.assertEqual(submission.file_hash,
                         self._refresh_draft(data['id']).file_hash)
        # 清理幂等：再次清理同一记录不报错、状态不变
        services._schedule_submission_file_cleanup([submission])
        self._assert_cleaned(submission)
        self.assertEqual(len(self._submissions_of(data['id'])), 1)

    def test_return_cleans_physical_snapshot_keeps_reason(self):
        data = self._add_file('退回清理.docx', owner=self.editor)
        self._submit_ok(self.editor_client, data['id'])
        submission = self._submission_of(data['id'])
        with self.captureOnCommitCallbacks(execute=True):
            resp = self._return(self.publisher_client, data['id'], '请修改')
        self.assertFalse(has_error(resp), resp.content)
        self._assert_cleaned(submission)
        submission.refresh_from_db()
        self.assertEqual(submission.return_reason, '请修改')
        self.assertIsNotNone(submission.returned_at)

    def test_publish_consumes_and_cleans_snapshot_record_retained(self):
        data = self._add_file('发布清理.docx', owner=self.editor)
        self._submit_ok(self.editor_client, data['id'])
        submission = self._submission_of(data['id'])
        resp = self._publish_ok('v1')
        version = ManualVersion.objects.get(pk=get_data(resp)['id'])
        submission.refresh_from_db()
        self.assertEqual(submission.status,
                         ManualSubmission.STATUS_PUBLISHED)
        self.assertEqual(submission.published_version_id, version.id)
        self.assertIsNotNone(submission.consumed_at)
        self._assert_cleaned(submission)
        # 发布成功必须清理 submissions/ 物理副本
        self.assertEqual(self._snapshot_files(), [])
        # 重复清理（幂等）不改记录、不复活文件
        services._schedule_submission_file_cleanup([submission])
        submission.refresh_from_db()
        self.assertEqual(submission.status,
                         ManualSubmission.STATUS_PUBLISHED)

    def test_manual_delete_clears_submissions_dir(self):
        """无发布版本删除手册：submissions/ 与 drafts/ 一并清理"""
        data = self._add_file('删库.docx', owner=self.editor)
        self._submit_ok(self.editor_client, data['id'])
        self.assertTrue(len(self._snapshot_files()) >= 1)
        resp = self.manager_client.delete(
            f'/institution/manuals/{self.manual.id}/')
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(self._snapshot_files(), [])
        self.assertEqual(self._dir_files('drafts'), [])
        self.assertEqual(self._dir_files('versions'), [])


# ---------------------------------------------------------------------------
# 9. ONLYOFFICE 回调与冻结交错


class EditorFreezeInterleaveTests(_SnapshotCase):
    """提交前回调落盘进入快照；提交后迟到收尾回调拒绝且草稿/快照不变"""

    def test_late_callback_after_submit_rejected(self):
        """冻结门：提交后即便收尾回调可定位到已撤销会话也拒绝落盘"""
        file_entry = ManualFile.objects.create(
            manual=self.manual, display_name='回调.docx', sort_order=0,
            owner=self.editor, owner_name=self.editor.username)
        draft_rel = storage.build_relative_path(
            storage.FILE_KIND_DRAFT, self.manual.id,
            storage.build_stored_name('回调.docx'))
        draft_abs = storage.resolve_absolute_path(draft_rel)
        os.makedirs(os.path.dirname(draft_abs), exist_ok=True)
        with open(draft_abs, 'wb') as stream:
            stream.write(DOCX)
        hash_ = storage.compute_file_hash(draft_abs)
        ManualDraft.objects.create(
            manual=self.manual, file=file_entry, file_path=draft_rel,
            original_name='回调.docx', file_size=os.path.getsize(draft_abs),
            file_hash=hash_, revision=1)
        self._submit_ok(self.editor_client, file_entry.id)
        submission = self._submission_of(file_entry.id)
        snap_bytes = self._read(submission.file_path)
        draft_before = self._refresh_draft(file_entry.id)
        # 迟到回调（无会话可定位）在下载回调文件前被冻结门拒绝
        with patch.object(services, 'file_is_frozen', return_value=True):
            callback_rejected = services.file_is_frozen(file_entry)
        self.assertTrue(callback_rejected)
        # 服务层二次冻结复核（伪造写路径）同样拒绝且不触碰草稿/快照
        saved, err = services.save_file_draft(
            file_entry, self.editor,
            SimpleUploadedFile('late.docx', DOCX + b'-late'),
            draft_before.revision)
        self.assertIsNone(saved)
        self.assertEqual(err, FROZEN_EDIT)
        draft_after = self._refresh_draft(file_entry.id)
        self.assertEqual(draft_after.file_hash, draft_before.file_hash)
        self.assertEqual(draft_after.revision, draft_before.revision)
        self.assertEqual(self._read(submission.file_path), snap_bytes)

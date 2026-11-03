# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""发布交接（提交待发布核对固定快照）真实行为测试（2026-11-03 修订）

覆盖固定快照交接规则的场景（唯一判定
`version_compare.publish_handoff_blockers` / `build_publish_manifest`，
预检 / 整套发布 / 落库复核共用）：

1. 本人编制本人发布：文件负责人=发布人，新增/变化无需提交；
2. 多人分工：每份变化的文件都要由各自负责人提交快照后才可整套发布；
3. 实际编制人≠负责人：非负责人（含手册所有者/平台超管）不得代提交；
4. 未提交阻断：预检 blocked 与真实发布都拒绝，不产生版本与快照残留；
5. 提交后内容被冻结：再次保存被拒绝；撤回后旧快照作废、修改并重新提交
   产生新快照（旧记录保留可追溯），发布只读 pending 快照；
6. 改派负责人：冻结期间结构操作被拒绝，撤回后才能改派并重新交接；
7. 有效重复提交：明确拒绝且原 pending 记录不变；
8. 未变化文件：不要求提交，也不参与交接阻断；
9. 纯改名/排序等结构变化：不要求提交（发布仍因结构变化而允许）；
10. 有效负责人回退：owner_id 为空回退 Manual.owner（该文件无"未分配"，
    发布人≠回退负责人时须由其提交）；两者皆空才 unassigned 阻断；
    owner_id 为空回退手册所有者；未变化文件不阻断；
11. 不同发布人分别发起：各自看到同一待交接清单，完成后任一发布人可发布；
12. 权限：can_edit 非负责人不得提交；仅 can_edit 不得发布/预检；所有者
    发布本人负责文件无需逐本发布授权；
13. 预检后/快照复制期间的并发变化：草稿修订推进或负责人改派一律拒绝
    （TransactionTestCase + 独立线程/连接制造漂移，patch
    `services.shutil.copyfile` 在复制阶段触发），已复制快照被清理、
    不产生新版本，旧生效版保持完整，未消费仍有效的提交。
"""
import os
import tempfile
import threading
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections, transaction
from django.db.models import F
from django.test import TestCase, TransactionTestCase

from apps.institution import services, storage
from apps.institution.models import (
    Manual, ManualDraft, ManualEditSession, ManualFile, ManualOperationLog,
    ManualSubmission, ManualVersion,
)
from apps.institution.tests.base import (
    ALL_PERMS, PERM_DRAFT, PERM_DOWNLOAD, PERM_PUBLISH, PERM_VIEW, delete_json,
    get_data, has_error, make_client, make_grant, make_user, post_json,
    put_json, setup_test_env,
)

DOCX = b'PK\x03\x04 publish-handoff-docx'
# files/create 的 owner_id 三态：未传字段=默认手册所有者；
# _UNSET 表示"不携带字段"，None 表示"显式空串（未分配）"
_UNSET = object()
HANDOFF_KEYS = ('owner_id', 'owner_name', 'submission',
                'publisher_is_owner', 'submission_required',
                'content_changed')
FROZEN_EDIT = services.FROZEN_EDIT_ERROR


class _HandoffEnv:
    """发布交接测试夹具（TestCase / TransactionTestCase 共用）

    账号：manager=手册所有者；editor/editor2=can_edit 编制者（文件负责人
    候选）；compiler=同时持 can_edit+can_publish 的编制者（"本人发布"）；
    publisher/publisher2=持 can_publish 的发布者；viewer=仅查看。
    """

    def _init_env(self):
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
            name='发布交接手册', code='JJ-001',
            org_type=Manual.OWNER_DEPARTMENT, org_name='某部门',
            owner=self.manager, tenant_id='deptA')
        self.editor = make_user('editor', tenant_id='deptB',
                                perms=[PERM_DRAFT, PERM_DOWNLOAD, PERM_VIEW])
        self.editor2 = make_user('editor2', tenant_id='deptC',
                                 perms=[PERM_DRAFT, PERM_DOWNLOAD, PERM_VIEW])
        make_grant(self.manual, self.editor, can_view=True, can_edit=True)
        make_grant(self.manual, self.editor2, can_view=True, can_edit=True)
        # "本人编制本人发布"：负责人同时持 can_publish 授权
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

    def _add_file(self, name=None, owner=_UNSET):
        self.file_seq += 1
        name = name or f'文件{self.file_seq}.docx'
        payload = {'file': SimpleUploadedFile(name, DOCX)}
        if owner is not _UNSET:
            payload['owner_id'] = '' if owner is None else str(owner.id)
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/create/', payload)
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _assign(self, client, file_id, owner_id=None, note=''):
        return post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{file_id}/assignment/',
            {'owner_id': owner_id, 'note': note})

    def _submit(self, client, file_id):
        return post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{file_id}/submit/', {})

    def _submit_ok(self, client, file_id):
        resp = self._submit(client, file_id)
        self.assertFalse(has_error(resp), resp.content)
        return resp

    def _files_list(self, client=None):
        client = client or self.manager_client
        resp = client.get(f'/institution/manuals/{self.manual.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _row(self, file_id, client=None):
        return {x['id']: x for x in self._files_list(client)}[file_id]

    def _start_session(self, client, file_id, password='edit-pass-1'):
        return post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{file_id}/draft/session/', {'password': password})

    def _start_revision(self, client, file_id):
        return post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{file_id}/revision/start/', {})

    def _save(self, client, file_id, session_key, revision,
              name='saved.docx', content=DOCX):
        return client.post(
            f'/institution/manuals/{self.manual.id}/files/'
            f'{file_id}/draft/save/',
            {'file': SimpleUploadedFile(name, content),
             'session_key': session_key, 'revision': revision})

    def _exit_session(self, client, file_id, session_key):
        resp = delete_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{file_id}/draft/session/', {'session_key': session_key})
        self.assertFalse(has_error(resp), resp.content)

    def _edit(self, client, file_id, content):
        """负责人编辑草稿（真实会话+保存+退出），返回新草稿修订号"""
        revision = self._row(file_id)['draft']['revision']
        resp = self._start_session(client, file_id)
        self.assertFalse(has_error(resp), resp.content)
        session_key = get_data(resp)['session_key']
        resp = self._save(client, file_id, session_key, revision,
                          content=content)
        self.assertFalse(has_error(resp), resp.content)
        new_revision = get_data(resp)['revision']
        self._exit_session(client, file_id, session_key)
        return new_revision

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

    def _setup_published_v1(self):
        """首发夹具：甲(editor)+乙(editor2) 各自提交后由 publisher 发布 v1"""
        self._set_password()
        self.file_a = self._add_file('甲.docx', owner=self.editor)
        self.file_b = self._add_file('乙.docx', owner=self.editor2)
        self._submit_ok(self.editor_client, self.file_a['id'])
        self._submit_ok(self.editor2_client, self.file_b['id'])
        resp = self._publish('v1')
        self.assertFalse(has_error(resp), resp.content)
        self.v1 = ManualVersion.objects.get(manual=self.manual)
        return self.file_a, self.file_b

    def _version_dir_files(self):
        root = os.path.join(self._tmp.name, 'versions')
        found = []
        for dirpath, _, filenames in os.walk(root):
            found.extend(os.path.join(dirpath, name) for name in filenames)
        return found

    def _version_dir_basenames(self):
        return sorted(os.path.basename(p) for p in self._version_dir_files())

    def _assert_no_version(self, version_no=2):
        self.assertFalse(ManualVersion.objects.filter(
            manual=self.manual, version_no=version_no).exists())

    def _assert_blocked(self, reason, file_name):
        plan = self._preview()
        blocked = {row['name']: row for row in plan['blocked']}
        self.assertIn(file_name, blocked)
        self.assertEqual(blocked[file_name]['reason'], reason)
        for key in HANDOFF_KEYS:
            self.assertIn(key, blocked[file_name])
        self.assertFalse(plan['can_publish'])
        return plan, blocked


class HandoffPublishTests(_HandoffEnv, TestCase):
    """发布交接的主场景（1~12）"""

    def setUp(self):
        super().setUp()
        self._init_env()

    # ---- 1. 本人编制本人发布 ---------------------------------------------

    def test_owner_publisher_skips_submission(self):
        """文件负责人=发布人：新增文件无需提交编制即可发布"""
        data = self._add_file('本人负责.docx', owner=self.compiler)
        plan = self._preview(self.compiler_client)
        rows = plan['added']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['owner_id'], self.compiler.id)
        self.assertTrue(row['publisher_is_owner'])
        self.assertFalse(row['submission_required'])
        self.assertTrue(row['content_changed'])
        self.assertEqual(row['submission']['state'], 'none')
        self.assertEqual(plan['blocked'], [])
        self.assertTrue(plan['can_publish'])
        resp = self._publish('本人负责首发', client=self.compiler_client)
        self.assertFalse(has_error(resp), resp.content)
        self.assertTrue(ManualVersion.objects.filter(
            manual=self.manual).exists())
        # 发布不产生提交记录（本人发布无需交接）
        row = self._row(data['id'])
        self.assertEqual(row['submission']['state'], 'none')
        self.assertFalse(ManualSubmission.objects.filter(
            file_id=data['id']).exists())

    # ---- 2. 多人分工 -------------------------------------------------------

    def test_division_requires_each_owner_submission(self):
        a = self._add_file('甲.docx', owner=self.editor)
        b = self._add_file('乙.docx', owner=self.editor2)
        plan = self._preview()
        blocked = {row['name']: row for row in plan['blocked']}
        self.assertEqual(set(blocked), {'甲.docx', '乙.docx'})
        for name, owner in (('甲.docx', self.editor), ('乙.docx', self.editor2)):
            row = blocked[name]
            for key in HANDOFF_KEYS:
                self.assertIn(key, row)
            self.assertEqual(row['reason'], 'submission_pending')
            self.assertIn('等待负责人', row['message'])
            self.assertIn(owner.username, row['message'])
            self.assertFalse(row['publisher_is_owner'])
            self.assertTrue(row['submission_required'])
            self.assertTrue(row['content_changed'])
        self.assertEqual(plan['blocker_summary'], {'submission_pending': 2})
        self.assertFalse(plan['can_publish'])
        resp = self._publish('未交接就发布')
        self.assertTrue(has_error(resp))
        self.assertIn('存在未完成的提交待发布核对', resp.json()['error'])
        self.assertIn('甲.docx', resp.json()['error'])
        self.assertIn('乙.docx', resp.json()['error'])
        self.assertFalse(ManualVersion.objects.filter(manual=self.manual).exists())
        self.assertEqual(self._version_dir_basenames(), [])
        # 两名负责人各自提交后放行
        self._submit_ok(self.editor_client, a['id'])
        self._submit_ok(self.editor2_client, b['id'])
        plan = self._preview()
        self.assertEqual(plan['blocked'], [])
        self.assertEqual(plan['blocker_summary'], {})
        self.assertTrue(plan['can_publish'])
        resp = self._publish('交接完成')
        self.assertFalse(has_error(resp), resp.content)
        version = ManualVersion.objects.get(pk=get_data(resp)['id'])
        self.assertEqual(version.files.count(), 2)
        # 提交随本版发布被消费（快照记录保留，状态 published）
        for file_id in (a['id'], b['id']):
            self.assertEqual(ManualSubmission.objects.get(
                file_id=file_id).status,
                ManualSubmission.STATUS_PUBLISHED)

    # ---- 3. 实际编制人≠负责人 ---------------------------------------------

    def test_non_owner_cannot_submit_even_manual_owner(self):
        data = self._add_file('乙负责.docx', owner=self.editor2)
        # 其他编制授权账号（非负责人）
        resp = self._submit(self.editor_client, data['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('只有该文件的有效负责人本人可以提交待发布核对',
                      resp.json()['error'])
        # 手册所有者同样不得代提交
        resp = self._submit(self.manager_client, data['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('只有该文件的有效负责人本人可以提交待发布核对',
                      resp.json()['error'])
        # 负责人本人提交后才可发布
        self._submit_ok(self.editor2_client, data['id'])
        resp = self._publish('由负责人提交后发布')
        self.assertFalse(has_error(resp), resp.content)

    # ---- 4. 未提交阻断（含无快照残留） ------------------------------------

    def test_unsubmitted_change_blocks_without_residue(self):
        a, b = self._setup_published_v1()
        self._edit(self.editor_client, a['id'], DOCX + b'-a2')
        plan, blocked = self._assert_blocked('submission_pending', '甲.docx')
        self.assertIn('等待负责人', blocked['甲.docx']['message'])
        before = self._version_dir_basenames()
        resp = self._publish('未提交改版')
        self.assertTrue(has_error(resp))
        self.assertIn('存在未完成的提交待发布核对', resp.json()['error'])
        self._assert_no_version()
        self.assertEqual(self._version_dir_basenames(), before)
        # 负责人提交后发布成功，旧版快照未被改写
        self._submit_ok(self.editor_client, a['id'])
        resp = self._publish('提交后改版')
        self.assertFalse(has_error(resp), resp.content)
        v2 = ManualVersion.objects.get(pk=get_data(resp)['id'])
        self.assertEqual(v2.files.count(), 2)
        self.assertEqual(ManualVersion.objects.get(pk=self.v1.id).files.count(), 2)
        self.assertEqual(len(self._version_dir_basenames()), 4)

    # ---- 5. 提交后冻结与撤回重提 -------------------------------------------

    def test_frozen_after_submit_then_withdraw_and_resubmit(self):
        """提交后内容被冻结：不得再保存；撤回后修改并重新提交才可发布

        2026-11-03 固定快照取代"提交后草稿再变化即 stale"的旧语义：
        提交 pending 期间已保存/回退等写路径必须被冻结拒绝；撤回使旧快照
        作废（记录保留），负责人修改后重新提交产生新快照，旧记录可追溯。
        """
        a, _ = self._setup_published_v1()
        self._edit(self.editor_client, a['id'], DOCX + b'-a2')
        self._submit_ok(self.editor_client, a['id'])
        first = ManualSubmission.objects.filter(
            file_id=a['id'], status=ManualSubmission.STATUS_PENDING).get()
        # 提交后再次保存必须被冻结拒绝，草稿修订号/物理副本不变
        resp = self._start_session(self.editor_client, a['id'])
        self.assertTrue(has_error(resp))
        self.assertIn(FROZEN_EDIT, resp.json()['error'])
        self.assertEqual(ManualDraft.objects.get(file_id=a['id']).revision,
                         first.draft_revision)
        # 有效 pending 快照可被发布人使用（预检不阻断，且状态为 submitted）
        plan = self._preview()
        self.assertEqual(plan['blocked'], [])
        self.assertTrue(plan['can_publish'])
        self.assertEqual(self._row(a['id'])['submission']['state'],
                         'submitted')
        self._assert_no_version()
        # 撤回后旧快照不可用于发布（记录/时间保留），负责人可继续编辑
        resp = post_json(
            self.editor_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{a["id"]}/submit/withdraw/', {})
        self.assertFalse(has_error(resp), resp.content)
        first.refresh_from_db()
        self.assertEqual(first.status, ManualSubmission.STATUS_WITHDRAWN)
        self.assertIsNotNone(first.withdrawn_at)
        self._edit(self.editor_client, a['id'], DOCX + b'-a3')
        self._submit_ok(self.editor_client, a['id'])
        second = ManualSubmission.objects.filter(
            file_id=a['id']).order_by('-id').first()
        self.assertEqual(second.status, ManualSubmission.STATUS_PENDING)
        self.assertNotEqual(second.id, first.id)
        self.assertEqual(self._row(a['id'])['submission']['state'],
                         'submitted')
        resp = self._publish('重新提交后发布')
        self.assertFalse(has_error(resp), resp.content)

    # ---- 6. 冻结期间改派被拒、撤回后改派 ------------------------------------

    def test_reassignment_clears_submission_and_revokes_session(self):
        """冻结期间改派被拒；撤回后改派成功，旧快照作废且记录保留"""
        a, _ = self._setup_published_v1()
        self._edit(self.editor_client, a['id'], DOCX + b'-a2')
        self._submit_ok(self.editor_client, a['id'])
        pending = ManualSubmission.objects.filter(
            file_id=a['id'], status=ManualSubmission.STATUS_PENDING).get()
        # 提交 pending 期间改派 = 结构操作被冻结拒绝
        resp = self._assign(self.manager_client, a['id'], self.editor2.id,
                            note='改派给乙')
        self.assertTrue(has_error(resp))
        self.assertIn(services.FROZEN_STRUCT_ERROR, resp.json()['error'])
        self.assertEqual(ManualFile.objects.get(pk=a['id']).owner_id,
                         self.editor.id)
        # 撤回后才能改派；旧快照状态 withdrawn、记录/提交人/时间保留
        resp = post_json(
            self.editor_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{a["id"]}/submit/withdraw/', {})
        self.assertFalse(has_error(resp), resp.content)
        pending.refresh_from_db()
        self.assertEqual(pending.status, ManualSubmission.STATUS_WITHDRAWN)
        resp = self._assign(self.manager_client, a['id'], self.editor2.id,
                            note='改派给乙')
        self.assertFalse(has_error(resp), resp.content)
        row = self._row(a['id'])
        self.assertEqual(row['assignment']['owner_id'], self.editor2.id)
        self.assertEqual(row['submission']['state'], 'none')
        self.assertEqual(row['submission']['status'], 'withdrawn')
        plan, blocked = self._assert_blocked('submission_pending', '甲.docx')
        self.assertIn(self.editor2.username, blocked['甲.docx']['message'])
        resp = self._publish('改派后未交接发布')
        self.assertTrue(has_error(resp))
        self._assert_no_version()
        self._submit_ok(self.editor2_client, a['id'])
        resp = self._publish('新负责人提交后发布')
        self.assertFalse(has_error(resp), resp.content)

    # ---- 7. 有效重复提交 ---------------------------------------------------

    def test_duplicate_submit_rejected_and_unchanged(self):
        a = self._add_file('重复提交.docx', owner=self.editor)
        self._submit_ok(self.editor_client, a['id'])
        first = ManualSubmission.objects.filter(
            file_id=a['id'], status=ManualSubmission.STATUS_PENDING).get()
        first_revision = first.draft_revision
        resp = self._submit(self.editor_client, a['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('该文件已有待发布人核对的提交，请勿重复提交',
                      resp.json()['error'])
        first.refresh_from_db()
        self.assertEqual(first.status, ManualSubmission.STATUS_PENDING)
        self.assertEqual(first.draft_revision, first_revision)
        self.assertEqual(ManualSubmission.objects.filter(
            file_id=a['id']).count(), 1)
        self.assertEqual(
            ManualOperationLog.objects.filter(
                manual=self.manual, action='file_submit').count(), 1)
        self.assertEqual(self._row(a['id'])['submission']['state'], 'submitted')

    # ---- 8. 未变化文件 -----------------------------------------------------

    def test_unchanged_file_needs_no_submission(self):
        a, b = self._setup_published_v1()
        self._edit(self.editor2_client, b['id'], DOCX + b'-b2')
        self._submit_ok(self.editor2_client, b['id'])
        plan = self._preview()
        self.assertEqual(plan['blocked'], [])
        self.assertTrue(plan['can_publish'])
        unchanged = {row['name']: row for row in plan['unchanged']}
        self.assertIn('甲.docx', unchanged)
        row = unchanged['甲.docx']
        for key in HANDOFF_KEYS:
            self.assertIn(key, row)
        self.assertFalse(row['content_changed'])
        self.assertFalse(row['submission_required'])
        self.assertEqual(row['submission']['state'], 'none')
        resp = self._publish('乙变化甲不变')
        self.assertFalse(has_error(resp), resp.content)
        v2 = ManualVersion.objects.get(pk=get_data(resp)['id'])
        self.assertEqual(v2.files.count(), 2)
        # 甲不需要也不产生提交记录（未变化文件沿用当前生效快照）
        self.assertFalse(ManualSubmission.objects.filter(
            file_id=a['id']).exists())

    # ---- 9. 纯改名/排序不要求提交 -----------------------------------------

    def test_pure_rename_and_reorder_skip_submission(self):
        a, b = self._setup_published_v1()
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
        self.assertEqual(plan['blocker_summary'], {})
        self.assertTrue(plan['can_publish'])
        self.assertTrue(plan['has_changes'])
        self.assertFalse(plan['first_publish'])
        self.assertTrue(plan.get('renamed'))
        self.assertTrue(plan.get('reordered'))
        unchanged = {row['name']: row for row in plan['unchanged']}
        row = unchanged['甲-改名.docx']
        self.assertTrue(row.get('renamed'))
        self.assertEqual(row['current_name'], '甲.docx')
        self.assertFalse(row['submission_required'])
        self.assertFalse(row['content_changed'])
        resp = self._publish('改名排序发布')
        self.assertFalse(has_error(resp), resp.content)
        v2 = ManualVersion.objects.get(pk=get_data(resp)['id'])
        self.assertEqual([f.display_name for f in v2.files.all()],
                         ['乙.docx', '甲-改名.docx'])

    # ---- 10. 有效负责人回退 -------------------------------------------------

    def test_unassigned_new_file_blocks_then_assigned_works(self):
        """显式不分配负责人（owner_id 空）按回退手册所有者处理

        2026-11-03 有效负责人判定：owner_id 为空时回退 Manual.owner；
        手册有所有者即不存在"未分配"，发布人不是该回退负责人时必须由
        手册所有者提交快照；指派显式负责人后由其提交放行。
        """
        data = self._add_file('未分配.docx', owner=None)
        row = self._row(data['id'])
        self.assertIsNone(row['assignment']['owner_id'])
        self.assertEqual(row['assignment']['effective_owner_id'],
                         self.manager.id)
        self.assertFalse(row['assignment']['owner_assigned'])
        # 回退负责人（手册所有者）本人可提交；发布人不是他时仍阻断
        plan, blocked = self._assert_blocked('submission_pending', '未分配.docx')
        self.assertIn(self.manager.username, blocked['未分配.docx']['message'])
        self.assertEqual(plan['blocker_summary'], {'submission_pending': 1})
        resp = self._publish('回退负责人未提交就发布')
        self.assertTrue(has_error(resp))
        self.assertFalse(ManualVersion.objects.filter(manual=self.manual).exists())
        self.assertEqual(self._version_dir_basenames(), [])
        # 手册所有者提交固定快照后放行
        self._submit_ok(self.manager_client, data['id'])
        resp = self._publish('回退负责人提交后发布')
        self.assertFalse(has_error(resp), resp.content)

    def test_unassigned_unchanged_file_does_not_block(self):
        a, b = self._setup_published_v1()
        # 乙内容未变化，清空负责人：不构成交接阻断
        resp = self._assign(self.manager_client, b['id'], None)
        self.assertFalse(has_error(resp), resp.content)
        self._edit(self.editor_client, a['id'], DOCX + b'-a2')
        self._submit_ok(self.editor_client, a['id'])
        plan = self._preview()
        self.assertEqual(plan['blocked'], [])
        self.assertTrue(plan['can_publish'])
        unchanged = {row['name']: row for row in plan['unchanged']}
        row = unchanged['乙.docx']
        self.assertIsNone(row['owner_id'])
        self.assertFalse(row['submission_required'])
        self.assertFalse(row['content_changed'])
        resp = self._publish('未分配未变化不阻断')
        self.assertFalse(has_error(resp), resp.content)
        self.assertIsNone(ManualFile.objects.get(pk=b['id']).owner_id)

    def test_blocked_message_lists_at_most_three(self):
        names = ['一.docx', '二.docx', '三.docx', '四.docx']
        for name in names:
            self._add_file(name, owner=None)
        plan = self._preview()
        self.assertEqual(len(plan['blocked']), 4)
        # owner_id 为空回退手册所有者：发布人≠该负责人且无提交快照
        self.assertEqual(plan['blocker_summary'], {'submission_pending': 4})
        resp = self._publish('四项待提交快照')
        self.assertTrue(has_error(resp))
        message = resp.json()['error']
        for name in names[:3]:
            self.assertIn(name, message)
        self.assertNotIn('四.docx', message)
        self.assertIn('等 4 项', message)

    # ---- 11. 不同发布人分别发起 ---------------------------------------------

    def test_second_publisher_sees_same_pending_and_can_publish(self):
        a = self._add_file('甲.docx', owner=self.editor)
        b = self._add_file('乙.docx', owner=self.editor2)
        self._submit_ok(self.editor_client, a['id'])
        # 两个发布人都看到同一份未交接清单（乙未提交）
        for client in (self.publisher_client, self.publisher2_client):
            plan = self._preview(client)
            blocked = {row['name']: row for row in plan['blocked']}
            self.assertEqual(set(blocked), {'乙.docx'})
            self.assertEqual(blocked['乙.docx']['reason'], 'submission_pending')
            self.assertEqual(plan['blocker_summary'], {'submission_pending': 1})
            self.assertFalse(plan['can_publish'])
        # 任一发布人真实发布都被拒（权威校验不在预检）
        resp = self._publish('发布人乙未交接', client=self.publisher2_client)
        self.assertTrue(has_error(resp))
        self._assert_no_version(version_no=1)
        # 乙负责人提交后，另一发布人即可发布
        self._submit_ok(self.editor2_client, b['id'])
        resp = self._publish('由第二发布人发起')
        self.assertFalse(has_error(resp), resp.content)

    # ---- 14. 修订轮关闭后禁止提交（无待发布修改） -------------------------

    def test_closed_revision_submit_rejected(self):
        """发布结束修订轮后不能提交：状态不得从「无需提交」翻成「已提交」"""
        a, _ = self._setup_published_v1()
        self.assertFalse(ManualFile.objects.get(pk=a['id']).revision_open)
        resp = self._submit(self.editor_client, a['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('当前文件没有待发布的修改，无需提交待发布核对',
                      resp.json()['error'])
        row = self._row(a['id'])
        self.assertEqual(row['submission']['state'], 'none')
        self.assertIsNone(row['submission']['submitted_at'])
        self.assertFalse(ManualSubmission.objects.filter(
            file_id=a['id']).exists())
        # 负责人开启新一轮修订后才允许提交（交接只针对新增/内容变化文件）
        resp = self._start_revision(self.editor_client, a['id'])
        self.assertFalse(has_error(resp), resp.content)
        self.assertFalse(get_data(resp).get('needs_repair'))
        self.assertTrue(ManualFile.objects.get(pk=a['id']).revision_open)
        self._submit_ok(self.editor_client, a['id'])
        self.assertEqual(self._row(a['id'])['submission']['state'],
                         'submitted')

    # ---- 15. 预检 has_changes 覆盖"受阻但确有变化" -------------------------

    def test_unassigned_new_file_on_published_manual_has_changes(self):
        """已发布制度新增未分配文件：has_changes=True（受阻≠无变化）"""
        self._setup_published_v1()
        data = self._add_file('未分配新文件.docx', owner=None)
        plan = self._preview()
        self.assertFalse(plan['first_publish'])
        self.assertTrue(plan['has_changes'])
        self.assertFalse(plan['can_publish'])
        self.assertEqual(plan['changed'], [])
        self.assertEqual(plan['added'], [])  # 受阻行不进 added 桶
        blocked = {row['name']: row for row in plan['blocked']}
        self.assertIn('未分配新文件.docx', blocked)
        # owner_id 为空回退手册所有者：发布人≠回退负责人且无提交快照
        self.assertEqual(blocked['未分配新文件.docx']['reason'],
                         'submission_pending')
        self.assertTrue(blocked['未分配新文件.docx']['content_changed'])
        self.assertEqual(plan['blocker_summary'], {'submission_pending': 1})
        self.assertEqual(plan['removed'], [])
        self.assertFalse(plan['reordered'])
        resp = self._publish('未分配新文件发布')
        self.assertTrue(has_error(resp))
        self.assertIn(self.manager.username, resp.json()['error'])
        self._assert_no_version()
        # 指定负责人+提交后 has_changes 仍为真且可发布
        self._assign(self.manager_client, data['id'], self.editor.id)
        self._submit_ok(self.editor_client, data['id'])
        plan = self._preview()
        self.assertTrue(plan['has_changes'])
        self.assertTrue(plan['can_publish'])
        resp = self._publish('新文件发布')
        self.assertFalse(has_error(resp), resp.content)

    # ---- 12. 权限 ---------------------------------------------------------

    def test_publish_and_preview_permissions(self):
        """仅 can_edit（非负责人）不能发布/预检；所有者可发布本人负责文件"""
        data = self._add_file('甲.docx', owner=self.editor)
        resp = post_json(
            self.editor_client,
            f'/institution/manuals/{self.manual.id}/publish/',
            {'change_note': '编制者尝试发布'})
        self.assertTrue(has_error(resp))
        self.assertIn('权限拒绝', resp.json()['error'])
        resp = self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/publish-preview/')
        self.assertTrue(has_error(resp))
        self.assertIn('手册不存在或无权限访问', resp.json()['error'])
        resp = self.viewer_client.get(
            f'/institution/manuals/{self.manual.id}/publish-preview/')
        self.assertTrue(has_error(resp))
        # 所有者发布本人负责的新文件：无需逐本发布授权；另一份新增文件
        # 由负责人提交后一并发布
        self._add_file('所有者负责.docx', owner=self.manager)
        self._submit_ok(self.editor_client, data['id'])
        resp = self._publish('所有者本人发布', client=self.manager_client)
        self.assertFalse(has_error(resp), resp.content)
        self.assertTrue(ManualVersion.objects.filter(
            manual=self.manual, version_no=1).exists())
        # 提交随本版发布被消费（记录保留，不删除）
        self.assertEqual(ManualSubmission.objects.get(
            file_id=data['id']).status,
            ManualSubmission.STATUS_PUBLISHED)


class ConcurrentHandoffDriftTests(_HandoffEnv, TransactionTestCase):
    """13. 预检后/快照复制期间的并发变化（行锁落库段复核）"""

    def setUp(self):
        super().setUp()
        self._init_env()
        self.file_a, self.file_b = self._setup_published_v1()
        # 构造 v2 待发布状态：甲内容变化 + 负责人已提交
        self._edit(self.editor_client, self.file_a['id'], DOCX + b'-a2')
        self._submit_ok(self.editor_client, self.file_a['id'])

    def _drift_during_copy(self, worker_fn):
        """让 worker 在首次快照复制时执行动作，再返回 (发布响应, worker 结果)"""
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
        self._assert_no_version()
        self.assertEqual(self._version_dir_basenames(), before_basenames)
        # 旧生效版保持完整
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.current_version_id, self.v1.id)

    def test_revision_advance_during_copy_rejected(self):
        before = self._version_dir_basenames()
        revision_before = self._row(self.file_a['id'])['draft']['revision']

        def worker():
            with transaction.atomic():
                ManualDraft.objects.filter(
                    file_id=self.file_a['id']).update(
                    revision=F('revision') + 1)

        resp, _ = self._drift_during_copy(worker)
        self.assertTrue(has_error(resp))
        # 草稿修订号被推进：固定快照与当前草稿不再一致，按提交失效阻断
        self.assertIn('提交待发布核对已失效', resp.json()['error'])
        self._assert_rejected_and_cleaned(before)
        self.assertEqual(
            ManualDraft.objects.get(file_id=self.file_a['id']).revision,
            revision_before + 1)
        # 提交未随失败发布被消费：仍为 pending（快照记录/哈希可追溯）
        submission = ManualSubmission.objects.get(
            file_id=self.file_a['id'],
            status=ManualSubmission.STATUS_PENDING)
        self.assertIsNone(submission.published_version_id)

    def test_owner_reassigned_during_copy_rejected(self):
        before = self._version_dir_basenames()

        def worker():
            with transaction.atomic():
                ManualFile.objects.filter(pk=self.file_a['id']).update(
                    owner=self.editor2, owner_name=self.editor2.username)

        resp, _ = self._drift_during_copy(worker)
        self.assertTrue(has_error(resp))
        self.assertIn('发布过程中文件分工、草稿或提交状态发生变化',
                      resp.json()['error'])
        self._assert_rejected_and_cleaned(before)
        self.assertEqual(
            ManualFile.objects.get(pk=self.file_a['id']).owner_id,
            self.editor2.id)
        # 改派只改 DB 负责人；旧 pending 未消费仍保留（可追溯，但不匹配固化签名）
        submission = ManualSubmission.objects.get(
            file_id=self.file_a['id'],
            status=ManualSubmission.STATUS_PENDING)
        self.assertIsNone(submission.published_version_id)

    def test_concurrent_same_content_publish_rejected_as_no_changes(self):
        """复制期间另一发布人已先发布同一内容：落库复核拒绝重复版本"""
        before = self._version_dir_basenames()
        self.assertEqual(len(before), 2)

        def worker():
            """第二发布人经真实 HTTP 完成一次同内容整套发布"""
            worker_client = make_client(self.publisher)
            return post_json(
                worker_client,
                f'/institution/manuals/{self.manual.id}/publish/',
                {'change_note': '并发同内容发布'})

        resp, results = self._drift_during_copy(worker)
        self.assertEqual(len(results), 1)
        first_publish = results[0]
        self.assertFalse(has_error(first_publish))
        worker_version = ManualVersion.objects.get(
            pk=get_data(first_publish)['id'])
        # 第一次（主线程）发布被拒绝：内容已与当前生效版一致
        self.assertTrue(has_error(resp))
        self.assertEqual(resp.json()['error'],
                         '当前没有内容或结构变化，无需重复发布')
        # 只产生 worker 的 v2，没有额外的新版本
        self.assertEqual(ManualVersion.objects.filter(
            manual=self.manual).count(), 2)
        self.assertEqual(worker_version.files.count(), 2)
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.current_version_id, worker_version.id)
        # 主线程已复制的 2 份快照被清理：目录只剩 v1+v2 各 2 份
        self.assertEqual(len(self._version_dir_basenames()), 4)

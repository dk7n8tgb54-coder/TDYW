# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""多文件制度改造的真实行为测试

覆盖（《制度管理模块设计方案》§10 验收点 4/5/8 与任务验收清单）：
- 文件条目管理：新增、列表、改名、排序、移除（最后一份不可移除）。
- 文件级单写：同一文件同时仅一个可写会话；不同文件可并行编辑。
- 越权与跨制度文件 ID：文件不属于当前制度一律拒绝。
- 修订冲突与迟到回调：文件级 document.key / editor_token / 回调绑定。
- 整套发布：缺草稿/活跃会话阻断；快照失败旧生效版保持完整；
  发布产生完整有序不可变快照清单（含旧列镜像）。
- 文件移除/改名/排序只影响待发布集合，历史版本不变。
- 历史版本逐份下载/预览；旧单文件接口委托唯一文件、多文件明确拒绝。
- 整套回退：按版本快照重建草稿集合，不覆盖历史版本。
"""
import json
import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from apps.institution import storage
from apps.institution.models import (Manual, ManualDraft, ManualEditSession,
                                     ManualFile, ManualOperationLog,
                                     ManualVersion, ManualVersionFile)
from apps.institution.tests.base import (
    ALL_PERMS, PERM_DOWNLOAD, PERM_DRAFT, PERM_PUBLISH, PERM_VIEW, get_data,
    has_error, make_client, make_grant, make_user, post_json, put_json,
    setup_test_env,
)

DOCX = b'PK\x03\x04 multi-file-docx'


class MultiFileBase(TestCase):
    """管理者（=手册所有者）+ 两名编制者 + 一名发布者 + 查看者；手册就绪

    授权夹具（2026-10-31）：manager 为手册所有者（文件条目管理/分工
    的业务门禁口径）；editor/editor2 持 can_edit 授权，publisher 持
    can_publish 授权，viewer 持 can_view 授权。
    """

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
                                   perms=[PERM_PUBLISH, PERM_DOWNLOAD, PERM_VIEW])
        make_grant(self.manual, self.publisher, can_view=True, can_publish=True)
        self.viewer = make_user('viewer', tenant_id='deptY',
                                perms=[PERM_VIEW, PERM_DOWNLOAD])
        make_grant(self.manual, self.viewer, can_view=True)
        self.viewer_client = make_client(self.viewer)
        self.editor_client = make_client(self.editor)
        self.editor2_client = make_client(self.editor2)
        self.publisher_client = make_client(self.publisher)
        self.file_seq = 0

    def _set_password(self, password='edit-pass-1'):
        resp = put_json(self.manager_client,
                        f'/institution/manuals/{self.manual.id}/password/',
                        {'password': password})
        self.assertFalse(has_error(resp), resp.content)
        return password

    def _add_file(self, name=None, content=DOCX, owner=None):
        """新增制度文件；owner 传入账号即同时指派为文件负责人（须持
        can_edit 编制授权）"""
        self.file_seq += 1
        name = name or f'文件{self.file_seq}.docx'
        payload = {'file': SimpleUploadedFile(name, content)}
        if owner:
            payload['owner_id'] = str(owner.id)
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/create/', payload)
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _ensure_handoff(self, actor):
        """完整发布夹具：发布前由各文件负责人经真实接口提交编制

        仅用于"预期发布成功"的用例；提交失败不断言（会话占用/缺草稿等
        情况由真实发布自己报错）。owner==actor 的文件无需提交。
        """
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

    def _files_list(self):
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _start_session(self, client=None, file_id=None, password='edit-pass-1'):
        client = client or self.editor_client
        file_id = file_id or self._files_list()[0]['id']
        return post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/session/',
            {'password': password})

    def _save(self, client, file_id, session_key, revision,
              name='saved.docx', content=DOCX):
        upload = SimpleUploadedFile(name, content)
        return client.post(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/save/',
            {'file': upload, 'session_key': session_key, 'revision': revision})


class FileManageTests(MultiFileBase):
    """文件新增/列表/改名/排序/移除"""

    def test_add_file_creates_entry_and_draft_directly(self):
        data = self._add_file('操作规程.docx')
        self.assertEqual(data['name'], '操作规程.docx')
        self.assertEqual(data['sort_order'], 1)
        self.assertEqual(data['draft']['revision'], 1)
        self.assertEqual(ManualFile.objects.filter(manual=self.manual).count(), 1)
        draft = ManualDraft.objects.get(file_id=data['id'])
        self.assertEqual(draft.revision, 1)
        self.assertIsNone(draft.base_version_id)
        # 直接建草稿：不再产生原稿记录/原稿物理文件
        originals_dir = os.path.join(self._tmp.name, 'originals')
        original_files = []
        for dirpath, _, filenames in os.walk(originals_dir):
            original_files.extend(filenames)
        self.assertEqual(original_files, [])
        # 操作记录落 file_add，不再有 upload_original/create_draft
        actions = set(ManualOperationLog.objects.filter(
            manual=self.manual, file_id=data['id']).values_list('action', flat=True))
        self.assertIn('file_add', actions)
        self.assertNotIn('upload_original', actions)
        self.assertNotIn('create_draft', actions)

    def test_list_ordered_with_draft_and_occupancy(self):
        # 会话开启要求负责人独占：甲指派 editor 为文件负责人
        first = self._add_file('甲.docx', owner=self.editor)
        second = self._add_file('乙.docx')
        self._set_password()
        resp = self._start_session(file_id=first['id'])
        self.assertFalse(has_error(resp), resp.content)
        # 占用 is_mine 以请求者视角计算：用发起会话的编辑者客户端取清单
        resp = self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        items = get_data(resp)
        self.assertEqual([i['name'] for i in items], ['甲.docx', '乙.docx'])
        by_id = {i['id']: i for i in items}
        self.assertEqual(by_id[first['id']]['draft']['revision'], 1)
        self.assertIsNotNone(by_id[first['id']]['active_session'])
        self.assertTrue(by_id[first['id']]['active_session']['is_mine'])
        self.assertIsNone(by_id[second['id']]['active_session'])

    def test_rename_file_only_affects_pending(self):
        data = self._add_file('旧名.docx')
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/{data["id"]}/rename/',
                         {'name': '新名.docx'})
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['name'], '新名.docx')
        file_entry = ManualFile.objects.get(pk=data['id'])
        self.assertEqual(file_entry.display_name, '新名.docx')

    def test_rename_empty_rejected(self):
        data = self._add_file()
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/{data["id"]}/rename/',
                         {'name': ' . '})
        self.assertTrue(has_error(resp))

    def test_move_file_reorders_pending_list(self):
        a = self._add_file('甲.docx')
        b = self._add_file('乙.docx')
        c = self._add_file('丙.docx')
        # 把甲移到末位
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/{a["id"]}/move/',
                         {'position': 3})
        self.assertFalse(has_error(resp), resp.content)
        names = [i['name'] for i in self._files_list()]
        self.assertEqual(names, ['乙.docx', '丙.docx', '甲.docx'])
        orders = {i['id']: i['sort_order'] for i in self._files_list()}
        self.assertEqual(orders, {b['id']: 1, c['id']: 2, a['id']: 3})

    def test_remove_file_keeps_entry_and_excludes_from_pending(self):
        a = self._add_file('甲.docx')
        b = self._add_file('乙.docx')
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/{a["id"]}/remove/', {})
        self.assertFalse(has_error(resp), resp.content)
        # 条目保留（软移除），草稿工作副本保留（回退可重新纳入）
        entry = ManualFile.objects.get(pk=a['id'])
        self.assertTrue(entry.is_removed)
        self.assertTrue(ManualDraft.objects.filter(file_id=a['id']).exists())
        # 待发布清单只剩乙
        names = [i['name'] for i in self._files_list()]
        self.assertEqual(names, ['乙.docx'])

    def test_remove_last_active_file_rejected(self):
        only = self._add_file()
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/{only["id"]}/remove/', {})
        self.assertTrue(has_error(resp))
        self.assertIn('最后一份', resp.json()['error'])

    def test_remove_file_with_active_session_rejected(self):
        data = self._add_file(owner=self.editor)
        self._add_file()
        self._set_password()
        resp = self._start_session(file_id=data['id'])
        self.assertFalse(has_error(resp), resp.content)
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/{data["id"]}/remove/', {})
        self.assertTrue(has_error(resp))
        self.assertIn('编辑会话', resp.json()['error'])

    def test_file_management_requires_role(self):
        data = self._add_file()
        self._add_file()
        insider = make_user('in', tenant_id='deptA', perms=[PERM_DRAFT])
        resp = post_json(make_client(insider),
                         f'/institution/manuals/{self.manual.id}/files/{data["id"]}/rename/',
                         {'name': 'x.docx'})
        self.assertTrue(has_error(resp))


class CrossManualFileAccessTests(MultiFileBase):
    """越权与跨制度文件 ID"""

    def setUp(self):
        super().setUp()
        self.other_manual = Manual.objects.create(
            name='另一手册', code='OT-100',
            org_type=Manual.OWNER_SECTION, org_name='乙科室',
            owner=self.manager, tenant_id='deptA')
        upload = SimpleUploadedFile('别家.docx', DOCX)
        resp = self.manager_client.post(
            f'/institution/manuals/{self.other_manual.id}/files/create/',
            {'file': upload})
        self.assertFalse(has_error(resp), resp.content)
        self.foreign_file_id = get_data(resp)['id']

    def _assert_foreign_rejected(self, resp):
        self.assertTrue(has_error(resp), resp.content)
        self.assertIn('不存在', resp.json()['error'])

    def test_file_ops_reject_cross_manual_file_id(self):
        base = f'/institution/manuals/{self.manual.id}/files/{self.foreign_file_id}'
        self._assert_foreign_rejected(self.manager_client.get(f'{base}/draft/'))
        self._assert_foreign_rejected(post_json(
            self.manager_client, f'{base}/rename/', {'name': 'x.docx'}))
        self._assert_foreign_rejected(post_json(
            self.manager_client, f'{base}/move/', {'position': 1}))
        self._assert_foreign_rejected(post_json(
            self.manager_client, f'{base}/remove/', {}))
        self._assert_foreign_rejected(post_json(
            self.manager_client, f'{base}/draft/create/', {}))
        self._assert_foreign_rejected(post_json(
            self.manager_client, f'{base}/draft/session/', {'password': 'x'}))

    def test_cross_manual_save_rejected(self):
        """跨制度保存：文件不属于 URL 中的制度，不得落任何草稿"""
        self._add_file(owner=self.editor)
        self._set_password()
        resp = self._start_session()
        self.assertFalse(has_error(resp), resp.content)
        session_key = get_data(resp)['session_key']
        resp = self._save(self.editor_client, self.foreign_file_id,
                          session_key, 1, content=DOCX + b'-evil')
        self._assert_foreign_rejected(resp)
        other = self.other_manual
        self.assertEqual(
            ManualDraft.objects.filter(file_id=self.foreign_file_id).count(), 1)


class ParallelEditTests(MultiFileBase):
    """文件级单写与并行编辑"""

    def setUp(self):
        super().setUp()
        self.file_a = self._add_file('甲.docx', owner=self.editor)
        self.file_b = self._add_file('乙.docx', owner=self.editor2)
        self._set_password()

    def test_same_file_single_writer(self):
        """单写以文件为单位：同账号复用同一会话（多标签）；其他编制授权
        账号因非负责人被负责人独占拒绝（单写由负责人身份保证）"""
        resp = self._start_session(client=self.editor_client,
                                   file_id=self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        key = get_data(resp)['session_key']
        # 同账号再次开启：复用同一活跃会话，不产生第二个写者
        resp = self._start_session(client=self.editor_client,
                                   file_id=self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['session_key'], key)
        # editor2 持编制授权但非该文件负责人：负责人独占拒绝
        resp = self._start_session(client=self.editor2_client,
                                   file_id=self.file_a['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])
        # 该文件活跃会话仍只有 editor 一条
        self.assertEqual(ManualEditSession.objects.filter(
            file_id=self.file_a['id'], revoked_at__isnull=True).count(), 1)

    def test_different_files_edit_in_parallel(self):
        """不同文件可由不同账号并行编辑，互不占用"""
        resp_a = self._start_session(client=self.editor_client,
                                     file_id=self.file_a['id'])
        resp_b = self._start_session(client=self.editor2_client,
                                     file_id=self.file_b['id'])
        self.assertFalse(has_error(resp_a), resp_a.content)
        self.assertFalse(has_error(resp_b), resp_b.content)
        key_a = get_data(resp_a)['session_key']
        key_b = get_data(resp_b)['session_key']
        self.assertNotEqual(key_a, key_b)
        resp = self._save(self.editor_client, self.file_a['id'], key_a, 1,
                          content=DOCX + b'-a1')
        self.assertFalse(has_error(resp), resp.content)
        resp = self._save(self.editor2_client, self.file_b['id'], key_b, 1,
                          content=DOCX + b'-b1')
        self.assertFalse(has_error(resp), resp.content)
        draft_a = ManualDraft.objects.get(file_id=self.file_a['id'])
        draft_b = ManualDraft.objects.get(file_id=self.file_b['id'])
        self.assertEqual(draft_a.revision, 2)
        self.assertEqual(draft_b.revision, 2)

    def test_revision_conflict_per_file(self):
        """同文件修订冲突：旧修订号保存被拒，另一文件不受影响"""
        resp = self._start_session(client=self.editor_client,
                                   file_id=self.file_a['id'])
        key_a = get_data(resp)['session_key']
        resp = self._save(self.editor_client, self.file_a['id'], key_a, 1,
                          content=DOCX + b'-a1')
        self.assertFalse(has_error(resp), resp.content)
        # 用旧修订号 1 再保存 → 冲突
        resp = self._save(self.editor_client, self.file_a['id'], key_a, 1,
                          content=DOCX + b'-stale')
        self.assertTrue(has_error(resp))
        self.assertIn('已被其他会话更新', resp.json()['error'])
        # 文件 B 用自己的修订号正常保存
        resp = self._start_session(client=self.editor2_client,
                                   file_id=self.file_b['id'])
        key_b = get_data(resp)['session_key']
        resp = self._save(self.editor2_client, self.file_b['id'], key_b, 1,
                          content=DOCX + b'-b1')
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(
            ManualDraft.objects.get(file_id=self.file_a['id']).revision, 2)

    def test_password_reset_revokes_all_file_sessions(self):
        """密码重置使制度下所有文件的编辑会话失效"""
        self._start_session(client=self.editor_client, file_id=self.file_a['id'])
        self._start_session(client=self.editor2_client, file_id=self.file_b['id'])
        put_json(self.manager_client,
                 f'/institution/manuals/{self.manual.id}/password/',
                 {'password': 'new-pass'})
        resp = self._save(self.editor_client, self.file_a['id'], 'whatever', 1)
        self.assertTrue(has_error(resp))
        self.assertEqual(
            ManualEditSession.objects.filter(
                manual=self.manual, revoked_at__isnull=True).count(), 0)


class WholePublishTests(MultiFileBase):
    """整套发布与快照不可变性"""

    def setUp(self):
        super().setUp()
        self.file_a = self._add_file('甲.docx', DOCX + b'-a', owner=self.editor)
        self.file_b = self._add_file('乙.docx', DOCX + b'-b')
        self._set_password()

    def _publish(self, note='整套发布'):
        self._ensure_handoff(self.publisher)
        return post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': note})

    def test_publish_creates_ordered_immutable_snapshots(self):
        # 乙移到首位
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/{self.file_b["id"]}/move/',
                         {'position': 1})
        self.assertFalse(has_error(resp), resp.content)
        resp = self._publish()
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(data['version_no'], 1)
        files = data['files']
        self.assertEqual([f['file_name'] for f in files], ['乙.docx', '甲.docx'])
        self.assertEqual([f['sort_order'] for f in files], [0, 1])
        # 逐份快照文件独立存在且哈希一致
        for f in files:
            abs_path = storage.resolve_absolute_path(
                ManualVersionFile.objects.get(pk=f['id']).file_path)
            self.assertTrue(os.path.exists(abs_path))
            self.assertEqual(storage.compute_file_hash(abs_path), f['file_hash'])
        # 旧列镜像 = 首个快照
        version = ManualVersion.objects.get(pk=data['id'])
        self.assertEqual(version.original_name, '乙.docx')
        self.assertEqual(version.file_hash, files[0]['file_hash'])
        # 两个草稿 base_version 均指向新版本
        self.assertEqual(
            ManualDraft.objects.filter(
                base_version_id=version.id).count(), 2)

    def test_publish_blocked_by_missing_draft(self):
        """任一文件缺少有效草稿不得发布（移除才可跳过，不能悄悄漏）"""
        ManualDraft.objects.get(file_id=self.file_b['id']).delete()
        resp = self._publish()
        self.assertTrue(has_error(resp))
        self.assertIn(self.file_b['name'], resp.json()['error'])
        self.assertFalse(ManualVersion.objects.filter(manual=self.manual).exists())

    def test_publish_blocked_by_active_session(self):
        """任一文件仍有编辑会话不得发布（未完成的编辑不能进入生效版）"""
        resp = self._start_session(client=self.editor_client,
                                   file_id=self.file_a['id'])
        self.assertFalse(has_error(resp), resp.content)
        resp = self._publish()
        self.assertTrue(has_error(resp))
        self.assertIn('编辑会话', resp.json()['error'])
        self.assertFalse(ManualVersion.objects.filter(manual=self.manual).exists())

    def test_publish_blocked_by_missing_physical_draft_file(self):
        draft_b = ManualDraft.objects.get(file_id=self.file_b['id'])
        os.remove(storage.resolve_absolute_path(draft_b.file_path))
        resp = self._publish()
        self.assertTrue(has_error(resp))
        self.assertIn('不存在', resp.json()['error'])
        self.assertFalse(ManualVersion.objects.filter(manual=self.manual).exists())

    def test_snapshot_copy_failure_keeps_old_version_intact(self):
        """v1 发布后，v2 快照复制中途失败：旧生效版与草稿完整保留"""
        resp = self._publish(note='v1')
        self.assertFalse(has_error(resp), resp.content)
        v1 = ManualVersion.objects.get(manual=self.manual)
        v1_paths = [storage.resolve_absolute_path(s.file_path)
                    for s in v1.files.all()]
        v1_hashes = [s.file_hash for s in v1.files.all()]
        # 保存草稿推进修订，再发布并让复制在第二份失败
        resp = self._start_session(client=self.editor_client,
                                   file_id=self.file_a['id'])
        key = get_data(resp)['session_key']
        resp = self._save(self.editor_client, self.file_a['id'], key,
                          get_data(self.editor_client.get(
                              f'/institution/manuals/{self.manual.id}/files/'
                              f'{self.file_a["id"]}/draft/'))['revision'],
                          content=DOCX + b'-a2')
        self.assertFalse(has_error(resp), resp.content)
        # 发布前退出编辑会话（活跃会话阻断整套发布）
        import json as _json
        self.editor_client.delete(
            f'/institution/manuals/{self.manual.id}/files/{self.file_a["id"]}/draft/session/',
            data=_json.dumps({'session_key': key}),
            content_type='application/json')
        real_copyfile = __import__('shutil').copyfile

        def exploding_copy(src, dst, _real=real_copyfile):
            if 'versions' in str(dst):
                raise OSError('simulated snapshot copy failure')
            return _real(src, dst)

        with patch('shutil.copyfile', side_effect=exploding_copy):
            resp = self._publish(note='v2 应失败')
        self.assertTrue(has_error(resp))
        self.assertIn('快照', resp.json()['error'])
        # v1 生效不变、文件未损
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.current_version_id, v1.id)
        self.assertEqual(
            [storage.compute_file_hash(p) for p in v1_paths], v1_hashes)
        # 没有残留的 versions 孤儿文件：目录里只有 v1 的两份快照
        versions_dir = os.path.join(self._tmp.name, 'versions',
                                    f'manual_{self.manual.id}')
        produced = [
            os.path.join(root, name)
            for root, _, names in os.walk(versions_dir) for name in names
        ] if os.path.isdir(versions_dir) else []
        self.assertEqual(
            sorted(os.path.basename(p) for p in produced),
            sorted(os.path.basename(p) for p in v1_paths))

    def test_publish_excludes_removed_files(self):
        """移除文件退出下一版候选；已发布版本清单不变"""
        resp = self._publish(note='v1')
        self.assertFalse(has_error(resp), resp.content)
        v1 = ManualVersion.objects.get(manual=self.manual)
        self.assertEqual(v1.files.count(), 2)
        # 移除甲并改名乙，再发布 v2
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/{self.file_a["id"]}/remove/', {})
        self.assertFalse(has_error(resp), resp.content)
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/{self.file_b["id"]}/rename/',
                         {'name': '乙-改.docx'})
        self.assertFalse(has_error(resp), resp.content)
        resp = self._publish(note='v2 移除甲')
        self.assertFalse(has_error(resp), resp.content)
        v2 = ManualVersion.objects.get(pk=get_data(resp)['id'])
        self.assertEqual(v2.files.count(), 1)
        self.assertEqual(v2.files.first().display_name, '乙-改.docx')
        # v1 快照清单与内容不变
        v1_files = list(v1.files.order_by('sort_order', 'id'))
        self.assertEqual([f.display_name for f in v1_files], ['甲.docx', '乙.docx'])
        for f in v1_files:
            self.assertTrue(os.path.exists(
                storage.resolve_absolute_path(f.file_path)))

    def test_old_version_download_delegates_single_and_rejects_multi(self):
        """旧版本下载接口：单快照版本委托，多快照版本明确拒绝；
        版本文件清单接口逐份下载不受限"""
        resp = self._publish(note='v1')
        v1 = ManualVersion.objects.get(manual=self.manual)
        # 单快照（移除一份后发布 v2）
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/{self.file_a["id"]}/remove/', {})
        self.assertFalse(has_error(resp), resp.content)
        resp = self._publish(note='v2 单文件')
        self.assertFalse(has_error(resp), resp.content)
        v2 = ManualVersion.objects.get(pk=get_data(resp)['id'])
        # v1 两份：旧接口拒绝
        resp = self.viewer_client.get(
            f'/institution/manuals/{self.manual.id}/versions/{v1.id}/download/')
        self.assertTrue(has_error(resp))
        self.assertIn('多份文件', resp.json()['error'])
        # v2 一份：旧接口委托成功
        resp = self.viewer_client.get(
            f'/institution/manuals/{self.manual.id}/versions/{v2.id}/download/')
        self.assertEqual(resp.status_code, 200)
        # 文件清单接口逐份下载
        resp = self.viewer_client.get(
            f'/institution/manuals/{self.manual.id}/versions/{v1.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        items = get_data(resp)['items']
        self.assertEqual(len(items), 2)
        snapshot = items[0]
        resp = self.viewer_client.get(
            f'/institution/manuals/{self.manual.id}/versions/{v1.id}/'
            f'files/{snapshot["id"]}/download/')
        self.assertEqual(resp.status_code, 200)

    def test_version_files_visible_to_viewer_grant(self):
        viewer = make_user('v', tenant_id='deptY', perms=[PERM_VIEW])
        make_grant(self.manual, viewer, can_view=True)
        resp = self._publish(note='v1')
        self.assertFalse(has_error(resp), resp.content)
        v1 = ManualVersion.objects.get(manual=self.manual)
        resp = make_client(viewer).get(
            f'/institution/manuals/{self.manual.id}/versions/{v1.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(len(get_data(resp)['items']), 2)


class WholeRollbackTests(MultiFileBase):
    """整套回退：按版本快照重建草稿集合（所有者/管理员的管理动作）"""

    def setUp(self):
        super().setUp()
        self.file_a = self._add_file('甲.docx', DOCX + b'-a', owner=self.editor)
        self.file_b = self._add_file('乙.docx', DOCX + b'-b')
        self._set_password()
        # 首发交接：甲由负责人 editor 提交编制后发布 v1
        self._ensure_handoff(self.publisher)
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': 'v1'})
        self.assertFalse(has_error(resp), resp.content)
        self.v1 = ManualVersion.objects.get(manual=self.manual)

    def _publish(self, note='再发布'):
        self._ensure_handoff(self.publisher)
        return post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': note})

    def test_rollback_restores_set_from_snapshots(self):
        # v1 后：修改甲并退出会话，发布 v2（当前生效）；
        # 再新增丙、移除乙，随后整套回退 v1
        resp = self._start_session(client=self.editor_client,
                                   file_id=self.file_a['id'])
        key = get_data(resp)['session_key']
        resp = self._save(self.editor_client, self.file_a['id'], key, 1,
                          content=DOCX + b'-a2')
        self.assertFalse(has_error(resp), resp.content)
        self.editor_client.delete(
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.file_a["id"]}/draft/session/',
            data=json.dumps({'session_key': key}),
            content_type='application/json')
        v2 = ManualVersion.objects.get(pk=get_data(self._publish('v2'))['id'])
        self._add_file('丙.docx', DOCX + b'-c')
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/files/{self.file_b["id"]}/remove/', {})
        self.assertFalse(has_error(resp), resp.content)
        # 整套回退到 v1（所有者执行：回退重建全部草稿并撤销全部会话）
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/draft/from-version/',
                         {'version_id': self.v1.id})
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['restored_files'], 2)
        # 待发布集合重建为 v1 清单：丙退出、乙回归（原位置）、甲草稿=快照
        names = [i['name'] for i in self._files_list()]
        self.assertEqual(names, ['甲.docx', '乙.docx'])
        draft_a = ManualDraft.objects.get(file_id=self.file_a['id'])
        self.assertEqual(draft_a.file_hash, self.v1.files.get(
            manual_file_id=self.file_a['id']).file_hash)
        # 活跃会话已被整套回退失效
        self.assertEqual(
            ManualEditSession.objects.filter(
                manual=self.manual, revoked_at__isnull=True).count(), 0)
        # 再发布 v3：内容与当前生效版（v2）不同，版本号更大
        resp = self._publish()
        self.assertFalse(has_error(resp), resp.content)
        v3 = ManualVersion.objects.get(pk=get_data(resp)['id'])
        self.assertEqual(v3.version_no, 3)
        self.assertEqual(v3.files.count(), 2)
        # v1/v2 快照不变
        for version in (self.v1, v2):
            self.assertEqual(
                list(version.files.order_by('sort_order', 'id')
                     .values_list('display_name', flat=True)),
                ['甲.docx', '乙.docx'])

    def test_rollback_rejected_for_other_manual_version(self):
        other = Manual.objects.create(
            name='别家手册', code='OT-200',
            org_type=Manual.OWNER_SECTION, org_name='乙科室',
            tenant_id='deptA')
        foreign_version = ManualVersion.objects.create(
            manual=other, version_no=1, file_path='versions/x/y.docx',
            original_name='x.docx', published_by=self.publisher)
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/draft/from-version/',
                         {'version_id': foreign_version.id})
        self.assertTrue(has_error(resp))

    def test_rollback_rejected_for_editor_without_manage(self):
        """仅持编制授权（非所有者/管理员）不得触发整套回退"""
        resp = post_json(self.editor_client,
                         f'/institution/manuals/{self.manual.id}/draft/from-version/',
                         {'version_id': self.v1.id})
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])


class LegacySingleFileDelegationTests(MultiFileBase):
    """过渡期旧单文件接口：单文件委托、多文件拒绝"""

    def test_legacy_draft_apis_delegate_to_single_file(self):
        self._add_file('唯一.docx', owner=self.editor)
        self._set_password()
        # 旧 draft 详情
        resp = self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/draft/')
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revision'], 1)
        # 旧 session/save
        resp = self._start_session()
        self.assertFalse(has_error(resp), resp.content)
        key = get_data(resp)['session_key']
        resp = self.editor_client.post(
            f'/institution/manuals/{self.manual.id}/draft/save/',
            {'file': SimpleUploadedFile('v2.docx', DOCX + b'-v2'),
             'session_key': key, 'revision': 1})
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revision'], 2)

    def test_legacy_apis_reject_multi_file_manual(self):
        self._add_file('甲.docx')
        self._add_file('乙.docx')
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/draft/')
        self.assertTrue(has_error(resp))
        self.assertIn('多份文件', resp.json()['error'])
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/draft/create/', {})
        self.assertTrue(has_error(resp))
        self.assertIn('多份文件', resp.json()['error'])

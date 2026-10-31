# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""草稿恢复优先级的真实行为测试（2026-10-29 草稿恢复规则）

核心规则（draft/create 默认路径的严格优先级）：
- 存在当前草稿 -> 拒绝重建（继续编辑或明确执行重建），不得无提示覆盖；
- 无草稿但有当前生效版本 -> 从该版本中该文件的 ManualVersionFile 快照
  恢复（base_version=来源版本；当前版本不含该文件时明确报错，绝不
  静默改用原稿补齐）；
- 无草稿且制度从未发布过版本 -> 才从该文件最近一次原稿创建。

原稿重建（original_id）是明确的高级操作：制度发布过版本（含废止）时
必须 confirm 二次确认、丢弃草稿内容时须通过编辑密码、活跃编辑会话
存在时一律拒绝；操作记录含来源原稿/修订号/版本号/操作账号。

全部断言走 test client 真实请求链路 + 隔离测试库 + 临时存储目录；
草稿行删除仅为构造"草稿丢失"夹具，不掩盖任何业务路径。
"""
import json
import os
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.institution import services, storage
from apps.institution.models import (Manual, ManualDraft, ManualFile,
                                     ManualOperationLog, ManualOriginal,
                                     ManualVersion)
from apps.institution.tests.base import (
    ALL_PERMS, PERM_DRAFT, PERM_DOWNLOAD, PERM_PUBLISH, PERM_VIEW, get_data,
    has_error, make_client, make_grant, make_user, post_json, put_json,
    setup_test_env,
)

RTF_AS_DOC = (b'{\\rtf1\\ansi\\deff0 {\\fonttbl {\\f0 Times;}}'
              b'\\f0 \\fs24 Chapter One: Introduction\\par}')
BROKEN_DOC = b'\x00\x01not-a-word-file'
DOCX_A = b'PK\x03\x04 content-A'
DOCX_B = b'PK\x03\x04 content-B'


class DraftRecoveryBase(TestCase):
    """管理者 + 编制者 + 发布者；手册与编辑密码就绪"""

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
            name='恢复规则手册', code='HF-001',
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
        put_json(self.manager_client,
                 f'/institution/manuals/{self.manual.id}/password/',
                 {'password': 'edit-pass-1'})
        self.file_seq = 0

    def _add_file(self, name=None, content=DOCX_A, owner=None):
        """新增制度文件（files/create 一步建条目+原稿+草稿）；默认负责人
        =editor（草稿建立/重建/恢复与编辑均要求负责人独占）"""
        self.file_seq += 1
        name = name or f'文件{self.file_seq}.docx'
        payload = {'file': SimpleUploadedFile(name, content),
                   'owner_id': str((owner or self.editor).id)}
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/create/', payload)
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _files_list(self):
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/files/')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _file_row(self, file_id):
        return next(f for f in self._files_list() if f['id'] == file_id)

    def _publish(self, note='v1'):
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/publish/',
                         {'change_note': note})
        self.assertFalse(has_error(resp), resp.content)
        return ManualVersion.objects.get(pk=get_data(resp)['id'])

    def _create_draft(self, file_id, body=None, client=None):
        # 草稿建立/重建/恢复属内容写路径：负责人独占编辑（编制者执行）
        return post_json(
            client or self.editor_client,
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/create/',
            body or {})

    def _start_session(self, file_id, client=None, password='edit-pass-1'):
        client = client or self.editor_client
        return post_json(
            client,
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/session/',
            {'password': password})

    def _exit_session(self, file_id, session_key, client=None):
        client = client or self.editor_client
        resp = client.delete(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/session/',
            data=json.dumps({'session_key': session_key}),
            content_type='application/json')
        self.assertFalse(has_error(resp), resp.content)

    def _save_then_release(self, file_id, content=DOCX_B):
        """编辑者开会话保存后主动退出（发布前置校验拒绝活跃会话）"""
        resp = self._start_session(file_id)
        self.assertFalse(has_error(resp), resp.content)
        key = get_data(resp)['session_key']
        resp = self._save(file_id, key, 1, content=content)
        self.assertFalse(has_error(resp), resp.content)
        self._exit_session(file_id, key)

    def _save(self, file_id, session_key, revision, content=DOCX_B,
              client=None, name='saved.docx'):
        client = client or self.editor_client
        return client.post(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/save/',
            {'file': SimpleUploadedFile(name, content),
             'session_key': session_key, 'revision': revision})

    def _draft_rows(self, file_id=None):
        qs = ManualDraft.objects.all()
        if file_id:
            qs = qs.filter(file_id=file_id)
        return qs

    def _prepare_published(self):
        """单文件 + 已发布 v1 的基线夹具"""
        data = self._add_file('甲.docx', DOCX_A)
        version = self._publish('第一版')
        return data['id'], version


class NoVersionOriginalTests(DraftRecoveryBase):
    """无发布版本：原稿是首次建立草稿的正当来源"""

    def test_draft_missing_no_version_creates_from_latest_original(self):
        """用例1：没有草稿、没有发布版本 -> 从最近一次原稿创建"""
        # broken.doc：条目+原稿就绪但草稿建立失败（无草稿）
        data = self._add_file('broken.doc', BROKEN_DOC)
        file_id = data['id']
        self.assertIsNone(data['draft'])
        # 再上传一份可转换的 .doc 原稿（成为最近原稿）
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/originals/upload/',
            {'file': SimpleUploadedFile('可转换.doc', RTF_AS_DOC)})
        self.assertFalse(has_error(resp), resp.content)
        latest_original_id = get_data(resp)['id']
        self.assertEqual(
            ManualDraft.objects.filter(file_id=file_id).count(), 0)
        resp = self._create_draft(file_id)
        self.assertFalse(has_error(resp), resp.content)
        draft = ManualDraft.objects.get(file_id=file_id)
        self.assertEqual(draft.source_original_id, latest_original_id)
        self.assertIsNone(draft.base_version_id)
        self.assertEqual(draft.revision, 1)
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(draft.file_path)))
        # 原稿字节保持不变
        original = ManualOriginal.objects.get(pk=latest_original_id)
        with open(storage.resolve_absolute_path(original.file_path), 'rb') as f:
            self.assertEqual(f.read(), RTF_AS_DOC)

    def test_draft_create_without_any_original_rejected(self):
        data = self._add_file()
        ManualDraft.objects.filter(file_id=data['id']).delete()
        ManualOriginal.objects.filter(file_id=data['id']).delete()
        resp = self._create_draft(data['id'])
        self.assertTrue(has_error(resp))
        self.assertIn('原稿', resp.json()['error'])


class RestoreFromCurrentVersionTests(DraftRecoveryBase):
    """有当前生效版本：快照是唯一默认恢复来源"""

    def test_draft_missing_restores_from_current_version_snapshot(self):
        """用例2：没有草稿、有当前发布版本 -> 从当前版本快照恢复"""
        file_id, version = self._prepare_published()
        snapshot = version.files.get(manual_file_id=file_id)
        # 构造草稿丢失（业务语义：草稿不存在时不得自动回到原稿）
        ManualDraft.objects.filter(file_id=file_id).delete()
        resp = self._create_draft(file_id)
        self.assertFalse(has_error(resp), resp.content)
        data = get_data(resp)
        self.assertEqual(data['base_version_no'], 1)
        draft = ManualDraft.objects.get(file_id=file_id)
        self.assertEqual(draft.base_version_id, version.id)
        self.assertEqual(draft.file_hash, snapshot.file_hash)
        self.assertIsNone(draft.source_original_id)
        self.assertEqual(draft.revision, 1)
        # 恢复内容与快照字节一致，快照本体不动
        with open(storage.resolve_absolute_path(draft.file_path), 'rb') as f:
            self.assertEqual(f.read(), DOCX_A)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.file_hash,
                         version.files.get(manual_file_id=file_id).file_hash)

    def test_multi_version_restore_uses_current_not_first(self):
        """用例5：多个发布版本时恢复当前版本，而不是最初原稿/首版"""
        file_id, v1 = self._prepare_published()
        self._save_then_release(file_id, content=DOCX_B)
        v2 = self._publish('第二版')
        ManualDraft.objects.filter(file_id=file_id).delete()
        resp = self._create_draft(file_id)
        self.assertFalse(has_error(resp), resp.content)
        draft = ManualDraft.objects.get(file_id=file_id)
        self.assertEqual(draft.base_version_id, v2.id)
        self.assertEqual(
            draft.file_hash,
            v2.files.get(manual_file_id=file_id).file_hash)
        self.assertNotEqual(
            draft.file_hash, v1.files.get(manual_file_id=file_id).file_hash)
        with open(storage.resolve_absolute_path(draft.file_path), 'rb') as f:
            self.assertEqual(f.read(), DOCX_B)

    def test_file_missing_from_current_version_explicit_error(self):
        """用例6：当前版本不含该文件（后加入）-> 明确报错，不静默补原稿"""
        file_id, version = self._prepare_published()
        broken = self._add_file('新加入.doc', BROKEN_DOC)
        new_file_id = broken['id']
        self.assertIsNone(broken['draft'])
        resp = self._create_draft(new_file_id)
        self.assertTrue(has_error(resp))
        self.assertIn(f'v{version.version_no}', resp.json()['error'])
        self.assertIn('快照', resp.json()['error'])
        # 没有从原稿静默补齐
        self.assertEqual(
            ManualDraft.objects.filter(file_id=new_file_id).count(), 0)
        # 该文件原稿仍在，未被动用
        self.assertTrue(
            ManualOriginal.objects.filter(file_id=new_file_id).exists())
        # 版本快照不受影响
        self.assertEqual(
            version.files.filter(manual_file_id=new_file_id).count(), 0)

    def test_deprecated_without_current_version_rejected(self):
        """已废止（有历史版本、无生效版本）：不静默回原稿"""
        file_id, version = self._prepare_published()
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/deprecate/', {})
        self.assertFalse(has_error(resp), resp.content)
        ManualDraft.objects.filter(file_id=file_id).delete()
        resp = self._create_draft(file_id)
        self.assertTrue(has_error(resp))
        self.assertIn('无生效版本', resp.json()['error'])
        self.assertEqual(
            ManualDraft.objects.filter(file_id=file_id).count(), 0)

    def test_rollback_to_history_version_still_uses_given_version(self):
        """用例7：从历史版本回退仍按指定历史版本恢复（from-version 不变）"""
        file_id, v1 = self._prepare_published()
        self._save_then_release(file_id, content=DOCX_B)
        self._publish('第二版')
        # 整套回退是整册管理动作：手册所有者执行（2026-10-31 授权模型）
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/draft/from-version/',
            {'version_id': v1.id})
        self.assertFalse(has_error(resp), resp.content)
        draft = ManualDraft.objects.get(file_id=file_id)
        self.assertEqual(draft.base_version_id, v1.id)
        self.assertEqual(
            draft.file_hash, v1.files.get(manual_file_id=file_id).file_hash)
        with open(storage.resolve_absolute_path(draft.file_path), 'rb') as f:
            self.assertEqual(f.read(), DOCX_A)


class ExistingDraftGuardTests(DraftRecoveryBase):
    """已有草稿：默认路径拒绝，不得无提示覆盖"""

    def test_existing_draft_blocks_default_create(self):
        """用例3/4：有草稿时普通进入编辑不重建；draft/create 无提示覆盖被拒"""
        data = self._add_file('甲.docx', DOCX_A)
        file_id = data['id']
        before = ManualDraft.objects.get(file_id=file_id)
        resp = self._create_draft(file_id)
        self.assertTrue(has_error(resp))
        self.assertIn('已有草稿', resp.json()['error'])
        after = ManualDraft.objects.get(file_id=file_id)
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(after.file_path, before.file_path)
        # 普通编辑路径不受影响：草稿详情与会话照常
        resp = self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/')
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['revision'], before.revision)
        resp = self._start_session(file_id)
        self.assertFalse(has_error(resp), resp.content)

    def test_files_list_and_error_responses_carry_recovery_hint(self):
        """草稿缺失：files 清单行与草稿详情/会话错误响应均携带恢复途径"""
        file_id, version = self._prepare_published()
        ManualDraft.objects.filter(file_id=file_id).delete()
        rows = self._files_list()
        row = next(f for f in rows if f['id'] == file_id)
        self.assertEqual(row['draft_recovery']['source'], 'current_version')
        self.assertEqual(row['draft_recovery']['version_no'],
                         version.version_no)
        # 草稿详情：error + draft_recovery（HTTP 200 业务错误）
        resp = self.editor_client.get(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/draft/')
        body = resp.json()
        self.assertTrue(body['error'])
        self.assertEqual(body['draft_recovery']['source'], 'current_version')
        self.assertEqual(body['draft_recovery']['version_no'],
                         version.version_no)
        # 会话开启同样返回可恢复状态
        resp = self._start_session(file_id)
        body = resp.json()
        self.assertTrue(body['error'])
        self.assertEqual(body['draft_recovery']['source'], 'current_version')


class ExplicitRebuildTests(DraftRecoveryBase):
    """明确的「从原始上传文件重建草稿」：确认/密码/会话防线"""

    def _prepare_published_with_draft(self):
        data = self._add_file('甲.docx', DOCX_A)
        file_id = data['id']
        version = self._publish('第一版')
        return file_id, version

    def _latest_original_id(self, file_id):
        return ManualOriginal.objects.filter(
            file_id=file_id).order_by('-id').first().id

    def test_rebuild_requires_confirm_after_versions_exist(self):
        """已发布过版本：original_id 无 confirm 被拒（高风险二次确认）"""
        file_id, _ = self._prepare_published_with_draft()
        resp = self._create_draft(
            file_id, {'original_id': self._latest_original_id(file_id)})
        self.assertTrue(has_error(resp))
        self.assertIn('confirm', resp.json()['error'])

    def test_rebuild_requires_password_when_discarding_draft(self):
        """丢弃现有草稿的重建必须通过编辑密码（错误密码被拒且计数）"""
        file_id, _ = self._prepare_published_with_draft()
        body = {'original_id': self._latest_original_id(file_id),
                'confirm': True}
        resp = self._create_draft(file_id, body)
        self.assertTrue(has_error(resp))
        self.assertIn('编辑密码', resp.json()['error'])
        resp = self._create_draft(
            file_id, dict(body, password='wrong-pass'))
        self.assertTrue(has_error(resp))
        self.assertIn('编辑密码错误', resp.json()['error'])
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.password_fail_count, 1)

    def test_rebuild_blocked_by_active_session(self):
        """活跃编辑会话存在时一律拒绝重建（confirm+正确密码也不行）"""
        file_id, _ = self._prepare_published_with_draft()
        resp = self._start_session(file_id)
        self.assertFalse(has_error(resp), resp.content)
        body = {'original_id': self._latest_original_id(file_id),
                'confirm': True, 'password': 'edit-pass-1'}
        resp = self._create_draft(file_id, body)
        self.assertTrue(has_error(resp))
        self.assertIn('编辑会话', resp.json()['error'])
        # 草稿未被替换
        self.assertEqual(ManualDraft.objects.get(file_id=file_id).revision, 1)

    def test_rebuild_with_confirm_and_password_succeeds(self):
        """用例8：确认+密码+无会话 -> 重建成功并留痕"""
        file_id, version = self._prepare_published_with_draft()
        original_id = self._latest_original_id(file_id)
        body = {'original_id': original_id, 'confirm': True,
                'password': 'edit-pass-1'}
        resp = self._create_draft(file_id, body)
        self.assertFalse(has_error(resp), resp.content)
        draft = ManualDraft.objects.get(file_id=file_id)
        self.assertEqual(draft.revision, 2)
        self.assertEqual(draft.source_original_id, original_id)
        # 重建后草稿不再指向发布版本（来源=原稿）
        self.assertIsNone(draft.base_version_id)
        # 操作记录含来源原稿/重建前修订号/当前版本号/操作账号
        log = ManualOperationLog.objects.filter(
            manual=self.manual, action='create_draft').latest('id')
        detail = json.loads(log.detail or '{}')
        self.assertTrue(detail['rebuild_from_original'])
        self.assertEqual(detail['source_original_id'], original_id)
        self.assertEqual(detail['previous_revision'], 1)
        self.assertEqual(detail['current_version_no'], version.version_no)
        self.assertEqual(detail['file_revision'], 2)
        # 重建由文件负责人（编制授权）执行：操作人=editor
        self.assertEqual(log.user_name, self.editor.username)

    def test_rebuild_without_password_configured_needs_confirm_only(self):
        """未配置编辑密码的手册：confirm 即可（无密码可校验）"""
        file_id, _ = self._prepare_published_with_draft()
        # 直接构造"未配置密码"夹具（密码接口不允许空值）
        Manual.objects.filter(pk=self.manual.pk).update(password_hash='')
        resp = self._create_draft(
            file_id, {'original_id': self._latest_original_id(file_id),
                      'confirm': True})
        self.assertFalse(has_error(resp), resp.content)

    def test_rebuild_for_out_of_version_file_with_confirm(self):
        """当前版本不含的后加入文件：confirm 后可从原稿建草稿（明确路径）"""
        file_id, version = self._prepare_published_with_draft()
        broken = self._add_file('后加入.doc', BROKEN_DOC)
        new_file_id = broken['id']
        # 上传可转换原稿（后加入文件的候选原稿）
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/{new_file_id}/originals/upload/',
            {'file': SimpleUploadedFile('后加入可转换.doc', RTF_AS_DOC)})
        self.assertFalse(has_error(resp), resp.content)
        # 默认路径被拒（用例6），明确 confirm 后走原稿
        resp = self._create_draft(
            new_file_id, {'original_id': self._latest_original_id(new_file_id),
                          'confirm': True})
        self.assertFalse(has_error(resp), resp.content)
        draft = ManualDraft.objects.get(file_id=new_file_id)
        self.assertIsNone(draft.base_version_id)
        self.assertTrue(draft.source_original_id)


class RecoveryFailureCompensationTests(DraftRecoveryBase):
    """恢复/重建失败：数据库与物理文件不得留下半完成状态"""

    def _drafts_dir_file_count(self):
        base = storage.get_institution_storage_base()
        drafts_root = os.path.join(base, 'drafts')
        count = 0
        for root, _, names in os.walk(drafts_root):
            count += len(names)
        return count

    def test_restore_copy_failure_leaves_no_partial_state(self):
        """用例9：恢复复制失败 -> 明确报错，无草稿行、无残留文件"""
        data = self._add_file('甲.docx', DOCX_A)
        file_id = data['id']
        self._publish('第一版')
        ManualDraft.objects.filter(file_id=file_id).delete()
        before_count = self._drafts_dir_file_count()
        with patch('apps.institution.services.shutil.copyfile',
                   side_effect=OSError('disk error')):
            resp = self._create_draft(file_id)
        self.assertTrue(has_error(resp))
        self.assertIn('恢复草稿制作失败', resp.json()['error'])
        self.assertEqual(
            ManualDraft.objects.filter(file_id=file_id).count(), 0)
        self.assertEqual(self._drafts_dir_file_count(), before_count)
        # 版本快照完好
        version = ManualVersion.objects.get(manual=self.manual)
        self.assertEqual(
            version.files.get(manual_file_id=file_id).file_hash,
            storage.compute_file_hash(storage.resolve_absolute_path(
                version.files.get(manual_file_id=file_id).file_path)))

    def test_rebuild_write_failure_leaves_no_partial_state(self):
        """重建物理写入失败 -> 明确报错，无草稿行、无残留文件"""
        data = self._add_file('broken.doc', BROKEN_DOC)
        file_id = data['id']
        from django.core.files.uploadedfile import SimpleUploadedFile
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/originals/upload/',
            {'file': SimpleUploadedFile('可转换.doc', RTF_AS_DOC)})
        self.assertFalse(has_error(resp), resp.content)
        before_count = self._drafts_dir_file_count()
        with patch('apps.institution.services.storage.save_stream_to_path',
                   side_effect=OSError('disk full')):
            resp = self._create_draft(file_id)
        self.assertTrue(has_error(resp))
        self.assertIn('草稿文件写入失败', resp.json()['error'])
        self.assertEqual(
            ManualDraft.objects.filter(file_id=file_id).count(), 0)
        self.assertEqual(self._drafts_dir_file_count(), before_count)
        # 原稿不受影响
        original = ManualOriginal.objects.filter(
            file_id=file_id).latest('id')
        with open(storage.resolve_absolute_path(original.file_path), 'rb') as f:
            self.assertEqual(f.read(), RTF_AS_DOC)

    def test_restore_service_refuses_when_draft_exists(self):
        """恢复服务行锁内复核：草稿已存在时放弃恢复且不覆盖（含复制清理）"""
        data = self._add_file('甲.docx', DOCX_A)
        file_entry = ManualFile.objects.get(pk=data['id'])
        self._publish('第一版')
        draft_before = ManualDraft.objects.get(file=file_entry)
        before_count = self._drafts_dir_file_count()
        restored, err = services.restore_draft_from_current_version(
            file_entry, self.manager)
        self.assertIsNone(restored)
        self.assertIn('已有草稿', err)
        draft_after = ManualDraft.objects.get(file=file_entry)
        self.assertEqual(draft_after.revision, draft_before.revision)
        self.assertEqual(draft_after.file_path, draft_before.file_path)
        # 已复制的候选文件被清理，drafts/ 不留孤儿
        self.assertEqual(self._drafts_dir_file_count(), before_count)

    def test_restore_without_current_version_rejected(self):
        """服务级防线：无生效版本时拒绝从版本恢复"""
        data = self._add_file('甲.docx', DOCX_A)
        file_entry = ManualFile.objects.get(pk=data['id'])
        ManualDraft.objects.filter(file=file_entry).delete()
        restored, err = services.restore_draft_from_current_version(
            file_entry, self.manager)
        self.assertIsNone(restored)
        self.assertIn('没有生效版本', err)


class RestoreAuditAndImmutabilityTests(DraftRecoveryBase):
    """用例10/11：操作留痕与历史版本不可变"""

    def test_restore_logs_source_version_file_and_operator(self):
        data = self._add_file('甲.docx', DOCX_A)
        file_id = data['id']
        version = self._publish('第一版')
        ManualDraft.objects.filter(file_id=file_id).delete()
        resp = self._create_draft(file_id)
        self.assertFalse(has_error(resp), resp.content)
        draft = ManualDraft.objects.get(file_id=file_id)
        log = ManualOperationLog.objects.filter(
            manual=self.manual, action='restore_draft').latest('id')
        self.assertEqual(log.version_id, version.id)
        self.assertEqual(log.file_id, file_id)
        # 恢复由文件负责人（编制授权）执行：操作人=editor
        self.assertEqual(log.user_name, self.editor.username)
        detail = json.loads(log.detail or '{}')
        self.assertEqual(detail['from_version_no'], version.version_no)
        self.assertEqual(detail['file_revision'], draft.revision)
        self.assertEqual(detail['source'], 'current_version')

    def test_history_version_files_immutable_after_recovery(self):
        """用例11：恢复/重建后历史发布版本的哈希与内容不变"""
        data = self._add_file('甲.docx', DOCX_A)
        file_id = data['id']
        v1 = self._publish('第一版')
        self._save_then_release(file_id, content=DOCX_B)
        v2 = self._publish('第二版')

        def snapshot_state(version):
            return [(s.id, s.manual_file_id, s.file_path, s.file_hash,
                     os.path.getsize(storage.resolve_absolute_path(s.file_path)),
                     open(storage.resolve_absolute_path(s.file_path), 'rb').read())
                    for s in version.files.order_by('id')]

        v1_before = snapshot_state(v1)
        v2_before = snapshot_state(v2)
        # 先恢复（草稿丢失场景），再执行一次明确原稿重建
        ManualDraft.objects.filter(file_id=file_id).delete()
        resp = self._create_draft(file_id)
        self.assertFalse(has_error(resp), resp.content)
        original_id = ManualOriginal.objects.filter(
            file_id=file_id).order_by('-id').first().id
        resp = self._create_draft(file_id, {
            'original_id': original_id, 'confirm': True,
            'password': 'edit-pass-1'})
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(snapshot_state(v1), v1_before)
        self.assertEqual(snapshot_state(v2), v2_before)
        # ManualVersionFile 行级不变（含路径与哈希列）
        for version in (v1, v2):
            version.refresh_from_db()
            for s in version.files.all():
                s.refresh_from_db()

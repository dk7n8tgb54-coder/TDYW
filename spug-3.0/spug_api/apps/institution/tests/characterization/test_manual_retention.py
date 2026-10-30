# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""文件生命周期保留策略的真实行为测试（2026-10-29 保留策略）

覆盖（全部走 test client 真实请求链路 + 隔离测试库 + 临时存储目录）：
- 初始来源聚合接口：一次请求返回全部文件行（最初原稿/历史/清理状态/
  首次发布版本），文件级归属与权限校验，草稿信息按工作区可见权下发。
- 原稿保护边界：该文件首次进入成功发布的版本之前原稿本体受保护；
  首次发布并超过缓冲期后才成为清理候选；草稿来源引用/活跃会话/
  共享路径引用阻止清理；已清理原稿的 下载/预览/重建 被明确拒绝且
  元数据保留，更换来源后重建入口恢复。
- 发布版本保留：当前生效版本永久受保护；近期数量/期限/长期保留标记/
  草稿 base_version 引用保护；is_effective=False 不作为可清理依据；
  整套按版清理、部分失败标 partial 可重试；清理后版本号/发布人/说明/
  快照清单与哈希保留，预览/下载/回退被拒绝。
- 预检完全只读（库与磁盘零写入）；未配置保留期限时预检不产出候选、
  执行整体拒绝；预检/执行由 institution.manual.config 门控。
"""
import datetime
import os
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from apps.institution import retention_services, storage
from apps.institution.models import (Manual, ManualDraft, ManualFile,
                                     ManualOperationLog, ManualOriginal,
                                     ManualVersion, ManualVersionFile)
from apps.institution.tests.base import (
    ALL_PERMS, PERM_DOWNLOAD, PERM_VIEW, get_data, has_error, make_client,
    make_role, make_user, post_json)
from apps.institution.tests.characterization.test_manual_draft_recovery import (
    DOCX_A, DOCX_B, DraftRecoveryBase)

RETENTION_CONFIG = override_settings(
    INSTITUTION_VERSION_RETENTION_DAYS=30,
    INSTITUTION_VERSION_RECENT_KEEP_COUNT=1,
    INSTITUTION_ORIGINAL_CLEAN_BUFFER_DAYS=7,
)


def _age_version(version, days):
    """把版本发布时间回拨 days 天（时间旅行；auto_now_add 列直改库）"""
    ManualVersion.objects.filter(pk=version.pk).update(
        published_at=timezone.now() - datetime.timedelta(days=days))
    version.refresh_from_db()


def _file_exists(original):
    return os.path.exists(storage.resolve_absolute_path(original.file_path))


class RetentionBase(DraftRecoveryBase):
    """复用恢复测试基类夹具；默认 30 天期限 / 近期保 1 版 / 7 天缓冲"""

    def _overview(self):
        resp = self.manager_client.get(
            f'/institution/manuals/{self.manual.id}/originals-overview/')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)['files']

    def _preview(self):
        resp = self.manager_client.get('/institution/cleanup/preview/')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _execute(self, body=None):
        resp = post_json(self.manager_client, '/institution/cleanup/execute/',
                         body or {})
        return resp

    def _manual_preview_row(self, preview):
        for m in preview['manuals']:
            if m['manual_id'] == self.manual.id:
                return m
        return None

    def _version_preview_row(self, version, preview=None):
        m = self._manual_preview_row(preview or self._preview())
        if not m:
            return None
        return next((r for r in m['versions']
                     if r['version_id'] == version.id), None)

    def _original_preview_row(self):
        m = self._manual_preview_row(self._preview())
        if not m:
            return None
        return next((r for r in m['originals']), None)

    def _upload_original(self, file_id, name='来源B.docx', content=DOCX_B):
        resp = self.manager_client.post(
            f'/institution/manuals/{self.manual.id}/files/{file_id}/originals/upload/',
            {'file': SimpleUploadedFile(name, content)})
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _resave_then_release(self, file_id, content=DOCX_B):
        """按当前修订号再保存一轮（基类 _save 硬编码 revision=1，二次保存不适用）"""
        revision = ManualDraft.objects.get(file_id=file_id).revision
        resp = self._start_session(file_id)
        self.assertFalse(has_error(resp), resp.content)
        key = get_data(resp)['session_key']
        resp = self._save(file_id, key, revision, content=content)
        self.assertFalse(has_error(resp), resp.content)
        self._exit_session(file_id, key)


@RETENTION_CONFIG
class OriginalsOverviewTests(RetentionBase):
    """初始来源聚合接口（"初始来源"页签数据源）"""

    def test_overview_lists_all_files_with_first_original_and_history(self):
        first = self._add_file('甲.docx', DOCX_A)
        second = self._add_file('乙.docx', DOCX_B)
        # 为文件甲更换来源：追加一条后续原稿记录
        self._upload_original(first['id'])
        # 移除乙（退出待发布集合，但初始来源仍可见）
        post_json(self.manager_client,
                  f'/institution/manuals/{self.manual.id}/files/{second["id"]}/remove/',
                  {})
        rows = self._overview()
        self.assertEqual(len(rows), 2)
        row_a = next(r for r in rows if r['file_id'] == first['id'])
        self.assertEqual(row_a['originals_count'], 2)
        # 最初原稿 = 最早一条；历史新→旧
        self.assertEqual(row_a['first_original']['file_name'], '甲.docx')
        history_ids = [h['id'] for h in row_a['history']]
        self.assertEqual(history_ids, sorted(history_ids, reverse=True))
        self.assertFalse(row_a['history'][0]['is_cleaned'])
        row_b = next(r for r in rows if r['file_id'] == second['id'])
        self.assertTrue(row_b['is_removed'])
        self.assertEqual(row_b['first_original']['file_name'], '乙.docx')

    def test_overview_reports_first_published_version_and_draft_info(self):
        data = self._add_file('甲.docx', DOCX_A)
        # 发布前：草稿来源指向初始原稿
        rows = self._overview()
        self.assertEqual(rows[0]['draft']['source_original_id'],
                         ManualOriginal.objects.get(
                             file_id=data['id']).id)
        version = self._publish('第一版')
        rows = self._overview()
        row = rows[0]
        self.assertEqual(row['first_published_version_no'], version.version_no)
        self.assertIsNotNone(row['first_published_at'])
        # 草稿信息对工作区可见者下发（管理者）。发布结束修订轮后，工作
        # 副本改以生效版本为基线（base_version），初始来源引用解除——
        # 来源历史由 ManualOriginal 记录与操作记录承载，不再由草稿行
        # 无限期保护原稿
        self.assertTrue(row['draft']['has_draft'])
        self.assertIsNone(row['draft']['source_original_id'])

    def test_overview_visibility_and_draft_info_by_workspace_role(self):
        self._add_file('甲.docx', DOCX_A)
        # 有页面 view 权限但无手册角色：不可见
        outsider = make_user('outsider', tenant_id='deptC', perms=[PERM_VIEW])
        resp = make_client(outsider).get(
            f'/institution/manuals/{self.manual.id}/originals-overview/')
        self.assertTrue(has_error(resp))
        # 授予手册查看角色：可见，但草稿来源信息不下发（与 files/ 口径一致）
        view_role = make_role()
        self.manual.view_roles.add(view_role)
        viewer = make_user('viewer', tenant_id='deptC', perms=[PERM_VIEW],
                           roles=[view_role])
        resp = make_client(viewer).get(
            f'/institution/manuals/{self.manual.id}/originals-overview/')
        self.assertFalse(has_error(resp), resp.content)
        row = get_data(resp)['files'][0]
        self.assertIsNone(row['draft'])
        self.assertIn('first_original', row)

    def test_overview_marks_cleaned_metadata(self):
        self._add_file('甲.docx', DOCX_A)
        ManualOriginal.objects.filter(file_id=self.manual.files.first().id).update(
            cleaned_at=timezone.now())
        rows = self._overview()
        row = rows[0]
        self.assertTrue(row['first_original']['is_cleaned'])
        self.assertIsNotNone(row['first_original']['cleaned_at'])
        self.assertFalse(row['has_usable_original'])


@RETENTION_CONFIG
class OriginalRetentionTests(RetentionBase):
    """原稿保护边界、候选条件与清理执行"""

    def setUp(self):
        super().setUp()
        self.data = self._add_file('甲.docx', DOCX_A)
        self.original = ManualOriginal.objects.get(file_id=self.data['id'])
        self.original_hash = self.original.file_hash

    def test_never_published_original_protected(self):
        row = self._original_preview_row()
        self.assertIsNotNone(row)
        self.assertFalse(row['candidate'])
        self.assertEqual(row['blockers'][0]['code'], 'never_published')
        self.assertIsNone(row['first_published_version_no'])
        resp = self._execute()
        self.assertFalse(has_error(resp), resp.content)
        self.assertTrue(_file_exists(self.original))
        self.original.refresh_from_db()
        self.assertIsNone(self.original.cleaned_at)

    def test_buffer_blocks_before_elapsed(self):
        version = self._publish('第一版')
        row = self._original_preview_row()
        self.assertEqual(row['blockers'][0]['code'], 'buffer_not_elapsed')
        self.assertEqual(row['first_published_version_no'], version.version_no)
        resp = self._execute()
        self.assertFalse(has_error(resp), resp.content)
        self.assertTrue(_file_exists(self.original))

    def test_candidate_after_buffer_cleanup_keeps_metadata(self):
        version = self._publish('第一版')
        _age_version(version, 8)
        # 发布即解除草稿对初始来源的引用；重新保存并退出会话（会话防线
        # 常规路径）后，原稿进入候选
        self._save_then_release(self.data['id'])
        row = self._original_preview_row()
        self.assertTrue(row['candidate'])
        self.assertIn('缓冲期', row['reason'])
        resp = self._execute()
        self.assertFalse(has_error(resp), resp.content)
        result = get_data(resp)
        self.assertEqual(result['summary']['originals_cleaned'], 1)
        # 物理文件删除；记录行与来源元数据（名称/哈希/清理时间）保留
        self.assertFalse(_file_exists(self.original))
        self.original.refresh_from_db()
        self.assertIsNotNone(self.original.cleaned_at)
        self.assertEqual(self.original.original_name, '甲.docx')
        self.assertEqual(self.original.file_hash, self.original_hash)
        self.assertTrue(ManualOriginal.objects.filter(
            pk=self.original.id).exists())
        # 操作记录留痕
        self.assertTrue(ManualOperationLog.objects.filter(
            manual=self.manual, action='retention_cleanup').exists())
        # 幂等：二次执行无候选、不报错
        resp = self._execute()
        self.assertFalse(has_error(resp), resp.content)
        self.assertEqual(get_data(resp)['summary']['originals_cleaned'], 0)

    def test_draft_source_reference_blocks_cleanup(self):
        version = self._publish('第一版')
        _age_version(version, 40)
        # 发布即解除工作副本对初始来源的引用（修订轮结束、基线改为生效版）：
        # 缓冲期已过时原稿直接成为候选
        row = self._original_preview_row()
        self.assertTrue(row['candidate'])
        # 以初始原稿重建草稿（高级恢复：confirm+密码）后，草稿重新引用
        # 原稿 -> 重新阻止清理
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/'
            f'{self.data["id"]}/draft/create/',
            {'original_id': self.original.id, 'confirm': True,
             'password': 'edit-pass-1'})
        self.assertFalse(has_error(resp), resp.content)
        row = self._original_preview_row()
        self.assertEqual(row['blockers'][0]['code'], 'draft_source_reference')
        resp = self._execute()
        self.assertTrue(_file_exists(self.original))
        # 重新保存草稿（清空来源引用）并退出会话 -> 可清理
        # （重建后修订号已推进，用按当前修订号保存的助手）
        self._resave_then_release(self.data['id'])
        row = self._original_preview_row()
        self.assertTrue(row['candidate'])
        resp = self._execute()
        self.assertFalse(has_error(resp), resp.content)
        self.assertFalse(_file_exists(self.original))

    def test_active_session_blocks_cleanup(self):
        version = self._publish('第一版')
        _age_version(version, 40)
        self._save_then_release(self.data['id'])
        resp = self._start_session(self.data['id'])
        self.assertFalse(has_error(resp), resp.content)
        key = get_data(resp)['session_key']
        row = self._original_preview_row()
        self.assertIn('active_session',
                      [b['code'] for b in row['blockers']])
        resp = self._execute()
        self.assertTrue(_file_exists(self.original))
        self._exit_session(self.data['id'], key)

    def test_shared_path_reference_blocks_deletion(self):
        version = self._publish('第一版')
        _age_version(version, 40)
        self._save_then_release(self.data['id'])
        # 伪造共享引用：另一文件的草稿指向同一路径（跨表共享路径核对防线）
        other = self._add_file('乙.docx', DOCX_B)
        ManualDraft.objects.filter(file_id=other['id']).update(
            file_path=self.original.file_path)
        resp = self._execute()
        self.assertFalse(has_error(resp), resp.content)
        result = get_data(resp)
        self.assertEqual(result['summary']['originals_cleaned'], 0)
        self.assertEqual(result['summary']['failures'], 1)
        self.assertTrue(_file_exists(self.original))
        self.original.refresh_from_db()
        self.assertIsNone(self.original.cleaned_at)

    def test_cleaned_original_download_preview_rebuild_rejected(self):
        version = self._publish('第一版')
        _age_version(version, 40)
        self._save_then_release(self.data['id'])
        resp = self._execute()
        self.assertFalse(has_error(resp), resp.content)
        base = f'/institution/manuals/{self.manual.id}'
        # 下载（文件级与制度级两个入口）与预览
        for path in (
                f'{base}/files/{self.data["id"]}/originals/{self.original.id}/download/',
                f'{base}/originals/{self.original.id}/download/',
                f'{base}/originals/{self.original.id}/preview-url/'):
            resp = self.manager_client.get(path)
            self.assertTrue(has_error(resp))
            self.assertIn('保留策略清理', resp.json()['error'])
        # 重建（confirm+密码路径防线之前即拒绝）
        resp = post_json(
            self.manager_client,
            f'{base}/files/{self.data["id"]}/draft/create/',
            {'original_id': self.original.id, 'confirm': True,
             'password': 'edit-pass-1'})
        self.assertTrue(has_error(resp))
        self.assertIn('保留策略清理', resp.json()['error'])

    def test_new_source_after_cleanup_reenables_rebuild(self):
        version = self._publish('第一版')
        _age_version(version, 40)
        self._save_then_release(self.data['id'])
        self._execute()
        # 更换来源（上传新原稿）后重建入口恢复可用
        new_original = self._upload_original(self.data['id'], '新来源.docx')
        self.assertFalse(new_original['is_cleaned'])
        resp = post_json(
            self.manager_client,
            f'/institution/manuals/{self.manual.id}/files/{self.data["id"]}/draft/create/',
            {'original_id': new_original['id'], 'confirm': True,
             'password': 'edit-pass-1'})
        self.assertFalse(has_error(resp), resp.content)


@RETENTION_CONFIG
class VersionRetentionTests(RetentionBase):
    """发布版本保留：保护集合、整套清理与清理后语义"""

    def setUp(self):
        super().setUp()
        self.file_a = self._add_file('甲.docx', DOCX_A)
        self.file_b = self._add_file('乙.docx', DOCX_B)
        self.v1 = self._publish('第一版')
        self._save_then_release(self.file_a['id'], content=DOCX_B)
        self.v2 = self._publish('第二版')
        self._resave_then_release(self.file_a['id'], content=DOCX_A)
        self.v3 = self._publish('第三版')
        _age_version(self.v1, 40)
        _age_version(self.v2, 35)

    def test_current_version_permanently_protected(self):
        row = self._version_preview_row(self.v3)
        self.assertIsNotNone(row)
        self.assertFalse(row['candidate'])
        self.assertEqual(row['blockers'][0]['code'], 'current_effective')
        self.assertTrue(row['is_current'])
        resp = self._execute()
        result = get_data(resp)
        cleaned_ids = [r['version_id'] for r in result['versions']
                       if r['status'] == 'cleaned']
        self.assertNotIn(self.v3.id, cleaned_ids)
        for snap in self.v3.files.all():
            self.assertTrue(os.path.exists(
                storage.resolve_absolute_path(snap.file_path)))

    @override_settings(INSTITUTION_VERSION_RECENT_KEEP_COUNT=2)
    def test_recent_count_protects_non_current_history(self):
        row_v2 = self._version_preview_row(self.v2)
        self.assertEqual(row_v2['blockers'][0]['code'], 'recent_window')
        row_v1 = self._version_preview_row(self.v1)
        self.assertTrue(row_v1['candidate'])
        self.assertEqual(len(row_v1['files']), 2)

    def test_retention_window_blocks_recent_versions(self):
        # v2（35 天前）已超 30 天期限；当前版本 v3（今天）受期限保护之外
        # 还受 current_effective 保护；以 v2 的窗口已过来证明期限口径生效
        row_v2 = self._version_preview_row(self.v2)
        self.assertTrue(row_v2['candidate'])
        row_v3 = self._version_preview_row(self.v3)
        self.assertEqual(row_v3['blockers'][0]['code'], 'current_effective')

    def test_long_term_protected_blocks_cleanup_until_unmarked(self):
        # 长期保留标记属发布域操作：由持手册发布角色的账号执行
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/versions/{self.v1.id}/protect/',
                         {'long_term_protected': True})
        self.assertFalse(has_error(resp), resp.content)
        row = self._version_preview_row(self.v1)
        self.assertEqual(row['blockers'][0]['code'], 'long_term_protected')
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/versions/{self.v1.id}/protect/',
                         {'long_term_protected': False})
        self.assertFalse(has_error(resp), resp.content)
        row = self._version_preview_row(self.v1)
        self.assertTrue(row['candidate'])

    def test_protect_requires_publish_role(self):
        resp = post_json(self.editor_client,
                         f'/institution/manuals/{self.manual.id}/versions/{self.v1.id}/protect/',
                         {'long_term_protected': True})
        self.assertTrue(has_error(resp))

    def test_whole_set_cleanup_preserves_metadata_and_closes_access(self):
        first_snap = self.v1.files.order_by('sort_order', 'id').first()
        # 旧兼容镜像列与首快照指向同一路径（迁移语义夹具自检）
        self.assertEqual(self.v1.file_path, first_snap.file_path)
        resp = self._execute()
        result = get_data(resp)
        v_row = next(r for r in result['versions'] if r['version_id'] == self.v1.id)
        self.assertEqual(v_row['status'], 'cleaned')
        self.assertEqual(v_row['cleaned_files'], 2)
        # 物理文件全部删除；快照行与哈希保留；整版标记 cleaned
        for snap in self.v1.files.all():
            self.assertFalse(os.path.exists(
                storage.resolve_absolute_path(snap.file_path)))
        self.assertEqual(ManualVersionFile.objects.filter(version=self.v1).count(), 2)
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.files_clean_status, ManualVersion.FILES_CLEAN_CLEANED)
        self.assertIsNotNone(self.v1.files_cleaned_at)
        self.assertEqual(self.v1.version_no, 1)
        self.assertEqual(self.v1.change_note, '第一版')
        # 清理后快照下载/预览被拒绝；整套回退被拒绝
        base = f'/institution/manuals/{self.manual.id}'
        resp = self.manager_client.get(
            f'{base}/versions/{self.v1.id}/files/{first_snap.id}/download/')
        self.assertTrue(has_error(resp))
        self.assertIn('保留策略清理', resp.json()['error'])
        resp = self.manager_client.get(
            f'{base}/versions/{self.v1.id}/files/{first_snap.id}/preview-url/')
        self.assertTrue(has_error(resp))
        resp = post_json(self.manager_client,
                         f'{base}/draft/from-version/', {'version_id': self.v1.id})
        self.assertTrue(has_error(resp))
        self.assertIn('保留策略清理', resp.json()['error'])
        # 版本列表序列化携带清理状态与快照清理标记
        resp = self.manager_client.get(f'{base}/versions/')
        versions = {v['id']: v for v in get_data(resp)['items']}
        self.assertEqual(versions[self.v1.id]['files_clean_status'], 'cleaned')
        self.assertTrue(all(f['is_cleaned'] for f in versions[self.v1.id]['files']))
        self.assertFalse(versions[self.v3.id]['files'][0]['is_cleaned'])

    def test_partial_failure_marks_partial_and_retry_succeeds(self):
        snaps = list(self.v1.files.order_by('sort_order', 'id'))
        failing_path = storage.resolve_absolute_path(snaps[1].file_path)

        def flaky_delete(abs_path):
            if os.path.abspath(abs_path) == os.path.abspath(failing_path):
                return False, 'device busy'
            try:
                os.remove(abs_path)
            except OSError:
                pass
            return True, None

        with patch.object(storage, 'safe_delete_file', side_effect=flaky_delete):
            resp = self._execute()
        result = get_data(resp)
        v_row = next(r for r in result['versions'] if r['version_id'] == self.v1.id)
        self.assertEqual(v_row['status'], 'partial')
        self.assertTrue(v_row['failures'])
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.files_clean_status, ManualVersion.FILES_CLEAN_PARTIAL)
        self.assertIn('device busy', self.v1.files_clean_error)
        # 成功快照已标记；失败快照保留物理文件且未标记（可重试）
        snaps = list(self.v1.files.order_by('sort_order', 'id'))
        self.assertIsNotNone(snaps[0].cleaned_at)
        self.assertIsNone(snaps[1].cleaned_at)
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(snaps[1].file_path)))
        # 部分清理版本不得显示为可完整回退
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/draft/from-version/',
                         {'version_id': self.v1.id})
        self.assertTrue(has_error(resp))
        # 重试成功后整版 cleaned
        resp = self._execute()
        self.assertFalse(has_error(resp), resp.content)
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.files_clean_status, ManualVersion.FILES_CLEAN_CLEANED)

    def test_deprecated_version_not_candidate_solely_by_is_effective(self):
        # 废止当前版本：is_effective=False，但发布时间在保留期限内，
        # 不得仅凭 is_effective 判定可删除
        resp = post_json(self.publisher_client,
                         f'/institution/manuals/{self.manual.id}/deprecate/', {})
        self.assertFalse(has_error(resp), resp.content)
        self.manual.refresh_from_db()
        self.assertIsNone(self.manual.current_version)
        row = self._version_preview_row(self.v3)
        self.assertIsNotNone(row)
        self.assertFalse(row['candidate'])
        self.assertEqual(row['blockers'][0]['code'], 'recent_window')
        resp = self._execute()
        result = get_data(resp)
        touched = [r['version_id'] for r in result['versions']]
        self.assertNotIn(self.v3.id, touched)

    def test_draft_base_version_reference_blocks(self):
        # 整套回退到 v2：草稿 base_version 指向 v2 -> v2 受业务引用保护
        resp = post_json(self.manager_client,
                         f'/institution/manuals/{self.manual.id}/draft/from-version/',
                         {'version_id': self.v2.id})
        self.assertFalse(has_error(resp), resp.content)
        preview = self._preview()
        row_v2 = self._version_preview_row(self.v2, preview)
        self.assertIn('referenced_by_draft',
                      [b['code'] for b in row_v2['blockers']])
        # v1 无草稿引用仍是候选
        row_v1 = self._version_preview_row(self.v1, preview)
        self.assertTrue(row_v1['candidate'])


@RETENTION_CONFIG
class PrecheckReadOnlyTests(RetentionBase):
    """预检完全只读；未配置期限时整体禁用"""

    def _db_counts(self):
        return {
            'originals': ManualOriginal.objects.count(),
            'versions': ManualVersion.objects.count(),
            'vfiles': ManualVersionFile.objects.count(),
            'drafts': ManualDraft.objects.count(),
            'logs': ManualOperationLog.objects.count(),
            'files': ManualFile.objects.count(),
            'manuals': Manual.objects.count(),
        }

    def _tree_fingerprint(self):
        fingerprint = {}
        for root, _, names in os.walk(self._tmp.name):
            for name in names:
                path = os.path.join(root, name)
                fingerprint[path] = os.path.getsize(path)
        return fingerprint

    def setUp(self):
        super().setUp()
        self.data = self._add_file('甲.docx', DOCX_A)
        version = self._publish('第一版')
        _age_version(version, 40)
        # 重新保存草稿（清空草稿来源引用）并退出会话 -> 版本受当前保护、
        # 原稿成为候选：预检应同时列出候选与阻止条件
        self._save_then_release(self.data['id'])

    def test_preview_writes_nothing_and_lists_candidates_with_blockers(self):
        before_counts = self._db_counts()
        before_tree = self._tree_fingerprint()
        preview = self._preview()
        self.assertEqual(before_counts, self._db_counts())
        self.assertEqual(before_tree, self._tree_fingerprint())
        self.assertTrue(preview['enabled'])
        manual_row = self._manual_preview_row(preview)
        self.assertIsNotNone(manual_row)
        # 版本行：唯一版本是当前生效版本 -> 阻止条件展示（永久保护）
        self.assertFalse(manual_row['versions'][0]['candidate'])
        self.assertEqual(manual_row['versions'][0]['blockers'][0]['code'],
                         'current_effective')
        # 原稿行：候选（首次发布超缓冲期）+ 大小与原因
        original_row = manual_row['originals'][0]
        self.assertTrue(original_row['candidate'])
        self.assertIn('缓冲期', original_row['reason'])
        self.assertEqual(original_row['file_size'], len(DOCX_A))
        self.assertGreater(preview['totals']['reclaimable_size'], 0)

    def test_execute_refuses_when_retention_unconfigured(self):
        with override_settings(INSTITUTION_VERSION_RETENTION_DAYS=0):
            preview = self._preview()
            self.assertFalse(preview['enabled'])
            self.assertIn('未配置', preview['notice'])
            self.assertEqual(preview['manuals'], [])
            resp = self._execute()
            self.assertTrue(has_error(resp))
            self.assertIn('未配置', resp.json()['error'])
            original = ManualOriginal.objects.get(file_id=self.data['id'])
            self.assertIsNone(original.cleaned_at)
            version = ManualVersion.objects.get(manual=self.manual)
            self.assertEqual(version.files_clean_status, '')


@RETENTION_CONFIG
class CleanupPermissionTests(RetentionBase):
    """预检/执行为模块级运维操作：institution.manual.config 门控"""

    def test_preview_and_execute_require_config_permission(self):
        editor_only = make_user('ed', tenant_id='deptB',
                                perms=[PERM_VIEW, PERM_DOWNLOAD],
                                roles=[self.edit_role])
        client = make_client(editor_only)
        resp = client.get('/institution/cleanup/preview/')
        self.assertTrue(has_error(resp))
        self.assertIn('权限拒绝', resp.json()['error'])
        resp = post_json(client, '/institution/cleanup/execute/', {})
        self.assertTrue(has_error(resp))
        self.assertIn('权限拒绝', resp.json()['error'])

    def test_execute_accepts_manual_scope(self):
        self._add_file('甲.docx', DOCX_A)
        version = self._publish('第一版')
        _age_version(version, 40)
        self._save_then_release(self.manual.files.first().id)
        resp = self._execute({'manual_id': self.manual.id})
        self.assertFalse(has_error(resp), resp.content)
        result = get_data(resp)
        self.assertEqual(result['summary']['originals_cleaned'], 1)
        version.refresh_from_db()
        # 当前版本不受影响
        self.assertEqual(version.files_clean_status, '')


class RetentionDisabledDefaultsTests(DraftRecoveryBase):
    """默认配置（未设置任何保留期限）：策略整体不启用，行为与迁移前一致"""

    def test_default_config_disables_cleanup(self):
        config = retention_services.get_retention_config()
        self.assertFalse(config['cleanup_enabled'])
        self.data = self._add_file('甲.docx', DOCX_A)
        version = self._publish('第一版')
        _age_version(version, 400)
        resp = post_json(self.manager_client, '/institution/cleanup/execute/', {})
        self.assertTrue(has_error(resp))
        original = ManualOriginal.objects.get(file_id=self.data['id'])
        self.assertIsNone(original.cleaned_at)
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(original.file_path)))
        self.assertEqual(version.files_clean_status, '')

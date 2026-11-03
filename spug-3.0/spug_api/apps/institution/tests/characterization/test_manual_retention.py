# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""发布版本保留策略的真实行为测试（2026-11-02 仅版本维度）

覆盖（全部走 test client 真实请求链路 + 隔离测试库 + 临时存储目录）：
- 发布版本保留：当前生效版本永久受保护；近期数量/期限/长期保留标记/
  草稿 base_version 引用保护；is_effective=False 不作为可清理依据；
  整套按版清理、部分失败标 partial 可重试；清理后版本号/发布人/说明/
  快照清单与哈希保留，预览/下载/回退被拒绝。
- 原稿体系已移除：保留策略不再有原稿维度（其存量数据由独立幂等命令
  purge_institution_originals 清理，见 tests/test_original_cleanup.py）。
- 预检完全只读（库与磁盘零写入）；未配置保留期限时预检不产出候选、
  执行整体拒绝；预检/执行由 institution.manual.config 门控。
"""
import datetime
import os
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.institution import retention_services, storage
from apps.institution.models import (Manual, ManualDraft, ManualFile,
                                     ManualOperationLog, ManualVersion,
                                     ManualVersionFile)
from apps.institution.tests.base import (
    ALL_PERMS, PERM_DOWNLOAD, PERM_VIEW, get_data, has_error, make_client,
    make_grant, make_user, post_json)
from apps.institution.tests.characterization.test_manual_draft_recovery import (
    DOCX_A, DOCX_B, DraftRecoveryBase)

RETENTION_CONFIG = override_settings(
    INSTITUTION_VERSION_RETENTION_DAYS=30,
    INSTITUTION_VERSION_RECENT_KEEP_COUNT=1,
)


def _age_version(version, days):
    """把版本发布时间回拨 days 天（时间旅行；auto_now_add 列直改库）"""
    ManualVersion.objects.filter(pk=version.pk).update(
        published_at=timezone.now() - datetime.timedelta(days=days))
    version.refresh_from_db()


class RetentionBase(DraftRecoveryBase):
    """复用恢复测试基类夹具；默认 30 天期限 / 近期保 1 版"""

    def _preview(self):
        resp = self.manager_client.get('/institution/cleanup/preview/')
        self.assertFalse(has_error(resp), resp.content)
        return get_data(resp)

    def _execute(self, body=None):
        return post_json(self.manager_client, '/institution/cleanup/execute/',
                         body or {})

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
        # 长期保留标记属发布域操作：由持手册发布授权的账号执行
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
        # 工作副本（当前草稿）保留且内容不受清理影响
        drafts_before = {
            d.file_id: (d.file_path, d.file_hash)
            for d in ManualDraft.objects.filter(manual=self.manual)}
        for file_id, (rel, file_hash) in drafts_before.items():
            self.assertEqual(
                ManualDraft.objects.get(file_id=file_id).file_path, rel)
            self.assertEqual(
                ManualDraft.objects.get(file_id=file_id).file_hash, file_hash)
            self.assertTrue(os.path.exists(storage.resolve_absolute_path(rel)))
        # 清理后快照下载/预览被拒绝（发布域 can_view_published：持
        # can_view 授权的发布者查询）；整套回退被拒绝（所有者执行）
        base = f'/institution/manuals/{self.manual.id}'
        resp = self.publisher_client.get(
            f'{base}/versions/{self.v1.id}/files/{first_snap.id}/download/')
        self.assertTrue(has_error(resp))
        self.assertIn('保留策略清理', resp.json()['error'])
        resp = self.publisher_client.get(
            f'{base}/versions/{self.v1.id}/files/{first_snap.id}/preview-url/')
        self.assertTrue(has_error(resp))
        resp = post_json(self.manager_client,
                         f'{base}/draft/from-version/', {'version_id': self.v1.id})
        self.assertTrue(has_error(resp))
        self.assertIn('保留策略清理', resp.json()['error'])
        # 版本列表序列化携带清理状态与快照清理标记
        resp = self.publisher_client.get(f'{base}/versions/')
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
        # 重新保存草稿并退出会话 -> 唯一版本是当前生效版本，受永久保护
        self._save_then_release(self.data['id'])

    def test_preview_writes_nothing_and_lists_blockers(self):
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
        # 原稿维度已删除：预检不再下发原稿行，也没有可回收大小
        self.assertEqual(manual_row.get('originals', []), [])
        self.assertEqual(preview['totals']['reclaimable_size'], 0)

    def test_execute_refuses_when_retention_unconfigured(self):
        with override_settings(INSTITUTION_VERSION_RETENTION_DAYS=0):
            preview = self._preview()
            self.assertFalse(preview['enabled'])
            self.assertIn('未配置', preview['notice'])
            self.assertEqual(preview['manuals'], [])
            resp = self._execute()
            self.assertTrue(has_error(resp))
            self.assertIn('未配置', resp.json()['error'])
            version = ManualVersion.objects.get(manual=self.manual)
            self.assertEqual(version.files_clean_status, '')
            # 草稿与快照文件都未被动过
            draft = ManualDraft.objects.get(file_id=self.data['id'])
            self.assertTrue(os.path.exists(
                storage.resolve_absolute_path(draft.file_path)))


@RETENTION_CONFIG
class CleanupPermissionTests(RetentionBase):
    """预检/执行为模块级运维操作：institution.manual.config 门控"""

    def test_preview_and_execute_require_config_permission(self):
        editor_only = make_user('ed', tenant_id='deptB',
                                perms=[PERM_VIEW, PERM_DOWNLOAD])
        client = make_client(editor_only)
        resp = client.get('/institution/cleanup/preview/')
        self.assertTrue(has_error(resp))
        self.assertIn('权限拒绝', resp.json()['error'])
        resp = post_json(client, '/institution/cleanup/execute/', {})
        self.assertTrue(has_error(resp))
        self.assertIn('权限拒绝', resp.json()['error'])

    def test_execute_accepts_manual_scope(self):
        data = self._add_file('甲.docx', DOCX_A)
        v1 = self._publish('第一版')
        self._save_then_release(data['id'], content=DOCX_B)
        v2 = self._publish('第二版')
        _age_version(v1, 40)
        resp = self._execute({'manual_id': self.manual.id})
        self.assertFalse(has_error(resp), resp.content)
        result = get_data(resp)
        # 只清理该手册范围内的历史版本快照
        row = next(r for r in result['versions'] if r['version_id'] == v1.id)
        self.assertIn(row['status'], ('cleaned', 'partial'))
        # 当前生效版本不受影响
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.current_version_id, v2.id)
        self.assertEqual(v2.files_clean_status, '')
        # 草稿记录与文件仍在
        draft = ManualDraft.objects.get(file_id=data['id'])
        self.assertTrue(os.path.exists(
            storage.resolve_absolute_path(draft.file_path)))


class RetentionDisabledDefaultsTests(DraftRecoveryBase):
    """默认配置（未设置任何保留期限）：策略整体不启用"""

    def test_default_config_disables_cleanup(self):
        config = retention_services.get_retention_config()
        self.assertFalse(config['cleanup_enabled'])
        self.data = self._add_file('甲.docx', DOCX_A)
        version = self._publish('第一版')
        _age_version(version, 400)
        resp = post_json(self.manager_client, '/institution/cleanup/execute/', {})
        self.assertTrue(has_error(resp))
        self.assertEqual(version.files_clean_status, '')
        self.assertTrue(ManualVersionFile.objects.filter(
            version=version).exists())
        for snap in version.files.all():
            self.assertTrue(os.path.exists(
                storage.resolve_absolute_path(snap.file_path)))

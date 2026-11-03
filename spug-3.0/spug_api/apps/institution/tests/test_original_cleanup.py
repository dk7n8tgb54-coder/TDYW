# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""原稿体系存量数据清理的真实行为测试（apps.institution.original_cleanup）

覆盖（真实函数 + 真实文件系统 + 真实隔离数据库）：
- 旧表存在：逐条「路径校验 -> 删物理文件 -> 删记录」；文件缺失仍算完成；
  删除失败/路径非法保留记录并计入 failures，success=False。
- 旧表不存在：只扫描 originals/ 根目录残余文件与空目录，不碰数据库。
- 只操作 originals/ 根：草稿、发布快照的记录与物理文件（字节）不变，
  ManualDraft/ManualVersion/ManualVersionFile 行数与 file_path 不变。
- 路径校验：拒绝绝对路径、.. 穿越、drafts/versions 路径、realpath 逃逸。
- 幂等：重复执行 deleted_files/deleted_records 归零，不遗留孤儿文件。
- 管理命令 purge_institution_originals：--dry-run 只读、--manual-id 限范围、
  失败时非 0 退出并打印逐项失败报告。
"""
import io
import json
import os
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TransactionTestCase

from apps.institution import original_cleanup, storage
from apps.institution.models import (Manual, ManualDraft, ManualFile,
                                     ManualVersion, ManualVersionFile)
from apps.institution.tests.base import make_user, setup_test_env

LEGACY_TABLE = 'tdyw_institution_original'


class OriginalCleanupBase(TransactionTestCase):
    """临时存储根 + 两本手册 + 草稿/版本/快照物理文件与行级夹具"""

    def setUp(self):
        setup_test_env()
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(storage, 'get_institution_storage_base',
                               return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._drop_legacy_table)
        self.operator = make_user('purge-op', tenant_id='deptA')
        self.manual = self._make_manual('清理手册甲', 'CL-001')
        self.other_manual = self._make_manual('清理手册乙', 'CL-002')
        self.media = {
            self.manual.id: self._seed_media(self.manual, b'draft-A', b'version-A'),
            self.other_manual.id: self._seed_media(
                self.other_manual, b'draft-B', b'version-B'),
        }

    def _make_manual(self, name, code):
        return Manual.objects.create(
            name=name, code=code, org_type=Manual.OWNER_SECTION,
            org_name='甲科室', owner=self.operator, tenant_id='deptA')

    def _write(self, subdir, manual_id, name, content):
        rel = f'{subdir}/manual_{manual_id}/202610/{name}'
        abs_path = os.path.join(self._tmp.name, *rel.split('/'))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'wb') as f:
            f.write(content)
        return rel, abs_path

    def _seed_media(self, manual, draft_content, version_content):
        """为手册建立一条草稿、一条发布版本与一条快照（真实物理文件）"""
        file_entry = ManualFile.objects.create(
            manual=manual, display_name='正文.docx', sort_order=0,
            owner=self.operator, owner_name=self.operator.username)
        draft_rel, draft_abs = self._write(
            'drafts', manual.id, 'draft.docx', draft_content)
        draft = ManualDraft.objects.create(
            manual=manual, file=file_entry, file_path=draft_rel,
            original_name='正文.docx', file_size=len(draft_content),
            file_hash=storage.compute_file_hash(draft_abs), revision=2)
        version_rel, version_abs = self._write(
            'versions', manual.id, 'version.docx', version_content)
        version = ManualVersion.objects.create(
            manual=manual, version_no=1, file_path=version_rel,
            original_name='正文.docx', file_size=len(version_content),
            file_hash=storage.compute_file_hash(version_abs),
            change_note='首版', published_by=self.operator)
        snapshot = ManualVersionFile.objects.create(
            version=version, manual_file=file_entry, display_name='正文.docx',
            sort_order=0, file_path=version_rel,
            file_size=len(version_content),
            file_hash=storage.compute_file_hash(version_abs))
        return {
            'file_id': file_entry.id,
            'draft_id': draft.id,
            'version_id': version.id,
            'snapshot_id': snapshot.id,
            'draft_path': draft_rel,
            'version_path': version_rel,
            'draft_bytes': draft_content,
            'version_bytes': version_content,
            'files': {
                'draft': draft_abs,
                'version': version_abs,
            },
        }

    def _seed_original(self, manual_id, name='orig.docx', content=b'original-A'):
        rel = f'originals/manual_{manual_id}/202610/{name}'
        abs_path = os.path.join(self._tmp.name, *rel.split('/'))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'wb') as f:
            f.write(content)
        return rel, abs_path

    def _create_legacy_table(self):
        with connection.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS {LEGACY_TABLE}')
            # 只建本清理读取的三列（真实旧表另有列，清理只用这三列）
            cur.execute(
                f'CREATE TABLE {LEGACY_TABLE} ('
                'id BIGINT AUTO_INCREMENT PRIMARY KEY, '
                'manual_id BIGINT NOT NULL, '
                'file_path VARCHAR(500) NOT NULL)')

    def _drop_legacy_table(self):
        with connection.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS {LEGACY_TABLE}')

    def _insert_legacy_record(self, manual_id, file_path):
        with connection.cursor() as cur:
            cur.execute(
                f'INSERT INTO {LEGACY_TABLE} (manual_id, file_path) VALUES (%s, %s)',
                [manual_id, file_path])
            return cur.lastrowid

    def _legacy_record_count(self, manual_id=None):
        with connection.cursor() as cur:
            if manual_id is None:
                cur.execute(f'SELECT COUNT(*) FROM {LEGACY_TABLE}')
            else:
                cur.execute(
                    f'SELECT COUNT(*) FROM {LEGACY_TABLE} WHERE manual_id = %s',
                    [manual_id])
            return cur.fetchone()[0]

    def _legacy_table_exists(self):
        return LEGACY_TABLE in connection.introspection.table_names()

    def _originals_files(self):
        root = original_cleanup.originals_root()
        files = []
        for dirpath, _, names in os.walk(root):
            for name in names:
                files.append(os.path.join(dirpath, name))
        return files

    def _assert_media_intact(self, manual=None):
        """草稿/发布快照记录与物理文件未被清理命令触碰"""
        manual = manual or self.manual
        media = self.media[manual.id]
        draft = ManualDraft.objects.get(pk=media['draft_id'])
        version = ManualVersion.objects.get(pk=media['version_id'])
        snapshot = ManualVersionFile.objects.get(pk=media['snapshot_id'])
        self.assertEqual(draft.file_path, media['draft_path'])
        self.assertEqual(version.file_path, media['version_path'])
        self.assertEqual(snapshot.file_path, media['version_path'])
        with open(media['files']['draft'], 'rb') as f:
            self.assertEqual(f.read(), media['draft_bytes'])
        with open(media['files']['version'], 'rb') as f:
            self.assertEqual(f.read(), media['version_bytes'])
        self.assertEqual(snapshot.file_hash, version.file_hash)
        self.assertEqual(ManualDraft.objects.count(), 2)
        self.assertEqual(ManualVersion.objects.count(), 2)
        self.assertEqual(ManualVersionFile.objects.count(), 2)

    def _call_command(self, *args):
        buf = io.StringIO()
        call_command('purge_institution_originals', *args, stdout=buf)
        return json.loads(buf.getvalue())


class ResolveOriginalPathTests(OriginalCleanupBase):
    """路径安全校验（直接调用清理模块的解析入口）"""

    def test_accepts_originals_manual_structure(self):
        abs_path = original_cleanup.resolve_original_path(
            'originals/manual_1/202610/a.docx')
        self.assertTrue(abs_path.startswith(
            os.path.abspath(original_cleanup.originals_root()) + os.sep))
        self.assertTrue(abs_path.endswith(os.path.join('202610', 'a.docx')))

    def test_rejects_absolute_traversal_and_foreign_subdirs(self):
        for rel in ('', '/tmp/a.docx', '../outside/a.docx',
                    'drafts/manual_1/202610/a.docx',
                    'versions/manual_1/202610/a.docx',
                    'originals/../drafts/manual_1/a.docx',
                    'originals/manualx/202610/a.docx'):
            with self.assertRaises(ValueError):
                original_cleanup.resolve_original_path(rel)

    def test_rejects_symlink_escape(self):
        outside_dir = os.path.join(self._tmp.name, 'outside')
        os.makedirs(outside_dir, exist_ok=True)
        outside_file = os.path.join(outside_dir, 'secret.docx')
        with open(outside_file, 'wb') as f:
            f.write(b'secret')
        link_dir = os.path.join(
            original_cleanup.originals_root(), 'manual_1', '202610')
        os.makedirs(link_dir, exist_ok=True)
        link_path = os.path.join(link_dir, 'a.docx')
        os.symlink(outside_file, link_path)
        with self.assertRaises(ValueError):
            original_cleanup.resolve_original_path(
                'originals/manual_1/202610/a.docx')


class LegacyTableCleanupTests(OriginalCleanupBase):
    """旧表存在：逐条清理记录与物理文件"""

    def setUp(self):
        super().setUp()
        self._create_legacy_table()

    def test_deletes_files_and_records_and_keeps_media_intact(self):
        rel_a, abs_a = self._seed_original(self.manual.id, 'a.docx', b'orig-A')
        rel_b, abs_b = self._seed_original(self.manual.id, 'b.docx', b'orig-B')
        self._insert_legacy_record(self.manual.id, rel_a)
        self._insert_legacy_record(self.manual.id, rel_b)
        report = original_cleanup.cleanup_originals()
        self.assertEqual(report['table_state'], 'present')
        self.assertEqual(report['scanned_records'], 2)
        self.assertEqual(report['scanned_files'], 2)
        self.assertEqual(report['deleted_files'], 2)
        self.assertEqual(report['deleted_records'], 2)
        self.assertEqual(report['missing_files'], 0)
        self.assertEqual(report['failures'], [])
        self.assertTrue(report['success'])
        self.assertFalse(os.path.exists(abs_a))
        self.assertFalse(os.path.exists(abs_b))
        self.assertEqual(self._originals_files(), [])
        self.assertEqual(self._legacy_record_count(), 0)
        # 当前草稿与发布快照：行数、路径、哈希与物理字节全部不变
        self._assert_media_intact()
        self._assert_media_intact(self.other_manual)

    def test_idempotent_second_run(self):
        rel, abs_path = self._seed_original(self.manual.id)
        self._insert_legacy_record(self.manual.id, rel)
        original_cleanup.cleanup_originals()
        report = original_cleanup.cleanup_originals()
        self.assertEqual(report['table_state'], 'present')
        self.assertEqual(report['scanned_records'], 0)
        self.assertEqual(report['scanned_files'], 0)
        self.assertEqual(report['deleted_files'], 0)
        self.assertEqual(report['deleted_records'], 0)
        self.assertTrue(report['success'])
        self.assertEqual(self._legacy_record_count(), 0)
        self.assertEqual(self._originals_files(), [])

    def test_manual_id_scope_filters_records_and_scan(self):
        rel_a, abs_a = self._seed_original(self.manual.id, 'a.docx', b'orig-A')
        rel_b, abs_b = self._seed_original(
            self.other_manual.id, 'b.docx', b'orig-B')
        self._insert_legacy_record(self.manual.id, rel_a)
        self._insert_legacy_record(self.other_manual.id, rel_b)
        # 另一本手册还有一条孤儿文件（无记录）
        _, orphan_b = self._seed_original(
            self.other_manual.id, 'orphan.docx', b'orphan-B')
        report = original_cleanup.cleanup_originals(
            manual_id=self.manual.id)
        self.assertEqual(report['scanned_records'], 1)
        self.assertEqual(report['deleted_files'], 1)
        self.assertEqual(report['deleted_records'], 1)
        self.assertEqual(report['failures'], [])
        self.assertTrue(report['success'])
        self.assertFalse(os.path.exists(abs_a))
        # 另一本手册的记录与文件（含孤儿）不在本次范围
        self.assertTrue(os.path.exists(abs_b))
        self.assertTrue(os.path.exists(orphan_b))
        self.assertEqual(self._legacy_record_count(self.other_manual.id), 1)
        self._assert_media_intact()
        self._assert_media_intact(self.other_manual)

    def test_missing_physical_file_still_deletes_record(self):
        rel = f'originals/manual_{self.manual.id}/202610/missing.docx'
        self._insert_legacy_record(self.manual.id, rel)
        report = original_cleanup.cleanup_originals()
        self.assertEqual(report['scanned_records'], 1)
        self.assertEqual(report['missing_files'], 1)
        self.assertEqual(report['deleted_files'], 0)
        self.assertEqual(report['deleted_records'], 1)
        self.assertTrue(report['success'])
        self.assertEqual(self._legacy_record_count(), 0)

    def test_invalid_paths_rejected_without_touching_media(self):
        # 记录路径指向真实草稿文件与穿越路径：必须拒绝且不删除任何媒体
        draft_rel = self.media[self.manual.id]['draft_path']
        self._insert_legacy_record(self.manual.id, draft_rel)
        self._insert_legacy_record(self.manual.id, '../outside/a.docx')
        self._insert_legacy_record(self.manual.id, '/tmp/a.docx')
        report = original_cleanup.cleanup_originals()
        self.assertFalse(report['success'])
        self.assertEqual(report['deleted_files'], 0)
        self.assertEqual(report['deleted_records'], 0)
        self.assertEqual(self._legacy_record_count(), 3)
        self.assertGreaterEqual(len(report['failures']), 3)
        for item in report['failures']:
            self.assertIn('path', item)
            self.assertIn('error', item)
        self._assert_media_intact()

    def test_deletion_failure_keeps_record_and_reports(self):
        rel, abs_path = self._seed_original(self.manual.id)
        self._insert_legacy_record(self.manual.id, rel)
        with patch.object(original_cleanup.os, 'remove',
                          side_effect=PermissionError('denied')):
            report = original_cleanup.cleanup_originals()
        self.assertFalse(report['success'])
        self.assertEqual(report['deleted_files'], 0)
        self.assertEqual(report['deleted_records'], 0)
        self.assertEqual(len(report['failures']), 1)
        self.assertIn('denied', report['failures'][0]['error'])
        self.assertTrue(os.path.exists(abs_path))
        self.assertEqual(self._legacy_record_count(), 1)

    def test_failure_makes_command_exit_nonzero(self):
        rel, abs_path = self._seed_original(self.manual.id, 'keep.docx')
        self._insert_legacy_record(self.manual.id, rel)
        with patch.object(original_cleanup.os, 'remove',
                          side_effect=PermissionError('device busy')):
            with self.assertRaises(CommandError) as ctx:
                buf = io.StringIO()
                call_command('purge_institution_originals', stdout=buf)
        self.assertIn('失败', str(ctx.exception))
        self.assertIn('keep.docx', str(ctx.exception))
        self.assertTrue(os.path.exists(abs_path))
        self.assertEqual(self._legacy_record_count(), 1)

    def test_command_success_outputs_json_report(self):
        rel, _ = self._seed_original(self.manual.id)
        self._insert_legacy_record(self.manual.id, rel)
        report = self._call_command()
        self.assertTrue(report['success'])
        self.assertEqual(report['deleted_records'], 1)
        self.assertEqual(report['table_state'], 'present')
        self.assertEqual(self._legacy_record_count(), 0)

    def test_dry_run_read_only(self):
        rel, abs_path = self._seed_original(self.manual.id, 'a.docx', b'orig')
        self._insert_legacy_record(self.manual.id, rel)
        report = original_cleanup.cleanup_originals(dry_run=True)
        self.assertTrue(report['dry_run'])
        self.assertEqual(report['deleted_files'], 0)
        self.assertEqual(report['deleted_records'], 0)
        self.assertTrue(os.path.exists(abs_path))
        self.assertEqual(self._legacy_record_count(), 1)
        self.assertEqual(len(report['candidates']), 1)
        self.assertIn(rel, report['candidates'][0].replace(os.sep, '/'))
        # 命令 --dry-run 同样只读
        self._call_command('--dry-run')
        self.assertTrue(os.path.exists(abs_path))
        self.assertEqual(self._legacy_record_count(), 1)
        # 再次真实执行才删除
        report = original_cleanup.cleanup_originals()
        self.assertEqual(report['deleted_records'], 1)

    def test_command_manual_id_scope(self):
        rel_a, abs_a = self._seed_original(self.manual.id, 'a.docx')
        rel_b, abs_b = self._seed_original(
            self.other_manual.id, 'b.docx')
        self._insert_legacy_record(self.manual.id, rel_a)
        self._insert_legacy_record(self.other_manual.id, rel_b)
        report = self._call_command(
            '--manual-id', str(self.manual.id))
        self.assertTrue(report['success'])
        self.assertFalse(os.path.exists(abs_a))
        self.assertTrue(os.path.exists(abs_b))
        self.assertEqual(self._legacy_record_count(self.other_manual.id), 1)

    def test_command_rejects_non_positive_manual_id(self):
        with self.assertRaises(CommandError):
            self._call_command('--manual-id', '0')


class TableAbsentCleanupTests(OriginalCleanupBase):
    """旧表不存在（迁移后）：只扫描 originals/ 目录"""

    def test_scans_directory_only_without_db_changes(self):
        rel_a, abs_a = self._seed_original(self.manual.id, 'a.docx')
        rel_b, abs_b = self._seed_original(
            self.other_manual.id, 'b.docx')
        self.assertFalse(self._legacy_table_exists())
        before_drafts = ManualDraft.objects.count()
        report = original_cleanup.cleanup_originals()
        self.assertEqual(report['table_state'], 'absent')
        self.assertEqual(report['scanned_records'], 0)
        self.assertEqual(report['scanned_files'], 2)
        self.assertEqual(report['deleted_files'], 2)
        self.assertEqual(report['deleted_records'], 0)
        self.assertEqual(report['failures'], [])
        self.assertTrue(report['success'])
        self.assertFalse(os.path.exists(abs_a))
        self.assertFalse(os.path.exists(abs_b))
        self.assertEqual(self._originals_files(), [])
        # 空目录一起清理，但 originals 根保留
        for manual_id in (self.manual.id, self.other_manual.id):
            self.assertFalse(os.path.isdir(os.path.join(
                original_cleanup.originals_root(), f'manual_{manual_id}')))
        self.assertTrue(os.path.isdir(original_cleanup.originals_root()))
        self.assertEqual(ManualDraft.objects.count(), before_drafts)
        self._assert_media_intact()
        self._assert_media_intact(self.other_manual)
        # 幂等：第二次扫描无文件
        report = original_cleanup.cleanup_originals()
        self.assertEqual(report['scanned_files'], 0)
        self.assertEqual(report['deleted_files'], 0)

    def test_only_originals_root_touched(self):
        rel, abs_path = self._seed_original(self.manual.id)
        outside = os.path.join(self._tmp.name, 'other', 'keep.txt')
        os.makedirs(os.path.dirname(outside), exist_ok=True)
        with open(outside, 'wb') as f:
            f.write(b'keep')
        stray = os.path.join(self._tmp.name, 'stray.txt')
        with open(stray, 'wb') as f:
            f.write(b'stray')
        report = original_cleanup.cleanup_originals()
        self.assertTrue(report['success'])
        self.assertFalse(os.path.exists(abs_path))
        self.assertTrue(os.path.exists(outside))
        self.assertTrue(os.path.exists(stray))
        self._assert_media_intact()

    def test_dry_run_lists_candidates_without_delete(self):
        rel_a, abs_a = self._seed_original(self.manual.id, 'a.docx')
        rel_b, abs_b = self._seed_original(
            self.other_manual.id, 'b.docx')
        report = original_cleanup.cleanup_originals(dry_run=True)
        self.assertTrue(report['dry_run'])
        self.assertEqual(report['scanned_files'], 2)
        self.assertEqual(report['deleted_files'], 0)
        self.assertEqual(len(report['candidates']), 2)
        self.assertTrue(os.path.exists(abs_a))
        self.assertTrue(os.path.exists(abs_b))
        reported = {c.replace(os.sep, '/') for c in report['candidates']}
        self.assertEqual(reported, {rel_a, rel_b})
        # 命令 --dry-run 输出 JSON 且不删除
        parsed = self._call_command('--dry-run')
        self.assertTrue(parsed['dry_run'])
        self.assertTrue(os.path.exists(abs_a))

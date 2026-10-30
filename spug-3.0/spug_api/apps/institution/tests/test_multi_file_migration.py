# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""存量单文件数据 -> 多文件结构迁移验证（migration_validation）

真实执行迁移链：先回退 institution 至 0002（多文件结构之前），
用原始 SQL 按旧表结构播种存量形态数据（单主草稿 + 每版一份文件 +
多条候选原稿 + 活跃编辑会话），再前向迁移到最新，逐项核对：

- 每个制度恰好生成一个稳定"主文件"条目；多条 ManualOriginal 只映射
  到该主文件，不据原稿数量推断多份正式文件。
- 主文件显示名：草稿名 > 最新版本名 > 最早原稿名 > 手册名.docx；
  系统生成名（callback_/oo_cb_ 前缀）不透出。
- 历史 ManualVersion 每版映射一条快照，路径/大小/SHA256 与旧列一致。
- 草稿/会话/原稿全部绑定主文件；活跃会话整体失效且 current_doc_key
  清空（document.key 协议变更，新旧不复用）。

回滚边界（设计 §9.4）：本迁移可安全回退的前提是尚未产生多文件写入；
回退只清理回填派生数据（文件条目/快照/file 外键），不动任何旧记录。
"""
import uuid
from datetime import timedelta

from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from apps.account.models import User
from apps.institution.models import (Manual, ManualDraft, ManualEditSession,
                                     ManualFile, ManualOriginal,
                                     ManualVersion, ManualVersionFile)
from apps.institution.tests.base import make_user

NOW = timezone.now()


def _sql_insert(table, columns, values):
    with connection.cursor() as cur:
        placeholders = ', '.join(['%s'] * len(values))
        col_list = ', '.join(columns)
        cur.execute(
            f'INSERT INTO {table} ({col_list}) VALUES ({placeholders})',
            values)
        return cur.lastrowid


class MultiFileMigrationTests(TransactionTestCase):
    """0002 存量形态 -> 0003 多文件回填的端到端迁移验证"""

    def setUp(self):
        # 回退 institution 至 0002：新表删除、file 外键列移除
        call_command('migrate', 'institution', '0002',
                     verbosity=0, interactive=False)

    def tearDown(self):
        # 恢复到最新迁移状态，避免影响其他测试
        call_command('migrate', 'institution',
                     verbosity=0, interactive=False)

    def _seed_legacy_data(self):
        """按 0002 表结构播种存量形态数据（原始 SQL，绕过新模型）"""
        operator = make_user('legacy-pub', tenant_id='deptA')
        operator2 = make_user('legacy-editor', tenant_id='deptB')

        def seed_manual(name, code):
            return _sql_insert(
                'tdyw_institution_manual',
                ['tenant_id', 'name', 'code', 'owner_type', 'owner_name',
                 'status', 'editor_can_view_published', 'password_hash',
                 'password_fail_count', 'created_at', 'updated_at'],
                ['deptA', name, code, 'department', '某部门', 'active', True,
                 '', 0, NOW, NOW])

        # 制度 A：单主草稿（可读名）+ 两个版本 + 两条候选原稿 + 活跃会话
        manual_a = seed_manual('部门管理手册', 'BM-100')
        draft_a = _sql_insert(
            'tdyw_institution_draft',
            ['tenant_id', 'manual_id', 'file_path', 'original_name',
             'file_size', 'file_hash', 'revision', 'created_at'],
            ['deptA', manual_a, 'drafts/manual_a/202610/draft_a.docx',
             '管理手册正文.docx', 1024, 'a' * 64, 7, NOW])
        version_a1 = _sql_insert(
            'tdyw_institution_version',
            ['tenant_id', 'manual_id', 'version_no', 'file_path',
             'original_name', 'file_size', 'file_hash', 'change_note',
             'published_at', 'is_effective', 'published_by_id'],
            ['deptA', manual_a, 1, 'versions/manual_a/202610/v1.docx',
             '管理手册正文.docx', 1000, '1' * 64, '首版', NOW, False,
             operator.id])
        version_a2 = _sql_insert(
            'tdyw_institution_version',
            ['tenant_id', 'manual_id', 'version_no', 'file_path',
             'original_name', 'file_size', 'file_hash', 'change_note',
             'published_at', 'is_effective', 'published_by_id'],
            ['deptA', manual_a, 2, 'versions/manual_a/202610/v2.docx',
             '管理手册正文.docx', 1001, '2' * 64, '修订版', NOW, True,
             operator.id])
        orig_a1 = _sql_insert(
            'tdyw_institution_original',
            ['tenant_id', 'manual_id', 'file_path', 'original_name', 'ext',
             'file_size', 'file_hash', 'uploaded_at', 'uploaded_by_id'],
            ['deptA', manual_a, 'originals/manual_a/202610/o1.docx',
             '候选原稿一.docx', '.docx', 900, 'o1' + '0' * 62, NOW,
             operator.id])
        orig_a2 = _sql_insert(
            'tdyw_institution_original',
            ['tenant_id', 'manual_id', 'file_path', 'original_name', 'ext',
             'file_size', 'file_hash', 'uploaded_at', 'uploaded_by_id'],
            ['deptA', manual_a, 'originals/manual_a/202610/o2.docx',
             '候选原稿二.doc', '.doc', 800, 'o2' + '0' * 62, NOW, operator.id])
        _sql_insert(
            'tdyw_institution_edit_session',
            ['tenant_id', 'manual_id', 'user_id', 'session_key',
             'revision_at_start', 'started_at', 'expires_at', 'revoked_at',
             'revoked_reason', 'current_doc_key'],
            ['deptA', manual_a, operator2.id, uuid.uuid4().hex, 7, NOW,
             NOW + timedelta(hours=2), None, '', 'oo-1-r7-deadbeef'])

        # 制度 B：无草稿，最新版本名是系统生成名（必须治愈为手册名）
        manual_b = seed_manual('应急手册', 'YJ-100')
        _sql_insert(
            'tdyw_institution_version',
            ['tenant_id', 'manual_id', 'version_no', 'file_path',
             'original_name', 'file_size', 'file_hash', 'change_note',
             'published_at', 'is_effective', 'published_by_id'],
            ['deptA', manual_b, 1, 'versions/manual_b/202610/v1.docx',
             'callback_1bb6e2b70ca4.docx', 500, 'b' * 64, '回调名版本', NOW,
             True, operator.id])

        # 制度 C：无草稿无版本，只有一条原稿（显示名回退到原稿名）
        manual_c = seed_manual('操作手册', 'CZ-100')
        _sql_insert(
            'tdyw_institution_original',
            ['tenant_id', 'manual_id', 'file_path', 'original_name', 'ext',
             'file_size', 'file_hash', 'uploaded_at', 'uploaded_by_id'],
            ['deptA', manual_c, 'originals/manual_c/202610/o1.docx',
             '唯一线索.docx', '.docx', 300, 'c' * 64, NOW, operator.id])

        # 制度 D：三无（无草稿/版本/原稿）——仅手册名兜底
        manual_d = seed_manual('空白手册', 'KB-100')

        return {
            'manuals': [manual_a, manual_b, manual_c, manual_d],
            'draft': draft_a, 'versions': [version_a1, version_a2],
            'originals': [orig_a1, orig_a2], 'users': [operator, operator2],
        }

    def test_forward_migration_backfills_and_verifies(self):
        seeded = self._seed_legacy_data()
        # 前向迁移：执行 0003 回填 + fail-closed 校验
        call_command('migrate', 'institution', verbosity=0, interactive=False)

        manuals = {m.id: m for m in Manual.objects.all()}
        self.assertEqual(len(manuals), 4)
        # 每个制度恰好一个主文件条目；存量不据多条原稿推断多份正式文件
        files = {f.manual_id: f for f in ManualFile.objects.all()}
        self.assertEqual(len(files), 4)

        # A：主文件显示名取草稿名；草稿/原稿/会话全部挂到主文件
        manual_a_id = seeded['manuals'][0]
        main_a = files[manual_a_id]
        self.assertEqual(main_a.display_name, '管理手册正文.docx')
        self.assertEqual(main_a.sort_order, 0)
        self.assertFalse(main_a.is_removed)
        draft = ManualDraft.objects.get(file=main_a)
        self.assertEqual(draft.revision, 7)
        self.assertEqual(ManualOriginal.objects.filter(file=main_a).count(), 2)
        session = ManualEditSession.objects.get(manual_id=manual_a_id)
        self.assertEqual(session.file_id, main_a.id)
        # 活跃会话被整体失效且旧协议 key 清空
        self.assertIsNotNone(session.revoked_at)
        self.assertIn('失效', session.revoked_reason)
        self.assertEqual(session.current_doc_key, '')

        # 历史 ManualVersion 每版一条快照：路径/大小/哈希原样保留
        for version_id, expected in zip(
                seeded['versions'],
                [('versions/manual_a/202610/v1.docx', 1000, '1' * 64),
                 ('versions/manual_a/202610/v2.docx', 1001, '2' * 64)]):
            version = ManualVersion.objects.get(pk=version_id)
            self.assertEqual(version.files.count(), 1)
            snapshot = version.files.get()
            self.assertEqual(snapshot.manual_file_id, main_a.id)
            self.assertEqual(
                (snapshot.file_path, snapshot.file_size, snapshot.file_hash),
                expected)
            # 旧列未删除（兼容镜像）
            self.assertEqual(version.file_path, expected[0])
            self.assertEqual(version.file_hash, expected[2])

        # B：版本名是系统生成名 -> 主文件名治愈为手册名
        manual_b_id = seeded['manuals'][1]
        self.assertEqual(files[manual_b_id].display_name, '应急手册.docx')
        snapshot_b = ManualVersionFile.objects.get(
            version__manual_id=manual_b_id)
        # 快照保留版本当时名（历史语义不漂移），主文件名独立治愈
        self.assertEqual(snapshot_b.display_name, 'callback_1bb6e2b70ca4.docx')

        # C：无草稿无版本 -> 主文件名取原稿名
        self.assertEqual(
            files[seeded['manuals'][2]].display_name, '唯一线索.docx')

        # D：三无 -> 手册名兜底
        self.assertEqual(
            files[seeded['manuals'][3]].display_name, '空白手册.docx')

        # 迁移后旧接口链路可用：唯一启用文件委托
        manual_a = Manual.objects.get(pk=manual_a_id)
        from apps.institution import services
        file_entry, err = services.get_single_active_file(manual_a)
        self.assertIsNone(err)
        self.assertEqual(file_entry.id, main_a.id)

    def test_reverse_migration_clears_derived_data_only(self):
        """回滚边界：回退只清理回填派生数据，旧记录与旧列保持不动"""
        seeded = self._seed_legacy_data()
        call_command('migrate', 'institution', verbosity=0, interactive=False)
        self.assertEqual(ManualFile.objects.count(), 4)
        # 回退到 0002：文件条目/快照删除，旧表数据仍在
        call_command('migrate', 'institution', '0002',
                     verbosity=0, interactive=False)
        with connection.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM tdyw_institution_manual')
            self.assertEqual(cur.fetchone()[0], 4)
            cur.execute('SELECT COUNT(*) FROM tdyw_institution_version')
            self.assertEqual(cur.fetchone()[0], 3)
            cur.execute('SELECT COUNT(*) FROM tdyw_institution_draft')
            self.assertEqual(cur.fetchone()[0], 1)
            cur.execute('SELECT COUNT(*) FROM tdyw_institution_original')
            self.assertEqual(cur.fetchone()[0], 3)
        # 再次前向迁移可重放（幂等重建派生数据）
        call_command('migrate', 'institution', verbosity=0, interactive=False)
        self.assertEqual(ManualFile.objects.count(), 4)
        self.assertEqual(ManualVersionFile.objects.count(), 3)
        draft = ManualDraft.objects.get(manual_id=seeded['manuals'][0])
        self.assertEqual(draft.revision, 7)

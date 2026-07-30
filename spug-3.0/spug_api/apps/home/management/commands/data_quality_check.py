# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License
"""
数据质量巡检命令

定期检查数据库中的数据完整性问题：
1. 软删除孤儿：子记录指向已软删除的父记录
2. 文件-数据库一致性：DB 有记录但磁盘文件不存在
3. unique_key 一致性：DocumentFolder 的 unique_key 与 is_deleted 状态不匹配
4. 软删除后缀：UpgradeRecord 软删除后 upgrade_no 缺少 __deleted_ 后缀
5. 待清理文件：is_pending_clean=True 的记录卡住
6. 租户隔离：跨租户引用

用法：
    python manage.py data_quality_check
    python manage.py data_quality_check --json
    python manage.py data_quality_check --check soft_delete_orphans
    python manage.py data_quality_check --no-alert
    python manage.py data_quality_check --file-sample 100  # 限制文件检查数量

建议每周运行一次（Celery Beat 或 cron）。
"""
import json
import os
import logging

from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "数据质量巡检：检查软删除孤儿、文件一致性、unique_key、租户隔离等"

    CHECK_NAMES = [
        'soft_delete_orphans',
        'file_db_consistency',
        'unique_key_consistency',
        'deleted_suffix',
        'pending_clean_files',
        'tenant_isolation',
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            '--check', type=str, default='',
            help=f'只运行指定检查项（可选：{", ".join(self.CHECK_NAMES)}）'
        )
        parser.add_argument(
            '--json', action='store_true',
            help='JSON 格式输出'
        )
        parser.add_argument(
            '--no-alert', action='store_true',
            help='不发送告警'
        )
        parser.add_argument(
            '--file-sample', type=int, default=500,
            help='文件一致性检查的最大采样数（默认 500）'
        )

    def handle(self, *args, **options):
        self.check_name = options.get('check', '')
        self.json_output = options.get('json', False)
        self.no_alert = options.get('no_alert', False)
        self.file_sample = options.get('file_sample', 500)

        checks = [
            self.check_soft_delete_orphans,
            self.check_file_db_consistency,
            self.check_unique_key_consistency,
            self.check_deleted_suffix,
            self.check_pending_clean_files,
            self.check_tenant_isolation,
        ]

        results = []
        for check in checks:
            # --check 参数用 CHECK_NAMES 中的名称（不含 check_ 前缀）
            check_key = check.__name__.replace('check_', '', 1)
            if self.check_name and check_key != self.check_name:
                continue
            try:
                result = check()
            except Exception as e:
                logger.error(f'[DataQuality] {check.__name__} failed: {e}', exc_info=True)
                result = {
                    'check': check.__name__,
                    'description': check.__doc__.strip() if check.__doc__ else '',
                    'status': 'error',
                    'error': str(e),
                    'count': 0,
                }
            results.append(result)

        total_problems = sum(r.get('count', 0) for r in results)
        passed = sum(1 for r in results if r['status'] == 'pass')
        failed = sum(1 for r in results if r['status'] == 'fail')

        summary = {
            'checked_at': timezone.now().isoformat(),
            'total_checks': len(results),
            'passed': passed,
            'failed': failed,
            'total_problems': total_problems,
            'results': results,
        }

        if self.json_output:
            self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        else:
            self._print_human_report(summary)

        # 发送告警
        if total_problems > 0 and not self.no_alert:
            self._send_alert(summary)

        return json.dumps(summary, ensure_ascii=False, default=str) if self.json_output else None

    # ============================================
    # 辅助：执行 raw SQL
    # ============================================
    def _query(self, sql, params=None):
        with connection.cursor() as cursor:
            cursor.execute(sql, params or [])
            cols = [desc[0] for desc in cursor.description] if cursor.description else []
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

    # ============================================
    # 检查 1：软删除孤儿
    # 子记录 is_deleted=False，但父记录 is_deleted=True
    # ============================================
    def check_soft_delete_orphans(self):
        """软删除孤儿：子记录指向已软删除的父记录"""
        problems = []

        # DocumentFilePrivate -> DocumentFolderPrivate (FK, on_delete=SET_NULL)
        # 软删除文件夹时，文件的 folder_id 不会变 NULL（SET_NULL 只在物理删除时触发）
        rows = self._query("""
            SELECT f.id, f.name, f.folder_id, f.tenant_id
            FROM tdyw_document_file_private f
            INNER JOIN tdyw_document_folder_private d ON f.folder_id = d.id
            WHERE f.is_deleted = 0 AND d.is_deleted = 1
        """)
        for row in rows:
            problems.append({
                'model': 'DocumentFilePrivate',
                'id': row['id'],
                'name': row['name'],
                'issue': f"folder({row['folder_id']}) is soft-deleted but file is not",
                'tenant_id': row['tenant_id'],
            })

        # DocumentFilePublic -> DocumentFolderPublic
        # 注意：公共空间无 tenant_id 字段
        rows = self._query("""
            SELECT f.id, f.name, f.folder_id
            FROM tdyw_document_file_public f
            INNER JOIN tdyw_document_folder_public d ON f.folder_id = d.id
            WHERE f.is_deleted = 0 AND d.is_deleted = 1
        """)
        for row in rows:
            problems.append({
                'model': 'DocumentFilePublic',
                'id': row['id'],
                'name': row['name'],
                'issue': f"folder({row['folder_id']}) is soft-deleted but file is not",
            })

        # UpgradeRecordStep -> UpgradeRecord (IntegerField, 非 FK)
        # upgrade_id 指向已软删除的 UpgradeRecord
        rows = self._query("""
            SELECT s.id, s.title, s.upgrade_id, s.tenant_id
            FROM tdyw_upgrade_record_steps s
            INNER JOIN tdyw_upgrade_records r ON s.upgrade_id = r.id
            WHERE s.is_deleted = 0 AND r.is_deleted = 1
        """)
        for row in rows:
            problems.append({
                'model': 'UpgradeRecordStep',
                'id': row['id'],
                'name': row['title'],
                'issue': f"upgrade_record({row['upgrade_id']}) is soft-deleted but step is not",
                'tenant_id': row['tenant_id'],
            })

        # RegulationAttachment -> Regulation: Regulation 无 is_deleted（用 status='retired'），
        # FK CASCADE 已在 DB 层处理，不需要软删除孤儿检查

        return self._format_result('soft_delete_orphans', problems, '软删除孤儿：子记录指向已软删除的父记录')

    # ============================================
    # 检查 2：文件-数据库一致性
    # DB 有文件记录但磁盘上文件不存在
    # ============================================
    def check_file_db_consistency(self):
        """文件-数据库一致性：DB 有记录但磁盘文件不存在"""
        problems = []
        checked = 0
        missing = 0

        # 每组：(table, model_name, base_path)
        # base_path=None 表示 file_path 是绝对路径，直接用
        media_root = getattr(settings, 'MEDIA_ROOT', '')
        doc_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')

        file_sources = [
            # (table, model_name, base_path, name_column)
            # base_path=None 表示 file_path 是绝对路径，直接用
            ('tdyw_document_file_private', 'DocumentFilePrivate', None, 'name'),
            ('tdyw_document_file_public', 'DocumentFilePublic', None, 'name'),
            ('tdyw_evidence_attachments', 'EvidenceAttachment', media_root, 'file_name'),
            ('tdyw_regulation_attachment', 'RegulationAttachment', doc_base, 'original_name'),
        ]

        for table, model_name, base_path, name_col in file_sources:
            rows = self._query(f"""
                SELECT id, file_path, {name_col} AS display_name
                FROM {table}
                WHERE is_deleted = 0 AND file_path != ''
                ORDER BY id DESC
                LIMIT %s
            """, [self.file_sample])

            for row in rows:
                checked += 1
                abs_path = os.path.join(base_path, row['file_path']) if base_path else row['file_path']
                if not os.path.exists(abs_path):
                    missing += 1
                    problems.append({
                        'model': model_name,
                        'id': row['id'],
                        'name': row['display_name'],
                        'file_path': abs_path,
                        'issue': 'file not found on disk',
                    })

        return {
            'check': 'file_db_consistency',
            'description': f'文件-数据库一致性（采样 {checked} 条，缺失 {missing} 条）',
            'status': 'pass' if missing == 0 else 'fail',
            'count': missing,
            'checked': checked,
            'details': problems[:50],
            'truncated': len(problems) > 50,
        }

    # ============================================
    # 检查 3：unique_key 一致性
    # DocumentFolder 模型：未删除 -> unique_key 有值；已删除 -> unique_key = NULL
    # 注意：DocumentFile 模型没有 unique_key 字段，不检查
    # ============================================
    def check_unique_key_consistency(self):
        """unique_key 一致性：DocumentFolder 的 unique_key 与 is_deleted 状态不匹配"""
        problems = []

        for table, model_name, has_tenant in [
            ('tdyw_document_folder_private', 'DocumentFolderPrivate', True),
            ('tdyw_document_folder_public', 'DocumentFolderPublic', False),
        ]:
            tenant_col = ', tenant_id' if has_tenant else ''
            # 未删除但 unique_key 为 NULL
            rows = self._query(f"""
                SELECT id, name{tenant_col}
                FROM {table}
                WHERE is_deleted = 0 AND unique_key IS NULL
            """)
            for row in rows:
                entry = {
                    'model': model_name,
                    'id': row['id'],
                    'name': row['name'],
                    'issue': 'is_deleted=False but unique_key is NULL',
                }
                if has_tenant:
                    entry['tenant_id'] = row['tenant_id']
                problems.append(entry)

            # 已删除但 unique_key 不为 NULL
            rows = self._query(f"""
                SELECT id, name, unique_key{tenant_col}
                FROM {table}
                WHERE is_deleted = 1 AND unique_key IS NOT NULL
            """)
            for row in rows:
                entry = {
                    'model': model_name,
                    'id': row['id'],
                    'name': row['name'],
                    'issue': f"is_deleted=True but unique_key is not NULL ({row['unique_key']})",
                }
                if has_tenant:
                    entry['tenant_id'] = row['tenant_id']
                problems.append(entry)

        return self._format_result('unique_key_consistency', problems, 'unique_key 与 is_deleted 状态不匹配')

    # ============================================
    # 检查 4：软删除后缀
    # UpgradeRecord 软删除后 upgrade_no 应有 __deleted_ 后缀
    # ============================================
    def check_deleted_suffix(self):
        """软删除后缀：UpgradeRecord 软删除后 upgrade_no 缺少 __deleted_ 后缀"""
        problems = []

        rows = self._query("""
            SELECT id, upgrade_no, tenant_id
            FROM tdyw_upgrade_records
            WHERE is_deleted = 1
              AND upgrade_no NOT LIKE '%%__deleted_%%'
        """)
        for row in rows:
            problems.append({
                'model': 'UpgradeRecord',
                'id': row['id'],
                'upgrade_no': row['upgrade_no'],
                'issue': 'is_deleted=True but upgrade_no lacks __deleted_ suffix',
                'tenant_id': row['tenant_id'],
            })

        return self._format_result('deleted_suffix', problems, 'UpgradeRecord 软删除后 upgrade_no 缺少 __deleted_ 后缀')

    # ============================================
    # 检查 5：待清理文件
    # is_pending_clean=True 的记录（物理文件删除失败）
    # ============================================
    def check_pending_clean_files(self):
        """待清理文件：is_pending_clean=True（物理文件删除失败）"""
        problems = []

        for table, model_name, has_tenant in [
            ('tdyw_document_file_private', 'DocumentFilePrivate', True),
            ('tdyw_document_file_public', 'DocumentFilePublic', False),
        ]:
            tenant_col = ', tenant_id' if has_tenant else ''
            rows = self._query(f"""
                SELECT id, name, clean_retry_count, last_clean_attempt{tenant_col}
                FROM {table}
                WHERE is_pending_clean = 1
                ORDER BY last_clean_attempt DESC
            """)
            for row in rows:
                entry = {
                    'model': model_name,
                    'id': row['id'],
                    'name': row['name'],
                    'retry_count': row['clean_retry_count'],
                    'last_clean_attempt': row['last_clean_attempt'].isoformat() if row['last_clean_attempt'] else None,
                    'issue': 'is_pending_clean=True (physical file deletion failed)',
                }
                if has_tenant:
                    entry['tenant_id'] = row['tenant_id']
                problems.append(entry)

        return self._format_result('pending_clean_files', problems, 'is_pending_clean=True（物理文件删除失败）')

    # ============================================
    # 检查 6：租户隔离
    # DocumentFilePrivate.tenant_id != folder.tenant_id
    # ============================================
    def check_tenant_isolation(self):
        """租户隔离：DocumentFile 与 Folder 的 tenant_id 不一致"""
        problems = []

        rows = self._query("""
            SELECT f.id, f.name, f.tenant_id AS file_tenant,
                   f.folder_id, d.tenant_id AS folder_tenant
            FROM tdyw_document_file_private f
            INNER JOIN tdyw_document_folder_private d ON f.folder_id = d.id
            WHERE f.is_deleted = 0
              AND f.tenant_id != d.tenant_id
        """)
        for row in rows:
            problems.append({
                'model': 'DocumentFilePrivate',
                'id': row['id'],
                'name': row['name'],
                'issue': f"tenant mismatch: file({row['file_tenant']}) vs folder({row['folder_tenant']})",
                'file_tenant_id': row['file_tenant'],
                'folder_id': row['folder_id'],
                'folder_tenant_id': row['folder_tenant'],
            })

        return self._format_result('tenant_isolation', problems, 'DocumentFile 与 Folder 的 tenant_id 不一致')

    # ============================================
    # 辅助方法
    # ============================================
    def _format_result(self, check_name, problems, description=''):
        return {
            'check': check_name,
            'description': description,
            'status': 'pass' if not problems else 'fail',
            'count': len(problems),
            'details': problems[:50],
            'truncated': len(problems) > 50,
        }

    def _print_human_report(self, summary):
        self.stdout.write(self.style.HTTP_INFO('=' * 60))
        self.stdout.write(self.style.HTTP_INFO('数据质量巡检报告'))
        self.stdout.write(self.style.HTTP_INFO(f'时间: {summary["checked_at"]}'))
        self.stdout.write(self.style.HTTP_INFO(
            f'通过: {summary["passed"]}/{summary["total_checks"]}  问题: {summary["total_problems"]}'
        ))
        self.stdout.write(self.style.HTTP_INFO('=' * 60))

        for r in summary['results']:
            status_str = 'PASS' if r['status'] == 'pass' else 'FAIL'
            style = self.style.SUCCESS if r['status'] == 'pass' else self.style.ERROR
            desc = r.get('description', '')
            count = r.get('count', 0)
            if r['status'] == 'error':
                self.stdout.write(style(f'[ERROR] {r["check"]}: {r.get("error", "")}'))
            else:
                self.stdout.write(style(f'[{status_str}] {r["check"]}: {desc} ({count})'))

            if r['status'] == 'fail' and r.get('details'):
                for d in r['details'][:5]:
                    self.stdout.write(f'    - {d.get("model", "")} id={d.get("id", "")} {d.get("issue", "")}')
                if r.get('truncated'):
                    remaining = r['count'] - len(r['details'])
                    self.stdout.write(f'    ... 还有 {remaining} 条')

        self.stdout.write('-' * 60)
        if summary['total_problems'] == 0 and not any(r['status'] == 'error' for r in summary['results']):
            self.stdout.write(self.style.SUCCESS('All checks passed'))
        elif summary['total_problems'] > 0:
            self.stdout.write(self.style.WARNING(
                f'Found {summary["total_problems"]} problem(s), alert sent'
            ))

    def _send_alert(self, summary):
        try:
            from libs.alert import send_alert
            failed_checks = [r for r in summary['results'] if r['status'] == 'fail']
            message_parts = []
            for r in failed_checks:
                message_parts.append(f"- {r['check']}: {r.get('count', 0)} 问题")
            message = '\n'.join(message_parts)
            send_alert(
                title=f'数据质量巡检发现 {summary["total_problems"]} 个问题',
                message=message or '数据质量巡检发现问题',
                level='warning',
                source='data_quality_check',
            )
        except Exception as e:
            logger.error(f'[DataQuality] send_alert failed: {e}')

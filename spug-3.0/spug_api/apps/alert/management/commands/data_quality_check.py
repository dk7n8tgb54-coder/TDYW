# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License
"""
数据质量巡检命令

定期检查数据库中的数据完整性问题：
1. 软删除孤儿：子记录指向已软删除的父记录
2. 文件-数据库一致性：DB 有记录但磁盘文件不存在（含缩略图）
3. unique_key 一致性：DocumentFolder 的 unique_key 与 is_deleted 状态不匹配
4. 待清理文件：is_pending_clean=True 的记录卡住
5. 科室归属一致性：业务记录与创建人科室不一致
6. 孤儿文件：磁盘上有物理文件但数据库中无对应记录（反向扫描）

注：私有资料库（tdyw_document_file_private / tdyw_document_folder_private）已废弃，
相关表已不存在，巡检不再覆盖；原"文件与文件夹科室隔离"检查随私有表一并移除。

用法：
    python manage.py data_quality_check
    python manage.py data_quality_check --json
    python manage.py data_quality_check --check soft_delete_orphans
    python manage.py data_quality_check --no-alert
    python manage.py data_quality_check --file-sample 100  # 限制文件检查数量（默认不限）

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
        'pending_clean_files',
        'record_tenant_consistency',
        'orphan_disk_files',
    ]

    # 检查执行异常时用于展示的中文检查名（正常路径由各检查函数自己传入 _format_result）
    CHECK_LABELS = {
        'check_soft_delete_orphans': '删除残留检查',
        'check_file_db_consistency': '文件完整性检查',
        'check_unique_key_consistency': '文件夹标识检查',
        'check_pending_clean_files': '待清理文件检查',
        'check_record_tenant_consistency': '科室归属检查',
        'check_orphan_disk_files': '孤儿文件检查',
    }

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
            '--file-sample', type=int, default=0,
            help='文件一致性检查的最大采样数（默认 0 表示不限制）'
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
            self.check_pending_clean_files,
            self.check_record_tenant_consistency,
            self.check_orphan_disk_files,
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
                    'check': self.CHECK_LABELS.get(check.__name__, check.__name__),
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
        """删除残留检查：检查已删除记录下是否仍有子记录"""
        problems = []

        # DocumentFilePrivate / DocumentFilePublic 已移除 is_deleted 字段（回收站废弃）
        # 不再检查软删除孤儿

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
                'model': '升级记录步骤',
                'id': row['id'],
                'name': row['title'],
                'issue': f"所属升级记录(ID:{row['upgrade_id']})已被删除，但此步骤仍存在",
                'tenant_id': row['tenant_id'],
            })

        return self._format_result('删除残留检查', problems, '检查已删除记录下是否仍有子记录')

    # ============================================
    # 检查 2：文件-数据库一致性
    # DB 有文件记录但磁盘上文件不存在
    # ============================================
    def check_file_db_consistency(self):
        """文件-数据库一致性：DB 有记录但磁盘文件不存在（含缩略图）"""
        problems = []
        checked = 0
        missing = 0

        # 每组：(table, model_name, base_path, name_column, has_soft_delete, thumb_column)
        # base_path=None 表示 file_path 是绝对路径，直接用
        # thumb_column=None 表示该表没有缩略图字段（证据附件/法规附件目前不生成缩略图）
        media_root = getattr(settings, 'MEDIA_ROOT', '')
        doc_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')

        file_sources = [
            # (table, model_name, base_path, name_column, has_soft_delete, thumb_column)
            # has_soft_delete=True 表示表有 is_deleted 字段，需过滤
            ('tdyw_document_file_public', '公共资料文件', None, 'name', False, 'thumbnail_path'),
            ('tdyw_evidence_attachments', '证据附件', media_root, 'file_name', True, None),
            ('tdyw_regulation_attachment', '法规附件', doc_base, 'original_name', True, None),
        ]

        for table, model_name, base_path, name_col, has_soft_delete, thumb_col in file_sources:
            where = "WHERE is_deleted = 0 AND file_path != ''" if has_soft_delete else "WHERE file_path != ''"
            # 无缩略图字段的表用空串占位，保证各表返回列一致
            thumb_expr = thumb_col if thumb_col else "''"
            # 默认全量检查：采样会漏掉早期记录（历史教训：缩略图记录 id 偏小，
            # 曾被 ORDER BY id DESC LIMIT 500 整体排除在检查范围外）
            limit_clause = 'LIMIT %s' if self.file_sample > 0 else ''
            limit_params = [self.file_sample] if self.file_sample > 0 else []
            rows = self._query(f"""
                SELECT id, file_path, {name_col} AS display_name, {thumb_expr} AS thumbnail_path
                FROM {table}
                {where}
                ORDER BY id DESC
                {limit_clause}
            """, limit_params)

            for row in rows:
                # --- 主文件 ---
                checked += 1
                abs_path = os.path.join(base_path, row['file_path']) if base_path else row['file_path']
                if not os.path.exists(abs_path):
                    missing += 1
                    problems.append({
                        'model': model_name,
                        'id': row['id'],
                        'name': row['display_name'],
                        'file_path': abs_path,
                        'issue': '磁盘上文件不存在',
                    })

                # --- 缩略图（与主文件同等对待：丢失也是一种文件缺失）---
                thumb_path = row.get('thumbnail_path')
                if not thumb_path:
                    continue
                checked += 1
                thumb_abs = os.path.join(base_path, thumb_path) if base_path else thumb_path
                if not os.path.exists(thumb_abs):
                    missing += 1
                    problems.append({
                        'model': f'{model_name}缩略图',
                        'id': row['id'],
                        'name': row['display_name'],
                        'file_path': thumb_abs,
                        'issue': '磁盘上缩略图不存在',
                    })

        return {
            'check': '文件完整性检查',
            'description': f'数据库有记录但磁盘上文件缺失（检查 {checked} 条，缺失 {missing} 条）',
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
        """文件夹标识检查：文件夹唯一标识不完整（不应为空）"""
        problems = []

        # DocumentFolder 已移除 is_deleted 字段（回收站废弃）
        # unique_key 由 UniqueKeyMixin.save() 自动计算，不应为 NULL
        for table, model_name, has_tenant in [
            ('tdyw_document_folder_public', '公共资料文件夹', False),
        ]:
            tenant_col = ', tenant_id' if has_tenant else ''
            rows = self._query(f"""
                SELECT id, name{tenant_col}
                FROM {table}
                WHERE unique_key IS NULL
            """)
            for row in rows:
                entry = {
                    'model': model_name,
                    'id': row['id'],
                    'name': row['name'],
                    'issue': '唯一标识为空（应由系统自动生成）',
                }
                if has_tenant:
                    entry['tenant_id'] = row['tenant_id']
                problems.append(entry)

        return self._format_result('文件夹标识检查', problems, '文件夹唯一标识不完整（不应为空）')

    # ============================================
    # 检查 4：待清理文件
    # is_pending_clean=True 的记录（物理文件删除失败）
    # ============================================
    def check_pending_clean_files(self):
        """待清理文件检查：删除失败的文件卡住未清理"""
        problems = []

        for table, model_name, has_tenant in [
            ('tdyw_document_file_public', '公共资料文件', False),
        ]:
            tenant_col = ', tenant_id' if has_tenant else ''
            rows = self._query(f"""
                SELECT id, name, clean_retry_count, last_clean_attempt{tenant_col}
                FROM {table}
                WHERE is_pending_clean = 1
                ORDER BY last_clean_attempt DESC
            """)
            for row in rows:
                retry = row['clean_retry_count']
                entry = {
                    'model': model_name,
                    'id': row['id'],
                    'name': row['name'],
                    'retry_count': retry,
                    'last_clean_attempt': row['last_clean_attempt'].isoformat() if row['last_clean_attempt'] else None,
                    'issue': f'文件删除失败，已重试 {retry} 次',
                }
                if has_tenant:
                    entry['tenant_id'] = row['tenant_id']
                problems.append(entry)

        return self._format_result('待清理文件检查', problems, '删除失败的文件卡住未清理')

    # ============================================
    # 检查 5：业务记录科室归属一致性
    # 记录的 tenant_id 与创建人的 tenant_id 不一致
    # ============================================
    def check_record_tenant_consistency(self):
        """科室归属检查：业务记录的科室与创建人所属科室不一致"""
        problems = []

        # (表名, 显示名, 记录名列)
        modules = [
            ('tdyw_fault_records', '故障记录', 'system_name'),
            ('tdyw_run_logs', '运行日志', 'event_title'),
            ('tdyw_interferences', '干扰记录', 'frequency'),
            ('tdyw_upgrade_records', '升级记录', 'title'),
            ('tdyw_duty_records', '值班日志', 'duty_person'),
        ]

        for table, model_name, name_col in modules:
            rows = self._query(f"""
                SELECT r.id, r.{name_col} AS display_name,
                       r.tenant_id AS record_tenant,
                       u.tenant_id AS user_tenant,
                       u.username AS created_by_name
                FROM {table} r
                INNER JOIN users u ON r.created_by_id = u.id
                WHERE r.is_deleted = 0
                  AND r.tenant_id != u.tenant_id
            """)
            for row in rows:
                problems.append({
                    'model': model_name,
                    'id': row['id'],
                    'name': row['display_name'] or f'(ID:{row["id"]})',
                    'issue': (f"记录科室({row['record_tenant']})与创建人"
                              f"({row['created_by_name']})科室({row['user_tenant']})不一致"),
                    'record_tenant_id': row['record_tenant'],
                    'user_tenant_id': row['user_tenant'],
                })

        return self._format_result('科室归属检查', problems, '业务记录的科室与创建人所属科室不一致')

    # ============================================
    # 检查 7：孤儿文件（磁盘 -> DB 反向扫描）
    # 扫描存储目录，找出磁盘上有物理文件但数据库中无对应记录的孤儿文件
    # ============================================
    def check_orphan_disk_files(self):
        """孤儿文件检查：磁盘上有物理文件但数据库中无对应记录"""
        import time

        problems = []
        scanned = 0

        doc_storage = os.path.join(settings.BASE_DIR, 'storage', 'documents')
        media_root = getattr(settings, 'MEDIA_ROOT', '')

        # 跳过最近 1 小时内修改的文件（可能是正在上传的文件）
        cutoff_time = time.time() - 3600

        # --- 1. 扫描 storage/documents/ 目录 ---
        # 收集 DB 中所有已知的文件绝对路径
        known_paths = set()

        # DocumentFilePublic：file_path 与 thumbnail_path 均为绝对路径
        # （私有资料库表 tdyw_document_file_private 已废弃删除，不再扫描）
        # 注意：缩略图不记录在 file_path 中，必须与 thumbnail_path 一并收集，
        # 否则每个缩略图都会被误判成孤儿（2026-08-31 修复：曾产生 27 条误报）
        for table in ('tdyw_document_file_public',):
            rows = self._query(f"""
                SELECT file_path, thumbnail_path
                FROM {table}
                WHERE file_path != ''
                   OR (thumbnail_path IS NOT NULL AND thumbnail_path != '')
            """)
            for row in rows:
                for col in ('file_path', 'thumbnail_path'):
                    if row.get(col):
                        known_paths.add(os.path.normpath(row[col]))

        # RegulationAttachment：file_path 为相对 storage/documents/ 的相对路径
        # 包含软删除记录（文件仍存在磁盘上，只是待清理，不算孤儿）
        reg_rows = self._query(
            "SELECT file_path FROM tdyw_regulation_attachment WHERE file_path != ''"
        )
        for row in reg_rows:
            abs_path = os.path.normpath(os.path.join(doc_storage, row['file_path']))
            known_paths.add(abs_path)

        if os.path.isdir(doc_storage):
            for root, dirs, files in os.walk(doc_storage):
                for fname in files:
                    # 跳过隐藏文件和临时文件
                    if fname.startswith('.') or fname.endswith('.tmp'):
                        continue
                    abs_path = os.path.normpath(os.path.join(root, fname))
                    scanned += 1
                    if abs_path in known_paths:
                        continue
                    # 跳过最近修改的文件（可能正在上传）
                    try:
                        if os.path.getmtime(abs_path) > cutoff_time:
                            continue
                    except OSError:
                        continue
                    # 计算相对路径用于显示
                    rel_path = os.path.relpath(abs_path, doc_storage)
                    # 根据顶层目录区分业务模块
                    top_dir = rel_path.split(os.sep)[0] if os.sep in rel_path else ''
                    if top_dir == 'party_building_documents':
                        model_label = '党建工作文件'
                    else:
                        model_label = '资料库/法规文件'
                    problems.append({
                        'model': model_label,
                        'file_path': abs_path,
                        'rel_path': rel_path,
                        'issue': '磁盘文件在数据库中无对应记录',
                    })

        # --- 2. 扫描 MEDIA_ROOT 目录（证据附件）---
        # 包含软删除记录（文件仍存在磁盘上，只是待清理，不算孤儿）
        evidence_known = set()
        evi_rows = self._query(
            "SELECT file_path FROM tdyw_evidence_attachments WHERE file_path != ''"
        )
        for row in evi_rows:
            abs_path = os.path.normpath(os.path.join(media_root, row['file_path']))
            evidence_known.add(abs_path)

        if media_root and os.path.isdir(media_root):
            for root, dirs, files in os.walk(media_root):
                for fname in files:
                    if fname.startswith('.') or fname.endswith('.tmp'):
                        continue
                    abs_path = os.path.normpath(os.path.join(root, fname))
                    scanned += 1
                    if abs_path in evidence_known:
                        continue
                    try:
                        if os.path.getmtime(abs_path) > cutoff_time:
                            continue
                    except OSError:
                        continue
                    rel_path = os.path.relpath(abs_path, media_root)
                    # 根据顶层目录区分业务模块
                    top_dir = rel_path.split(os.sep)[0] if os.sep in rel_path else ''
                    model_label = self._media_dir_label(top_dir)
                    problems.append({
                        'model': model_label,
                        'file_path': abs_path,
                        'rel_path': rel_path,
                        'issue': '磁盘文件在数据库中无对应记录',
                    })

        return {
            'check': '孤儿文件检查',
            'description': f'磁盘上有物理文件但数据库中无记录（扫描 {scanned} 个文件，发现 {len(problems)} 个孤儿）',
            'status': 'pass' if not problems else 'fail',
            'count': len(problems),
            'scanned': scanned,
            'details': problems[:50],
            'truncated': len(problems) > 50,
        }

    # ============================================
    # 辅助方法
    # ============================================
    # MEDIA_ROOT 子目录 -> 业务模块名称映射
    _MEDIA_DIR_LABELS = {
        'radio_license': '无线电台执照',
        'contract_agreement': '合同协议',
        'department_duty_log': '部门值班日志',
        'fault': '故障管理',
        'interference': '干扰管理',
        'upgrade': '系统升级',
        'device': '设备台账',
        'account_signature': '电子签名',
        'announcement': '公告附件',
        'regulation': '规章管理',
    }

    def _media_dir_label(self, top_dir):
        """将 MEDIA_ROOT 下的顶层目录名映射为业务模块名称"""
        return self._MEDIA_DIR_LABELS.get(top_dir, '证据附件')

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
                    if 'id' in d:
                        self.stdout.write(f'    - {d.get("model", "")} id={d["id"]} {d.get("issue", "")}')
                    else:
                        self.stdout.write(f'    - {d.get("model", "")} {d.get("rel_path", d.get("file_path", ""))} {d.get("issue", "")}')
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

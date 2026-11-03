# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""清理已下线原稿体系的物理文件与数据库记录（幂等，可重复执行）

用法：
    python manage.py purge_institution_originals --dry-run
    python manage.py purge_institution_originals
    python manage.py purge_institution_originals --manual-id 12

行为（见 apps/institution/original_cleanup.py）：
- 旧表 tdyw_institution_original 仍存在（迁移 0010 前）：逐条「校验路径
  → 删物理文件 → 删记录」；失败保留记录并报告，命令以非 0 退出。
- 旧表已删除（迁移后）：只扫描 originals/ 目录残余文件与空目录。
- 只操作 storage/institution/originals/ 内的文件，绝不删除 drafts/ 或
  versions/ 下的草稿与发布快照，也不改动任何草稿/版本/操作记录。
- dry-run 只读：不删除文件/记录，只返回将删除的 candidates。

推荐部署顺序：先执行本命令（旧表仍在时逐条安全清理），成功后再
`migrate institution 0010`；若已先迁移，本命令仍可作为目录收尾入口。
"""
from django.core.management.base import BaseCommand, CommandError

from apps.institution import original_cleanup


class Command(BaseCommand):
    help = ('清理已下线原稿体系的原稿记录与 originals/ 物理文件'
            '（幂等；失败逐项报告并以非 0 退出）')

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true', default=False,
            help='只扫描并报告将删除的文件，不执行任何删除')
        parser.add_argument(
            '--manual-id', type=int, default=None,
            help='仅清理指定制度（manual id）的原稿记录与目录')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        manual_id = options['manual_id']
        if manual_id is not None and manual_id <= 0:
            raise CommandError('--manual-id 必须为正整数')
        report = original_cleanup.cleanup_originals(
            dry_run=dry_run, manual_id=manual_id)
        self.stdout.write(original_cleanup.format_report(report))
        if not report['success']:
            failure_paths = '；'.join(
                f"{item['path']}: {item['error']}"
                for item in report['failures'][:20])
            more = ''
            if len(report['failures']) > 20:
                more = f'（另有 {len(report["failures"]) - 20} 项，详见上方 JSON）'
            raise CommandError(
                f'原稿清理存在 {len(report["failures"])} 项失败，未完成的'
                f'文件/记录已保留：{failure_paths}{more}')

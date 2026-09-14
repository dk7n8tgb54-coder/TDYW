# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License
"""一次性修复存量 PeriodicTask 的首次调度时区口径（幂等、可审计）。

背景见 libs/beat_tz_compat.py：django-celery-beat 2.9 在 last_run_at 为空时把
date_changed（USE_TZ=False 下为 Asia/Shanghai 本地 naive）当 UTC 解释，新任务
首次调度最多延迟 8 小时。TZCompatDatabaseScheduler 已在加载侧兼容该场景，但
数据库中 last_run_at 仍为 NULL，直到任务真正执行一次才会落值；本命令把存量
空 last_run_at 按同一转换规则显式落库，使数据库状态可见、可审计，且不再依赖
调度器子类兜底。

幂等性：只选中 last_run_at 为 NULL 且 enabled=True 的任务，修复后不再命中。
审计性：逐行打印任务名、修复前 date_changed 与修复后 last_run_at 及摘要计数。
不触碰已有 last_run_at 的任务；停用任务不修复（PeriodicTask.save() 对
enabled=False 会重置 last_run_at，重新启用时由兼容调度器按新 date_changed 转换）。
"""
from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask

from libs.beat_tz_compat import local_naive_to_utc_naive


class Command(BaseCommand):
    help = '将 last_run_at 为空的启用任务按 date_changed（本地 naive）→ UTC naive 修复首次调度基准'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='只打印将要修复的任务，不写入数据库',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        targets = PeriodicTask.objects.filter(
            enabled=True, last_run_at__isnull=True, date_changed__isnull=False,
        ).order_by('name')
        fixed = 0
        for task in targets:
            new_last_run = local_naive_to_utc_naive(task.date_changed)
            self.stdout.write(
                f'{"[dry-run]" if dry_run else "[fixed]"} {task.name}: '
                f'date_changed={task.date_changed} (local naive) -> '
                f'last_run_at={new_last_run} (utc naive)'
            )
            if dry_run:
                fixed += 1
                continue
            task.last_run_at = new_last_run
            # save() 会触发 PeriodicTasks.changed，运行中的 Beat 立即感知并重建调度；
            # date_changed 因 auto_now 同步刷新为本次修复时刻，语义即"任务最近一次变更"。
            task.save()
            fixed += 1
        label = 'examined' if dry_run else 'repaired'
        self.stdout.write(self.style.SUCCESS(f'periodic task last_run_at {label}: {fixed}'))

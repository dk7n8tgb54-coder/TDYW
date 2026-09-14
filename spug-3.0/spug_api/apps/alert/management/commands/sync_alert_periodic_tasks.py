from django.core.management.base import BaseCommand
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = '幂等初始化运行指标 Beat 任务（DatabaseScheduler）'

    def handle(self, *args, **options):
        # flush-run-metrics 聚合完整 5 分钟窗口，周期必须与 WINDOW_SECONDS=300 对齐。
        # 历史版本误用 5 秒，会产生大量空窗口聚合；重复执行同步命令时
        # update_or_create 只更新 defaults 中的调度字段，last_run_at / total_run_count
        # 不在 defaults 内，已有调度进度不会被清空或重置。
        interval, _ = IntervalSchedule.objects.get_or_create(every=300, period=IntervalSchedule.SECONDS)
        PeriodicTask.objects.update_or_create(
            name='flush-run-metrics', defaults={'task': 'apps.alert.tasks.flush_run_metrics', 'interval': interval, 'enabled': True}
        )
        cron, _ = CrontabSchedule.objects.get_or_create(minute='20', hour='3', day_of_week='*', day_of_month='*', month_of_year='*')
        PeriodicTask.objects.update_or_create(
            name='cleanup-run-metrics', defaults={'task': 'apps.alert.tasks.cleanup_run_metrics', 'crontab': cron, 'enabled': True}
        )
        self.stdout.write(self.style.SUCCESS('alert periodic tasks synchronized'))

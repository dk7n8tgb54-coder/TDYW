from django.core.management.base import BaseCommand
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = '幂等初始化运行指标 Beat 任务（DatabaseScheduler）'

    def handle(self, *args, **options):
        interval, _ = IntervalSchedule.objects.get_or_create(every=5, period=IntervalSchedule.SECONDS)
        PeriodicTask.objects.update_or_create(
            name='flush-run-metrics', defaults={'task': 'apps.alert.tasks.flush_run_metrics', 'interval': interval, 'enabled': True}
        )
        cron, _ = CrontabSchedule.objects.get_or_create(minute='20', hour='3', day_of_week='*', day_of_month='*', month_of_year='*')
        PeriodicTask.objects.update_or_create(
            name='cleanup-run-metrics', defaults={'task': 'apps.alert.tasks.cleanup_run_metrics', 'crontab': cron, 'enabled': True}
        )
        self.stdout.write(self.style.SUCCESS('alert periodic tasks synchronized'))

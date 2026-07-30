# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License
"""告警监控模块 Celery Beat 定时任务配置

使用方式（已在 spug/settings.py 中合并）：
    from apps.alert.celery_beat_schedule import ALERT_BEAT_SCHEDULE
    CELERY_BEAT_SCHEDULE.update(ALERT_BEAT_SCHEDULE)
"""
from celery.schedules import crontab

ALERT_BEAT_SCHEDULE = {
    # 每 10 分钟检查磁盘空间
    'check-disk-space': {
        'task': 'apps.alert.tasks.check_disk_space',
        'schedule': 600.0,
    },
    # 每 5 分钟采集数据库指标
    'collect-db-metrics': {
        'task': 'apps.alert.tasks.collect_db_metrics',
        'schedule': 300.0,
    },
    # 每周一 06:00 运行数据质量巡检
    'run-data-quality-check': {
        'task': 'apps.alert.tasks.run_data_quality_check',
        'schedule': crontab(hour=6, minute=0, day_of_week=1),
    },
}

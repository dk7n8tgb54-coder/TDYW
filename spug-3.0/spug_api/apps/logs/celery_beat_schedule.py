# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

"""
Logs 模块 Celery Beat 定时任务配置
需要在主项目的 settings.py 中导入并合并到 CELERY_BEAT_SCHEDULE

使用方式：
1. 在 spug/settings.py 中添加：
   from apps.logs.celery_beat_schedule import LOGS_BEAT_SCHEDULE
   CELERY_BEAT_SCHEDULE.update(LOGS_BEAT_SCHEDULE)

2. 启动 Celery Beat：
   celery -A spug beat -l info
"""
from celery.schedules import crontab

# Logs 模块定时任务配置
LOGS_BEAT_SCHEDULE = {
    # ========================================
    # 审计日志归档清理 - 每天凌晨4点执行
    # 保留 60 天审计日志（合规要求 2 个月），超过的物理删除
    # 避开 document 模块清理任务（02:00/03:00/05:00）
    # ========================================
    'logs-cleanup-old-audit-logs': {
        'task': 'apps.logs.tasks.cleanup_old_audit_logs',
        'schedule': crontab(hour=4, minute=0),
        'kwargs': {'days': 60},
        'options': {'queue': 'default'},
    },
}

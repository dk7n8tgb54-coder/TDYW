# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
协作任务模块 Celery Beat 定时任务配置
需要在主项目的 settings.py 中导入并合并到 CELERY_BEAT_SCHEDULE
"""
from celery.schedules import crontab

# 协作任务模块定时任务配置
COOP_TASK_BEAT_SCHEDULE = {
    # ========================================
    # 到期任务附件清理 - 每天凌晨 03:40 执行
    # 已完成/已作废/已删除超过保留期（COOP_TASK_FILE_RETENTION_DAYS）的任务，
    # 物理清理其附件文件与附件记录；任务/交付/审计记录保留。
    # ========================================
    'coop-task-cleanup-expired-attachments': {
        'task': 'apps.coop_task.tasks.cleanup_expired_task_attachments',
        'schedule': crontab(hour=3, minute=40),  # 每天 03:40
        'options': {
            'queue': 'default',
            'time_limit': 600,  # 10分钟超时
        },
    },
}

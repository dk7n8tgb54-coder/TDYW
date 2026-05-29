# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
Celery Beat 定时任务配置
用于周期性执行的后台任务
"""
from celery.schedules import crontab

# 定时任务配置
CELERY_BEAT_SCHEDULE = {
    # 每小时清理一次过期分片（保留7天）
    'cleanup-old-chunks-every-hour': {
        'task': 'apps.document.tasks.cleanup_old_chunks',
        'schedule': crontab(minute=0),  # 每小时执行
        'args': (7,),
        'options': {'queue': 'document.cleanup'},
    },
    
    # 每天凌晨3点清理过期传输记录（保留30天）
    'cleanup-expired-transfers-daily': {
        'task': 'apps.document.tasks.cleanup_expired_transfers',
        'schedule': crontab(hour=3, minute=0),  # 每天凌晨3点
        'args': (30,),
        'options': {'queue': 'document.cleanup'},
    },
}

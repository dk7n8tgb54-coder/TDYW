# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""公告模块 Celery Beat 定时任务配置

使用方式（已在 spug/settings.py 中合并）：
    from apps.home.celery_beat_schedule import HOME_BEAT_SCHEDULE
    CELERY_BEAT_SCHEDULE.update(HOME_BEAT_SCHEDULE)
"""
from celery.schedules import crontab

# 公告模块定时任务配置
HOME_BEAT_SCHEDULE = {
    # 每小时将到期公告置为已过期（接口实时计算 computed_status 已兜底，本任务保持存储状态准确）
    'announcement-sync-status': {
        'task': 'apps.home.tasks.sync_announcement_status',
        'schedule': crontab(minute=5),  # 每小时第 5 分钟
        'kwargs': {},
        'options': {'queue': 'home.announcement'},
    },
}

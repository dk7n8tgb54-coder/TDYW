# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
RadioLicense 模块 Celery Beat 定时任务配置
需要在主项目的 settings.py 中导入并合并到 CELERY_BEAT_SCHEDULE

使用方式：
1. 在 spug/settings.py 中添加：
   from apps.radio_license.celery_beat_schedule import RADIO_LICENSE_BEAT_SCHEDULE
   CELERY_BEAT_SCHEDULE.update(RADIO_LICENSE_BEAT_SCHEDULE)

2. 启动 Celery Beat：
   celery -A spug beat -l info
"""
from celery.schedules import crontab

# RadioLicense 模块定时任务配置
RADIO_LICENSE_BEAT_SCHEDULE = {
    # ========================================
    # 执照到期扫描 - 每天早上8点执行
    # 扫描未删除执照，更新状态，生成分级提醒
    # ========================================
    'radio-license-scan-expiration': {
        'task': 'apps.radio_license.tasks.scan_radio_license_expiration',
        'schedule': crontab(hour=8, minute=0),  # 每天 08:00
        'options': {
            'queue': 'radio_license',
            'time_limit': 600,  # 10分钟超时
        },
    },
}

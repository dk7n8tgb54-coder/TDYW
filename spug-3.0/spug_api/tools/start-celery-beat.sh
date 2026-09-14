#!/bin/bash
# Celery Beat 定时任务调度器启动脚本
cd /data/spug/spug_api
python manage.py sync_alert_periodic_tasks || echo '[alert] periodic task sync skipped; settings schedule remains active'
# 【修复】使用时区兼容调度器：last_run_at 为空的首次初始化任务把 date_changed
# （上海本地 naive）转换为 UTC naive，避免首次调度延迟约 8 小时。
# 与 settings.py 的 CELERY_BEAT_SCHEDULER 保持一致，详见 libs/beat_tz_compat.py。
exec celery -A spug beat -l info --scheduler libs.beat_tz_compat:TZCompatDatabaseScheduler

#!/bin/bash
# Celery Beat 定时任务调度器启动脚本
cd /data/spug/spug_api
exec celery -A spug beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler

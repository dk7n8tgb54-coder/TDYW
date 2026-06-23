#!/bin/bash
# Celery Default Worker 启动脚本（通用业务任务）
# 职责: 只监听 celery 默认队列（定时任务、消息通知等通用任务）
# 注意: 不再监听 document.merge（由专用 start-celery-merge.sh 处理）
#       不再监听 document.batch（由专用 start-celery-batch.sh 处理）
#       不再监听 document.cleanup（由专用 start-celery-cleanup.sh 处理）
# 依据: 《资料库并发上传与状态机修复方案》5.3 拆分 Celery merge worker
cd /data/spug/spug_api

# 确保 Django 设置模块已设置
export DJANGO_SETTINGS_MODULE=spug.settings

# 先导入 Django 确保所有应用加载
python3 -c "import django; django.setup()"

# 并发默认 2，可通过环境变量 CELERY_DEFAULT_CONCURRENCY 覆盖
CELERY_DEFAULT_CONCURRENCY=${CELERY_DEFAULT_CONCURRENCY:-2}

# 启动 Celery Default Worker（只监听 celery 默认队列）
exec celery -A spug worker -l info \
    -Q celery \
    -n default-worker@%h \
    --concurrency=${CELERY_DEFAULT_CONCURRENCY} \
    --prefetch-multiplier=1

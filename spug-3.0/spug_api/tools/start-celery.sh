#!/bin/bash
# Celery General Worker 启动脚本（通用任务 + 清理任务）
# 职责: 监听 celery(默认队列) 和 document.cleanup(清理队列)
# 注意: 不再监听 document.merge，合并任务由专用 start-celery-merge.sh 处理
#       不再监听 document.batch，批量任务由专用 start-celery-batch.sh 处理
# 依据: 《资料库并发上传与状态机修复方案》5.3 拆分 Celery merge worker
cd /data/spug/spug_api

# 确保 Django 设置模块已设置
export DJANGO_SETTINGS_MODULE=spug.settings

# 先导入 Django 确保所有应用加载
python3 -c "import django; django.setup()"

# 并发默认 2，可通过环境变量 CELERY_GENERAL_CONCURRENCY 覆盖
CELERY_GENERAL_CONCURRENCY=${CELERY_GENERAL_CONCURRENCY:-2}

# 启动 Celery General Worker（只监听通用队列和清理队列）
exec celery -A spug worker -l info \
    -Q celery,document.cleanup \
    -n general-worker@%h \
    --concurrency=${CELERY_GENERAL_CONCURRENCY} \
    --prefetch-multiplier=1

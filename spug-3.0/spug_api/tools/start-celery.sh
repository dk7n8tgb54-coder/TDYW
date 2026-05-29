#!/bin/bash
# Celery Worker 启动脚本（通用任务 + 文档合并任务）
cd /data/spug/spug_api

# 确保 Django 设置模块已设置
export DJANGO_SETTINGS_MODULE=spug.settings

# 先导入 Django 确保所有应用加载
python3 -c "import django; django.setup()"

# 启动 Celery Worker（监听通用任务队列、文档合并队列和清理队列）
exec celery -A spug worker -l info \
    -Q celery,document.merge,document.cleanup \
    -n general-worker@%h \
    --concurrency=4 \
    --prefetch-multiplier=1

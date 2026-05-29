#!/bin/bash
# Celery Worker 启动脚本（带队列配置）
cd /data/spug/spug_api

# 确保 Django 设置模块已设置
export DJANGO_SETTINGS_MODULE=spug.settings

# 先导入 Django 确保所有应用加载
python3 -c "import django; django.setup()"

# 启动 Celery Worker（监听 document 合并、批量操作、清理队列）
exec celery -A spug worker -l info \
    -Q document.merge,document.batch,document.cleanup \
    -n dev-worker@%h \
    --concurrency=2 \
    --prefetch-multiplier=1

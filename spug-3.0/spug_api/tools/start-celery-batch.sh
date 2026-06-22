#!/bin/bash
# Celery Batch Worker 启动脚本（批量操作专用）
# 职责: 只监听 document.batch 队列（批量删除、批量取消等）
# 依据: 《资料库并发上传与状态机修复方案》5.3 拆分 Celery merge worker
# 说明:
#   - 初始并发 2，可通过环境变量 CELERY_BATCH_CONCURRENCY 覆盖
#   - 保留 --prefetch-multiplier=1
cd /data/spug/spug_api

# 确保 Django 设置模块已设置
export DJANGO_SETTINGS_MODULE=spug.settings

# 先导入 Django 确保所有应用加载
python3 -c "import django; django.setup()"

# 并发默认 2，可通过环境变量 CELERY_BATCH_CONCURRENCY 覆盖
CELERY_BATCH_CONCURRENCY=${CELERY_BATCH_CONCURRENCY:-2}

# 启动 Celery Batch Worker（只监听 document.batch 批量队列）
exec celery -A spug worker -l info \
    -Q document.batch \
    -n batch-worker@%h \
    --concurrency=${CELERY_BATCH_CONCURRENCY} \
    --prefetch-multiplier=1

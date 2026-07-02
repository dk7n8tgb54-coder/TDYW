#!/bin/bash
# Celery Merge Worker 启动脚本（文件分片合并专用）
# 职责: 只监听 document.merge 队列
# 依据: 《资料库并发上传与状态机修复方案》5.3 拆分 Celery merge worker
# 说明:
#   - 默认并发 2（适合 8G 内存、普通 SSD/机械盘服务器），可通过环境变量 CELERY_MERGE_CONCURRENCY 覆盖
#   - 生产建议: 小型服务器(8G)用 1-2，高性能服务器(NVMe/16G+)可用 3-4
#   - 保留 --prefetch-multiplier=1，避免大文件合并任务被预取后阻塞其他任务
cd /data/spug/spug_api

# 确保 Django 设置模块已设置
export DJANGO_SETTINGS_MODULE=spug.settings

# 先导入 Django 确保所有应用加载
python3 -c "import django; django.setup()"

# 并发默认 2（8G 服务器建议），可通过环境变量 CELERY_MERGE_CONCURRENCY 覆盖
CELERY_MERGE_CONCURRENCY=${CELERY_MERGE_CONCURRENCY:-2}

# 启动 Celery Merge Worker（只监听 document.merge 合并队列）
exec celery -A spug worker -l info \
    -Q document.merge \
    -n merge-worker@%h \
    --concurrency=${CELERY_MERGE_CONCURRENCY} \
    --prefetch-multiplier=1

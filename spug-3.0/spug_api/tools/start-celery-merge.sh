#!/bin/bash
# Celery Merge Worker 启动脚本（文件分片合并专用）
# 职责: 只监听 document.merge 队列
# 依据: 《资料库并发上传与状态机修复方案》5.3 拆分 Celery merge worker
# 说明:
#   - 默认并发 1（单机械盘环境：合并串行，避免与上传随机写抢磁头；SSD/NVMe 可调回 2-3）
#   - 可通过环境变量 CELERY_MERGE_CONCURRENCY 覆盖
#   - 生产建议: 单机械盘用 1；SSD/RAID 用 2；NVMe/16G+ 可用 3-4
#   - 保留 --prefetch-multiplier=1，避免大文件合并任务被预取后阻塞其他任务
cd /data/spug/spug_api

# 确保 Django 设置模块已设置
export DJANGO_SETTINGS_MODULE=spug.settings

# 先导入 Django 确保所有应用加载
python3 -c "import django; django.setup()"

# 并发默认 1（单机械盘环境建议），可通过环境变量 CELERY_MERGE_CONCURRENCY 覆盖
CELERY_MERGE_CONCURRENCY=${CELERY_MERGE_CONCURRENCY:-1}

# 启动 Celery Merge Worker（只监听 document.merge 合并队列）
exec celery -A spug worker -l info \
    -Q document.merge \
    -n merge-worker@%h \
    --concurrency=${CELERY_MERGE_CONCURRENCY} \
    --prefetch-multiplier=1

#!/bin/bash
# Celery Cleanup Worker 启动脚本（上传链路清理专用）
# 职责: 只监听 document.cleanup 队列
# 依据: 《资料库并发上传与状态机修复方案》5.3 拆分 Celery merge worker
# 说明:
#   - 该队列只负责上传链路相关清理，不再作为回收站删除兜底队列
#   - 清理任务包括:
#       * 旧分片清理 (cleanup_old_chunks)
#       * 过期传输记录清理 (cleanup_expired_transfers)
#       * 孤儿传输记录清理 (cleanup_orphan_transfers)
#       * 卡住的 merging 任务清理 (check_merge_timeout / cleanup_stale_merging_tasks)
#       * 物理文件待清理重试 (retry_clean_pending_files)
#   - 默认并发 1，可通过环境变量 CELERY_CLEANUP_CONCURRENCY 覆盖
#   - 保留 --prefetch-multiplier=1，避免清理任务被预取后阻塞
cd /data/spug/spug_api

# 确保 Django 设置模块已设置
export DJANGO_SETTINGS_MODULE=spug.settings

# 先导入 Django 确保所有应用加载
python3 -c "import django; django.setup()"

# 并发默认 1，可通过环境变量 CELERY_CLEANUP_CONCURRENCY 覆盖
CELERY_CLEANUP_CONCURRENCY=${CELERY_CLEANUP_CONCURRENCY:-1}

# 启动 Celery Cleanup Worker（只监听 document.cleanup 清理队列）
exec celery -A spug worker -l info \
    -Q document.cleanup \
    -n cleanup-worker@%h \
    --concurrency=${CELERY_CLEANUP_CONCURRENCY} \
    --prefetch-multiplier=1

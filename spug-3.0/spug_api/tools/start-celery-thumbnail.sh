#!/bin/bash
# Celery Thumbnail Worker 启动脚本（资料库缩略图生成专用）
# 职责: 只监听 document.thumbnail 队列
# 依据: 《资料库上传性能优化建议》第 4 项 - 缩略图生成改异步
# 说明:
#   - 缩略图生成依赖 Pillow，大图解码吃 CPU
#   - 独立 worker 避免拖慢合并 worker（document.merge）和上传 API
#   - 并发默认 1（8G 服务器建议），可通过环境变量 CELERY_THUMBNAIL_CONCURRENCY 覆盖
#   - 图片上传量较大时可调到 2，但不建议与 merge worker 抢太多 CPU
#   - --prefetch-multiplier=1 避免单个大图任务被预取后阻塞其他缩略图任务
#   - --max-tasks-per-child=100 防止 Pillow 内存泄漏长期累积
cd /data/spug/spug_api

# 确保 Django 设置模块已设置
export DJANGO_SETTINGS_MODULE=spug.settings

# 先导入 Django 确保所有应用加载
python3 -c "import django; django.setup()"

# 并发默认 1，可通过环境变量 CELERY_THUMBNAIL_CONCURRENCY 覆盖
CELERY_THUMBNAIL_CONCURRENCY=${CELERY_THUMBNAIL_CONCURRENCY:-1}

# 启动 Celery Thumbnail Worker（只监听 document.thumbnail 队列）
exec celery -A spug worker -l info \
    -Q document.thumbnail \
    -n thumbnail-worker@%h \
    --concurrency=${CELERY_THUMBNAIL_CONCURRENCY} \
    --prefetch-multiplier=1 \
    --max-tasks-per-child=100

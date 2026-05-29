#!/bin/bash
# Celery 启动脚本

# 启动 Celery Worker
echo "Starting Celery Worker..."
celery -A spug worker -l info --concurrency=4 &

# 启动 Celery Beat (定时任务)
echo "Starting Celery Beat..."
celery -A spug beat -l info &

echo "Celery services started!"

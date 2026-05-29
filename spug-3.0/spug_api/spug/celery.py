# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
Celery 异步任务队列配置
"""
import os
from celery import Celery

# 设置 Django settings 模块
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

# 【修复】在加载 Celery 之前先加载 Django 配置，确保时区设置正确
import django
django.setup()

app = Celery('spug')

# 从 Django settings 加载配置
app.config_from_object('django.conf:settings', namespace='CELERY')

# 自动发现任务
app.autodiscover_tasks()

# 【修复】显式导入 document 模块的任务
# autodiscover_tasks() 只自动发现 tasks.py 文件，不发现 tasks/ 目录
def import_document_tasks():
    """显式导入 document 模块的 Celery 任务"""
    try:
        from apps.document.tasks import (
            merge_file_chunks,
            batch_delete_transfers,
            batch_cancel_transfers,
            cleanup_old_chunks,
            cleanup_expired_transfers,
            cleanup_soft_deleted_files,
            cleanup_soft_deleted_folders,
            retry_clean_pending_files,
            async_batch_permanent_delete,
            async_batch_folder_permanent_delete,
        )
        # 任务已通过 @shared_task 装饰器注册
        print('[Celery] Document tasks imported successfully')
    except Exception as e:
        print(f'[Celery] Warning: Failed to import document tasks: {e}')

# 在 Celery 应用初始化后导入任务
import_document_tasks()


@app.task(bind=True)
def debug_task(self):
    """调试任务"""
    print(f'Request: {self.request!r}')


# Celery 配置（备用，直接在settings中配置）
# CELERY_BROKER_URL = 'redis://127.0.0.1:6379/2'
# CELERY_RESULT_BACKEND = 'redis://127.0.0.1:6379/3'
# CELERY_ACCEPT_CONTENT = ['json']
# CELERY_TASK_SERIALIZER = 'json'
# CELERY_RESULT_SERIALIZER = 'json'
# CELERY_TIMEZONE = 'Asia/Shanghai'
# CELERY_TASK_TRACK_STARTED = True
# CELERY_TASK_TIME_LIMIT = 3600  # 1小时超时

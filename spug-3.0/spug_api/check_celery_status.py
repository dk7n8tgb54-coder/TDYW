#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Celery 状态诊断脚本
用于检查 Celery Worker 和任务队列状态
"""
import os
import sys

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import django
django.setup()

from celery import current_app as celery_app
from celery.result import AsyncResult
from spug.celery import app

def print_section(title):
    """打印带分隔线的标题"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

def check_celery_config():
    """检查 Celery 配置"""
    print_section("1. Celery 配置检查")
    
    print(f"Broker URL: {app.conf.broker_url}")
    print(f"Result Backend: {app.conf.result_backend}")
    print(f"Accepted Content: {app.conf.accept_content}")
    print(f"Task Serializer: {app.conf.task_serializer}")
    print(f"Result Serializer: {app.conf.result_serializer}")
    print(f"Timezone: {app.conf.timezone}")
    print(f"Task Routes: {app.conf.task_routes}")

def check_registered_tasks():
    """检查已注册的任务"""
    print_section("2. 已注册任务检查")
    
    tasks = app.tasks
    cleanup_tasks = [name for name in tasks.keys() if 'cleanup' in name]
    
    print(f"总共注册任务数: {len(tasks)}")
    print(f"\n清理相关任务 ({len(cleanup_tasks)}):")
    for task_name in sorted(cleanup_tasks):
        print(f"  ✓ {task_name}")
    
    # 检查关键任务是否存在
    required_tasks = [
        'apps.document.tasks.merge_file_chunks',
        'apps.document.tasks.cleanup_old_chunks',
        'apps.document.tasks.cleanup_expired_transfers',
        'apps.document.tasks.cleanup.retry_clean_pending_files',
        'apps.document.tasks.cleanup.orphan_transfers.cleanup_orphan_transfers',
        'apps.document.tasks.timeout_checker.check_merge_timeout',
    ]
    
    print("\n关键任务检查:")
    for task_name in required_tasks:
        if task_name in tasks:
            print(f"  ✓ {task_name}")
        else:
            print(f"  ✗ {task_name} - 未找到！")

def check_worker_status():
    """检查 Worker 状态"""
    print_section("3. Worker 状态检查")
    
    try:
        inspector = app.control.inspect()
        
        # 检查活跃 Worker
        active_workers = inspector.active()
        if active_workers:
            print(f"活跃 Worker 数量: {len(active_workers)}")
            for worker_name, tasks in active_workers.items():
                print(f"  - {worker_name}: {len(tasks)} 个活跃任务")
        else:
            print("  ✗ 没有活跃的 Worker！")
        
        # 检查 Worker 队列
        active_queues = inspector.active_queues()
        if active_queues:
            print(f"\nWorker 队列信息:")
            for worker_name, queues in active_queues.items():
                queue_names = [q['name'] for q in queues]
                print(f"  - {worker_name}: {', '.join(queue_names)}")
                
                # 检查 document.cleanup 队列
                if 'document.cleanup' in queue_names:
                    print(f"    ✓ 已监听 document.cleanup 队列")
                else:
                    print(f"    ✗ 未监听 document.cleanup 队列！")
        else:
            print("  ✗ 无法获取队列信息")
        
        # 检查计划任务
        scheduled = inspector.scheduled()
        if scheduled:
            print(f"\n计划任务:")
            for worker_name, tasks in scheduled.items():
                print(f"  - {worker_name}: {len(tasks)} 个计划任务")
        
        # 检查保留任务
        reserved = inspector.reserved()
        if reserved:
            print(f"\n保留任务:")
            for worker_name, tasks in reserved.items():
                print(f"  - {worker_name}: {len(tasks)} 个保留任务")
                
    except Exception as e:
        print(f"  ✗ 检查 Worker 状态失败: {e}")
        print("  提示: 请确保 Celery Worker 已启动")

def check_redis_connection():
    """检查 Redis 连接"""
    print_section("4. Redis 连接检查")
    
    try:
        from kombu import Connection
        with Connection(app.conf.broker_url) as conn:
            conn.connect()
            print("  ✓ Redis Broker 连接成功")
    except Exception as e:
        print(f"  ✗ Redis 连接失败: {e}")

def check_pending_tasks():
    """检查待处理任务"""
    print_section("5. 待处理任务检查")
    
    try:
        inspector = app.control.inspect()
        
        # 检查队列中的任务
        scheduled = inspector.scheduled()
        reserved = inspector.reserved()
        
        total_pending = 0
        if scheduled:
            for tasks in scheduled.values():
                total_pending += len(tasks)
        if reserved:
            for tasks in reserved.values():
                total_pending += len(tasks)
        
        print(f"  队列中待处理任务数: {total_pending}")
        
        if total_pending > 0:
            print("\n  提示: 如果有任务长时间处于等待状态，可能是 Worker 未正确启动")
            print("  或 Worker 未监听正确的队列")
            
    except Exception as e:
        print(f"  检查失败: {e}")

def main():
    print("=" * 60)
    print("  Celery 状态诊断工具")
    print("=" * 60)
    print(f"\n当前时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    check_celery_config()
    check_registered_tasks()
    check_redis_connection()
    check_worker_status()
    check_pending_tasks()
    
    print_section("诊断建议")
    print("""
如果上传/合并/清理任务一直处于"等待中"，请检查:

1. Celery Worker 是否已启动（每个队列应由专用 worker 消费）:
   cd spug_api
   celery -A spug worker -Q document.merge -n merge-worker@%%h -l info
   celery -A spug worker -Q document.cleanup -n cleanup-worker@%%h -l info
   celery -A spug worker -Q document.batch -n batch-worker@%%h -l info
   celery -A spug worker -Q celery -n default-worker@%%h -l info

2. 检查各 worker 监听的队列是否正确:
   celery -A spug inspect active_queues

3. Redis 是否正常运行:
   redis-cli ping

4. 重启 Worker (如果配置已修改):
   supervisorctl restart spug-celery-merge spug-celery-cleanup spug-celery-batch spug-celery
""")

if __name__ == '__main__':
    main()

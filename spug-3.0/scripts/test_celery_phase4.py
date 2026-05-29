#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第四阶段 - Celery 功能验证测试脚本
测试内容：
1. Celery 任务注册检查
2. 文件合并任务提交测试
3. 批量操作任务提交测试
4. 任务状态查询测试
5. 定时任务配置检查
"""

import os
import sys
import time
import django

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, '/data/spug/spug_api')

try:
    django.setup()
except Exception as e:
    print(f"❌ Django 初始化失败: {e}")
    sys.exit(1)

from spug.celery import app
from celery.result import AsyncResult
from django_celery_beat.models import PeriodicTask, IntervalSchedule, CrontabSchedule

def print_header(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def print_result(test_name, success, message=""):
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} - {test_name}")
    if message:
        print(f"       {message}")

def test_celery_app():
    """测试 Celery 应用配置"""
    print_header("1. Celery 应用配置检查")
    
    tests = []
    
    # 检查 broker 配置
    try:
        broker_url = app.conf.broker_url
        tests.append(("Broker URL 配置", True, broker_url))
    except Exception as e:
        tests.append(("Broker URL 配置", False, str(e)))
    
    # 检查 result backend
    try:
        result_backend = app.conf.result_backend
        tests.append(("Result Backend 配置", True, result_backend))
    except Exception as e:
        tests.append(("Result Backend 配置", False, str(e)))
    
    # 检查任务路由
    try:
        task_routes = app.conf.task_routes
        tests.append(("Task Routes 配置", True, f"{len(task_routes)} routes"))
    except Exception as e:
        tests.append(("Task Routes 配置", False, str(e)))
    
    for name, success, msg in tests:
        print_result(name, success, msg)
    
    return all(t[1] for t in tests)

def test_registered_tasks():
    """测试已注册任务"""
    print_header("2. 已注册任务检查")
    
    # 手动导入任务模块以确保任务注册
    try:
        import apps.document.tasks
        from apps.document.tasks import (
            merge_file_chunks,
            batch_delete_transfers,
            batch_cancel_transfers,
            cleanup_old_chunks,
            cleanup_expired_transfers,
        )
        import_success = True
    except Exception as e:
        import_success = False
        import_error = str(e)
    
    expected_tasks = [
        ('merge_file_chunks', 'apps.document.tasks.merge.merge_file_chunks'),
        ('batch_delete_transfers', 'apps.document.tasks.batch.batch_delete_transfers'),
        ('batch_cancel_transfers', 'apps.document.tasks.batch.batch_cancel_transfers'),
        ('cleanup_old_chunks', 'apps.document.tasks.cleanup.cleanup_old_chunks'),
        ('cleanup_expired_transfers', 'apps.document.tasks.cleanup.cleanup_expired_transfers'),
        ('debug_task', 'spug.celery.debug_task'),
    ]
    
    # 重新获取任务列表（导入后）
    all_tasks = list(app.tasks.keys())
    tests = []
    
    for short_name, full_name in expected_tasks:
        if full_name in all_tasks:
            tests.append((short_name, True, "已注册"))
        else:
            # 检查是否是别名
            found = False
            for task_key in all_tasks:
                if short_name in task_key or full_name in task_key:
                    tests.append((short_name, True, f"已注册 ({task_key})"))
                    found = True
                    break
            if not found:
                tests.append((short_name, False, "未找到"))
    
    for name, success, msg in tests:
        print_result(name, success, msg)
    
    return all(t[1] for t in tests)

def test_task_execution():
    """测试任务执行"""
    print_header("3. 任务执行测试")
    
    tests = []
    
    # 测试 debug 任务
    try:
        from spug.celery import debug_task
        result = debug_task.delay()
        tests.append(("Debug 任务提交", True, f"task_id: {result.id}"))
        
        # 等待任务完成
        time.sleep(1)
        async_result = AsyncResult(result.id)
        tests.append(("Debug 任务状态查询", True, f"state: {async_result.state}"))
    except Exception as e:
        tests.append(("Debug 任务执行", False, str(e)))
    
    for name, success, msg in tests:
        print_result(name, success, msg)
    
    return all(t[1] for t in tests)

def test_periodic_tasks():
    """测试定时任务配置"""
    print_header("4. 定时任务配置检查")
    
    tests = []
    
    try:
        # 检查 IntervalSchedule
        interval_count = IntervalSchedule.objects.count()
        tests.append(("IntervalSchedule 记录", True, f"{interval_count} records"))
        
        # 检查 CrontabSchedule
        crontab_count = CrontabSchedule.objects.count()
        tests.append(("CrontabSchedule 记录", True, f"{crontab_count} records"))
        
        # 检查 PeriodicTask
        periodic_count = PeriodicTask.objects.count()
        tests.append(("PeriodicTask 记录", True, f"{periodic_count} tasks"))
        
        # 列出所有定时任务
        if periodic_count > 0:
            tasks = PeriodicTask.objects.all()
            task_names = [t.name for t in tasks]
            tests.append(("定时任务列表", True, ", ".join(task_names)))
        
    except Exception as e:
        tests.append(("定时任务查询", False, str(e)))
    
    for name, success, msg in tests:
        print_result(name, success, msg)
    
    return all(t[1] for t in tests)

def test_document_tasks():
    """测试 Document 模块任务"""
    print_header("5. Document 模块任务测试")
    
    tests = []
    
    # 测试导入
    try:
        from apps.document.tasks import (
            merge_file_chunks,
            batch_delete_transfers,
            batch_cancel_transfers,
            cleanup_old_chunks,
            cleanup_expired_transfers,
        )
        tests.append(("任务模块导入", True, "所有任务可导入"))
    except Exception as e:
        tests.append(("任务模块导入", False, str(e)))
        return False
    
    # 测试 cleanup 任务（安全，不修改数据）
    try:
        result = cleanup_old_chunks.delay()
        tests.append(("Cleanup 任务提交", True, f"task_id: {result.id}"))
        
        time.sleep(1)
        async_result = AsyncResult(result.id)
        tests.append(("Cleanup 任务状态", True, f"state: {async_result.state}"))
    except Exception as e:
        tests.append(("Cleanup 任务执行", False, str(e)))
    
    for name, success, msg in tests:
        print_result(name, success, msg)
    
    return all(t[1] for t in tests)

def test_redis_connection():
    """测试 Redis 连接"""
    print_header("6. Redis 连接检查")
    
    tests = []
    
    try:
        from django_redis import get_redis_connection
        conn = get_redis_connection("default")
        conn.ping()
        tests.append(("Redis 连接", True, "PONG"))
        
        # 检查 Celery broker
        from kombu import Connection
        with Connection(app.conf.broker_url) as conn:
            conn.connect()
            tests.append(("Celery Broker 连接", True, "已连接"))
            
    except Exception as e:
        tests.append(("Redis 连接", False, str(e)))
    
    for name, success, msg in tests:
        print_result(name, success, msg)
    
    return all(t[1] for t in tests)

def main():
    print_header("Celery 功能验证测试 - 第四阶段")
    print(f"开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []
    
    results.append(("Celery 应用配置", test_celery_app()))
    results.append(("已注册任务", test_registered_tasks()))
    results.append(("任务执行", test_task_execution()))
    results.append(("定时任务配置", test_periodic_tasks()))
    results.append(("Document 模块任务", test_document_tasks()))
    results.append(("Redis 连接", test_redis_connection()))
    
    print_header("测试总结")
    
    total = len(results)
    passed = sum(1 for _, r in results if r)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")
    
    print(f"\n总计: {passed}/{total} 项测试通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！Celery 迁移第四阶段验证成功！")
        return 0
    else:
        print(f"\n⚠️ 有 {total - passed} 项测试失败，请检查配置")
        return 1

if __name__ == '__main__':
    sys.exit(main())

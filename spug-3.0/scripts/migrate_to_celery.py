#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Celery 迁移辅助脚本
用于检查 APScheduler 未完成任务并准备迁移
"""
import os
import sys

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, '/data/spug/spug_api')

try:
    import django
    django.setup()
except Exception as e:
    print(f"Django setup failed: {e}")
    sys.exit(1)


def check_aps_scheduler_jobs():
    """检查APScheduler中未完成的任务"""
    print("\n=== 检查APScheduler未完成任务 ===")
    try:
        from apps.document.libs.scheduler import get_scheduler
        scheduler = get_scheduler()
        
        if not scheduler.running:
            print("⚠️  APScheduler未运行")
            return []
        
        jobs = scheduler.get_jobs()
        print(f"发现 {len(jobs)} 个未完成任务")
        
        for job in jobs:
            print(f"  - {job.id}: {job.name}")
        
        return jobs
        
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        return []


def check_database_migrations():
    """检查数据库迁移状态"""
    print("\n=== 检查数据库迁移状态 ===")
    
    required_tables = [
        'django_celery_beat_periodictask',
        'django_celery_beat_intervalschedule',
        'django_celery_beat_crontabschedule',
        'django_celery_results_taskresult',
    ]
    
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            existing_tables = [row[0] for row in cursor.fetchall()]
        
        missing_tables = []
        for table in required_tables:
            if table in existing_tables:
                print(f"  ✓ {table}")
            else:
                print(f"  ✗ {table} (缺失)")
                missing_tables.append(table)
        
        if missing_tables:
            print(f"\n⚠️  需要执行迁移: python manage.py migrate django_celery_beat django_celery_results")
        
        return len(missing_tables) == 0
        
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        return False


def check_redis_connection():
    """检查Redis连接"""
    print("\n=== 检查Redis连接 ===")
    try:
        from django.conf import settings
        from redis import Redis
        
        redis_client = Redis.from_url(settings.CELERY_BROKER_URL)
        if redis_client.ping():
            print("  ✓ Redis连接正常")
            
            # 检查Broker和Backend数据库
            broker_info = settings.CELERY_BROKER_URL
            backend_info = settings.CELERY_RESULT_BACKEND
            print(f"  ℹ️  Broker: {broker_info}")
            print(f"  ℹ️  Backend: {backend_info}")
            
            return True
        else:
            print("  ❌ Redis连接失败")
            return False
            
    except Exception as e:
        print(f"  ❌ Redis连接失败: {e}")
        return False


def check_celery_config():
    """检查Celery配置"""
    print("\n=== 检查Celery配置 ===")
    try:
        from django.conf import settings
        
        required_settings = [
            'CELERY_BROKER_URL',
            'CELERY_RESULT_BACKEND',
            'CELERY_TASK_ROUTES',
        ]
        
        all_ok = True
        for setting in required_settings:
            if hasattr(settings, setting):
                print(f"  ✓ {setting}")
            else:
                print(f"  ✗ {setting} (缺失)")
                all_ok = False
        
        # 检查定时任务配置
        if hasattr(settings, 'CELERY_BEAT_SCHEDULE') and settings.CELERY_BEAT_SCHEDULE:
            print(f"  ✓ CELERY_BEAT_SCHEDULE ({len(settings.CELERY_BEAT_SCHEDULE)}个定时任务)")
        else:
            print(f"  ⚠️  CELERY_BEAT_SCHEDULE (空)")
        
        return all_ok
        
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        return False


def main():
    print("="*50)
    print("Celery 迁移前检查工具")
    print("="*50)
    
    results = {
        'apscheduler_jobs': check_aps_scheduler_jobs(),
        'database_migrations': check_database_migrations(),
        'redis_connection': check_redis_connection(),
        'celery_config': check_celery_config(),
    }
    
    print("\n" + "="*50)
    print("检查结果汇总")
    print("="*50)
    
    if not results['database_migrations']:
        print("\n⚠️  请先执行数据库迁移:")
        print("   python manage.py migrate django_celery_beat")
        print("   python manage.py migrate django_celery_results")
    
    if not results['redis_connection']:
        print("\n❌ Redis连接失败，请检查:")
        print("   1. Redis服务是否启动")
        print("   2. CELERY_BROKER_URL配置是否正确")
    
    if not results['celery_config']:
        print("\n⚠️  Celery配置不完整，请参考迁移方案文档")
    
    if results['apscheduler_jobs']:
        print("\n⚠️  APScheduler中有未完成任务，请等待完成或手动处理")
    
    if all([
        results['database_migrations'],
        results['redis_connection'],
        results['celery_config'],
        not results['apscheduler_jobs']
    ]):
        print("\n✅ 所有检查通过，可以开始迁移！")
        print("\n下一步操作:")
        print("   1. 启动Celery Worker")
        print("   2. 启动Celery Beat")
        print("   3. 验证任务执行")
    else:
        print("\n❌ 请解决上述问题后再进行迁移")
        sys.exit(1)


if __name__ == '__main__':
    main()

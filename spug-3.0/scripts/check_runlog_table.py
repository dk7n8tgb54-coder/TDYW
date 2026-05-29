#!/usr/bin/env python
"""检查运行日志表是否存在"""
import os
import sys
import django

# 设置Django环境
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from django.db import connection
from django.core.management import call_command

def check_table_exists(table_name):
    """检查表是否存在"""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
            AND table_name = %s
        """, [table_name])
        count = cursor.fetchone()[0]
        return count > 0

def main():
    print("="*60)
    print("  运行日志表检查")
    print("="*60)

    # 检查runlog_run_logs表（根据models.py中的db_table定义）
    runlog_exists = check_table_exists('runlog_run_logs')
    runlog_update_exists = check_table_exists('runlog_run_log_updates')

    print(f"\nrunlog_run_logs表存在: {'✅ 是' if runlog_exists else '❌ 否'}")
    print(f"runlog_run_log_updates表存在: {'✅ 是' if runlog_update_exists else '❌ 否'}")

    if not runlog_exists:
        print("\n❌ runlog_run_logs表不存在，需要创建")
        print("\n请运行以下命令创建表：")
        print("  python manage.py migrate runlog")
        return 1

    if not runlog_update_exists:
        print("\n❌ runlog_run_log_updates表不存在，需要创建")
        print("\n请运行以下命令创建表：")
        print("  python manage.py migrate runlog")
        return 1

    # 检查表结构
    print("\n检查表结构...")
    with connection.cursor() as cursor:
        cursor.execute("DESCRIBE runlog_run_logs")
        columns = cursor.fetchall()
        print(f"\nrunlog_run_logs表字段数: {len(columns)}")
        for col in columns[:5]:  # 显示前5个字段
            print(f"  - {col[0]} ({col[1]})")

    print("\n✅ 运行日志表检查通过")
    return 0

if __name__ == '__main__':
    sys.exit(main())

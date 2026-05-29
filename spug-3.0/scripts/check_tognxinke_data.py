#!/usr/bin/env python
"""检查tognxinke租户数据"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from django.db import connection
cursor = connection.cursor()

# 检查tognxinke租户数据量
cursor.execute('SELECT COUNT(*) FROM runlog_run_logs WHERE tenant_id="tognxinke"')
tognxinke_count = cursor.fetchone()[0]
print(f'tognxinke租户记录数: {tognxinke_count}')

# 检查总记录数
cursor.execute('SELECT COUNT(*) FROM runlog_run_logs')
total = cursor.fetchone()[0]
print(f'总记录数: {total}')

# 测试tognxinke租户的查询性能
cursor.execute('EXPLAIN SELECT COUNT(CASE WHEN status="in_progress" THEN 1 END) FROM runlog_run_logs WHERE tenant_id="tognxinke"')
explain = cursor.fetchall()
print(f'\ntognxinke租户查询执行计划:')
for row in explain:
    print(f'  type: {row[3]}, key: {row[4]}, rows: {row[6]}')

# 测试日期查询
from datetime import datetime, timedelta
start_date = (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')
cursor.execute(f'EXPLAIN SELECT DATE(created_at) AS day, COUNT(*) FROM runlog_run_logs WHERE tenant_id="tognxinke" AND created_at >= "{start_date} 00:00:00" GROUP BY DATE(created_at)')
explain2 = cursor.fetchall()
print(f'\ntognxinke租户日期查询执行计划:')
for row in explain2:
    print(f'  type: {row[3]}, key: {row[4]}, rows: {row[6]}')

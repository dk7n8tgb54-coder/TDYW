#!/usr/bin/env python
"""检查runlog表结构"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from django.db import connection
cursor = connection.cursor()
print('runlog_run_logs 表结构:')
print('='*60)
cursor.execute('DESC runlog_run_logs')
for row in cursor.fetchall():
    print(f'{row[0]:20} {row[1]:20} {row[2]:10}')

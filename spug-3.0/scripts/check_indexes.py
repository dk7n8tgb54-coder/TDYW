#!/usr/bin/env python
"""检查exec_interferences表的索引"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("SHOW INDEX FROM exec_interferences;")
    indexes = cursor.fetchall()

    print("exec_interferences 表的索引:")
    print("-" * 80)
    for idx in indexes:
        print(f"表名: {idx[0]}, 索引名: {idx[2]}, 列名: {idx[4]}, 唯一: {idx[1]}")
    print("-" * 80)
    print(f"共 {len(indexes)} 个索引")

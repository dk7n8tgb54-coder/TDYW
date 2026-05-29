import os
import django

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ.setdefault('MYSQL_DATABASE', 'spug')
os.environ.setdefault('MYSQL_USER', 'spug')
os.environ.setdefault('MYSQL_PASSWORD', 'spug.cc')
os.environ.setdefault('MYSQL_HOST', '127.0.0.1')
os.environ.setdefault('MYSQL_PORT', '3306')

django.setup()

from django.db import connection

# 检查碎片情况
with connection.cursor() as cursor:
    cursor.execute("""
        SELECT table_schema, table_name, data_free, engine 
        FROM information_schema.tables 
        WHERE table_schema = 'spug' AND data_free > 0 
        ORDER BY data_free DESC
    """)
    results = cursor.fetchall()

print("数据库表碎片情况：")
print("-" * 80)
print(f"{'数据库':<15} {'表名':<30} {'碎片大小(字节)':<20} {'存储引擎':<10}")
print("-" * 80)

if results:
    for row in results:
        table_schema, table_name, data_free, engine = row
        print(f"{table_schema:<15} {table_name:<30} {data_free:<20} {engine:<10}")
    print("-" * 80)
    print("发现碎片，需要优化！")
else:
    print("未发现碎片，数据库状态良好。")
    print("-" * 80)

# 检查所有表的状态
print("\n所有表状态：")
print("-" * 80)
print(f"{'表名':<30} {'行数':<10} {'数据大小':<15} {'索引大小':<15} {'总大小':<15}")
print("-" * 80)

with connection.cursor() as cursor:
    cursor.execute("""
        SELECT table_name, table_rows, data_length, index_length, data_length + index_length as total_size 
        FROM information_schema.tables 
        WHERE table_schema = 'spug' 
        ORDER BY total_size DESC
    """)
    all_tables = cursor.fetchall()

for row in all_tables:
    table_name, table_rows, data_length, index_length, total_size = row
    print(f"{table_name:<30} {table_rows:<10} {data_length:<15} {index_length:<15} {total_size:<15}")

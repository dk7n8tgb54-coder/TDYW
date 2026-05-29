#!/usr/bin/env python3
import os, sys
sys.path.insert(0, "/data/spug/spug_api")
os.environ['DJANGO_SETTINGS_MODULE'] = "spug.settings"
import django
django.setup()
from django.db import connection

cursor = connection.cursor()

# 查看公共空间文件表的创建语句
print("=" * 60)
print("spug_document_file_public 表结构")
print("=" * 60)
cursor.execute("SHOW CREATE TABLE spug_document_file_public")
row = cursor.fetchone()
print(row[1])

print("\n" + "=" * 60)
print("检查外键约束")
print("=" * 60)

# 方法1: 使用 SHOW CREATE TABLE 解析
import re
fk_pattern = r"CONSTRAINT `([^`]+)` FOREIGN KEY \(`([^`]+)`\)"
fks = re.findall(fk_pattern, row[1])
if fks:
    for fk in fks:
        print(f"  找到外键: {fk[0]} -> {fk[1]}")
else:
    print("  没有找到外键约束")

# 方法2: 检查索引
print("\n" + "=" * 60)
print("检查索引")
print("=" * 60)
cursor.execute("SHOW INDEX FROM spug_document_file_public")
for row in cursor.fetchall():
    print(f"  {row[2]}: {row[4]}")

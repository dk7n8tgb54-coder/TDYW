#!/usr/bin/env python3
"""
修复数据库字段长度
"""
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "spug.settings")

import django
django.setup()

from django.db import connection

def fix_columns():
    with connection.cursor() as cursor:
        # 修改私有空间文件表
        cursor.execute("ALTER TABLE document_documentfileprivate MODIFY COLUMN physical_name VARCHAR(100) NULL")
        cursor.execute("ALTER TABLE document_documentfileprivate MODIFY COLUMN name VARCHAR(100)")
        print("[OK] document_documentfileprivate columns updated")
        
        # 修改公共空间文件表
        cursor.execute("ALTER TABLE document_documentfilepublic MODIFY COLUMN physical_name VARCHAR(100) NULL")
        cursor.execute("ALTER TABLE document_documentfilepublic MODIFY COLUMN name VARCHAR(100)")
        print("[OK] document_documentfilepublic columns updated")
        
    print("\nAll database columns updated successfully!")

if __name__ == "__main__":
    fix_columns()

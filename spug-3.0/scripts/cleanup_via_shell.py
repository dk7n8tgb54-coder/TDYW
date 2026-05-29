#!/usr/bin/env python3
"""
Django Shell 极速清理脚本
直接在数据库层面删除，绕过业务逻辑，速度最快

使用方法:
    cd spug_api
    python manage.py shell < ../cleanup_via_shell.py

警告: 此脚本直接操作数据库，不经过业务逻辑验证，请确保已备份数据！
"""

import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django
django.setup()

from apps.document.models import DocumentFolderPrivate, DocumentFolderPublic

print("=" * 70)
print("Django Shell 极速清理回收站")
print("=" * 70)

# 统计数量
private_count = DocumentFolderPrivate.all_objects.filter(is_deleted=True).count()
public_count = DocumentFolderPublic.all_objects.filter(is_deleted=True).count()
total = private_count + public_count

print(f"\n待清理文件夹:")
print(f"  私有空间: {private_count} 个")
print(f"  公共空间: {public_count} 个")
print(f"  总计: {total} 个")

if total == 0:
    print("\n✅ 回收站为空")
    exit(0)

# 确认
confirm = input("\n⚠️ 确定要永久删除这些文件夹吗？输入 'yes' 继续: ")
if confirm.lower() != 'yes':
    print("❌ 操作已取消")
    exit(0)

print("\n🗑️ 开始清理...")

# 使用原始SQL加速删除（绕过Django ORM的级联操作）
from django.db import connection

with connection.cursor() as cursor:
    # 删除私有文件夹（软删除标记的）
    if private_count > 0:
        cursor.execute("""
            DELETE FROM spug_document_folder_private 
            WHERE is_deleted = 1
        """)
        print(f"  已删除 {private_count} 个私有文件夹")
    
    # 删除公共文件夹
    if public_count > 0:
        cursor.execute("""
            DELETE FROM spug_document_folder_public 
            WHERE is_deleted = 1
        """)
        print(f"  已删除 {public_count} 个公共文件夹")

print("\n✅ 清理完成！")
print(f"总计删除: {total} 个文件夹")
print("=" * 70)

# 注意：物理文件需要单独清理
print("\n⚠️ 注意: 数据库记录已删除，但物理文件可能仍在磁盘上")
print("如需清理物理文件，请手动删除 storage/documents 目录下的相关文件")

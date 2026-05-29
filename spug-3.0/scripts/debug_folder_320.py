#!/usr/bin/env python
"""
调试脚本：检查文件夹 ID=320 的状态
"""
import os
import sys
import django

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'spug_api'))

django.setup()

from apps.document.models import DocumentFolderPrivate, DocumentFolderPublic

folder_id = 320

print(f"=== 检查文件夹 ID={folder_id} 的状态 ===\n")

# 检查私有空间
print("1. 私有空间 (DocumentFolderPrivate):")
try:
    folder = DocumentFolderPrivate.objects.get(id=folder_id)
    print(f"   - 存在: 是")
    print(f"   - 名称: {folder.name}")
    print(f"   - is_deleted: {folder.is_deleted}")
    print(f"   - deleted_at: {folder.deleted_at}")
    print(f"   - created_by: {folder.created_by}")
    print(f"   - tenant_id: {getattr(folder, 'tenant_id', 'N/A')}")
except DocumentFolderPrivate.DoesNotExist:
    print(f"   - 存在: 否")

# 使用 all_objects 检查（包含已删除）
print("\n2. 私有空间 (包含已删除 all_objects):")
try:
    folder = DocumentFolderPrivate.all_objects.get(id=folder_id)
    print(f"   - 存在: 是")
    print(f"   - 名称: {folder.name}")
    print(f"   - is_deleted: {folder.is_deleted}")
    print(f"   - deleted_at: {folder.deleted_at}")
    print(f"   - created_by: {folder.created_by}")
except DocumentFolderPrivate.DoesNotExist:
    print(f"   - 存在: 否")

# 检查公共空间
print("\n3. 公共空间 (DocumentFolderPublic):")
try:
    folder = DocumentFolderPublic.objects.get(id=folder_id)
    print(f"   - 存在: 是")
    print(f"   - 名称: {folder.name}")
    print(f"   - is_deleted: {folder.is_deleted}")
    print(f"   - deleted_at: {folder.deleted_at}")
    print(f"   - created_by: {folder.created_by}")
except DocumentFolderPublic.DoesNotExist:
    print(f"   - 存在: 否")

# 使用 all_objects 检查
print("\n4. 公共空间 (包含已删除 all_objects):")
try:
    folder = DocumentFolderPublic.all_objects.get(id=folder_id)
    print(f"   - 存在: 是")
    print(f"   - 名称: {folder.name}")
    print(f"   - is_deleted: {folder.is_deleted}")
    print(f"   - deleted_at: {folder.deleted_at}")
    print(f"   - created_by: {folder.created_by}")
except DocumentFolderPublic.DoesNotExist:
    print(f"   - 存在: 否")

print("\n=== 结论 ===")
print("如果文件夹在 all_objects 中存在但 is_deleted=False，说明已经被恢复了")
print("如果文件夹在 all_objects 中也不存在，说明已被彻底删除或ID错误")

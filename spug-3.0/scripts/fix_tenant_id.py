#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
修复用户和私密空间数据的 tenant_id
将用户的 tenant_id 从默认的 'admin' 改为用户的 username
"""

import os
import sys
import django

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, '/data/spug/spug_api')
django.setup()

from apps.account.models import User
from apps.document.models import DocumentFolderPrivate, DocumentFilePrivate

def fix_user_tenant_id():
    """修复用户的 tenant_id"""
    print("=" * 60)
    print("开始修复用户 tenant_id")
    print("=" * 60)
    
    users = User.objects.all()
    fixed_count = 0
    
    for user in users:
        old_tenant_id = user.tenant_id
        # 如果 tenant_id 是 'admin' 或空，则改为 username
        if old_tenant_id == 'admin' or not old_tenant_id:
            user.tenant_id = user.username
            user.save(update_fields=['tenant_id'])
            print(f"  用户 {user.username}: '{old_tenant_id}' -> '{user.username}'")
            fixed_count += 1
        else:
            print(f"  用户 {user.username}: tenant_id='{old_tenant_id}' (无需修改)")
    
    print(f"\n共修复 {fixed_count} 个用户")
    return fixed_count

def fix_folder_tenant_id():
    """修复私密文件夹的 tenant_id"""
    print("\n" + "=" * 60)
    print("开始修复私密文件夹 tenant_id")
    print("=" * 60)
    
    folders = DocumentFolderPrivate.objects.all()
    fixed_count = 0
    
    for folder in folders:
        old_tenant_id = folder.tenant_id
        # 获取创建者的 tenant_id
        creator_tenant_id = folder.created_by.tenant_id if folder.created_by else None
        
        if creator_tenant_id and old_tenant_id != creator_tenant_id:
            folder.tenant_id = creator_tenant_id
            folder.save(update_fields=['tenant_id'])
            print(f"  文件夹 {folder.name}: '{old_tenant_id}' -> '{creator_tenant_id}'")
            fixed_count += 1
    
    print(f"\n共修复 {fixed_count} 个文件夹")
    return fixed_count

def fix_file_tenant_id():
    """修复私密文件的 tenant_id"""
    print("\n" + "=" * 60)
    print("开始修复私密文件 tenant_id")
    print("=" * 60)
    
    files = DocumentFilePrivate.objects.all()
    fixed_count = 0
    
    for file in files:
        old_tenant_id = file.tenant_id
        # 获取创建者的 tenant_id
        creator_tenant_id = file.created_by.tenant_id if file.created_by else None
        
        if creator_tenant_id and old_tenant_id != creator_tenant_id:
            file.tenant_id = creator_tenant_id
            file.save(update_fields=['tenant_id'])
            print(f"  文件 {file.name}: '{old_tenant_id}' -> '{creator_tenant_id}'")
            fixed_count += 1
    
    print(f"\n共修复 {fixed_count} 个文件")
    return fixed_count

if __name__ == '__main__':
    print("租户ID修复脚本")
    print("=" * 60)
    
    # 修复用户
    user_fixed = fix_user_tenant_id()
    
    # 修复文件夹
    folder_fixed = fix_folder_tenant_id()
    
    # 修复文件
    file_fixed = fix_file_tenant_id()
    
    print("\n" + "=" * 60)
    print("修复完成！")
    print(f"  用户: {user_fixed} 个")
    print(f"  文件夹: {folder_fixed} 个")
    print(f"  文件: {file_fixed} 个")
    print("=" * 60)

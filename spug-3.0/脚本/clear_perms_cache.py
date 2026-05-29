#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
清除所有用户的权限缓存，强制重新计算权限
"""
import os
import sys
import django

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'spug_api'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug_api.settings')

django.setup()

from django.core.cache import cache
from apps.account.models import User, Role
import json

print("=== 清除所有用户的权限缓存 ===")
count = 0
for user in User.objects.filter(deleted_by_id__isnull=True):
    # 清除缓存
    cache.delete(f'perms_{user.id}')
    user.set_perms_cache()
    count += 1
    print(f"已清除用户 {user.username} 的权限缓存")

print(f"\n总共清除了 {count} 个用户的权限缓存")

print("\n=== 检查所有角色的 page_perms ===")
for role in Role.objects.all():
    if role.page_perms:
        try:
            perms = json.loads(role.page_perms)
            print(f"\n角色: {role.name}")
            print(f"  包含模块: {list(perms.keys())}")
        except Exception as e:
            print(f"\n角色: {role.name} - page_perms 解析失败: {e}")
    else:
        print(f"\n角色: {role.name} - page_perms 为空")

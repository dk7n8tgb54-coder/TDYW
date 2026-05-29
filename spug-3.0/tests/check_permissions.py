#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, '/data/spug/spug_api')
django.setup()

from apps.account.models import User

# 检查用户权限
user = User.objects.get(id=5)
print(f"用户: {user.username}")
print(f"昵称: {user.nickname}")
print(f"是否为超级管理员: {user.is_supper}")
print(f"用户组: {list(user.groups.values_list('name', flat=True))}")

# 检查用户的所有权限
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

print("\n用户直接权限:")
for perm in user.user_permissions.all():
    print(f"  - {perm.codename}")

print("\n通过用户组获得的权限:")
for group in user.groups.all():
    print(f"  组: {group.name}")
    for perm in group.permissions.all():
        print(f"    - {perm.codename}")

# 检查是否有document相关的权限
document_perms = user.get_all_permissions()
doc_perms = [p for p in document_perms if 'document' in p]
print(f"\nDocument相关权限 ({len(doc_perms)}):")
for p in doc_perms:
    print(f"  - {p}")

#!/usr/bin/env python
"""检查admin用户权限"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.account.models import User

admin_user = User.objects.filter(username='admin').first()
if admin_user:
    print(f'用户名: {admin_user.username}')
    print(f'是否超级管理员: {admin_user.is_supper}')
    print(f'租户ID: {admin_user.tenant_id}')
    print(f'是否激活: {admin_user.is_active}')
else:
    print('admin用户不存在')

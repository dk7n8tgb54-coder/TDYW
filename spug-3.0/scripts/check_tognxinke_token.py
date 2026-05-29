#!/usr/bin/env python
"""检查tognxinke用户的token"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.account.models import User

user = User.objects.filter(username='tognxinke').first()
if user:
    print(f'用户名: {user.username}')
    print(f'type: {user.type}')
    print(f'租户ID: {user.tenant_id}')
    print(f'是否激活: {user.is_active}')
    print(f'是否超级管理员: {user.is_supper}')
    print(f'access_token: {user.access_token[:20] if user.access_token else None}...')
    print(f'token_expired: {user.token_expired}')
else:
    print('用户不存在')

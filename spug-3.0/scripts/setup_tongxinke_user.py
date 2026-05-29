#!/usr/bin/env python
"""创建tongxinke用户用于压测"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.account.models import User
from libs import human_datetime
import string, random

# 检查tongxinke用户
user = User.objects.filter(username='tongxinke').first()
if user:
    print(f'✅ 用户已存在:')
    print(f'  用户名: {user.username}')
    print(f'  昵称: {user.nickname}')
    print(f'  是否超级管理员: {user.is_supper}')
    print(f'  租户ID: {user.tenant_id}')
    print(f'  是否激活: {user.is_active}')
else:
    print('tongxinke用户不存在，正在创建...')

    # 创建access_token
    access_token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))

    user = User.objects.create(
        username='tongxinke',
        nickname='通信科技',
        password_hash=User.make_password('Dt@6299093'),
        type='default',
        is_supper=False,
        is_active=True,
        access_token=access_token,
        token_expired=None,
        last_login=human_datetime(),
        last_ip='127.0.0.1',
        tenant_id='tongxinke'
    )
    print(f'✅ 已创建用户:')
    print(f'  用户名: {user.username}')
    print(f'  昵称: {user.nickname}')
    print(f'  是否超级管理员: {user.is_supper}')
    print(f'  租户ID: {user.tenant_id}')
    print(f'  密码: Dt@6299093')

print(f'\n压测账号信息:')
print(f'  用户名: tongxinke')
print(f'  密码: Dt@6299093')
print(f'  是否超级管理员: {user.is_supper} (False表示会触发租户过滤)')

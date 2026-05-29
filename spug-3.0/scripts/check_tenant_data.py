#!/usr/bin/env python
"""检查tongxinke账号数据量"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.account.models import User
from apps.runlog.models import RunLog
from libs.tenant_utils import apply_tenant_filter

user = User.objects.filter(username='tongxinke').first()
if user:
    print(f'用户: {user.username}, 租户ID: {user.tenant_id}, is_supper: {user.is_supper}')
    logs = apply_tenant_filter(RunLog.objects.all(), user)
    print(f'tongxinke租户数据量: {logs.count()} 条')

super_user = User.objects.filter(username='admin').first()
if super_user:
    super_logs = apply_tenant_filter(RunLog.objects.all(), super_user)
    print(f'超级管理员数据量: {super_logs.count()} 条')

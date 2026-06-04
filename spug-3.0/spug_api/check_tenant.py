#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查 tenant_id 是否一致"""
import os
import sys

sys.path.insert(0, '/data/spug/spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django
django.setup()

from apps.runlog.models import RunLog, RunLogUpdate

print("=" * 80)
print("检查 tenant_id 一致性")
print("=" * 80)

events = RunLog.objects.all().order_by('-id')

for event in events:
    updates = RunLogUpdate.objects.filter(runlog_id=event.id)

    print(f"\n事件 ID={event.id}, tenant_id={event.tenant_id}")
    print(f"  动态记录数 (未过滤): {updates.count()}")

    # 检查每条动态的 tenant_id
    for u in updates:
        match = "✓" if u.tenant_id == event.tenant_id else "✗ 不匹配!"
        print(f"    Update ID={u.id}, tenant_id={u.tenant_id} {match}")

    # 使用租户过滤后的计数
    from libs.tenant_utils import apply_tenant_filter

    class FakeRequest:
        def __init__(self, user):
            self.user = user

    # 创建一个模拟请求来测试 apply_tenant_filter
    # 由于没有真实用户，我们直接看 SQL

print("\n" + "=" * 80)
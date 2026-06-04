#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""直接测试修复逻辑"""
import os
import sys

# 设置 Django 环境
sys.path.insert(0, '/data/spug/spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django
django.setup()

from apps.runlog.models import RunLog, RunLogUpdate

print("=" * 80)
print("测试修复 update_count")
print("=" * 80)

# 获取所有事件
events = RunLog.objects.all()
fixed_count = 0

for event in events:
    # 实时计算实际的动态数量
    actual_count = RunLogUpdate.objects.filter(runlog_id=event.id).count()

    # 如果不一致，则修复
    if event.update_count != actual_count:
        old_count = event.update_count
        event.update_count = actual_count

        # 同时更新首尾日期
        if actual_count > 0:
            updates = RunLogUpdate.objects.filter(runlog_id=event.id).order_by('update_date', 'sequence', 'id')

            first_update = updates.first()
            last_update = updates.last()

            if first_update:
                event.first_update_date = first_update.update_date
            if last_update:
                event.last_update_date = last_update.update_date
        else:
            event.first_update_date = None
            event.last_update_date = None

        event.save()
        fixed_count += 1
        print(f'[修复] 事件ID={event.id}, update_count: {old_count} -> {actual_count}')

print(f"\n修复完成: 成功修复 {fixed_count} 条记录")

# 再次验证
print("\n" + "=" * 80)
print("修复后验证")
print("=" * 80)

events = RunLog.objects.all().order_by('-id')
print(f"\n{'ID':<5} {'名称':<20} {'update_count':<15} {'actual_count':<15}")
print("-" * 80)

for event in events:
    actual_count = RunLogUpdate.objects.filter(runlog_id=event.id).count()
    marker = " <-- 不一致" if event.update_count != actual_count else ""
    print(f"{event.id:<5} {event.event_title[:18]:<20} {event.update_count:<15} {actual_count:<15}{marker}")

print("\n" + "=" * 80)
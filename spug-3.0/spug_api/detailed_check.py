#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""详细检查 RunLog update_count 与实际动态记录的不一致情况"""
import os
import sys

# 设置 Django 环境
sys.path.insert(0, '/data/spug/spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django
django.setup()

from apps.runlog.models import RunLog, RunLogUpdate

print("=" * 80)
print("详细检查 update_count 不一致问题")
print("=" * 80)

# 获取所有 RunLog 记录及其实际动态数量
# RunLogUpdate 使用 runlog_id 整数字段关联，需要手动计数
events = RunLog.objects.all().order_by('-id')

print(f"\n{'ID':<5} {'名称':<20} {'update_count':<15} {'actual_count':<15} {'差异':<10}")
print("-" * 80)

inconsistent = []
for event in events:
    actual_count = RunLogUpdate.objects.filter(runlog_id=event.id).count()
    diff = event.update_count - actual_count
    marker = " <-- 不一致" if diff != 0 else ""
    print(f"{event.id:<5} {event.event_title[:18]:<20} {event.update_count:<15} {actual_count:<15} {diff:<10}{marker}")
    if diff != 0:
        inconsistent.append({
            'id': event.id,
            'name': event.event_title,
            'stored': event.update_count,
            'actual': actual_count
        })

print("\n" + "=" * 80)
print(f"不一致记录数: {len(inconsistent)}")
print("=" * 80)

for item in inconsistent:
    print(f"\nID={item['id']} ({item['name']}):")
    print(f"  update_count (缓存值): {item['stored']}")
    print(f"  actual_count (实际值): {item['actual']}")

    # 查看该事件的所有动态记录
    updates = RunLogUpdate.objects.filter(runlog_id=item['id']).order_by('update_date', 'id')
    print(f"  动态记录详情 ({updates.count()} 条):")
    for u in updates:
        content_preview = u.detail_content[:50] if u.detail_content else 'None'
        print(f"    - ID={u.id}, date={u.update_date}, content={content_preview}...")

print("\n" + "=" * 80)
print("检查完成")
print("=" * 80)
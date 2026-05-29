#!/usr/bin/env python
"""
检查运行日志 update_count 字段准确性的脚本
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.runlog.models import RunLog, RunLogUpdate

print('=== 检查运行日志 update_count 字段准确性 ===\n')

# 检查 update_count 不准确的记录
inaccurate_logs = []

logs = RunLog.objects.all()
for log in logs:
    # 查询该运行日志的实际动态数（按 tenant_id 过滤）
    actual_count = RunLogUpdate.objects.filter(
        runlog_id=log.id,
        tenant_id=log.tenant_id
    ).count()

    if log.update_count != actual_count:
        inaccurate_logs.append({
            'id': log.id,
            'event_title': log.event_title,
            'tenant_id': log.tenant_id,
            'stored_count': log.update_count,
            'actual_count': actual_count,
            'diff': actual_count - log.update_count
        })

if inaccurate_logs:
    print(f'❌ 发现 {len(inaccurate_logs)} 条 update_count 不准确的记录:\n')

    for i, item in enumerate(inaccurate_logs, 1):
        print(f'{i}. ID={item["id"]}')
        print(f'   标题: {item["event_title"][:50]}')
        print(f'   租户: {item["tenant_id"]}')
        print(f'   存储值: {item["stored_count"]}, 实际值: {item["actual_count"]}, 差值: {item["diff"]:+d}')
        print()

    # 询问是否修复
    print('=' * 60)
    print('若需修复，请运行修复脚本或手动执行 SQL')

else:
    print('✅ 所有记录的 update_count 都是准确的！')

# 统计各租户数据
print('\n=== 各租户数据统计 ===')
from django.db.models import Count, Sum

tenant_stats = logs.values('tenant_id').annotate(
    log_count=Count('id'),
    stored_total=Sum('update_count')
).order_by('tenant_id')

for stat in tenant_stats:
    # 计算实际总动态数
    actual_total = RunLogUpdate.objects.filter(
        runlog_id__in=RunLog.objects.filter(tenant_id=stat['tenant_id']).values('id'),
        tenant_id=stat['tenant_id']
    ).count()

    print(f'租户 {stat["tenant_id"]}:')
    print(f'  运行日志: {stat["log_count"]} 条')
    print(f'  存储的动态总数: {stat["stored_total"] or 0}')
    print(f'  实际动态总数: {actual_total}')

    if stat["stored_total"] != actual_total:
        print(f'  ⚠️  不一致! 差值: {actual_total - (stat["stored_total"] or 0):+d}')
    else:
        print(f'  ✅ 一致')
    print()

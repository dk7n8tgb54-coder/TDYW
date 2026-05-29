#!/usr/bin/env python
import django
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

# 初始化Django
django.setup()

from apps.interference.models import Interference

print("检查干扰记录总数...")
total_count = Interference.objects.count()
print(f"数据库中干扰记录总数: {total_count}")

# 按时间分组统计
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from datetime import timedelta

# 最近7天创建的记录
recent_date = timezone.now() - timedelta(days=7)
recent_count = Interference.objects.filter(created_at__gte=recent_date).count()
print(f"最近7天创建的记录数: {recent_count}")

# 按租户统计
from django.db.models.functions import TruncDay
daily_stats = Interference.objects.filter(
    created_at__gte=recent_date
).annotate(
    date=TruncDate('created_at')
).values('date', 'tenant_id').annotate(
    count=Count('id')
).order_by('date', 'tenant_id')

print("\n最近7天每日创建记录（按租户）:")
for stat in daily_stats:
    print(f"  {stat['date']} | 租户: {stat['tenant_id'] or '全局'} | 创建: {stat['count']}条")

# 查看最新创建的10条记录
print("\n最新创建的10条记录:")
latest_records = Interference.objects.order_by('-created_at')[:10]
for record in latest_records:
    print(f"  ID: {record.id} | 时间: {record.created_at} | 租户: {record.tenant_id or '全局'} | 序号: {record.serial_number}")

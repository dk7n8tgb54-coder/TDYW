#!/usr/bin/env python
"""为tongxinke租户创建测试数据"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.runlog.models import RunLog, RunLogUpdate
from apps.account.models import User
from libs import human_datetime
from datetime import datetime, timedelta
import random

# 获取tongxinke用户
user = User.objects.filter(username='tongxinke').first()
if not user:
    print('错误: tongxinke用户不存在')
    exit(1)

print(f'为租户 {user.tenant_id} 创建测试数据...')

# 创建测试事件
test_data = []
today = datetime.now()

for i in range(200):  # 创建200个测试事件
    event_title = f'通信科技测试事件_{i}'
    days_ago = random.randint(0, 30)  # 最近30天
    event_date = today - timedelta(days=days_ago)
    created_at_str = human_datetime(event_date)

    test_data.append(RunLog(
        event_title=event_title,
        event_type=random.choice(['运行异常', '设备故障', '安全事件', '数据异常']),
        system_name=random.choice(['通信系统', '网络设备', '服务器', '数据库']),
        severity=random.choice(['P0', 'P1', 'P2']),
        status=random.choice(['in_progress', 'resolved']),
        responsible_user_name=random.choice(['张三', '李四', '王五']),
        tenant_id=user.tenant_id,
        created_by=user,
        created_at=created_at_str,
        updated_at=created_at_str
    ))

# 批量插入
RunLog.objects.bulk_create(test_data)
print(f'✅ 已创建 {len(test_data)} 个测试事件')

# 创建一些动态（可选）
for event in RunLog.objects.filter(tenant_id=user.tenant_id)[:100]:  # 前100个事件
    # 提取日期部分
    update_date_str = event.created_at.split(' ')[0] if ' ' in event.created_at else event.created_at[:10]
    RunLogUpdate.objects.create(
        runlog_id=event.id,
        event_title=event.event_title,
        update_date=update_date_str,
        update_time_detail=f'{random.randint(0,23):02d}:{random.randint(0,59):02d}',
        sequence=1,
        recorder='通信科技',
        detail_content='初始动态',
        editable_until=(datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S'),
        created_by=user,
        tenant_id=user.tenant_id
    )
    # 更新事件统计
    event.update_count = 1
    event.first_update_date = update_date_str
    event.last_update_date = update_date_str
    event.save()

print('✅ 已为部分事件创建动态')

print('\n数据创建完成，可以开始压测了！')

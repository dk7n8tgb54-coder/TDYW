#!/usr/bin/env python
"""生成运行日志测试数据脚本 给每个账号生成1w条数据，每条日志包含3条动态记录"""
"""docker exec tdyw python3 /data/spug/spug_api/generate_runlog_data.py"""
import os
import sys
import django

# 配置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from apps.runlog.models import RunLog, RunLogUpdate
from apps.account.models import User
from datetime import datetime, timedelta
from django.utils import timezone
import random

# 账号配置
ACCOUNTS = [
    {'username': 'tongxinke', 'password': 'Dt@6299093', 'name': '通信科'},
    {'username': 'zidonghuake', 'password': 'Aa@123456', 'name': '自动化科'},
    {'username': 'daohangke', 'password': 'Aa@123456', 'name': '导航科'},
    {'username': 'dianhuake', 'password': 'Aa@123456', 'name': '电话科'}
]

# 数据配置
RECORDS_PER_ACCOUNT = 10000  # 每个账号1万条
UPDATES_PER_RECORD = 3  # 每条日志3条动态
BATCH_SIZE = 500  # 批量插入批次大小

# 事件类型
EVENT_TYPES = ['运行异常', '设备故障', '安全事件', '其他']
SYSTEM_NAMES = ['主服务器', '数据库系统', '网络设备', '存储系统', '备份系统']
SEVERITY_LEVELS = ['P0', 'P1', 'P2']
STATUSES = ['in_progress', 'resolved']

# 动态内容模板
UPDATE_TEMPLATES = [
    "发现{severity}级别问题，正在排查",
    "已完成初步诊断，问题原因：{cause}",
    "修复方案已实施，效果验证正常"
]

CAUSE_TEMPLATES = [
    "资源占用过高",
    "服务响应超时",
    "配置参数异常",
    "硬件故障",
    "网络波动"
]


def get_user(username):
    """获取用户"""
    try:
        return User.objects.get(username=username)
    except User.DoesNotExist:
        print(f"⚠️  账号 {username} 不存在")
        return None


def generate_random_date(days_back=60):
    """生成随机日期（最近60天内）"""
    random_days = random.randint(0, days_back)
    random_hours = random.randint(0, 23)
    random_minutes = random.randint(0, 59)
    return datetime.now() - timedelta(days=random_days, hours=random_hours, minutes=random_minutes)


def generate_updates(runlog, count, created_by, tenant_id):
    """为运行日志生成动态记录"""
    updates = []
    severity = runlog.severity
    cause = random.choice(CAUSE_TEMPLATES)

    # 动态日期：从事件创建日期开始，每隔几天一条
    base_date = datetime.strptime(runlog.created_at, '%Y-%m-%d %H:%M:%S')

    for i in range(count):
        update_date = base_date + timedelta(days=i)
        update_date_str = update_date.strftime('%Y-%m-%d')

        # 动态内容
        if i == 0:
            detail_content = f"发现{severity}级别问题，问题类型：{runlog.event_type}，系统：{runlog.system_name}"
        elif i == count - 1:
            detail_content = f"已完成问题修复，最终方案：优化{cause}问题，已验证效果正常"
        else:
            detail_content = UPDATE_TEMPLATES[1].format(severity=severity, cause=cause)

        update = RunLogUpdate(
            runlog_id=runlog.id,
            event_title=runlog.event_title,
            update_date=update_date_str,
            sequence=i + 1,
            recorder=created_by.username,
            detail_content=detail_content,
            editable_until=(update_date + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S'),
            created_by=created_by,
            tenant_id=tenant_id
        )
        updates.append(update)

    return updates


def main():
    print("="*70)
    print("  运行日志测试数据生成工具")
    print("="*70)

    # 验证账号
    users = []
    for account in ACCOUNTS:
        user = get_user(account['username'])
        if user:
            users.append(user)
            print(f"✓ 找到账号: {account['name']} ({account['username']})")

    if not users:
        print("❌ 未找到有效账号，请先创建账号")
        return

    print(f"\n将为 {len(users)} 个账号各生成 {RECORDS_PER_ACCOUNT} 条运行日志")
    print(f"每条日志包含 {UPDATES_PER_RECORD} 条动态记录")
    print(f"总计将生成: {len(users) * RECORDS_PER_ACCOUNT} 条日志 + {len(users) * RECORDS_PER_ACCOUNT * UPDATES_PER_RECORD} 条动态\n")

    # 生成数据
    for user in users:
        print(f"\n{'='*70}")
        print(f"正在为 {user.username} 生成数据...")
        print(f"{'='*70}")

        tenant_id = getattr(user, 'tenant_id', 'admin')
        logs_to_create = []
        updates_to_create = []

        for i in range(RECORDS_PER_ACCOUNT):
            # 生成随机创建时间（最近60天内分散）
            created_at = generate_random_date(60)
            created_at_str = created_at.strftime('%Y-%m-%d %H:%M:%S')

            # 随机选择事件级别和状态
            severity = random.choice(SEVERITY_LEVELS)
            status = random.choice(STATUSES)

            # 创建运行日志
            log = RunLog(
                event_title=f"{user.username}测试事件_{i:05d}",
                event_type=random.choice(EVENT_TYPES),
                system_name=random.choice(SYSTEM_NAMES),
                severity=severity,
                status=status,
                responsible_user_name=user.username,
                tenant_id=tenant_id,
                created_by=user,
                created_at=created_at_str
            )
            logs_to_create.append(log)

            # 批量插入日志（每BATCH_SIZE条）
            if len(logs_to_create) >= BATCH_SIZE:
                RunLog.objects.bulk_create(logs_to_create)
                print(f"  ✓ 已创建 {len(logs_to_create)} 条日志")
                logs_to_create = []

        # 插入剩余日志
        if logs_to_create:
            RunLog.objects.bulk_create(logs_to_create)
            print(f"  ✓ 已创建 {len(logs_to_create)} 条日志")
            logs_to_create = []

        # 获取刚创建的日志ID
        print(f"\n  正在为日志生成动态记录...")
        recent_logs = RunLog.objects.filter(
            tenant_id=tenant_id,
            created_by=user
        ).order_by('-created_at')[:RECORDS_PER_ACCOUNT]

        for log in recent_logs:
            updates = generate_updates(log, UPDATES_PER_RECORD, user, tenant_id)
            updates_to_create.extend(updates)

            # 批量插入动态
            if len(updates_to_create) >= BATCH_SIZE:
                RunLogUpdate.objects.bulk_create(updates_to_create)
                print(f"  ✓ 已创建 {len(updates_to_create)} 条动态")
                updates_to_create = []

        # 插入剩余动态
        if updates_to_create:
            RunLogUpdate.objects.bulk_create(updates_to_create)
            print(f"  ✓ 已创建 {len(updates_to_create)} 条动态")
            updates_to_create = []

        # 更新日志的统计信息
        print(f"\n  正在更新日志统计信息...")
        for log in recent_logs:
            # 实际查询每个日志的动态数量（考虑租户隔离）
            actual_count = RunLogUpdate.objects.filter(
                runlog_id=log.id,
                tenant_id=log.tenant_id
            ).count()
            log.update_count = actual_count
            log.save(update_fields=['update_count'])

        print(f"\n✓ {user.username} 数据生成完成！")

    print(f"\n{'='*70}")
    print("  所有数据生成完成！")
    print(f"{'='*70}")
    print(f"  账号数量: {len(users)}")
    print(f"  日志总数: {len(users) * RECORDS_PER_ACCOUNT} 条")
    print(f"  动态总数: {len(users) * RECORDS_PER_ACCOUNT * UPDATES_PER_RECORD} 条")
    print(f"  日期范围: 最近60天内分散分布")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()

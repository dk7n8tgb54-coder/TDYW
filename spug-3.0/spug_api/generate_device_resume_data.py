"""""""""
设备履历数据生成脚本

该脚本用于为测试账号批量生成设备履历和设备事件数据：
- 为每个账号生成 100 条设备履历记录
- 为每条设备履历生成 600 条事件记录（平均分配3种事件类型）
- 自动设置 tenant_id 为对应用户的 username，实现租户隔离
- 总共生成 400 条设备履历和 240,000 条事件记录

使用方法：
    docker exec tdyw python3 /data/spug/spug_api/generate_device_resume_data.py
"""

import os
import django
import random
import time
from datetime import datetime, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.account.models import User
from apps.device.models import DeviceResume, DeviceEvent


# 账号配置
ACCOUNTS = [
    {'username': 'tongxinke', 'password': 'Dt@6299093', 'name': '通信科'},
    {'username': 'zidonghuake', 'password': 'Aa@123456', 'name': '自动化科'},
    {'username': 'daohangke', 'password': 'Aa@123456', 'name': '导航科'},
    {'username': 'dianhuake', 'password': 'Aa@123456', 'name': '电话科'},
]

# 设备状态
DEVICE_STATUS = ['1', '2', '3', '4', '5']  # 正常, 故障, 维修中, 停用, 报废

# 事件类型
EVENT_TYPES = [1, 2, 3]  # 重大故障维修, 设备更新, 设备检修

# 使用单位
USE_UNITS = ['通信科', '自动化科', '导航科', '电话科', '雷达科', '气象科', '导航台']

# 设备型号
DEVICE_MODELS = [
    '华为设备-1型', '华为设备-2型', '中兴设备-1型', '中兴设备-2型',
    '雷达设备-A型', '雷达设备-B型', '通信设备-1型', '通信设备-2型',
    '导航设备-X型', '导航设备-Y型', '自动化设备-A1', '自动化设备-B1'
]

# 事件描述
EVENT_DESCRIPTIONS = [
    '设备例行检查，状态良好',
    '发现异常，已进行故障排查',
    '完成设备维护，更换相关部件',
    '系统升级，功能正常',
    '设备检修完成，测试通过',
    '紧急故障处理，已恢复运行',
    '年度保养完成',
    '软件更新，性能优化',
    '硬件升级，提高稳定性',
    '预防性维护',
    '发现潜在问题，已处理',
    '设备校准完成'
]

# 备注内容
REMARKS = [
    '正常使用中',
    '需要定期检查',
    '已安排维护计划',
    '重点关注设备',
    '使用频率较高',
    '需加强保养',
    '设备老化，需关注',
    '运行稳定',
    '状态良好',
    '建议定期更换配件'
]


def generate_device_name(unit_name, index):
    """生成设备名称"""
    return f"{unit_name}-设备-{index:04d}"


def generate_random_date(start_days_ago=365):
    """生成随机日期（过去365天内）"""
    start_date = datetime.now() - timedelta(days=start_days_ago)
    random_days = random.randint(0, start_days_ago)
    random_hours = random.randint(0, 23)
    random_minutes = random.randint(0, 59)
    return start_date + timedelta(days=random_days, hours=random_hours, minutes=random_minutes)


def create_device_resume(user, account_name, index):
    """创建设备履历"""
    current_status = random.choice(DEVICE_STATUS)
    use_unit = account_name  # 使用单位与账号对应
    device_model = random.choice(DEVICE_MODELS)
    device_name = generate_device_name(account_name, index)
    # 生成唯一设备编号：科室-用户ID-索引-时间戳后4位
    timestamp_suffix = str(int(time.time()))[-4:]
    device_sn = f"{account_name}-{user.id}-{index:04d}-{timestamp_suffix}"
    install_location = f"{account_name}-机房-{random.randint(1, 10)}"
    manufacturer = random.choice(['华为', '中兴', '海康威视', '大华', '浪潮', '联想'])
    install_unit = account_name
    install_time = generate_random_date(365*3)
    enable_time = install_time + timedelta(days=random.randint(1, 30))
    responsible_user_id = user.id
    responsible_user_name = user.username

    device = DeviceResume.objects.create(
        device_sn=device_sn,
        device_name=device_name,
        device_model=device_model,
        install_location=install_location,
        manufacturer=manufacturer,
        install_unit=install_unit,
        use_unit=use_unit,
        install_time=install_time.strftime('%Y-%m-%d'),
        enable_time=enable_time.strftime('%Y-%m-%d'),
        current_status=current_status,
        responsible_user_id=responsible_user_id,
        responsible_user_name=responsible_user_name,
        tenant_id=user.username,
        created_by=user,
        updated_by=user
    )
    return device


def create_device_events(device, user):
    """为设备创建事件（平均分配三种事件类型）"""
    event_count = 600
    events_per_type = event_count // 3  # 每种类型200条

    events = []
    # 事件时间范围：过去365天，从最早到今天
    start_date = datetime.now() - timedelta(days=365)

    # 按时间顺序生成事件，确保事件时间递增
    for event_type in EVENT_TYPES:
        for i in range(events_per_type):
            # 每个事件的时间都不同，均匀分布在365天内
            days_offset = i + (EVENT_TYPES.index(event_type) * events_per_type)
            total_events = len(EVENT_TYPES) * events_per_type
            progress = days_offset / total_events  # 0 到 1 之间

            # 按进度分配天数，加上随机偏移让时间更自然
            base_days = int(365 * progress)
            random_offset = random.randint(0, 5)  # 0-5天随机偏移
            actual_days = base_days + random_offset

            # 确保不超过365天
            actual_days = min(actual_days, 365)

            # 随机小时和分钟
            random_hour = random.randint(0, 23)
            random_minute = random.randint(0, 59)

            event_time = start_date + timedelta(
                days=actual_days,
                hours=random_hour,
                minutes=random_minute
            )

            event = DeviceEvent(
                device_resume_id=device.id,
                device_name=device.device_name,
                device_sn=device.device_sn,
                event_type=event_type,
                event_time=event_time.strftime('%Y-%m-%d %H:%M:%S'),
                event_title=random.choice(EVENT_DESCRIPTIONS),
                related_user_id=user.id,
                related_user_name=user.username,
                tenant_id=user.username,
                created_by=user
            )
            events.append(event)

    # 按事件时间排序（从旧到新）
    events.sort(key=lambda x: x.event_time)

    # 批量创建事件
    DeviceEvent.objects.bulk_create(events)
    return events


def generate_data_for_account(account_info):
    """为单个账号生成数据"""
    username = account_info['username']
    password = account_info['password']
    account_name = account_info['name']

    print(f"\n{'='*60}")
    print(f"开始为账号 {username} ({account_name}) 生成数据...")
    print(f"{'='*60}")

    # 获取用户
    try:
        user = User.objects.get(username=username)
        print(f"✓ 找到用户: {user.username} (ID: {user.id})")
    except User.DoesNotExist:
        print(f"✗ 错误: 未找到用户 {username}")
        return

    # 生成设备履历
    print(f"\n开始生成 100 条设备履历...")
    resume_count = 100
    event_count = 0

    start_time = time.time()

    for i in range(1, resume_count + 1):
        # 创建设备履历
        device = create_device_resume(user, account_name, i)

        # 创建事件
        events = create_device_events(device, user)
        event_count += len(events)

        # 每50条输出进度
        if i % 50 == 0:
            elapsed = time.time() - start_time
            speed = i / elapsed if elapsed > 0 else 0
            print(f"  进度: {i}/{resume_count} ({i*100//resume_count}%) | "
                  f"事件数: {event_count} | "
                  f"速度: {speed:.2f} 条/秒")

    elapsed = time.time() - start_time
    print(f"\n✓ 账号 {username} 完成!")
    print(f"  设备履历: {resume_count} 条")
    print(f"  事件总数: {event_count} 条")
    print(f"  平均事件数/设备: {event_count/resume_count:.0f} 条")
    print(f"  耗时: {elapsed:.2f} 秒")
    print(f"  速度: {resume_count/elapsed:.2f} 条/秒")


def main():
    """主函数"""
    print(f"\n{'='*60}")
    print("设备履历数据生成脚本")
    print(f"{'='*60}")
    print(f"\n配置:")
    print(f"  - 账号数量: {len(ACCOUNTS)}")
    print(f"  - 每账号设备履历: 100 条")
    print(f"  - 每履历事件数: 600 条")
    print(f"  - 总设备履历数: {len(ACCOUNTS) * 100} 条")
    print(f"  - 总事件数: {len(ACCOUNTS) * 100 * 600} 条")
    print(f"  - 事件类型: {EVENT_TYPES} (平均分配)")

    total_start = time.time()

    for account_info in ACCOUNTS:
        generate_data_for_account(account_info)

    total_elapsed = time.time() - total_start

    print(f"\n{'='*60}")
    print("全部完成!")
    print(f"{'='*60}")
    print(f"  总耗时: {total_elapsed:.2f} 秒 ({total_elapsed/60:.2f} 分钟)")
    print(f"  总设备履历: {len(ACCOUNTS) * 100} 条")
    print(f"  总事件数: {len(ACCOUNTS) * 100 * 600} 条")
    print(f"  平均速度: {(len(ACCOUNTS) * 100) / total_elapsed:.2f} 条/秒")


if __name__ == '__main__':
    main()

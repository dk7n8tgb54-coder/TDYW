#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
为通信科账号生成5万条干扰记录测试数据
"""
"""docker exec tdyw python3 /data/spug/spug_api/generate_interference_data_tongxinke.py"""
import django
import os
import sys
import random
from datetime import datetime, timedelta

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

# 初始化Django
django.setup()

from apps.interference.models import Interference
from apps.account.models import User

# 通信科账号信息
USERNAME = 'tongxinke'
PASSWORD = 'Dt@6299093'

# 测试数据
FREQUENCIES = ["118.1", "118.45", "121.6", "121.5", "119.875", "119.15"]
REPORT_DEPTS = ["塔台", "进近", "运控"]
INTERFERENCE_TYPES = ["调频广播干扰", "航空电台干扰", "雷达干扰", "导航台干扰", "其他干扰"]
PHENOMENA = [
    "通信质量下降，有杂音",
    "信号不稳定，时断时续",
    "严重干扰，无法正常通信",
    "频率偏移，干扰正常频道",
    "背景噪声大，影响通信",
    "间歇性干扰，持续时间短",
    "强干扰源，范围广"
]
FLIGHT_NUMBERS = ["CA1234", "MU5678", "CZ3456", "ZH7890", "3U1111", "EU2222", "HO3333", "MF4444"]
AIRCRAFT_TYPES = ["A320", "B737", "A330", "B777", "A350", "B787", "A321", "B738"]
COORDINATES = [
    "116.404, 39.915",  # 北京
    "121.474, 31.230",  # 上海
    "113.264, 23.129",  # 广州
    "114.058, 22.543",  # 深圳
    "104.066, 30.573",  # 成都
    "108.940, 34.341",  # 西安
    "120.153, 30.287",  # 杭州
    "118.778, 32.057",  # 南京
]


def generate_random_data(total_count=50000):
    """生成随机数据，时间均匀分配到过去5年"""

    print(f"开始生成 {total_count} 条干扰记录数据...")
    print(f"频率选项: {FREQUENCIES}")
    print(f"汇报科室: {REPORT_DEPTS}")
    print(f"时间范围: 过去5年均匀分配")

    # 获取通信科用户
    try:
        user = User.objects.get(username=USERNAME)
        print(f"找到用户: {user.username} (租户ID: {user.tenant_id})")
    except User.DoesNotExist:
        print(f"错误: 用户 '{USERNAME}' 不存在")
        sys.exit(1)

    # 计算时间范围：过去5年
    now = datetime.now()
    total_days = 365 * 5  # 5年
    start_date = now - timedelta(days=total_days)

    # 计算每天需要生成多少条记录
    records_per_day = total_count // total_days
    remainder = total_count % total_days  # 余数

    created_count = 0
    failed_count = 0

    # 生成数据
    for day_offset in range(total_days):
        # 计算当前日期
        current_date = start_date + timedelta(days=day_offset)

        # 计算当天需要生成的记录数（处理余数）
        daily_count = records_per_day + (1 if day_offset < remainder else 0)

        if daily_count == 0:
            continue

        # 批量创建当天数据
        batch_records = []
        for i in range(daily_count):
            # 随机生成时间（当天的0-23小时）
            random_hours = random.randint(0, 23)
            random_minutes = random.randint(0, 59)
            random_seconds = random.randint(0, 59)
            datetime_str = current_date.replace(
                hour=random_hours,
                minute=random_minutes,
                second=random_seconds
            ).strftime('%Y-%m-%d %H:%M:%S')

            # 生成序号：使用日编号+每日递增，确保在Integer范围内且唯一
            # Integer最大值: 2147483647
            # 序号格式: 年份(2位)*365 + 天偏移量 + 每日递增
            year_offset = day_offset // 365  # 年份偏移（0-4）
            day_offset_in_year = day_offset % 365  # 当年第几天（0-364）
            base_serial = year_offset * 3650000 + day_offset_in_year * 10000 + i
            serial_number = base_serial

            # 随机选择数据
            record = Interference(
                tenant_id=user.tenant_id,
                serial_number=serial_number,
                frequency=random.choice(FREQUENCIES),
                report_dept=random.choice(REPORT_DEPTS),
                datetime=datetime_str,
                coordinates=random.choice(COORDINATES),
                interference_type=random.choice(INTERFERENCE_TYPES),
                phenomenon=random.choice(PHENOMENA),
                is_reported=random.choice(["是", "否"]),
                created_by=user,
                created_at=datetime_str
            )

            # 随机添加航班信息（20%概率）
            if random.random() < 0.2:
                record.flight_number = random.choice(FLIGHT_NUMBERS)
                record.aircraft_type = random.choice(AIRCRAFT_TYPES)

            batch_records.append(record)

        # 批量插入数据库
        try:
            Interference.objects.bulk_create(batch_records, batch_size=500)
            created_count += len(batch_records)

            # 显示进度
            progress = (day_offset + 1) / total_days * 100
            print(f"\r进度: {progress:.2f}% | 已创建: {created_count} 条", end='', flush=True)

        except Exception as e:
            failed_count += len(batch_records)
            print(f"\n错误: 第 {day_offset + 1} 天数据插入失败: {e}")

    print(f"\n\n生成完成！")
    print(f"成功创建: {created_count} 条")
    print(f"失败: {failed_count} 条")

    # 显示统计信息
    total_in_db = Interference.objects.filter(tenant_id=user.tenant_id).count()
    print(f"\n数据库中通信科干扰记录总数: {total_in_db}")


if __name__ == '__main__':
    generate_random_data(total_count=50000)

# -*- coding: utf-8 -*-
"""
测试数据填充脚本：给运行日志、设备履历、干扰管理、系统升级、故障管理、值班日志各插 50 条。

用法（在 spug_api 目录下，Docker 容器内执行）：
    python seed_data.py

幂等：每次先删除带 TEST_SEED_ 前缀的旧数据，再插入，可重复运行。
"""
import os
import sys
import random
from datetime import datetime, timedelta

# Django 环境初始化（settings 模块为 spug.settings，需把 spug_api 目录加入 path）
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from apps.account.models import User
from apps.runlog.models import RunLog
from apps.device.models import DeviceResume
from apps.interference.models import Interference
from apps.upgrade.models import UpgradeRecord
from apps.fault.models import FaultRecord
from apps.duty.models import DutyRecord

BATCH = 50
PREFIX = 'TEST_SEED_'

# 优先选 tongxinke 租户（实际业务租户），回退到第一个用户
user = (User.objects.filter(tenant_id='tongxinke', is_active=True).first()
        or User.objects.filter(is_active=True).first()
        or User.objects.first())
if not user:
    print('[ERROR] 系统无用户，无法创建数据')
    sys.exit(1)
TENANT_ID = user.tenant_id or 'admin'
print('[INFO] 使用用户: %s (id=%s, tenant_id=%s)' % (user.username, user.id, TENANT_ID))

# 清理其他租户残留的测试数据（避免脏数据）
def cleanup_other_tenant_test_data():
    """删除非当前租户的 TEST_SEED_ 测试数据"""
    models_and_fields = [
        (RunLog, 'event_title'),
        (DeviceResume, 'device_sn'),
        (Interference, 'frequency'),
        (UpgradeRecord, 'upgrade_no'),
        (FaultRecord, 'system_name'),
        (DutyRecord, 'duty_person'),
    ]
    for model, field in models_and_fields:
        kw = {'%s__startswith' % field: PREFIX, 'tenant_id__ne': TENANT_ID}
        # Django 没有 __ne，用 exclude
        old = model.objects.filter(**{'%s__startswith' % field: PREFIX}).exclude(tenant_id=TENANT_ID)
        n = old.count()
        if n:
            old.delete()
            print('[cleanup] 删除其他租户 %s 测试数据 %d 条' % (model.__name__, n))


def fmt(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def fmt_date(dt):
    return dt.strftime('%Y-%m-%d')


def rand_dt(days_back_max=30):
    """生成最近 N 天内的随机时间字符串"""
    delta = timedelta(days=random.randint(0, days_back_max),
                      hours=random.randint(0, 23),
                      minutes=random.randint(0, 59),
                      seconds=random.randint(0, 59))
    return fmt(datetime.now() - delta)


def rand_date(days_back_max=60):
    return fmt_date(datetime.now() - timedelta(days=random.randint(0, days_back_max)))


# ============ 1. 运行日志 ============
def seed_runlog():
    old = RunLog.objects.filter(event_title__startswith=PREFIX)
    n = old.count()
    old.delete()
    print('[runlog] 删除旧测试数据 %d 条' % n)

    event_types = ['运行异常', '设备故障', '安全事件', '其他']
    severities = ['P0', 'P1', 'P2']
    statuses = ['in_progress', 'resolved']
    systems = ['雷达系统', '通信系统', '导航系统', '气象系统', '供电系统']
    names = ['张三', '李四', '王五', '赵六', '钱七']

    objs = []
    for i in range(BATCH):
        objs.append(RunLog(
            tenant_id=TENANT_ID,
            event_title='%s运行日志事件_%04d' % (PREFIX, i + 1),
            event_type=random.choice(event_types),
            system_name=random.choice(systems),
            severity=random.choice(severities),
            status=random.choice(statuses),
            responsible_user_name=random.choice(names),
            created_by=user,
        ))
    RunLog.objects.bulk_create(objs)
    print('[runlog] 插入 %d 条' % len(objs))


# ============ 2. 设备履历 ============
def seed_device():
    old = DeviceResume.objects.filter(device_sn__startswith=PREFIX)
    n = old.count()
    old.delete()
    print('[device] 删除旧测试数据 %d 条' % n)

    models = ['型号A', '型号B', '型号C', '型号D']
    statuses = ['1', '2', '3', '4', '5']
    units = ['第一分队', '第二分队', '第三分队', '技术保障队']
    makers = ['某某厂', '某研究所', '某公司']

    objs = []
    for i in range(BATCH):
        install = rand_date(365)
        enable = rand_date(300)
        objs.append(DeviceResume(
            tenant_id=TENANT_ID,
            device_sn='%sDEV%04d' % (PREFIX, i + 1),
            device_name='%s设备_%04d' % (PREFIX, i + 1),
            device_model=random.choice(models),
            frequency='%d.%d MHz' % (random.randint(100, 400), random.randint(0, 9)),
            call_sign='CALL%04d' % (i + 1),
            install_location='机房%d号位' % random.randint(1, 10),
            manufacturer=random.choice(makers),
            install_unit=random.choice(units),
            use_unit=random.choice(units),
            install_time=install,
            enable_time=enable,
            current_status=random.choice(statuses),
            responsible_user_name='负责人%d' % random.randint(1, 5),
            created_by=user,
        ))
    DeviceResume.objects.bulk_create(objs)
    print('[device] 插入 %d 条' % len(objs))


# ============ 3. 干扰管理 ============
def seed_interference():
    old = Interference.objects.filter(frequency__startswith=PREFIX)
    n = old.count()
    old.delete()
    print('[interference] 删除旧测试数据 %d 条' % n)

    depts = ['塔台', '进近', '区管', '气象科', '通导科']
    types = ['电磁干扰', '信号干扰', '设备干扰', '其他']
    max_id = Interference.objects.order_by('-serial_number').first()
    start_sn = (max_id.serial_number + 1) if max_id else 1

    objs = []
    for i in range(BATCH):
        objs.append(Interference(
            tenant_id=TENANT_ID,
            serial_number=start_sn + i,
            frequency='%s%d.%d MHz' % (PREFIX, random.randint(100, 400), random.randint(0, 9)),
            report_dept=random.choice(depts),
            datetime=rand_dt(30),
            coordinates='%.4f,%.4f' % (random.uniform(100, 120), random.uniform(20, 40)),
            interference_type=random.choice(types),
            phenomenon='%s干扰现象描述_%04d：测得异常信号，已记录并上报。' % (PREFIX, i + 1),
            flight_number='CA%04d' % random.randint(1000, 9999),
            aircraft_type=random.choice(['B737', 'A320', 'B777', 'A330']),
            is_reported=random.choice(['是', '否']),
            created_by=user,
        ))
    Interference.objects.bulk_create(objs)
    print('[interference] 插入 %d 条' % len(objs))


# ============ 4. 系统升级管理 ============
def seed_upgrade():
    old = UpgradeRecord.objects.filter(upgrade_no__startswith=PREFIX)
    n = old.count()
    old.delete()
    print('[upgrade] 删除旧测试数据 %d 条' % n)

    systems = ['雷达系统', '通信系统', '导航系统', '气象系统', '供电系统']
    types = ['例行升级', '紧急升级', '版本回退', '补丁更新']
    statuses = ['处理中', '已完成', '已回退']
    owners = ['张三', '李四', '王五', '赵六']

    objs = []
    for i in range(BATCH):
        objs.append(UpgradeRecord(
            tenant_id=TENANT_ID,
            upgrade_no='%sUPG%04d' % (PREFIX, i + 1),
            system=random.choice(systems),
            upgrade_type=random.choice(types),
            version='v%d.%d.%d' % (random.randint(1, 3), random.randint(0, 9), random.randint(0, 9)),
            upgrade_time=rand_dt(60),
            status=random.choice(statuses),
            owner=random.choice(owners),
            created_at=rand_dt(60),
            created_by=user,
        ))
    UpgradeRecord.objects.bulk_create(objs)
    print('[upgrade] 插入 %d 条' % len(objs))


# ============ 5. 故障管理 ============
def seed_fault():
    old = FaultRecord.objects.filter(system_name__startswith=PREFIX)
    n = old.count()
    old.delete()
    print('[fault] 删除旧测试数据 %d 条' % n)

    systems = ['雷达系统', '通信系统', '导航系统', '气象系统', '供电系统']
    levels = ['一级', '二级', '三级', '四级']
    names = ['张三', '李四', '王五', '赵六', '钱七']

    objs = []
    for i in range(BATCH):
        objs.append(FaultRecord(
            tenant_id=TENANT_ID,
            system_name='%s%s_%04d' % (PREFIX, random.choice(systems), i + 1),
            device_code='DEV%04d' % random.randint(1000, 9999),
            fault_date=rand_date(90),
            handler=random.choice(names),
            recorder=random.choice(names),
            fault_level=random.choice(levels),
            fault_phenomenon='%s故障现象描述_%04d：设备出现异常告警，经排查确认故障部位。' % (PREFIX, i + 1),
            handling_process='%s处理过程_%04d：隔离故障 → 更换备件 → 测试验证 → 恢复运行。' % (PREFIX, i + 1),
            created_by=user,
        ))
    FaultRecord.objects.bulk_create(objs)
    print('[fault] 插入 %d 条' % len(objs))


# ============ 6. 值班日志 ============
def seed_duty():
    old = DutyRecord.objects.filter(duty_person__startswith=PREFIX)
    n = old.count()
    old.delete()
    print('[duty] 删除旧测试数据 %d 条' % n)

    depts = ['塔台', '进近', '区管', '气象科', '通导科']
    names = ['张三', '李四', '王五', '赵六', '钱七']
    situations = [
        '值班期间设备运行正常，无异常情况。',
        '夜间出现短暂告警，已复位恢复正常。',
        '完成日常巡检，各项指标正常。',
        '处理一起用户报障，已解决。',
        '天气转差，加强监控，未发现异常。',
    ]

    objs = []
    for i in range(BATCH):
        objs.append(DutyRecord(
            tenant_id=TENANT_ID,
            duty_person='%s值班员_%04d' % (PREFIX, i + 1),
            reporter=random.choice(names),
            department=random.choice(depts),
            duty_date=rand_date(30),
            duty_situation=random.choice(situations),
            created_by=user,
        ))
    DutyRecord.objects.bulk_create(objs)
    print('[duty] 插入 %d 条' % len(objs))


if __name__ == '__main__':
    random.seed(20260627)
    cleanup_other_tenant_test_data()
    seed_runlog()
    seed_device()
    seed_interference()
    seed_upgrade()
    seed_fault()
    seed_duty()
    print('[DONE] 全部完成')

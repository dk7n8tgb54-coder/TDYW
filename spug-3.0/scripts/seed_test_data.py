#!/usr/bin/env python
"""
为7个模块插入测试数据的独立脚本（通过 pymysql 直接连接 MySQL）。
由于 Django 2.2 与 Python 3.14 不兼容，绕过 Django ORM 直接操作数据库。

插入数据的模块：
  1. 检查单 (checksheet)       - 部门值班日检查单
  2. 运行日志 (runlog)          - 运行日志
  3. 设备管理 (device)          - 设备档案 + 设备事件
  4. 干扰管理 (interference)    - 干扰记录
  5. 系统升级 (upgrade)         - 升级记录 + 模板 + 清单
  6. 值班日志 (duty)            - 值班日志
  7. 故障管理 (fault)           - 故障记录 + 故障件

用法:
    python scripts/seed_test_data.py
"""

import json
import random
from datetime import datetime, timedelta

import pymysql

# ===================== 数据库配置 =====================
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3307,
    'user': 'spug',
    'password': 'spug.cc',
    'database': 'spug',
    'charset': 'utf8mb4',
}

# ===================== 工具函数 =====================


def random_datetime(days_ago=30):
    """生成过去 N 天内的一个随机时间字符串 YYYY-MM-DD HH:MM:SS"""
    now = datetime.now()
    delta = timedelta(
        days=random.randint(0, days_ago),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
        seconds=random.randint(0, 59),
    )
    return (now - delta).strftime('%Y-%m-%d %H:%M:%S')


def random_date(days_ago=30):
    """生成过去 N 天内的一个随机日期字符串 YYYY-MM-DD"""
    now = datetime.now()
    delta = timedelta(days=random.randint(0, days_ago))
    return (now - delta).strftime('%Y-%m-%d')


def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ===================== 各模块种子函数 =====================


def seed_checksheet(cur, user_id, user_name, tenant_id):
    """1. 部门值班日检查单"""
    print('[检查单] 插入测试数据...')

    now = datetime.now()
    year = str(now.year)
    month = f'{now.month:02d}'

    # --- 模板 ---
    templates = [
        ('通信系统值班检查',
         ['通信设备运行状态', '备用电源状态', '环境温湿度', '告警信息检查', '日志记录完整性']),
        ('雷达系统值班检查',
         ['雷达天线运行状态', '信号处理单元状态', '冷却系统运行状态', '显示终端状态', '数据记录完整性']),
    ]

    tpl_ids = []
    for project, items in templates:
        items_json = json.dumps(items, ensure_ascii=False)
        cur.execute(
            'INSERT INTO tdyw_checksheet_template (project, check_items, created_at, updated_at) '
            'VALUES (%s, %s, %s, %s)',
            (project, items_json, now_str(), now_str()),
        )
        tpl_ids.append(cur.lastrowid)

    # --- 检查记录 ---
    status_choices = ['NORMAL', 'NORMAL', 'NORMAL', 'ABNORMAL', 'UNCHECKED']
    for tpl_id, (project, items) in zip(tpl_ids, templates):
        for day_offset in range(3):
            day = now.day - day_offset
            if day <= 0:
                continue
            for idx in range(len(items)):
                status = random.choice(status_choices)
                remark = f'自动测试数据 - {items[idx]}' if idx == 0 else ''
                rectification = '已处理，运行正常' if idx == 0 else ''
                cur.execute(
                    'INSERT INTO tdyw_checksheet_record '
                    '(template_id, year, month, day, item_index, status, remark, rectification, operator, created_at, updated_at) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                    (tpl_id, year, month, day, idx, status, remark, rectification, user_name, now_str(), now_str()),
                )

    # --- 每日汇总 ---
    for day_offset in range(3):
        day = now.day - day_offset
        if day <= 0:
            continue
        cur.execute(
            'INSERT INTO tdyw_checksheet_daily_summary '
            '(year, month, day, operator, remark, rectification, created_at, updated_at) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            (year, month, day, user_name,
             f'{year}-{month}-{day} 值班情况正常，无异常事件。',
             '', now_str(), now_str()),
        )

    print(f'  ✓ 模板 {len(tpl_ids)} 个, 记录 + 汇总已插入')


def seed_runlog(cur, user_id, user_name, tenant_id):
    """2. 运行日志"""
    print('[运行日志] 插入测试数据...')

    events = [
        {
            'title': '核心路由器CPU负载过高告警',
            'type': '运行异常',
            'system': '核心路由系统',
            'severity': 'P1',
            'status': 'in_progress',
        },
        {
            'title': '数据库主从同步延迟异常',
            'type': '运行异常',
            'system': '数据库集群',
            'severity': 'P1',
            'status': 'resolved',
            'resolution': '优化主从复制参数，调整binlog过期时间，同步恢复正常。',
        },
        {
            'title': '安全扫描发现高危漏洞',
            'type': '安全事件',
            'system': 'Web应用防火墙',
            'severity': 'P0',
            'status': 'in_progress',
        },
    ]

    updates_content = [
        '正在进行排查，已定位到问题模块...',
        '已联系厂商技术支持，获取修复方案...',
        '正在执行修复操作，预计需要30分钟...',
        '修复完成，正在进行验证测试...',
        '验证通过，系统恢复正常运行。',
    ]

    for evt in events:
        created_at = random_datetime(15)
        closed_at = random_datetime(10) if evt['status'] == 'resolved' else ''
        verified_at = random_datetime(10) if evt['status'] == 'resolved' else ''

        cur.execute(
            'INSERT INTO tdyw_run_logs '
            '(tenant_id, event_title, event_type, system_name, severity, status, '
            'responsible_user_id, responsible_user_name, resolution, '
            'verifier_id, verifier_name, verified_at, closed_at, '
            'update_count, first_update_date, last_update_date, '
            'created_at, created_by_id, updated_at, updated_by_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, '
            '%s, %s, %s, '
            '%s, %s, %s, %s, '
            '0, NULL, NULL, '
            '%s, %s, %s, %s)',
            (tenant_id, evt['title'], evt['type'], evt['system'], evt['severity'], evt['status'],
             user_id, user_name, evt.get('resolution', ''),
             user_id if verified_at else None, user_name if verified_at else '', verified_at, closed_at,
             created_at, user_id, None, None),
        )
        runlog_id = cur.lastrowid

        # 添加1-3条动态
        num_updates = random.randint(1, 3)
        base_date = datetime.strptime(created_at[:10], '%Y-%m-%d')
        first_update = None
        last_update = None

        for i in range(num_updates):
            update_date = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
            if first_update is None:
                first_update = update_date
            last_update = update_date

            detail = random.choice(updates_content)
            editable_until = (datetime.strptime(update_date, '%Y-%m-%d') + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')

            cur.execute(
                'INSERT INTO tdyw_run_log_updates '
                '(tenant_id, runlog_id, event_title, update_date, sequence, recorder, '
                'detail_content, attachments, editable_until, created_at, created_by_id) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                (tenant_id, runlog_id, evt['title'], update_date, i, user_name,
                 detail, '[]', editable_until, now_str(), user_id),
            )

        # 更新统计字段
        cur.execute(
            'UPDATE tdyw_run_logs SET update_count=%s, first_update_date=%s, last_update_date=%s WHERE id=%s',
            (num_updates, first_update, last_update, runlog_id),
        )

    print(f'  ✓ 运行日志 3 条 + 动态若干')


def seed_device(cur, user_id, user_name, tenant_id):
    """3. 设备管理"""
    print('[设备管理] 插入测试数据...')

    devices = [
        {
            'device_sn': 'TZ-RX-2024-001',
            'device_name': 'Ku波段接收机',
            'device_model': 'KuRX-3200',
            'frequency': '12.25-12.75GHz',
            'call_sign': 'B7X-01',
            'install_location': '主站机房A区-01号机柜',
            'geo_coordinate': '116.397,39.908',
            'device_purpose': '接收Ku波段卫星信号',
            'manufacturer': '华通科技',
            'install_unit': '技术保障部',
            'use_unit': '通信室',
            'install_time': '2024-01-15',
            'enable_time': '2024-02-01',
            'current_status': '1',
        },
        {
            'device_sn': 'TZ-TX-2024-002',
            'device_name': 'C波段发射机',
            'device_model': 'CTX-5000',
            'frequency': '5.85-6.45GHz',
            'call_sign': 'B7X-02',
            'install_location': '主站机房B区-03号机柜',
            'geo_coordinate': '116.398,39.909',
            'device_purpose': '发射C波段上行信号',
            'manufacturer': '华通科技',
            'install_unit': '技术保障部',
            'use_unit': '通信室',
            'install_time': '2023-06-20',
            'enable_time': '2023-07-01',
            'current_status': '2',
        },
        {
            'device_sn': 'TZ-PS-2024-003',
            'device_name': '备用发电机',
            'device_model': 'DieselGen-2000',
            'frequency': '50Hz',
            'install_location': '动力机房',
            'device_purpose': '市电中断时提供应急电力保障',
            'manufacturer': '电力设备集团',
            'install_unit': '动力保障科',
            'use_unit': '动力保障科',
            'install_time': '2024-03-10',
            'enable_time': '2024-03-15',
            'current_status': '3',
        },
    ]

    event_types_map = {1: '重大故障维修', 2: '设备更新', 3: '设备检修'}
    event_titles_map = {
        1: ['电源模块故障维修', '功放模块更换'],
        2: ['固件版本升级', '设备参数调整'],
        3: ['季度例行检修', '年度设备检修'],
    }

    for dev in devices:
        created_at = random_datetime(30)
        cur.execute(
            'INSERT INTO tdyw_device_resume '
            '(tenant_id, device_sn, device_name, device_model, frequency, call_sign, '
            'install_location, geo_coordinate, device_purpose, manufacturer, '
            'install_unit, use_unit, install_time, enable_time, current_status, '
            'responsible_user_id, responsible_user_name, remark, is_deleted, '
            'created_at, created_by_id, updated_at, updated_by_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, '
            '%s, %s, %s, %s, '
            '%s, %s, %s, %s, %s, '
            '%s, %s, %s, 0, '
            '%s, %s, %s, %s)',
            (tenant_id, dev['device_sn'], dev['device_name'], dev['device_model'],
             dev.get('frequency', ''), dev.get('call_sign', ''),
             dev['install_location'], dev.get('geo_coordinate', ''),
             dev.get('device_purpose', ''), dev['manufacturer'],
             dev['install_unit'], dev['use_unit'],
             dev['install_time'], dev['enable_time'], dev['current_status'],
             user_id, user_name, '测试数据',
             created_at, user_id, None, None),
        )
        device_id = cur.lastrowid

        # 为每台设备添加1-2条事件
        num_events = random.randint(1, 2)
        for _ in range(num_events):
            et = random.choice(list(event_types_map.keys()))
            title = random.choice(event_titles_map[et])
            event_time = random_date(90)
            cur.execute(
                'INSERT INTO tdyw_device_event '
                '(tenant_id, device_resume_id, device_name, device_sn, event_type, event_time, event_title, '
                'fault_part, fault_phenomenon_cause, maintenance_measures, '
                'related_user_id, related_user_name, repair_time, remark, is_deleted, created_at, created_by_id) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, '
                '%s, %s, %s, '
                '%s, %s, %s, %s, 0, %s, %s)',
                (tenant_id, device_id, dev['device_name'], dev['device_sn'], et, event_time,
                 f'{title}({dev["device_name"]})',
                 '电源模块' if et == 1 else '',
                 '电压异常导致模块损坏' if et == 1 else '',
                 '更换故障模块，测试正常' if et == 1 else '',
                 user_id, user_name,
                 random_datetime(30) if et == 1 else '',
                 '自动测试数据',
                 random_datetime(30), user_id),
            )

    print(f'  ✓ 设备 3 条 + 事件若干')


def seed_interference(cur, user_id, user_name, tenant_id):
    """4. 干扰管理"""
    print('[干扰管理] 插入测试数据...')

    records = [
        ('128.500MHz', '航管中心', 'N40°03\'24", E116°35\'48"', '同频干扰',
         '航管频率128.500MHz出现持续噪声干扰，影响地空通信质量。', 'CA1234', 'B737-800', '是'),
        ('132.050MHz', '进近管制室', 'N39°58\'12", E116°22\'36"', '互调干扰',
         '进近频率132.050MHz存在间歇性互调干扰，偶发信号丢失。', '', '', '否'),
        ('118.100MHz', '塔台管制室', 'N40°04\'48", E116°35\'12"', '其他干扰',
         '塔台频率118.100MHz受不明信号干扰，已排查周边电磁环境。', 'MU5678', 'A320', '是'),
    ]

    for i, (freq, dept, coord, itype, phenom, flight, ac, reported) in enumerate(records):
        cur.execute(
            'INSERT INTO tdyw_interferences '
            '(tenant_id, serial_number, frequency, report_dept, datetime, coordinates, '
            'interference_type, phenomenon, flight_number, aircraft_type, is_reported, '
            'created_at, created_by_id, updated_at, updated_by_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (tenant_id, i + 1, freq, dept, random_datetime(60), coord,
             itype, phenom, flight, ac, reported,
             random_datetime(60), user_id, None, None),
        )

    print(f'  ✓ 干扰记录 3 条')


def seed_upgrade(cur, user_id, user_name, tenant_id):
    """5. 系统升级管理"""
    print('[系统升级] 插入测试数据...')

    now = now_str()

    # --- 模板 ---
    cur.execute(
        'INSERT INTO tdyw_upgrade_templates '
        '(tenant_id, name, system, upgrade_type, version, owner, status, detail_content, '
        'is_default, created_at, created_by_id, updated_at) '
        'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
        (tenant_id, '标准升级模板', '通信系统', '常规升级', 'v2.0.0', user_name,
         '处理中', '用于常规系统升级的预设模板', 1, now, user_id, None),
    )

    # --- 步骤清单 ---
    cur.execute(
        'INSERT INTO tdyw_upgrade_checklists '
        '(tenant_id, name, description, is_default, created_at, created_by_id, updated_at) '
        'VALUES (%s, %s, %s, %s, %s, %s, %s)',
        (tenant_id, '标准升级步骤清单', '适用于常规系统升级的标准步骤清单', 1, now, user_id, None),
    )
    checklist_id = cur.lastrowid

    step_titles = [
        '备份当前系统配置',
        '下载升级包并校验完整性',
        '停止相关服务',
        '执行升级脚本',
        '验证升级结果',
        '恢复服务并监控运行状态',
    ]
    for seq, title in enumerate(step_titles):
        cur.execute(
            'INSERT INTO tdyw_upgrade_checklist_steps '
            '(tenant_id, checklist_id, title, description, sequence, is_required, created_at) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s)',
            (tenant_id, checklist_id, title, f'自动执行: {title}', seq, 1, now),
        )

    # --- 升级记录 ---
    upgrades = [
        ('UPG-2025-001', '通信交换系统', '安全补丁', 'v3.1.2', '已完成'),
        ('UPG-2025-002', '数据存储系统', '常规升级', 'v5.0.0', '处理中'),
    ]

    for upg_no, system, utype, version, status in upgrades:
        upgrade_time = random_datetime(30)
        cur.execute(
            'INSERT INTO tdyw_upgrade_records '
            '(tenant_id, upgrade_no, system, upgrade_type, version, upgrade_time, status, owner, '
            'created_at, created_by_id, updated_at, updated_by_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (tenant_id, upg_no, system, utype, version, upgrade_time[:16], status, user_name,
             upgrade_time, user_id, None, None),
        )
        rec_id = cur.lastrowid

        for seq, title in enumerate(step_titles):
            step_status = 'completed' if status == '已完成' else random.choice(['completed', 'pending'])
            completed_by = user_name if step_status == 'completed' else ''
            completed_at = upgrade_time if step_status == 'completed' else ''
            cur.execute(
                'INSERT INTO tdyw_upgrade_record_steps '
                '(tenant_id, upgrade_id, checklist_id, title, description, sequence, is_required, '
                'status, completed_by, completed_at, remark, created_at) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                (tenant_id, rec_id, checklist_id, title, f'执行: {title}', seq, 1,
                 step_status, completed_by, completed_at, '', upgrade_time),
            )

    print(f'  ✓ 升级记录 2 条 + 模板/清单各 1 个')


def seed_duty(cur, user_id, user_name, tenant_id):
    """6. 值班日志"""
    print('[值班日志] 插入测试数据...')

    now = datetime.now()
    records = [
        (user_name, user_name, '通信室',
         (now - timedelta(days=0)).strftime('%Y-%m-%d'),
         '今日值班情况正常，所有通信设备运行稳定，无告警事件发生。完成了日常巡检工作，设备状态良好。'),
        (user_name, user_name, '通信室',
         (now - timedelta(days=1)).strftime('%Y-%m-%d'),
         '凌晨3点出现一次短暂网络中断，约5分钟后自动恢复，已记录日志并上报。其余时段运行正常。'),
        ('张三', '李四', '雷达室',
         (now - timedelta(days=2)).strftime('%Y-%m-%d'),
         '雷达系统运行正常，完成了例行数据备份。与气象部门协调了数据共享事宜。'),
    ]

    for person, reporter, dept, date, situation in records:
        cur.execute(
            'INSERT INTO tdyw_duty_records '
            '(tenant_id, duty_person, reporter, department, duty_date, duty_situation, '
            'created_at, created_by_id, updated_at, updated_by_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (tenant_id, person, reporter, dept, date, situation,
             random_datetime(3), user_id, None, None),
        )

    print(f'  ✓ 值班日志 3 条')


def seed_fault(cur, user_id, user_name, tenant_id):
    """7. 故障管理"""
    print('[故障管理] 插入测试数据...')

    faults = [
        ('通信交换系统', 'SW-2024-001', '一级故障',
         '通信交换系统主控板故障，导致部分用户无法正常通话，影响约200用户。',
         '1. 立即切换至备用主控板\n2. 检查故障主控板日志\n3. 发现内存错误，联系厂家更换\n4. 更换后测试正常，恢复主用'),
        ('雷达监控系统', 'RD-MON-002', '二级故障',
         '雷达监控终端画面卡顿，数据刷新延迟约30秒。',
         '1. 检查网络连接状态\n2. 重启监控终端服务\n3. 清理系统缓存\n4. 恢复正常运行'),
    ]

    for sys_name, dev_code, level, phenomenon, process in faults:
        fault_date = random_date(60)
        cur.execute(
            'INSERT INTO tdyw_fault_records '
            '(tenant_id, system_name, device_code, fault_date, handler, recorder, '
            'fault_level, fault_phenomenon, handling_process, '
            'created_at, created_by_id, updated_at, updated_by_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (tenant_id, sys_name, dev_code, fault_date, user_name, user_name,
             level, phenomenon, process,
             random_datetime(60), user_id, None, None),
        )

    # 故障件
    parts = [
        ('主控板-FPGA芯片', '通信交换系统', random_date(90), random_date(95), '已送修',
         random_date(85), '', ''),
        ('电源模块-PSM-200', '通信交换系统', random_date(60), random_date(65), '已归档',
         random_date(55), random_date(40), random_date(30)),
    ]

    for name, sys_name, date, fault_date, status, sent_date, test_date, archive_date in parts:
        cur.execute(
            'INSERT INTO tdyw_fault_parts '
            '(tenant_id, name, system_name, date, fault_date, status, '
            'fault_sent_date, test_return_date, archive_date, '
            'created_at, created_by_id, updated_at, updated_by_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (tenant_id, name, sys_name, date, fault_date, status,
             sent_date, test_date, archive_date,
             random_datetime(60), user_id, None, None),
        )

    print(f'  ✓ 故障记录 2 条 + 故障件 2 条')


# ===================== 主流程 =====================

def main():
    print('=' * 50)
    print('  开始插入测试数据...')
    print(f'  时间: {now_str()}')
    print('=' * 50)

    conn = pymysql.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()

        # 获取用户信息
        cur.execute('SELECT id, nickname FROM users WHERE username = %s', ('admin',))
        row = cur.fetchone()
        if not row:
            print('ERROR: 用户 admin 不存在！')
            return
        user_id, user_name = row
        tenant_id = 'admin'

        print(f'[用户] 使用: {user_name} (id={user_id})\n')

        # 按模块依次插入
        seed_checksheet(cur, user_id, user_name, tenant_id)
        seed_runlog(cur, user_id, user_name, tenant_id)
        seed_device(cur, user_id, user_name, tenant_id)
        seed_interference(cur, user_id, user_name, tenant_id)
        seed_upgrade(cur, user_id, user_name, tenant_id)
        seed_duty(cur, user_id, user_name, tenant_id)
        seed_fault(cur, user_id, user_name, tenant_id)

        conn.commit()
        print('\n' + '=' * 50)
        print('  ✅ 所有测试数据插入完成!')
        print('=' * 50)
    except Exception as e:
        conn.rollback()
        print(f'\n❌ 错误: {e}')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()

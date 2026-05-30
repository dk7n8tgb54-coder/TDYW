#!/usr/bin/env python
"""验证各模块测试数据量"""
import pymysql

conn = pymysql.connect(host='127.0.0.1', port=3307, user='spug', password='spug.cc', database='spug', charset='utf8mb4')
cur = conn.cursor()

tables = [
    ('检查单-模板', 'tdyw_checksheet_template'),
    ('检查单-记录', 'tdyw_checksheet_record'),
    ('检查单-汇总', 'tdyw_checksheet_daily_summary'),
    ('运行日志', 'tdyw_run_logs'),
    ('运行日志-动态', 'tdyw_run_log_updates'),
    ('设备档案', 'tdyw_device_resume'),
    ('设备事件', 'tdyw_device_event'),
    ('干扰记录', 'tdyw_interferences'),
    ('升级记录', 'tdyw_upgrade_records'),
    ('升级模板', 'tdyw_upgrade_templates'),
    ('升级清单', 'tdyw_upgrade_checklists'),
    ('升级清单步骤', 'tdyw_upgrade_checklist_steps'),
    ('升级记录步骤', 'tdyw_upgrade_record_steps'),
    ('值班日志', 'tdyw_duty_records'),
    ('故障记录', 'tdyw_fault_records'),
    ('故障件', 'tdyw_fault_parts'),
]

print(f'{"模块":<18} {"表名":<30} {"数据量":>8}')
print('-' * 60)
for name, table in tables:
    cur.execute(f'SELECT COUNT(*) FROM {table}')
    count = cur.fetchone()[0]
    print(f'{name:<16} {table:<28} {count:>6} 条')

conn.close()

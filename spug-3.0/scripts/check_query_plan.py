#!/usr/bin/env python
"""检查查询执行计划"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from django.db import connection
from django.db.models import Count, Q
from datetime import datetime, timedelta
from apps.runlog.models import RunLog

def main():
    print("="*60)
    print("  统计接口执行计划分析")
    print("="*60)

    cursor = connection.cursor()

    # 模拟普通租户查询（不是超级管理员）
    print("\n模拟查询: tenant_id='admin'（普通租户）")

    # 查询1: 聚合统计
    print("\n" + "="*60)
    print("查询1: 聚合统计")
    print("="*60)

    sql1 = """
    SELECT
        COUNT(CASE WHEN status='in_progress' THEN 1 END) AS in_progress_count,
        COUNT(CASE WHEN status='resolved' THEN 1 END) AS resolved_count,
        COUNT(CASE WHEN severity='P0' THEN 1 END) AS p0_count,
        COUNT(CASE WHEN severity='P1' THEN 1 END) AS p1_count,
        COUNT(CASE WHEN severity='P2' THEN 1 END) AS p2_count
    FROM runlog_run_logs
    WHERE tenant_id='admin'
    """

    print(f"\nSQL:\n{sql1}")

    cursor.execute(f"EXPLAIN {sql1}")
    explain1 = cursor.fetchall()

    print("\n执行计划:")
    for row in explain1:
        print(f"  id: {row[0]}, select_type: {row[1]}, table: {row[2]}")
        print(f"  type: {row[3]}, key: {row[4]}, rows: {row[6]}")
        print(f"  Extra: {row[9]}")

    # 检查是否使用了索引
    if explain1[0][4]:
        print(f"\n✅ 使用了索引: {explain1[0][4]}")
    else:
        print(f"\n❌ 未使用索引，全表扫描！")

    print(f"\n预估扫描行数: {explain1[0][6]}")

    # 查询2: 日期分组统计
    print("\n" + "="*60)
    print("查询2: 日期分组统计")
    print("="*60)

    now = datetime.now()
    start_date = (now - timedelta(days=6)).strftime('%Y-%m-%d')

    sql2 = f"""
    SELECT DATE(created_at) AS day, COUNT(*) AS count
    FROM runlog_run_logs
    WHERE tenant_id='admin' AND created_at >= '{start_date} 00:00:00'
    GROUP BY DATE(created_at)
    """

    print(f"\nSQL:\n{sql2}")

    cursor.execute(f"EXPLAIN {sql2}")
    explain2 = cursor.fetchall()

    print("\n执行计划:")
    for row in explain2:
        print(f"  id: {row[0]}, select_type: {row[1]}, table: {row[2]}")
        print(f"  type: {row[3]}, key: {row[4]}, rows: {row[6]}")
        print(f"  Extra: {row[9]}")

    # 检查是否使用了索引
    if explain2[0][4]:
        print(f"\n✅ 使用了索引: {explain2[0][4]}")
    else:
        print(f"\n❌ 未使用索引，全表扫描！")

    print(f"\n预估扫描行数: {explain2[0][6]}")

    # 数据量统计
    print("\n" + "="*60)
    print("当前数据量")
    print("="*60)

    cursor.execute("SELECT COUNT(*) FROM runlog_run_logs")
    total = cursor.fetchone()[0]
    print(f"\n总记录数: {total}")

    cursor.execute("SELECT COUNT(*) FROM runlog_run_logs WHERE tenant_id='admin'")
    admin_count = cursor.fetchone()[0]
    print(f"admin租户记录数: {admin_count}")

    # 根本原因分析
    print("\n" + "="*60)
    print("问题分析")
    print("="*60)

    print("\n压测结果:")
    print("  - P95响应时间: 9500ms（统计接口）")
    print("  - 目标响应时间: <400ms")

    print("\n可能原因:")
    print("  1. 压测用户是否是超级管理员？")
    print("     - 如果是超级管理员，会查询全表而非单租户")
    print("  2. 索引是否真正生效？")
    print("     - 上述EXPLAIN结果显示是否使用了索引")
    print("  3. 数据量问题？")
    print("     - admin租户当前有 {} 条记录".format(admin_count))
    print("  4. 其他慢查询？")
    print("     - 列表接口的P95=8300ms也很慢，说明不只是统计接口的问题")

    print("\n建议检查:")
    print("  1. 检查压测脚本使用的用户权限")
    print("  2. 查看慢查询日志")
    print("  3. 检查Django ORM实际生成的SQL")

if __name__ == '__main__':
    main()

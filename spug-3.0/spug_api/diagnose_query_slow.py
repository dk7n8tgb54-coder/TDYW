#!/usr/bin/env python
"""诊断查询慢的原因"""
import os
import sys
import django
import time

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.runlog.models import RunLog
from apps.account.models import User
from libs.tenant_utils import apply_tenant_filter
from django.db.models import Count, Q
from django.db import connection
from datetime import datetime, timedelta

def diagnose_query():
    """诊断查询性能"""
    print("="*70)
    print("  运行日志查询性能诊断")
    print("="*70)

    # 获取tongxinke用户
    user = User.objects.filter(username='tongxinke').first()
    if not user:
        print("错误: tongxinke用户不存在")
        return

    print(f"\n测试用户: {user.username}")
    print(f"租户ID: {user.tenant_id}")
    print(f"是否超级管理员: {user.is_supper}")

    logs = apply_tenant_filter(RunLog.objects.all(), user)
    count = logs.count()
    print(f"数据量: {count} 条\n")

    # 测试1: 简单COUNT查询
    print("-" * 70)
    print("测试1: 简单COUNT查询")
    start = time.time()
    for i in range(10):
        _ = logs.count()
    elapsed = (time.time() - start) * 1000
    avg = elapsed / 10
    print(f"10次COUNT查询总时间: {elapsed:.2f}ms")
    print(f"平均每次: {avg:.2f}ms")

    # 测试2: 聚合查询（统计接口使用）
    print("\n" + "-" * 70)
    print("测试2: 聚合查询（模拟统计接口）")
    start = time.time()
    for i in range(10):
        agg_stats = logs.aggregate(
            in_progress_count=Count('id', filter=Q(status='in_progress')),
            resolved_count=Count('id', filter=Q(status='resolved')),
            p0_count=Count('id', filter=Q(severity='P0')),
            p1_count=Count('id', filter=Q(severity='P1')),
            p2_count=Count('id', filter=Q(severity='P2'))
        )
    elapsed = (time.time() - start) * 1000
    avg = elapsed / 10
    print(f"10次聚合查询总时间: {elapsed:.2f}ms")
    print(f"平均每次: {avg:.2f}ms")

    # 测试3: 列表查询（限制20条）
    print("\n" + "-" * 70)
    print("测试3: 列表查询（LIMIT 20）")
    start = time.time()
    for i in range(10):
        _ = list(logs.order_by('-created_at', '-id')[:20])
    elapsed = (time.time() - start) * 1000
    avg = elapsed / 10
    print(f"10次列表查询总时间: {elapsed:.2f}ms")
    print(f"平均每次: {avg:.2f}ms")

    # 测试4: to_dict()序列化
    print("\n" + "-" * 70)
    print("测试4: to_dict()序列化（20条记录）")
    start = time.time()
    for i in range(10):
        data = [x.to_dict() for x in logs.order_by('-created_at', '-id')[:20]]
    elapsed = (time.time() - start) * 1000
    avg = elapsed / 10
    print(f"10次序列化总时间: {elapsed:.2f}ms")
    print(f"平均每次: {avg:.2f}ms")

    # 测试5: to_view()完整转换
    print("\n" + "-" * 70)
    print("测试5: to_view()完整转换（20条记录）")
    start = time.time()
    for i in range(10):
        data = [x.to_view() for x in logs.order_by('-created_at', '-id')[:20]]
    elapsed = (time.time() - start) * 1000
    avg = elapsed / 10
    print(f"10次完整转换总时间: {elapsed:.2f}ms")
    print(f"平均每次: {avg:.2f}ms")

    # 测试6: 查看实际执行的SQL
    print("\n" + "-" * 70)
    print("测试6: 查看实际执行的SQL和执行计划")
    from django.db import reset_queries
    from django.conf import settings
    settings.DEBUG = True

    reset_queries()
    _ = logs.order_by('-created_at', '-id')[:20]
    queries = connection.queries

    print(f"\n执行的SQL数量: {len(queries)}")
    if queries:
        print("SQL语句:")
        for i, query in enumerate(queries[:3]):  # 只显示前3条
            print(f"\n查询 {i+1}:")
            print(f"  时间: {query['time']}s")
            print(f"  SQL: {query['sql'][:200]}...")

    settings.DEBUG = False

    print("\n" + "="*70)
    print("诊断总结")
    print("="*70)
    print("如果:")
    print("  - COUNT/聚合查询 > 100ms: 可能是索引问题")
    print("  - 列表查询 > 100ms: 可能是排序/索引问题")
    print("  - to_dict/to_view > 500ms: 可能是序列化问题")
    print("  - 所有操作都慢: 可能是网络/数据库连接问题")

if __name__ == '__main__':
    diagnose_query()

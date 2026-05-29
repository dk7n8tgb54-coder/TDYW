#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单次查询性能测试脚本
测试不同数据量下的单次查询耗时（非并发场景）
"""

import time
import statistics
import os
import sys
import django

# 设置Django环境
sys.path.insert(0, '/data/spug/spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.runlog.models import RunLog
from django.db.models import Count, Q


def time_query(name, query_func, iterations=10):
    """测量查询执行时间"""
    times = []
    results = []

    for i in range(iterations):
        start = time.perf_counter()
        result = query_func()
        end = time.perf_counter()
        times.append((end - start) * 1000)  # 转换为毫秒
        results.append(result)

    return {
        'name': name,
        'avg': statistics.mean(times),
        'min': min(times),
        'max': max(times),
        'p50': statistics.median(times),
        'p95': sorted(times)[int(len(times) * 0.95)] if len(times) >= 20 else max(times),
        'p99': sorted(times)[int(len(times) * 0.99)] if len(times) >= 100 else max(times),
    }


def test_single_queries():
    """测试单次查询性能"""

    # 获取当前数据量
    total_count = RunLog.objects.count()

    print(f"\n{'='*70}")
    print(f"单次查询性能测试（非并发场景）")
    print(f"当前数据量: {total_count} 条")
    print(f"{'='*70}\n")

    # 测试1：列表查询（分页）
    print("测试1: 列表查询（分页20条）")
    result = time_query(
        "列表查询",
        lambda: list(RunLog.objects.all().order_by('-created_at')[:20])
    )
    print(f"  平均: {result['avg']:.2f}ms, "
          f"P50: {result['p50']:.2f}ms, "
          f"P95: {result['p95']:.2f}ms, "
          f"P99: {result['p99']:.2f}ms")

    # 测试2：计数查询
    print("\n测试2: 计数查询")
    result = time_query(
        "计数查询",
        lambda: RunLog.objects.count()
    )
    print(f"  平均: {result['avg']:.2f}ms, "
          f"P50: {result['p50']:.2f}ms, "
          f"P95: {result['p95']:.2f}ms, "
          f"P99: {result['p99']:.2f}ms")

    # 测试3：统计聚合（状态和级别）
    print("\n测试3: 统计聚合（状态和级别）")
    result = time_query(
        "统计聚合",
        lambda: RunLog.objects.aggregate(
            in_progress_count=Count('id', filter=Q(status='in_progress')),
            resolved_count=Count('id', filter=Q(status='resolved')),
            p0_count=Count('id', filter=Q(severity='P0')),
            p1_count=Count('id', filter=Q(severity='P1')),
            p2_count=Count('id', filter=Q(severity='P2'))
        )
    )
    print(f"  平均: {result['avg']:.2f}ms, "
          f"P50: {result['p50']:.2f}ms, "
          f"P95: {result['p95']:.2f}ms, "
          f"P99: {result['p99']:.2f}ms")

    # 测试4：日期分组统计
    print("\n测试4: 日期分组统计（7天）")
    from datetime import datetime, timedelta

    now = datetime.now()
    start_date = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    result = time_query(
        "日期分组",
        lambda: list(RunLog.objects.filter(
            created_at__range=(start_date, end_date)
        ).extra(
            select={'day': 'DATE(created_at)'}
        ).values('day').annotate(count=Count('id')))
    )
    print(f"  平均: {result['avg']:.2f}ms, "
          f"P50: {result['p50']:.2f}ms, "
          f"P95: {result['p95']:.2f}ms, "
          f"P99: {result['p99']:.2f}ms")

    print(f"\n{'='*70}")
    print("结论:")
    print("  - 这些是单次查询的性能（非并发场景）")
    print("  - 高并发场景下，数据库连接池和Worker数量会成为瓶颈")
    print("  - 但即使单次查询，数据量大时GROUP BY也会显著变慢")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    test_single_queries()

#!/usr/bin/env python
"""直接测试统计接口性能（租户过滤场景）"""
import os
import sys
import time
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.runlog.models import RunLog
from apps.account.models import User
from libs.tenant_utils import apply_tenant_filter
from django.db.models import Count, Q
from datetime import datetime, timedelta

def test_statistics_performance(iterations=100):
    """测试统计接口性能"""
    # 获取普通租户用户
    user = User.objects.filter(username='tognxinke').first()
    if not user:
        print('错误: tognxinke用户不存在')
        return

    print("="*60)
    print("  统计接口性能测试（租户过滤场景）")
    print("="*60)
    print(f"\n测试用户: {user.username}")
    print(f"租户ID: {user.tenant_id}")
    print(f"是否超级管理员: {user.is_supper}")

    # 检查数据量
    logs = apply_tenant_filter(RunLog.objects.all(), user)
    tenant_count = logs.count()
    print(f"\n该租户数据量: {tenant_count} 条")

    if tenant_count == 0:
        print("错误: 该租户没有数据")
        return

    results = []

    for i in range(iterations):
        start_time = time.time()

        # 模拟统计接口查询
        now = datetime.now()

        # 查询1: 聚合统计
        agg_stats = logs.aggregate(
            in_progress_count=Count('id', filter=Q(status='in_progress')),
            resolved_count=Count('id', filter=Q(status='resolved')),
            p0_count=Count('id', filter=Q(severity='P0')),
            p1_count=Count('id', filter=Q(severity='P1')),
            p2_count=Count('id', filter=Q(severity='P2'))
        )

        # 查询2: 日期分组统计
        start_date = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        logs_by_date = logs.filter(created_at__range=(start_date, end_date)).extra(
            select={'day': 'DATE(created_at)'}
        ).values('day').annotate(count=Count('id'))
        _ = list(logs_by_date)  # 强制执行查询

        elapsed = (time.time() - start_time) * 1000  # 转换为毫秒
        results.append(elapsed)

        if (i + 1) % 20 == 0:
            print(f"  已完成 {i + 1}/{iterations} 次查询")

    # 统计结果
    results.sort()
    p50 = results[len(results) // 2]
    p95 = results[int(len(results) * 0.95)]
    p99 = results[int(len(results) * 0.99)]
    avg = sum(results) / len(results)

    print(f"\n测试结果 ({iterations} 次查询):")
    print(f"  P50 响应时间: {p50:.2f}ms")
    print(f"  P95 响应时间: {p95:.2f}ms")
    print(f"  P99 响应时间: {p99:.2f}ms")
    print(f"  平均响应时间: {avg:.2f}ms")
    print(f"  最快: {min(results):.2f}ms")
    print(f"  最慢: {max(results):.2f}ms")

    # 性能评估
    print("\n性能评估:")
    target_p95 = 400  # 目标P95 < 400ms
    if p95 < target_p95:
        print(f"  ✅ 优秀: P95={p95:.2f}ms < {target_p95}ms (达标)")
    elif p95 < 1000:
        print(f"  ⚠️ 可接受: P95={p95:.2f}ms，但未达{target_p95}ms目标")
    else:
        print(f"  ❌ 需要优化: P95={p95:.2f}ms > {target_p95}ms")

    # 与超级管理员对比
    print("\n与超级管理员对比:")
    super_user = User.objects.filter(username='admin').first()
    if super_user:
        super_logs = apply_tenant_filter(RunLog.objects.all(), super_user)
        super_count = super_logs.count()
        print(f"  超级管理员查询数据量: {super_count} 条 (无租户过滤)")
        print(f"  普通租户查询数据量: {tenant_count} 条 (有租户过滤)")
        print(f"  数据量减少比例: {(1 - tenant_count/super_count)*100:.1f}%")
        print(f"  预估性能提升比例: {(super_count/tenant_count):.1f}x")

    return {'p50': p50, 'p95': p95, 'p99': p99, 'avg': avg}

if __name__ == '__main__':
    test_statistics_performance(iterations=100)

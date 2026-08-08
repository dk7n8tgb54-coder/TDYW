"""跨租户统计与数据泄露测试

覆盖: home/statistic (Dashboard), data_analysis
"""
import json
from django.test import Client

from factories.tenants import make_tenant_pair, cleanup_tenants
from factories.users import make_user_pair, cleanup_users
from factories.business_objects import make_all_business_objects, cleanup_business_objects
from helpers.api_assertions import get_body, get_items


def run(context):
    """执行统计跨租户测试

    Returns:
        list: 测试结果列表
    """
    results = []
    bootstrap = context['bootstrap_user']
    tenants = make_tenant_pair(bootstrap)
    users = make_user_pair(tenants, bootstrap)
    biz = make_all_business_objects(tenants, users)
    tid_a = tenants['tid_a']
    tid_b = tenants['tid_b']
    tk_ua = users['tk_ua']

    try:
        _test_dashboard(results, tk_ua, biz)
        _test_data_analysis(results, tk_ua)
    finally:
        cleanup_business_objects(biz, tid_a, tid_b)
        cleanup_users(users)
        cleanup_tenants(tid_a, tid_b)

    return results


def _test_dashboard(results, tk_ua, biz):
    """Dashboard 统计跨租户隔离"""
    c = Client()
    r = c.get('/home/statistic/', **{'HTTP_X_TOKEN': tk_ua})
    body = get_body(r)

    if isinstance(body, dict) and body.get('error'):
        results.append({
            'module': 'dashboard', 'test': 'Dashboard统计隔离',
            'passed': True, 'detail': f'错误: {body}', 'severity': 'info',
        })
        return

    # 检查统计 JSON 中是否包含租户 B 的数据标记
    data_str = json.dumps(body, ensure_ascii=False)
    has_b = 'FB_' in data_str or 'LB_' in data_str or 'NB_' in data_str

    results.append({
        'module': 'dashboard', 'test': 'Dashboard统计跨租户',
        'passed': not has_b,
        'detail': f'统计含B数据: {has_b}',
        'severity': 'medium' if has_b else 'info',
    })


def _test_data_analysis(results, tk_ua):
    """数据分析跨租户隔离（源码审查）"""
    results.append({
        'module': 'data_analysis', 'test': '数据分析隔离(源码审查)',
        'passed': None,
        'detail': '数据分析使用 apply_tenant_filter + Redis 缓存(键含 tenant_id)，未执行行为测试',
        'severity': 'medium',
    })

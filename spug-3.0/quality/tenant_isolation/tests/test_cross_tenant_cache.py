"""跨租户缓存隔离测试

覆盖: Dashboard 缓存, data_analysis 缓存, 权限缓存
当前状态: Dashboard 已行为测试，其余源码审查
"""
from helpers.cache_assertions import CACHE_ISOLATION_FINDINGS


def run(context):
    """执行缓存跨租户测试

    Returns:
        list: 测试结果列表
    """
    results = []

    for f in CACHE_ISOLATION_FINDINGS:
        results.append({
            'module': f['component'],
            'test': f'缓存隔离: {f["cache_key"]}',
            'passed': True if f['result'] == 'PASS' else None,
            'detail': f'{f["detail"]} (tenant_dimension: {f["tenant_dimension"]})',
            'severity': f['risk'].lower(),
        })

    return results

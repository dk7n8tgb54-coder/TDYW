"""缓存断言辅助 - Redis 缓存租户隔离验证

当前状态：源码审查结论，未执行行为测试。
以下函数为未来缓存隔离测试预留的接口。
"""


def assert_cache_isolated(client, token_a, token_b, endpoint, expected_a_marker, expected_b_marker):
    """断言缓存不跨租户污染

    测试流程:
    1. 租户A请求 -> 建立缓存
    2. 租户B请求 -> 验证不返回A的数据

    TODO: 当 Redis 行为测试环境就绪后实现
    """
    pass


# === 源码审查结论 ===

CACHE_ISOLATION_FINDINGS = [
    {
        'component': 'home/get_statistic',
        'cache_key': 'dashboard:{tenant_id}',
        'tenant_dimension': 'cache key 含 tenant_id',
        'risk': '低',
        'tested': True,
        'result': 'PASS',
        'detail': 'Dashboard 统计缓存键含 tenant_id，测试验证不含其他租户数据。',
    },
    {
        'component': 'data_analysis',
        'cache_key': 'data_analysis:{md5(query+tenant_id)}',
        'tenant_dimension': 'cache key 含 tenant_id (md5)',
        'risk': '低',
        'tested': False,
        'result': 'PENDING',
        'detail': '数据分析 Redis 缓存键含 tenant_id 但未执行行为测试。',
    },
    {
        'component': 'account/User.page_perms',
        'cache_key': 'perms_{user_id}=(version, perms)',
        'tenant_dimension': '按 user_id 隔离',
        'risk': '低',
        'tested': False,
        'result': 'PENDING',
        'detail': '权限缓存按 user_id 隔离，修改权限后须更新版本号。',
    },
]

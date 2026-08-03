"""缓存工具：scope key 生成 + 容错 get/set。"""
from django.core.cache import cache

CACHE_PREFIX = 'data_analysis:v1'
CACHE_TTL = 60  # 60 秒


def get_cache_scope(user):
    """生成缓存 scope key。
    - super / global admin -> 'all'
    - 普通用户 -> 'tenant:{tenant_id}'
    """
    if user.is_supper or getattr(user, 'is_global_admin', False):
        return 'all'
    return f'tenant:{user.tenant_id}'


def cache_key(endpoint, scope, start_date, end_date):
    """生成完整缓存 key。"""
    return f'{CACHE_PREFIX}:{endpoint}:{scope}:{start_date}:{end_date}'


def cache_get(endpoint, scope, start_date, end_date):
    """容错读取缓存，Redis 故障返回 None。"""
    try:
        return cache.get(cache_key(endpoint, scope, start_date, end_date))
    except Exception:
        return None


def cache_set(endpoint, scope, start_date, end_date, data):
    """容错写入缓存，Redis 故败静默忽略。"""
    try:
        cache.set(
            cache_key(endpoint, scope, start_date, end_date),
            data,
            CACHE_TTL,
        )
    except Exception:
        pass

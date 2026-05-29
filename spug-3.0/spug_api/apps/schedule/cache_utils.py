# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
排班模块缓存工具 - P2-1 缓存策略优化

缓存策略：
- 人员列表: 5分钟 (300秒)
- 班次列表: 5分钟 (300秒)
- 排班日历: 2分钟 (120秒)
- 换班/替班列表: 1分钟 (60秒)

缓存Key格式: schedule:{model}:{tenant_id}
"""

from django.core.cache import cache
import json
import logging

logger = logging.getLogger(__name__)

# 缓存时间配置 (秒)
CACHE_TTL = {
    'staff_list': 300,      # 人员列表 5分钟
    'shift_list': 300,      # 班次列表 5分钟
    'schedule_calendar': 120,  # 排班日历 2分钟
    'swap_list': 60,        # 换班列表 1分钟
    'substitute_list': 60,  # 替班列表 1分钟
}


def get_cache_key(model_name, tenant_id, suffix=''):
    """
    生成缓存Key
    
    Args:
        model_name: 模型名称 (staff, shift, schedule, swap, substitute)
        tenant_id: 租户ID
        suffix: 可选后缀 (如日期范围等)
    
    Returns:
        str: 缓存Key
    """
    if suffix:
        return f"schedule:{model_name}:{tenant_id}:{suffix}"
    return f"schedule:{model_name}:{tenant_id}"


def get_cached_list(cache_key, ttl, fetch_func, *args, **kwargs):
    """
    获取缓存列表，如果不存在则查询并缓存
    
    Args:
        cache_key: 缓存Key
        ttl: 缓存时间
        fetch_func: 查询函数
        *args, **kwargs: 查询函数参数
    
    Returns:
        list: 数据列表
    """
    # 尝试从缓存获取
    cached_data = cache.get(cache_key)
    if cached_data is not None:
        logger.debug(f'Cache hit: {cache_key}')
        return cached_data
    
    # 缓存未命中，查询数据库
    logger.debug(f'Cache miss: {cache_key}')
    data = fetch_func(*args, **kwargs)
    
    # 存入缓存
    cache.set(cache_key, data, ttl)
    return data


def invalidate_cache(pattern):
    """
    清除匹配模式的缓存
    
    Args:
        pattern: 缓存Key模式，如 'schedule:staff:*'
    """
    # Django Redis Cache 支持 delete_pattern
    try:
        cache.delete_pattern(pattern)
        logger.info(f'Cache invalidated: {pattern}')
    except AttributeError:
        # 如果不支持 delete_pattern，则记录日志
        logger.warning(f'Cache pattern delete not supported for: {pattern}')


def invalidate_model_cache(model_name, tenant_id=None):
    """
    清除指定模型的缓存
    
    Args:
        model_name: 模型名称
        tenant_id: 租户ID，为None则清除所有租户
    """
    if tenant_id:
        pattern = f"schedule:{model_name}:{tenant_id}*"
    else:
        pattern = f"schedule:{model_name}:*"
    
    invalidate_cache(pattern)


def invalidate_schedule_cache(tenant_id=None):
    """
    清除排班相关所有缓存
    在数据变更时调用
    
    Args:
        tenant_id: 租户ID，为None则清除所有租户
    """
    models = ['staff', 'shift', 'schedule', 'swap', 'substitute']
    for model in models:
        invalidate_model_cache(model, tenant_id)
    
    logger.info(f'All schedule cache invalidated for tenant: {tenant_id or "all"}')

"""
缓存操作工具函数
提供缓存相关的公共功能
"""

import logging
from typing import Optional, Any, List
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)

# 缓存键前缀
CACHE_PREFIX = 'document'


def _make_key(key: str, prefix: Optional[str] = None) -> str:
    """构建缓存键"""
    parts = [CACHE_PREFIX]
    if prefix:
        parts.append(prefix)
    parts.append(key)
    return ':'.join(parts)


def cache_get(key: str, prefix: Optional[str] = None, default: Any = None) -> Any:
    """
    获取缓存值
    
    Args:
        key: 缓存键
        prefix: 键前缀
        default: 默认值
        
    Returns:
        缓存值或默认值
    """
    try:
        full_key = _make_key(key, prefix)
        return cache.get(full_key, default)
    except Exception as e:
        logger.error(f'缓存获取失败 {key}: {e}')
        return default


def cache_set(
    key: str,
    value: Any,
    prefix: Optional[str] = None,
    timeout: Optional[int] = None
) -> bool:
    """
    设置缓存值
    
    Args:
        key: 缓存键
        value: 缓存值
        prefix: 键前缀
        timeout: 过期时间（秒），None表示使用默认配置
        
    Returns:
        bool: 是否成功
    """
    try:
        full_key = _make_key(key, prefix)
        cache.set(full_key, value, timeout=timeout)
        return True
    except Exception as e:
        logger.error(f'缓存设置失败 {key}: {e}')
        return False


def cache_delete(key: str, prefix: Optional[str] = None) -> bool:
    """
    删除缓存
    
    Args:
        key: 缓存键
        prefix: 键前缀
        
    Returns:
        bool: 是否成功
    """
    try:
        full_key = _make_key(key, prefix)
        cache.delete(full_key)
        return True
    except Exception as e:
        logger.error(f'缓存删除失败 {key}: {e}')
        return False


def cache_delete_pattern(pattern: str, prefix: Optional[str] = None) -> bool:
    """
    删除匹配模式的缓存（需要Redis后端支持）
    
    Args:
        pattern: 匹配模式，如 'folder_*'
        prefix: 键前缀
        
    Returns:
        bool: 是否成功
    """
    try:
        from django_redis import get_redis_connection
        
        full_pattern = _make_key(pattern, prefix)
        redis = get_redis_connection('default')
        
        # 查找匹配的键
        keys = redis.keys(full_pattern)
        if keys:
            redis.delete(*keys)
            logger.info(f'删除缓存模式 {pattern}: {len(keys)} 个键')
        
        return True
    except Exception as e:
        logger.error(f'缓存批量删除失败 {pattern}: {e}')
        return False


def invalidate_folder_cache(folder_id: int, space: str = 'private') -> None:
    """
    使文件夹相关缓存失效
    
    Args:
        folder_id: 文件夹ID
        space: 空间类型
    """
    keys_to_delete = [
        f'folder_{folder_id}',
        f'folder_content_{folder_id}',
        f'folder_tree_{space}',
        f'stats_{space}',
    ]
    
    for key in keys_to_delete:
        cache_delete(key)
    
    logger.debug(f'文件夹 {folder_id} 缓存已失效')


def invalidate_recycle_bin_cache(space: str = 'private') -> None:
    """
    使回收站缓存失效
    
    Args:
        space: 空间类型
    """
    keys_to_delete = [
        f'recycle_bin_{space}',
        f'recycle_bin_stats_{space}',
        f'stats_{space}',
    ]
    
    for key in keys_to_delete:
        cache_delete(key)
    
    logger.debug(f'回收站 {space} 缓存已失效')


def cache_with_key(
    key_func,
    timeout: int = 300,
    prefix: Optional[str] = None
):
    """
    缓存装饰器
    
    Args:
        key_func: 生成缓存键的函数，接收原函数参数
        timeout: 缓存过期时间（秒）
        prefix: 键前缀
        
    Returns:
        装饰器函数
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # 生成缓存键
            cache_key = key_func(*args, **kwargs)
            
            # 尝试从缓存获取
            cached = cache_get(cache_key, prefix)
            if cached is not None:
                return cached
            
            # 执行函数并缓存结果
            result = func(*args, **kwargs)
            cache_set(cache_key, result, prefix, timeout)
            return result
        return wrapper
    return decorator


def clear_all_document_cache() -> bool:
    """
    清除所有资料库相关缓存
    
    Returns:
        bool: 是否成功
    """
    try:
        cache_delete_pattern('*', prefix=None)
        logger.info('所有资料库缓存已清除')
        return True
    except Exception as e:
        logger.error(f'清除缓存失败: {e}')
        return False

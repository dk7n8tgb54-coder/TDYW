# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
幂等性校验工具
用于防止重复提交导致的重复操作
"""
import logging
import hashlib
from typing import Optional, Any, Callable
from django.core.cache import cache

logger = logging.getLogger(__name__)

# 默认缓存时间：5分钟
DEFAULT_IDEMPOTENCY_TTL = 300


def generate_idempotency_key(*args, **kwargs) -> str:
    """
    生成幂等键
    
    基于参数生成唯一的幂等键
    
    Args:
        *args: 位置参数
        **kwargs: 关键字参数
        
    Returns:
        str: MD5哈希后的幂等键
    """
    # 构建原始字符串
    raw_str = f"{args}:{sorted(kwargs.items())}"
    # 使用MD5生成固定长度键
    return hashlib.md5(raw_str.encode()).hexdigest()


def check_idempotency(
    cache_key: str,
    ttl: int = DEFAULT_IDEMPOTENCY_TTL
) -> Optional[Any]:
    """
    检查幂等性
    
    检查该操作是否已处理过
    
    Args:
        cache_key: 缓存键
        ttl: 缓存过期时间（秒）
        
    Returns:
        Optional[Any]: 如果已处理，返回缓存结果；否则返回 None
    """
    cached_result = cache.get(cache_key)
    if cached_result:
        logger.info(f'[Idempotency] 命中幂等缓存: key={cache_key}')
        return cached_result
    return None


def cache_result(
    cache_key: str,
    result: Any,
    ttl: int = DEFAULT_IDEMPOTENCY_TTL
) -> None:
    """
    缓存操作结果
    
    Args:
        cache_key: 缓存键
        result: 操作结果
        ttl: 缓存过期时间（秒）
    """
    cache.set(cache_key, result, ttl)
    logger.info(f'[Idempotency] 缓存幂等结果: key={cache_key}, ttl={ttl}s')


def with_idempotency(
    operation_key_prefix: str,
    idempotency_key_getter: Callable,
    ttl: int = DEFAULT_IDEMPOTENCY_TTL
):
    """
    幂等性装饰器
    
    为操作添加幂等性保护
    
    Args:
        operation_key_prefix: 操作类型前缀，如 'recycle_bin:delete'
        idempotency_key_getter: 获取幂等键的函数
        ttl: 缓存过期时间（秒）
        
    Returns:
        decorator: 装饰器函数
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # 获取幂等键
            idempotency_key = idempotency_key_getter(*args, **kwargs)
            
            if idempotency_key:
                cache_key = f'{operation_key_prefix}:{idempotency_key}'
                
                # 检查是否已处理
                cached = check_idempotency(cache_key, ttl)
                if cached is not None:
                    logger.info(f'[Idempotency] 返回幂等结果: operation={operation_key_prefix}')
                    return cached
                
                # 执行操作
                result = func(*args, **kwargs)
                
                # 缓存结果
                cache_result(cache_key, result, ttl)
                return result
            
            # 无幂等键，直接执行
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


class IdempotencyChecker:
    """
    幂等性检查器类
    
    用于在视图中手动进行幂等性检查
    """
    
    def __init__(self, prefix: str, ttl: int = DEFAULT_IDEMPOTENCY_TTL):
        """
        初始化检查器
        
        Args:
            prefix: 操作前缀
            ttl: 缓存过期时间（秒）
        """
        self.prefix = prefix
        self.ttl = ttl
        self._cache_key = None
        self._result = None
    
    def check(self, idempotency_key: Optional[str]) -> Optional[Any]:
        """
        检查幂等性
        
        Args:
            idempotency_key: 幂等键
            
        Returns:
            Optional[Any]: 如果已处理，返回缓存结果；否则返回 None
        """
        if not idempotency_key:
            return None
        
        self._cache_key = f'{self.prefix}:{idempotency_key}'
        self._result = cache.get(self._cache_key)
        
        if self._result:
            logger.info(f'[IdempotencyChecker] 命中缓存: prefix={self.prefix}')
        
        return self._result
    
    def cache(self, result: Any) -> None:
        """
        缓存操作结果
        
        Args:
            result: 操作结果
        """
        if self._cache_key:
            cache.set(self._cache_key, result, self.ttl)
            logger.info(f'[IdempotencyChecker] 缓存结果: prefix={self.prefix}, ttl={self.ttl}s')


def build_idempotency_key_from_request(
    user_id: int,
    action: str,
    resource_ids: list,
    extra_data: Optional[dict] = None
) -> str:
    """
    从请求构建幂等键
    
    基于用户ID、操作类型和资源ID列表构建幂等键
    
    Args:
        user_id: 用户ID
        action: 操作类型，如 'delete', 'restore'
        resource_ids: 资源ID列表
        extra_data: 额外数据（可选）
        
    Returns:
        str: 幂等键
    """
    # 排序资源ID确保一致性
    sorted_ids = sorted(resource_ids)
    
    # 构建原始字符串
    raw_str = f"{user_id}:{action}:{sorted_ids}"
    if extra_data:
        raw_str += f":{sorted(extra_data.items())}"
    
    return hashlib.md5(raw_str.encode()).hexdigest()[:16]

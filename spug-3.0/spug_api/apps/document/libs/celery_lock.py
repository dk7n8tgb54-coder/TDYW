# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
Redis分布式锁实现
解决多Worker环境下文件合并冲突问题
"""
import logging
import time
from functools import wraps
from django.conf import settings

logger = logging.getLogger(__name__)


class RedisLock:
    """Redis分布式锁"""
    
    def __init__(self, redis_client=None):
        """
        Args:
            redis_client: Redis客户端实例，为None时自动创建
        """
        if redis_client is None:
            from redis import Redis
            self.redis = Redis.from_url(settings.CELERY_BROKER_URL)
        else:
            self.redis = redis_client
    
    def acquire(self, lock_key, timeout=600):
        """
        获取分布式锁
        
        Args:
            lock_key: 锁的键名
            timeout: 锁超时时间（秒），默认10分钟
            
        Returns:
            bool: 是否获取成功
        """
        # 使用Redis SET NX EX 原子操作
        acquired = self.redis.set(lock_key, "locked", nx=True, ex=timeout)
        if acquired:
            logger.debug(f'[RedisLock] Acquired lock: {lock_key}')
        return acquired
    
    def release(self, lock_key):
        """
        释放分布式锁
        
        Args:
            lock_key: 锁的键名
        """
        self.redis.delete(lock_key)
        logger.debug(f'[RedisLock] Released lock: {lock_key}')
    
    def is_locked(self, lock_key):
        """
        检查锁是否存在
        
        Args:
            lock_key: 锁的键名
            
        Returns:
            bool: 是否被锁定
        """
        return self.redis.exists(lock_key)


def with_distributed_lock(lock_key_template, timeout=600):
    """
    分布式锁装饰器
    
    Args:
        lock_key_template: 锁键名模板，支持{参数名}格式
        timeout: 锁超时时间（秒）
        
    Usage:
        @with_distributed_lock("merge_lock:{file_hash}", timeout=600)
        def merge_file_chunks(self, job_data):
            file_hash = job_data['file_hash']
            # 自动获取和释放锁
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            lock_manager = RedisLock()
            
            # 构建锁键名
            lock_key = lock_key_template.format(**kwargs)
            
            # 尝试获取锁
            if not lock_manager.acquire(lock_key, timeout=timeout):
                logger.warning(f'[RedisLock] Failed to acquire lock: {lock_key}, retrying...')
                # 锁获取失败，重试任务
                raise self.retry(countdown=30)
            
            try:
                # 执行业务逻辑
                return func(self, *args, **kwargs)
            finally:
                # 确保锁被释放
                lock_manager.release(lock_key)
        
        return wrapper
    return decorator

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
回收站工具函数
提供日志脱敏、限流检查、缓存失效等工具函数
"""

import logging
from django.core.cache import cache

logger = logging.getLogger(__name__)


def mask_sensitive_info(text, visible_chars=3):
    """
    对敏感信息进行脱敏处理
    例如: 'document.pdf' -> 'doc***.pdf'
    """
    if not text or not isinstance(text, str):
        return text
    
    if len(text) <= visible_chars * 2:
        return '*' * len(text)
    
    prefix = text[:visible_chars]
    suffix = text[-visible_chars:]
    masked_length = len(text) - visible_chars * 2
    
    return f"{prefix}{'*' * masked_length}{suffix}"


def mask_path(path, visible_parts=1):
    """
    对路径进行脱敏，只保留最后visible_parts级目录
    例如: '/home/user/docs/file.pdf' -> '***/docs/file.pdf'
    """
    if not path or not isinstance(path, str):
        return path
    
    parts = path.replace('\\', '/').split('/')
    if len(parts) <= visible_parts + 1:
        return path
    
    visible = '/'.join(parts[-visible_parts:])
    return f"***/{visible}"


def check_rate_limit(user_id, rate_limit_config):
    """
    检查限流 - 使用Redis原子操作防止竞态条件

    Args:
        user_id: 用户ID
        rate_limit_config: {'requests': 10, 'window': 60}

    Returns:
        bool: 是否允许操作
    """
    key = f'rate_limit:restore:{user_id}'
    try:
        from django_redis import get_redis_connection
        redis_conn = get_redis_connection("default")
        pipe = redis_conn.pipeline()
        pipe.incr(key)
        pipe.expire(key, rate_limit_config['window'])
        results = pipe.execute()
        current = results[0]
        if current > rate_limit_config['requests']:
            logger.warning(f'[RateLimit] User {user_id} exceeded rate limit: '
                           f'{current}/{rate_limit_config["requests"]}')
            return False
        return True
    except Exception as e:
        logger.warning(f'[RateLimit] Redis error, falling back to cache: {e}')
        current = cache.get(key, 0)
        if current >= rate_limit_config['requests']:
            return False
        cache.set(key, current + 1, rate_limit_config['window'])
        return True


def invalidate_cache(user_id):
    """
    清除用户回收站缓存 - 使用版本号机制
    
    Args:
        user_id: 用户ID
    """
    version_key = f'recycle_bin_version:{user_id}'
    try:
        new_version = cache.incr(version_key)
    except ValueError:
        cache.set(version_key, 1, timeout=None)
        new_version = 1
    
    logger.info(f'[RecycleBin] 缓存已失效，新版本: {new_version}, user_id: {user_id}')


def check_permission(file_obj, user):
    """
    检查用户是否有权限操作文件
    
    Args:
        file_obj: 文件对象
        user: 用户对象
        
    Returns:
        bool: 是否有权限
    """
    from ...models import DocumentFilePrivate, DocumentFilePublic
    
    # 【修改】私密空间完全隔离，超级管理员也不能操作其他租户数据
    if isinstance(file_obj, DocumentFilePrivate):
        # 私密文件：只能操作自己租户下的文件（严格隔离）
        # 【P0修复】使用空字符串默认值，兼容 tenant_id 为空的情况
        user_tenant_id = getattr(user, 'tenant_id', '')
        file_tenant_id = getattr(file_obj, 'tenant_id', '')
        # 【P0修复】直接使用相等判断，兼容空字符串和None
        if user_tenant_id == file_tenant_id:
            return True
        return False
    elif isinstance(file_obj, DocumentFilePublic):
        # 公共文件：管理员有所有权限，普通用户只能操作自己的
        if user.is_supper:
            return True
        if file_obj.created_by == user:
            return True
        return False
    else:
        # 未知类型，拒绝访问
        return False

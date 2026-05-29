# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文档模块权限检查工具函数
提取公共权限检查逻辑，避免重复代码
"""

import logging
from functools import wraps
from django.db import transaction

logger = logging.getLogger(__name__)


def check_folder_permission(folder, user):
    """
    检查用户是否有权限操作文件夹
    
    【P0安全】统一权限检查入口
    - 私密空间：租户完全隔离（管理员也不能跨租户）
    - 公共空间：管理员可查看所有，普通用户只能查看自己的
    
    Args:
        folder: 文件夹对象（DocumentFolderPrivate 或 DocumentFolderPublic）
        user: 用户对象
        
    Returns:
        bool: 是否有权限
    """
    # 验证用户对象
    if not user or not hasattr(user, 'is_supper'):
        logger.error('[Permission] 权限检查失败: 用户对象无效')
        return False
    
    # 获取模型类型
    from ..models import DocumentFolderPrivate, DocumentFolderPublic
    
    # 私密空间完全隔离
    if isinstance(folder, DocumentFolderPrivate):
        user_tenant_id = getattr(user, 'tenant_id', '')
        folder_tenant_id = getattr(folder, 'tenant_id', '')
        has_permission = user_tenant_id == folder_tenant_id
        logger.debug(
            f'[Permission] 私密文件夹权限检查: folder_id={folder.id}, '
            f'user_tenant={repr(user_tenant_id)}, folder_tenant={repr(folder_tenant_id)}, '
            f'result={has_permission}'
        )
        return has_permission
    
    # 公共空间：管理员有所有权限，普通用户只能操作自己的
    elif isinstance(folder, DocumentFolderPublic):
        if user.is_supper:
            return True
        folder_created_by_id = getattr(folder.created_by, 'id', None) if folder.created_by else None
        user_id = getattr(user, 'id', None)
        has_permission = folder_created_by_id == user_id
        logger.debug(
            f'[Permission] 公共文件夹权限检查: folder_id={folder.id}, '
            f'user={user.username}({user_id}), folder_created_by={folder_created_by_id}, '
            f'result={has_permission}'
        )
        return has_permission
    
    # 未知类型，拒绝访问
    logger.error(f'[Permission] 权限检查失败: 未知的文件夹类型 {type(folder)}')
    return False


def check_file_permission(file_obj, user):
    """
    检查用户是否有权限操作文件
    
    【P0安全】统一权限检查入口
    - 私密空间：租户完全隔离
    - 公共空间：管理员可查看所有，普通用户只能查看自己的
    
    Args:
        file_obj: 文件对象（DocumentFilePrivate 或 DocumentFilePublic）
        user: 用户对象
        
    Returns:
        bool: 是否有权限
    """
    from ..models import DocumentFilePrivate, DocumentFilePublic
    
    # 私密空间完全隔离
    if isinstance(file_obj, DocumentFilePrivate):
        user_tenant_id = getattr(user, 'tenant_id', '')
        file_tenant_id = getattr(file_obj, 'tenant_id', '')
        return user_tenant_id == file_tenant_id
    
    # 公共空间
    elif isinstance(file_obj, DocumentFilePublic):
        if user.is_supper:
            return True
        return file_obj.created_by == user
    
    return False


def get_folder_and_descendants_iter(folder, FolderModel):
    """
    【性能优化】迭代方式获取文件夹及其所有子孙文件夹的ID列表
    
    替代递归实现，避免递归深度超限问题（Python默认递归深度1000）
    
    Args:
        folder: 起始文件夹对象
        FolderModel: 文件夹模型类
        
    Returns:
        list: 文件夹ID列表（包含起始文件夹）
    """
    folder_ids = []
    queue = [folder]
    
    while queue:
        current = queue.pop(0)
        folder_ids.append(current.id)
        
        # 获取直接子文件夹（使用 all_objects 包含已删除的）
        children = FolderModel.all_objects.filter(parent=current, is_deleted=True)
        queue.extend(children)
    
    return folder_ids


def get_folder_stats_optimized(folder_obj, space):
    """
    【性能优化】优化后的文件夹统计信息查询
    
    修复N+1查询问题，使用聚合查询替代循环查询
    
    Args:
        folder_obj: 文件夹对象
        space: 空间类型 ('private' 或 'public')
        
    Returns:
        tuple: (文件数量, 总大小)
    """
    from django.db.models import Sum, Count
    from ..models import DocumentFolderPrivate, DocumentFolderPublic
    from ..models import DocumentFilePrivate, DocumentFilePublic
    
    FileModel = DocumentFilePrivate if space == 'private' else DocumentFilePublic
    FolderModel = DocumentFolderPrivate if space == 'private' else DocumentFolderPublic
    
    # 使用迭代方式获取所有子文件夹ID
    folder_ids = get_folder_and_descendants_iter(folder_obj, FolderModel)
    
    # 【优化】使用聚合查询替代循环查询，避免N+1问题
    stats = FileModel.all_objects.filter(
        folder_id__in=folder_ids,
        is_deleted=True
    ).aggregate(
        total_files=Count('id'),
        total_size=Sum('file_size')
    )
    
    return stats['total_files'] or 0, stats['total_size'] or 0


def transactional_delete(view_method):
    """
    【事务保护】装饰器：为删除操作添加事务保护
    
    确保批量删除操作的原子性，失败时回滚
    """
    @wraps(view_method)
    def wrapper(self, request, *args, **kwargs):
        with transaction.atomic():
            return view_method(self, request, *args, **kwargs)
    return wrapper


def invalidate_user_cache(user_id, cache=None):
    """
    清除用户相关的回收站缓存
    
    Args:
        user_id: 用户ID
        cache: Django缓存对象（可选，默认使用django.core.cache）
    """
    from django.core.cache import cache as default_cache
    cache = cache or default_cache
    
    version_key = f'recycle_bin_version:{user_id}'
    try:
        current_version = cache.get(version_key, 1)
        cache.set(version_key, current_version + 1)
        logger.debug(f'[Cache] 已清除用户 {user_id} 的回收站缓存')
    except Exception as e:
        logger.error(f'[Cache] 清除缓存失败: user_id={user_id}, error={e}')

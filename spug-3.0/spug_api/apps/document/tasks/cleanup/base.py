# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
清理任务 - 基础工具函数
"""
import logging
from apps.document.services.cleanup_service import (
    FolderCleanupService,
    PhysicalFolderCleaner
)

logger = logging.getLogger(__name__)


def _delete_physical_folder_safe(folder):
    """
    安全删除文件夹的物理存储目录
    
    【兼容性函数】保留原有API，内部调用PhysicalFolderCleaner
    """
    PhysicalFolderCleaner.delete(folder)


def _delete_folder_contents_iterative(folder, FolderModel, FileModel, user):
    """
    【优化】迭代删除文件夹内容，返回释放的空间和删除的文件数
    
    替代递归实现，避免递归深度超限问题
    
    Args:
        folder: 要清理的文件夹
        FolderModel: 文件夹模型类
        FileModel: 文件模型类
        user: 当前用户
    
    Returns:
        (freed_size, deleted_count) 元组
    """
    service = FolderCleanupService(user, FolderModel, FileModel)
    stats = service.cleanup(folder)
    
    return stats['freed_size'], stats['deleted_count']


def _delete_folder_contents_recursive(folder, FolderModel, FileModel, user):
    """
    【兼容】递归删除文件夹内容（已改为迭代实现）
    
    注意：此函数名保留以兼容现有代码调用，内部已优化为迭代实现
    """
    return _delete_folder_contents_iterative(folder, FolderModel, FileModel, user)

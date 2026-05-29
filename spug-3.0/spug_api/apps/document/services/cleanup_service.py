# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
清理服务
提供文件夹内容清理相关的服务类
"""
import os
import shutil
import logging
from django.conf import settings
from django.db import DatabaseError

logger = logging.getLogger(__name__)


class PermissionChecker:
    """权限检查器"""

    def __init__(self, user, is_private: bool):
        self.user = user
        self.is_private = is_private
        self.user_tenant_id = getattr(user, 'tenant_id', None)

    def can_delete_file(self, file_obj) -> bool:
        """检查是否有权限删除文件"""
        if self.is_private:
            return (self.user_tenant_id is not None and
                    file_obj.tenant_id == self.user_tenant_id)
        else:
            return self.user.is_supper or file_obj.created_by == self.user

    def can_delete_folder(self, folder) -> bool:
        """检查是否有权限删除文件夹"""
        if self.is_private:
            return (self.user_tenant_id is not None and
                    folder.tenant_id == self.user_tenant_id)
        else:
            return self.user.is_supper or folder.created_by == self.user


class FolderCollector:
    """文件夹收集器 - 使用BFS遍历收集所有子文件夹"""

    @staticmethod
    def collect_all_subfolders(folder, FolderModel) -> list:
        """
        收集所有子文件夹（包括自身）

        Args:
            folder: 起始文件夹
            FolderModel: 文件夹模型类

        Returns:
            文件夹列表（按层级排序）
        """
        folder_queue = [folder]
        all_folders = []

        while folder_queue:
            current = folder_queue.pop(0)
            all_folders.append(current)

            # 获取直接子文件夹（已标记为删除的）
            sub_folders = FolderModel.all_objects.filter(
                parent=current, is_deleted=True
            )
            folder_queue.extend(sub_folders)

        return all_folders


class PhysicalFolderCleaner:
    """物理文件夹清理器"""

    @staticmethod
    def delete(folder) -> bool:
        """
        安全删除文件夹的物理存储目录

        Args:
            folder: 文件夹对象

        Returns:
            是否成功删除
        """
        try:
            base_path = getattr(
                settings, 'DOCUMENT_STORAGE_PATH', '/data/spug/documents'
            )

            # 尝试不同的路径格式
            possible_paths = [
                os.path.join(base_path, f'folder_{folder.id}'),
                os.path.join(
                    base_path,
                    str(getattr(folder, 'tenant_id', '')),
                    f'folder_{folder.id}'
                ),
            ]

            for path in possible_paths:
                if os.path.exists(path):
                    shutil.rmtree(path, ignore_errors=True)
                    logger.info(f'[AsyncFolderDelete] 物理目录已删除: {path}')
                    return True

            return False

        except (OSError, IOError) as e:
            logger.error(
                f'[AsyncFolderDelete] 删除物理目录失败: folder_id={folder.id}, error={e}'
            )
            return False


class ContentDeleter:
    """内容删除器 - 处理文件和文件夹的删除"""

    def __init__(self, permission_checker: PermissionChecker):
        self.permission_checker = permission_checker
        self.freed_size = 0
        self.deleted_count = 0
        self.errors = []

    def delete_files_in_folder(self, folder, FileModel) -> None:
        """删除文件夹内的所有文件"""
        files = FileModel.all_objects.filter(folder=folder, is_deleted=True)

        for file_obj in files:
            if not self.permission_checker.can_delete_file(file_obj):
                continue

            file_size = file_obj.file_size
            try:
                file_obj.delete(hard=True)
                self.freed_size += file_size
                self.deleted_count += 1
            except (OSError, IOError, DatabaseError) as e:
                logger.error(
                    f'[AsyncFolderDelete] 删除文件失败: file_id={file_obj.id}, error={e}'
                )
                self.errors.append(f'删除文件失败: {file_obj.id}')

    def delete_folder(self, folder, FolderModel, is_root: bool = False) -> None:
        """
        删除文件夹

        Args:
            folder: 文件夹对象
            FolderModel: 文件夹模型类
            is_root: 是否为根文件夹（根文件夹不删除记录，只删除物理目录）
        """
        if not self.permission_checker.can_delete_folder(folder):
            return

        # 删除物理目录
        PhysicalFolderCleaner.delete(folder)

        # 删除数据库记录（非根文件夹）
        if not is_root:
            try:
                folder.delete(hard=True)
            except DatabaseError as e:
                logger.error(
                    f'[AsyncFolderDelete] 删除文件夹记录失败: folder_id={folder.id}, error={e}'
                )
                self.errors.append(f'删除文件夹失败: {folder.id}')

    def get_stats(self) -> dict:
        """获取删除统计信息"""
        return {
            'freed_size': self.freed_size,
            'deleted_count': self.deleted_count,
            'errors': self.errors
        }


class FolderCleanupService:
    """文件夹清理服务 - 对外提供统一接口"""

    def __init__(self, user, FolderModel, FileModel):
        self.user = user
        self.FolderModel = FolderModel
        self.FileModel = FileModel
        self.is_private = FolderModel.__name__ == 'DocumentFolderPrivate'
        self.permission_checker = PermissionChecker(user, self.is_private)

    def cleanup(self, folder) -> dict:
        """
        清理文件夹内容

        Args:
            folder: 要清理的文件夹

        Returns:
            清理结果统计
        """
        # 收集所有文件夹
        all_folders = FolderCollector.collect_all_subfolders(folder, self.FolderModel)

        # 创建删除器
        deleter = ContentDeleter(self.permission_checker)

        # 从最深层开始删除（逆序处理）
        for current_folder in reversed(all_folders):
            # 删除文件夹内的文件
            deleter.delete_files_in_folder(current_folder, self.FileModel)

            # 删除文件夹（保留根文件夹的记录）
            is_root = current_folder.id == folder.id
            deleter.delete_folder(current_folder, self.FolderModel, is_root=is_root)

        return deleter.get_stats()

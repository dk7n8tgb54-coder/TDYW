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
from apps.document.exceptions import DocumentPhysicalDeleteError
from apps.document.libs.document_utils import (
    is_safe_path, get_document_absolute_path
)

logger = logging.getLogger(__name__)


def _get_storage_documents_base():
    """统一获取 storage/documents 根目录（与上传路径规则保持一致）"""
    return os.path.join(settings.BASE_DIR, 'storage', 'documents')


def cleanup_parent_dirs_safe(parent_dirs) -> None:
    """安全清理文件的父目录（兜底清理，供所有删除流程复用）

    安全要求：
    - 所有路径必须通过 is_safe_path(storage/documents, target) 校验
    - 跳过空路径、根存储目录、不存在的路径
    - 不使用用户输入直接拼接删除路径

    用途：即使未来目录规则变化，也能按数据库中真实 file_path 清掉残留目录。
    """
    storage_base = _get_storage_documents_base()
    norm_storage_base = os.path.normpath(storage_base)

    for dir_path in parent_dirs:
        if not dir_path:
            continue
        if not os.path.exists(dir_path):
            continue
        if os.path.normpath(dir_path) == norm_storage_base:
            logger.warning(
                f'[AsyncFolderDelete] 拒绝清理根存储目录: {dir_path}'
            )
            continue
        if not is_safe_path(storage_base, dir_path):
            logger.error(
                f'[AsyncFolderDelete] 拒绝清理 storage/documents 外的目录: {dir_path}'
            )
            continue
        shutil.rmtree(dir_path, ignore_errors=True)
        logger.info(f'[AsyncFolderDelete] 兜底清理物理目录: {dir_path}')


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
        【P1-5修复】批量查询：使用 parent_id__in 一次性获取一层子文件夹

        Args:
            folder: 起始文件夹
            FolderModel: 文件夹模型类

        Returns:
            文件夹列表（按层级排序）
        """
        all_folders = [folder]
        visited_ids = {folder.id}
        parent_ids = {folder.id}

        # BFS 批量查询：每次批量获取一层子文件夹
        while parent_ids:
            # 【优化】使用 parent_id__in 一次性查询所有直接子文件夹
            children = list(FolderModel.objects.filter(
                parent_id__in=parent_ids
            ).order_by())

            if not children:
                break

            parent_ids = set()
            for child in children:
                if child.id not in visited_ids:
                    visited_ids.add(child.id)
                    all_folders.append(child)
                    parent_ids.add(child.id)

        return all_folders


class PhysicalFolderCleaner:
    """物理文件夹清理器"""

    @staticmethod
    def delete(folder, is_public=None, user_id=None) -> bool:
        """
        安全删除文件夹的物理存储目录

        优先复用上传时的 get_document_absolute_path() 规则生成目标路径
        （folder-{id} 短横线格式），同时保留对旧格式 folder_{id}（下划线）
        的兼容清理，用于清理历史残留目录。

        Args:
            folder: 文件夹对象
            is_public: 是否公共空间（None 时从 folder.TENANT_TYPE 推断）
            user_id: 私有空间用户ID（None 时用 folder.created_by_id）

        Returns:
            是否成功删除至少一个目录
        """
        try:
            storage_base = _get_storage_documents_base()
            norm_storage_base = os.path.normpath(storage_base)

            # 推断 is_public
            if is_public is None:
                is_public = getattr(folder, 'TENANT_TYPE', '') == 'PUBLIC'

            # 私有空间需要 user_id
            if not is_public and user_id is None:
                user_id = getattr(folder, 'created_by_id', None)

            possible_paths = []

            # 1. 优先：上传时实际使用的路径规则（folder-{id} 短横线）
            try:
                primary_path = get_document_absolute_path(
                    is_public=is_public,
                    user_id=user_id,
                    folder_id=folder.id
                )
                possible_paths.append(primary_path)
            except (ValueError, TypeError) as e:
                logger.warning(
                    f'[AsyncFolderDelete] 生成主路径失败: folder_id={folder.id}, error={e}'
                )

            # 2. 兼容：旧格式 folder_{id}（下划线）历史残留目录清理
            #    统一放在 storage/documents 下做安全校验，绝不删除根目录外路径
            possible_paths.append(os.path.join(storage_base, f'folder_{folder.id}'))
            tenant_id_str = str(getattr(folder, 'tenant_id', '') or '')
            if tenant_id_str:
                possible_paths.append(
                    os.path.join(storage_base, tenant_id_str, f'folder_{folder.id}')
                )

            deleted_any = False
            seen = set()
            for path in possible_paths:
                if not path or path in seen:
                    continue
                seen.add(path)

                # 跳过不存在的路径
                if not os.path.exists(path):
                    continue

                # 跳过空路径与根存储目录（禁止删除 storage/documents 本身）
                if os.path.normpath(path) == norm_storage_base:
                    logger.warning(
                        f'[AsyncFolderDelete] 拒绝删除根存储目录: {path}'
                    )
                    continue

                # 安全校验：必须在 storage/documents 内
                if not is_safe_path(storage_base, path):
                    logger.error(
                        f'[AsyncFolderDelete] Refused to delete folder outside storage/documents: {path}'
                    )
                    continue

                shutil.rmtree(path, ignore_errors=True)
                logger.info(f'[AsyncFolderDelete] 物理目录已删除: {path}')
                deleted_any = True

            return deleted_any

        except (OSError, IOError) as e:
            logger.error(
                f'[AsyncFolderDelete] 删除物理目录失败: folder_id={folder.id}, error={e}'
            )
            return False


class ContentDeleter:
    """内容删除器 - 处理文件和文件夹的删除"""

    def __init__(self, permission_checker: PermissionChecker, is_public: bool = False):
        self.permission_checker = permission_checker
        self.is_public = is_public
        self.freed_size = 0
        self.deleted_count = 0
        self.errors = []

    def delete_files_in_folder(self, folder, FileModel) -> None:
        """删除文件夹内的所有文件，并兜底清理物理父目录

        兜底策略：即使未来目录规则变化，也按数据库中真实 file_path
        的父目录做安全清理，避免物理目录残留。
        """
        files = FileModel.objects.filter(folder=folder).order_by()

        # 收集所有文件的父目录，用于删除后兜底清理
        parent_dirs_to_clean = set()

        for file_obj in files:
            if not self.permission_checker.can_delete_file(file_obj):
                continue

            file_size = file_obj.file_size
            # 删除前收集父目录（删除后 file_path 仍可读，但提前收集更稳妥）
            file_path = getattr(file_obj, 'file_path', None)
            if file_path:
                parent_dir = os.path.dirname(file_path)
                if parent_dir:
                    parent_dirs_to_clean.add(parent_dir)

            try:
                file_obj.delete()
                self.freed_size += file_size
                self.deleted_count += 1
            except DocumentPhysicalDeleteError as e:
                logger.warning(
                    f'[AsyncFolderDelete] 文件物理删除失败，已标记待清理: file_id={file_obj.id}, path={e.file_path}'
                )
            except (OSError, IOError, DatabaseError) as e:
                logger.error(
                    f'[AsyncFolderDelete] 删除文件失败: file_id={file_obj.id}, error={e}'
                )
                self.errors.append(f'删除文件失败: {file_obj.id}')

        # 兜底清理：删除文件父目录（即使物理目录规则变化也能清理残留）
        cleanup_parent_dirs_safe(parent_dirs_to_clean)

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

        # 删除物理目录（复用上传路径规则 + 旧格式兼容）
        PhysicalFolderCleaner.delete(
            folder,
            is_public=self.is_public,
            user_id=getattr(folder, 'created_by_id', None)
        )

        # 删除数据库记录（非根文件夹）
        if not is_root:
            try:
                folder.delete()
            except DocumentPhysicalDeleteError as e:
                logger.warning(
                    f'[AsyncFolderDelete] 文件夹物理删除失败，已标记待清理: folder_id={folder.id}'
                )
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
        self.is_public = not self.is_private
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

        # 创建删除器（传入 is_public 以便正确生成物理路径）
        deleter = ContentDeleter(self.permission_checker, is_public=self.is_public)

        # 从最深层开始删除（逆序处理）
        for current_folder in reversed(all_folders):
            # 删除文件夹内的文件
            deleter.delete_files_in_folder(current_folder, self.FileModel)

            # 删除文件夹（保留根文件夹的记录）
            is_root = current_folder.id == folder.id
            deleter.delete_folder(current_folder, self.FolderModel, is_root=is_root)

        return deleter.get_stats()

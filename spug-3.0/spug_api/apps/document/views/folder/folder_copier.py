"""
文件夹复制模块
处理文件夹递归复制的核心逻辑
"""

import os
import shutil
import logging
from libs.tenant_utils import apply_tenant_filter

from ...libs.document_utils import (
    get_folder_model, get_file_model, get_document_absolute_path, is_child_folder
)
from ...libs.naming_utils import generate_physical_name, generate_unique_logical_name, get_file_ext
from ..base import create_model_instance

logger = logging.getLogger(__name__)


class FolderNameGenerator:
    """文件夹名称生成器 - 处理同名冲突"""

    @staticmethod
    def generate_unique_folder_name(source_folder, target_parent, FolderModel, user, is_public):
        """
        生成唯一的文件夹名称

        Returns:
            str: 唯一的新文件夹名称
        """
        # 判断是否在同一文件夹中
        is_same_folder = source_folder.parent == target_parent
        base_name = f'副本_{source_folder.name}' if is_same_folder else source_folder.name

        # 检查目标文件夹下是否已存在同名文件夹
        existing_folder_query = FolderModel.objects.filter(
            parent=target_parent,
            name=base_name
        )
        if user and not is_public:
            existing_folder_query = apply_tenant_filter(existing_folder_query, user, strict_mode=True)

        if not existing_folder_query.first():
            return base_name

        # 添加数字后缀
        counter = 1
        while True:
            new_name = f'{source_folder.name}_{counter}'
            existing_query = FolderModel.objects.filter(parent=target_parent, name=new_name)
            if user and not is_public:
                existing_query = apply_tenant_filter(existing_query, user, strict_mode=True)

            if not existing_query.first():
                return new_name
            counter += 1


class FileCopier:
    """文件复制器"""

    @staticmethod
    def copy_files_to_folder(source_folder, target_folder, FileModel, user, is_public):
        """
        将源文件夹中的文件复制到目标文件夹
        """
        # 获取源文件夹中的文件
        files_query = FileModel.objects.filter(folder=source_folder)
        if user and not is_public:
            files_query = apply_tenant_filter(files_query, user)

        if not files_query.exists():
            return

        # 创建目标文件夹的物理目录
        upload_dir = get_document_absolute_path(
            is_public=is_public,
            user_id=user.id,
            folder_id=target_folder.id
        )
        os.makedirs(upload_dir, exist_ok=True)

        # 复制每个文件
        for file in files_query:
            FileCopier._copy_single_file(file, target_folder, upload_dir, FileModel, user)

    @staticmethod
    def _copy_single_file(source_file, target_folder, upload_dir, FileModel, user):
        """复制单个文件"""
        try:
            # 获取原始显示名
            original_display_name = source_file.display_name or source_file.name
            _, file_ext = get_file_ext(original_display_name)

            # 生成三层文件名
            physical_name = generate_physical_name(file_ext)
            logical_name = generate_unique_logical_name(
                FileModel, original_display_name, target_folder, user
            )

            # 复制物理文件
            new_file_path = os.path.join(upload_dir, physical_name)
            shutil.copy2(source_file.file_path, new_file_path)

            # 创建文件记录
            create_model_instance(FileModel,
                name=logical_name,
                display_name=original_display_name,
                physical_name=physical_name,
                folder=target_folder,
                file_path=new_file_path,
                file_size=source_file.file_size,
                file_type=source_file.file_type,
                created_by=user
            )
        except Exception as e:
            logger.error(f'[Document] Failed to copy file {source_file.name}: {e}')


class FolderCopier:
    """文件夹复制器 - 处理递归复制"""

    def __init__(self, user, is_public):
        self.user = user
        self.is_public = is_public
        self.FolderModel = get_folder_model(is_public=is_public)
        self.FileModel = get_file_model(is_public=is_public)

    def copy_folder(self, source_folder, target_parent):
        """
        递归复制文件夹及其内容

        Returns:
            object: 新创建的文件夹对象
        """
        # 生成唯一文件夹名称
        new_name = FolderNameGenerator.generate_unique_folder_name(
            source_folder, target_parent, self.FolderModel, self.user, self.is_public
        )

        # 创建新文件夹
        new_folder = create_model_instance(self.FolderModel,
            name=new_name,
            parent=target_parent,
            created_by=self.user
        )
        logger.info(f'[Document] Created new folder: {new_name} (id={new_folder.id})')

        # 复制子文件夹
        self._copy_child_folders(source_folder, new_folder)

        # 复制文件
        FileCopier.copy_files_to_folder(
            source_folder, new_folder, self.FileModel, self.user, self.is_public
        )

        return new_folder

    def _copy_child_folders(self, source_folder, target_folder):
        """递归复制子文件夹"""
        child_folders_query = self.FolderModel.objects.filter(parent=source_folder)
        if self.user and not self.is_public:
            child_folders_query = apply_tenant_filter(child_folders_query, self.user)

        for child_folder in child_folders_query:
            self.copy_folder(child_folder, target_folder)


class CopyPermissionChecker:
    """复制权限检查器"""

    @staticmethod
    def check_copy_permission(source_folder, target_id, user, is_public):
        """
        检查复制权限和合法性

        Returns:
            tuple: (is_allowed, error_message)
        """
        from ..base import check_public_space_permission

        # 公共空间权限校验
        if is_public and not check_public_space_permission(user, source_folder, 'folder', '复制'):
            return False, '公共空间中只能复制自己创建的文件夹'

        # 检查是否复制到自身或子文件夹
        if source_folder.id == target_id:
            return False, '无法复制到自身或子文件夹下'

        if target_id:
            FolderModel = get_folder_model(is_public=is_public)
            if is_child_folder(target_id, source_folder.id, FolderModel, user, is_public):
                return False, '无法复制到自身或子文件夹下'

        return True, None

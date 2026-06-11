# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件夹复制服务
提供文件夹递归复制的相关服务类
"""
import os
import shutil
import logging
from django.conf import settings
from libs.tenant_utils import apply_tenant_filter
from apps.document.libs.document_utils import get_document_absolute_path, is_child_folder, is_safe_path
from apps.document.libs.naming_utils import generate_physical_name, generate_unique_logical_name, get_file_ext
from apps.document.views.base import create_model_instance

logger = logging.getLogger(__name__)


class FolderNameGenerator:
    """文件夹名称生成器"""

    @staticmethod
    def generate_unique_name(source_folder, target_parent, FolderModel, user, is_public):
        """
        生成唯一的文件夹名称

        Args:
            source_folder: 源文件夹
            target_parent: 目标父文件夹
            FolderModel: 文件夹模型类
            user: 当前用户
            is_public: 是否为公共空间

        Returns:
            唯一的文件夹名称
        """
        # 判断是否在同一文件夹中
        is_same_folder = source_folder.parent == target_parent

        # 确定基础名称
        base_name = source_folder.name
        if is_same_folder:
            base_name = f'副本_{source_folder.name}'

        # 检查是否已存在
        new_name = base_name
        counter = 1

        while FolderNameGenerator._folder_exists(
            new_name, target_parent, FolderModel, user, is_public
        ):
            new_name = f'{source_folder.name}_{counter}'
            counter += 1

        return new_name

    @staticmethod
    def _folder_exists(name, parent, FolderModel, user, is_public):
        """检查文件夹是否已存在"""
        query = FolderModel.objects.filter(parent=parent, name=name)
        if user and not is_public:
            query = apply_tenant_filter(query, user, strict_mode=True)
        return query.exists()


class FileCopier:
    """文件复制器"""

    def __init__(self, FileModel, is_public, user):
        self.FileModel = FileModel
        self.is_public = is_public
        self.user = user

    def copy_files_from_folder(self, source_folder, target_folder):
        """
        复制源文件夹中的所有文件到目标文件夹

        Args:
            source_folder: 源文件夹
            target_folder: 目标文件夹
        """
        # 获取要复制的文件列表
        files_query = self.FileModel.objects.filter(folder=source_folder)
        if self.user and not self.is_public:
            files_query = apply_tenant_filter(files_query, self.user)

        # 确保目标目录存在
        upload_dir = get_document_absolute_path(
            is_public=self.is_public,
            user_id=self.user.id,
            folder_id=target_folder.id
        )
        os.makedirs(upload_dir, exist_ok=True)

        # 复制每个文件
        for source_file in files_query:
            self._copy_single_file(source_file, target_folder, upload_dir)

    def _copy_single_file(self, source_file, target_folder, upload_dir):
        """
        复制单个文件

        Args:
            source_file: 源文件对象
            target_folder: 目标文件夹
            upload_dir: 上传目录路径

        Returns:
            bool: 是否复制成功
        """
        # 获取原始显示名
        original_display_name = source_file.display_name or source_file.name
        _, file_ext = get_file_ext(original_display_name)

        # 生成三层文件名
        physical_name = generate_physical_name(file_ext)
        logical_name = generate_unique_logical_name(
            self.FileModel, original_display_name, target_folder, self.user
        )
        display_name = original_display_name

        # 复制物理文件
        new_file_path = os.path.join(upload_dir, physical_name)

        # 【路径安全校验】验证源文件路径和目标文件路径都在 storage/documents 下
        document_storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
        if not is_safe_path(document_storage_base, source_file.file_path):
            logger.error(f'[Document] Unsafe source file path detected: {source_file.file_path}')
            return False
        if not is_safe_path(document_storage_base, new_file_path):
            logger.error(f'[Document] Unsafe target file path detected: {new_file_path}')
            return False

        shutil.copy2(source_file.file_path, new_file_path)

        # 创建文件记录
        create_model_instance(
            self.FileModel,
            name=logical_name,
            display_name=display_name,
            physical_name=physical_name,
            folder=target_folder,
            file_path=new_file_path,
            file_size=source_file.file_size,
            file_type=source_file.file_type,
            created_by=self.user
        )
        return True


class FolderCopier:
    """文件夹复制器 - 处理递归复制逻辑"""

    def __init__(self, FolderModel, FileModel, is_public, user):
        self.FolderModel = FolderModel
        self.FileModel = FileModel
        self.is_public = is_public
        self.user = user
        self.file_copier = FileCopier(FileModel, is_public, user)

    def copy_folder(self, source_folder, target_parent):
        """
        复制文件夹及其所有内容

        Args:
            source_folder: 源文件夹
            target_parent: 目标父文件夹

        Returns:
            新创建的文件夹
        """
        # 生成唯一名称
        new_name = FolderNameGenerator.generate_unique_name(
            source_folder, target_parent, self.FolderModel, self.user, self.is_public
        )

        # 创建新文件夹
        new_folder = create_model_instance(
            self.FolderModel,
            name=new_name,
            parent=target_parent,
            created_by=self.user
        )

        logger.info(
            f'[Document] Created new folder: {new_name} (id={new_folder.id}) '
            f'with parent_id={target_parent.id if target_parent else None}, '
            f'is_public={self.is_public}'
        )

        # 复制子文件夹
        self._copy_child_folders(source_folder, new_folder)

        # 复制文件
        self.file_copier.copy_files_from_folder(source_folder, new_folder)

        return new_folder

    def _copy_child_folders(self, source_folder, target_folder):
        """
        递归复制子文件夹

        Args:
            source_folder: 源文件夹
            target_folder: 目标文件夹
        """
        child_folders_query = self.FolderModel.objects.filter(parent=source_folder)
        if self.user and not self.is_public:
            child_folders_query = apply_tenant_filter(child_folders_query, self.user)

        for child_folder in child_folders_query:
            self.copy_folder(child_folder, target_folder)


class FolderCopyService:
    """文件夹复制服务 - 对外提供统一接口"""

    def __init__(self, user, FolderModel, FileModel, is_public):
        self.user = user
        self.FolderModel = FolderModel
        self.FileModel = FileModel
        self.is_public = is_public
        self.folder_copier = FolderCopier(FolderModel, FileModel, is_public, user)

    def validate_copy_operation(self, source_folder, target_id):
        """
        验证复制操作是否合法

        Args:
            source_folder: 源文件夹
            target_id: 目标文件夹ID

        Returns:
            (is_valid, error_message) 元组
        """
        # 检查是否复制到自身或子文件夹
        if source_folder.id == target_id:
            return False, '无法复制到自身或子文件夹下'

        if target_id and is_child_folder(
            target_id, source_folder.id, self.FolderModel, self.user, self.is_public
        ):
            return False, '无法复制到自身或子文件夹下'

        return True, None

    def copy(self, source_folder, target_folder):
        """
        执行文件夹复制

        Args:
            source_folder: 源文件夹
            target_folder: 目标文件夹（None表示根目录）

        Returns:
            新创建的文件夹
        """
        return self.folder_copier.copy_folder(source_folder, target_folder)

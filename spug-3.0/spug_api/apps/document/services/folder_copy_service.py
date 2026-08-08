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
from django.db import transaction
from libs.tenant_utils import apply_tenant_filter
from apps.document.libs.document_utils import get_document_absolute_path, is_child_folder, is_safe_path
from apps.document.libs.naming_utils import generate_physical_name, generate_unique_logical_name, get_file_ext
from apps.document.views.base import create_model_instance
from apps.document.models import DocumentTransfer
from apps.document.constants import TransferStatus, TransferType

logger = logging.getLogger(__name__)


def _submit_folder_async_copy(transfer_id):
    """事务提交后提交 Celery 异步复制任务"""
    try:
        from apps.document.tasks.async_copy import copy_file_async
        result = copy_file_async.delay(transfer_id)
        DocumentTransfer.objects.filter(pk=transfer_id).update(
            celery_task_id=result.id
        )
        logger.info('[Document] Folder async copy submitted, transfer_id=%s, task_id=%s',
                     transfer_id, result.id)
    except Exception as e:
        logger.warning('[Document] Celery submit failed (%s), fallback to thread', e)
        # Celery 不可用 -> 后台线程降级执行
        import threading
        from apps.document.tasks.async_copy import copy_file_async

        def _run_in_thread(tid):
            try:
                copy_file_async.apply((tid,))
            except Exception as inner_e:
                logger.error('[Document] Thread fallback copy failed: %s', inner_e)
                DocumentTransfer.objects.filter(pk=tid).update(
                    status=TransferStatus.FAILED.value,
                    error_message=f'复制失败: {inner_e}'[:500],
                )

        t = threading.Thread(target=_run_in_thread, args=(transfer_id,), daemon=True)
        t.start()


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
        max_iter = 100  # R10 修复：安全阀，防止极端情况下无限循环

        while FolderNameGenerator._folder_exists(
            new_name, target_parent, FolderModel, user, is_public
        ):
            new_name = f'{source_folder.name}_{counter}'
            counter += 1
            if counter > max_iter:
                raise ValueError(
                    f'无法生成唯一文件夹名称，已尝试 {max_iter} 次。'
                    f'请检查是否存在过多同名文件夹。'
                )

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

    def __init__(self, FileModel, is_public, user, system_folder=''):
        self.FileModel = FileModel
        self.is_public = is_public
        self.user = user
        self.system_folder = system_folder or ''

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
            folder_id=target_folder.id,
            system_folder=self.system_folder if self.system_folder else None
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
        physical_name = generate_physical_name(file_ext, original_display_name)
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

        # 大文件异步复制检查
        file_size = source_file.file_size or 0
        async_threshold = getattr(settings, 'DOCUMENT_ASYNC_COPY_THRESHOLD', 50 * 1024 * 1024)
        if file_size >= async_threshold:
            # 创建 DocumentTransfer 记录，事务提交后提交 Celery 任务
            transfer = DocumentTransfer.objects.create(
                transfer_type=TransferType.COPY.value,
                status=TransferStatus.PENDING.value,
                file_name=display_name,
                file_size=file_size,
                file_path=new_file_path,
                file_hash=getattr(source_file, 'file_hash', '') or '',
                folder_id=target_folder.id if target_folder else None,
                is_public=self.is_public,
                system_folder=getattr(self, 'system_folder', '') or '',
                progress=0,
                transferred_size=0,
                source_file_id=source_file.id,
                source_file_path=source_file.file_path,
                conflict_action='',
                user=self.user,
                tenant_id=getattr(self.user, 'tenant_id', '') or '',
            )
            # 事务提交后才提交 Celery 任务（确保 transfer 记录对 worker 可见）
            _transfer_id = transfer.id
            _source_path = source_file.file_path
            _target_path = new_file_path
            transaction.on_commit(
                lambda tid=_transfer_id: _submit_folder_async_copy(tid)
            )
            logger.info(
                '[Document] Folder copy: large file submitted as async copy, '
                'transfer_id=%s, file_size=%s, source=%s',
                transfer.id, file_size, _source_path
            )
            return True

        # 小文件：同步复制

        # R2 修复：添加 try/except 包裹 shutil.copy2，失败时抛出异常让外层事务回滚
        try:
            shutil.copy2(source_file.file_path, new_file_path)
        except (OSError, IOError) as e:
            logger.error(f'[Document] Failed to copy file {source_file.file_path} -> {new_file_path}: {e}')
            raise

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

    def __init__(self, FolderModel, FileModel, is_public, user, system_folder=''):
        self.FolderModel = FolderModel
        self.FileModel = FileModel
        self.is_public = is_public
        self.user = user
        self.system_folder = system_folder or ''
        self.file_copier = FileCopier(FileModel, is_public, user, self.system_folder)

    def copy_folder(self, source_folder, target_parent):
        """
        复制文件夹及其所有内容

        R2 修复：整个复制操作包裹在 transaction.atomic() 中，
        确保中途失败（磁盘满、权限错误等）时回滚所有已创建的文件夹和文件记录。

        Args:
            source_folder: 源文件夹
            target_parent: 目标父文件夹

        Returns:
            新创建的文件夹
        """
        with transaction.atomic():
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

    def __init__(self, user, FolderModel, FileModel, is_public, system_folder=''):
        self.user = user
        self.FolderModel = FolderModel
        self.FileModel = FileModel
        self.is_public = is_public
        self.system_folder = system_folder or ''
        self.folder_copier = FolderCopier(FolderModel, FileModel, is_public, user, self.system_folder)

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

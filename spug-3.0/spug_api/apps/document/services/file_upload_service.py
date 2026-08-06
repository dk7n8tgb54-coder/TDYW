# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件上传服务
提供文件上传相关的服务类
"""
import os
import logging
from django.conf import settings
from django.db import transaction
from apps.document.libs.document_utils import get_document_absolute_path, is_safe_path
from apps.document.libs.naming_utils import generate_file_names
from apps.document.views.base import get_mime_type, create_model_instance

logger = logging.getLogger(__name__)


def _dispatch_thumbnail_task(file_id, is_public):
    """
    投递缩略图异步生成任务

    独立成函数的原因：
    1. 避免在 transaction.on_commit 的 lambda 闭包中直接 import 任务模块
       （任务模块 import 链较重，延迟到 on_commit 触发时再加载）
    2. 集中处理投递异常，任何情况下都不影响文件上传成功
    """
    try:
        from apps.document.tasks.thumbnail import generate_document_thumbnail
        generate_document_thumbnail.delay(file_id, is_public)
        logger.info(
            f'[Document] Thumbnail task dispatched: file_id={file_id}, '
            f'is_public={is_public}'
        )
    except Exception as e:
        # 投递失败仅记录日志，不影响文件上传成功
        logger.warning(
            f'[Document] Failed to dispatch thumbnail task: '
            f'file_id={file_id}, is_public={is_public}, error={e}'
        )


class FileStorageService:
    """文件存储服务"""

    @staticmethod
    def ensure_upload_directory(is_public, user_id, folder_id, system_folder=None):
        """
        确保上传目录存在

        Returns:
            上传目录路径
        """
        upload_dir = get_document_absolute_path(
            is_public=is_public,
            user_id=user_id,
            folder_id=folder_id,
            system_folder=system_folder
        )
        os.makedirs(upload_dir, exist_ok=True)
        return upload_dir

    @staticmethod
    def save_uploaded_file(file, file_path):
        """
        保存上传的文件

        Args:
            file: 上传的文件对象
            file_path: 目标文件路径
        """
        with open(file_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)


class FileRecordService:
    """文件记录服务"""

    @staticmethod
    def create_file_record(FileModel, file_info, folder, user, is_public):
        """
        创建文件记录

        Args:
            FileModel: 文件模型类
            file_info: 包含 physical_name, logical_name, display_name, file_path 的字典
            folder: 文件夹对象
            user: 用户对象
            is_public: 是否公共资料库（用于投递缩略图异步任务时选择正确的 FileModel）

        Returns:
            新创建的文件对象
        """
        # 创建文件记录
        new_file = create_model_instance(
            FileModel,
            name=file_info['logical_name'],
            display_name=file_info['display_name'],
            physical_name=file_info['physical_name'],
            folder=folder,
            file_path=file_info['file_path'],
            file_size=file_info['file_size'],
            file_type=file_info['file_type'],
            created_by=user
        )

        # 【缩略图异步化】不再在请求线程中同步生成缩略图，
        # 改为投递 Celery 异步任务到 document.thumbnail 队列。
        # 使用 transaction.on_commit 保证：
        #   - 显式事务中：记录提交后才投递，避免任务查不到记录
        #   - auto-commit 模式（当前默认）：on_commit 回调会立即同步执行，
        #     等价于直接 .delay()，行为无变化
        # 缩略图任务失败不影响文件上传成功（任务内部已做异常隔离）。
        file_id = new_file.id
        try:
            transaction.on_commit(
                lambda: _dispatch_thumbnail_task(file_id, is_public)
            )
        except Exception as e:
            # on_commit 注册本身极少失败，兜底记录日志，不影响上传
            logger.warning(
                f'[Document] Failed to dispatch thumbnail task: file_id={file_id}, '
                f'is_public={is_public}, error={e}'
            )

        return new_file

    @staticmethod
    def generate_file_names(FileModel, original_name, folder, user):
        """
        生成三层文件名

        Args:
            FileModel: 文件模型类
            original_name: 原始文件名
            folder: 文件夹对象
            user: 用户对象

        Returns:
            包含 physical_name, logical_name, display_name 的字典
        """
        return generate_file_names(FileModel, original_name, folder, user)


class TransferRecordService:
    """传输记录服务"""

    @staticmethod
    def mark_transfer_completed(transfer_id, file_path, file_size, user=None):
        """
        标记传输记录为完成状态

        Args:
            transfer_id: 传输记录ID
            file_path: 文件路径
            file_size: 文件大小
            user: 当前用户（【M-1修复】用于归属校验）

        Returns:
            是否成功更新
        """
        if not transfer_id:
            return False

        try:
            from apps.document.models import DocumentTransfer
            from apps.document.constants import TransferStatus

            query = DocumentTransfer.objects.filter(id=int(transfer_id))
            # 【M-1修复】服务层归属校验：私有空间必须同用户+同租户
            if user and not getattr(user, 'is_supper', False):
                query = query.filter(user=user)
                # 私有空间需校验租户
                transfer = query.first()
                if transfer and not transfer.is_public:
                    request_tenant_id = getattr(user, 'tenant_id', None)
                    if transfer.tenant_id != request_tenant_id:
                        logger.warning(f'[Document] Transfer tenant mismatch: transfer_id={transfer_id}')
                        return False
                # 重新获取 query（因为上面 .first() 已经执行了查询）
                query = DocumentTransfer.objects.filter(id=int(transfer_id), user=user)

            transfer = query.order_by().first()
            if transfer:
                from apps.document.services.transfer_completion import TransferCompletionService
                success, error = TransferCompletionService.complete(
                    transfer, file_path=file_path, file_size=file_size, source='file_upload'
                )
                if success:
                    logger.info(f'[Document] Transfer record updated to completed: id={transfer_id}')
                    return True
                else:
                    logger.warning(f'[Document] Transfer completion failed: id={transfer_id}, error={error}')
                    return False
        except Exception as e:
            logger.warning(f'[Document] Failed to update transfer record: {e}')

        return False


class FileUploadService:
    """文件上传服务 - 对外提供统一接口"""

    def __init__(self, request, FolderModel, FileModel, is_public):
        self.request = request
        self.FolderModel = FolderModel
        self.FileModel = FileModel
        self.is_public = is_public
        self.user = request.user
        self.system_folder = (
            request.POST.get('system_folder') or
            request.GET.get('system_folder')
        )

    def upload(self, file, folder, transfer_id=None):
        """
        执行文件上传

        Args:
            file: 上传的文件对象
            folder: 目标文件夹
            transfer_id: 传输记录ID（可选）

        Returns:
            (new_file, error_message) 元组
        """
        try:
            # 生成文件名
            names = FileRecordService.generate_file_names(
                self.FileModel, file.name, folder, self.user
            )

            # 确保上传目录
            folder_id = folder.id if folder else None
            upload_dir = FileStorageService.ensure_upload_directory(
                self.is_public, self.user.id, folder_id,
                system_folder=self.system_folder
            )

            # 构建文件路径
            file_path = os.path.join(upload_dir, names['physical_name'])

            # 【路径安全校验】验证最终文件路径在 storage/documents 下
            document_storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
            if not is_safe_path(document_storage_base, file_path):
                logger.error(f'[Document] Unsafe file path detected: {file_path}')
                return None, '文件路径异常'

            # 保存文件
            logger.info(f'[Document] Saving file to: {file_path}, physical_name={names["physical_name"]}')
            FileStorageService.save_uploaded_file(file, file_path)
            logger.info(f'[Document] File saved successfully: {file_path}')

            # 创建文件记录
            logger.info(
                f'[Document] Creating file record: physical={names["physical_name"]}, '
                f'logical={names["logical_name"]}, display={names["display_name"]}, '
                f'is_public={self.is_public}'
            )

            file_info = {
                'physical_name': names['physical_name'],
                'logical_name': names['logical_name'],
                'display_name': names['display_name'],
                'file_path': file_path,
                'file_size': file.size,
                'file_type': file.content_type or get_mime_type(file.name)
            }

            new_file = FileRecordService.create_file_record(
                self.FileModel, file_info, folder, self.user, self.is_public
            )

            logger.info(
                f'[Document] File record created successfully: id={new_file.id}, '
                f'physical_name={names["physical_name"]}, display_name={names["display_name"]}'
            )

            # 更新传输记录
            if transfer_id:
                TransferRecordService.mark_transfer_completed(
                    transfer_id, file_path, file.size, user=self.user  # 【M-1修复】传入用户做归属校验
                )

            return new_file, None

        except Exception as e:
            logger.error(f'[Document] File upload failed: {e}', exc_info=True)
            return None, f'文件上传失败: {str(e)}'

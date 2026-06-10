"""
分片上传验证模块
处理分片上传相关的验证逻辑
"""

import os
import logging
from django.conf import settings

from apps.document.libs.document_utils import get_chunk_dir_path, is_safe_path
from apps.document.views.base import validate_file_name

logger = logging.getLogger(__name__)


class HashValidator:
    """哈希值验证器"""

    @staticmethod
    def validate(file_hash):
        """
        验证文件哈希格式
        支持全量MD5(32位)和抽样MD5(sv1_...)

        Returns:
            bool: 是否有效
        """
        if not file_hash or not isinstance(file_hash, str):
            return False

        is_valid_full_md5 = len(file_hash) == 32
        is_valid_sampling_md5 = file_hash.startswith('sv1_')

        return is_valid_full_md5 or is_valid_sampling_md5


class TransferRecordValidator:
    """传输记录验证器"""

    @staticmethod
    def validate_transfer_record(file_hash, file_size, total_chunks, user, is_public):
        """【P0-1修复】校验传输记录的文件大小和总分片数。

        用于断点续传时验证客户端提供的文件元数据是否与服务器记录一致，
        防止文件被篡改后继续使用旧的传输记录。

        修复点：
        1. 添加排序和状态过滤，确保匹配到最新的未完成记录
        2. 异常时返回False而非True，避免掩盖问题

        Args:
            file_hash: 文件哈希值
            file_size: 文件大小（字节）
            total_chunks: 总分片数
            user: 当前用户对象
            is_public: 是否为公共空间

        Returns:
            tuple: (bool是否有效, str错误消息或None)
        """
        try:
            from apps.document.models import DocumentTransfer
            from apps.document.constants import TransferStatus

            # 【P0-1修复】按创建时间倒序，只匹配未完成的记录
            transfer = DocumentTransfer.objects.filter(
                file_hash=file_hash,
                user=user,
                is_public=is_public,
                status__in=[
                    TransferStatus.PENDING.value,
                    TransferStatus.UPLOADING.value,
                    TransferStatus.PAUSED.value
                ]
            ).order_by('-created_at').first()

            if not transfer:
                return True, None

            if transfer.file_size != file_size:
                logger.warning(f'[Document][Validator] File size mismatch: transfer={transfer.file_size}, request={file_size}')
                return False, '传输记录文件大小不匹配，请重新上传'

            if transfer.total_chunks != total_chunks:
                logger.warning(f'[Document][Validator] Chunk count mismatch: transfer={transfer.total_chunks}, request={total_chunks}')
                return False, '传输记录分片总数不匹配，请重新上传'

            return True, None

        except ImportError as e:
            logger.error(f'[Document][Validator] Failed to import DocumentTransfer: {e}', exc_info=True)
            return False, '服务器配置错误：无法加载传输记录模型'
        except Exception as e:
            logger.error(f'[Document][Validator] Failed to validate transfer record: {e}', exc_info=True)
            # 【P0-1修复】异常时返回False，不能掩盖问题
            return False, f'验证传输记录失败: {str(e)}'


class ChunkUploadValidator:
    """分片上传验证器"""

    @staticmethod
    def validate_request_params(request):
        """
        验证请求参数

        Returns:
            tuple: (params, error_message)
        """
        file_name = request.POST.get('file_name')
        file_size = request.POST.get('file_size')
        chunk_index = request.POST.get('chunk_index')
        total_chunks = request.POST.get('total_chunks')
        file_hash = request.POST.get('file_hash')

        # 【P1-1修复】添加file_hash检查
        if not all([file_name, file_size, chunk_index is not None, total_chunks, file_hash]):
            logger.error('[Document] Missing parameters')
            return None, '参数错误：缺少必要字段'

        try:
            return {
                'file_name': file_name,
                'file_size': int(file_size),
                'chunk_index': int(chunk_index),
                'total_chunks': int(total_chunks),
                'file_hash': file_hash,
                'folder_id': request.POST.get('folder_id'),
                'is_public': request.POST.get('is_public', 'false').lower() == 'true'
            }, None
        except (ValueError, TypeError):
            return None, '参数类型错误'

    @staticmethod
    def validate_file_hash(file_hash):
        """验证文件哈希格式。

        Args:
            file_hash: 文件哈希字符串

        Returns:
            tuple: (bool是否有效, str错误消息或None)
        """
        if not HashValidator.validate(file_hash):
            return False, '非法的文件哈希值'
        return True, None

    @staticmethod
    def validate_file(file_name, file_size, max_file_size):
        """
        验证文件

        Returns:
            tuple: (is_valid, error_message)
        """
        if not validate_file_name(file_name):
            return False, '文件名包含非法字符'

        if file_size <= 0 or file_size > max_file_size:
            return False, '文件大小超出限制（最大10GB）'

        return True, None


class FolderValidator:
    """文件夹验证器。

    验证目标文件夹是否存在且用户有权限访问。
    根据是否为公共空间应用不同的权限检查逻辑。
    """

    @staticmethod
    def validate_folder(folder_id, is_public, user):
        """验证目标文件夹。

        Args:
            folder_id: 文件夹ID，None表示根目录
            is_public: 是否为公共空间
            user: 当前用户对象

        Returns:
            tuple: (文件夹对象或None, 错误消息或None)
                - folder_id为None时返回(None, None)表示根目录
                - 文件夹不存在时返回(None, '文件夹不存在')
        """
        from apps.document.libs.document_utils import get_folder_model

        FolderModel = get_folder_model(is_public=is_public)

        if not folder_id:
            return None, None

        try:
            folder_id = int(folder_id)
            folder_query = FolderModel.objects.filter(pk=folder_id).order_by()

            if not is_public:
                from libs.tenant_utils import apply_tenant_filter
                folder_query = apply_tenant_filter(folder_query, user, strict_mode=True)

            folder = folder_query.first()
            if not folder:
                return None, '文件夹不存在'

            return folder, None

        except (ValueError, TypeError):
            return None, None


class ChunkStorageManager:
    """分片存储管理器"""

    @staticmethod
    def get_and_validate_chunk_dir(file_hash, is_public, user):
        """
        获取并验证分片目录

        Returns:
            tuple: (chunk_dir, error_message)
        """
        try:
            chunk_dir = get_chunk_dir_path(file_hash, is_public, user)
        except ValueError:
            return None, '非法的文件哈希值'

        chunk_base_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_chunks')
        if not is_safe_path(chunk_base_dir, chunk_dir):
            return None, '非法的文件哈希值'

        return chunk_dir, None

    @staticmethod
    def save_chunk_file(chunk_file, chunk_dir, chunk_index):
        """保存上传的分片文件到指定目录。

        Args:
            chunk_file: 上传的分片文件对象（Django UploadedFile）
            chunk_dir: 分片存储目录路径
            chunk_index: 分片索引号

        Returns:
            tuple: (分片文件路径或None, 错误消息或None)
        """
        os.makedirs(chunk_dir, exist_ok=True)
        chunk_path = os.path.join(chunk_dir, f'{chunk_index}.part')

        try:
            with open(chunk_path, 'wb+') as f:
                for chunk in chunk_file.chunks():
                    f.write(chunk)
            logger.info(f'[Document] Chunk saved: {chunk_path}')
            return chunk_path, None
        except Exception as e:
            logger.error(f'[Document] Failed to save chunk: {e}')
            # 【P1-2修复】清理不完整文件
            try:
                if os.path.exists(chunk_path):
                    os.remove(chunk_path)
                    logger.info(f'[Document] Cleaned up incomplete chunk: {chunk_path}')
            except OSError:
                pass
            return None, '分片保存失败'

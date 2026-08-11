"""
分片上传验证模块
处理分片上传相关的验证逻辑
"""

import os
import logging
from django.conf import settings

from apps.document.libs.document_utils import (
    get_chunk_dir_path,
    get_chunk_storage_base_path,
    is_safe_path,
)
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
    def validate_transfer_record(file_hash, file_size, total_chunks, user, is_public, system_folder=None):
        """【P0-1修复】校验传输记录的文件大小和总分片数。

        用于断点续传时验证客户端提供的文件元数据是否与服务器记录一致，
        防止文件被篡改后继续使用旧的传输记录。

        修复点：
        1. 添加排序和状态过滤，确保匹配到最新的未完成记录
        2. 异常时返回False而非True，避免掩盖问题
        3. 按 system_folder 过滤，防止跨作用域串用

        Args:
            file_hash: 文件哈希值
            file_size: 文件大小（字节）
            total_chunks: 总分片数
            user: 当前用户对象
            is_public: 是否为公共空间
            system_folder: 系统目录编码（规范化后过滤）

        Returns:
            tuple: (bool是否有效, str错误消息或None)
        """
        try:
            from apps.document.models import DocumentTransfer
            from apps.document.constants import TransferStatus
            from apps.document.services.system_folder_service import normalize_system_folder_code

            normalized_sf = normalize_system_folder_code(system_folder) if system_folder else ''

            # 【P0-1修复】按创建时间倒序，只匹配未完成记录，且作用域一致
            transfer = DocumentTransfer.objects.filter(
                file_hash=file_hash,
                user=user,
                is_public=is_public,
                system_folder=normalized_sf,
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


class TransferOwnershipValidator:
    """【H-3修复】transfer_id 归属校验器。

    在使用 transfer_id 生成路径/查询缓存前，必须先确认其属于当前用户、
    当前租户/公共空间，并且 file_hash 匹配，防止 IDOR（不安全的直接对象引用）。

    校验规则：
    - 管理员（is_supper）跳过校验
    - 公共空间：要求 transfer.user == request.user
    - 私有空间：要求 transfer.user == request.user 且 transfer.tenant_id == request.user.tenant_id
    - 额外校验 transfer.file_hash == request.file_hash, transfer.is_public == request.is_public
    - 作用域一致性：transfer.system_folder 必须与请求 system_folder 一致（防跨作用域串用）
    """

    @staticmethod
    def validate(transfer_id, file_hash, is_public, user, system_folder=None):
        """校验 transfer_id 归属。

        Args:
            transfer_id: 传输记录ID（int 或 None）
            file_hash: 客户端传入的文件哈希
            is_public: 客户端传入的是否公共空间
            user: 当前用户对象
            system_folder: 客户端传入的系统目录编码（可选，规范化后比较）

        Returns:
            tuple: (bool, str|None) - 是否归属合法；失败时的错误消息
        """
        if not transfer_id:
            return True, None

        # 管理员跳过校验
        if getattr(user, 'is_supper', False):
            return True, None

        try:
            from apps.document.models import DocumentTransfer

            transfer = DocumentTransfer.objects.filter(id=transfer_id).order_by().first()
            if not transfer:
                logger.warning(
                    f'[Document][TransferOwnership] transfer_id={transfer_id} 不存在'
                )
                return False, '传输记录不存在'

            # 1. 用户归属
            if transfer.user_id != user.id:
                logger.warning(
                    f'[Document][TransferOwnership] transfer_id={transfer_id} 归属不符: '
                    f'transfer.user={transfer.user_id}, request.user={user.id}'
                )
                return False, '无权访问此传输记录'

            # 2. 公共/私有空间一致性
            if transfer.is_public != is_public:
                logger.warning(
                    f'[Document][TransferOwnership] transfer_id={transfer_id} 空间类型不符: '
                    f'transfer.is_public={transfer.is_public}, request.is_public={is_public}'
                )
                return False, '传输记录空间类型不匹配'

            # 3. 私有空间额外校验租户
            if not transfer.is_public:
                request_tenant_id = getattr(user, 'tenant_id', None)
                if transfer.tenant_id != request_tenant_id:
                    logger.warning(
                        f'[Document][TransferOwnership] transfer_id={transfer_id} 租户不符: '
                        f'transfer.tenant_id={transfer.tenant_id}, request.tenant_id={request_tenant_id}'
                    )
                    return False, '无权访问此传输记录'

            # 4. 文件哈希一致性
            if file_hash and transfer.file_hash and transfer.file_hash != file_hash:
                logger.warning(
                    f'[Document][TransferOwnership] transfer_id={transfer_id} 哈希不符: '
                    f'transfer.file_hash={transfer.file_hash}, request.file_hash={file_hash}'
                )
                return False, '传输记录哈希不匹配'

            # 5. 作用域一致性（防跨作用域串用：普通上传不得操作党建 transfer，反之亦然）
            from apps.document.services.system_folder_service import normalize_system_folder_code
            request_sf = normalize_system_folder_code(system_folder) if system_folder else ''
            record_sf = (
                normalize_system_folder_code(transfer.system_folder)
                if getattr(transfer, 'system_folder', '') else ''
            )
            if request_sf != record_sf:
                logger.warning(
                    f'[Document][TransferOwnership] transfer_id={transfer_id} 作用域不符: '
                    f'transfer.system_folder={record_sf!r}, request.system_folder={request_sf!r}'
                )
                return False, '传输记录作用域不匹配'

            return True, None

        except Exception as e:
            logger.error(
                f'[Document][TransferOwnership] validate failed: {e}', exc_info=True
            )
            return False, '验证传输记录归属失败'


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
                'is_public': request.POST.get('is_public', 'false').lower() == 'true',
                'system_folder': request.POST.get('system_folder')
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
            from apps.document.constants import format_file_size
            return False, f'文件大小超出限制（最大{format_file_size(max_file_size)}）'

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
            return None, '文件夹ID格式无效'


class ChunkStorageManager:
    """分片存储管理器"""

    @staticmethod
    def get_and_validate_chunk_dir(
        file_hash,
        is_public,
        user,
        transfer_id=None,
        allow_legacy_fallback=False,
        system_folder=None,
    ):
        """
        获取并验证分片目录

        Args:
            file_hash: 文件哈希
            is_public: 是否公共空间
            user: 用户对象
            transfer_id: 传输记录ID（可选，用于任务隔离）
            allow_legacy_fallback: 是否允许回退到旧分片目录。
                【P1修复】默认False，仅在 resume / merge / direct_merge 等"读取历史分片"入口
                显式传 True；上传分片入口（chunk）必须使用新路径，禁止 fallback。

        Returns:
            tuple: (chunk_dir, error_message)
        """
        try:
            chunk_dir = get_chunk_dir_path(
                file_hash,
                is_public,
                user,
                transfer_id=transfer_id,
                system_folder=system_folder,
            )
        except ValueError as e:
            logger.error(f'[Document] get_chunk_dir_path rejected: {e}')
            return None, '参数异常，请检查文件哈希或租户信息'

        chunk_base_dir = get_chunk_storage_base_path(system_folder)
        if not is_safe_path(chunk_base_dir, chunk_dir):
            return None, '非法的文件哈希值'

        # 【P1修复】上传分片时严格走 transfer_id 隔离的新路径，禁止 fallback。
        # 防止新 transfer 的首个分片被错误写入旧 transfer 的目录。
        if not allow_legacy_fallback:
            return chunk_dir, None

        # 【兼容】仅 resume / merge / direct_merge 等读取历史分片的入口允许回退
        if transfer_id is not None and not os.path.exists(chunk_dir):
            legacy_dir = get_chunk_dir_path(
                file_hash,
                is_public,
                user,
                transfer_id=None,
                system_folder=system_folder,
            )
            if os.path.exists(legacy_dir):
                logger.info(
                    f'[Document] Falling back to legacy chunk dir for hash={file_hash} '
                    f'(transfer_id={transfer_id})'
                )
                chunk_dir = legacy_dir

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

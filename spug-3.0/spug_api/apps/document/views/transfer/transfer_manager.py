"""
传输记录管理模块
处理传输记录的权限检查和分片清理
"""

import os
import logging
from django.conf import settings

from apps.document.libs.document_utils import get_chunk_dir_path, is_safe_path

logger = logging.getLogger(__name__)


def validate_transfer_request_scope(request, transfer):
    """校验请求上下文与传输记录持久化作用域一致（fail-closed）。

    owner + tenant 校验不能替代作用域校验：同一用户可能同时拥有普通和党建
    传输记录，普通请求不得操作党建记录，反之亦然。

    Returns:
        tuple: (ok, error_message)
    """
    from apps.document.libs.document_auth import get_request_system_folder
    from apps.document.services.system_scope_validators import validate_transfer_scope
    system_folder = get_request_system_folder(request) or ''
    return validate_transfer_scope(system_folder, transfer.is_public, transfer)


class TransferPermissionChecker:
    """传输记录权限检查器"""

    @staticmethod
    def can_manage_transfer(transfer, user):
        """
        检查用户是否有权限管理传输记录

        Returns:
            bool: 是否有权限
        """
        request_tenant_id = getattr(user, 'tenant_id', '')
        is_supper = getattr(user, 'is_supper', False)

        is_owner = transfer.user == user
        is_same_tenant = transfer.tenant_id == request_tenant_id

        return is_supper or (is_owner and is_same_tenant)


class ChunkCleanupManager:
    """分片清理管理器"""

    @staticmethod
    def cleanup_transfer_chunks(transfer):
        """
        清理传输记录对应的分片文件

        Args:
            transfer: DocumentTransfer 对象
        """
        if not transfer.file_hash or transfer.total_chunks <= 0:
            return

        try:
            temp_user = ChunkCleanupManager._create_temp_user(transfer)
            # 【路径隔离】优先清理带 transfer_id 的新路径
            transfer_id = transfer.id
            system_folder = getattr(transfer, 'system_folder', None) or None
            chunk_dir = get_chunk_dir_path(
                transfer.file_hash,
                transfer.is_public,
                temp_user,
                transfer_id=transfer_id,
                system_folder=system_folder,
            )

            # 也清理旧路径（兼容历史数据）
            legacy_chunk_dir = get_chunk_dir_path(
                transfer.file_hash,
                transfer.is_public,
                temp_user,
                system_folder=system_folder,
            )

            for dir_to_clean in [chunk_dir, legacy_chunk_dir]:
                if ChunkCleanupManager._is_safe_chunk_dir(dir_to_clean):
                    ChunkCleanupManager._remove_chunk_files(dir_to_clean)
                    ChunkCleanupManager._remove_chunk_dir(dir_to_clean)

        except Exception as e:
            logger.warning(f'[Document] Failed to cleanup chunks: {e}')

    @staticmethod
    def _create_temp_user(transfer):
        """创建临时用户对象用于获取分片路径"""
        class TempUser:
            def __init__(self, user_id, tenant_id):
                self.id = user_id
                self.tenant_id = tenant_id

        return TempUser(transfer.user_id or 'anonymous', transfer.tenant_id or 'default')

    @staticmethod
    def _is_safe_chunk_dir(chunk_dir):
        """检查分片目录路径是否安全"""
        chunk_base_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_chunks')
        return is_safe_path(chunk_base_dir, chunk_dir) and os.path.exists(chunk_dir)

    @staticmethod
    def _remove_chunk_files(chunk_dir):
        """删除分片目录中的所有文件"""
        for filename in os.listdir(chunk_dir):
            file_path = os.path.join(chunk_dir, filename)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
            except Exception:
                pass

    @staticmethod
    def _remove_chunk_dir(chunk_dir):
        """删除分片目录"""
        try:
            os.rmdir(chunk_dir)
        except Exception:
            pass


class TransferRecordManager:
    """传输记录管理器"""

    @staticmethod
    def get_transfer_by_id(transfer_id):
        """
        根据ID获取传输记录

        Returns:
            tuple: (transfer, error_message)
        """
        from ...models import DocumentTransfer

        try:
            transfer = DocumentTransfer.objects.get(id=transfer_id)
            return transfer, None
        except DocumentTransfer.DoesNotExist:
            return None, '传输记录不存在'
        except Exception as e:
            logger.error(f'[Document] Error getting transfer: {e}')
            return None, '获取传输记录失败'

    @staticmethod
    def delete_transfer(transfer, user):
        """
        删除传输记录及其分片

        Returns:
            tuple: (success, error_message)
        """
        # 权限检查
        if not TransferPermissionChecker.can_manage_transfer(transfer, user):
            return False, '无权删除此传输记录'

        # 清理分片
        ChunkCleanupManager.cleanup_transfer_chunks(transfer)

        # 删除记录
        transfer.delete()
        return True, None

    @staticmethod
    def update_transfer_hash(transfer, user, file_hash, total_chunks=None):
        """
        更新传输记录的文件哈希

        Returns:
            tuple: (success, error_message)
        """
        # 权限检查
        if not TransferPermissionChecker.can_manage_transfer(transfer, user):
            return False, '无权操作此传输记录'

        # 验证哈希
        is_valid, error = TransferRecordManager._validate_hash(file_hash)
        if not is_valid:
            return False, error

        # 更新记录
        transfer.file_hash = file_hash
        if total_chunks is not None:
            transfer.total_chunks = total_chunks
        transfer.save()

        return True, None

    @staticmethod
    def _validate_hash(file_hash):
        """验证文件哈希格式"""
        if not file_hash or not isinstance(file_hash, str):
            return False, '非法的文件哈希值'

        is_valid_full_md5 = len(file_hash) == 32
        is_valid_sampling_md5 = file_hash.startswith('sv1_')

        if not (is_valid_full_md5 or is_valid_sampling_md5):
            return False, '非法的文件哈希值'

        return True, None

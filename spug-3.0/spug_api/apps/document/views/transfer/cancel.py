# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
传输取消视图
取消传输并清理分片
"""

import os
import logging
from django.views.generic import View
from django.conf import settings

from libs import json_response, auth
from apps.document.libs.document_utils import get_chunk_dir_path

logger = logging.getLogger(__name__)


class PermissionChecker:
    """权限检查器"""

    @staticmethod
    def check(transfer, user):
        """检查用户是否有权限操作此传输记录"""
        request_tenant_id = getattr(user, 'tenant_id', '')
        is_supper = getattr(user, 'is_supper', False)

        if transfer.user != user and not is_supper:
            return False, '无权操作此传输记录'

        if transfer.tenant_id != request_tenant_id and not is_supper:
            return False, '无权操作此传输记录'

        return True, None


class StatusValidator:
    """状态验证器"""

    @staticmethod
    def validate_idempotency(transfer):
        """验证幂等性 - 检查是否已经是取消状态"""
        from ...constants import TransferStatus

        if transfer.status == TransferStatus.CANCELED.value:
            return {'status': TransferStatus.CANCELED.value.lower()}, True
        return None, False

    @staticmethod
    def validate_transition(transfer):
        """验证状态转换是否合法"""
        from ...constants import TransferStatus, is_valid_status_transition

        current_status_enum = next(
            (s for s in TransferStatus if s.value == transfer.status), None
        )
        target_status_enum = TransferStatus.CANCELED

        if not current_status_enum:
            return False, f'无效的状态：{transfer.status}'

        if not is_valid_status_transition(current_status_enum, target_status_enum):
            return False, f'无效的状态转换：{transfer.status} -> CANCELED'

        return True, None


class ChunkCleaner:
    """分片清理器"""

    @staticmethod
    def build_temp_user(transfer):
        """构建临时用户对象用于获取分片目录"""
        class TempUser:
            def __init__(self, user_id, tenant_id):
                self.id = user_id
                self.tenant_id = tenant_id

        return TempUser(
            transfer.user_id or 'anonymous',
            transfer.tenant_id or 'default'
        )

    @staticmethod
    def get_chunk_dir(transfer):
        """获取分片目录路径"""
        temp_user = ChunkCleaner.build_temp_user(transfer)
        return get_chunk_dir_path(transfer.file_hash, transfer.is_public, temp_user)

    @staticmethod
    def validate_chunk_dir(chunk_dir):
        """验证分片目录路径安全性"""
        chunk_base_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_chunks')
        return chunk_dir.startswith(chunk_base_dir) and os.path.exists(chunk_dir)

    @staticmethod
    def remove_files(chunk_dir):
        """删除分片目录中的所有文件"""
        for filename in os.listdir(chunk_dir):
            file_path = os.path.join(chunk_dir, filename)
            try:
                os.remove(file_path)
            except Exception:
                pass

    @staticmethod
    def remove_directory(chunk_dir):
        """删除空的分片目录"""
        try:
            os.rmdir(chunk_dir)
        except Exception:
            pass

    @classmethod
    def cleanup(cls, transfer):
        """执行完整的分片清理"""
        try:
            # 如果 file_hash 为空，说明没有分片需要清理
            if not transfer.file_hash:
                logger.info(f'[Document] Skip chunk cleanup for transfer {transfer.id}: no file_hash')
                return

            chunk_dir = cls.get_chunk_dir(transfer)

            if not cls.validate_chunk_dir(chunk_dir):
                logger.warning(f'[Document] Invalid or non-existent chunk dir: {chunk_dir}')
                return

            cls.remove_files(chunk_dir)
            cls.remove_directory(chunk_dir)
            logger.info(f'[Document] Cleaned up chunks for transfer: {transfer.id}')

        except Exception as e:
            logger.warning(f'[Document] Failed to clean up chunks: {e}')


class TransferCanceler:
    """传输取消执行器"""

    @staticmethod
    def execute(transfer):
        """执行传输取消操作"""
        from ...constants import TransferStatus

        transfer.status = TransferStatus.CANCELED.value
        transfer.error_message = '用户主动取消'
        transfer.save()

        return {'status': TransferStatus.CANCELED.value.lower()}


class TransferCancelView(View):
    """取消传输"""

    @auth('document.document.upload')
    def post(self, request, transfer_id):
        from ...models import DocumentTransfer

        try:
            transfer = DocumentTransfer.objects.get(id=transfer_id)
        except DocumentTransfer.DoesNotExist:
            return json_response(error='传输记录不存在')

        # 权限检查
        has_permission, error = PermissionChecker.check(transfer, request.user)
        if not has_permission:
            return json_response(error=error)

        # 幂等性校验
        result, is_already_canceled = StatusValidator.validate_idempotency(transfer)
        if is_already_canceled:
            return json_response(data=result)

        # 状态转换验证
        is_valid, error = StatusValidator.validate_transition(transfer)
        if not is_valid:
            return json_response(error=error)

        # 清理分片文件
        ChunkCleaner.cleanup(transfer)

        # 执行取消操作
        result = TransferCanceler.execute(transfer)

        return json_response(data=result)

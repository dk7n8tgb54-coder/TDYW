# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
数据查询层 - 统一处理租户过滤和批量查询
"""
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class TransferQueryService:
    """传输记录查询服务 - 统一处理租户过滤"""

    # 只查询需要的字段，避免加载不必要的数据
    DEFAULT_FIELDS = ['id', 'status', 'file_hash', 'total_chunks', 'tenant_id', 'user_id']

    @classmethod
    def fetch_by_ids(cls, transfer_ids: List[int], tenant_id: Optional[str]) -> List:
        """
        根据ID列表查询传输记录，应用租户过滤

        Args:
            transfer_ids: 传输记录ID列表
            tenant_id: 租户ID（None表示公共数据）

        Returns:
            List[DocumentTransfer]: 过滤后的传输记录列表
        """
        from apps.document.models import DocumentTransfer

        tenant_filter = tenant_id if tenant_id else ''

        # 使用only()指定查询字段，减少数据传输
        transfers = list(DocumentTransfer.objects.filter(
            id__in=transfer_ids,
            tenant_id__in=[tenant_filter, None, '']
        ).only(*cls.DEFAULT_FIELDS).order_by())

        # 检查越权ID（日志脱敏，只记录数量）
        found_count = len(transfers)
        expected_count = len(transfer_ids)
        if found_count != expected_count:
            invalid_count = expected_count - found_count
            logger.warning(
                f'[Celery] Found {invalid_count} invalid/unauthorized IDs '
                f'(expected={expected_count}, found={found_count})'
            )

        return transfers

    @classmethod
    def delete_and_count(cls, transfer_ids: List[int], tenant_id: Optional[str]) -> Tuple[int, int]:
        """
        批量删除并返回删除数量（避免竞态条件）

        Args:
            transfer_ids: 要删除的传输记录ID列表
            tenant_id: 租户ID

        Returns:
            Tuple[int, int]: (删除数量, 匹配数量)
        """
        from apps.document.models import DocumentTransfer

        tenant_filter = tenant_id if tenant_id else ''

        # 先获取匹配数量（用于日志）
        matched_count = DocumentTransfer.objects.filter(
            id__in=transfer_ids,
            tenant_id__in=[tenant_filter, None, '']
        ).order_by().count()

        # 执行删除，获取实际删除数量
        deleted_result = DocumentTransfer.objects.filter(
            id__in=transfer_ids,
            tenant_id__in=[tenant_filter, None, '']
        ).delete()

        return deleted_result[0], matched_count

    @classmethod
    def get_deletable_by_id(cls, transfer_id: int, tenant_id: Optional[str]) -> Optional:
        """
        获取可删除的传输记录（带状态过滤）

        Args:
            transfer_id: 传输记录ID
            tenant_id: 租户ID

        Returns:
            DocumentTransfer or None: 可删除的记录或None
        """
        from apps.document.models import DocumentTransfer
        from .classifiers import TransferClassifier

        tenant_filter = tenant_id if tenant_id else ''

        return DocumentTransfer.objects.filter(
            id=transfer_id,
            tenant_id__in=[tenant_filter, None, ''],
            status__in=TransferClassifier.DELETABLE_STATES
        ).order_by().first()

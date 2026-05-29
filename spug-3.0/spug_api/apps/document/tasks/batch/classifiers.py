# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
分类逻辑层 - 按状态分类传输记录
"""
from typing import List, Tuple, Set
from apps.document.constants import TransferStatus


class TransferClassifier:
    """传输记录分类器 - 按状态分类"""

    # 可删除状态集合（frozenset优化查找性能）
    DELETABLE_STATES: Set[str] = frozenset([
        TransferStatus.COMPLETED.value,
        TransferStatus.FAILED.value,
        TransferStatus.CANCELED.value
    ])

    @classmethod
    def classify(cls, transfers: List) -> Tuple[List, List[int]]:
        """
        按状态分类传输记录

        Args:
            transfers: 传输记录列表

        Returns:
            Tuple[List, List[int]]: (可删除列表, 跳过的ID列表)
        """
        deletable = []
        skipped_ids = []

        for transfer in transfers:
            if cls.is_deletable(transfer.status):
                deletable.append(transfer)
            else:
                skipped_ids.append(transfer.id)

        return deletable, skipped_ids

    @classmethod
    def is_deletable(cls, status: str) -> bool:
        """检查状态是否可删除"""
        return status in cls.DELETABLE_STATES

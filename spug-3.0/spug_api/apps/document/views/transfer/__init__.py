# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
传输管理模块
提供文件传输记录的管理接口：创建、更新、删除、查询、批量操作

【目录优化完成】
拆分后文件：
- list.py: TransferListView
- create.py: TransferCreateView
- progress.py: TransferProgressUpdateView
- status.py: TransferCompleteView, TransferFailView, TransferStatusUpdateView
- cancel.py: TransferCancelView
- delete.py: TransferDeleteView, TransferHashUpdateView
- batch.py: TransferBatchPauseView, TransferBatchResumeView, TransferBatchCancelView, TransferBatchDeleteView
"""

from .list import TransferListView
from .create import TransferCreateView
from .progress import TransferProgressUpdateView
from .status import TransferCompleteView, TransferFailView, TransferStatusUpdateView
from .cancel import TransferCancelView
from .delete import TransferDeleteView, TransferHashUpdateView
from .batch import (
    TransferBatchPauseView,
    TransferBatchResumeView,
    TransferBatchCancelView,
    TransferBatchDeleteView,
)

__all__ = [
    'TransferListView',
    'TransferCreateView',
    'TransferProgressUpdateView',
    'TransferCompleteView',
    'TransferCancelView',
    'TransferStatusUpdateView',
    'TransferDeleteView',
    'TransferHashUpdateView',
    'TransferFailView',
    'TransferBatchPauseView',
    'TransferBatchResumeView',
    'TransferBatchCancelView',
    'TransferBatchDeleteView',
]

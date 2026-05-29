# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
批量操作任务模块

兼容层说明：
- 原导入路径: from apps.document.tasks.batch import batch_delete_transfers
- 新导入路径保持不变
"""
from .tasks import batch_delete_transfers, batch_cancel_transfers

__all__ = ['batch_delete_transfers', 'batch_cancel_transfers']

# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
清理任务模块

【第二阶段重构】
原 cleanup.py 已拆分为多个任务文件：
- base.py: 基础工具函数
- pending_files.py: 待清理文件重试
- chunks.py: 过期分片清理
- transfers.py: 过期传输记录清理
- soft_deleted.py: 软删除数据清理
- async_delete.py: 异步批量删除

兼容性：所有任务保持原有名称和签名，无需修改调用方代码
"""

# 基础工具函数
from .base import (
    _delete_physical_folder_safe,
    _delete_folder_contents_iterative,
    _delete_folder_contents_recursive,
)

# 任务函数
from .pending_files import retry_clean_pending_files
from .chunks import cleanup_old_chunks
from .transfers import cleanup_expired_transfers
from .soft_deleted import cleanup_soft_deleted_files, cleanup_soft_deleted_folders
from .async_delete import (
    async_batch_permanent_delete,
    async_batch_folder_permanent_delete,
)

__all__ = [
    # 基础工具
    '_delete_physical_folder_safe',
    '_delete_folder_contents_iterative',
    '_delete_folder_contents_recursive',
    # 任务函数
    'retry_clean_pending_files',
    'cleanup_old_chunks',
    'cleanup_expired_transfers',
    'cleanup_soft_deleted_files',
    'cleanup_soft_deleted_folders',
    'async_batch_permanent_delete',
    'async_batch_folder_permanent_delete',
]

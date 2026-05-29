# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
清理任务 Celery 任务

【第二阶段重构】
本文件现为兼容层，实际实现已迁移到 cleanup/ 目录下的多个文件：
- cleanup/base.py              # 基础工具函数
- cleanup/pending_files.py     # 待清理文件重试
- cleanup/chunks.py           # 过期分片清理
- cleanup/transfers.py        # 过期传输记录清理
- cleanup/soft_deleted.py     # 软删除数据清理
- cleanup/async_delete.py     # 异步批量删除

所有导入和调用保持向后兼容，无需修改现有代码。
"""

# 从新的模块结构导出所有任务和函数
# 使用完整路径导入，避免与 cleanup.py 文件名冲突
from apps.document.tasks.cleanup.base import (
    _delete_physical_folder_safe,
    _delete_folder_contents_iterative,
    _delete_folder_contents_recursive,
)
from apps.document.tasks.cleanup.pending_files import retry_clean_pending_files
from apps.document.tasks.cleanup.chunks import cleanup_old_chunks
from apps.document.tasks.cleanup.transfers import cleanup_expired_transfers
from apps.document.tasks.cleanup.soft_deleted import (
    cleanup_soft_deleted_files,
    cleanup_soft_deleted_folders,
)
from apps.document.tasks.cleanup.async_delete import (
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

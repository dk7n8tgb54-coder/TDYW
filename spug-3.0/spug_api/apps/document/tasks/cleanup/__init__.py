# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
清理任务模块（上传链路清理专用）

原 cleanup.py 已拆分为多个任务文件：
- base.py: 基础工具函数
- pending_files.py: 待清理文件重试（物理文件删除失败重试）
- chunks.py: 过期分片清理
- transfers.py: 过期传输记录清理
- orphan_transfers.py: 孤儿传输记录清理

说明：
- 回收站删除功能已于 2026-06-23 完全移除，原 soft_deleted.py / async_delete.py 不再保留。
- 本模块只负责上传链路相关清理，不再作为回收站删除兜底队列。
- 兼容性：所有保留任务保持原有名称和签名，无需修改调用方代码。
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

__all__ = [
    # 基础工具
    '_delete_physical_folder_safe',
    '_delete_folder_contents_iterative',
    '_delete_folder_contents_recursive',
    # 任务函数
    'retry_clean_pending_files',
    'cleanup_old_chunks',
    'cleanup_expired_transfers',
]

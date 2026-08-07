# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
Document 模块 Celery 任务导出
"""

from .merge import merge_file_chunks
from .batch.tasks import batch_delete_transfers, batch_cancel_transfers
from .cleanup.chunks import cleanup_old_chunks
from .cleanup.transfers import cleanup_expired_transfers
from .cleanup.pending_files import retry_clean_pending_files
from .pack import pack_folder_to_zip, cleanup_expired_pack_tasks
from .timeout_checker import (
    check_merge_timeout,
    cleanup_stale_merging_tasks,
)
from .cleanup.orphan_transfers import cleanup_orphan_transfers
# 【缩略图异步化】新增缩略图异步生成任务
from .thumbnail import generate_document_thumbnail
# 【大文件异步复制】新增异步复制任务
from .async_copy import copy_file_async

__all__ = [
    'merge_file_chunks',
    'batch_delete_transfers',
    'batch_cancel_transfers',
    'cleanup_old_chunks',
    'cleanup_expired_transfers',
    'retry_clean_pending_files',
    'pack_folder_to_zip',
    'cleanup_expired_pack_tasks',
    'check_merge_timeout',
    'cleanup_stale_merging_tasks',
    'cleanup_orphan_transfers',
    'generate_document_thumbnail',
    'copy_file_async',
]

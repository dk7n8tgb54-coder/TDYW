# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
Document 模块视图子包

【目录优化完成】
新目录结构：
├── __init__.py          # 统一导出
├── base.py              # 基础工具函数
├── constants.py         # 视图层常量
├── disk.py              # 磁盘监控
├── search.py            # 搜索功能
├── file/                # 文件管理模块（已拆分）
│   ├── __init__.py
│   ├── views.py         # FileView（删除、列表）
│   ├── upload.py        # FileUploadView
│   ├── download.py      # FileDownloadView
│   ├── preview.py       # FilePreviewView
│   ├── copy.py          # FileCopyView
│   ├── move.py          # FileMoveView
│   └── rename.py        # FileRenameView
├── folder/              # 文件夹管理模块（已拆分）
│   ├── __init__.py
│   ├── views.py         # FolderView（CRUD、列表）
│   ├── copy.py          # FolderCopyView
│   ├── move.py          # FolderMoveView
│   ├── download.py      # FolderDownloadView
│   └── rename.py        # FolderRenameView
├── upload/              # 上传管理模块（已拆分）
│   ├── __init__.py
│   ├── lock.py          # MergeLock、锁管理
│   ├── chunk.py         # FileChunkUploadView
│   ├── merge.py         # FileMergeChunksView
│   ├── resume.py        # CheckUploadedChunksView
│   └── status.py        # FileMergeStatusView
├── transfer/            # 传输记录模块
│   └── __init__.py      # 传输相关视图
"""

# 基础工具函数
from .base import (
    format_file_size,
    check_public_space_permission,
    permission_denied_response,
    MIME_TYPES,
    get_mime_type,
    handle_view_errors,
    log_operation,
    is_safe_path,
    create_model_instance,
    validate_file_name,
    validate_file_upload,
)

# 清理函数
from ..tasks.cleanup import cleanup_old_chunks

# 磁盘使用监控
from .disk import DiskUsageView

# 搜索
from .search import FolderSearchView

# 文件管理模块（新子目录结构）
from .file import (
    FileView,
    FileUploadView,
    FileDownloadView,
    FilePreviewView,
    FileCopyView,
    FileMoveView,
    FileRenameView,
)

# 文件夹管理模块（新子目录结构）
from .folder import (
    FolderView,
    FolderCopyView,
    FolderMoveView,
    FolderDownloadView,
    FolderRenameView,
)

# 上传管理模块（新子目录结构）
from .upload import (
    FileChunkUploadView,
    FileMergeChunksView,
    CheckUploadedChunksView,
    FileMergeStatusView,
    MergeLock,
    get_merge_lock,
    cleanup_stale_locks,
)

# 传输管理模块（通过子目录）
from .transfer import (
    TransferListView,
    TransferCreateView,
    TransferProgressUpdateView,
    TransferCompleteView,
    TransferCancelView,
    TransferStatusUpdateView,
    TransferDeleteView,
    TransferHashUpdateView,
    TransferFailView,
    TransferBatchPauseView,
    TransferBatchResumeView,
    TransferBatchCancelView,
    TransferBatchDeleteView,
)

__all__ = [
    # 工具函数
    'format_file_size',
    'check_public_space_permission',
    'permission_denied_response',
    'MIME_TYPES',
    'get_mime_type',
    'handle_view_errors',
    'log_operation',
    'is_safe_path',
    'create_model_instance',
    'validate_file_name',
    'validate_file_upload',
    # 清理函数
    'cleanup_old_chunks',
    # 磁盘使用
    'DiskUsageView',
    # 搜索
    'FolderSearchView',
    # 文件管理
    'FileView',
    'FileUploadView',
    'FileDownloadView',
    'FilePreviewView',
    'FileCopyView',
    'FileMoveView',
    'FileRenameView',
    # 文件夹管理
    'FolderView',
    'FolderCopyView',
    'FolderMoveView',
    'FolderDownloadView',
    'FolderRenameView',
    # 上传管理
    'FileChunkUploadView',
    'FileMergeChunksView',
    'CheckUploadedChunksView',
    'FileMergeStatusView',
    'MergeLock',
    'get_merge_lock',
    'cleanup_stale_locks',
    # 传输管理
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

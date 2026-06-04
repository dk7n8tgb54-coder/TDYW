# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
Document 模块 URL 配置

【优化后】使用子目录结构导入视图
"""
from django.urls import path

# 文件夹管理 - 从子目录导入
from .views.folder import (
    FolderView,
    FolderCopyView,
    FolderMoveView,
    FolderDownloadView,
    FolderRenameView,
    FolderDownloadStatusView,  # 【P0-6新增】异步打包状态查询
    FolderDownloadReadyView,   # 【P0-6新增】异步打包下载
)

# 搜索 - 独立模块
from .views.search import FolderSearchView

# 文件管理 - 从子目录导入
from .views.file import (
    FileView,
    FileUploadView,
    FileDownloadView,
    FilePreviewView,
    FileTextContentView,
    OfficePreviewUrlView,
    FileCopyView,
    FileMoveView,
    FileRenameView,
)

# 上传管理 - 从子目录导入
from .views.upload import (
    FileChunkUploadView,
    FileMergeChunksView,
    FileMergeStatusView,
    CheckUploadedChunksView,
    DirectMergeView,
)

# 磁盘使用 - 独立模块
from .views.disk import DiskUsageView

# 传输管理 - 从子目录导入
from .views.transfer import (
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

# 回收站管理 - 从子目录导入
from .views.recycle_bin import (
    RecycleBinView,
    RecycleBinRestoreView,
    RecycleBinPermanentDeleteView,
    RecycleBinTaskStatusView,
    RecycleBinStatsView,
    RecycleBinFolderRestoreView,
    RecycleBinFolderPermanentDeleteView,
    RecycleBinFolderContentView,
)

# 健康检查
from .views.health import (
    HealthCheckView, 
    CeleryHealthView,
    DatabasePoolStatusView,
    DatabasePoolMetricsView,
)

urlpatterns = [
    # 文件夹管理
    path('folder/', FolderView.as_view()),
    path('folder/search/', FolderSearchView.as_view()),
    
    # 文件管理
    path('file/', FileView.as_view()),
    path('upload/', FileUploadView.as_view()),
    path('download/', FileDownloadView.as_view()),
    path('preview/', FilePreviewView.as_view()),
    path('text_content/', FileTextContentView.as_view()),
    path('office_preview_url/', OfficePreviewUrlView.as_view()),
    path('file/copy/', FileCopyView.as_view()),
    path('file/move/', FileMoveView.as_view()),
    path('file/rename/', FileRenameView.as_view()),
    
    # 文件夹操作
    path('folder/copy/', FolderCopyView.as_view()),
    path('folder/move/', FolderMoveView.as_view()),
    path('folder/download/', FolderDownloadView.as_view()),
    path('folder/rename/', FolderRenameView.as_view()),
    # 【P0-6新增】异步打包相关
    path('folder/download/status/', FolderDownloadStatusView.as_view()),
    path('folder/download/ready/', FolderDownloadReadyView.as_view()),
    
    # 分片上传
    path('upload_chunk/', FileChunkUploadView.as_view()),
    path('merge_chunks/', FileMergeChunksView.as_view()),
    path('merge_status/', FileMergeStatusView.as_view()),
    path('check_uploaded_chunks/', CheckUploadedChunksView.as_view()),
    path('direct_merge/', DirectMergeView.as_view()),  # 【P0-Day1新增】直接合并接口
    
    # 磁盘使用
    path('disk_usage/', DiskUsageView.as_view()),
    
    # 传输记录相关接口
    path('transfers/', TransferListView.as_view()),
    path('transfers/create/', TransferCreateView.as_view()),
    path('transfers/<int:transfer_id>/progress/', TransferProgressUpdateView.as_view()),
    path('transfers/<int:transfer_id>/complete/', TransferCompleteView.as_view()),
    path('transfers/<int:transfer_id>/cancel/', TransferCancelView.as_view()),
    path('transfers/<int:transfer_id>/status/', TransferStatusUpdateView.as_view()),
    path('transfers/<int:transfer_id>/delete/', TransferDeleteView.as_view()),
    path('transfers/<int:transfer_id>/fail/', TransferFailView.as_view()),
    path('transfers/<int:transfer_id>/update_hash/', TransferHashUpdateView.as_view()),
    
    # 批量操作接口
    path('transfers/batch/pause/', TransferBatchPauseView.as_view()),
    path('transfers/batch/resume/', TransferBatchResumeView.as_view()),
    path('transfers/batch/cancel/', TransferBatchCancelView.as_view()),
    path('transfers/batch/delete/', TransferBatchDeleteView.as_view()),
    
    # 回收站接口
    path('recycle-bin/', RecycleBinView.as_view()),
    path('recycle-bin/restore/', RecycleBinRestoreView.as_view()),
    path('recycle-bin/permanent/', RecycleBinPermanentDeleteView.as_view()),
    path('recycle-bin/task-status/', RecycleBinTaskStatusView.as_view()),
    path('recycle-bin/stats/', RecycleBinStatsView.as_view()),
    
    # 【新增】文件夹恢复和彻底删除
    path('recycle-bin/folder-restore/', RecycleBinFolderRestoreView.as_view()),
    path('recycle-bin/folder-permanent/', RecycleBinFolderPermanentDeleteView.as_view()),
    
    # 【新增】查看已删除文件夹内容
    path('recycle-bin/folder-content/', RecycleBinFolderContentView.as_view()),
    
    # 健康检查
    path('health/', HealthCheckView.as_view()),
    path('health/celery/', CeleryHealthView.as_view()),
    
    # 【新增】数据库连接池监控
    path('health/db-pool/', DatabasePoolStatusView.as_view()),
    path('health/db-pool/metrics/', DatabasePoolMetricsView.as_view()),
]

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文档模块常量定义

包含传输状态、操作类型、配置默认值等常量
"""
from enum import Enum


# ==================== 传输状态机 ====================
class TransferStatus(Enum):
    """传输记录状态"""
    PENDING = "PENDING"           # 等待中
    UPLOADING = "UPLOADING"       # 上传中
    PAUSED = "PAUSED"             # 已暂停
    MERGING = "MERGING"           # 合并中
    COMPLETED = "COMPLETED"       # 已完成
    FAILED = "FAILED"             # 失败
    CANCELED = "CANCELED"         # 已取消


# ==================== 传输类型 ====================
class TransferType(Enum):
    """传输类型"""
    UPLOAD = "UPLOAD"             # 上传
    DOWNLOAD = "DOWNLOAD"         # 下载


# ==================== 操作类型（用于审计） ====================
class DocumentOperationType(Enum):
    """文档操作类型"""
    # 文件操作
    UPLOAD_FILE = "upload_file"
    DOWNLOAD_FILE = "download_file"
    DELETE_FILE = "delete_file"
    MOVE_FILE = "move_file"
    RENAME_FILE = "rename_file"
    COPY_FILE = "copy_file"
    PREVIEW_FILE = "preview_file"

    # 文件夹操作
    CREATE_FOLDER = "create_folder"
    DELETE_FOLDER = "delete_folder"
    MOVE_FOLDER = "move_folder"
    RENAME_FOLDER = "rename_folder"
    COPY_FOLDER = "copy_folder"
    DOWNLOAD_FOLDER = "download_folder"

    # 传输操作
    PAUSE_TRANSFER = "pause_transfer"
    RESUME_TRANSFER = "resume_transfer"
    CANCEL_TRANSFER = "cancel_transfer"
    DELETE_TRANSFER = "delete_transfer"

    # 批量操作
    BATCH_PAUSE_TRANSFER = "batch_pause_transfer"
    BATCH_RESUME_TRANSFER = "batch_resume_transfer"
    BATCH_CANCEL_TRANSFER = "batch_cancel_transfer"
    BATCH_DELETE_TRANSFER = "batch_delete_transfer"


# ==================== 资源类型 ====================
class ResourceType(Enum):
    """资源类型"""
    FILE = "FILE"               # 文件
    FOLDER = "FOLDER"           # 文件夹
    TRANSFER = "TRANSFER"       # 传输记录


# ==================== 空间类型 ====================
class SpaceType(Enum):
    """空间类型"""
    PUBLIC = "PUBLIC"           # 公共空间
    PRIVATE = "PRIVATE"         # 私有空间


# ==================== 配置项默认值 ====================
# 文件夹递归最大深度
DEFAULT_MAX_FOLDER_DEPTH = 100

# 文件上传最大大小（字节，默认10GB）
DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024

# 分片文件清理时间（秒，默认24小时）
DEFAULT_CHUNK_CLEANUP_AGE = 24 * 3600

# 合并锁超时时间（秒，默认10分钟）
DEFAULT_MERGE_LOCK_TIMEOUT = 600

# 合并状态查询超时时间（秒，默认5分钟）
DEFAULT_MERGE_STATUS_TIMEOUT = 300


# ==================== 传输状态转换规则 ====================
# 允许的状态转换（用于状态机验证）
ALLOWED_STATUS_TRANSITIONS = {
    # 前端支持 waiting(=PENDING) 状态直接暂停，因此允许 PENDING -> PAUSED
    # 【P1-修复】普通上传（无分片合并）需要支持 PENDING -> COMPLETED
    TransferStatus.PENDING: [TransferStatus.UPLOADING, TransferStatus.PAUSED, TransferStatus.CANCELED, TransferStatus.COMPLETED],
    # 上传中允许用户主动取消
    TransferStatus.UPLOADING: [TransferStatus.PAUSED, TransferStatus.MERGING, TransferStatus.FAILED, TransferStatus.CANCELED],
    TransferStatus.PAUSED: [TransferStatus.UPLOADING, TransferStatus.CANCELED],
    # 合并中保留取消能力（与现有取消接口行为保持一致）
    TransferStatus.MERGING: [TransferStatus.COMPLETED, TransferStatus.FAILED, TransferStatus.CANCELED],
    TransferStatus.COMPLETED: [],  # 终态
    TransferStatus.FAILED: [TransferStatus.UPLOADING, TransferStatus.CANCELED],  # 允许重试（P1修复：FAILED可直接到UPLOADING）
    TransferStatus.CANCELED: [],  # 终态
}


def is_valid_status_transition(current_status: TransferStatus, new_status: TransferStatus) -> bool:
    """
    检查状态转换是否有效

    Args:
        current_status: 当前状态
        new_status: 目标状态

    Returns:
        bool: 如果转换有效返回True，否则返回False
    """
    return new_status in ALLOWED_STATUS_TRANSITIONS.get(current_status, [])

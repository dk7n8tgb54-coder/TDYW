# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文档管理工具函数
提供路径生成、模型获取、权限校验、MD5计算等核心功能
"""
import os
import hashlib
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

# 【性能优化】延迟导入模型，避免启动时加载
def _get_models():
    """延迟导入模型"""
    from apps.document.models import (
        DocumentFolderPrivate, DocumentFilePrivate,
        DocumentFolderPublic, DocumentFilePublic
    )
    return DocumentFolderPrivate, DocumentFilePrivate, DocumentFolderPublic, DocumentFilePublic

# MIME类型映射表
MIME_TYPES = {
    '.mp4': 'video/mp4',
    '.avi': 'video/x-msvideo',
    '.mov': 'video/quicktime',
    '.wmv': 'video/x-ms-wmv',
    '.flv': 'video/x-flv',
    '.mkv': 'video/x-matroska',
    '.webm': 'video/webm',
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.flac': 'audio/flac',
    '.aac': 'audio/aac',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.bmp': 'image/bmp',
    '.webp': 'image/webp',
    '.svg': 'image/svg+xml',
    '.pdf': 'application/pdf',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls': 'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.ppt': 'application/vnd.ms-powerpoint',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.txt': 'text/plain',
    '.zip': 'application/zip',
    '.rar': 'application/x-rar-compressed',
    '.7z': 'application/x-7z-compressed',
}

# 【修复】延迟获取递归深度，避免启动时访问未配置的settings
def _get_max_recursion_depth():
    return getattr(settings, 'MAX_FOLDER_RECURSION_DEPTH', 100)


# ==================== 循环引用检测工具函数 ====================
def is_child_folder(child_id, parent_id, FolderModel, request_user=None, is_public=False):
    """
    检查child_id是否是parent_id的子文件夹（防止循环引用）

    Args:
        child_id: 子文件夹ID
        parent_id: 父文件夹ID
        FolderModel: 文件夹模型类
        request_user: 请求用户（用于租户过滤）
        is_public: 是否为公共空间

    Returns:
        bool: 如果child_id是parent_id的子文件夹返回True，否则返回False
    """
    visited_ids = set()  # 防止无限循环
    username = getattr(request_user, 'username', 'Unknown') if request_user else 'Unknown'

    while True:
        # 检查是否已访问（防止循环引用）
        if child_id in visited_ids:
            logger.warning(
                f'[Document] 检测到循环引用，folder_id={child_id} 已被访问！'
                f'user={username}, parent_id={parent_id}'
            )
            return True
        visited_ids.add(child_id)

        # 递归深度限制
        max_depth = _get_max_recursion_depth()
        if len(visited_ids) > max_depth:
            logger.warning(
                f'[Document] is_child_folder 超过最大递归深度: {max_depth}，'
                f'可能存在循环引用！user={username}, child_id={child_id}, parent_id={parent_id}'
            )
            return False

        # 私有空间：必须验证租户归属
        child_query = FolderModel.objects.filter(pk=child_id)
        if request_user and not is_public:
            from libs.tenant_utils import apply_tenant_filter
            child_query = apply_tenant_filter(child_query, request_user)

        child = child_query.first()
        if not child:
            return False

        # 检查是否找到目标父文件夹
        if child.parent_id == parent_id:
            return True

        # 到达根节点，未找到
        if child.parent_id is None:
            return False

        child_id = child.parent_id


# ==================== 路径生成工具函数 ====================
def get_document_relative_path(is_public=False, user_id=None, folder_id=None):
    """
    生成文档相对路径（相对于 storage/documents 目录）

    Args:
        is_public: 是否公共空间
        user_id: 用户ID（私有空间必需）
        folder_id: 文件夹ID（可选）

    Returns:
        str: 相对路径，如 'private/user-1/' 或 'public/' 或 'public/folder-123/'
    """
    if is_public:
        # 公共空间路径：public/ 或 public/folder-{id}/
        if folder_id:
            return f'public/folder-{folder_id}'
        return 'public'
    else:
        # 私有空间路径：private/user-{id}/ 或 private/user-{id}/folder-{id}/
        if not user_id:
            raise ValueError('私有空间必须提供 user_id')
        if folder_id:
            return f'private/user-{user_id}/folder-{folder_id}'
        return f'private/user-{user_id}'


def get_document_absolute_path(is_public=False, user_id=None, folder_id=None):
    """
    生成文档绝对路径

    Args:
        is_public: 是否公共空间
        user_id: 用户ID（私有空间必需）
        folder_id: 文件夹ID（可选）

    Returns:
        str: 绝对路径，如 '/path/to/storage/documents/private/user-1/'
    """
    base_dir = os.path.join(settings.BASE_DIR, 'storage', 'documents')
    relative_path = get_document_relative_path(is_public, user_id, folder_id)
    return os.path.join(base_dir, relative_path)


def is_safe_path(base_path, target_path):
    """
    验证目标路径是否在基础路径内，防止路径遍历攻击

    Args:
        base_path: 基础路径
        target_path: 目标路径

    Returns:
        bool: True 表示安全，False 表示存在路径遍历风险
    """
    base_path = os.path.normpath(base_path)
    target_path = os.path.normpath(target_path)
    try:
        # 确保目标路径在基础路径内
        common_prefix = os.path.commonpath([base_path, target_path])
        return common_prefix == base_path
    except ValueError:
        # 路径在不同驱动器上（Windows）
        return False


# ==================== 模型获取工具函数 ====================
def get_folder_model(is_public=False):
    """
    根据是否公共空间获取文件夹模型

    Args:
        is_public: 是否公共空间

    Returns:
        Model: DocumentFolderPrivate 或 DocumentFolderPublic
    """
    DocumentFolderPrivate, _, DocumentFolderPublic, _ = _get_models()
    return DocumentFolderPublic if is_public else DocumentFolderPrivate


def get_file_model(is_public=False):
    """
    根据是否公共空间获取文件模型

    Args:
        is_public: 是否公共空间

    Returns:
        Model: DocumentFilePrivate 或 DocumentFilePublic
    """
    _, DocumentFilePrivate, _, DocumentFilePublic = _get_models()
    return DocumentFilePublic if is_public else DocumentFilePrivate


def is_global_admin(user):
    """
    判断用户是否为全局管理员
    适配项目的权限体系：检查 is_supper 或全局管理员角色

    Args:
        user: 用户对象

    Returns:
        bool: True 表示是管理员，False 表示普通用户
    """
    from libs.tenant_utils import is_superuser
    return is_superuser(user)


def calculate_file_md5(file_path, chunk_size=1024*1024):
    """
    计算文件的MD5哈希值（使用分块读取，避免大文件内存溢出）

    Args:
        file_path: 文件绝对路径
        chunk_size: 每次读取的字节数（默认1MB，优化大文件计算速度）

    Returns:
        str: 32位MD5哈希字符串

    Raises:
        FileNotFoundError: 文件不存在
        IOError: 读取文件失败
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f'File not found: {file_path}')

    md5_hash = hashlib.md5()
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            md5_hash.update(chunk)

    return md5_hash.hexdigest()


# 【任务3.3】抽样MD5计算的阈值（与前端保持一致：500MB）
SAMPLING_MD5_THRESHOLD = 500 * 1024 * 1024  # 500MB
SAMPLING_MD5_SAMPLE_SIZE = 2 * 1024 * 1024  # 2MB


def calculate_sampling_md5(file_path):
    """
    【任务3.3】计算文件的抽样MD5（用于大文件）
    
    对于超大文件，只计算头部、中部、尾部各2MB的MD5，
    大幅提升计算速度，同时保持较高的唯一性。
    
    Args:
        file_path: 文件绝对路径
        
    Returns:
        str: 抽样MD5标识，格式：sv1_{size}_{hash1}_{hash2}_{hash3}
        
    Raises:
        FileNotFoundError: 文件不存在
        IOError: 读取文件失败
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f'File not found: {file_path}')
    
    file_size = os.path.getsize(file_path)
    
    # 如果文件小于阈值，使用全量MD5
    if file_size < SAMPLING_MD5_THRESHOLD:
        return calculate_file_md5(file_path)
    
    # 计算抽样块的MD5
    sample_hashes = []
    sample_size = SAMPLING_MD5_SAMPLE_SIZE
    
    with open(file_path, 'rb') as f:
        # 头部抽样
        f.seek(0)
        head_chunk = f.read(sample_size)
        head_md5 = hashlib.md5(head_chunk).hexdigest()
        sample_hashes.append(head_md5)
        
        # 中部抽样
        if file_size > sample_size * 2:
            middle_start = (file_size - sample_size) // 2
            f.seek(middle_start)
            middle_chunk = f.read(sample_size)
            middle_md5 = hashlib.md5(middle_chunk).hexdigest()
            sample_hashes.append(middle_md5)
            
            # 尾部抽样
            f.seek(-sample_size, 2)  # 从文件末尾倒数2MB
            tail_chunk = f.read(sample_size)
            tail_md5 = hashlib.md5(tail_chunk).hexdigest()
            sample_hashes.append(tail_md5)
    
    # 生成抽样MD5标识（与前端格式一致）
    # 格式: sv1_{size(6位base36)}_{hash1(16位)}_{hash2(16位)}_{hash3(16位)}
    import string
    
    def to_base36(n):
        """将整数转换为base36字符串"""
        chars = string.digits + string.ascii_lowercase
        if n == 0:
            return '0'
        result = ''
        while n:
            n, remainder = divmod(n, 36)
            result = chars[remainder] + result
        return result
    
    size_str = to_base36(file_size)[:6].zfill(6)  # 确保6位，不足前面补0
    h1 = sample_hashes[0][:16]
    h2 = sample_hashes[1][:16] if len(sample_hashes) > 1 else '0'
    h3 = sample_hashes[2][:16] if len(sample_hashes) > 2 else '0'

    return f'sv1_{size_str}_{h1}_{h2}_{h3}'


# ==================== 分片路径生成工具函数 ====================
def get_chunk_dir_path(file_hash, is_public, request_user):
    """
    【P0修复】统一的分片目录路径生成函数
    确保所有视图的路径生成逻辑完全一致
    
    Args:
        file_hash: 文件MD5哈希值（32位全量MD5或抽样MD5）
        is_public: 是否为公共空间
        request_user: 请求用户对象
        
    Returns:
        str: 分片目录绝对路径，如 '/path/to/storage/document_chunks/public_1_2/abc123...'
        
    Raises:
        ValueError: 如果file_hash格式不正确
    """
    # 【任务3.2修复】验证MD5哈希格式（支持全量MD5和抽样MD5）
    is_valid_full_md5 = file_hash and isinstance(file_hash, str) and len(file_hash) == 32
    is_valid_sampling_md5 = file_hash and isinstance(file_hash, str) and file_hash.startswith('sv1_')
    if not (is_valid_full_md5 or is_valid_sampling_md5):
        raise ValueError(f'Invalid file_hash format: {file_hash}')
    
    chunk_base_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_chunks')
    
    if is_public:
        # 公共空间：简化路径，只使用 public
        tenant_path = "public"
    else:
        # 私有空间：租户ID隔离
        tenant_path = getattr(request_user, 'tenant_id', 'default') or 'default'
    
    return os.path.join(chunk_base_dir, tenant_path, file_hash)


# ==================== MIME类型工具函数 ====================
def get_mime_type(file_name):
    """根据文件名获取 MIME 类型"""
    file_ext = os.path.splitext(file_name)[1].lower()
    return MIME_TYPES.get(file_ext, 'application/octet-stream')


# ==================== 模型创建工具函数 ====================
def create_model_instance(Model, **kwargs):
    """
    创建模型实例的辅助函数，自动处理 tenant_id 字段
    公共模型没有 tenant_id 字段，私有模型有

    Args:
        Model: Django模型类
        **kwargs: 模型字段参数

    Returns:
        Model: 创建的模型实例
    """
    if hasattr(Model, 'tenant_id') and 'tenant_id' not in kwargs:
        user = kwargs.get('created_by')
        if user and hasattr(user, 'tenant_id'):
            kwargs['tenant_id'] = user.tenant_id or ''
    return Model.objects.create(**kwargs)

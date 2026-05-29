# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from django.http import HttpResponse
from libs import json_response, JsonParser, Argument, auth
from .libs.document_utils import get_folder_model, get_file_model, is_child_folder, get_chunk_dir_path
from .models import DocumentTransfer
from .constants import (
    TransferStatus, is_valid_status_transition,
    DEFAULT_MAX_FOLDER_DEPTH, DEFAULT_MAX_FILE_SIZE,
    DEFAULT_CHUNK_CLEANUP_AGE,
    DEFAULT_MERGE_LOCK_TIMEOUT, DEFAULT_MERGE_STATUS_TIMEOUT
)
from apps.libs.tenant_utils import apply_tenant_filter, check_tenant_unique_name
import os
import re
import logging
import json
import threading
import time
from django.conf import settings
from django.db.models import Sum, Q
from django.db import transaction
from django.utils import timezone
from functools import wraps

logger = logging.getLogger(__name__)

# 从配置文件读取文档模块参数
MAX_RECURSION_DEPTH = getattr(settings, 'MAX_FOLDER_RECURSION_DEPTH', DEFAULT_MAX_FOLDER_DEPTH)
MAX_FILE_SIZE = getattr(settings, 'MAX_DOCUMENT_FILE_SIZE', DEFAULT_MAX_FILE_SIZE)
CHUNK_CLEANUP_AGE = getattr(settings, 'DOCUMENT_CHUNK_CLEANUP_AGE', DEFAULT_CHUNK_CLEANUP_AGE)
MERGE_STATUS_TIMEOUT = getattr(settings, 'DOCUMENT_MERGE_STATUS_TIMEOUT', DEFAULT_MERGE_STATUS_TIMEOUT)  # 合并状态查询超时时间（秒）



# 【P1-3修复】合并锁超时配置（秒）
MERGE_LOCK_TIMEOUT = DEFAULT_MERGE_LOCK_TIMEOUT


# 全局合并锁字典（用于防止并发合并同一文件）
_merge_locks = {}
_merge_locks_mutex = threading.Lock()


class MergeLock:
    """【P1-3修复】带超时的合并锁"""

    def __init__(self):
        self.lock = threading.Lock()
        self.acquired_time = None
        self.holder = None  # 持有者标识

    def acquire(self, timeout=None, blocking=True):
        """获取锁"""
        if blocking:
            # 带超时的阻塞获取
            acquired = self.lock.acquire(timeout=timeout)
            if acquired:
                self.acquired_time = time.time()
                self.holder = threading.get_ident()
            return acquired
        else:
            # 非阻塞获取
            acquired = self.lock.acquire(blocking=False)
            if acquired:
                self.acquired_time = time.time()
                self.holder = threading.get_ident()
            return acquired

    def release(self):
        """释放锁"""
        if self.lock.locked():
            self.acquired_time = None
            self.holder = None
            self.lock.release()

    def is_locked(self):
        """检查锁是否被持有"""
        return self.lock.locked()

    def get_held_duration(self):
        """获取锁被持有的时长"""
        if self.acquired_time:
            return time.time() - self.acquired_time
        return None


def get_merge_lock(file_hash, is_public, tenant_id):
    """
    【P1-3修复】获取按file_hash+空间类型+租户的无嵌套合并锁

    Args:
        file_hash: 文件MD5哈希值
        is_public: 是否为公共空间
        tenant_id: 租户ID

    Returns:
        MergeLock对象
    """
    # 【P1-3修复】锁粒度优化：包含空间类型和租户ID
    lock_key = f"{file_hash}_{'public' if is_public else 'private'}_{tenant_id or 'default'}"

    with _merge_locks_mutex:
        if lock_key not in _merge_locks:
            _merge_locks[lock_key] = MergeLock()
        return _merge_locks[lock_key]


def cleanup_stale_locks():
    """【P1-3修复】清理长时间持有的锁（定期调用）"""
    current_time = time.time()
    cleaned_count = 0

    with _merge_locks_mutex:
        stale_locks = []
        for lock_key, lock_obj in list(_merge_locks.items()):
            if lock_obj.is_locked():
                duration = lock_obj.get_held_duration()
                if duration and duration > MERGE_LOCK_TIMEOUT * 2:  # 超过2倍超时时间
                    stale_locks.append(lock_key)
                    logger.warning(
                        f'[Document] Found stale merge lock: {lock_key}, '
                        f'held for {duration:.1f}s, timeout={MERGE_LOCK_TIMEOUT}s'
                    )

        # 强制释放过期锁（最后手段，不应频繁发生）
        for lock_key in stale_locks:
            lock_obj = _merge_locks[lock_key]
            try:
                lock_obj.release()
                cleaned_count += 1
                logger.info(f'[Document] Force released stale lock: {lock_key}')
            except Exception as e:
                logger.error(f'[Document] Failed to release stale lock {lock_key}: {e}')

    if cleaned_count > 0:
        logger.info(f'[Document] Cleanup stale locks completed: {cleaned_count} locks cleaned')

    return cleaned_count


def format_file_size(size_bytes):
    """格式化文件大小为可读格式"""
    if size_bytes is None:
        return '未知大小'
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f'{size_bytes:.2f} {unit}'
        size_bytes /= 1024
    return f'{size_bytes:.2f} PB'


def check_public_space_permission(request_user, resource_obj, resource_type='file', operation='操作'):
    """
    检查公共空间权限（仅管理员或创建人可操作）

    Args:
        request_user: 当前请求用户
        resource_obj: 资源对象（文件夹或文件）
        resource_type: 资源类型，'folder' 或 'file'
        operation: 操作类型，用于错误提示

    Returns:
        bool: True表示有权限，False表示无权限
    """
    # 超级管理员可以操作所有资源
    if getattr(request_user, 'is_supper', False):
        return True

    # 检查是否为创建人
    if getattr(resource_obj, 'created_by_id', None) != request_user.id:
        logger.warning(
            f'[Document] User {request_user.username} attempting to {operation}他人的公共'
            f'{resource_type} id:{resource_obj.id}'
        )
        return False

    return True


# MIME 类型映射表
MIME_TYPES = {
    # 文档
    '.pdf': 'application/pdf',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls': 'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.ppt': 'application/vnd.ms-powerpoint',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.txt': 'text/plain',
    '.rtf': 'application/rtf',
    # 图片
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.bmp': 'image/bmp',
    '.svg': 'image/svg+xml',
    '.webp': 'image/webp',
    '.ico': 'image/x-icon',
    # 音频
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.ogg': 'audio/ogg',
    '.aac': 'audio/aac',
    '.flac': 'audio/flac',
    # 视频
    '.mp4': 'video/mp4',
    '.avi': 'video/x-msvideo',
    '.mkv': 'video/x-matroska',
    '.mov': 'video/quicktime',
    '.wmv': 'video/x-ms-wmv',
    '.flv': 'video/x-flv',
    '.webm': 'video/webm',
    # 压缩文件
    '.zip': 'application/zip',
    '.rar': 'application/x-rar-compressed',
    '.7z': 'application/x-7z-compressed',
    '.tar': 'application/x-tar',
    '.gz': 'application/gzip',
    # 代码
    '.js': 'text/javascript',
    '.json': 'application/json',
    '.xml': 'application/xml',
    '.html': 'text/html',
    '.css': 'text/css',
    '.py': 'text/x-python',
    '.java': 'text/x-java-source',
    '.c': 'text/x-c',
    '.cpp': 'text/x-c++',
    '.h': 'text/x-c',
    '.hpp': 'text/x-c++',
    # 工程文件
    '.dwg': 'application/octet-stream',
    '.dxf': 'application/octet-stream',
    '.stp': 'application/octet-stream',
    '.iges': 'application/octet-stream',
    '.igs': 'application/octet-stream',
    '.igs': 'application/octet-stream',
}


def get_mime_type(file_name):
    """根据文件名获取 MIME 类型"""
    file_ext = os.path.splitext(file_name)[1].lower()
    return MIME_TYPES.get(file_ext, 'application/octet-stream')


def handle_view_errors(func):
    """统一处理视图错误的装饰器"""
    @wraps(func)
    def wrapper(self, request, *args, **kwargs):
        try:
            return func(self, request, *args, **kwargs)
        except json.JSONDecodeError:
            logger.error(f'[Document] JSON解析错误: {request.body}')
            return json_response(error='参数格式错误')
        except Exception as e:
            import traceback
            logger.error(f'[Document] 未处理的异常: {str(e)}')
            logger.error(f'[Document] 异常堆栈:\n{traceback.format_exc()}')
            logger.error(f'[Document] 请求路径: {request.path}, 方法: {request.method}')
            logger.error(f'[Document] 请求用户: {request.user.username if hasattr(request, "user") else "Unknown"}')
            logger.error(f'[Document] 请求参数: GET={request.GET}, POST={request.POST if hasattr(request, "POST") else "N/A"}')
            return json_response(error='服务器内部错误')
    return wrapper


def log_operation(action, user, resource_type, resource_id, **kwargs):
    """
    统一的审计日志函数

    Args:
        action: 操作类型 (CREATE, DELETE, UPDATE, DOWNLOAD, etc.)
        user: 用户对象
        resource_type: 资源类型 (FILE, FOLDER, etc.)
        resource_id: 资源ID
        **kwargs: 额外信息
    """
    tenant_id = getattr(user, 'tenant_id', 'N/A')
    is_public = kwargs.get('is_public', False)
    details = ', '.join([f'{k}={v}' for k, v in kwargs.items() if k != 'is_public'])

    logger.info(
        f'[TenantAudit] Action={action}, User={user.username}, '
        f'Tenant={tenant_id}, IsPublic={is_public}, '
        f'Type={resource_type}, ID={resource_id}, {details}'
    )


def is_safe_path(base_path, target_path):
    """验证目标路径是否在基础路径内，防止路径遍历"""
    base_path = os.path.normpath(base_path)
    target_path = os.path.normpath(target_path)
    try:
        # 确保目标路径在基础路径内
        common_prefix = os.path.commonpath([base_path, target_path])
        return common_prefix == base_path
    except ValueError:
        # 路径在不同驱动器上（Windows）
        return False


def create_model_instance(Model, **kwargs):
    """
    创建模型实例的辅助函数，自动处理 tenant_id 字段
    公共模型没有 tenant_id 字段，私有模型有
    """
    if hasattr(Model, 'tenant_id') and 'tenant_id' not in kwargs:
        user = kwargs.get('created_by')
        if user and hasattr(user, 'tenant_id'):
            kwargs['tenant_id'] = user.tenant_id or ''
    return Model.objects.create(**kwargs)


def validate_file_name(file_name):
    """校验文件名，防止路径遍历和非法字符"""
    # 检查路径遍历攻击
    if '..' in file_name:
        return False
    # 检查文件系统非法字符
    forbidden_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for char in forbidden_chars:
        if char in file_name:
            return False
    # 检查文件名长度
    if len(file_name) == 0 or len(file_name) > 255:
        return False
    return True


def validate_file_upload(file_name, file_size, max_file_size=None):
    """增强的文件上传验证"""
    # 验证文件名
    if not validate_file_name(file_name):
        return False, "文件名包含非法字符"

    # 验证文件大小
    if not isinstance(file_size, (int, float)) or file_size <= 0:
        return False, "文件大小必须为正数"

    if max_file_size and file_size > max_file_size:
        max_mb = max_file_size / (1024 * 1024)
        return False, f"文件大小超过限制（最大{max_mb:.1f}MB）"

    # 验证文件类型
    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext not in MIME_TYPES and file_ext:
        return False, "不支持的文件类型"

    return True, "验证通过"


class FolderSearchView(View):
    @auth('document.document.view')
    def get(self, request):
        """递归搜索文件夹和文件"""
        logger.info(f'[Document] FolderSearchView.get called, user: {request.user.username}')
        form, error = JsonParser(
            Argument('folder_id', type=int, required=False, default=None),
            Argument('keyword', type=str, required=False),
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)

        if error is None:
            if not form.keyword or form.keyword.strip() == '':
                return json_response({'folders': [], 'files': []})

            keyword = form.keyword.strip().lower()

            # 根据 is_public 参数获取对应的模型
            FolderModel = get_folder_model(is_public=form.is_public)
            FileModel = get_file_model(is_public=form.is_public)

            # 获取所有需要搜索的文件夹ID（递归获取子树）
            folder_ids_to_search = self._get_descendant_folder_ids(
                form.folder_id, FolderModel, request.user, form.is_public
            )

            # 搜索匹配的文件夹
            folders_query = FolderModel.objects.filter(
                id__in=folder_ids_to_search,
                name__icontains=keyword
            ).select_related('created_by')

            # 私有空间：添加租户过滤
            if not form.is_public:
                folders_query = apply_tenant_filter(folders_query, request.user)

            folders = list(folders_query)

            # 搜索匹配的文件（在所有目标文件夹内）
            files_query = FileModel.objects.filter(
                folder_id__in=folder_ids_to_search,
                name__icontains=keyword
            ).select_related('created_by')

            # 私有空间：添加租户过滤
            if not form.is_public:
                files_query = apply_tenant_filter(files_query, request.user)

            files = list(files_query)

            # 构建文件夹ID到路径的映射
            folder_id_to_path = self._build_folder_path_map(folder_ids_to_search, FolderModel, request.user, form.is_public)

            # 格式化返回结果
            result = {
                'folders': [
                    {
                        'id': f.id,
                        'name': f.name,
                        'parent_id': f.parent_id,
                        'path': folder_id_to_path.get(f.id, ''),
                        'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        'created_by': f.created_by.nickname if f.created_by else None,
                        'created_by_id': f.created_by_id
                    } for f in folders
                ],
                'files': []
            }

            # 格式化文件数据
            for f in files:
                file_size = f.file_size
                if file_size >= 1024 * 1024:
                    size = f'{file_size / 1024 / 1024:.2f} MB'
                elif file_size >= 1024:
                    size = f'{file_size / 1024:.2f} KB'
                else:
                    size = f'{file_size} B'

                result['files'].append({
                    'id': f.id,
                    'name': f.name,
                    'display_name': f.display_name if hasattr(f, 'display_name') else None,
                    'folder_id': f.folder_id,
                    'size': size,
                    'file_type': f.file_type,
                    'path': folder_id_to_path.get(f.folder_id, ''),
                    'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'created_by': f.created_by.nickname if f.created_by else None,
                    'created_by_id': f.created_by_id
                })

            logger.info(f'[Document] 搜索结果: folders={len(folders)}, files={len(files)}')
            return json_response(result)

        logger.error(f'[Document] Parse error: {error}')
        return json_response(error=error)

    def _get_descendant_folder_ids(self, start_folder_id, FolderModel, request_user, is_public):
        """
        获取起始文件夹及其所有后代文件夹的ID列表（广度优先搜索）
        """
        if start_folder_id is None:
            # 从根目录搜索，获取所有文件夹
            query = FolderModel.objects.all()
            if not is_public:
                query = apply_tenant_filter(query, request_user)
            return set(f.id for f in query)

        # 从指定文件夹开始搜索，获取该文件夹及其所有后代
        folder_ids = set([start_folder_id])
        visited_ids = set([start_folder_id])
        queue = [start_folder_id]
        depth = 0
        max_depth = MAX_RECURSION_DEPTH

        while queue and depth < max_depth:
            current_batch_size = len(queue)
            depth += 1

            # 批量查询所有父文件夹的子文件夹（避免 N+1 查询）
            parent_ids = queue[:current_batch_size]
            queue = queue[current_batch_size:]  # 移除当前批次的父文件夹

            # 一次性查询所有子文件夹
            child_folders_query = FolderModel.objects.filter(parent_id__in=parent_ids)
            if not is_public:
                child_folders_query = apply_tenant_filter(child_folders_query, request_user)

            for child in child_folders_query:
                if child.id not in visited_ids:
                    visited_ids.add(child.id)
                    folder_ids.add(child.id)
                    queue.append(child.id)

            # 如果没有找到子文件夹，提前退出
            if not child_folders_query.exists():
                break

        if depth >= max_depth:
            logger.warning(f'[Document] 搜索递归深度超限: {max_depth}, folder_id={start_folder_id}')

        return folder_ids

    def _build_folder_path_map(self, folder_ids, FolderModel, request_user, is_public):
        """
        构建文件夹ID到完整路径的映射
        返回: {folder_id: '父文件夹/子文件夹'}
        """
        folder_id_to_path = {}

        # 查询所有相关文件夹
        folders_query = FolderModel.objects.filter(id__in=folder_ids).select_related('created_by')
        if not is_public:
            folders_query = apply_tenant_filter(folders_query, request_user)

        # 构建 parent_id -> [folders] 的映射
        parent_to_children = {}
        folder_map = {}
        for f in folders_query:
            folder_map[f.id] = f
            parent_id = f.parent_id if f.parent_id else 0
            if parent_id not in parent_to_children:
                parent_to_children[parent_id] = []
            parent_to_children[parent_id].append(f)

        # 为每个文件夹构建路径
        def build_path(folder_id, visited_ids=None):
            if visited_ids is None:
                visited_ids = set()

            if folder_id in folder_id_to_path:
                return folder_id_to_path[folder_id]

            if folder_id in visited_ids:
                logger.warning(f'[Document] 检测到循环引用, folder_id={folder_id}')
                return ''

            visited_ids.add(folder_id)

            folder = folder_map.get(folder_id)
            if not folder:
                return ''

            if folder.parent_id is None:
                folder_id_to_path[folder_id] = folder.name
                return folder.name

            # 递归构建父路径
            parent_path = build_path(folder.parent_id, visited_ids)
            if parent_path:
                folder_id_to_path[folder_id] = f'{parent_path}/{folder.name}'
            else:
                folder_id_to_path[folder_id] = folder.name

            return folder_id_to_path[folder_id]

        for folder_id in folder_ids:
            if folder_id not in folder_id_to_path:
                build_path(folder_id)

        return folder_id_to_path


class FolderView(View):
    @auth('document.document.view')
    def get(self, request):
        logger.info(f'[Document] FolderView.get called, user: {request.user.username}')
        form, error = JsonParser(
            Argument('id', type=int, required=False, default=None),
            Argument('all', type=bool, required=False, default=False),
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)
        if error is None:
            # 根据 is_public 参数获取对应的模型
            FolderModel = get_folder_model(is_public=form.is_public)
            FileModel = get_file_model(is_public=form.is_public)

            # 获取所有文件夹（用于构建树）或子文件夹和文件
            if form.id is None:
                if form.all:
                    # 返回所有文件夹用于构建树（左侧文件夹树）
                    # 私有空间: 仅返回当前租户的文件夹
                    # 公共空间: 返回所有公共文件夹
                    query = FolderModel.objects.all().select_related('created_by')
                    if not form.is_public:
                        query = apply_tenant_filter(query, request.user)

                    all_folders = list(query)
                    result = [
                        {'id': f.id, 'name': f.name, 'parent_id': f.parent_id, 'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'), 'created_by': f.created_by.nickname if f.created_by else None, 'created_by_id': f.created_by_id}
                        for f in all_folders
                    ]
                    return json_response(result)
                else:
                    # 只返回根目录下的文件夹（parent_id=None）- 用于 Explorer
                    folders_query = FolderModel.objects.filter(parent__isnull=True).select_related('created_by')
                    if not form.is_public:
                        folders_query = apply_tenant_filter(folders_query, request.user)

                    folders = list(folders_query)
                    # 查询根目录下的文件（folder_id为NULL）
                    files_query = FileModel.objects.filter(folder__isnull=True).select_related('created_by')
                    if not form.is_public:
                        files_query = apply_tenant_filter(files_query, request.user)

                    files = list(files_query)
                    result = {
                        'folders': [{'id': f.id, 'name': f.name, 'parent_id': f.parent_id, 'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'), 'created_by': f.created_by.nickname if f.created_by else None, 'created_by_id': f.created_by_id} for f in folders],
                        'files': []
                    }
            else:
                # 返回指定文件夹下的子文件夹和文件
                folders_query = FolderModel.objects.filter(parent_id=form.id).select_related('created_by')
                if not form.is_public:
                    folders_query = apply_tenant_filter(folders_query, request.user)

                folders = list(folders_query)

                files_query = FileModel.objects.filter(folder_id=form.id).select_related('created_by')
                if not form.is_public:
                    files_query = apply_tenant_filter(files_query, request.user)

                files = list(files_query)
                result = {
                    'folders': [{'id': f.id, 'name': f.name, 'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'), 'created_by': f.created_by.nickname if f.created_by else None, 'created_by_id': f.created_by_id} for f in folders],
                    'files': []
                }

            # 处理文件数据
            for f in files:
                file_size = f.file_size
                if file_size >= 1024 * 1024:
                    size = f'{file_size / 1024 / 1024:.2f} MB'
                elif file_size >= 1024:
                    size = f'{file_size / 1024:.2f} KB'
                else:
                    size = f'{file_size} B'
                result['files'].append({
                    'id': f.id,
                    'name': f.name,
                    'display_name': f.display_name if hasattr(f, 'display_name') else None,
                    'size': size,
                    'file_type': f.file_type,
                    'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'created_by': f.created_by.nickname if f.created_by else None,
                    'created_by_id': f.created_by_id
                })
            return json_response(result)
        logger.error(f'[Document] Parse error: {error}')
        return json_response(error=error)

    @auth('document.document.create_folder')
    def post(self, request):
        import json
        try:
            data = json.loads(request.body)
            name = data.get('name')
            parent_id = data.get('parent_id')
            is_public = data.get('is_public', False)
        except Exception as e:
            logger.error(f'解析请求参数失败: {e}')
            return json_response(error='参数错误')

        if not name:
            return json_response(error='请输入文件夹名称')

        # 校验文件夹名称安全性
        if not validate_file_name(name):
            return json_response(error='文件夹名称包含非法字符')

        # 根据 is_public 参数获取对应的模型
        FolderModel = get_folder_model(is_public=is_public)

        # 检查文件夹名称是否重复
        if parent_id:
            # 验证 parent_id 是否为有效整数
            try:
                parent_id = int(parent_id)
            except (ValueError, TypeError):
                return json_response(error='父文件夹ID无效')

            # 验证 parent_id 是否为正数
            if parent_id <= 0:
                return json_response(error='父文件夹ID无效')

            parent_query = FolderModel.objects.filter(pk=parent_id)
            if not is_public:
                parent_query = apply_tenant_filter(parent_query, request.user)
            parent = parent_query.first()
            if not parent:
                return json_response(error='父文件夹不存在')
            # 检查同一父文件夹下是否存在同名文件夹
            # 私有空间：每个用户独立目录，允许同名文件夹；公共空间：禁止同名文件夹
            if is_public:
                # 公共空间：检查所有用户创建的同名文件夹
                if FolderModel.objects.filter(parent_id=parent_id, name=name).exists():
                    return json_response(error='文件夹名称已存在')
            else:
                # 私有空间：仅检查当前用户创建的同名文件夹
                if FolderModel.objects.filter(parent_id=parent_id, name=name, created_by=request.user).exists():
                    return json_response(error='文件夹名称已存在')
            new_folder = create_model_instance(FolderModel, name=name, parent=parent, created_by=request.user)
        else:
            # 检查根目录下是否存在同名文件夹
            if is_public:
                # 公共空间：检查所有用户创建的同名文件夹
                if FolderModel.objects.filter(parent__isnull=True, name=name).exists():
                    return json_response(error='文件夹名称已存在')
            else:
                # 私有空间：仅检查当前用户创建的同名文件夹
                if FolderModel.objects.filter(parent__isnull=True, name=name, created_by=request.user).exists():
                    return json_response(error='文件夹名称已存在')
            new_folder = create_model_instance(FolderModel, name=name, created_by=request.user)
        return json_response({'id': new_folder.id})

    @auth('document.document.delete')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)
        if error is None:
            # 根据 is_public 参数获取对应的模型
            FolderModel = get_folder_model(is_public=form.is_public)
            FileModel = get_file_model(is_public=form.is_public)

            folder_query = FolderModel.objects.filter(pk=form.id)
            if not form.is_public:
                folder_query = apply_tenant_filter(folder_query, request.user)
            folder = folder_query.first()
            if not folder:
                return json_response(error='文件夹不存在')

            # 公共空间权限校验：仅管理员或创建人可删除
            if form.is_public and not check_public_space_permission(request.user, folder, 'folder', '删除'):
                return json_response(error='公共空间中只能删除自己创建的文件夹')

            try:
                # 删除文件夹及其所有内容
                self._delete_folder(folder, FolderModel, FileModel, form.is_public, request.user)
                log_operation(
                    action="FOLDER_DELETE",
                    user=request.user,
                    resource_type="FOLDER",
                    resource_id=folder.id,
                    is_public=form.is_public,
                    folder_name=folder.name
                )
                return json_response()
            except Exception as e:
                logger.error(f'[Document] Error deleting folder {folder.name}: {e}')
                return json_response(error=f'文件夹删除失败: {str(e)}')
        return json_response(error=error)

    def _delete_folder(self, folder, FolderModel, FileModel, is_public, request_user=None):
        # 耗时监控：开始时间
        import time
        start_time = time.time()

        # 【P0修复】分批处理删除，避免大事务
        BATCH_SIZE = 50  # 每批处理50个文件

        # 第一步：递归删除子文件夹（正确顺序：先子后父）
        sub_folders_query = FolderModel.objects.filter(parent=folder)
        # 私有空间：添加租户过滤
        if request_user and not is_public:
            from apps.libs.tenant_utils import apply_tenant_filter
            sub_folders_query = apply_tenant_filter(sub_folders_query, request_user)
        sub_folders_count = sub_folders_query.count()
        logger.info(f'[Document] Deleting folder {folder.name} (id={folder.id}) with {sub_folders_count} subfolders')
        if sub_folders_count > 0:
            for sub_folder in sub_folders_query:
                self._delete_folder(sub_folder, FolderModel, FileModel, is_public, request_user)

        # 第二步：分批删除当前文件夹下的文件（避免大事务）
        delete_errors = []
        from django.db import transaction
        files = folder.files.all().select_related('created_by')
        files_count = files.count()
        logger.info(f'[Document] Deleting {files_count} files in folder {folder.name}')

        # 【P0修复】分批删除，每批处理BATCH_SIZE个文件
        total_deleted = 0
        for batch_start in range(0, files_count, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, files_count)
            batch_files = files[batch_start:batch_end]
            batch_files_list = list(batch_files)

            try:
                with transaction.atomic():  # 每批一个独立事务
                    for file in batch_files_list:
                        try:
                            # 删除物理文件
                            if os.path.exists(file.file_path):
                                os.remove(file.file_path)
                            # 删除数据库记录
                            file.delete()
                        except Exception as e:
                            delete_errors.append(f"文件{file.name}删除失败: {str(e)}")
                            logger.error(f'[Document] Failed to delete file {file.name}: {e}')

                    total_deleted += len(batch_files_list)
                    logger.info(f'[Document] Batch delete progress: {total_deleted}/{files_count} files deleted')

            except Exception as batch_error:
                logger.error(f'[Document] Batch delete failed at batch {batch_start//BATCH_SIZE}: {batch_error}')
                delete_errors.append(f"批次删除失败: {str(batch_error)}")

        # 第三步：删除当前文件夹的物理目录（仅在所有子项删除后）
        try:
            from .libs.document_utils import get_document_absolute_path
            # 私有空间：使用文件夹创建者的用户ID（而不是当前删除操作的用户ID）
            # 因为物理路径是基于创建者的 user_id 创建的
            if not is_public:
                # 获取文件夹创建者的用户ID
                folder_creator_id = folder.created_by.id if folder.created_by else (request_user.id if request_user else None)
                user_id_for_path = folder_creator_id
            else:
                # 公共空间不需要 user_id
                user_id_for_path = None

            # 使用正确的路径函数获取文件夹存储目录
            folder_storage_dir = get_document_absolute_path(
                is_public=is_public,
                user_id=user_id_for_path,
                folder_id=folder.id
            )
            if os.path.exists(folder_storage_dir):
                import shutil
                logger.info(f'[Document] Removing folder storage directory: {folder_storage_dir}')
                shutil.rmtree(folder_storage_dir)
                logger.info(f'[Document] Deleted folder storage directory: {folder_storage_dir}')
            else:
                logger.info(f'[Document] Folder storage directory does not exist: {folder_storage_dir}')
        except Exception as e:
            logger.error(f'[Document] Error deleting folder storage directory: {e}')

        # 第四步：删除文件夹数据库记录
        folder.delete()

        # 耗时监控：超过4分钟打告警日志
        cost = time.time() - start_time
        if cost > 240:  # 4分钟
            logger.warning(f'[Document] FolderDelete 耗时过长: folder_id={folder.id}, name={folder.name}, cost={cost:.2f}秒')
        logger.info(f'[Document] Folder {folder.name} (id={folder.id}) deleted successfully, cost={cost:.2f}秒')


class FileView(View):
    @auth('document.document.delete')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)
        if error is None:
            # 根据 is_public 参数获取对应的模型
            FileModel = get_file_model(is_public=form.is_public)

            file_query = FileModel.objects.filter(pk=form.id)
            if not form.is_public:
                file_query = apply_tenant_filter(file_query, request.user)
            file = file_query.select_related('created_by').first()
            if not file:
                return json_response(error='文件不存在')

            # 公共空间权限校验：仅管理员或创建人可删除
            if form.is_public and not check_public_space_permission(request.user, file, 'file', '删除'):
                return json_response(error='公共空间中只能删除自己创建的文件')

            try:
                self._delete_file(file, form.is_public)
                log_operation(
                    action="FILE_DELETE",
                    user=request.user,
                    resource_type="FILE",
                    resource_id=file.id,
                    is_public=form.is_public,
                    file_name=file.name
                )
                return json_response()
            except Exception as e:
                logger.error(f'[Document] Error deleting file: {e}')
                return json_response(error=f'文件删除失败: {str(e)}')
        return json_response(error=error)

    def _delete_file(self, file_obj, is_public=False):
        """
        安全删除文件：先删数据库，再删物理文件
        - 事务保护：确保数据库删除原子性
        - 物理删除失败：记录日志但不影响数据库删除（避免僵尸文件）
        """
        # 【P0修复】先删除数据库记录，确保原子性
        file_obj.delete()
        logger.info(f'[Document] Deleted database record: file_id={file_obj.id}, file_path={file_obj.file_path}')

        # 【P0修复】再删除物理文件，失败不影响一致性（通过后台清理任务处理）
        if os.path.exists(file_obj.file_path):
            try:
                os.remove(file_obj.file_path)
                logger.info(f'[Document] Deleted physical file: {file_obj.file_path}')
            except Exception as e:
                # 物理文件删除失败不影响数据库删除的一致性
                # 后台清理任务会自动清理孤立的物理文件
                logger.warning(f'[Document] Failed to delete physical file {file_obj.file_path}: {e}, will be cleaned up by background task')


class FileUploadView(View):
    @auth('document.document.upload')
    @handle_view_errors
    def post(self, request):
        # 手动解析 FormData 参数，因为 JsonParser 可能无法正确处理 FormData 中的整数类型
        folder_id = request.POST.get('folder_id')
        is_public = request.POST.get('is_public', 'false').lower() == 'true'

        logger.info(f'[Document] FileUploadView.post called, user: {request.user.username}, is_public: {is_public}, folder_id: {folder_id}')

        if folder_id:
            try:
                folder_id = int(folder_id)
            except (ValueError, TypeError):
                folder_id = None

        # 根据 is_public 参数获取对应的模型
        FolderModel = get_folder_model(is_public=is_public)
        FileModel = get_file_model(is_public=is_public)

        if folder_id:
            folder_query = FolderModel.objects.filter(pk=folder_id)
            if not is_public:
                folder_query = apply_tenant_filter(folder_query, request.user)
            folder = folder_query.first()
            if not folder:
                return json_response(error='文件夹不存在')
        else:
            folder = None

        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')

        # 校验文件名安全性
        if not validate_file_name(file.name):
            return json_response(error='文件名包含非法字符或路径遍历符号')

        # 验证文件大小和类型
        is_valid, msg = validate_file_upload(file.name, file.size, max_file_size=10 * 1024 * 1024 * 1024)  # 10GB
        if not is_valid:
            return json_response(error=msg)

        # 创建上传目录（根据 is_public 使用不同路径）
        from .libs.document_utils import get_document_absolute_path
        upload_dir = get_document_absolute_path(
            is_public=is_public,
            user_id=request.user.id,
            folder_id=folder_id
        )
        logger.info(f'[Document] Upload directory: {upload_dir}')
        os.makedirs(upload_dir, exist_ok=True)

        # 生成唯一文件名（使用用户ID、时间戳和UUID随机后缀防止冲突）
        import time
        import uuid
        file_ext = os.path.splitext(file.name)[1]
        file_base = os.path.splitext(file.name)[0]

        # 截断基础文件名（保留120字符，为其他后缀预留空间，避免文件名过长）
        max_base_name_length = 120
        if len(file_base) > max_base_name_length:
            file_base = file_base[:max_base_name_length]

        timestamp = int(time.time())
        random_suffix = uuid.uuid4().hex[:8]
        unique_name = f"{file_base}_{request.user.id}_{timestamp}_{random_suffix}{file_ext}"

        # 验证总长度不超过255字符
        if len(unique_name) > 255:
            logger.error(f'[Document] Unique file name too long: {len(unique_name)} characters')
            return json_response(error='文件名过长，请缩短文件名后重试')

        file_path = os.path.join(upload_dir, unique_name)

        # 保存文件
        logger.info(f'[Document] Saving file to: {file_path}')
        with open(file_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)
        logger.info(f'[Document] File saved successfully: {file_path}')

        # 创建文件记录（name存唯一物理名，display_name存用户上传的原名称）
        logger.info(f'[Document] Creating file record: unique_name={unique_name}, display_name={file.name}, is_public={is_public}, FileModel={FileModel.__name__}')
        try:
            new_file = create_model_instance(FileModel,
                name=unique_name,  # 物理文件名（唯一）
                display_name=file.name,  # 显示名称（用户看到的文件名）
                folder=folder,
                file_path=file_path,
                file_size=file.size,
                file_type=file.content_type or get_mime_type(file.name),
                created_by=request.user
            )
            logger.info(f'[Document] File record created successfully: id={new_file.id}, name={unique_name}, display_name={file.name}')
        except Exception as e:
            logger.error(f'[Document] Failed to create file record: {e}')
            logger.error(f'[Document] FileModel has tenant_id: {hasattr(FileModel, "tenant_id")}')
            logger.error(f'[Document] request.user.tenant_id: {getattr(request.user, "tenant_id", "N/A")}')
            raise
        log_operation(
            action="FILE_UPLOAD",
            user=request.user,
            resource_type="FILE",
            resource_id=new_file.id,
            is_public=is_public,
            file_name=file.name,
            unique_name=unique_name,
            file_size=file.size,
            folder_id=folder.id if folder else None
        )
        return json_response()


class FileDownloadView(View):
    @auth('document.document.view')
    def get(self, request):
        logger.info(f'[Document] FileDownloadView.get called, user: {request.user.username}')
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)
        if error is None:
            # 根据 is_public 参数获取对应的模型
            FileModel = get_file_model(is_public=form.is_public)

            logger.info(f'[Document] Downloading file id: {form.id}, is_public={form.is_public}')
            file_query = FileModel.objects.filter(pk=form.id)
            if not form.is_public:
                file_query = apply_tenant_filter(file_query, request.user)
            file = file_query.select_related('created_by').first()
            if not file:
                logger.error(f'[Document] File not found with id: {form.id}')
                return json_response(error='文件不存在')
            logger.info(f'[Document] File path: {file.file_path}, exists: {os.path.exists(file.file_path)}')
            if not os.path.exists(file.file_path):
                logger.error(f'[Document] Physical file not found: {file.file_path}')
                return json_response(error='文件不存在')

            # 公共空间下载权限：允许所有人下载
            # 私有空间已通过租户过滤确保只能下载自己租户的文件

            with open(file.file_path, 'rb') as f:
                response = HttpResponse(f.read())
                from urllib.parse import quote
                # 优先使用display_name，兼容旧数据
                display_name = file.display_name or file.name
                encoded_filename = quote(display_name)
                response['Content-Disposition'] = f'attachment; filename="{encoded_filename}"; filename*=UTF-8\'\'{encoded_filename}'
                response['Content-Type'] = file.file_type
                log_operation(
                    action="FILE_DOWNLOAD",
                    user=request.user,
                    resource_type="FILE",
                    resource_id=file.id,
                    is_public=form.is_public,
                    file_name=display_name,
                    file_size=file.file_size
                )
                logger.info(f'[Document] File download successful: {file.name}, is_public={form.is_public}')
                return response
        logger.error(f'[Document] Download parse error: {error}')
        return json_response(error=error)


class FilePreviewView(View):
    @auth('document.document.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)
        if error is None:
            # 根据 is_public 参数获取对应的模型
            FileModel = get_file_model(is_public=form.is_public)

            file_query = FileModel.objects.filter(pk=form.id)
            if not form.is_public:
                file_query = apply_tenant_filter(file_query, request.user)
            file = file_query.select_related('created_by').first()
            if not file:
                return json_response(error='文件不存在')
            if not os.path.exists(file.file_path):
                return json_response(error='文件不存在')

            # 公共空间预览权限：允许所有人预览
            # 私有空间已通过租户过滤确保只能预览自己租户的文件

            # 支持图片预览
            if file.file_type.startswith('image/'):
                with open(file.file_path, 'rb') as f:
                    response = HttpResponse(f.read())
                    response['Content-Type'] = file.file_type
                    return response
            # 支持PDF预览
            elif file.file_type == 'application/pdf' or file.file_type.startswith('application/pdf'):
                with open(file.file_path, 'rb') as f:
                    response = HttpResponse(f.read())
                    response['Content-Type'] = 'application/pdf'
                    response['Content-Disposition'] = f'inline; filename="{file.name}"'
                    return response
            # 支持视频流
            elif file.file_type.startswith('video/'):
                response = HttpResponse()
                response['Content-Type'] = file.file_type
                response['X-Content-Type-Options'] = 'nosniff'
                response['Accept-Ranges'] = 'bytes'

                # 处理Range请求（支持视频进度条）
                range_header = request.META.get('HTTP_RANGE', '').strip()
                file_size = os.path.getsize(file.file_path)

                if range_header:
                    # 解析Range头
                    try:
                        range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
                        if range_match:
                            start = int(range_match.group(1))
                            end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                            content_length = end - start + 1
                            response.status_code = 206
                            response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
                            response['Content-Length'] = str(content_length)

                            with open(file.file_path, 'rb') as f:
                                f.seek(start)
                                response.content = f.read(content_length)
                    except Exception as e:
                        logger.error(f'[Document] Error parsing range header: {e}')
                        # Range解析失败，返回完整文件
                        with open(file.file_path, 'rb') as f:
                            response.status_code = 200
                            response['Content-Length'] = str(file_size)
                            response.content = f.read()
                else:
                    # 没有Range请求，返回完整文件
                    with open(file.file_path, 'rb') as f:
                        response.status_code = 200
                        response['Content-Length'] = str(file_size)
                        response.content = f.read()
                return response
            else:
                return json_response(error='该文件类型不支持在线预览')
        return json_response(error=error)


class FileCopyView(View):
    @auth('document.document.copy')
    def post(self, request):
        logger.info(f'[Document] FileCopyView.post called, user: {request.user.username}')
        import json
        try:
            data = json.loads(request.body)
            file_id = data.get('id')
            folder_id = data.get('folder_id')
            is_public = data.get('is_public', False)
        except:
            return json_response(error='参数错误')

        if not file_id:
            return json_response(error='参数错误')

        # 根据 is_public 参数获取对应的模型
        FileModel = get_file_model(is_public=is_public)
        FolderModel = get_folder_model(is_public=is_public)

        logger.info(f'[Document] Copying file id: {file_id} to folder_id: {folder_id}, is_public={is_public}')
        file_query = FileModel.objects.filter(pk=file_id)
        if not is_public:
            file_query = apply_tenant_filter(file_query, request.user)
        file = file_query.select_related('created_by').first()
        if not file:
            logger.error(f'[Document] Source file not found with id: {file_id}')
            return json_response(error='文件不存在')

        # 公共空间权限校验：仅管理员或创建人可复制
        if is_public and not check_public_space_permission(request.user, file, 'file', '复制'):
            return json_response(error='公共空间中只能复制自己创建的文件')

        if folder_id:
            folder_query = FolderModel.objects.filter(pk=folder_id)
            if not is_public:
                folder_query = apply_tenant_filter(folder_query, request.user)
            folder = folder_query.first()
            if not folder:
                logger.error(f'[Document] Target folder not found with id: {folder_id}')
                return json_response(error='目标文件夹不存在')
        else:
            # 允许复制到根目录（folder 为 None）
            folder = None

        # 复制文件 - 使用统一的路径生成函数
        from .libs.document_utils import get_document_absolute_path
        upload_dir = get_document_absolute_path(
            is_public=is_public,
            user_id=request.user.id,
            folder_id=folder.id if folder else None
        )
        os.makedirs(upload_dir, exist_ok=True)

        # 生成复制文件的唯一物理文件名
        import uuid
        file_ext = os.path.splitext(file.file_path)[1]
        timestamp = int(time.time())
        random_suffix = uuid.uuid4().hex[:8]
        unique_name = f"copy_{file.id}_{request.user.id}_{timestamp}_{random_suffix}{file_ext}"
        new_file_path = os.path.join(upload_dir, unique_name)

        logger.info(f'[Document] Copying from {file.file_path} to {new_file_path}')

        # 复制物理文件
        import shutil
        shutil.copy2(file.file_path, new_file_path)

        logger.info(f'[Document] Physical file copied successfully')

        # 判断是否在同一文件夹中
        is_same_folder = file.folder == folder

        # 确定新文件的显示名称（display_name）
        # 优先使用display_name，兼容旧数据
        original_display_name = file.display_name or file.name

        # 如果原始文件的display_name为null，则从物理文件名中提取原始名称
        # 物理文件名格式：{hash}_{index}_{timestamp}_{uuid}_{original_name}
        if not file.display_name:
            # 尝试从物理文件名中提取原始名称
            parts = file.name.split('_')
            if len(parts) >= 4:
                # 最后一部分是原始文件名
                original_display_name = '_'.join(parts[4:])

        new_display_name = original_display_name
        if is_same_folder:
            new_display_name = f'副本_{original_display_name}'

        # 检查目标文件夹下是否已存在同名显示名称（添加租户过滤）
        existing_file_query = FileModel.objects.filter(
            folder=folder,
            display_name=new_display_name
        )
        # 私有空间：添加租户过滤
        if not is_public:
            existing_file_query = apply_tenant_filter(existing_file_query, request.user)
        existing_file = existing_file_query.first()

        if existing_file:
            # 如果同名显示名称已存在，添加数字后缀
            counter = 1
            while True:
                name_without_ext, ext = os.path.splitext(new_display_name)
                new_display_name = f'{name_without_ext}_{counter}{ext}'
                existing_file_query = FileModel.objects.filter(
                    folder=folder,
                    display_name=new_display_name
                )
                # 私有空间：添加租户过滤
                if not is_public:
                    existing_file_query = apply_tenant_filter(existing_file_query, request.user)
                existing_file = existing_file_query.first()
                if not existing_file:
                    break
                counter += 1

        # 创建新文件记录（name存物理名，display_name存显示名）
        new_file = create_model_instance(FileModel,
            name=unique_name,  # 物理文件名（唯一）
            display_name=new_display_name,  # 显示名称
            folder=folder,
            file_path=new_file_path,
            file_size=file.file_size,
            file_type=file.file_type,
            created_by=request.user
        )
        log_operation(
            action="FILE_COPY",
            user=request.user,
            resource_type="FILE",
            resource_id=new_file.id,
            is_public=is_public,
            source_file_id=file.id,
            original_display_name=original_display_name,
            new_display_name=new_display_name,
            target_folder_id=folder.id if folder else None
        )
        logger.info(f'[Document] File record created successfully, is_public={is_public}')
        return json_response()


class FolderCopyView(View):
    @auth('document.document.copy')
    def post(self, request):
        import json
        try:
            data = json.loads(request.body)
            folder_id = data.get('id')
            target_id = data.get('target_id')
            is_public = data.get('is_public', False)
        except:
            return json_response(error='参数错误')

        if not folder_id:
            return json_response(error='参数错误')

        # 根据 is_public 参数获取对应的模型
        FolderModel = get_folder_model(is_public=is_public)
        FileModel = get_file_model(is_public=is_public)

        source_folder_query = FolderModel.objects.filter(pk=folder_id)
        if not is_public:
            source_folder_query = apply_tenant_filter(source_folder_query, request.user)
        source_folder = source_folder_query.select_related('created_by').first()
        if not source_folder:
            return json_response(error='源文件夹不存在')

        # 公共空间权限校验：仅管理员或创建人可复制
        if is_public and not check_public_space_permission(request.user, source_folder, 'folder', '复制'):
            return json_response(error='公共空间中只能复制自己创建的文件夹')

        if target_id:
            target_folder_query = FolderModel.objects.filter(pk=target_id)
            if not is_public:
                target_folder_query = apply_tenant_filter(target_folder_query, request.user)
            target_folder = target_folder_query.first()
            if not target_folder:
                return json_response(error='目标文件夹不存在')
        else:
            # 允许复制到根目录（target_folder 为 None）
            target_folder = None

        logger.info(f'[Document] Copying folder {source_folder.name} (id={folder_id}) to target folder id={target_id}, is_public={is_public}')

        # 检查是否复制到自身或子文件夹（使用公共函数）
        if source_folder.id == target_id or (target_id and is_child_folder(target_id, source_folder.id, FolderModel, request.user, is_public)):
            return json_response(error='无法复制到自身或子文件夹下')

        # 递归复制文件夹及其内容
        self._copy_folder_recursive(source_folder, target_folder, request.user, FolderModel, FileModel, is_public)
        log_operation(
            action="FOLDER_COPY",
            user=request.user,
            resource_type="FOLDER",
            resource_id=source_folder.id,
            is_public=is_public,
            source_folder_name=source_folder.name,
            target_folder_id=target_folder.id if target_folder else None
        )
        return json_response()

    def _copy_folder_recursive(self, source_folder, target_parent, user, FolderModel, FileModel, is_public):
        # 判断是否在同一文件夹中
        is_same_folder = source_folder.parent == target_parent

        # 确定新文件夹名称
        new_name = source_folder.name
        if is_same_folder:
            new_name = f'副本_{source_folder.name}'

        # 检查目标文件夹下是否已存在同名文件夹（添加租户过滤）
        existing_folder_query = FolderModel.objects.filter(
            parent=target_parent,
            name=new_name
        )
        # 私有空间：添加租户过滤
        if user and not is_public:
            existing_folder_query = apply_tenant_filter(existing_folder_query, user)
        existing_folder = existing_folder_query.first()

        if existing_folder:
            # 如果同名文件夹已存在，添加数字后缀
            counter = 1
            while True:
                new_name = f'{new_name}_{counter}'
                existing_folder_query = FolderModel.objects.filter(
                    parent=target_parent,
                    name=new_name
                )
                # 私有空间：添加租户过滤
                if user and not is_public:
                    existing_folder_query = apply_tenant_filter(existing_folder_query, user)
                existing_folder = existing_folder_query.first()
                if not existing_folder:
                    break
                counter += 1

        # 创建新文件夹
        new_folder = create_model_instance(FolderModel,
            name=new_name,
            parent=target_parent,
            created_by=user
        )
        logger.info(f'[Document] Created new folder: {new_name} (id={new_folder.id}) with parent_id={target_parent.id if target_parent else None}, is_public={is_public}')

        # 复制子文件夹
        child_folders_query = FolderModel.objects.filter(parent=source_folder)
        # 私有空间：添加租户过滤
        if user and not is_public:
            child_folders_query = apply_tenant_filter(child_folders_query, user)
        for child_folder in child_folders_query:
            self._copy_folder_recursive(child_folder, new_folder, user, FolderModel, FileModel, is_public)

        # 复制文件
        files_query = FileModel.objects.filter(folder=source_folder)
        # 私有空间：添加租户过滤
        if user and not is_public:
            files_query = apply_tenant_filter(files_query, user)

        # 使用统一的路径生成函数
        from .libs.document_utils import get_document_absolute_path
        upload_dir = get_document_absolute_path(
            is_public=is_public,
            user_id=user.id,
            folder_id=new_folder.id
        )
        os.makedirs(upload_dir, exist_ok=True)

        for file in files_query:
            import shutil
            # 文件复制到新文件夹目录
            file_ext = os.path.splitext(file.file_path)[1]
            unique_name = f"copy_{file.id}_{id(user)}{file_ext}"
            new_file_path = os.path.join(upload_dir, unique_name)

            shutil.copy2(file.file_path, new_file_path)

            # 【修复】处理display_name：如果原始文件的display_name为null，则从物理文件名中提取原始名称
            original_display_name = file.display_name or file.name
            if not file.display_name:
                # 尝试从物理文件名中提取原始名称
                parts = file.name.split('_')
                if len(parts) >= 4:
                    # 最后一部分是原始文件名
                    original_display_name = '_'.join(parts[4:])

            create_model_instance(FileModel,
                name=unique_name,  # 新的物理文件名（唯一）
                display_name=original_display_name,  # 显示名称
                folder=new_folder,
                file_path=new_file_path,
                file_size=file.file_size,
                file_type=file.file_type,
                created_by=user
            )


class FolderMoveView(View):
    @auth('document.document.move')
    def post(self, request):
        import json
        try:
            data = json.loads(request.body)
            folder_id = data.get('id')
            target_id = data.get('target_id')
            is_public = data.get('is_public', False)
        except:
            return json_response(error='参数错误')

        if not folder_id:
            return json_response(error='参数错误')

        # 根据 is_public 参数获取对应的模型
        FolderModel = get_folder_model(is_public=is_public)

        folder_query = FolderModel.objects.filter(pk=folder_id)
        if not is_public:
            folder_query = apply_tenant_filter(folder_query, request.user)
        folder = folder_query.select_related('created_by').first()
        if not folder:
            return json_response(error='文件夹不存在')

        # 公共空间权限校验：仅管理员或创建人可移动
        if is_public and not check_public_space_permission(request.user, folder, 'folder', '移动'):
            return json_response(error='公共空间中只能移动自己创建的文件夹')

        if target_id:
            target_query = FolderModel.objects.filter(pk=target_id)
            if not is_public:
                target_query = apply_tenant_filter(target_query, request.user)
            target = target_query.first()
            if not target:
                return json_response(error='目标文件夹不存在')
            # 防止循环引用（使用公共函数）
            if folder.id == target_id or is_child_folder(target.id, folder.id, FolderModel, request.user, is_public):
                return json_response(error='无法移动到自身或子文件夹下')

            # 检查目标位置是否已存在同名文件夹（添加租户过滤）
            is_unique, _ = check_tenant_unique_name(
                FolderModel,
                {'parent_id': target_id, 'name': folder.name},
                request.user,
                is_public
            )
            if not is_unique:
                return json_response(error='目标位置已存在同名文件夹')

            folder.parent = target
        else:
            # 检查根目录下是否已存在同名文件夹（添加租户过滤）
            is_unique, _ = check_tenant_unique_name(
                FolderModel,
                {'parent__isnull': True, 'name': folder.name},
                request.user,
                is_public
            )
            if not is_unique:
                return json_response(error='根目录已存在同名文件夹')

            folder.parent = None
        folder.save()
        log_operation(
            action="FOLDER_MOVE",
            user=request.user,
            resource_type="FOLDER",
            resource_id=folder.id,
            is_public=is_public,
            target_folder_id=target_id
        )
        logger.info(f'[Document] Folder moved successfully, is_public={is_public}')
        return json_response()


class FileMoveView(View):
    @auth('document.document.move')
    def post(self, request):
        import json
        try:
            data = json.loads(request.body)
            file_id = data.get('id')
            target_id = data.get('target_id')
            is_public = data.get('is_public', False)
        except:
            return json_response(error='参数错误')

        # 根据 is_public 参数获取对应的模型
        FileModel = get_file_model(is_public=is_public)
        FolderModel = get_folder_model(is_public=is_public)

        file_query = FileModel.objects.filter(pk=file_id)
        if not is_public:
            file_query = apply_tenant_filter(file_query, request.user)
        file = file_query.select_related('created_by').first()
        if not file:
            return json_response(error='文件不存在')

        # 公共空间权限校验：仅管理员或创建人可移动
        if is_public and not check_public_space_permission(request.user, file, 'file', '移动'):
            return json_response(error='公共空间中只能移动自己创建的文件')

        # 确定当前目标目录 - 使用统一的路径生成函数
        if target_id:
            target_query = FolderModel.objects.filter(pk=target_id)
            if not is_public:
                target_query = apply_tenant_filter(target_query, request.user)
            target = target_query.first()
            if not target:
                return json_response(error='目标文件夹不存在')

        from .libs.document_utils import get_document_absolute_path
        target_dir = get_document_absolute_path(
            is_public=is_public,
            user_id=request.user.id,
            folder_id=target_id
        )

        # 如果文件已经在目标文件夹中，不需要移动
        current_folder_id = file.folder.id if file.folder else None
        if current_folder_id == target_id:
            return json_response()

        # 移动物理文件
        try:
            os.makedirs(target_dir, exist_ok=True)
            import shutil
            original_name = file.name  # 保存原始文件名
            file_name = os.path.basename(file.file_path)
            new_file_path = os.path.join(target_dir, file_name)
            new_name = original_name  # 默认使用原始文件名

            # 如果目标位置已存在同名文件，添加序号后缀
            if os.path.exists(new_file_path):
                name_without_ext, ext = os.path.splitext(original_name)
                counter = 1
                while os.path.exists(os.path.join(target_dir, f"{name_without_ext}_{counter}{ext}")):
                    counter += 1
                new_name = f"{name_without_ext}_{counter}{ext}"
                new_file_path = os.path.join(target_dir, new_name)
                logger.info(f'[Document] File name conflict resolved: {original_name} -> {new_name}')

            shutil.move(file.file_path, new_file_path)

            # 同时更新路径和文件名
            file.file_path = new_file_path
            file.name = new_name
        except Exception as e:
            logger.error(f'[Document] Error moving file: {e}')
            return json_response(error=f'文件移动失败: {str(e)}')

        # 更新文件关联
        if target_id:
            file.folder = target
        else:
            file.folder = None
        file.save()
        log_operation(
            action="FILE_MOVE",
            user=request.user,
            resource_type="FILE",
            resource_id=file.id,
            is_public=is_public,
            original_name=original_name,
            new_name=new_name,
            target_folder_id=target_id
        )
        logger.info(f'[Document] File moved successfully, is_public={is_public}')
        return json_response()


class FolderDownloadView(View):
    @auth('document.document.view')
    def get(self, request):
        logger.info(f'[Document] FolderDownloadView.get called, user: {request.user.username}')
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)
        if error is None:
            # 根据 is_public 参数获取对应的模型
            FolderModel = get_folder_model(is_public=form.is_public)
            FileModel = get_file_model(is_public=form.is_public)

            logger.info(f'[Document] Downloading folder id: {form.id}, is_public={form.is_public}')
            folder_query = FolderModel.objects.filter(pk=form.id)
            if not form.is_public:
                folder_query = apply_tenant_filter(folder_query, request.user)
            folder = folder_query.select_related('created_by').first()
            if not folder:
                logger.error(f'[Document] Folder not found with id: {form.id}')
                return json_response(error='文件夹不存在')

            # 公共空间下载权限：允许所有人下载
            # 私有空间已通过租户过滤确保只能下载自己租户的文件

            import io
            import zipfile
            from urllib.parse import quote

            # 创建内存中的 ZIP 文件
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                self._add_folder_to_zip(folder, zipf, '', FolderModel, FileModel, form.is_public, request.user)

            zip_buffer.seek(0)

            # 创建响应
            response = HttpResponse(zip_buffer.read())
            encoded_foldername = quote(folder.name)
            response['Content-Disposition'] = f'attachment; filename="{encoded_foldername}.zip"; filename*=UTF-8\'\'{encoded_foldername}.zip'
            response['Content-Type'] = 'application/zip'
            log_operation(
                action="FOLDER_DOWNLOAD",
                user=request.user,
                resource_type="FOLDER",
                resource_id=folder.id,
                is_public=form.is_public,
                folder_name=folder.name
            )
            logger.info(f'[Document] Folder download successful: {folder.name}.zip, is_public={form.is_public}')
            return response
        logger.error(f'[Document] Download parse error: {error}')
        return json_response(error=error)

    def _add_folder_to_zip(self, folder, zipf, path, FolderModel, FileModel, is_public, request_user=None, visited=None):
        """递归将文件夹及其内容添加到 ZIP 文件"""
        import os

        # 初始化已访问集合
        if visited is None:
            visited = set()

        # 检查循环引用
        if folder.id in visited:
            logger.warning(f'[Document] 检测到循环引用，跳过文件夹: {folder.name} (id={folder.id})')
            return
        visited.add(folder.id)

        # 构建当前文件夹在 ZIP 中的路径
        current_path = f'{path}{folder.name}/'

        # 添加文件夹中的所有文件
        files_query = FileModel.objects.filter(folder=folder)
        # 私有空间：添加租户过滤
        if request_user and not is_public:
            files_query = apply_tenant_filter(files_query, request_user)
        for file in files_query:
            if os.path.exists(file.file_path):
                # 将文件添加到 ZIP
                zipf.write(file.file_path, f'{current_path}{file.name}')
                logger.info(f'[Document] Added file to ZIP: {current_path}{file.name}')
            else:
                logger.warning(f'[Document] File not found: {file.file_path}')

        # 递归处理子文件夹
        sub_folders_query = FolderModel.objects.filter(parent=folder)
        # 私有空间：添加租户过滤
        if request_user and not is_public:
            sub_folders_query = apply_tenant_filter(sub_folders_query, request_user)
        for sub_folder in sub_folders_query:
            self._add_folder_to_zip(sub_folder, zipf, current_path, FolderModel, FileModel, is_public, request_user, visited)


class FolderRenameView(View):
    @auth('document.document.rename')
    def post(self, request):
        import json
        try:
            data = json.loads(request.body)
            folder_id = data.get('id')
            name = data.get('name')
            is_public = data.get('is_public', False)
        except:
            return json_response(error='参数错误')

        if not folder_id:
            return json_response(error='参数错误')

        if not name or name.strip() == '':
            return json_response(error='文件夹名称不能为空')

        # 校验文件夹名称安全性
        if not validate_file_name(name):
            return json_response(error='文件夹名称包含非法字符')

        # 根据 is_public 参数获取对应的模型
        FolderModel = get_folder_model(is_public=is_public)

        folder_query = FolderModel.objects.filter(pk=folder_id)
        if not is_public:
            folder_query = apply_tenant_filter(folder_query, request.user)
        folder = folder_query.select_related('created_by').first()
        if not folder:
            return json_response(error='文件夹不存在')

        # 公共空间权限校验：仅管理员或创建人可重命名
        if is_public and not check_public_space_permission(request.user, folder, 'folder', '重命名'):
            return json_response(error='公共空间中只能重命名自己创建的文件夹')

        # 检查同一文件夹下是否存在同名文件夹（排除自己，添加租户过滤）
        existing_folder_query = FolderModel.objects.filter(
            parent_id=folder.parent_id,
            name=name
        ).exclude(pk=folder_id)

        # 私有空间：添加租户过滤
        if not is_public:
            existing_folder_query = apply_tenant_filter(existing_folder_query, request.user)

        existing_folder = existing_folder_query.first()

        if existing_folder:
            return json_response(error='该文件夹名称已存在')

        original_name = folder.name
        folder.name = name
        folder.save()
        log_operation(
            action="FOLDER_RENAME",
            user=request.user,
            resource_type="FOLDER",
            resource_id=folder.id,
            is_public=is_public,
            original_name=original_name,
            new_name=name
        )
        logger.info(f'[Document] Folder renamed successfully: {original_name} -> {name}, is_public={is_public}')
        return json_response()


class FileRenameView(View):
    @auth('document.document.rename')
    def post(self, request):
        import json
        try:
            data = json.loads(request.body)
            file_id = data.get('id')
            name = data.get('name')
            is_public = data.get('is_public', False)
        except:
            return json_response(error='参数错误')

        if not file_id:
            return json_response(error='参数错误')

        if not name or name.strip() == '':
            return json_response(error='文件名称不能为空')

        # 校验文件名安全性
        if not validate_file_name(name):
            return json_response(error='文件名包含非法字符')

        # 根据 is_public 参数获取对应的模型
        FileModel = get_file_model(is_public=is_public)

        file_query = FileModel.objects.filter(pk=file_id)
        if not is_public:
            file_query = apply_tenant_filter(file_query, request.user)
        file = file_query.select_related('created_by').first()
        if not file:
            return json_response(error='文件不存在')

        # 公共空间权限校验：仅管理员或创建人可重命名
        if is_public and not check_public_space_permission(request.user, file, 'file', '重命名'):
            return json_response(error='公共空间中只能重命名自己创建的文件')

        # 检查同一文件夹下是否存在同名文件（排除自己，添加租户过滤）
        # 注意：这里检查的是display_name，因为物理文件名已经是唯一的
        existing_file_query = FileModel.objects.filter(
            folder_id=file.folder_id,
            display_name=name
        ).exclude(pk=file_id)

        # 私有空间：添加租户过滤
        if not is_public:
            existing_file_query = apply_tenant_filter(existing_file_query, request.user)

        existing_file = existing_file_query.first()

        if existing_file:
            return json_response(error='该文件名称已存在')

        # 更新display_name（用户看到的文件名），不修改物理文件名
        original_display_name = file.display_name or file.name
        file.display_name = name

        # 物理文件路径和文件名（name字段）保持不变，不需要重命名物理文件
        # 这样可以避免并发冲突和磁盘IO操作

        file.save()
        log_operation(
            action="FILE_RENAME",
            user=request.user,
            resource_type="FILE",
            resource_id=file.id,
            is_public=is_public,
            original_name=original_display_name,
            new_name=name
        )
        logger.info(f'[Document] File display_name renamed successfully: {original_display_name} -> {name}, physical_name unchanged, is_public={is_public}')
        return json_response()


class FileChunkUploadView(View):
    @auth('document.document.upload')
    def post(self, request):
        """处理文件分片上传"""
        logger.info(f'[Document] FileChunkUploadView called, user: {request.user.username}')

        file_name = request.POST.get('file_name')
        file_size = request.POST.get('file_size')
        chunk_index = request.POST.get('chunk_index')
        total_chunks = request.POST.get('total_chunks')
        file_hash = request.POST.get('file_hash')
        folder_id = request.POST.get('folder_id')
        is_public = request.POST.get('is_public', 'false').lower() == 'true'

        # 参数验证
        if not all([file_name, file_size, chunk_index is not None, total_chunks]):
            logger.error(f'[Document] Missing parameters: file_name={file_name}, file_size={file_size}, chunk_index={chunk_index}, total_chunks={total_chunks}')
            return json_response(error='参数错误')

        try:
            chunk_index = int(chunk_index)
            total_chunks = int(total_chunks)
            file_size = int(file_size)
        except (ValueError, TypeError):
            logger.error(f'[Document] Invalid parameter types')
            return json_response(error='参数类型错误')

        # 验证 MD5 哈希格式（防止路径遍历）
        if not (file_hash and isinstance(file_hash, str) and len(file_hash) == 32):
            logger.error(f'[Document] Invalid file_hash format: {file_hash}')
            return json_response(error='非法的文件哈希值')

        # 验证文件名安全性
        if not validate_file_name(file_name):
            logger.error(f'[Document] Invalid file name: {file_name}')
            return json_response(error='文件名包含非法字符')

        # 验证文件大小
        if file_size <= 0 or file_size > MAX_FILE_SIZE:
            logger.error(f'[Document] Invalid file size: {file_size}')
            return json_response(error='文件大小超出限制（最大10GB）')

        # 根据 is_public 参数获取对应的模型
        FolderModel = get_folder_model(is_public=is_public)

        if folder_id:
            try:
                folder_id = int(folder_id)
                folder_query = FolderModel.objects.filter(pk=folder_id)
                if not is_public:
                    folder_query = apply_tenant_filter(folder_query, request.user)
                folder = folder_query.first()
                if not folder:
                    logger.error(f'[Document] Folder not found: {folder_id}')
                    return json_response(error='文件夹不存在')
            except (ValueError, TypeError):
                folder_id = None
                folder = None
        else:
            folder = None

        # 获取分片文件
        chunk_file = request.FILES.get('file')
        if not chunk_file:
            logger.error(f'[Document] No chunk file received')
            return json_response(error='未接收到文件分片')

        # 【P1-1修复】校验传输记录的文件大小和总分片数
        try:
            transfer = DocumentTransfer.objects.filter(
                file_hash=file_hash,
                user=request.user,
                is_public=is_public
            ).first()

            if transfer:
                # 校验文件大小
                if transfer.file_size != file_size:
                    logger.warning(
                        f'[Document] Chunk upload file size mismatch: '
                        f'transfer={transfer.file_size}, request={file_size}, hash={file_hash}'
                    )
                    return json_response(error=f'传输记录文件大小不匹配（原大小：{format_file_size(transfer.file_size)}，当前大小：{format_file_size(file_size)}），请重新上传')

                # 校验总分片数
                if transfer.total_chunks != total_chunks:
                    logger.warning(
                        f'[Document] Chunk upload total chunks mismatch: '
                        f'transfer={transfer.total_chunks}, request={total_chunks}, hash={file_hash}'
                    )
                    return json_response(error=f'传输记录分片总数不匹配（原总数：{transfer.total_chunks}，当前总数：{total_chunks}），请重新上传')

                logger.info(f'[Document] Transfer record validated for chunk upload: id={transfer.id}')
            else:
                logger.info(f'[Document] No transfer record found for hash={file_hash}, skipping validation')
        except Exception as e:
            logger.error(f'[Document] Failed to validate transfer record: {e}')
            # 校验失败不影响上传，继续原有逻辑

        # 【P1-1修复】校验分片索引范围
        if chunk_index < 0 or chunk_index >= total_chunks:
            logger.error(f'[Document] Invalid chunk index: {chunk_index}, total_chunks: {total_chunks}')
            return json_response(error=f'分片索引无效（索引范围：0-{total_chunks-1}）')

        # 【P1-1修复】校验分片大小
        chunk_size = chunk_file.size
        # 使用固定分片大小校验（与前端一致：20MB）
        CHUNK_SIZE = 20 * 1024 * 1024  # 20MB
        # 非最后一个分片：大小应接近CHUNK_SIZE（允许1KB误差）
        # 最后一个分片：可以小于等于CHUNK_SIZE
        if chunk_index != total_chunks - 1:
            # 前 N-1 个分片大小应在 CHUNK_SIZE ± 1KB 范围内
            if abs(chunk_size - CHUNK_SIZE) > 1024:
                logger.error(
                    f'[Document] Chunk size invalid for non-last chunk: '
                    f'chunk_index={chunk_index}, actual={chunk_size}, expected={CHUNK_SIZE}'
                )
                return json_response(error=f'分片{chunk_index}大小无效，请重新上传')
        else:
            # 最后一个分片大小应 ≤ CHUNK_SIZE
            if chunk_size > CHUNK_SIZE:
                logger.error(
                    f'[Document] Last chunk size too large: '
                    f'chunk_index={chunk_index}, actual={chunk_size}, max_allowed={CHUNK_SIZE}'
                )
                return json_response(error=f'分片{chunk_index}大小无效，请重新上传')

        # 计算预期分片大小（保留用于日志）
        avg_chunk_size = file_size / total_chunks

        # 【P0修复】按空间类型隔离存储分片（使用公共函数）
        # 公共空间: 租户ID + 用户ID双重隔离
        # 私有空间: 租户ID隔离
        try:
            safe_chunk_dir = get_chunk_dir_path(file_hash, is_public, request.user)
            logger.info(f'[Document] Chunk upload path generated: is_public={is_public}, tenant_id={request.user.tenant_id}, user_id={request.user.id}, safe_chunk_dir={safe_chunk_dir}')
        except ValueError as e:
            logger.error(f'[Document] Invalid file_hash format: {e}')
            return json_response(error='非法的文件哈希值')
        
        # 【P1修复】单独处理分片目录创建异常
        try:
            os.makedirs(safe_chunk_dir, exist_ok=True)
            logger.debug(f'[Document] Chunk directory ready: {safe_chunk_dir}')
        except PermissionError as e:
            logger.error(f'[Document] Permission denied when creating chunk directory: {safe_chunk_dir}, error: {e}')
            return json_response(error='分片目录创建失败：权限不足')
        except OSError as e:
            logger.error(f'[Document] Failed to create chunk directory: {safe_chunk_dir}, error: {e}')
            return json_response(error=f'分片目录创建失败: {str(e)}')

        # 分片文件名：{分片序号}.part
        chunk_filename = f"{chunk_index}.part"
        chunk_path = os.path.join(safe_chunk_dir, chunk_filename)

        # 检查分片是否已存在（避免重复接收）
        if os.path.exists(chunk_path):
            logger.info(f'[Document] Chunk {chunk_index} already exists, skipping')
            return json_response({
                'skip': True,
                'message': f'分片 {chunk_index} 已存在，跳过上传'
            })

        # 保存分片文件
        logger.info(f'[Document] Saving chunk {chunk_index + 1}/{total_chunks} for file: {file_name} to {safe_chunk_dir}, hash: {file_hash}, is_public={is_public}')
        try:
            with open(chunk_path, 'wb+') as destination:
                for chunk in chunk_file.chunks():
                    destination.write(chunk)

            # 验证分片大小（写入成功）
            actual_size = os.path.getsize(chunk_path)
            logger.info(f'[Document] Chunk {chunk_index + 1}/{total_chunks} saved successfully, size: {actual_size} bytes at {chunk_path}')
            return json_response()
        except Exception as e:
            logger.error(f'[Document] Failed to save chunk {chunk_index}: {e}')
            # 清理可能损坏的分片文件
            if os.path.exists(chunk_path):
                os.remove(chunk_path)
            return json_response(error=f'分片保存失败: {str(e)}')


def cleanup_old_chunks():
    """
    清理超过24小时的分片文件
    支持按租户 + MD5 子目录结构的清理
    """
    import time
    try:
        chunk_base_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_chunks')
        if not os.path.exists(chunk_base_dir):
            logger.info('[Document] Chunk directory does not exist')
            return

        current_time = time.time()
        max_age = CHUNK_CLEANUP_AGE  # 从配置文件读取

        # 遍历所有租户子目录（兼容新旧结构：public_{tenant_id}_{user_id} 和 {tenant_id}）
        for tenant_dir_name in os.listdir(chunk_base_dir):
            tenant_dir_path = os.path.join(chunk_base_dir, tenant_dir_name)

            # 跳过非目录文件
            if not os.path.isdir(tenant_dir_path):
                continue

            # 遍历该租户下的所有 MD5 子目录
            for md5_dir_name in os.listdir(tenant_dir_path):
                md5_dir_path = os.path.join(tenant_dir_path, md5_dir_name)

                # 跳过非目录文件
                if not os.path.isdir(md5_dir_path):
                    continue

                # 检查目录修改时间
                dir_age = current_time - os.path.getmtime(md5_dir_path)

                if dir_age > max_age:
                    logger.info(f'[Document] Cleaning up old chunk directory: tenant_dir={tenant_dir_name}, md5_dir={md5_dir_name}, age={dir_age:.0f}s')
                    try:
                        import shutil
                        shutil.rmtree(md5_dir_path, ignore_errors=True)
                        logger.info(f'[Document] Cleaned up chunk directory: {md5_dir_path}')
                        
                        # 尝试删除空的租户目录
                        if os.path.exists(tenant_dir_path) and not os.listdir(tenant_dir_path):
                            os.rmdir(tenant_dir_path)
                            logger.info(f'[Document] Removed empty tenant directory: {tenant_dir_path}')
                    except Exception as e:
                        logger.error(f'[Document] Failed to delete chunk directory {md5_dir_path}: {e}')

        # 同时清理过期的合并任务文件
        merge_task_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_merge_tasks')
        if os.path.exists(merge_task_dir):
            for task_file in os.listdir(merge_task_dir):
                if not task_file.endswith('.task'):
                    continue

                task_path = os.path.join(merge_task_dir, task_file)
                file_age = current_time - os.path.getmtime(task_path)

                if file_age > max_age:
                    try:
                        os.remove(task_path)
                        logger.info(f'[Document] Cleaned up old merge task: {task_file}')
                    except Exception as e:
                        logger.error(f'[Document] Failed to delete task {task_file}: {e}')

    except Exception as e:
        logger.error(f'[Document] Error cleaning up chunks: {e}')


class FileMergeChunksView(View):
    @auth('document.document.upload')
    @handle_view_errors
    def post(self, request):
        """合并文件分片（APScheduler异步模式）"""
        logger.info(f'[Document] FileMergeChunksView called, user: {request.user.username}')

        import json
        import time
        import uuid
        try:
            data = json.loads(request.body)
            file_name = data.get('file_name')
            file_size = data.get('file_size')
            total_chunks = data.get('total_chunks')
            file_hash = data.get('file_hash')
            folder_id = data.get('folder_id')
            is_public = data.get('is_public', False)
            transfer_id = data.get('transfer_id')  # 【修复】接收传输记录ID
        except Exception as e:
            logger.error(f'[Document] Parse error: {e}')
            return json_response(error='参数错误')

        # 参数验证
        if not all([file_name, file_size, total_chunks, file_hash]):
            logger.error(f'[Document] Missing parameters')
            return json_response(error='参数错误')

        try:
            total_chunks = int(total_chunks)
            file_size = int(file_size)
        except (ValueError, TypeError):
            logger.error(f'[Document] Invalid parameter types')
            return json_response(error='参数类型错误')

        # 验证 MD5 哈希格式（防止路径遍历）
        if not (file_hash and isinstance(file_hash, str) and len(file_hash) == 32):
            logger.error(f'[Document] Invalid file_hash format: {file_hash}')
            return json_response(error='非法的文件哈希值')

        # 验证文件名安全性
        if not validate_file_name(file_name):
            logger.error(f'[Document] Invalid file name: {file_name}')
            return json_response(error='文件名包含非法字符')

        # 验证文件大小
        if file_size <= 0 or file_size > MAX_FILE_SIZE:
            logger.error(f'[Document] Invalid file size: {file_size}')
            return json_response(error='文件大小超出限制（最大10GB）')

        # 根据 is_public 参数获取对应的模型
        FolderModel = get_folder_model(is_public=is_public)
        FileModel = get_file_model(is_public=is_public)

        # 处理文件夹
        folder = None
        if folder_id:
            try:
                folder_query = FolderModel.objects.filter(pk=int(folder_id))
                if not is_public:
                    folder_query = apply_tenant_filter(folder_query, request.user)
                folder = folder_query.first()
                if not folder:
                    logger.error(f'[Document] Folder not found: {folder_id}')
                    return json_response(error='文件夹不存在')
            except (ValueError, TypeError):
                folder = None

        # 验证文件名和大小
        is_valid, msg = validate_file_upload(file_name, file_size, max_file_size=10 * 1024 * 1024 * 1024)  # 10GB
        if not is_valid:
            return json_response(error=msg)

        # 【P0修复】按空间类型隔离存储分片（使用公共函数）
        # 公共空间: 租户ID + 用户ID双重隔离
        # 私有空间: 租户ID隔离
        try:
            chunk_dir = get_chunk_dir_path(file_hash, is_public, request.user)
        except ValueError as e:
            logger.error(f'[Document] Invalid file_hash format: {e}')
            return json_response(error='非法的文件哈希值')

        # 确保路径在允许范围内（防止路径遍历）
        chunk_base_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_chunks')
        if not is_safe_path(chunk_base_dir, chunk_dir):
            logger.error(f'[Document] Invalid file_hash path traversal attempt: hash={file_hash}, is_public={is_public}')
            return json_response(error='非法的文件哈希值')

        # 创建最终文件存储目录（根据 is_public 使用不同路径）
        from .libs.document_utils import get_document_absolute_path
        upload_dir = get_document_absolute_path(
            is_public=is_public,
            user_id=request.user.id,
            folder_id=folder_id
        )
        os.makedirs(upload_dir, exist_ok=True)

        # 【P1-3修复】生成唯一文件名（使用用户ID、时间戳和UUID随机后缀防止冲突）
        file_ext = os.path.splitext(file_name)[1]
        file_base = os.path.splitext(file_name)[0]

        # 截断基础文件名（保留120字符，为其他后缀预留空间，避免文件名过长）
        max_base_name_length = 120
        if len(file_base) > max_base_name_length:
            file_base = file_base[:max_base_name_length]

        timestamp = int(time.time())
        random_suffix = uuid.uuid4().hex[:8]
        unique_name = f"{file_base}_{request.user.id}_{timestamp}_{random_suffix}{file_ext}"

        # 【P1-3修复】在获取锁之前验证文件名长度（修复2204行bug）
        if len(unique_name) > 255:
            logger.error(f'[Document] Unique file name too long: {len(unique_name)} characters')
            return json_response(error='文件名过长，请缩短文件名后重试')

        file_path = os.path.join(upload_dir, unique_name)

        # 【P1-3修复】幂等性检查（结合传输记录的status字段）
        transfer_obj = None
        if transfer_id:
            try:
                from .models import DocumentTransfer
                transfer_obj = DocumentTransfer.objects.filter(id=transfer_id).first()
                if transfer_obj:
                    # 检查是否已经合并完成
                    if transfer_obj.status == TransferStatus.COMPLETED.value and transfer_obj.file_id:
                        logger.info(f'[Document] Transfer already completed: id={transfer_id}')
                        return json_response({
                            'status': TransferStatus.COMPLETED.value.lower(),
                            'file_id': transfer_obj.file_id,
                            'message': '文件已合并完成'
                        })

                    # 检查是否正在合并中
                    if transfer_obj.status == TransferStatus.MERGING.value:
                        logger.warning(f'[Document] Transfer already merging: id={transfer_id}')
                        return json_response(error='文件正在合并中，请稍后重试')
            except Exception as e:
                logger.error(f'[Document] Failed to check transfer status: {e}')

        # 【P1-3修复】获取优化后的合并锁（包含空间类型和租户ID）
        tenant_id = getattr(request.user, 'tenant_id', None)
        merge_lock = get_merge_lock(file_hash, is_public, tenant_id)

        # 【P1-3修复】带超时的锁获取
        try:
            if not merge_lock.acquire(timeout=MERGE_LOCK_TIMEOUT, blocking=True):
                logger.warning(
                    f'[Document] File merge lock acquisition timeout: '
                    f'file_hash={file_hash}, is_public={is_public}, tenant={tenant_id}'
                )
                return json_response(error='合并锁获取超时，请稍后重试')
        except Exception as e:
            logger.error(f'[Document] Failed to acquire merge lock: {e}')
            return json_response(error='获取合并锁失败，请稍后重试')

        try:
            # 创建状态文件（标记合并中）
            status_file = os.path.join(chunk_dir, '.merge_status')
            with open(status_file, 'w') as f:
                f.write(TransferStatus.MERGING.value.lower())

            # 检查所有分片是否存在
            logger.info(f'[Document] Checking chunks for file: {file_name}, total_chunks: {total_chunks}, chunk_dir: {chunk_dir}, is_public={is_public}')
            missing_chunks = []
            existing_chunks = []
            for i in range(total_chunks):
                chunk_filename = f"{i}.part"
                chunk_path = os.path.join(chunk_dir, chunk_filename)
                if not os.path.exists(chunk_path):
                    missing_chunks.append(i)
                else:
                    # 验证分片大小
                    try:
                        chunk_size = os.path.getsize(chunk_path)
                        existing_chunks.append((i, chunk_size))
                    except Exception as e:
                        logger.error(f'[Document] Failed to get size for chunk {i}: {e}')
                        missing_chunks.append(i)

            logger.info(f'[Document] Chunk check result: {len(existing_chunks)} existing, {len(missing_chunks)} missing')

            if missing_chunks:
                logger.error(f'[Document] Missing chunks: {missing_chunks} for file: {file_name}, hash: {file_hash}')
                # 【修复】更新传输记录状态为FAILED（如果有transfer_id）
                if transfer_id:
                    try:
                        from .models import DocumentTransfer
                        transfer_obj = DocumentTransfer.objects.filter(id=transfer_id).first()
                        if transfer_obj and transfer_obj.user == request.user:
                            transfer_obj.status = TransferStatus.FAILED.value
                            transfer_obj.error_message = f'缺少分片: {missing_chunks}'
                            transfer_obj.save()
                            logger.info(f'[Document] Transfer status updated to FAILED (missing chunks): id={transfer_id}')
                    except Exception as e:
                        logger.error(f'[Document] Failed to update transfer status to FAILED: {e}')

                # 更新状态文件为失败
                with open(status_file, 'w') as f:
                    f.write(TransferStatus.FAILED.value.lower())

                # 清理分片目录（避免磁盘泄漏）
                try:
                    import shutil
                    if os.path.exists(chunk_dir):
                        shutil.rmtree(chunk_dir, ignore_errors=True)
                        logger.info(f'[Document] Cleaned up chunk directory: {chunk_dir}')
                except Exception as cleanup_error:
                    logger.error(f'[Document] Failed to cleanup chunk directory: {cleanup_error}')

                return json_response(error=f'缺少分片: {missing_chunks}')

            # 【修复】更新传输记录状态为MERGING（如果有transfer_id）
            transfer_obj = None
            if transfer_id:
                try:
                    from .models import DocumentTransfer
                    transfer_obj = DocumentTransfer.objects.filter(id=transfer_id).first()
                    if transfer_obj and transfer_obj.user == request.user:
                        # 检查状态转换合法性：只能从 UPLOADING/PAUSED 转换到 MERGING
                        if transfer_obj.status in [TransferStatus.UPLOADING.value, TransferStatus.PAUSED.value]:
                            transfer_obj.status = TransferStatus.MERGING.value
                            transfer_obj.save()
                            logger.info(f'[Document] Transfer status updated to MERGING: id={transfer_id}')
                        else:
                            logger.warning(f'[Document] Transfer status cannot be changed to MERGING: id={transfer_id}, current_status={transfer_obj.status}')
                except Exception as e:
                    logger.error(f'[Document] Failed to update transfer status to MERGING: {e}')

            # 【APScheduler】创建合并任务ID
            merge_task_id = f"{file_hash}_{timestamp}"
            merge_task_file = os.path.join(settings.BASE_DIR, 'storage', 'document_merge_tasks', f"{merge_task_id}.task")
            os.makedirs(os.path.dirname(merge_task_file), exist_ok=True)

            # 准备任务数据
            job_data = {
                'file_name': file_name,
                'file_hash': file_hash,
                'file_path': file_path,
                'chunk_dir': chunk_dir,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'folder_id': folder_id,
                'is_public': is_public,
                'user_id': request.user.id,
                'username': request.user.username,
                'tenant_id': tenant_id,
                'transfer_id': transfer_id,
                'unique_name': unique_name,
                'timestamp': timestamp,
                'start_time': time.time()
            }

            # 写入初始任务文件
            with open(merge_task_file, 'w') as f:
                f.write(json.dumps({
                    'status': TransferStatus.PENDING.value.lower(),
                    'file_name': file_name,
                    'file_hash': file_hash,
                    'user': request.user.username,
                    'is_public': is_public,
                    'start_time': time.time()
                }))

            # 【APScheduler】提交合并任务到调度器
            from .libs.scheduler import submit_merge_job
            submit_merge_job(merge_task_id, job_data)

            # 立即返回，不等待合并完成
            logger.info(f'[APScheduler] Merge task submitted: {merge_task_id}')
            return json_response({
                'merge_task_id': merge_task_id,
                'status': 'pending',
                'message': '合并任务已提交，请轮询查询状态'
            })

        finally:
            # 【APScheduler】立即释放锁（APScheduler在任务执行时不需要持有锁）
            # 注意：这里立即释放锁是因为APScheduler会通过任务ID确保幂等性
            try:
                merge_lock.release()
                logger.info(
                    f'[APScheduler] Merge lock released: '
                    f'file_hash={file_hash}, is_public={is_public}, tenant={tenant_id}'
                )
            except Exception as release_error:
                logger.error(f'[APScheduler] Failed to release merge lock: {release_error}')


class CheckUploadedChunksView(View):
    """
    检查已上传分片接口（断点续传）
    返回当前租户下指定 file_hash 已上传的分片列表
    【P1-1修复】添加文件大小和总分片数校验，防止续传时文件被篡改
    """
    @auth('document.document.view')
    def post(self, request):
        """检查已上传分片"""
        logger.info(f'[Document] CheckUploadedChunksView called, user: {request.user.username}')

        form, error = JsonParser(
            Argument('file_hash', type=str, required=True, help='文件哈希(MD5)'),
            Argument('file_size', type=int, required=False, help='文件大小（字节）'),
            Argument('total_chunks', type=int, required=False, help='总分片数'),
            Argument('is_public', type=bool, required=False, default=False, help='是否公共空间')
        ).parse(request.body)

        if error:
            return json_response(error=error)

        file_hash = form.file_hash
        file_size = form.file_size
        total_chunks = form.total_chunks
        is_public = form.is_public

        # 验证 MD5 哈希格式（防止路径遍历）
        if not (file_hash and isinstance(file_hash, str) and len(file_hash) == 32):
            logger.error(f'[Document] Invalid file_hash format: {file_hash}')
            return json_response(error='非法的文件哈希值')

        tenant_id = getattr(request.user, 'tenant_id', '')

        # 【P1-1修复】查询传输记录，校验文件大小和总分片数
        if file_size is not None or total_chunks is not None:
            try:
                from .models import DocumentTransfer
                transfer = DocumentTransfer.objects.filter(
                    file_hash=file_hash,
                    user=request.user,
                    is_public=is_public
                ).first()

                if transfer:
                    # 校验文件大小
                    if file_size is not None and transfer.file_size != file_size:
                        logger.warning(
                            f'[Document] Resume upload file size mismatch: '
                            f'record={transfer.file_size}, request={file_size}, hash={file_hash}'
                        )
                        return json_response({
                            'exists': False,
                            'uploaded_chunks': [],
                            'error': f'文件大小已修改（原大小：{format_file_size(transfer.file_size)}，当前大小：{format_file_size(file_size)}），请重新上传'
                        })

                    # 校验总分片数
                    if total_chunks is not None and transfer.total_chunks != total_chunks:
                        logger.warning(
                            f'[Document] Resume upload total chunks mismatch: '
                            f'record={transfer.total_chunks}, request={total_chunks}, hash={file_hash}'
                        )
                        return json_response({
                            'exists': False,
                            'uploaded_chunks': [],
                            'error': f'分片总数已修改（原总数：{transfer.total_chunks}，当前总数：{total_chunks}），请重新上传'
                        })

                    logger.info(f'[Document] Transfer record validated: id={transfer.id}, file_size={transfer.file_size}, total_chunks={transfer.total_chunks}')
                else:
                    logger.info(f'[Document] No transfer record found for hash={file_hash}, skipping validation')
            except Exception as e:
                logger.error(f'[Document] Failed to validate transfer record: {e}')
                # 校验失败不影响续传，继续原有逻辑

        try:
            # 【P0修复】使用公共函数生成分片目录路径（与FileChunkUploadView完全一致）
            chunk_dir = get_chunk_dir_path(file_hash, is_public, request.user)

            logger.info(f'[Document] Checking uploaded chunks: hash={file_hash}, path={chunk_dir}, is_public={is_public}')

            # 检查分片目录是否存在
            if not os.path.exists(chunk_dir):
                logger.info(f'[Document] Chunk directory not exists: {chunk_dir}')
                return json_response({
                    'exists': False,
                    'uploaded_chunks': [],
                    'message': '未找到分片目录'
                })

            # 扫描已上传的分片文件
            uploaded_chunks = []
            try:
                for filename in os.listdir(chunk_dir):
                    if filename.endswith('.part'):
                        try:
                            # 提取分片索引：{chunk_index}.part
                            chunk_index = int(filename.replace('.part', ''))
                            uploaded_chunks.append(chunk_index)
                        except (ValueError, IndexError):
                            logger.warning(f'[Document] Invalid chunk filename: {filename}')
                            continue
            except OSError as e:
                logger.error(f'[Document] Error scanning chunk directory: {e}')
                return json_response(error='扫描分片目录失败')

            uploaded_chunks.sort()
            logger.info(f'[Document] Found uploaded chunks: {uploaded_chunks}')

            # 【修复】检查合并状态文件
            merge_status = None
            merge_task_id = None
            status_file = os.path.join(chunk_dir, '.merge_status')
            if os.path.exists(status_file):
                try:
                    with open(status_file, 'r') as f:
                        merge_status = f.read().strip()
                    logger.info(f'[Document] Found merge status file: {merge_status}')

                    # 如果正在合并中，尝试查找合并任务ID
                    if merge_status == 'merging':
                        # 查找最新的合并任务文件
                        merge_task_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_merge_tasks')
                        if os.path.exists(merge_task_dir):
                            import glob
                            task_files = glob.glob(os.path.join(merge_task_dir, f"{file_hash}_*.task"))
                            if task_files:
                                # 获取最新的任务文件
                                latest_task_file = max(task_files, key=os.path.getmtime)
                                merge_task_id = os.path.basename(latest_task_file).replace('.task', '')
                                logger.info(f'[Document] Found merge task ID: {merge_task_id}')
                except Exception as e:
                    logger.warning(f'[Document] Failed to read merge status file: {e}')

            return json_response({
                'exists': True,
                'uploaded_chunks': uploaded_chunks,
                'count': len(uploaded_chunks),
                'message': f'找到 {len(uploaded_chunks)} 个已上传分片',
                'merge_status': merge_status,
                'merge_task_id': merge_task_id
            })

        except Exception as e:
            logger.error(f'[Document] Error in CheckUploadedChunksView: {e}')
            return json_response(error=f'检查已上传分片失败: {str(e)}')


class FileMergeStatusView(View):
    """
    合并状态查询接口
    用于前端轮询合并任务状态
    【APScheduler】支持查询APScheduler任务状态
    """
    @auth('document.document.view')
    def get(self, request):
        """查询文件合并状态"""
        logger.info(f'[Document] FileMergeStatusView called, user: {request.user.username}')

        form, error = JsonParser(
            Argument('merge_task_id', required=True)
        ).parse(request.GET)

        if error:
            logger.error(f'[Document] Parse error: {error}')
            return json_response(error=error)

        # 【APScheduler】先查询调度器中的任务状态
        try:
            from .libs.scheduler import get_job_status
            task_info = get_job_status(form.merge_task_id)

            # 检查超时（从配置读取）
            import time
            if task_info.get('status') in ['pending', 'merging', 'scheduled']:
                start_time = task_info.get('start_time', time.time())
                elapsed = time.time() - start_time
                if elapsed > MERGE_STATUS_TIMEOUT:
                    return json_response({
                        'status': 'timeout',
                        'message': '合并任务超时'
                    })

            return json_response(task_info)
        except Exception as e:
            logger.error(f'[Document] Error querying merge task status: {e}')
            return json_response(error=f'查询合并状态失败: {str(e)}')


class DiskUsageView(View):
    """
    磁盘使用率查询接口
    返回上传目录的磁盘使用情况，区分公共/私有空间
    """
    @auth('document.document.view')
    def get(self, request):
        """获取磁盘使用率"""
        logger.info(f'[Document] DiskUsageView called, user: {request.user.username}')

        form, error = JsonParser(
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        # 根据 is_public 参数获取对应的模型
        FileModel = get_file_model(is_public=form.is_public)

        # 获取文档存储目录（根据 is_public 区分）
        if form.is_public:
            storage_dir = os.path.join(settings.BASE_DIR, 'storage', 'documents', 'public')
        else:
            storage_dir = os.path.join(settings.BASE_DIR, 'storage', 'documents', 'private', f'user-{request.user.id}')

        # 计算当前空间的文件大小
        try:
            query = FileModel.objects.all()
            if not form.is_public:
                query = apply_tenant_filter(query, request.user)

            total_size = query.aggregate(total_size=Sum('file_size'))['total_size'] or 0
            used_gb = round(total_size / (1024**3), 2)
        except Exception as e:
            logger.error(f'[Document] Error calculating file size: {e}')
            used_gb = 0

        # 获取磁盘使用率（跨平台兼容）
        import platform
        import shutil

        try:
            if platform.system() == 'Windows':
                # Windows 系统使用 ctypes 调用 GetDiskFreeSpaceExW
                import ctypes
                free_bytes = ctypes.c_ulonglong(0)
                total_bytes = ctypes.c_ulonglong(0)
                available_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    ctypes.c_wchar_p(storage_dir),
                    ctypes.byref(free_bytes),
                    ctypes.byref(total_bytes),
                    ctypes.byref(available_bytes)
                )
                total_disk_bytes = total_bytes.value
                total_disk_gb = round(total_disk_bytes / (1024**3), 2)
                available_gb = round(available_bytes.value / (1024**3), 2)
            else:
                # Linux/Unix 系统使用 shutil.disk_usage
                disk_usage = shutil.disk_usage(storage_dir)
                total_disk_bytes = disk_usage.total
                total_disk_gb = round(total_disk_bytes / (1024**3), 2)
                available_gb = round(disk_usage.free / (1024**3), 2)

            logger.info(f'[Document] Disk usage: {used_gb}GB used, {total_disk_gb}GB total, is_public={form.is_public}')
            return json_response({
                'usage_percent': 0,  # 文件大小占磁盘百分比
                'used_gb': used_gb,  # 当前空间已使用大小
                'total_gb': total_disk_gb,  # 磁盘总大小
                'available_gb': available_gb,  # 磁盘可用大小
                'storage_dir': storage_dir,
                'is_public': form.is_public
            })
        except Exception as e:
            logger.error(f'[Document] Error getting disk usage: {e}')
            # 返回默认值，避免阻塞上传
            return json_response({
                'usage_percent': 0,
                'used_gb': used_gb,
                'total_gb': 0,
                'available_gb': 0,
                'storage_dir': storage_dir,
                'is_public': form.is_public,
                'error': str(e)
            })


# ==================== 文件传输记录视图 ====================

class TransferListView(View):
    """获取用户的传输记录列表"""

    @auth('document.document.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('status', type=str, required=False, help='传输状态筛选'),
            Argument('transfer_type', type=str, required=False, help='传输类型筛选'),
            Argument('is_public', type=bool, required=False, help='是否公共空间'),
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        request_user = request.user

        # 【核心修复】根据 is_public 参数区分查询公共/私有空间的传输记录
        if hasattr(form, 'is_public') and form.is_public is not None:
            if form.is_public:
                # 公共空间：仅查询当前用户创建的传输记录（分账号隔离）
                # 【业务设计】公共空间传输列表分账号隔离，只显示自己创建的记录
                # 【理由】传输列表用于个人进度监控，文件列表用于资源发现，场景不同
                # 【优势】避免多用户同时上传时信息过载，提升用户体验
                queryset = DocumentTransfer.objects.filter(
                    user=request_user,
                    is_public=True
                )
            else:
                # 私有空间：查询当前用户、当前租户、is_public=false 的记录
                queryset = DocumentTransfer.objects.filter(
                    user=request_user,
                    is_public=False
                )
                # 添加租户过滤（如果用户有 tenant_id）
                if hasattr(request_user, 'tenant_id') and request_user.tenant_id:
                    queryset = queryset.filter(tenant_id=request_user.tenant_id)
        else:
            # 未指定空间类型：默认查询当前用户的所有记录（包括公共和私有）
            queryset = DocumentTransfer.objects.filter(user=request_user)
            # 添加租户过滤（如果用户有 tenant_id）
            if hasattr(request_user, 'tenant_id') and request_user.tenant_id:
                queryset = queryset.filter(tenant_id=request_user.tenant_id)

        # 可选：按状态筛选
        if form.status:
            queryset = queryset.filter(status=form.status)

        # 可选：按传输类型筛选
        if form.transfer_type:
            queryset = queryset.filter(transfer_type=form.transfer_type)

        # 按创建时间倒序，限制返回最近100条
        queryset = queryset.order_by('-created_at')[:100]

        # 构建响应数据
        transfers = []
        for t in queryset:
            transfers.append({
                'id': t.id,
                'transfer_type': t.transfer_type,
                'status': t.status,
                'file_name': t.file_name,
                'file_size': t.file_size,
                'file_hash': t.file_hash or '',  # 【传输恢复修复】返回文件哈希，用于断点续传
                'progress': t.progress,
                'transferred_size': t.transferred_size,
                'speed': t.speed,
                'total_chunks': t.total_chunks,
                'uploaded_chunks': t.uploaded_chunks,
                'folder_id': t.folder_id,
                'is_public': t.is_public,
                'created_at': t.created_at.strftime('%Y-%m-%d %H:%M:%S') if t.created_at else None,
                'started_at': t.started_at.strftime('%Y-%m-%d %H:%M:%S') if t.started_at else None,
                'completed_at': t.completed_at.strftime('%Y-%m-%d %H:%M:%S') if t.completed_at else None,
                'error_message': t.error_message,
            })

        logger.info(f'[Document] User {request_user.username} fetched {len(transfers)} transfer records')
        return json_response(data=transfers)


class TransferCreateView(View):
    """创建传输记录"""

    @auth('document.document.upload')
    def post(self, request):
        form, error = JsonParser(
            Argument('transfer_type', type=str, required=True, help='传输类型：UPLOAD/DOWNLOAD'),
            Argument('file_name', type=str, required=True, help='文件名'),
            Argument('file_size', type=int, required=True, help='文件大小(字节)'),
            Argument('file_hash', type=str, required=False, default='', help='文件哈希(MD5)'),
            Argument('folder_id', type=int, required=False, default=None, help='目标文件夹ID'),
            Argument('is_public', type=bool, required=False, default=False, help='是否公共空间'),
            Argument('total_chunks', type=int, required=False, default=None, help='总分片数'),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        request_user = request.user
        tenant_id = getattr(request_user, 'tenant_id', '')

        # 创建传输记录
        try:
            transfer = DocumentTransfer.objects.create(
                tenant_id=tenant_id,
                user=request_user,
                transfer_type=form.transfer_type,
                status=TransferStatus.PENDING.value,
                file_name=form.file_name,
                file_size=form.file_size,
                file_path='',  # 上传开始后再更新
                file_hash=form.file_hash or '',
                folder_id=form.folder_id,
                is_public=form.is_public or False,
                total_chunks=form.total_chunks or 0,
                uploaded_chunks=0,
                progress=0,
                transferred_size=0,
                speed=0,
            )

            logger.info(f'[Document] Created transfer record: id={transfer.id}, file={form.file_name}, user={request_user.username}')
            return json_response(data={'id': transfer.id, 'status': TransferStatus.PENDING.value.lower()})
        except Exception as e:
            logger.error(f'[Document] Error creating transfer record: {e}')
            return json_response(error=f'创建传输记录失败: {str(e)}')


class TransferProgressUpdateView(View):
    """更新传输进度"""

    @auth('document.document.upload')
    def post(self, request, transfer_id):
        form, error = JsonParser(
            Argument('uploaded_chunks', type=int, required=False, help='已上传分片数'),
            Argument('progress', type=int, required=False, help='进度百分比'),
            Argument('transferred_size', type=int, required=False, help='已传输大小(字节)'),
            Argument('speed', type=float, required=False, help='传输速度(字节/秒)'),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        try:
            transfer = DocumentTransfer.objects.get(id=transfer_id)

            # 权限检查：只能更新自己的传输记录，且必须在同一租户内
            # 超级管理员可以操作所有租户的传输记录
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            if (transfer.user != request.user and not is_supper) or \
               (transfer.tenant_id != request_tenant_id and not is_supper):
                logger.warning(f'[Document] User {request.user.username}(tenant={request_tenant_id}, is_supper={is_supper}) attempting to update transfer {transfer_id} owned by user {transfer.user.username}(tenant={transfer.tenant_id})')
                return json_response(error='无权更新此传输记录')

            # 更新字段
            if form.uploaded_chunks is not None:
                transfer.uploaded_chunks = form.uploaded_chunks
            if form.progress is not None:
                transfer.progress = form.progress
            if form.transferred_size is not None:
                transfer.transferred_size = form.transferred_size
            if form.speed is not None:
                transfer.speed = form.speed

            transfer.save()

            logger.debug(f'[Document] Updated transfer {transfer_id} progress: {transfer.progress}%')
            return json_response(data={'status': 'updated'})

        except DocumentTransfer.DoesNotExist:
            logger.warning(f'[Document] Transfer record not found: id={transfer_id}')
            return json_response(error='传输记录不存在')
        except Exception as e:
            logger.error(f'[Document] Error updating transfer progress: {e}')
            return json_response(error=f'更新进度失败: {str(e)}')


class TransferCompleteView(View):
    """完成传输"""

    @auth('document.document.upload')
    def post(self, request, transfer_id):
        try:
            from django.utils import timezone
            transfer = DocumentTransfer.objects.get(id=transfer_id)

            # 权限检查：只能完成自己的传输记录，且必须在同一租户内
            # 超级管理员可以操作所有租户的传输记录
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            if (transfer.user != request.user and not is_supper) or \
               (transfer.tenant_id != request_tenant_id and not is_supper):
                logger.warning(f'[Document] User {request.user.username}(tenant={request_tenant_id}, is_supper={is_supper}) attempting to complete transfer {transfer_id} owned by user {transfer.user.username}(tenant={transfer.tenant_id})')
                return json_response(error='无权操作此传输记录')

            # 幂等性校验：如果已经是完成状态，直接返回成功
            if transfer.status == TransferStatus.COMPLETED.value:
                logger.info(f'[Document] Transfer already in COMPLETED state: id={transfer_id}')
                return json_response(data={'status': TransferStatus.COMPLETED.value.lower(), 'completed_at': transfer.completed_at.strftime('%Y-%m-%d %H:%M:%S') if transfer.completed_at else None})

            # 【核心修复】状态转换验证：只能从 UPLOADING/MERGING/PAUSED/PENDING 转换到 COMPLETED
            if transfer.status in [TransferStatus.CANCELED.value, TransferStatus.FAILED.value]:
                logger.warning(f'[Document] Invalid status transition to COMPLETED: id={transfer_id}, current_status={transfer.status}')
                return json_response(error=f'无效的状态转换：{transfer.status} -> COMPLETED')

            # 更新状态为完成
            old_status = transfer.status
            transfer.status = TransferStatus.COMPLETED.value
            transfer.progress = 100
            transfer.transferred_size = transfer.file_size
            transfer.uploaded_chunks = transfer.total_chunks
            transfer.completed_at = timezone.now()
            transfer.save()

            logger.info(f'[Document] Transfer completed: id={transfer_id}, {old_status} -> COMPLETED, file={transfer.file_name}, user={request.user.username}')
            return json_response(data={'status': TransferStatus.COMPLETED.value.lower(), 'completed_at': transfer.completed_at.strftime('%Y-%m-%d %H:%M:%S')})

        except DocumentTransfer.DoesNotExist:
            logger.warning(f'[Document] Transfer record not found: id={transfer_id}')
            return json_response(error='传输记录不存在')
        except Exception as e:
            logger.error(f'[Document] Error completing transfer: {e}')
            return json_response(error=f'完成传输失败: {str(e)}')


class TransferCancelView(View):
    """取消传输"""

    @auth('document.document.upload')
    def post(self, request, transfer_id):
        try:
            transfer = DocumentTransfer.objects.get(id=transfer_id)

            # 权限检查：只能取消自己的传输记录，且必须在同一租户内
            # 超级管理员可以操作所有租户的传输记录
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            if (transfer.user != request.user and not is_supper) or \
               (transfer.tenant_id != request_tenant_id and not is_supper):
                logger.warning(f'[Document] User {request.user.username}(tenant={request_tenant_id}, is_supper={is_supper}) attempting to cancel transfer {transfer_id} owned by user {transfer.user.username}(tenant={transfer.tenant_id})')
                return json_response(error='无权操作此传输记录')

            # 幂等性校验：如果已经是取消状态，直接返回成功
            if transfer.status == TransferStatus.CANCELED.value:
                logger.info(f'[Document] Transfer already in CANCELED state: id={transfer_id}')
                return json_response(data={'status': TransferStatus.CANCELED.value.lower()})

            # 【核心修复】状态转换验证：只能从 PENDING/UPLOADING/PAUSED/MERGING 转换到 CANCELED
            if transfer.status in [TransferStatus.COMPLETED.value, TransferStatus.FAILED.value]:
                logger.warning(f'[Document] Invalid status transition to CANCELED: id={transfer_id}, current_status={transfer.status}')
                return json_response(error=f'无效的状态转换：{transfer.status} -> CANCELED')

            # 【P0修复】清理分片文件（如果有）- 使用公共函数生成路径
            try:
                # 使用公共函数生成分片目录路径（与分片上传路径一致）
                # 注意：transfer 没有 request_user，需要模拟用户对象
                from .libs.document_utils import get_chunk_dir_path
                
                # 构造临时用户对象（仅用于路径生成）
                class TempUser:
                    def __init__(self, user_id, tenant_id):
                        self.id = user_id
                        self.tenant_id = tenant_id
                
                temp_user = TempUser(transfer.user_id or 'anonymous', transfer.tenant_id or 'default')
                chunk_dir = get_chunk_dir_path(transfer.file_hash, transfer.is_public, temp_user)

                # 安全检查：防止路径遍历攻击
                chunk_base_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_chunks')
                if chunk_dir.startswith(chunk_base_dir) and os.path.exists(chunk_dir):
                    # 删除所有分片文件和状态文件
                    for filename in os.listdir(chunk_dir):
                        file_path = os.path.join(chunk_dir, filename)
                        try:
                            os.remove(file_path)
                            logger.info(f'[Document] Deleted chunk file: {filename}')
                        except Exception as e:
                            logger.warning(f'[Document] Failed to delete chunk file {filename}: {e}')

                    # 删除分片目录
                    try:
                        os.rmdir(chunk_dir)
                        logger.info(f'[Document] Cleaned up chunk directory for transfer {transfer_id}: {chunk_dir}')
                    except Exception as e:
                        logger.warning(f'[Document] Failed to remove chunk directory: {e}')

                    # 尝试删除租户目录（如果为空）
                    try:
                        tenant_dir = os.path.dirname(chunk_dir)
                        if os.path.exists(tenant_dir) and not os.listdir(tenant_dir):
                            os.rmdir(tenant_dir)
                            logger.info(f'[Document] Removed empty tenant directory: {tenant_dir}')
                    except Exception as e:
                        logger.debug(f'[Document] Tenant directory not empty or cannot be removed: {e}')

            except Exception as e:
                logger.warning(f'[Document] Failed to clean up chunks for transfer {transfer_id}: {e}')
                # 分片清理失败不影响取消操作

            # 更新状态为已取消
            transfer.status = TransferStatus.CANCELED.value
            transfer.error_message = '用户主动取消'
            transfer.save()

            logger.info(f'[Document] Transfer canceled: id={transfer_id}, file={transfer.file_name}, user={request.user.username}')
            return json_response(data={'status': TransferStatus.CANCELED.value.lower()})

        except DocumentTransfer.DoesNotExist:
            logger.warning(f'[Document] Transfer record not found: id={transfer_id}')
            return json_response(error='传输记录不存在')
        except Exception as e:
            logger.error(f'[Document] Error canceling transfer: {e}')
            return json_response(error=f'取消传输失败: {str(e)}')


class TransferStatusUpdateView(View):
    """更新传输状态"""

    @auth('document.document.upload')
    def post(self, request, transfer_id):
        try:
            form, error = JsonParser(
                Argument('status', type=str, required=True, help=f'新状态：{"/".join([s.value for s in TransferStatus])}'),
            ).parse(request.body)

            if error:
                return json_response(error=error)

            transfer = DocumentTransfer.objects.get(id=transfer_id)

            # 权限检查：只能操作自己的传输记录，且必须在同一租户内
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            if (transfer.user != request.user and not is_supper) or \
               (transfer.tenant_id != request_tenant_id and not is_supper):
                logger.warning(f'[Document] User {request.user.username}(tenant={request_tenant_id}) attempting to update status of transfer {transfer_id} owned by tenant {transfer.tenant_id}')
                return json_response(error='无权更新此传输记录')

            # 状态流转验证 - 使用常量中的状态转换规则
            current_status = transfer.status
            new_status = form.status

            # 使用 constants.py 中的状态转换验证函数
            current_status_enum = next((s for s in TransferStatus if s.value == current_status), None)
            new_status_enum = next((s for s in TransferStatus if s.value == new_status), None)

            if current_status_enum and new_status_enum:
                if not is_valid_status_transition(current_status_enum, new_status_enum):
                    logger.warning(f'[Document] Invalid status transition: {current_status} -> {new_status}')
                    return json_response(error=f'无效的状态转换：{current_status} -> {new_status}')
            else:
                logger.warning(f'[Document] Invalid status value: current={current_status}, new={new_status}')
                return json_response(error='无效的状态值')

            old_status = transfer.status
            transfer.status = new_status

            if new_status == TransferStatus.UPLOADING.value:
                if not transfer.started_at:
                    transfer.started_at = timezone.now()

            transfer.save()

            logger.info(f'[Document] Transfer status updated: id={transfer_id}, {old_status} -> {new_status}, user={request.user.username}')
            return json_response(data={'status': new_status})

        except DocumentTransfer.DoesNotExist:
            logger.warning(f'[Document] Transfer record not found: id={transfer_id}')
            return json_response(error='传输记录不存在')
        except Exception as e:
            logger.error(f'[Document] Error updating transfer status: {e}')
            return json_response(error=f'更新传输状态失败: {str(e)}')


class TransferDeleteView(View):
    """删除传输记录"""

    @auth('document.document.upload')
    def delete(self, request, transfer_id):
        try:
            transfer = DocumentTransfer.objects.get(id=transfer_id)

            # 权限检查：只能删除自己的传输记录，且必须在同一租户内
            # 超级管理员可以操作所有租户的传输记录
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            if (transfer.user != request.user and not is_supper) or \
               (transfer.tenant_id != request_tenant_id and not is_supper):
                logger.warning(f'[Document] User {request.user.username}(tenant={request_tenant_id}, is_supper={is_supper}) attempting to delete transfer {transfer_id} owned by user {transfer.user.username}(tenant={transfer.tenant_id})')
                return json_response(error='无权删除此传输记录')

            file_name = transfer.file_name

            # 【P0修复】清理分片文件（如果有）- 使用公共函数生成路径
            if transfer.file_hash and transfer.total_chunks > 0:
                try:
                    # 使用公共函数生成分片目录路径（与分片上传路径一致）
                    # 注意：transfer 没有 request_user，需要模拟用户对象
                    class TempUser:
                        def __init__(self, user_id, tenant_id):
                            self.id = user_id
                            self.tenant_id = tenant_id
                    
                    temp_user = TempUser(transfer.user_id or 'anonymous', transfer.tenant_id or 'default')
                    chunk_dir = get_chunk_dir_path(transfer.file_hash, transfer.is_public, temp_user)

                    # 安全检查：防止路径遍历攻击
                    chunk_base_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_chunks')
                    if chunk_dir.startswith(chunk_base_dir) and os.path.exists(chunk_dir):
                        # 删除所有分片文件和状态文件
                        for filename in os.listdir(chunk_dir):
                            file_path = os.path.join(chunk_dir, filename)
                            try:
                                os.remove(file_path)
                                logger.info(f'[Document] Deleted chunk file: {filename} for transfer {transfer_id}')
                            except Exception as e:
                                logger.warning(f'[Document] Failed to delete chunk file {filename}: {e}')

                        # 删除分片目录
                        try:
                            os.rmdir(chunk_dir)
                            logger.info(f'[Document] Cleaned up chunk directory for transfer {transfer_id}: {chunk_dir}')
                        except Exception as e:
                            logger.warning(f'[Document] Failed to remove chunk directory: {e}')

                        # 尝试删除租户目录（如果为空）
                        try:
                            tenant_dir = os.path.dirname(chunk_dir)
                            if os.path.exists(tenant_dir) and not os.listdir(tenant_dir):
                                os.rmdir(tenant_dir)
                                logger.info(f'[Document] Removed empty tenant directory: {tenant_dir}')
                        except Exception as e:
                            logger.debug(f'[Document] Tenant directory not empty or cannot be removed: {e}')

                        logger.info(f'[Document] Chunks cleaned up for transfer {transfer_id}')
                except Exception as e:
                    logger.warning(f'[Document] Failed to clean up chunks for transfer {transfer_id}: {e}')
                    # 分片清理失败不影响删除操作

            transfer.delete()

            logger.info(f'[Document] Transfer record deleted: id={transfer_id}, file={file_name}, user={request.user.username}')
            return json_response(data={'status': 'deleted', 'chunks_cleaned': transfer.file_hash is not None})

        except DocumentTransfer.DoesNotExist:
            logger.warning(f'[Document] Transfer record not found: id={transfer_id}')
            return json_response(error='传输记录不存在')
        except Exception as e:
            logger.error(f'[Document] Error deleting transfer record: {e}')
            return json_response(error=f'删除传输记录失败: {str(e)}')


class TransferHashUpdateView(View):
    """更新传输记录的 file_hash"""

    @auth('document.document.upload')
    def post(self, request, transfer_id):
        try:
            transfer = DocumentTransfer.objects.get(id=transfer_id)

            # 权限检查：只能更新自己的传输记录，且必须在同一租户内
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            if (transfer.user != request.user and not is_supper) or \
               (transfer.tenant_id != request_tenant_id and not is_supper):
                logger.warning(f'[Document] User {request.user.username}(tenant={request_tenant_id}) attempting to update hash of transfer {transfer_id} owned by user {transfer.user.username}(tenant={transfer.tenant_id})')
                return json_response(error='无权操作此传输记录')

            # 解析请求参数
            form, error = JsonParser(
                Argument('file_hash', type=str, required=True, help='文件哈希(MD5)'),
                Argument('total_chunks', type=int, required=False, default=None, help='总分片数')
            ).parse(request.body)

            if error:
                return json_response(error=error)

            # 更新 file_hash 和 total_chunks
            file_hash = form.file_hash
            total_chunks = form.total_chunks

            # 验证 MD5 哈希格式
            if not (file_hash and isinstance(file_hash, str) and len(file_hash) == 32):
                logger.error(f'[Document] Invalid file_hash format: {file_hash}')
                return json_response(error='非法的文件哈希值')

            old_hash = transfer.file_hash
            transfer.file_hash = file_hash
            update_fields = ['file_hash']

            if total_chunks is not None:
                old_chunks = transfer.total_chunks
                transfer.total_chunks = total_chunks
                update_fields.append('total_chunks')
                logger.info(f'[Document] Updated transfer total_chunks: id={transfer_id}, old_chunks={old_chunks}, new_chunks={total_chunks}, user={request.user.username}')

            transfer.save(update_fields=update_fields)

            logger.info(f'[Document] Updated transfer hash: id={transfer_id}, old_hash={old_hash}, new_hash={file_hash}, user={request.user.username}')
            return json_response(data={'status': 'updated', 'file_hash': file_hash})
        except DocumentTransfer.DoesNotExist:
            logger.error(f'[Document] Transfer not found for hash update: {transfer_id}')
            return json_response(error='传输记录不存在')
        except Exception as e:
            logger.error(f'[Document] Error updating transfer hash: {e}')
            return json_response(error=f'更新文件哈希失败: {str(e)}')


class TransferFailView(View):
    """标记传输失败"""

    @auth('document.document.upload')
    def post(self, request, transfer_id):
        try:
            form, error = JsonParser(
                Argument('error_message', type=str, required=False, help='错误信息'),
            ).parse(request.body)

            if error:
                return json_response(error=error)

            transfer = DocumentTransfer.objects.get(id=transfer_id)

            # 权限检查：只能操作自己的传输记录，且必须在同一租户内
            # 超级管理员可以操作所有租户的传输记录
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            if (transfer.user != request.user and not is_supper) or \
               (transfer.tenant_id != request_tenant_id and not is_supper):
                logger.warning(f'[Document] User {request.user.username}(tenant={request_tenant_id}, is_supper={is_supper}) attempting to fail transfer {transfer_id} owned by user {transfer.user.username}(tenant={transfer.tenant_id})')
                return json_response(error='无权操作此传输记录')

            # 幂等性校验：如果已经是失败状态，直接返回
            if transfer.status == TransferStatus.FAILED.value:
                logger.info(f'[Document] Transfer already in FAILED state: id={transfer_id}')
                return json_response(data={'status': TransferStatus.FAILED.value.lower(), 'id': transfer.id})

            # 更新状态为失败
            transfer.status = TransferStatus.FAILED.value
            transfer.error_message = form.error_message or '上传失败'
            transfer.save()

            logger.info(f'[Document] Transfer marked as failed: id={transfer_id}, file={transfer.file_name}, error={transfer.error_message}')
            return json_response(data={'status': TransferStatus.FAILED.value.lower()})

        except DocumentTransfer.DoesNotExist:
            logger.warning(f'[Document] Transfer record not found: id={transfer_id}')
            return json_response(error='传输记录不存在')
        except Exception as e:
            logger.error(f'[Document] Error marking transfer as failed: {e}')
            return json_response(error=f'标记传输失败失败: {str(e)}')


class TransferBatchPauseView(View):
    """批量暂停传输"""

    @auth('document.document.upload')
    @transaction.atomic  # 【P1-2修复】添加事务保护
    def post(self, request):
        try:
            logger.debug(f'[Document] Batch pause request body: {request.body}')
            form, error = JsonParser(
                Argument('transfer_ids', type=list, required=True, help='传输ID列表')
            ).parse(request.body)

            if error:
                logger.error(f'[Document] Batch pause parse error: {error}')
                return json_response(error=error)

            transfer_ids = form.transfer_ids
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            # 【P1-2修复】批量查询所有传输记录（避免N+1查询）
            all_transfers = DocumentTransfer.objects.filter(id__in=transfer_ids)
            valid_transfer_ids = set(all_transfers.values_list('id', flat=True))

            # 找出不存在的传输ID
            invalid_ids = set(transfer_ids) - valid_transfer_ids
            if invalid_ids:
                logger.warning(f'[Document] Batch pause: invalid transfer IDs: {invalid_ids}')

            # 【P1-2修复】批量权限校验（一次性查询）
            permitted_transfers = all_transfers.filter(
                Q(user=request.user) | Q(user__isnull=True) if is_supper else Q(user=request.user),
                Q(tenant_id=request_tenant_id) | Q(tenant_id='') | Q(tenant_id__isnull=True) if is_supper else Q(tenant_id=request_tenant_id)
            ).distinct()

            # 【P1-2修复】只能暂停未完成的传输
            can_pause_transfers = permitted_transfers.filter(
                status__in=[TransferStatus.PENDING.value, TransferStatus.UPLOADING.value, TransferStatus.PAUSED.value]
            )

            # 【P1-2修复】批量更新（减少数据库往返）
            updated_count = 0
            skipped_count = 0
            success_ids = []

            for transfer in can_pause_transfers:
                # 幂等性检查：如果已经是 PAUSED 状态，直接跳过更新
                if transfer.status == TransferStatus.PAUSED.value:
                    logger.info(f'[Document] Transfer {transfer.id} already paused (idempotent)')
                    success_ids.append(transfer.id)
                    updated_count += 1
                    continue

                # 更新状态
                transfer.status = TransferStatus.PAUSED.value
                transfer.save()
                success_ids.append(transfer.id)
                updated_count += 1

            # 计算跳过的数量
            skipped_count = len(transfer_ids) - updated_count

            logger.info(f'[Document] Batch pause: updated={updated_count}, skipped={skipped_count}, user={request.user.username}')
            return json_response(data={
                'updated': updated_count,
                'skipped': skipped_count,
                'success_ids': success_ids
            })

        except Exception as e:
            logger.error(f'[Document] Error in batch pause: {e}')
            # 事务会自动回滚
            return json_response(error=f'批量暂停失败: {str(e)}')


class TransferBatchResumeView(View):
    """批量恢复传输"""

    @auth('document.document.upload')
    @transaction.atomic  # 【P1-2修复】添加事务保护
    def post(self, request):
        try:
            logger.debug(f'[Document] Batch resume request body: {request.body}')
            form, error = JsonParser(
                Argument('transfer_ids', type=list, required=True, help='传输ID列表')
            ).parse(request.body)

            if error:
                logger.error(f'[Document] Batch resume parse error: {error}')
                return json_response(error=error)

            transfer_ids = form.transfer_ids
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            # 【P1-2修复】批量查询所有传输记录
            all_transfers = DocumentTransfer.objects.filter(id__in=transfer_ids)
            valid_transfer_ids = set(all_transfers.values_list('id', flat=True))

            # 找出不存在的传输ID
            invalid_ids = set(transfer_ids) - valid_transfer_ids
            if invalid_ids:
                logger.warning(f'[Document] Batch resume: invalid transfer IDs: {invalid_ids}')

            # 【P1-2修复】批量权限校验
            permitted_transfers = all_transfers.filter(
                Q(user=request.user) | Q(user__isnull=True) if is_supper else Q(user=request.user),
                Q(tenant_id=request_tenant_id) | Q(tenant_id='') | Q(tenant_id__isnull=True) if is_supper else Q(tenant_id=request_tenant_id)
            ).distinct()

            # 【P1-2修复】只能恢复已暂停的传输
            can_resume_transfers = permitted_transfers.filter(status=TransferStatus.PAUSED.value)

            # 【P1-2修复】批量更新
            updated_count = 0
            skipped_count = 0
            success_ids = []

            for transfer in can_resume_transfers:
                # 更新状态
                transfer.status = TransferStatus.PENDING.value
                transfer.error_message = ''
                transfer.save()
                success_ids.append(transfer.id)
                updated_count += 1

            # 计算跳过的数量
            skipped_count = len(transfer_ids) - updated_count

            logger.info(f'[Document] Batch resume: updated={updated_count}, skipped={skipped_count}, user={request.user.username}')
            return json_response(data={
                'updated': updated_count,
                'skipped': skipped_count,
                'success_ids': success_ids
            })

        except Exception as e:
            logger.error(f'[Document] Error in batch resume: {e}')
            # 事务会自动回滚
            return json_response(error=f'批量恢复失败: {str(e)}')


class TransferBatchCancelView(View):
    """批量取消传输"""

    @auth('document.document.upload')
    @transaction.atomic  # 【P1-2修复】添加事务保护
    def post(self, request):
        try:
            logger.debug(f'[Document] Batch cancel request body: {request.body}')
            form, error = JsonParser(
                Argument('transfer_ids', type=list, required=True, help='传输ID列表')
            ).parse(request.body)

            if error:
                logger.error(f'[Document] Batch cancel parse error: {error}')
                return json_response(error=error)

            transfer_ids = form.transfer_ids
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            # 【P1-2修复】批量查询所有传输记录（加锁防止并发）
            all_transfers = DocumentTransfer.objects.filter(id__in=transfer_ids).select_for_update()
            valid_transfer_ids = set(all_transfers.values_list('id', flat=True))

            # 找出不存在的传输ID
            invalid_ids = set(transfer_ids) - valid_transfer_ids
            if invalid_ids:
                logger.warning(f'[Document] Batch cancel: invalid transfer IDs: {invalid_ids}')

            # 【P1-2修复】批量权限校验
            permitted_transfers = all_transfers.filter(
                Q(user=request.user) | Q(user__isnull=True) if is_supper else Q(user=request.user),
                Q(tenant_id=request_tenant_id) | Q(tenant_id='') | Q(tenant_id__isnull=True) if is_supper else Q(tenant_id=request_tenant_id)
            ).distinct()

            # 【P1-2修复】只能取消未完成的传输
            can_cancel_transfers = permitted_transfers.exclude(
                status__in=[TransferStatus.COMPLETED.value, TransferStatus.FAILED.value, TransferStatus.CANCELED.value]
            )

            # 【P1-2修复】批量更新
            updated_count = 0
            skipped_count = 0
            success_ids = []
            chunk_dir_paths = []  # 需要清理的分片目录

            for transfer in can_cancel_transfers:
                # 【P0修复】清理分片文件（如果有）- 使用公共函数生成路径
                if transfer.file_hash and transfer.total_chunks > 0:
                    # 使用公共函数生成分片目录路径（与分片上传路径一致）
                    # 注意：transfer 没有 request_user，需要模拟用户对象
                    class TempUser:
                        def __init__(self, user_id, tenant_id):
                            self.id = user_id
                            self.tenant_id = tenant_id
                    
                    temp_user = TempUser(transfer.user_id or 'anonymous', transfer.tenant_id or 'default')
                    chunk_dir = get_chunk_dir_path(transfer.file_hash, transfer.is_public, temp_user)
                    chunk_dir_paths.append(chunk_dir)

                # 更新状态
                transfer.status = 'CANCELED'
                transfer.error_message = '用户主动取消'
                transfer.save()
                success_ids.append(transfer.id)
                updated_count += 1

            # 【P1-2修复】批量清理分片目录
            for chunk_dir in chunk_dir_paths:
                if chunk_dir.startswith(chunk_base_dir) and os.path.exists(chunk_dir):
                    try:
                        import shutil
                        shutil.rmtree(chunk_dir, ignore_errors=True)
                        logger.info(f'[Document] Cleaned up chunk directory: {chunk_dir}')
                    except Exception as e:
                        logger.warning(f'[Document] Failed to clean up chunk directory {chunk_dir}: {e}')

            # 计算跳过的数量
            skipped_count = len(transfer_ids) - updated_count

            logger.info(f'[Document] Batch cancel: updated={updated_count}, skipped={skipped_count}, user={request.user.username}')
            return json_response(data={
                'updated': updated_count,
                'skipped': skipped_count,
                'success_ids': success_ids
            })

        except Exception as e:
            logger.error(f'[Document] Error in batch cancel: {e}')
            # 事务会自动回滚
            return json_response(error=f'批量取消失败: {str(e)}')


class TransferBatchDeleteView(View):
    """批量删除传输记录"""

    @auth('document.document.upload')
    def post(self, request):
        try:
            logger.debug(f'[Document] Batch pause request body: {request.body}')
            form, error = JsonParser(
                Argument('transfer_ids', type=list, required=True, help='传输ID列表')
            ).parse(request.body)

            if error:
                logger.error(f'[Document] Batch pause parse error: {error}')
                return json_response(error=error)

            transfer_ids = form.transfer_ids
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            # 批量删除记录
            deleted_count = 0
            skipped_count = 0

            for transfer_id in transfer_ids:
                try:
                    transfer = DocumentTransfer.objects.get(id=transfer_id)

                    # 权限检查
                    if (transfer.user != request.user and not is_supper) or \
                       (transfer.tenant_id != request_tenant_id and not is_supper):
                        skipped_count += 1
                        logger.warning(f'[Document] User {request.user.username} cannot delete transfer {transfer_id}')
                        continue

                    # 只能删除已完成的传输记录，避免删除正在进行的传输
                    if transfer.status not in [TransferStatus.COMPLETED.value, TransferStatus.FAILED.value, TransferStatus.CANCELED.value]:
                        skipped_count += 1
                        logger.debug(f'[Document] Skip deleting active transfer {transfer_id} with status {transfer.status}')
                        continue

                    # 删除记录
                    transfer.delete()
                    deleted_count += 1

                except DocumentTransfer.DoesNotExist:
                    skipped_count += 1
                    continue

            logger.info(f'[Document] Batch delete: deleted={deleted_count}, skipped={skipped_count}, user={request.user.username}')
            return json_response(data={'deleted': deleted_count, 'skipped': skipped_count})

        except Exception as e:
            logger.error(f'[Document] Error in batch delete: {e}')
            return json_response(error=f'批量删除失败: {str(e)}')

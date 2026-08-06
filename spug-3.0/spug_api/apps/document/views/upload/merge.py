# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
合并分片视图
处理文件分片合并提交

【P1-4修复】代码结构优化：
将纯静态方法类改为模块级函数，简化代码结构
"""

from typing import Optional, Any, TYPE_CHECKING
import os
import json
import time
import logging
from uuid import uuid4
from django.db import transaction
from django.db.models import Q
from django.views.generic import View
from django.conf import settings
from django.http import HttpRequest

from libs import json_response, auth

if TYPE_CHECKING:
    from apps.document.models import DocumentTransfer
    from apps.account.models import User
from apps.document.constants import TransferStatus, DEFAULT_MAX_FILE_SIZE
from apps.document.libs.document_utils import (
    get_folder_model,
    get_file_model,
    get_chunk_dir_path,
    get_merge_task_file_path,
    is_safe_path,
    get_document_absolute_path,
)
from apps.document.libs.document_auth import document_auth
from apps.document.services.system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE, validate_system_folder_context, UPLOAD_TARGET_MSG,
)
from apps.document.services.system_scope_validators import validate_upload_target_scope
from apps.document.views.base import validate_file_name, validate_file_upload, handle_view_errors
from apps.document.views.upload.lock import get_merge_lock, MERGE_LOCK_TIMEOUT
from apps.document.views.upload.validators import HashValidator, FolderValidator, ChunkStorageManager
from apps.document.libs.view_utils import rate_limit

# 【P1-4修复】模块级导入（无循环依赖，提升性能）
from apps.document.models import DocumentTransfer
from apps.document.tasks import merge_file_chunks
from apps.document.libs.naming_utils import generate_file_names

logger = logging.getLogger(__name__)

# 【P2-2修复】合并任务目录路径常量
MERGE_TASKS_DIR_NAME = 'document_merge_tasks'
MERGE_TASKS_BASE_PATH_PARTS = ('storage', MERGE_TASKS_DIR_NAME)

# R7 修复：request_id 幂等缓存时长（秒），覆盖前端重试窗口
REQUEST_ID_CACHE_TTL = 3600


def _get_max_file_size() -> int:
    return getattr(settings, 'MAX_DOCUMENT_FILE_SIZE', DEFAULT_MAX_FILE_SIZE)


# ============================================================================
# R7 修复：request_id 幂等去重
# ============================================================================

def _check_request_id_dedup(request_id: Optional[str], user) -> Optional[dict]:
    """基于 request_id 的幂等去重检查。

    使用 Redis 缓存 request_id -> transfer_id 映射，
    防止前端网络重试导致重复提交 Celery 合并任务。

    Args:
        request_id: 前端生成的唯一请求标识
        user: 当前用户

    Returns:
        已有结果字典或 None
    """
    if not request_id:
        return None
    from django.core.cache import cache
    cache_key = f'merge_request_id:{request_id}'
    transfer_id = cache.get(cache_key)
    if not transfer_id:
        return None
    transfer = DocumentTransfer.objects.filter(id=transfer_id).first()
    if not transfer:
        return None
    # 归属校验：防止跨用户 IDOR
    if user and not getattr(user, 'is_supper', False) and transfer.user_id != user.id:
        logger.warning(
            '[Document][Merge] request_id dedup user mismatch: '
            'request_id=%s, transfer_id=%s', request_id, transfer_id
        )
        return None
    if transfer.status in [TransferStatus.MERGING.value, TransferStatus.COMPLETED.value]:
        logger.info(
            '[Document][Merge] request_id dedup hit: '
            'request_id=%s, transfer_id=%s, status=%s',
            request_id, transfer_id, transfer.status
        )
        return _build_result_from_transfer(transfer)
    return None


def _store_request_id_mapping(request_id: Optional[str], transfer_id: int):
    """存储 request_id -> transfer_id 映射。"""
    if not request_id:
        return
    from django.core.cache import cache
    cache_key = f'merge_request_id:{request_id}'
    cache.set(cache_key, transfer_id, REQUEST_ID_CACHE_TTL)


# ============================================================================
# 模块级函数（替代原来的静态方法类）
# ============================================================================

def parse_merge_request(request: HttpRequest) -> tuple[Optional[dict], Optional[str]]:
    """
    解析合并请求数据
    
    Args:
        request: HTTP请求对象
        
    Returns:
        tuple: (data字典或None, 错误消息或None)
    """
    try:
        data = json.loads(request.body)
        return data, None
    except json.JSONDecodeError as e:
        logger.error(f'[Document][Merge] JSON decode error: {e}')
        return None, '参数错误：无效的JSON格式'
    except Exception as e:
        logger.error(f'[Document][Merge] Failed to parse request body: {e}', exc_info=True)
        return None, '参数错误'


def validate_merge_params(data: dict) -> tuple[Optional[dict], Optional[str]]:
    """
    验证合并请求参数
    
    Args:
        data: 请求数据字典
        
    Returns:
        tuple: (参数字典或None, 错误消息或None)
    """
    file_name = data.get('file_name')
    file_size = data.get('file_size')
    total_chunks = data.get('total_chunks')
    file_hash = data.get('file_hash')

    if not all([file_name, file_size, total_chunks, file_hash]):
        return None, '参数错误'

    try:
        total_chunks = int(total_chunks)
        file_size = int(file_size)
    except (ValueError, TypeError):
        return None, '参数类型错误'

    return {
        'file_name': file_name,
        'file_size': file_size,
        'total_chunks': total_chunks,
        'file_hash': file_hash,
        'folder_id': data.get('folder_id'),
        'is_public': data.get('is_public', False),
        'transfer_id': data.get('transfer_id'),
        'system_folder': data.get('system_folder'),
        # R7 修复：解析 request_id 用于幂等去重
        'request_id': data.get('request_id'),
    }, None


def build_file_path(params: dict, folder: Any, user: 'User') -> dict[str, str]:
    """
    构建文件存储路径和名称
    
    Args:
        params: 合并参数字典
        folder: 文件夹对象
        user: 当前用户
        
    Returns:
        dict: 包含physical_name, logical_name, display_name, file_path的字典
    """
    is_public = params['is_public']
    folder_id = params['folder_id']
    file_name = params['file_name']

    # 创建最终文件存储目录
    upload_dir = get_document_absolute_path(
        is_public=is_public,
        user_id=user.id,
        folder_id=folder_id,
        system_folder=params.get('system_folder'),
    )
    os.makedirs(upload_dir, exist_ok=True)

    # 使用新的命名规范生成三层文件名
    FileModel = get_file_model(is_public=is_public)
    names = generate_file_names(FileModel, file_name, folder, user)

    file_path = os.path.join(upload_dir, names['physical_name'])

    # 【路径安全校验】验证最终文件路径在 storage/documents 下
    document_storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
    if not is_safe_path(document_storage_base, file_path):
        raise ValueError(f'Unsafe file path detected: {file_path}')

    return {
        'physical_name': names['physical_name'],
        'logical_name': names['logical_name'],
        'display_name': names['display_name'],
        'file_path': file_path,
    }


def check_all_chunks_present(chunk_dir: str, total_chunks: int) -> list[int]:
    """
    检查所有分片是否存在
    
    Args:
        chunk_dir: 分片目录路径
        total_chunks: 总分片数
        
    Returns:
        list: 缺失的分片索引列表
    """
    missing_chunks: list[int] = []
    for i in range(total_chunks):
        chunk_path = os.path.join(chunk_dir, f'{i}.part')
        if not os.path.exists(chunk_path):
            missing_chunks.append(i)
    return missing_chunks


def validate_chunk_directory(
    file_hash: str,
    is_public: bool,
    user: 'User',
    transfer_id: Optional[int] = None,
    system_folder: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    验证并获取分片目录

    【分片路径策略 — 有意设计的不一致】
    - resume.py：拒绝 legacy fallback（return None 让前端从头传）
      原因：避免"读旧分片、写新分片"，分片被拆成两份
    - chunk.py（上传分片）：严格走 transfer_id 新目录，禁止 fallback
      原因：写路径绝对不能写错目录
    - merge.py / direct_merge.py（本入口）：**允许 legacy fallback**
      原因：merge/direct_merge 是"读取历史分片入口"，已确认分片齐了直接合并，
      兼容老用户升级到新逻辑前的失败任务——这些任务的历史分片还在旧目录里，
      拒绝 fallback 会让它们永远合并不了。

    【P1修复】统一调用 ChunkStorageManager.get_and_validate_chunk_dir，
    合并入口是"读取历史分片"，所以显式传 allow_legacy_fallback=True。
    """
    return ChunkStorageManager.get_and_validate_chunk_dir(
        file_hash, is_public, user,
        transfer_id=transfer_id,
        allow_legacy_fallback=True,
        system_folder=system_folder,
    )


def _lookup_by_transfer_id(transfer_id: int, user: Optional['User']) -> Optional[dict]:
    """通过 transfer_id 查询传输记录，含归属校验和租户校验

    Returns:
        结果字典或 None
    """
    from django.db import transaction

    with transaction.atomic():
        transfer_query = DocumentTransfer.objects.select_for_update().filter(id=transfer_id)
        # 【M-1修复】加入用户归属校验，防止 IDOR
        if user and not getattr(user, 'is_supper', False):
            transfer_query = transfer_query.filter(user=user)
        transfer = transfer_query.order_by().first()
        if not transfer:
            return None

        # 私有空间额外校验租户
        if not getattr(user, 'is_supper', False) and not transfer.is_public:
            request_tenant_id = getattr(user, 'tenant_id', None)
            if transfer.tenant_id != request_tenant_id:
                logger.warning(f'[Document][Merge] Transfer tenant mismatch: transfer_id={transfer_id}')
                return None

        return _build_result_from_transfer(transfer)


def _lookup_by_file_hash(file_hash: str, is_public: Optional[bool], user: 'User',
                         folder_id: Optional[int] = None, system_folder: Optional[str] = None,
                         file_name: str = None) -> Optional[dict]:
    """通过 file_hash 查询 MERGING/COMPLETED 记录

    【P0修复】必须按 folder_id、system_folder 过滤，防止跨目录/跨空间误命中。
    【去重修复】同时按 file_name 过滤，不同文件名的同内容文件不算重复。

    Args:
        file_hash: 文件哈希
        is_public: 是否公共空间
        user: 当前用户
        folder_id: 目标目录ID（None 表示根目录）
        system_folder: 系统目录标识（如党建空间）
        file_name: 文件名（不同文件名的同内容文件不算重复）

    Returns:
        结果字典或 None
    """
    query = DocumentTransfer.objects.filter(
        file_hash=file_hash,
        status__in=[TransferStatus.MERGING.value, TransferStatus.COMPLETED.value]
    )

    # 【修复】同时按 file_name 匹配：不同文件名的同内容文件不算重复
    if file_name:
        query = query.filter(file_name=file_name)

    # 【P0修复】必须按目标目录和系统空间过滤，防止跨目录误命中
    if folder_id is not None:
        query = query.filter(folder_id=folder_id)
    else:
        # folder_id 为 None 表示根目录，排除有 folder_id 的记录
        query = query.filter(folder_id__isnull=True)

    # 【P0修复】按系统空间过滤（党建 vs 普通）
    if system_folder:
        query = query.filter(system_folder=system_folder)
    else:
        query = query.filter(Q(system_folder='') | Q(system_folder__isnull=True))

    # 租户过滤：私有空间按租户过滤，公共空间按用户过滤
    if not is_public:
        tenant_id = getattr(user, 'tenant_id', None)
        if tenant_id:
            query = query.filter(tenant_id=tenant_id)
        else:
            query = query.filter(user=user)
    else:
        # 【P0修复】公共空间也必须按用户过滤，防止跨用户误命中
        query = query.filter(user=user)

    # 【P0-3修复】合并为一个查询：优先返回有task_id的MERGING或COMPLETED
    transfer = query.filter(
        status=TransferStatus.MERGING.value,
        celery_task_id__isnull=False
    ).first() or query.filter(
        status=TransferStatus.COMPLETED.value,
        file_path__isnull=False
    ).exclude(file_path='').first()

    if not transfer:
        return None

    result = _build_result_from_transfer(transfer)
    if result:
        logger.info(f'[Document][Merge] Idempotent hit: id={transfer.id}, status={transfer.status}')
    return result


def check_idempotency(
    transfer_id: Optional[int],
    file_hash: Optional[str] = None,
    is_public: Optional[bool] = None,
    user: Optional['User'] = None,
    folder_id: Optional[int] = None,
    system_folder: Optional[str] = None,
    file_name: Optional[str] = None
) -> tuple[Optional[dict], Optional[str]]:
    """
    【P0-3修复】幂等性检查 - 简化版

    【P0修复】增加 folder_id、system_folder 参数，防止跨目录/跨空间误命中。
    【去重修复】增加 file_name 参数，不同文件名的同内容文件不算重复。

    Args:
        transfer_id: 传输记录ID（优先使用）
        file_hash: 文件哈希（当transfer_id为null时使用）
        is_public: 是否公共空间
        user: 当前用户
        folder_id: 目标目录ID
        system_folder: 系统目录标识

    Returns:
        tuple: (结果字典或None, 错误消息或None)
    """
    try:
        # 步骤1: 优先通过transfer_id查询自己的记录
        if transfer_id:
            result = _lookup_by_transfer_id(transfer_id, user)
            if result:
                return result, None

        # 步骤2: 通过file_hash查询MERGING/COMPLETED记录
        if file_hash and user:
            result = _lookup_by_file_hash(file_hash, is_public, user,
                                          folder_id=folder_id, system_folder=system_folder,
                                          file_name=file_name)
            if result:
                return result, None

        return None, None

    except Exception as e:
        logger.error(f'[Document][Merge] Idempotent check failed: {e}', exc_info=True)
        return None, str(e)


def _build_result_from_transfer(transfer: 'DocumentTransfer') -> Optional[dict[str, Any]]:
    """
    从传输记录构建返回结果

    【2026-08-05 修复】返回 COMPLETED 前验证文件记录真实存在，
    防止 Celery 任务异常导致状态已完成但文件记录未创建。

    Args:
        transfer: 传输记录对象

    Returns:
        dict或None: 结果字典，如果状态不匹配则返回None
    """
    # 【修正】file_path 为空但状态 COMPLETED -> 显式记日志并返回 None
    if transfer.status == TransferStatus.COMPLETED.value and not transfer.file_path:
        logger.warning(
            f'[Document][Merge] 状态异常: transfer={transfer.id} '
            f'status=COMPLETED 但 file_path 为空'
        )
        return None

    if transfer.status == TransferStatus.COMPLETED.value and transfer.file_path:
        # 验证文件记录真实存在
        try:
            FileModel = get_file_model(is_public=transfer.is_public)
            file_exists = FileModel.objects.filter(
                physical_name=os.path.basename(transfer.file_path),
                folder_id=transfer.folder_id,
            ).exists()
            if not file_exists:
                logger.warning(
                    f'[Document][Merge] 状态异常: transfer={transfer.id} '
                    f'status=COMPLETED但文件记录不存在'
                )
                return None
        except Exception as e:
            logger.error(f'[Document][Merge] 文件记录验证失败: {e}')
            return None
        return {
            'status': 'completed',
            'file_path': transfer.file_path,
            'message': '文件已合并完成'
        }

    # 【修复】只有存在celery_task_id时才返回merging状态
    if transfer.status == TransferStatus.MERGING.value and transfer.celery_task_id:
        return {
            'status': 'merging',
            'message': '文件正在合并中',
            'task_id': transfer.celery_task_id,
            'transfer_id': transfer.id,
        }

    return None


def update_transfer_to_merging(transfer_id: Optional[int], user: 'User') -> None:
    """
    更新传输记录为合并中状态
    
    Args:
        transfer_id: 传输记录ID
        user: 当前用户
    """
    if not transfer_id:
        return

    try:
        from django.db import transaction
        from apps.document.models import DocumentTransfer

        with transaction.atomic():
            transfer_obj = DocumentTransfer.objects.select_for_update().filter(id=transfer_id).order_by().first()
            if transfer_obj and transfer_obj.user == user:
                if transfer_obj.status in [TransferStatus.UPLOADING.value, TransferStatus.PAUSED.value]:
                    transfer_obj.status = TransferStatus.MERGING.value
                    transfer_obj.save()
    except Exception as e:
        logger.error(f'[Document][Merge] Update transfer status failed: {e}')


def submit_merge_task(
    params: dict,
    names: dict,
    chunk_dir: str,
    tenant_id: Optional[int],
    request: HttpRequest
) -> tuple[Any, str, str]:
    """
    提交合并任务到Celery队列
    
    Args:
        params: 合并参数字典
        names: 文件名信息字典
        chunk_dir: 分片目录路径
        tenant_id: 租户ID
        request: HTTP请求对象
        
    Returns:
        tuple: (Celery任务对象, 合并任务ID, 合并任务文件路径)
    """
    timestamp = int(time.time())
    merge_task_id = f"{params['file_hash']}_{timestamp}"
    merge_task_file = get_merge_task_file_path(
        merge_task_id,
        system_folder=params.get('system_folder'),
    )
    os.makedirs(os.path.dirname(merge_task_file), exist_ok=True)

    job_data = {
        'file_name': params['file_name'],
        'file_hash': params['file_hash'],
        'file_path': names['file_path'],
        'physical_name': names['physical_name'],
        'logical_name': names['logical_name'],
        'display_name': names['display_name'],
        'chunk_dir': chunk_dir,
        'file_size': params['file_size'],
        'total_chunks': params['total_chunks'],
        'folder_id': params['folder_id'],
        'is_public': params['is_public'],
        'user_id': request.user.id,
        'username': request.user.username,
        'tenant_id': tenant_id,
        'transfer_id': params['transfer_id'],
        'system_folder': params.get('system_folder'),
        'timestamp': int(time.time()),
        'start_time': time.time()
    }

    task_id = str(uuid4())

    def dispatch_after_commit():
        try:
            merge_file_chunks.apply_async(args=[job_data], task_id=task_id)
        except Exception as dispatch_error:
            from apps.document.models import DocumentTransfer
            DocumentTransfer.objects.filter(
                pk=params.get('transfer_id'), celery_task_id=task_id,
            ).update(
                status=TransferStatus.FAILED.value,
                error_message=f'合并任务投递失败: {dispatch_error}',
            )
            logger.error(
                f'[Document][Merge] Dispatch after commit failed: '
                f'transfer={params.get("transfer_id")}, task={task_id}, error={dispatch_error}',
                exc_info=True,
            )

    transaction.on_commit(dispatch_after_commit)
    task = merge_file_chunks.AsyncResult(task_id)

    return task, merge_task_id, merge_task_file


def save_task_id_to_transfer(transfer_id: Optional[int], task_id: str, user: Optional['User'] = None) -> None:
    """
    保存celery_task_id到传输记录

    Args:
        transfer_id: 传输记录ID
        task_id: Celery任务ID
        user: 当前用户（【M-1修复】用于归属校验）
    """
    if not transfer_id:
        return

    try:
        query = DocumentTransfer.objects.filter(id=transfer_id)
        # 【M-1修复】加入用户归属校验
        if user and not getattr(user, 'is_supper', False):
            query = query.filter(user=user)
        query.update(
            celery_task_id=task_id,
            status=TransferStatus.MERGING.value
        )
    except Exception as db_error:
        logger.error(f'[Document][Merge] Save task_id failed: {db_error}')


def write_merge_task_file(
    merge_task_file: str,
    params: dict,
    is_public: bool,
    task_id: str,
    user: 'User'
) -> None:
    """
    写入任务文件
    
    Args:
        merge_task_file: 任务文件路径
        params: 合并参数字典
        is_public: 是否公共空间
        task_id: Celery任务ID
        user: 当前用户
    """
    try:
        with open(merge_task_file, 'w') as f:
            f.write(json.dumps({
                'status': TransferStatus.PENDING.value.lower(),
                'file_name': params['file_name'],
                'file_hash': params['file_hash'],
                'user': user.username,
                'is_public': is_public,
                'system_folder': params.get('system_folder'),
                'start_time': time.time(),
                'task_id': task_id
            }))
    except Exception as file_error:
        logger.error(f'[Document][Merge] Write task file failed: {file_error}')


# ============================================================================
# 视图类
# ============================================================================

class FileMergeChunksView(View):
    """合并文件分片视图（Celery异步模式）。

    处理文件分片合并请求，将上传的分片合并为完整文件。
    使用分布式锁防止并发合并冲突，支持幂等性检查避免重复合并。
    """

    @staticmethod
    def _validate_context_and_scope(params):
        """党建上下文 + 上传目标作用域校验，返回 error_str 或 None"""
        system_folder = params.get('system_folder')
        ok, ctx_err = validate_system_folder_context(system_folder, params['is_public'])
        if not ok:
            return ctx_err
        ok, scope_err = validate_upload_target_scope(
            system_folder, params['is_public'], params['folder_id']
        )
        if not ok:
            return scope_err
        return None

    @staticmethod
    def _sync_transfer_on_idempotent_hit(params, result):
        """幂等命中时同步当前传输记录状态"""
        if not params.get('transfer_id'):
            return
        current_transfer = DocumentTransfer.objects.filter(
            id=params['transfer_id']
        ).first()
        if not current_transfer:
            return
        # 幂等命中 completed -> 同步 file_path + 设 COMPLETED
        if result.get('status') == 'completed' and \
           current_transfer.status != TransferStatus.COMPLETED.value:
            from apps.document.services.transfer_completion import TransferCompletionService
            TransferCompletionService.complete(
                current_transfer,
                file_path=result.get('file_path'),
                source='idempotent_file_hash'
            )
        # 幂等命中 merging -> 同步 celery_task_id
        elif result.get('status') == 'merging' and result.get('task_id') and \
             not current_transfer.celery_task_id:
            current_transfer.celery_task_id = result['task_id']
            current_transfer.status = TransferStatus.MERGING.value
            current_transfer.save(update_fields=['celery_task_id', 'status'])

    @document_auth('upload')
    @rate_limit(max_requests=60, window=60, key_prefix='merge')
    @handle_view_errors
    def post(self, request):
        """处理文件分片合并POST请求。"""
        # 步骤1: 解析并验证基础参数
        params, error = self._parse_and_validate_params(request)
        if error:
            logger.error(f'[Document][Merge] Param validation failed: {error}')
            return json_response(error=error)

        # 党建上下文与作用域校验
        scope_error = self._validate_context_and_scope(params)
        if scope_error:
            return json_response(error=scope_error)

        # R7 修复：request_id 幂等性检查
        request_id = params.get('request_id')
        if request_id:
            existing = _check_request_id_dedup(request_id, request.user)
            if existing:
                return json_response(existing)

        # 步骤2: 验证文件夹和文件
        folder, chunk_dir, error = self._validate_folder_and_chunk(params, request)
        if error:
            logger.error(f'[Document][Merge] Folder/chunk validation failed: {error}')
            return json_response(error=error)

        # 步骤3: 获取合并锁
        tenant_id = getattr(request.user, 'tenant_id', None)
        lock_key = f"{params['file_hash']}_{'public' if params['is_public'] else 'private'}_{tenant_id or 'default'}"
        merge_lock = get_merge_lock(params['file_hash'], params['is_public'], tenant_id)

        try:
            if not merge_lock.acquire(timeout=MERGE_LOCK_TIMEOUT, blocking=True):
                logger.error(f'[Document][Merge] Lock acquire timeout: {lock_key}')
                return json_response(error='合并锁获取超时')
        except Exception as e:
            logger.error(f'[Document][Merge] Lock acquire exception: {e}')
            return json_response(error='获取合并锁失败')

        try:
            # 步骤4: 在锁保护下构建文件路径并检查幂等性
            names, result, error = self._prepare_merge(params, folder, request)
            if error:
                logger.error(f'[Document][Merge] Idempotent check error: {error}')
                return json_response(error=error)
            if result:
                self._sync_transfer_on_idempotent_hit(params, result)
                return json_response(result)

            # 步骤5: 执行实际的合并操作
            return self._do_merge(params, names, chunk_dir, tenant_id, request)
        finally:
            try:
                merge_lock.release()
            except Exception as release_error:
                logger.error(f'[Document][Merge] Lock release failed: {release_error}')

    def _parse_and_validate_params(self, request):
        """解析并验证基础参数。

        Args:
            request: HTTP请求对象

        Returns:
            tuple: (参数字典或None, 错误消息或None)
        """
        # 解析请求
        data, error = parse_merge_request(request)
        if error:
            return None, error

        # 验证参数
        params, error = validate_merge_params(data)
        if error:
            return None, error

        # 验证哈希
        if not HashValidator.validate(params['file_hash']):
            return None, '非法的文件哈希值'

        # 验证文件名
        if not validate_file_name(params['file_name']):
            return None, '文件名包含非法字符'

        # 验证文件大小
        if params['file_size'] <= 0 or params['file_size'] > _get_max_file_size():
            return None, '文件大小超出限制（最大10GB）'

        return params, None

    def _validate_folder_and_chunk(self, params, request):
        """验证文件夹和分片目录。

        Args:
            params: 合并参数字典
            request: HTTP请求对象

        Returns:
            tuple: (文件夹对象或None, 分片目录路径或None, 错误消息或None)
        """
        # 解析文件夹
        folder, error = FolderValidator.validate_folder(params['folder_id'], params['is_public'], request.user)
        if error:
            return None, None, error

        # 验证文件
        is_valid, msg = validate_file_upload(
            params['file_name'], params['file_size'],
            max_file_size=_get_max_file_size()
        )
        if not is_valid:
            return None, None, msg

        # 验证分片目录
        chunk_dir, error = validate_chunk_directory(
            params['file_hash'], params['is_public'], request.user,
            transfer_id=params.get('transfer_id'),
            system_folder=params.get('system_folder'),
        )
        if error:
            return None, None, error

        return folder, chunk_dir, None

    def _prepare_merge(self, params, folder, request):
        """准备合并：构建路径并检查幂等性。

        Args:
            params: 合并参数字典
            folder: 文件夹对象
            request: HTTP请求对象

        Returns:
            tuple: (文件名信息字典或None, 幂等性结果或None, 错误消息或None)
        """
        # 构建文件路径
        try:
            names = build_file_path(params, folder, request.user)
        except ValueError as e:
            logger.error(f'[Document][Merge] Unsafe file path: {e}')
            return None, None, '文件路径异常'

        # 幂等性检查（支持通过transfer_id或file_hash查询）
        # 【P0修复】传入 folder_id 和 system_folder，防止跨目录/跨空间误命中
        result, error = check_idempotency(
            transfer_id=params['transfer_id'],
            file_hash=params['file_hash'],
            is_public=params['is_public'],
            user=request.user,
            folder_id=params.get('folder_id'),
            system_folder=params.get('system_folder'),
            file_name=params.get('file_name')
        )
        if error:
            return None, None, error
        if result:
            return None, result, None

        return names, None, None

    def _do_merge(self, params, names, chunk_dir, tenant_id, request):
        """执行实际的合并操作。

        创建状态文件、检查分片完整性、提交Celery合并任务。

        Args:
            params: 合并参数字典
            names: 文件名信息字典
            chunk_dir: 分片目录路径
            tenant_id: 租户ID
            request: HTTP请求对象

        Returns:
            JsonResponse: 包含任务提交结果或错误信息
        """
        # 【P1-5修复】使用try-except替代存在性检查，避免TOCTOU竞态条件
        try:
            # 尝试创建状态文件，如果目录不存在会抛出FileNotFoundError
            status_file = os.path.join(chunk_dir, '.merge_status')
            with open(status_file, 'w') as f:
                f.write(TransferStatus.MERGING.value.lower())
        except FileNotFoundError:
            logger.error(f'[Document][Merge] Chunk dir not exists: {chunk_dir}')
            return json_response(error='分片目录不存在，可能已被清理，请重新上传')
        except Exception as e:
            logger.error(f'[Document][Merge] Create status file failed: {e}')
            return json_response(error='创建状态文件失败')

        # 检查所有分片
        missing_chunks = check_all_chunks_present(chunk_dir, params['total_chunks'])
        if missing_chunks:
            logger.error(f'[Document][Merge] Missing chunks: {missing_chunks}')
            with open(status_file, 'w') as f:
                f.write(TransferStatus.FAILED.value.lower())
            return json_response(error=f'缺少分片: {missing_chunks}')

        # 显式事务保证即使脱离 ATOMIC_REQUESTS 调用，也会先登记任务再在提交后投递。
        with transaction.atomic():
            logger.info(f'[Document][Merge] _do_merge start: transfer={params["transfer_id"]}, file={params["file_name"]}')

            task, merge_task_id, merge_task_file = submit_merge_task(
                params, names, chunk_dir, tenant_id, request
            )
            logger.info(
                f'[Document][Merge] submit_merge_task OK: '
                f'task_id={task.id}, file={params["file_name"]}'
            )

            # 一次性更新状态和task_id，避免并发查询看到不一致的状态
            save_task_id_to_transfer(
                params['transfer_id'], task.id, user=request.user
            )  # 【M-1修复】传入用户
            logger.info(f'[Document][Merge] save_task_id_to_transfer OK: transfer={params["transfer_id"]}, task_id={task.id}')

            # 任务文件与数据库登记完成后，on_commit 回调才会投递 Celery。
            write_merge_task_file(
                merge_task_file, params, params['is_public'], task.id, request.user
            )
            logger.info(f'[Document][Merge] write_merge_task_file OK: transfer={params["transfer_id"]}')

            # R7 修复：存储 request_id -> transfer_id 映射，供后续重试请求幂等
            _store_request_id_mapping(params.get('request_id'), params['transfer_id'])
            logger.info(f'[Document][Merge] _do_merge all steps OK: transfer={params["transfer_id"]}')

        return json_response({
            'task_id': task.id,
            'merge_task_id': merge_task_id,
            'status': 'pending',
            'message': '合并任务已提交'
        })

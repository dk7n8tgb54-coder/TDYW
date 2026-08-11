# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
文件夹打包任务 - 异步 ZIP 压缩
【P0-6修复】解决同步 I/O 阻塞问题
"""
import os
import zipfile
import tempfile
import logging
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)

# 打包任务存储目录
PACK_TASKS_DIR = os.path.join(settings.BASE_DIR, 'storage', 'document_pack_tasks')


def _ensure_pack_dir():
    """确保打包任务目录存在"""
    os.makedirs(PACK_TASKS_DIR, exist_ok=True)


@shared_task(bind=True, soft_time_limit=3600, time_limit=7200, queue='document.pack')
def pack_folder_to_zip(self, folder_id, is_public, user_id, tenant_id=None):
    """
    【P0-6修复】异步打包文件夹为 ZIP

    Args:
        folder_id: 文件夹ID
        is_public: 是否公共空间
        user_id: 用户ID
        tenant_id: 租户ID（私有空间需要）

    Returns:
        dict: {
            'status': 'success' | 'failed',
            'zip_path': 生成的 ZIP 文件路径,
            'zip_size': ZIP 文件大小,
            'folder_name': 文件夹名称,
            'error': 错误信息（如果失败）
        }
    """
    from apps.document.models import DocumentFolderPublic, DocumentFilePublic
    from libs.tenant_utils import apply_tenant_filter
    from apps.document.libs.document_utils import get_folder_model, get_file_model, is_safe_path

    _ensure_pack_dir()

    # 选择模型
    FolderModel = DocumentFolderPublic
    FileModel = DocumentFilePublic

    try:
        # 查询文件夹
        folder_query = FolderModel.objects.filter(pk=folder_id)
        if not is_public and tenant_id:
            folder_query = apply_tenant_filter(folder_query, {'id': user_id, 'tenant_id': tenant_id})
        folder = folder_query.select_related('created_by').first()

        if not folder:
            return {'status': 'failed', 'error': '文件夹不存在'}

        # 创建临时 ZIP 文件
        zip_fd, zip_path = tempfile.mkstemp(suffix='.zip', prefix='spug_folder_')
        os.close(zip_fd)

        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zipf:
                # 使用 BFS 批量查询
                _pack_folder_recursive(folder, zipf, '', FolderModel, FileModel, is_public, user_id, tenant_id)

            zip_size = os.path.getsize(zip_path)

            # 移动到持久化目录
            final_path = os.path.join(PACK_TASKS_DIR, f'pack_{folder_id}_{user_id}_{self.request.id}.zip')
            os.rename(zip_path, final_path)

            logger.info(f'[Pack] Folder packed successfully: folder_id={folder_id}, size={zip_size}')

            return {
                'status': 'success',
                'zip_path': final_path,
                'zip_size': zip_size,
                'folder_name': folder.name,
                'task_id': self.request.id,
                # 【H-1修复】返回归属信息，供下载端校验
                'user_id': user_id,
                'tenant_id': tenant_id,
                'is_public': is_public,
                'folder_id': folder_id,
            }

        except Exception as e:
            # 清理临时文件
            if os.path.exists(zip_path):
                os.remove(zip_path)
            raise

    except Exception as e:
        logger.error(f'[Pack] Pack folder failed: folder_id={folder_id}, error={e}', exc_info=True)
        return {'status': 'failed', 'error': str(e)}


def _pack_folder_recursive(folder, zipf, path, FolderModel, FileModel, is_public, user_id, tenant_id):
    """
    BFS 批量查询并打包文件夹内容

    Args:
        folder: 当前文件夹对象
        zipf: ZipFile 对象
        path: ZIP 内部路径前缀
        FolderModel: 文件夹模型类
        FileModel: 文件模型类
        is_public: 是否公共空间
        user_id: 用户ID
        tenant_id: 租户ID
    """
    from libs.tenant_utils import apply_tenant_filter

    # BFS 收集所有文件夹
    folder_map = {}  # id -> folder_obj
    folder_children = {}  # parent_id -> [child_ids]
    folder_paths = {}  # folder_id -> zip_path

    queue = [folder]
    visited = set([folder.id])
    root_path = path

    while queue:
        current = queue.pop(0)
        folder_map[current.id] = current

        if current.id == folder.id:
            current_zip_path = f'{path}{current.name}/'
        else:
            parent_path = folder_paths.get(current.parent_id, root_path)
            current_zip_path = f'{parent_path}{current.name}/'
        folder_paths[current.id] = current_zip_path

        children_query = FolderModel.objects.filter(parent=current)
        if not is_public and tenant_id:
            children_query = apply_tenant_filter(children_query, {'id': user_id, 'tenant_id': tenant_id})
        children = list(children_query.select_related('created_by'))

        folder_children[current.id] = []
        for child in children:
            if child.id not in visited:
                visited.add(child.id)
                folder_children[current.id].append(child.id)
                queue.append(child)

    # 批量查询所有文件
    all_folder_ids = list(folder_map.keys())
    files_query = FileModel.objects.filter(folder_id__in=all_folder_ids)
    if not is_public and tenant_id:
        files_query = apply_tenant_filter(files_query, {'id': user_id, 'tenant_id': tenant_id})

    files_by_folder = {}
    for file in files_query.select_related('created_by'):
        files_by_folder.setdefault(file.folder_id, []).append(file)

    # 写入 ZIP（使用栈避免递归）
    stack = [folder.id]
    while stack:
        folder_id = stack.pop()
        current_folder = folder_map[folder_id]
        current_path = folder_paths[folder_id]

        for file in files_by_folder.get(folder_id, []):
            document_storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
            if not is_safe_path(document_storage_base, file.file_path):
                logger.warning(f'[Pack] Unsafe file path skipped: {file.file_path}')
                continue
            if os.path.exists(file.file_path):
                zipf.write(file.file_path, f'{current_path}{file.name}')
            else:
                logger.warning(f'[Pack] File not found: {file.file_path}')

        # 子文件夹入栈
        for child_id in reversed(folder_children.get(folder_id, [])):
            stack.append(child_id)


@shared_task(bind=True, soft_time_limit=300, time_limit=600, queue='document.pack')
def cleanup_expired_pack_tasks(self, max_age_hours=24):
    """
    清理过期的打包任务文件

    Args:
        max_age_hours: 最大保留时间（小时）

    Returns:
        dict: 清理统计
    """
    import time
    _ensure_pack_dir()

    deleted_count = 0
    error_count = 0
    cutoff_time = time.time() - (max_age_hours * 3600)

    for filename in os.listdir(PACK_TASKS_DIR):
        if not filename.endswith('.zip'):
            continue

        file_path = os.path.join(PACK_TASKS_DIR, filename)
        try:
            if os.path.getmtime(file_path) < cutoff_time:
                os.remove(file_path)
                deleted_count += 1
                logger.info(f'[Pack] Deleted expired pack task: {filename}')
        except Exception as e:
            error_count += 1
            logger.error(f'[Pack] Failed to delete pack task: {filename}, error={e}')

    return {
        'status': 'success',
        'deleted_count': deleted_count,
        'error_count': error_count
    }
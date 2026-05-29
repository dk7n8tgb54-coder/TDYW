# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
清理任务 - 异步批量删除
"""
import logging
from celery import shared_task
from django.db import transaction, DatabaseError

logger = logging.getLogger(__name__)


@shared_task(
    bind=True, 
    name='apps.document.tasks.cleanup.async_batch_permanent_delete',
    soft_time_limit=1800, 
    time_limit=3600, 
    queue='document.cleanup'
)
def async_batch_permanent_delete(self, file_ids, user_id):
    """
    【V3新增】异步批量彻底删除文件（用于大文件或大批量删除）
    避免阻塞前端用户操作
    
    Args:
        file_ids: 要删除的文件ID列表
        user_id: 执行删除的用户ID
        
    Returns:
        dict: 删除结果统计
    """
    from apps.account.models import User
    from apps.document.models import DocumentFilePrivate, DocumentFilePublic
    from apps.document.views.recycle_bin.utils import invalidate_cache
    from apps.document.views.base import log_operation
    
    logger.info(f'[AsyncDelete] 开始异步删除任务: task_id={self.request.id}, files={len(file_ids)}, user_id={user_id}')
    
    try:
        user = User.objects.get(id=user_id)
        logger.info(f'[AsyncDelete] 用户验证成功: user={user.username}, is_supper={getattr(user, "is_supper", False)}')
    except User.DoesNotExist:
        logger.error(f'[AsyncDelete] 用户不存在: user_id={user_id}')
        return {'status': 'failed', 'error': '用户不存在'}
    
    results = []
    success_count = 0
    failed_count = 0
    total_freed = 0
    
    # 分批处理，每批10个，避免单次事务过大
    batch_size = 10
    total = len(file_ids)
    
    logger.info(f'[AsyncDelete] 开始处理: total={total}, batch_size={batch_size}')
    
    for i in range(0, total, batch_size):
        batch = file_ids[i:i + batch_size]
        logger.info(f'[AsyncDelete] 处理批次: batch={i//batch_size + 1}, files={batch}')
        
        try:
            with transaction.atomic():
                for file_id in batch:
                    logger.info(f'[AsyncDelete] 删除文件: file_id={file_id}')
                    result = _permanent_delete_single(file_id, user_id, user, log_operation)
                    results.append(result)
                    
                    if result['status'] == 'success':
                        success_count += 1
                        total_freed += result.get('file_size', 0)
                        logger.info(f'[AsyncDelete] 删除成功: file_id={file_id}, size={result.get("file_size", 0)}')
                    else:
                        failed_count += 1
                        logger.error(f'[AsyncDelete] 删除失败: file_id={file_id}, error={result.get("error")}')
        except (OSError, IOError, DatabaseError) as e:
            logger.error(f'[AsyncDelete] 批次处理失败: batch={batch}, error={e}', exc_info=True)
            for file_id in batch:
                results.append({'id': file_id, 'status': 'failed', 'error': str(e)})
                failed_count += 1
        
        # 更新任务进度
        progress = min(100, int((i + len(batch)) / total * 100))
        self.update_state(
            state='PROGRESS',
            meta={'progress': progress, 'processed': i + len(batch), 'total': total}
        )
    
    # 【修复】清除回收站缓存，确保列表和统计数量一致
    logger.info(f'[AsyncDelete] 清除用户缓存: user_id={user_id}')
    invalidate_cache(user_id)
    
    logger.info(
        f'[AsyncDelete] 任务完成: task_id={self.request.id}, '
        f'success={success_count}, failed={failed_count}, freed={total_freed}'
    )
    
    return {
        'status': 'completed',
        'success_count': success_count,
        'failed_count': failed_count,
        'freed_space': total_freed,
        'details': results
    }


def _permanent_delete_single(file_id, user_id, user=None, log_operation_func=None):
    """【P0修复】删除单个文件（供异步任务使用）"""
    from apps.account.models import User
    from apps.document.models import DocumentFilePrivate, DocumentFilePublic
    
    # 【P0修复】重新查询用户并验证状态
    if user is None:
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.error(f'[AsyncDelete] 用户不存在: user_id={user_id}')
            return {'id': file_id, 'status': 'failed', 'error': '用户不存在'}
    
    try:
        # 尝试私有空间
        try:
            file_obj = DocumentFilePrivate.all_objects.get(id=file_id, is_deleted=True)
            is_public = False
            logger.info(f'[AsyncDelete] 找到私有空间文件: file_id={file_id}, physical_name={file_obj.physical_name}')
        except DocumentFilePrivate.DoesNotExist:
            try:
                file_obj = DocumentFilePublic.all_objects.get(id=file_id, is_deleted=True)
                is_public = True
                logger.info(f'[AsyncDelete] 找到公共空间文件: file_id={file_id}, physical_name={file_obj.physical_name}')
            except DocumentFilePublic.DoesNotExist:
                logger.error(f'[AsyncDelete] 文件不存在: file_id={file_id}')
                return {'id': file_id, 'status': 'failed', 'error': '文件不存在或未被删除'}
        
        # 【修改】权限校验 - 私密空间完全隔离，超级管理员也不能操作其他租户数据
        user_tenant_id = getattr(user, 'tenant_id', None)
        if not is_public:
            # 私密空间：检查租户ID，管理员也不能跨租户
            if user_tenant_id is None or file_obj.tenant_id != user_tenant_id:
                logger.error(f'[AsyncDelete] 租户隔离检查失败: file_id={file_id}, file_tenant={file_obj.tenant_id}, user_tenant={user_tenant_id}')
                return {'id': file_id, 'status': 'failed', 'error': '权限不足（租户隔离）'}
        else:
            # 公共空间：管理员可以操作所有，普通用户只能操作自己的
            if not user.is_supper and file_obj.created_by != user:
                logger.error(f'[AsyncDelete] 权限不足: file_id={file_id}, file_owner={file_obj.created_by}, user={user}')
                return {'id': file_id, 'status': 'failed', 'error': '无操作权限'}
        
        file_size = file_obj.file_size
        physical_name = file_obj.physical_name
        
        # 执行硬删除
        logger.info(f'[AsyncDelete] 执行硬删除: file_id={file_id}, physical_name={physical_name}')
        file_obj.delete(hard=True)
        logger.info(f'[AsyncDelete] 硬删除完成: file_id={file_id}')
        
        # 记录审计日志
        if log_operation_func:
            log_operation_func(
                action="FILE_PERMANENT_DELETE",
                user=user,
                resource_type="FILE",
                resource_id=file_id,
                is_public=is_public,
                file_size=file_size
            )
        
        return {'id': file_id, 'status': 'success', 'file_size': file_size}
        
    except (OSError, IOError, DatabaseError) as e:
        logger.error(f'[AsyncDelete] 删除文件失败: file_id={file_id}, error={e}', exc_info=True)
        return {'id': file_id, 'status': 'failed', 'error': str(e)}


@shared_task(
    bind=True, 
    name='apps.document.tasks.cleanup.async_batch_folder_permanent_delete',
    soft_time_limit=3600, 
    time_limit=7200, 
    queue='document.cleanup'
)
def async_batch_folder_permanent_delete(self, folder_ids, user_id):
    """
    【V3新增】异步批量彻底删除文件夹及其内容
    用于大文件夹或大批量删除，避免阻塞前端用户操作
    
    Args:
        folder_ids: 要删除的文件夹ID列表
        user_id: 执行删除的用户ID
        
    Returns:
        dict: 删除结果统计
    """
    from apps.account.models import User
    from apps.document.views.recycle_bin.utils import invalidate_cache
    
    logger.info(f'[AsyncFolderDelete] 开始异步删除文件夹任务: task_id={self.request.id}, folders={len(folder_ids)}, user_id={user_id}')
    
    try:
        user = User.objects.get(id=user_id)
        logger.info(f'[AsyncFolderDelete] 用户验证成功: user={user.username}, is_supper={getattr(user, "is_supper", False)}')
    except User.DoesNotExist:
        logger.error(f'[AsyncFolderDelete] 用户不存在: user_id={user_id}')
        return {'status': 'failed', 'error': '用户不存在'}
    
    results = []
    success_count = 0
    failed_count = 0
    total_freed = 0
    total_deleted_files = 0
    
    total = len(folder_ids)
    logger.info(f'[AsyncFolderDelete] 开始处理: total={total}')
    
    for i, folder_id in enumerate(folder_ids):
        logger.info(f'[AsyncFolderDelete] 删除文件夹: folder_id={folder_id}, progress={i+1}/{total}')
        
        try:
            with transaction.atomic():
                result = _permanent_delete_folder_single(folder_id, user_id, user)
                results.append(result)
                
                if result['status'] == 'success':
                    success_count += 1
                    total_freed += result.get('freed_size', 0)
                    total_deleted_files += result.get('deleted_file_count', 0)
                    logger.info(f'[AsyncFolderDelete] 文件夹删除成功: folder_id={folder_id}, freed={result.get("freed_size", 0)}')
                else:
                    failed_count += 1
                    logger.error(f'[AsyncFolderDelete] 文件夹删除失败: folder_id={folder_id}, error={result.get("error")}')
        except (OSError, IOError, DatabaseError) as e:
            logger.error(f'[AsyncFolderDelete] 文件夹处理失败: folder_id={folder_id}, error={e}', exc_info=True)
            results.append({'id': folder_id, 'status': 'failed', 'error': str(e)})
            failed_count += 1
        
        # 更新任务进度
        progress = min(100, int((i + 1) / total * 100))
        self.update_state(
            state='PROGRESS',
            meta={'progress': progress, 'processed': i + 1, 'total': total}
        )
    
    # 清除回收站缓存
    logger.info(f'[AsyncFolderDelete] 清除用户缓存: user_id={user_id}')
    invalidate_cache(user_id)
    
    logger.info(
        f'[AsyncFolderDelete] 任务完成: task_id={self.request.id}, '
        f'success={success_count}, failed={failed_count}, freed={total_freed}, files={total_deleted_files}'
    )
    
    return {
        'status': 'completed',
        'success_count': success_count,
        'failed_count': failed_count,
        'freed_space': total_freed,
        'deleted_file_count': total_deleted_files,
        'details': results
    }


def _permanent_delete_folder_single(folder_id, user_id, user=None):
    """【新增】删除单个文件夹及其内容（供异步任务使用）"""
    from apps.account.models import User
    from apps.document.models import DocumentFolderPrivate, DocumentFolderPublic, DocumentFilePrivate, DocumentFilePublic
    from apps.document.views.base import log_operation
    from apps.document.tasks.cleanup.base import _delete_folder_contents_iterative, _delete_physical_folder_safe
    
    if user is None:
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.error(f'[AsyncFolderDelete] 用户不存在: user_id={user_id}')
            return {'id': folder_id, 'status': 'failed', 'error': '用户不存在'}
    
    # 尝试查找文件夹
    try:
        folder = DocumentFolderPrivate.all_objects.get(id=folder_id, is_deleted=True)
        FolderModel = DocumentFolderPrivate
        FileModel = DocumentFilePrivate
        is_public = False
        logger.info(f'[AsyncFolderDelete] 找到私有空间文件夹: folder_id={folder_id}, name={folder.name}')
    except DocumentFolderPrivate.DoesNotExist:
        try:
            folder = DocumentFolderPublic.all_objects.get(id=folder_id, is_deleted=True)
            FolderModel = DocumentFolderPublic
            FileModel = DocumentFilePublic
            is_public = True
            logger.info(f'[AsyncFolderDelete] 找到公共空间文件夹: folder_id={folder_id}, name={folder.name}')
        except DocumentFolderPublic.DoesNotExist:
            logger.error(f'[AsyncFolderDelete] 文件夹不存在: folder_id={folder_id}')
            return {'id': folder_id, 'status': 'failed', 'error': '文件夹不存在或未被删除'}
    
    # 【修改】权限校验 - 私密空间完全隔离，超级管理员也不能操作其他租户数据
    # 【P0修复】使用 is_public 变量判断，避免 hasattr 判断错误
    user_tenant_id = getattr(user, 'tenant_id', None)
    if not is_public:
        # 私密空间：检查租户ID，管理员也不能跨租户
        if user_tenant_id is None or folder.tenant_id != user_tenant_id:
            logger.error(f'[AsyncFolderDelete] 租户隔离检查失败: folder_id={folder_id}')
            return {'id': folder_id, 'status': 'failed', 'error': '权限不足（租户隔离）'}
    else:
        # 公共空间：管理员可以操作所有，普通用户只能操作自己的
        if not user.is_supper and folder.created_by != user:
            logger.error(f'[AsyncFolderDelete] 权限不足: folder_id={folder_id}, owner={folder.created_by}, user={user}')
            return {'id': folder_id, 'status': 'failed', 'error': '无操作权限'}
    
    folder_name = folder.name
    freed_size = 0
    deleted_count = 0
    
    try:
        # 【优化】使用迭代方式删除子文件夹和文件
        freed_size, deleted_count = _delete_folder_contents_iterative(
            folder, FolderModel, FileModel, user
        )
        
        # 删除物理目录
        _delete_physical_folder_safe(folder)
        
        # 删除文件夹记录
        folder.delete(hard=True)
        logger.info(f'[AsyncFolderDelete] 文件夹删除完成: folder_id={folder_id}, name={folder_name}')
        
        # 记录审计日志
        log_operation(
            action="FOLDER_PERMANENT_DELETE",
            user=user,
            resource_type="FOLDER",
            resource_id=folder_id,
            is_public=is_public,
            folder_name=folder_name,
            freed_size=freed_size,
            deleted_file_count=deleted_count
        )
        
        return {
            'id': folder_id,
            'status': 'success',
            'freed_size': freed_size,
            'deleted_file_count': deleted_count
        }
        
    except (OSError, IOError, DatabaseError) as e:
        logger.error(f'[AsyncFolderDelete] 删除文件夹失败: folder_id={folder_id}, error={e}', exc_info=True)
        return {'id': folder_id, 'status': 'failed', 'error': str(e)}

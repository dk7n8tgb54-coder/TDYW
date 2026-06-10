# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
回收站文件夹永久删除视图
彻底删除文件夹及其内容（支持异步批量操作和幂等性校验）
"""

import os
import shutil
import logging
from django.views.generic import View
from django.db import transaction
from django.conf import settings
from django.core.cache import cache

from libs import json_response, JsonParser, Argument, auth
from ...models import DocumentFolderPrivate, DocumentFolderPublic, DocumentFilePrivate, DocumentFilePublic
from ...exceptions import DocumentPhysicalDeleteError
from ..base import log_operation
from .utils import invalidate_cache
from ...libs.permission_utils import (
    check_folder_permission,
    check_file_permission,
    get_folder_and_descendants_iter
)
from ...libs.idempotency_utils import IdempotencyChecker

logger = logging.getLogger(__name__)


class RecycleBinFolderPermanentDeleteView(View):
    """彻底删除文件夹视图（支持异步批量操作）"""
    
    # 【修改】移除批量删除数量限制，只保留大文件异步处理阈值
    LARGE_FOLDER_THRESHOLD = 100 * 1024 * 1024  # 100MB，超过则异步处理
    
    @auth('document.recycle-bin.permanent_delete')
    def post(self, request):
        """彻底删除文件夹（支持幂等性校验）"""
        form, error = JsonParser(
            Argument('folder_ids', type=list, required=True),
            Argument('async_mode', type=bool, required=False, default=False),
            Argument('idempotent_key', required=False),  # 【新增】幂等键
            # 【Bug 2 修复 2026-06-08】新增 space 参数，与文件删除保持一致
            Argument('space', required=False, default=None,
                     filter=lambda x: x in ('private', 'public', None)),
        ).parse(request.body)

        if error:
            return json_response(error=error, code=400001)

        if len(form.folder_ids) == 0:
            return json_response(error='请选择要删除的文件夹', code=400002)

        # 【新增】幂等性检查
        idempotency_checker = IdempotencyChecker('recycle_bin:folder_permanent_delete', ttl=300)
        if form.idempotent_key:
            cached_result = idempotency_checker.check(form.idempotent_key)
            if cached_result:
                logger.info(f'[RecycleBin] 文件夹删除幂等性命中: user={request.user.username}, folders={len(form.folder_ids)}')
                return json_response(data=cached_result)
        
        # 计算总大小决定是否需要异步处理
        total_size, total_files = self._calculate_total_size(form.folder_ids, form.space)
        need_async = form.async_mode or total_size > self.LARGE_FOLDER_THRESHOLD or len(form.folder_ids) > 3
        
        if need_async:
            try:
                from ...tasks.cleanup import async_batch_folder_permanent_delete
                from celery import current_app as celery_app
                
                # 检查Celery连接状态
                inspector = celery_app.control.inspect()
                active_queues = inspector.active_queues()
                logger.info(f'[RecycleBin] Celery连接状态: active_queues={active_queues is not None}')
                
                # 提交异步任务
                task = async_batch_folder_permanent_delete.delay(
                    form.folder_ids, request.user.id, form.space
                )
                logger.info(f'[RecycleBin] 异步删除文件夹任务已提交: task_id={task.id}, '
                           f'folders={len(form.folder_ids)}, space={form.space}, user={request.user.username}')

                response_data = {
                    'async': True,
                    'task_id': str(task.id),
                    'message': '删除任务已提交',
                    'folder_count': len(form.folder_ids),
                    'total_size': total_size,
                    'total_files': total_files
                }

                # 【新增】缓存幂等结果（5分钟）
                if form.idempotent_key:
                    idempotency_checker.cache(response_data)

                return json_response(data=response_data)
            except Exception as e:
                logger.error(f'[RecycleBin] 提交异步任务失败: {e}', exc_info=True)
                # 降级为同步处理
                logger.info('[RecycleBin] 降级为同步删除')
        
        # 同步删除
        # 【H3 修复 2026-06-08】每个 folder 单独事务（SAVEPOINT-like 行为）
        # - 修复前：整个 with transaction.atomic() 包住所有 folders，任一失败全部回滚
        #   → 单个 folder 失败导致"已删的物理文件"无法回滚
        # - 修复后：每个 folder 独立事务，单个失败不影响其他 folder
        # - 与异步路径 (async_batch_folder_permanent_delete) 语义一致
        # - 物理文件删除仍在事务内（受 DB 失败影响），但**单 folder 隔离**已大幅降低不一致风险
        #   物理 vs DB 不一致的深层修复需要重写 _delete_folder_recursive（不在本次范围）
        results = []
        total_freed = 0
        total_deleted_files = 0

        for folder_id in form.folder_ids:
            try:
                with transaction.atomic():
                    result = self._permanent_delete_folder(folder_id, request.user, form.space)
                    results.append(result)
                    if result['status'] == 'success':
                        total_freed += result.get('freed_size', 0)
                        total_deleted_files += result.get('deleted_file_count', 0)
            except Exception as e:
                # 单个 folder 失败被捕获：不影响其他 folder
                logger.error(
                    f'[RecycleBin] 删除文件夹失败: folder_id={folder_id}, error={e}',
                    exc_info=True
                )
                results.append({
                    'id': folder_id,
                    'status': 'failed',
                    'error': f'删除失败: {str(e)}',
                    'code': 500003
                })
        
        invalidate_cache(request.user.id)

        response_data = {
            'async': False,
            'success_count': sum(1 for r in results if r['status'] == 'success'),
            'failed_count': sum(1 for r in results if r['status'] == 'failed'),
            'freed_space': total_freed,
            'deleted_file_count': total_deleted_files,
            'details': results
        }

        # 【新增】缓存幂等结果（5分钟）
        if form.idempotent_key:
            idempotency_checker.cache(response_data)

        return json_response(data=response_data)
    
    def _calculate_total_size(self, folder_ids, space=None):
        """计算文件夹总大小和文件数"""
        total_size = 0
        total_files = 0

        for folder_id in folder_ids:
            # 【Bug 2 修复 2026-06-08】按 space 路由，与 _permanent_delete_folder 保持一致
            if space in ('private', None):
                try:
                    folder = DocumentFolderPrivate.all_objects.get(id=folder_id, is_deleted=True)
                    size, count = self._get_folder_size_and_count(folder, DocumentFolderPrivate, DocumentFilePrivate)
                    total_size += size
                    total_files += count
                    continue
                except DocumentFolderPrivate.DoesNotExist:
                    if space == 'private':
                        pass  # space 明确为 private，查不到就跳过
                    else:
                        pass  # 兼容模式，继续查 public

            if space in ('public', None):
                try:
                    folder = DocumentFolderPublic.all_objects.get(id=folder_id, is_deleted=True)
                    size, count = self._get_folder_size_and_count(folder, DocumentFolderPublic, DocumentFilePublic)
                    total_size += size
                    total_files += count
                except DocumentFolderPublic.DoesNotExist:
                    pass

        return total_size, total_files
    
    def _get_folder_size_and_count(self, folder, FolderModel, FileModel):
        """【优化】获取文件夹及其子文件夹的大小和文件数"""
        from django.db.models import Sum, Count
        
        # 【优化】使用迭代方式获取所有子文件夹ID，避免递归深度问题
        folder_ids = get_folder_and_descendants_iter(folder, FolderModel)
        
        # 【优化】使用聚合查询替代循环查询，避免N+1问题
        stats = FileModel.all_objects.filter(
            folder_id__in=folder_ids,
            is_deleted=True
        ).aggregate(
            total_files=Count('id'),
            total_size=Sum('file_size')
        )
        
        return stats['total_size'] or 0, stats['total_files'] or 0
    
    def _permanent_delete_folder(self, folder_id, user, space=None):
        """彻底删除单个文件夹及其内容"""
        logger.info(f'[RecycleBin] 尝试删除文件夹: folder_id={folder_id}, space={space}, user={user.username}')

        # 【Bug 2 修复 2026-06-08】按 space 路由
        # - 修复前：先查 Private，ID 冲突会错误地走 Private 路径
        # - 修复后：如果 space 明确，只查对应表
        if space == 'private':
            try:
                folder = DocumentFolderPrivate.all_objects.get(id=folder_id, is_deleted=True)
                logger.info(f'[RecycleBin] 找到私密空间文件夹: folder_id={folder_id}, tenant_id={repr(folder.tenant_id)}')
                return self._delete_private_folder(folder, user)
            except DocumentFolderPrivate.DoesNotExist:
                logger.error(f'[RecycleBin] 文件夹不存在: folder_id={folder_id}')
                return {
                    'id': folder_id,
                    'status': 'failed',
                    'error': '文件夹不存在或未被删除',
                    'code': 404001
                }

        if space == 'public':
            try:
                folder = DocumentFolderPublic.all_objects.get(id=folder_id, is_deleted=True)
                logger.info(f'[RecycleBin] 找到公共空间文件夹: folder_id={folder_id}, created_by={folder.created_by}')
                return self._delete_public_folder(folder, user)
            except DocumentFolderPublic.DoesNotExist:
                logger.error(f'[RecycleBin] 文件夹不存在: folder_id={folder_id}')
                return {
                    'id': folder_id,
                    'status': 'failed',
                    'error': '文件夹不存在或未被删除',
                    'code': 404001
                }

        # 向后兼容：space 缺省时保持原行为（先 Private 再 Public）
        # 先尝试私有空间
        try:
            folder = DocumentFolderPrivate.all_objects.get(id=folder_id, is_deleted=True)
            logger.info(f'[RecycleBin] 找到私密空间文件夹: folder_id={folder_id}, tenant_id={repr(folder.tenant_id)}')
            return self._delete_private_folder(folder, user)
        except DocumentFolderPrivate.DoesNotExist:
            pass

        # 再尝试公共空间
        try:
            folder = DocumentFolderPublic.all_objects.get(id=folder_id, is_deleted=True)
            logger.info(f'[RecycleBin] 找到公共空间文件夹: folder_id={folder_id}, created_by={folder.created_by}')
            return self._delete_public_folder(folder, user)
        except DocumentFolderPublic.DoesNotExist:
            logger.error(f'[RecycleBin] 文件夹不存在: folder_id={folder_id}')
            return {
                'id': folder_id,
                'status': 'failed',
                'error': '文件夹不存在或未被删除',
                'code': 404001
            }
    
    def _delete_private_folder(self, folder, user):
        """删除私有空间文件夹"""
        logger.info(f'[RecycleBin] 开始删除私密文件夹: folder_id={folder.id}, name={folder.name}, user={user.username}')
        
        # 【P0修复】统一使用 _check_folder_permission 进行权限校验
        if not self._check_folder_permission(folder, user):
            logger.error(f'[RecycleBin] 删除私密文件夹权限检查失败: folder_id={folder.id}, user={user.username}')
            return {
                'id': folder.id,
                'status': 'failed',
                'error': '只有文件夹所有者可以彻底删除文件夹',
                'code': 403001
            }
        
        folder_name = folder.name
        folder_id = folder.id
        
        # 递归删除
        freed_size, deleted_count = self._delete_folder_recursive(
            folder, DocumentFolderPrivate, DocumentFilePrivate, user
        )
        
        # 【P0修复】删除顶层文件夹记录
        try:
            folder.delete(hard=True)
            logger.info(f'[RecycleBin] 顶层文件夹已删除: {folder_name} (id={folder_id})')
        except Exception as e:
            logger.error(f'[RecycleBin] 删除顶层文件夹记录失败: folder_id={folder_id}, error={e}')
            return {'id': folder_id, 'status': 'failed', 'error': '删除文件夹记录失败', 'code': 500002}
        
        # 记录审计日志
        log_operation(
            action="FOLDER_PERMANENT_DELETE",
            user=user,
            resource_type="FOLDER",
            resource_id=folder_id,
            is_public=False,
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
    
    def _delete_public_folder(self, folder, user):
        """删除公共空间文件夹"""
        logger.info(f'[RecycleBin] 开始删除公共文件夹: folder_id={folder.id}, name={folder.name}, user={user.username}')
        
        # 权限校验
        if not self._check_folder_permission(folder, user):
            logger.error(f'[RecycleBin] 删除公共文件夹权限检查失败: folder_id={folder.id}, user={user.username}')
            return {
                'id': folder.id,
                'status': 'failed',
                'error': '只有管理员或文件夹所有者可以彻底删除文件夹',
                'code': 403001
            }
        
        folder_name = folder.name
        folder_id = folder.id
        
        # 递归删除
        freed_size, deleted_count = self._delete_folder_recursive(
            folder, DocumentFolderPublic, DocumentFilePublic, user
        )
        
        # 【P0修复】删除顶层文件夹记录
        try:
            folder.delete(hard=True)
            logger.info(f'[RecycleBin] 顶层文件夹已删除: {folder_name} (id={folder_id})')
        except Exception as e:
            logger.error(f'[RecycleBin] 删除顶层文件夹记录失败: folder_id={folder_id}, error={e}')
            return {'id': folder_id, 'status': 'failed', 'error': '删除文件夹记录失败', 'code': 500002}
        
        # 记录审计日志
        log_operation(
            action="FOLDER_PERMANENT_DELETE",
            user=user,
            resource_type="FOLDER",
            resource_id=folder_id,
            is_public=True,
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
    
    def _check_folder_permission(self, folder, user):
        """【优化】检查用户是否有权限操作文件夹（使用公共函数）"""
        return check_folder_permission(folder, user)
    
    def _check_file_permission(self, file_obj, user):
        """【优化】检查用户是否有权限操作文件（使用公共函数）"""
        return check_file_permission(file_obj, user)
    
    def _delete_folder_recursive(self, folder, FolderModel, FileModel, user):
        """
        【优化】迭代删除文件夹及其内容，返回释放的空间大小和删除的文件数
        
        替代递归实现，避免递归深度超限问题（Python默认递归深度1000）
        """
        freed_size = 0
        deleted_count = 0
        
        # 【优化】使用队列收集所有需要处理的文件夹（迭代替代递归）
        folder_queue = [folder]
        all_folders = []
        
        # 1. 迭代收集所有子文件夹（BFS遍历）
        while folder_queue:
            current_folder = folder_queue.pop(0)
            all_folders.append(current_folder)
            
            # 获取直接子文件夹
            sub_folders = FolderModel.all_objects.filter(parent=current_folder, is_deleted=True).order_by()
            folder_queue.extend(sub_folders)
        
        # 2. 从最深层开始删除（逆序处理）
        for current_folder in reversed(all_folders):
            # 删除当前文件夹内的文件
            files = FileModel.all_objects.filter(folder=current_folder, is_deleted=True).order_by()
            for file_obj in files:
                if self._check_file_permission(file_obj, user):
                    file_size = file_obj.file_size
                    try:
                        file_obj.delete(hard=True)
                        freed_size += file_size
                        deleted_count += 1
                    except DocumentPhysicalDeleteError as e:
                        logger.warning(f'[RecycleBin] 文件物理删除失败，已标记待清理: file_id={file_obj.id}, path={e.file_path}')
                    except Exception as e:
                        logger.error(f'[RecycleBin] 删除文件失败: file_id={file_obj.id}, error={e}')

            # 删除子文件夹的物理目录和记录（顶层文件夹除外）
            if current_folder.id != folder.id:
                if self._check_folder_permission(current_folder, user):
                    self._delete_physical_folder(current_folder)
                    try:
                        current_folder.delete(hard=True)
                    except DocumentPhysicalDeleteError as e:
                        logger.warning(f'[RecycleBin] 文件夹物理删除失败，已标记待清理: folder_id={current_folder.id}')
                    except Exception as e:
                        logger.error(f'[RecycleBin] 删除子文件夹记录失败: folder_id={current_folder.id}, error={e}')
            else:
                # 顶层文件夹只删除物理目录
                self._delete_physical_folder(current_folder)
        
        logger.info(f'[RecycleBin] 文件夹内容删除完成: {folder.name} (id={folder.id}), '
                   f'释放空间: {freed_size}, 删除文件数: {deleted_count}')
        return freed_size, deleted_count
    
    def _delete_physical_folder(self, folder):
        """删除文件夹的物理存储目录"""
        try:
            # 构建可能的存储路径
            base_path = getattr(settings, 'DOCUMENT_STORAGE_PATH', '/data/spug/documents')
            
            # 尝试不同的路径格式
            possible_paths = [
                os.path.join(base_path, f'folder_{folder.id}'),
                os.path.join(base_path, str(getattr(folder, 'tenant_id', '')), f'folder_{folder.id}'),
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    shutil.rmtree(path)
                    logger.info(f'[RecycleBin] 物理目录已删除: {path}')
                    break
        except Exception as e:
            logger.error(f'[RecycleBin] 删除物理目录失败: folder_id={folder.id}, error={e}')

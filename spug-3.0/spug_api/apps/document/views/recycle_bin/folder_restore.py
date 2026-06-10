# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
回收站文件夹恢复视图
恢复软删除的文件夹及其内容
"""

import time
import logging
from django.views.generic import View
from django.db import transaction
from django.core.cache import cache

from libs import json_response, JsonParser, Argument, auth
from ...models import DocumentFolderPrivate, DocumentFolderPublic, DocumentFilePrivate, DocumentFilePublic
from ..base import log_operation
from .utils import check_rate_limit, invalidate_cache
from ...libs.permission_utils import check_folder_permission, check_file_permission

logger = logging.getLogger(__name__)


class RecycleBinFolderRestoreView(View):
    """恢复文件夹视图（支持递归恢复子文件夹和文件）"""
    
    RATE_LIMIT = {'requests': 5, 'window': 60}  # 每分钟最多5次
    BATCH_LIMIT = 20  # 批量恢复上限
    
    @auth('document.recycle-bin.restore')
    def post(self, request):
        """恢复软删除的文件夹"""
        # 限流检查
        if not check_rate_limit(request.user.id, self.RATE_LIMIT):
            return json_response(error='操作过于频繁，请稍后再试', code=429001)
        
        form, error = JsonParser(
            Argument('folder_ids', type=list, required=True),
            Argument('restore_mode', required=False, default='original',
                     filter=lambda x: x in ['original', 'root', 'custom']),
            Argument('target_parent_id', type=int, required=False),
            Argument('idempotent_key', required=False)
        ).parse(request.body)
        
        if error:
            return json_response(error=error, code=400001)
        
        # 限制批量操作数量
        if len(form.folder_ids) > self.BATCH_LIMIT:
            return json_response(error=f'批量恢复最多支持{self.BATCH_LIMIT}个文件夹', code=400002)
        
        # 幂等性检查
        if form.idempotent_key:
            cache_key = f'recycle_bin:folder_restore:{form.idempotent_key}'
            cached_result = cache.get(cache_key)
            if cached_result:
                return json_response(data=cached_result)
        
        results = []
        success_count = 0
        total_restored_files = 0
        start_time = time.time()
        
        try:
            with transaction.atomic():
                for folder_id in form.folder_ids:
                    result = self._restore_folder(
                        folder_id,
                        request.user,
                        form.restore_mode,
                        form.target_parent_id
                    )
                    results.append(result)
                    if result['status'] == 'success':
                        success_count += 1
                        total_restored_files += result.get('restored_file_count', 0)
        except Exception as e:
            logger.error(f'[RecycleBin] 批量恢复文件夹事务失败: {e}')
            return json_response(error='恢复操作失败，请稍后重试', code=500001)
        
        duration = time.time() - start_time
        logger.info(f'[RecycleBinMetrics] operation=folder_restore, success={success_count}, '
                   f'total={len(form.folder_ids)}, files={total_restored_files}, duration={duration:.3f}s')
        
        response_data = {
            'success_count': success_count,
            'failed_count': len(form.folder_ids) - success_count,
            'total_restored_files': total_restored_files,
            'details': results
        }
        
        # 缓存幂等结果（5分钟）
        if form.idempotent_key:
            cache.set(cache_key, response_data, 300)
        
        # 清除列表缓存
        invalidate_cache(request.user.id)
        
        return json_response(data=response_data)
    
    def _restore_folder(self, folder_id, user, mode, target_parent_id):
        """恢复单个文件夹及其内容"""
        # 先尝试私有空间
        try:
            folder = DocumentFolderPrivate.all_objects.select_for_update().get(
                id=folder_id, is_deleted=True
            )
            return self._restore_private_folder(folder, user, mode, target_parent_id)
        except DocumentFolderPrivate.DoesNotExist:
            pass
        
        # 再尝试公共空间
        try:
            folder = DocumentFolderPublic.all_objects.select_for_update().get(
                id=folder_id, is_deleted=True
            )
            return self._restore_public_folder(folder, user, mode, target_parent_id)
        except DocumentFolderPublic.DoesNotExist:
            return {
                'id': folder_id,
                'status': 'failed',
                'error': '文件夹不存在或未被删除',
                'code': 404001
            }
    
    def _restore_private_folder(self, folder, user, mode, target_parent_id):
        """恢复私有空间文件夹"""
        user_id = getattr(user, 'id', 'N/A')
        
        if not folder.is_deleted:
            logger.warning(f'[RecycleBin] 文件夹已被恢复或不存在: {folder.name} (id={folder.id}), user={user_id}')
            return {'id': folder.id, 'status': 'failed', 'error': '文件夹已被恢复或不存在', 'code': 409001}
        
        # 权限检查
        if not self._check_folder_permission(folder, user):
            return {'id': folder.id, 'status': 'failed', 'error': '无操作权限', 'code': 403001}
        
        # 确定恢复位置
        target_parent = self._determine_restore_target(folder, mode, target_parent_id, 
                                                        DocumentFolderPrivate, user)
        if isinstance(target_parent, dict) and 'error' in target_parent:
            logger.error(f'[RecycleBin] 确定恢复目标失败: folder_id={folder.id}, mode={mode}, '
                        f'target_parent_id={target_parent_id}, error={target_parent["error"]}')
            return {'id': folder.id, 'status': 'failed', 'error': target_parent['error'], 'code': target_parent.get('code', 400)}
        
        # 检查同名冲突并自动重命名
        new_name = self._resolve_name_conflict(folder.name, target_parent, DocumentFolderPrivate, user)
        
        # 递归恢复文件夹及其内容
        restored_count = self._restore_folder_recursive(folder, target_parent, new_name, 
                                                        DocumentFolderPrivate, DocumentFilePrivate, user)
        
        # 记录审计日志
        log_operation(
            action="FOLDER_RESTORE",
            user=user,
            resource_type="FOLDER",
            resource_id=folder.id,
            is_public=False,
            restore_mode=mode,
            restored_path=folder.get_full_path()
        )
        
        return {
            'id': folder.id,
            'status': 'success',
            'restored_id': folder.id,
            'restored_name': new_name,
            'restored_file_count': restored_count
        }
    
    def _restore_public_folder(self, folder, user, mode, target_parent_id):
        """恢复公共空间文件夹"""
        user_id = getattr(user, 'id', 'N/A')
        
        if not folder.is_deleted:
            logger.warning(f'[RecycleBin] 文件夹已被恢复或不存在: {folder.name} (id={folder.id}), user={user_id}')
            return {'id': folder.id, 'status': 'failed', 'error': '文件夹已被恢复或不存在', 'code': 409001}
        
        # 权限检查
        if not self._check_folder_permission(folder, user):
            return {'id': folder.id, 'status': 'failed', 'error': '无操作权限', 'code': 403001}
        
        # 确定恢复位置
        target_parent = self._determine_restore_target(folder, mode, target_parent_id,
                                                        DocumentFolderPublic, user)
        if isinstance(target_parent, dict) and 'error' in target_parent:
            logger.error(f'[RecycleBin] 确定恢复目标失败(公共空间): folder_id={folder.id}, mode={mode}, '
                        f'target_parent_id={target_parent_id}, error={target_parent["error"]}')
            return {'id': folder.id, 'status': 'failed', 'error': target_parent['error'], 'code': target_parent.get('code', 400)}
        
        # 检查同名冲突并自动重命名
        new_name = self._resolve_name_conflict(folder.name, target_parent, DocumentFolderPublic, user)
        
        # 递归恢复文件夹及其内容
        restored_count = self._restore_folder_recursive(folder, target_parent, new_name,
                                                        DocumentFolderPublic, DocumentFilePublic, user)
        
        # 记录审计日志
        log_operation(
            action="FOLDER_RESTORE",
            user=user,
            resource_type="FOLDER",
            resource_id=folder.id,
            is_public=True,
            restore_mode=mode,
            restored_path=folder.get_full_path()
        )
        
        return {
            'id': folder.id,
            'status': 'success',
            'restored_id': folder.id,
            'restored_name': new_name,
            'restored_file_count': restored_count
        }
    
    def _check_folder_permission(self, folder, user):
        """【优化】检查用户是否有权限操作文件夹（使用公共函数）"""
        return check_folder_permission(folder, user)
    
    def _check_file_permission(self, file_obj, user):
        """【优化】检查用户是否有权限操作文件（使用公共函数）"""
        return check_file_permission(file_obj, user)
    
    def _determine_restore_target(self, folder, mode, target_parent_id, FolderModel, user):
        """确定文件夹恢复的目标位置"""
        if mode == 'original':
            # 恢复到原位置
            if folder.parent and folder.parent.is_deleted:
                # 父文件夹也被删除了，恢复到根目录
                return None
            return folder.parent
            
        elif mode == 'root':
            # 恢复到根目录
            return None
            
        elif mode == 'custom' and target_parent_id:
            # 恢复到指定位置
            try:
                target = FolderModel.all_objects.get(id=target_parent_id, is_deleted=False)
                # 检查权限
                if not self._check_folder_permission(target, user):
                    return {'error': '无权限访问目标文件夹', 'code': 403002}
                return target
            except FolderModel.DoesNotExist:
                return {'error': '目标文件夹不存在或已被删除', 'code': 404002}
        
        return None
    
    def _resolve_name_conflict(self, name, parent, FolderModel, user):
        """解决文件夹名称冲突，自动重命名"""
        # 检查是否已存在同名文件夹
        # 注意：公共空间 unique_key = name + parent（全局唯一，不按 created_by 区分），
        # 所以冲突检查也不能按 created_by 过滤，否则会漏判别人创建的同名文件夹
        existing = FolderModel.objects.filter(
            name=name,
            parent=parent,
            is_deleted=False
        ).order_by()
        
        if not existing.exists():
            return name
        
        # 自动重命名：名称_恢复_1, 名称_恢复_2, ...
        import re
        base_name = name
        # 如果已经包含_恢复_后缀，提取基础名称
        match = re.match(r'^(.*)_恢复_(\d+)$', name)
        if match:
            base_name = match.group(1)
        
        counter = 1
        while True:
            new_name = f"{base_name}_恢复_{counter}"
            existing = FolderModel.objects.filter(
                name=new_name,
                parent=parent,
                is_deleted=False
            ).order_by()
            
            if not existing.exists():
                return new_name
            counter += 1
            
            # 防止无限循环
            if counter > 1000:
                import uuid
                return f"{base_name}_恢复_{uuid.uuid4().hex[:8]}"
    
    def _restore_folder_recursive(self, folder, new_parent, new_name, FolderModel, FileModel, user):
        """
        【优化】迭代恢复文件夹及其内容，返回恢复的文件数量
        
        替代递归实现，避免递归深度超限问题
        """
        restored_files = 0
        
        # 【优化】使用队列收集所有需要处理的文件夹（迭代替代递归）
        folder_queue = [(folder, new_parent, new_name)]  # (folder, new_parent, new_name)
        processed_folders = []
        
        # 1. 迭代收集所有子文件夹（BFS遍历）
        while folder_queue:
            current_folder, current_parent, current_name = folder_queue.pop(0)
            
            # 检查文件夹是否已经被恢复
            if not current_folder.is_deleted:
                logger.warning(f'[RecycleBin] 文件夹已被恢复，跳过: {current_folder.name} (id={current_folder.id})')
            else:
                # 更新文件夹信息
                current_folder.parent = current_parent
                current_folder.name = current_name
                current_folder.is_deleted = False
                current_folder.deleted_at = None
                current_folder.deleted_by = None
                current_folder.save(update_fields=['parent', 'name', 'is_deleted', 'deleted_at', 'deleted_by'])
                logger.info(f'[RecycleBin] 文件夹已恢复: {current_folder.name} (id={current_folder.id})')
            
            processed_folders.append(current_folder)
            
            # 获取子文件夹
            sub_folders = FolderModel.all_objects.filter(parent=current_folder, is_deleted=True).order_by()
            for sub_folder in sub_folders:
                if not self._check_folder_permission(sub_folder, user):
                    logger.warning(f'[RecycleBin] 无权恢复子文件夹: folder_id={sub_folder.id}')
                    continue
                folder_queue.append((sub_folder, current_folder, sub_folder.name))
        
        # 2. 恢复所有文件夹内的文件
        for current_folder in processed_folders:
            files = FileModel.all_objects.filter(folder=current_folder, is_deleted=True).order_by()
            for file_obj in files:
                if self._check_file_permission(file_obj, user):
                    file_obj.restore()
                    
                    # 处理文件同名冲突
                    from ...libs.naming_utils import generate_unique_logical_name
                    file_obj.name = generate_unique_logical_name(
                        FileModel,
                        file_obj.display_name or file_obj.name,
                        current_folder,
                        user
                    )
                    file_obj.save(update_fields=['name'])
                    restored_files += 1
        
        logger.info(f'[RecycleBin] 文件夹恢复完成: {folder.name} (id={folder.id}), 恢复文件数: {restored_files}')
        return restored_files

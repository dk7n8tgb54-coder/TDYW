# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
回收站恢复视图
恢复软删除的文件（支持幂等和限流）
"""

import time
import logging
from django.views.generic import View
from django.db import transaction
from django.core.cache import cache

from libs import json_response, JsonParser, Argument, auth
from ...models import DocumentFilePrivate, DocumentFilePublic, DocumentFolderPrivate, DocumentFolderPublic
from ..base import log_operation
from .utils import check_rate_limit, invalidate_cache, check_permission

logger = logging.getLogger(__name__)


class RecycleBinRestoreView(View):
    """恢复文件视图（支持幂等和限流）"""
    
    RATE_LIMIT = {'requests': 10, 'window': 60}  # 每分钟最多10次
    
    @auth('document.recycle-bin.restore')
    def post(self, request):
        """恢复软删除的文件"""
        # 限流检查
        if not check_rate_limit(request.user.id, self.RATE_LIMIT):
            return json_response(error='操作过于频繁，请稍后再试', code=429001)
        
        form, error = JsonParser(
            Argument('file_ids', type=list, required=True),
            Argument('target_folder_id', type=int, required=False),
            Argument('current_folder_id', type=int, required=False),
            Argument('restore_mode', required=False, default='original',
                     filter=lambda x: x in ['original', 'current', 'custom']),
            Argument('idempotent_key', required=False)
        ).parse(request.body)
        
        if error:
            return json_response(error=error, code=400001)
        
        # 限制批量操作数量
        batch_limit = 50
        if len(form.file_ids) > batch_limit:
            return json_response(error=f'批量恢复最多支持{batch_limit}个文件', code=400002)
        
        # 幂等性检查
        if form.idempotent_key:
            cache_key = f'recycle_bin:restore:{form.idempotent_key}'
            if cache.get(cache_key):
                return json_response(data=cache.get(cache_key))
        
        results = []
        success_count = 0
        start_time = time.time()
        
        try:
            with transaction.atomic():
                for file_id in form.file_ids:
                    result = self._restore_file(
                        file_id, 
                        request.user,
                        form.restore_mode,
                        form.target_folder_id,
                        form.current_folder_id
                    )
                    results.append(result)
                    if result['status'] == 'success':
                        success_count += 1
        except Exception as e:
            logger.error(f'[RecycleBin] 批量恢复事务失败: {e}')
            return json_response(error='恢复操作失败，请稍后重试', code=500001)
        
        duration = time.time() - start_time
        logger.info(f'[RecycleBinMetrics] operation=restore, success={success_count}, total={len(form.file_ids)}, duration={duration:.3f}s')
        
        response_data = {
            'success_count': success_count,
            'failed_count': len(form.file_ids) - success_count,
            'details': results
        }
        
        # 缓存幂等结果（5分钟）
        if form.idempotent_key:
            cache.set(cache_key, response_data, 300)
        
        # 清除列表缓存
        invalidate_cache(request.user.id)
        
        return json_response(data=response_data)
    
    def _restore_file(self, file_id, user, mode, target_folder_id, current_folder_id):
        """恢复单个文件"""
        # 先尝试私有空间
        try:
            file_obj = DocumentFilePrivate.all_objects.select_for_update().get(
                id=file_id, is_deleted=True
            )
            return self._restore_private_file(file_obj, user, mode, target_folder_id, current_folder_id)
        except DocumentFilePrivate.DoesNotExist:
            pass
        
        # 再尝试公共空间
        try:
            file_obj = DocumentFilePublic.all_objects.select_for_update().get(
                id=file_id, is_deleted=True
            )
            return self._restore_public_file(file_obj, user, mode, target_folder_id, current_folder_id)
        except DocumentFilePublic.DoesNotExist:
            return {
                'id': file_id,
                'status': 'failed',
                'error': '文件不存在或未被删除',
                'code': 404001
            }
    
    def _restore_private_file(self, file_obj, user, mode, target_folder_id, current_folder_id):
        """恢复私有空间文件"""
        if not file_obj.is_deleted:
            return {'id': file_obj.id, 'status': 'failed', 'error': '文件已被恢复或不存在', 'code': 409001}
        
        if not check_permission(file_obj, user):
            return {'id': file_obj.id, 'status': 'failed', 'error': '无操作权限', 'code': 403001}
        
        # 检查原文件夹是否存在
        original_folder_exists = True
        if file_obj.folder:
            try:
                DocumentFolderPrivate.all_objects.get(id=file_obj.folder.id)
            except DocumentFolderPrivate.DoesNotExist:
                original_folder_exists = False
        
        # 恢复模式处理
        if mode == 'original':
            if not original_folder_exists:
                file_obj.folder = None
        elif mode == 'current':
            if current_folder_id:
                try:
                    target_folder = DocumentFolderPrivate.all_objects.get(id=current_folder_id)
                    file_obj.folder = target_folder
                except DocumentFolderPrivate.DoesNotExist:
                    file_obj.folder = None
            else:
                file_obj.folder = None
        elif mode == 'custom' and target_folder_id:
            try:
                target_folder = DocumentFolderPrivate.all_objects.get(id=target_folder_id)
                file_obj.folder = target_folder
            except DocumentFolderPrivate.DoesNotExist:
                return {'id': file_obj.id, 'status': 'failed', 'error': '指定文件夹不存在', 'code': 404002}
        
        # 恢复文件
        file_obj.restore()
        
        # 处理同名冲突
        from ...libs.naming_utils import generate_unique_logical_name
        file_obj.name = generate_unique_logical_name(
            DocumentFilePrivate,
            file_obj.display_name or file_obj.name,
            file_obj.folder,
            user
        )
        file_obj.save(update_fields=['folder', 'name'])
        
        # 记录审计日志
        log_operation(
            action="FILE_RESTORE",
            user=user,
            resource_type="FILE",
            resource_id=file_obj.id,
            is_public=False,
            restore_mode=mode
        )
        
        return {'id': file_obj.id, 'status': 'success', 'restored_id': file_obj.id}
    
    def _restore_public_file(self, file_obj, user, mode, target_folder_id, current_folder_id):
        """恢复公共空间文件"""
        if not file_obj.is_deleted:
            return {'id': file_obj.id, 'status': 'failed', 'error': '文件已被恢复或不存在', 'code': 409001}
        
        if not check_permission(file_obj, user):
            return {'id': file_obj.id, 'status': 'failed', 'error': '无操作权限', 'code': 403001}
        
        original_folder_exists = True
        if file_obj.folder:
            try:
                DocumentFolderPublic.all_objects.get(id=file_obj.folder.id)
            except DocumentFolderPublic.DoesNotExist:
                original_folder_exists = False
        
        if mode == 'original':
            if not original_folder_exists:
                file_obj.folder = None
        elif mode == 'current':
            if current_folder_id:
                try:
                    target_folder = DocumentFolderPublic.all_objects.get(id=current_folder_id)
                    file_obj.folder = target_folder
                except DocumentFolderPublic.DoesNotExist:
                    file_obj.folder = None
            else:
                file_obj.folder = None
        elif mode == 'custom' and target_folder_id:
            try:
                target_folder = DocumentFolderPublic.all_objects.get(id=target_folder_id)
                file_obj.folder = target_folder
            except DocumentFolderPublic.DoesNotExist:
                return {'id': file_obj.id, 'status': 'failed', 'error': '指定文件夹不存在', 'code': 404002}
        
        file_obj.restore()
        
        from ...libs.naming_utils import generate_unique_logical_name
        file_obj.name = generate_unique_logical_name(
            DocumentFilePublic,
            file_obj.display_name or file_obj.name,
            file_obj.folder,
            user
        )
        file_obj.save(update_fields=['folder', 'name'])
        
        log_operation(
            action="FILE_RESTORE",
            user=user,
            resource_type="FILE",
            resource_id=file_obj.id,
            is_public=True,
            restore_mode=mode
        )
        
        return {'id': file_obj.id, 'status': 'success', 'restored_id': file_obj.id}

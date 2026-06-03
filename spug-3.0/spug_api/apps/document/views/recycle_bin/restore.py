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
from apps.document.models import DocumentFilePrivate, DocumentFilePublic, DocumentFolderPrivate, DocumentFolderPublic
from apps.document.views.base import log_operation
from apps.document.views.recycle_bin.utils import check_rate_limit, invalidate_cache, check_permission

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
        return self._restore_file_common(
            file_obj, user, mode, target_folder_id, current_folder_id,
            DocumentFolderPrivate, is_public=False
        )

    def _restore_public_file(self, file_obj, user, mode, target_folder_id, current_folder_id):
        """恢复公共空间文件"""
        return self._restore_file_common(
            file_obj, user, mode, target_folder_id, current_folder_id,
            DocumentFolderPublic, is_public=True
        )

    def _resolve_target_folder(self, file_obj, user, mode, target_folder_id, current_folder_id,
                               FolderModel, is_public, original_folder_exists):
        """解析恢复目标文件夹

        Args:
            file_obj: 文件对象
            user: 当前用户
            mode: 恢复模式（original/current/custom）
            target_folder_id: 目标文件夹ID（custom模式）
            current_folder_id: 当前文件夹ID（current模式）
            FolderModel: 文件夹模型类
            is_public: 是否为公共空间
            original_folder_exists: 原文件夹是否存在

        Returns:
            文件夹对象或 None（失败时返回错误dict）
        """
        if mode == 'original':
            return None if not original_folder_exists else file_obj.folder

        folder_id = current_folder_id if mode == 'current' else target_folder_id
        if not folder_id:
            return None

        try:
            target_folder = FolderModel.all_objects.get(id=folder_id)
        except FolderModel.DoesNotExist:
            if mode == 'current':
                return None
            return {'id': file_obj.id, 'status': 'failed', 'error': '指定文件夹不存在', 'code': 404002}

        # 租户验证（仅私密空间）
        if not is_public:
            user_tenant = getattr(user, 'tenant_id', '') or ''
            folder_tenant = getattr(target_folder, 'tenant_id', '') or ''
            if user_tenant != folder_tenant:
                return {'id': file_obj.id, 'status': 'failed',
                        'error': '目标文件夹不属于当前租户', 'code': 403002}
        return target_folder

    def _restore_file_common(self, file_obj, user, mode, target_folder_id, current_folder_id,
                              FolderModel, is_public):
        """【P1-2重构】恢复文件的公共逻辑

        Args:
            file_obj: 文件对象（DocumentFilePrivate 或 DocumentFilePublic）
            user: 当前用户
            mode: 恢复模式（original/current/custom）
            target_folder_id: 目标文件夹ID（custom模式）
            current_folder_id: 当前文件夹ID（current模式）
            FolderModel: 文件夹模型类（DocumentFolderPrivate 或 DocumentFolderPublic）
            is_public: 是否为公共空间

        Returns:
            dict: 恢复结果
        """
        if not file_obj.is_deleted:
            return {'id': file_obj.id, 'status': 'failed', 'error': '文件已被恢复或不存在', 'code': 409001}

        if not check_permission(file_obj, user):
            return {'id': file_obj.id, 'status': 'failed', 'error': '无操作权限', 'code': 403001}

        # 检查原文件夹是否存在
        original_folder_exists = True
        if file_obj.folder:
            try:
                FolderModel.all_objects.get(id=file_obj.folder.id)
            except FolderModel.DoesNotExist:
                original_folder_exists = False

        # 设置目标文件夹
        file_obj.folder = self._resolve_target_folder(
            file_obj, user, mode, target_folder_id, current_folder_id,
            FolderModel, is_public, original_folder_exists
        )
        if file_obj.folder is None and mode in ('current', 'custom'):
            return file_obj.folder  # 返回错误信息

        # 恢复文件
        file_obj.restore()

        # 处理同名冲突
        from apps.document.libs.naming_utils import generate_unique_logical_name
        FileModel = DocumentFilePrivate if not is_public else DocumentFilePublic
        file_obj.name = generate_unique_logical_name(
            FileModel,
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
            is_public=is_public,
            restore_mode=mode
        )

        return {'id': file_obj.id, 'status': 'success', 'restored_id': file_obj.id}

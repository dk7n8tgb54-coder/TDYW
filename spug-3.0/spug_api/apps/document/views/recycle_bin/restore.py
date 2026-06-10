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
    BATCH_LIMIT = 50

    @auth('document.recycle-bin.restore')
    def post(self, request):
        """恢复软删除的文件"""
        if not check_rate_limit(request.user.id, self.RATE_LIMIT):
            return json_response(error='操作过于频繁，请稍后再试', code=429001)

        form, error = JsonParser(
            Argument('file_ids', type=list, required=True),
            Argument('idempotent_key', required=False)
        ).parse(request.body)

        if error:
            return json_response(error=error, code=400001)

        if len(form.file_ids) > self.BATCH_LIMIT:
            return json_response(error=f'批量恢复最多支持{self.BATCH_LIMIT}个文件', code=400002)

        idempotent_key = f'recycle_bin:restore:{form.idempotent_key}' if form.idempotent_key else None
        if idempotent_key and cache.get(idempotent_key):
            return json_response(data=cache.get(idempotent_key))

        all_files = self._preload_files(form)
        results, success_count = self._batch_restore(form, request.user, all_files)
        response_data = {
            'success_count': success_count,
            'failed_count': len(form.file_ids) - success_count,
            'details': results
        }

        if idempotent_key:
            cache.set(idempotent_key, response_data, 300)

        invalidate_cache(request.user.id)
        return json_response(data=response_data)

    def _preload_files(self, form):
        """批量预查询文件"""
        private_files = {
            f.id: f for f in DocumentFilePrivate.all_objects.select_for_update().filter(
                id__in=form.file_ids, is_deleted=True
            ).select_related('folder', 'created_by').order_by()
        }

        public_files = {
            f.id: f for f in DocumentFilePublic.all_objects.select_for_update().filter(
                id__in=form.file_ids, is_deleted=True
            ).select_related('folder', 'created_by').order_by()
        }

        all_files = private_files.copy()
        all_files.update(public_files)
        return all_files

    def _batch_restore(self, form, user, all_files):
        """批量恢复文件"""
        results = []
        success_count = 0
        start_time = time.time()

        try:
            with transaction.atomic():
                for file_id in form.file_ids:
                    file_obj = all_files.get(file_id)
                    result = self._restore_single_file(file_obj, user, file_id)
                    results.append(result)
                    if result['status'] == 'success':
                        success_count += 1
        except Exception as e:
            logger.error(f'[RecycleBin] 批量恢复事务失败: {e}')
            return [], 0

        duration = time.time() - start_time
        logger.info(f'[RecycleBinMetrics] operation=restore, success={success_count}, total={len(form.file_ids)}, duration={duration:.3f}s')
        return results, success_count

    def _restore_single_file(self, file_obj, user, file_id):
        """恢复单个文件（仅支持恢复到原位置）"""
        if file_obj is None:
            return {'id': file_id, 'status': 'failed', 'error': '文件不存在或未被删除', 'code': 404001}

        if not file_obj.is_deleted:
            return {'id': file_obj.id, 'status': 'failed', 'error': '文件已被恢复或不存在', 'code': 409001}

        if not check_permission(file_obj, user):
            return {'id': file_obj.id, 'status': 'failed', 'error': '无操作权限', 'code': 403001}

        is_public = isinstance(file_obj, DocumentFilePublic)
        FolderModel = DocumentFolderPublic if is_public else DocumentFolderPrivate

        # 恢复到原位置
        target_folder = None
        if file_obj.folder_id:
            try:
                FolderModel.all_objects.get(id=file_obj.folder_id)
                target_folder = file_obj.folder
            except FolderModel.DoesNotExist:
                # 原文件夹已不存在，恢复到根目录
                target_folder = None

        file_obj.folder = target_folder
        file_obj.is_deleted = False
        file_obj.deleted_at = None
        file_obj.save(update_fields=['folder', 'is_deleted', 'deleted_at'])

        from apps.document.libs.naming_utils import generate_unique_logical_name
        FileModel = DocumentFilePrivate if not is_public else DocumentFilePublic
        file_obj.name = generate_unique_logical_name(
            FileModel,
            file_obj.display_name or file_obj.name,
            target_folder,
            user
        )
        file_obj.save(update_fields=['name'])

        log_operation(
            action="FILE_RESTORE",
            user=user,
            resource_type="FILE",
            resource_id=file_obj.id,
            is_public=is_public,
            restore_mode='original'
        )

        return {'id': file_obj.id, 'status': 'success', 'restored_id': file_obj.id}



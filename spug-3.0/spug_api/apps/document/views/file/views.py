# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件管理模块 - 核心视图
提供文件的列表查询和删除功能
"""

import os
import logging
from django.views.generic import View
from django.utils import timezone

from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_file_model
from ..base import check_public_space_permission, log_operation, handle_view_errors
from ..recycle_bin.utils import invalidate_cache

logger = logging.getLogger(__name__)


class FileView(View):
    """文件视图 - 删除和列表查询"""

    @auth('document.document.delete')
    def delete(self, request):
        """
        【V3修复】文件删除操作 - 默认软删除
        
        支持两种方式：
        - 软删除（默认）：标记删除状态，物理文件保留
        - 硬删除：彻底删除数据库记录和物理文件（需传入 hard=true）
        """
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False),
            Argument('hard', type=bool, required=False, default=False)
        ).parse(request.GET)
        
        if error is not None:
            return json_response(error=error)
            
        FileModel = get_file_model(is_public=form.is_public)

        file_query = FileModel.objects.filter(pk=form.id)
        if not form.is_public:
            file_query = apply_tenant_filter(file_query, request.user, strict_mode=True)
        file = file_query.select_related('created_by').first()
        
        if not file:
            return json_response(error='文件不存在')

        # 公共空间权限校验
        if form.is_public and not check_public_space_permission(request.user, file, 'file', '删除'):
            return json_response(error='公共空间中只能删除自己创建的文件')

        try:
            if form.hard:
                # 硬删除权限检查：只有管理员可以硬删除
                if not request.user.is_supper:
                    return json_response(error='只有管理员可以硬删除文件', code=403)
                self._hard_delete(file, form.is_public)
                logger.info(f'[Document] 文件已硬删除：id={file.id}, physical_name={file.physical_name or file.name}')
            else:
                # 软删除（默认）
                file.delete(hard=False)
                logger.info(f'[Document] 文件已软删除：id={file.id}, physical_name={file.physical_name or file.name}')
            
            log_operation(
                action="FILE_DELETE",
                user=request.user,
                resource_type="FILE",
                resource_id=file.id,
                is_public=form.is_public,
                hard=form.hard,
                file_name=file.name
            )
            
            # 【修复】清除回收站缓存，确保列表和统计数量一致
            invalidate_cache(request.user.id)
            
            return json_response()
            
        except Exception as e:
            logger.error(f'[Document] 文件删除失败：{e}')
            # 【P2-6修复】返回通用错误消息，避免信息泄露
            return json_response(error='文件删除失败，请稍后重试')

    def _hard_delete(self, file_obj, is_public=False):
        """
        【P0修复】硬删除：先删除物理文件，再删除数据库记录
        
        修复时序问题：确保物理文件删除成功后再删除数据库记录
        如果物理文件删除失败，保留数据库记录以便重试
        """
        file_path = file_obj.file_path
        physical_name = file_obj.physical_name or file_obj.name
        
        # 1. 先删除物理文件
        physical_deleted = True
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f'[Document] 物理文件已删除：{file_path}')
            except Exception as e:
                logger.error(f'[Document] 物理文件删除失败：{file_path}, error={e}')
                physical_deleted = False
        
        # 2. 只有物理文件删除成功才删除数据库记录
        if physical_deleted:
            file_obj.delete(hard=True)
            logger.info(f'[Document] 数据库记录已删除：physical_name={physical_name}')
        else:
            # 标记为待清理状态，由定时任务重试
            file_obj.is_pending_clean = True
            file_obj.clean_retry_count = (file_obj.clean_retry_count or 0) + 1
            file_obj.last_clean_attempt = timezone.now()
            file_obj.save(update_fields=['is_pending_clean', 'clean_retry_count', 'last_clean_attempt'])
            raise Exception(f'物理文件删除失败，已标记为待清理: {file_path}')

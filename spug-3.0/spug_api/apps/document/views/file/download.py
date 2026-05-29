# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件下载视图
提供文件下载功能（权限检查、流式响应）
"""

import os
import logging
from django.views.generic import View
from django.http import HttpResponse
from urllib.parse import quote

from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_file_model
from ..base import log_operation

logger = logging.getLogger(__name__)


class FileDownloadView(View):
    """文件下载视图"""

    @auth('document.document.view')
    def get(self, request):
        logger.info(f'[Document] FileDownloadView.get called, user: {request.user.username}')
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)
        
        if error is not None:
            logger.error(f'[Document] Download parse error: {error}')
            return json_response(error=error)
            
        FileModel = get_file_model(is_public=form.is_public)

        logger.info(f'[Document] Downloading file id: {form.id}, is_public={form.is_public}')
        file_query = FileModel.objects.filter(pk=form.id)
        if not form.is_public:
            file_query = apply_tenant_filter(file_query, request.user, strict_mode=True)
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

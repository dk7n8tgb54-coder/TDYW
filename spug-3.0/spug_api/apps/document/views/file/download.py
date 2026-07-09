# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件下载视图
提供文件下载功能（权限检查、流式响应）
"""

import os
import logging
from django.conf import settings
from django.views.generic import View
from django.http import FileResponse
from urllib.parse import quote

from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_file_model, is_safe_path
from ...libs.document_auth import document_auth
from ...services.system_folder_service import (
    INDUSTRY_RULES_CODE, ensure_file_in_scope_or_error,
    validate_system_folder_context,
)
from ..base import log_operation

logger = logging.getLogger(__name__)


class FileDownloadView(View):
    """文件下载视图 - 使用流式响应避免内存溢出"""

    @document_auth('download')
    def get(self, request):
        logger.info(f'[Document] FileDownloadView.get called, user: {request.user.username}')
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False),
            Argument('system_folder', type=str, required=False, default=None),
        ).parse(request.GET)

        if error is not None:
            logger.error(f'[Document] Download parse error: {error}')
            return json_response(error=error)

        # 行业规章上下文校验
        ok, ctx_err = validate_system_folder_context(form.system_folder, form.is_public)
        if not ok:
            return json_response(error=ctx_err)

        FileModel = get_file_model(is_public=form.is_public)

        logger.info(f'[Document] Downloading file id: {form.id}, is_public={form.is_public}')
        file_query = FileModel.objects.filter(pk=form.id)
        if not form.is_public:
            file_query = apply_tenant_filter(file_query, request.user, strict_mode=True)
        file = file_query.select_related('created_by').first()

        if not file:
            logger.error(f'[Document] File not found with id: {form.id}')
            return json_response(error='文件不存在')

        # 行业规章范围校验
        if form.system_folder == INDUSTRY_RULES_CODE:
            scope_ok, scope_err = ensure_file_in_scope_or_error(file, INDUSTRY_RULES_CODE)
            if not scope_ok:
                return json_response(error=scope_err)

        # 【P2-2修复】路径安全检查，防止路径遍历攻击
        document_storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
        if not is_safe_path(document_storage_base, file.file_path):
            logger.error(f'[Document] Unsafe file path detected: {file.file_path}')
            return json_response(error='文件不存在')

        if not os.path.exists(file.file_path):
            logger.error(f'[Document] Physical file not found: {file.file_path}')
            return json_response(error='文件不存在')

        # 使用 FileResponse 流式下载（避免整个文件加载到内存）
        display_name = file.display_name or file.name
        encoded_filename = quote(display_name)

        response = FileResponse(
            open(file.file_path, 'rb'),
            content_type=file.file_type or 'application/octet-stream',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="{encoded_filename}"; '
            f'filename*=UTF-8\'\'{encoded_filename}'
        )
        response['Content-Length'] = os.path.getsize(file.file_path)

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

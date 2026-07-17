# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件上传视图
提供普通文件上传功能
"""

import logging
from django.views.generic import View

from libs import json_response, auth
from apps.document.libs.document_utils import get_folder_model, get_file_model
from apps.document.libs.document_auth import document_auth
from apps.document.services.system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE, validate_system_folder_context, UPLOAD_TARGET_MSG,
)
from apps.document.services.system_scope_validators import validate_upload_target_scope
from apps.document.views.base import validate_file_name, validate_file_upload, log_operation, handle_view_errors
from apps.document.services.file_upload_service import FileUploadService
from apps.document.views.upload.validators import FolderValidator

logger = logging.getLogger(__name__)


class FileUploadView(View):
    """文件上传视图"""

    @document_auth('upload')
    @handle_view_errors
    def post(self, request):
        """处理文件上传"""
        # 解析参数
        folder_id, is_public, transfer_id, system_folder = self._parse_params(request)

        logger.info(
            f'[Document] FileUploadView.post called, user: {request.user.username}, '
            f'is_public: {is_public}, folder_id: {folder_id}, transfer_id={transfer_id}, '
            f'system_folder={system_folder}'
        )

        # 党建文档上下文与上传目标校验（统一：党建正向 + 普通反向隔离）
        ok, ctx_err = validate_system_folder_context(system_folder, is_public)
        if not ok:
            return json_response(error=ctx_err)
        ok, scope_err = validate_upload_target_scope(system_folder, is_public, folder_id)
        if not ok:
            return json_response(error=scope_err)

        # 获取模型
        FolderModel = get_folder_model(is_public=is_public)
        FileModel = get_file_model(is_public=is_public)

        # 解析文件夹
        folder, error = FolderValidator.validate_folder(folder_id, is_public, request.user)
        if error:
            return json_response(error=error)

        # 获取上传文件
        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')

        # 验证文件
        error = self._validate_file(file)
        if error:
            return json_response(error=error)

        # 执行上传
        upload_service = FileUploadService(request, FolderModel, FileModel, is_public)
        new_file, error = upload_service.upload(file, folder, transfer_id)

        if error:
            return json_response(error=error)

        # 记录操作日志
        log_operation(
            action="FILE_UPLOAD",
            user=request.user,
            resource_type="FILE",
            resource_id=new_file.id,
            is_public=is_public,
            file_name=file.name,
            physical_name=new_file.physical_name,
            logical_name=new_file.name,
            file_size=file.size,
            folder_id=folder.id if folder else None
        )

        return json_response()

    def _parse_params(self, request):
        """解析请求参数"""
        folder_id = request.POST.get('folder_id')
        is_public = request.POST.get('is_public', 'false').lower() == 'true'
        transfer_id = request.POST.get('transfer_id')
        system_folder = request.POST.get('system_folder')

        # 转换folder_id为整数
        if folder_id:
            try:
                folder_id = int(folder_id)
            except (ValueError, TypeError):
                folder_id = None

        return folder_id, is_public, transfer_id, system_folder

    def _validate_file(self, file):
        """验证上传文件"""
        # 校验文件名
        if not validate_file_name(file.name):
            return '文件名包含非法字符或路径遍历符号'

        # 验证文件大小和类型
        is_valid, msg = validate_file_upload(
            file.name, file.size, max_file_size=10 * 1024 * 1024 * 1024
        )
        if not is_valid:
            return msg

        return None

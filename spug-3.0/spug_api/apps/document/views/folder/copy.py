# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件夹复制视图
提供文件夹递归复制功能
"""

import json
import logging
from django.views.generic import View

from libs import json_response, auth
from libs.tenant_utils import apply_tenant_filter
from apps.document.libs.document_utils import get_folder_model, get_file_model
from apps.document.libs.view_utils import permission_denied_response
from apps.document.libs.document_auth import document_auth
from apps.document.services.system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE, is_protected_system_root,
    is_folder_in_scope, ensure_folder_in_scope_or_error,
    validate_system_folder_context, SCOPE_ERROR_MSG, PROTECTED_ROOT_MSG,
)
from apps.document.views.base import check_public_space_permission, log_operation
from apps.document.services.folder_copy_service import FolderCopyService

logger = logging.getLogger(__name__)


class FolderCopyView(View):
    """文件夹复制视图 - 递归复制"""

    @document_auth('copy')
    def post(self, request):
        # 解析参数
        try:
            data = request._document_cached_json_body if hasattr(request, '_document_cached_json_body') else json.loads(request.body)
            folder_id = data.get('id')
            target_id = data.get('target_id')
            is_public = data.get('is_public', False)
            system_folder = data.get('system_folder')
        except:
            return json_response(error='参数错误')

        if not folder_id:
            return json_response(error='参数错误')

        # 党建文档上下文、根目录保护与范围校验
        ok, ctx_err = validate_system_folder_context(system_folder, is_public)
        if not ok:
            return json_response(error=ctx_err)
        if system_folder == PARTY_BUILDING_DOCUMENTS_CODE:
            if is_protected_system_root(folder_id):
                return json_response(error=PROTECTED_ROOT_MSG)
            scope_ok, scope_err = ensure_folder_in_scope_or_error(
                folder_id, PARTY_BUILDING_DOCUMENTS_CODE, include_root=False
            )
            if not scope_ok:
                return json_response(error=scope_err)
            if target_id and not is_folder_in_scope(target_id, PARTY_BUILDING_DOCUMENTS_CODE, include_root=True):
                return json_response(error=SCOPE_ERROR_MSG)

        # 获取模型
        FolderModel = get_folder_model(is_public=is_public)
        FileModel = get_file_model(is_public=is_public)

        # 查询源文件夹
        source_folder = self._get_source_folder(folder_id, FolderModel, request.user, is_public)
        if not source_folder:
            return json_response(error='源文件夹不存在')

        # 公共空间权限校验
        if is_public and not check_public_space_permission(
            request.user, source_folder, 'folder', '复制'
        ):
            return permission_denied_response('公共空间中只能复制自己创建的文件夹', 'not_owner')

        # 查询目标文件夹
        target_folder = self._get_target_folder(target_id, FolderModel, request.user, is_public)
        if target_id and not target_folder:
            return json_response(error='目标文件夹不存在')

        logger.info(
            f'[Document] Copying folder {source_folder.name} (id={folder_id}) '
            f'to target folder id={target_id}, is_public={is_public}'
        )

        # 执行复制
        copy_service = FolderCopyService(request.user, FolderModel, FileModel, is_public)

        # 验证复制操作
        is_valid, error_msg = copy_service.validate_copy_operation(source_folder, target_id)
        if not is_valid:
            return json_response(error=error_msg)

        # 执行复制
        copy_service.copy(source_folder, target_folder)

        # 记录操作日志
        log_operation(
            action="FOLDER_COPY",
            user=request.user,
            resource_type="FOLDER",
            resource_id=source_folder.id,
            is_public=is_public,
            source_folder_name=source_folder.name,
            target_folder_id=target_folder.id if target_folder else None
        )

        return json_response()

    def _get_source_folder(self, folder_id, FolderModel, user, is_public):
        """获取源文件夹"""
        query = FolderModel.objects.filter(pk=folder_id).order_by()
        if not is_public:
            query = apply_tenant_filter(query, user, strict_mode=True)
        return query.select_related('created_by').first()

    def _get_target_folder(self, target_id, FolderModel, user, is_public):
        """获取目标文件夹"""
        if not target_id:
            return None

        query = FolderModel.objects.filter(pk=target_id).order_by()
        if not is_public:
            query = apply_tenant_filter(query, user, strict_mode=True)
        return query.first()

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件管理模块 - 核心视图
提供文件的列表查询和删除功能
"""

import logging
from django.views.generic import View

from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_file_model
from ...libs.view_utils import permission_denied_response
from ...libs.document_auth import document_auth
from ...services.system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE, validate_system_folder_context, SCOPE_ERROR_MSG,
)
from ...services.system_scope_validators import validate_file_source_scope
from ...exceptions import DocumentPhysicalDeleteError
from ..base import check_public_space_permission, log_operation

logger = logging.getLogger(__name__)


class FileView(View):
    """文件视图 - 删除和列表查询"""

    @document_auth('delete')
    def delete(self, request):
        """
        文件删除操作 - 直接物理删除

        创建人可直接删除自己上传的文件，删除后不可恢复。
        - 公共空间：仅创建人可删除自己的文件
        - 私有空间：受租户隔离保护
        """
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False),
            Argument('system_folder', type=str, required=False, default=None),
        ).parse(request.GET)

        if error is not None:
            return json_response(error=error)

        # 党建文档上下文校验
        ok, ctx_err = validate_system_folder_context(form.system_folder, form.is_public)
        if not ok:
            return json_response(error=ctx_err)

        FileModel = get_file_model(is_public=form.is_public)

        file_query = FileModel.objects.filter(pk=form.id).order_by()
        if not form.is_public:
            file_query = apply_tenant_filter(file_query, request.user, strict_mode=True)
        file = file_query.select_related('created_by').first()

        if not file:
            return json_response(error='文件不存在')

        # 党建文档范围校验（统一：党建正向 + 普通反向隔离）
        scope_ok, scope_err = validate_file_source_scope(
            form.system_folder, form.is_public, file
        )
        if not scope_ok:
            return json_response(error=scope_err)

        # 公共空间权限校验：仅创建人可删除
        if form.is_public and not check_public_space_permission(request.user, file, 'file', '删除'):
            return permission_denied_response('公共空间中只能删除自己创建的文件', 'not_owner')

        file_name = file.name
        file_id = file.id
        try:
            # 直接物理删除（模型层负责物理文件 + 缩略图清理 + 待清理兜底）
            file.delete(hard=True)
            logger.info(f'[Document] 文件已删除：id={file_id}, name={file_name}')

            log_operation(
                action="FILE_DELETE",
                user=request.user,
                request=request,
                resource_type="FILE",
                resource_id=file_id,
                is_public=form.is_public,
                file_name=file_name
            )

            return json_response()

        except DocumentPhysicalDeleteError as e:
            # 物理文件删除失败，已标记为待清理，不算完全失败
            logger.warning(f'[Document] 物理文件删除失败，已标记待清理：{e.file_path}')
            return json_response(error='文件删除失败，已加入待清理队列，系统将自动重试')
        except Exception as e:
            logger.error(f'[Document] 文件删除失败：{e}')
            return json_response(error='文件删除失败，请稍后重试')

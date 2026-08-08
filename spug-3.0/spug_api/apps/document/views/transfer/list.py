# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
传输记录列表视图
获取用户的传输记录列表
"""

import logging
from django.views.generic import View

from libs import json_response, JsonParser, Argument
from ...libs.document_auth import document_auth
from ...services.system_folder_service import normalize_system_folder_code, validate_system_folder_context

logger = logging.getLogger(__name__)


class TransferListView(View):
    """获取用户的传输记录列表"""

    # 时间字段的统一格式化
    _DATETIME_FMT = '%Y-%m-%d %H:%M:%S'

    @document_auth('view')
    def get(self, request):
        form, error = JsonParser(
            Argument('status', type=str, required=False, help='传输状态筛选'),
            Argument('transfer_type', type=str, required=False, help='传输类型筛选'),
            Argument('is_public', type=bool, required=False, help='是否公共空间'),
            Argument('system_folder', type=str, required=False, default=None),
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        system_folder = normalize_system_folder_code(form.system_folder) if form.system_folder else None
        # 系统文件夹本身是公共空间，is_public 未提供时默认 True
        is_public = form.is_public if form.is_public is not None else (True if system_folder else False)
        ok, ctx_err = validate_system_folder_context(system_folder, is_public)
        if not ok:
            return json_response(error=ctx_err)

        queryset = self._build_queryset(request, form, system_folder)
        transfers = [self._serialize(t) for t in queryset]

        logger.info(f'[Document] User {request.user.username} fetched {len(transfers)} transfer records')
        return json_response(data=transfers)

    def _build_queryset(self, request, form, system_folder):
        """根据筛选条件构建传输记录查询集"""
        from ...models import DocumentTransfer

        request_user = request.user
        is_public_provided = getattr(form, 'is_public', None) is not None

        if is_public_provided and form.is_public:
            # 公共空间：仅按用户过滤
            queryset = DocumentTransfer.objects.filter(user=request_user, is_public=True)
        else:
            # 私有空间或未指定：按用户过滤，并追加租户隔离
            queryset = DocumentTransfer.objects.filter(user=request_user)
            if is_public_provided:
                queryset = queryset.filter(is_public=False)
            tenant_id = getattr(request_user, 'tenant_id', None)
            if tenant_id:
                queryset = queryset.filter(tenant_id=tenant_id)

        if form.status:
            queryset = queryset.filter(status=form.status)
        if form.transfer_type:
            queryset = queryset.filter(transfer_type=form.transfer_type)

        queryset = queryset.filter(system_folder=system_folder or '')
        return queryset.order_by('-created_at')[:100]

    def _serialize(self, t):
        """将单条传输记录序列化为响应字典"""
        fmt = self._DATETIME_FMT
        return {
            'id': t.id,
            'transfer_type': t.transfer_type,
            'status': t.status,
            'file_name': t.file_name,
            'file_size': t.file_size,
            'file_hash': t.file_hash or '',
            'progress': t.progress,
            'transferred_size': t.transferred_size,
            'speed': t.speed,
            'total_chunks': t.total_chunks,
            'uploaded_chunks': t.uploaded_chunks,
            'folder_id': t.folder_id,
            'is_public': t.is_public,
            'system_folder': t.system_folder or '',
            'created_at': t.created_at.strftime(fmt) if t.created_at else None,
            'started_at': t.started_at.strftime(fmt) if t.started_at else None,
            'completed_at': t.completed_at.strftime(fmt) if t.completed_at else None,
            'error_message': t.error_message,
        }

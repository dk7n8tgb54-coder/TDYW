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

logger = logging.getLogger(__name__)


class TransferListView(View):
    """获取用户的传输记录列表"""

    @document_auth('view')
    def get(self, request):
        from ...models import DocumentTransfer
        from ...constants import TransferStatus
        
        form, error = JsonParser(
            Argument('status', type=str, required=False, help='传输状态筛选'),
            Argument('transfer_type', type=str, required=False, help='传输类型筛选'),
            Argument('is_public', type=bool, required=False, help='是否公共空间'),
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        request_user = request.user

        # 根据 is_public 参数区分查询公共/私有空间的传输记录
        if hasattr(form, 'is_public') and form.is_public is not None:
            if form.is_public:
                queryset = DocumentTransfer.objects.filter(
                    user=request_user,
                    is_public=True
                )
            else:
                queryset = DocumentTransfer.objects.filter(
                    user=request_user,
                    is_public=False
                )
                if hasattr(request_user, 'tenant_id') and request_user.tenant_id:
                    queryset = queryset.filter(tenant_id=request_user.tenant_id)
        else:
            queryset = DocumentTransfer.objects.filter(user=request_user)
            if hasattr(request_user, 'tenant_id') and request_user.tenant_id:
                queryset = queryset.filter(tenant_id=request_user.tenant_id)

        # 可选：按状态筛选
        if form.status:
            queryset = queryset.filter(status=form.status)

        # 可选：按传输类型筛选
        if form.transfer_type:
            queryset = queryset.filter(transfer_type=form.transfer_type)

        # 按创建时间倒序，限制返回最近100条
        queryset = queryset.order_by('-created_at')[:100]

        # 构建响应数据
        transfers = []
        for t in queryset:
            transfers.append({
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
                'created_at': t.created_at.strftime('%Y-%m-%d %H:%M:%S') if t.created_at else None,
                'started_at': t.started_at.strftime('%Y-%m-%d %H:%M:%S') if t.started_at else None,
                'completed_at': t.completed_at.strftime('%Y-%m-%d %H:%M:%S') if t.completed_at else None,
                'error_message': t.error_message,
            })

        logger.info(f'[Document] User {request_user.username} fetched {len(transfers)} transfer records')
        return json_response(data=transfers)

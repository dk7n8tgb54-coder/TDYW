# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
传输进度更新视图
更新传输进度
"""

import logging
from django.views.generic import View

from libs import json_response, JsonParser, Argument, auth
from apps.document.libs.view_utils import permission_denied_response

logger = logging.getLogger(__name__)


class TransferProgressUpdateView(View):
    """更新传输进度"""

    @auth('document.document.upload')
    def post(self, request, transfer_id):
        from ...models import DocumentTransfer
        
        form, error = JsonParser(
            Argument('uploaded_chunks', type=int, required=False, help='已上传分片数'),
            Argument('progress', type=int, required=False, help='进度百分比'),
            Argument('transferred_size', type=int, required=False, help='已传输大小(字节)'),
            Argument('speed', type=float, required=False, help='传输速度(字节/秒)'),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        try:
            transfer = DocumentTransfer.objects.get(id=transfer_id)

            # 权限检查
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            if (transfer.user != request.user and not is_supper) or \
               (transfer.tenant_id != request_tenant_id and not is_supper):
                return permission_denied_response('无权更新此传输记录', 'not_owner')

            # 更新字段
            if form.uploaded_chunks is not None:
                transfer.uploaded_chunks = form.uploaded_chunks
            if form.progress is not None:
                transfer.progress = form.progress
            if form.transferred_size is not None:
                transfer.transferred_size = form.transferred_size
            if form.speed is not None:
                transfer.speed = form.speed

            transfer.save()
            return json_response(data={'status': 'updated'})

        except DocumentTransfer.DoesNotExist:
            return json_response(error='传输记录不存在')
        except Exception as e:
            logger.error(f'[Document] Error updating transfer progress: {e}')
            return json_response(error=f'更新进度失败: {str(e)}')

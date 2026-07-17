# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
传输记录创建视图
创建传输记录
"""

import logging
from django.views.generic import View

from libs import json_response, JsonParser, Argument
from ...libs.document_auth import document_auth
from ...services.system_folder_service import normalize_system_folder_code
from ...services.system_scope_validators import validate_upload_target_scope

logger = logging.getLogger(__name__)


class TransferCreateView(View):
    """创建传输记录"""

    @document_auth('upload')
    def post(self, request):
        from ...models import DocumentTransfer
        from ...constants import TransferStatus
        
        logger.info(f'[Document] Transfer create request body: {request.body}')
        
        form, error = JsonParser(
            Argument('transfer_type', type=str, required=True, help='传输类型：UPLOAD/DOWNLOAD'),
            Argument('file_name', type=str, required=True, help='文件名'),
            Argument('file_size', type=int, required=True, help='文件大小(字节)'),
            Argument('file_hash', type=str, required=False, default='', help='文件哈希(MD5)'),
            Argument('folder_id', type=int, required=False, default=None),
            Argument('is_public', type=bool, required=False, default=False, help='是否公共空间'),
            Argument('total_chunks', type=int, required=False, default=None, help='总分片数'),
            Argument('system_folder', type=str, required=False, default=None),
        ).parse(request.body)

        if error:
            logger.error(f'[Document] Transfer create parse error: {error}')
            return json_response(error=error)

        system_folder = normalize_system_folder_code(form.system_folder) if form.system_folder else None
        ok, scope_err = validate_upload_target_scope(
            system_folder,
            form.is_public or False,
            form.folder_id,
            require_folder=form.transfer_type == 'upload',
        )
        if not ok:
            return json_response(error=scope_err)

        request_user = request.user
        tenant_id = getattr(request_user, 'tenant_id', '')

        # 创建传输记录
        try:
            transfer = DocumentTransfer.objects.create(
                tenant_id=tenant_id,
                user=request_user,
                transfer_type=form.transfer_type,
                status=TransferStatus.PENDING.value,
                file_name=form.file_name,
                file_size=form.file_size,
                file_path='',
                file_hash=form.file_hash or '',
                folder_id=form.folder_id,
                is_public=form.is_public or False,
                system_folder=system_folder or '',
                total_chunks=form.total_chunks or 0,
                uploaded_chunks=0,
                progress=0,
                transferred_size=0,
                speed=0,
            )

            logger.info(f'[Document] Created transfer record: id={transfer.id}, file={form.file_name}')
            return json_response(data={'id': transfer.id, 'status': TransferStatus.PENDING.value.lower()})
        except Exception as e:
            logger.error(f'[Document] Error creating transfer record: {e}')
            return json_response(error=f'创建传输记录失败: {str(e)}')

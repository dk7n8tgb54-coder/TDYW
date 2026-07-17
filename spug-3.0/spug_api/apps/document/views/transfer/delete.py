# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
传输记录删除视图
删除传输记录和更新哈希
"""

import logging
from django.views.generic import View

from libs import json_response, JsonParser, Argument
from ...libs.document_auth import document_auth
from .transfer_manager import TransferRecordManager, validate_transfer_request_scope

logger = logging.getLogger(__name__)


class TransferDeleteView(View):
    """删除传输记录"""

    @document_auth('upload')
    def delete(self, request, transfer_id):
        # 获取传输记录
        transfer, error = TransferRecordManager.get_transfer_by_id(transfer_id)
        if error:
            return json_response(error=error)

        # 作用域一致性校验
        scope_ok, scope_err = validate_transfer_request_scope(request, transfer)
        if not scope_ok:
            return json_response(error=scope_err)

        # 删除传输记录
        success, error = TransferRecordManager.delete_transfer(transfer, request.user)
        if not success:
            return json_response(error=error)

        return json_response(data={'status': 'deleted'})


class TransferHashUpdateView(View):
    """更新传输记录的 file_hash"""

    @document_auth('upload')
    def post(self, request, transfer_id):
        # 获取传输记录
        transfer, error = TransferRecordManager.get_transfer_by_id(transfer_id)
        if error:
            return json_response(error=error)

        # 作用域一致性校验
        scope_ok, scope_err = validate_transfer_request_scope(request, transfer)
        if not scope_ok:
            return json_response(error=scope_err)

        # 解析请求参数
        form, error = JsonParser(
            Argument('file_hash', type=str, required=True, help='文件哈希(MD5)'),
            Argument('total_chunks', type=int, required=False, default=None)
        ).parse(request.body)

        if error:
            return json_response(error=error)

        # 更新哈希
        success, error = TransferRecordManager.update_transfer_hash(
            transfer, request.user, form.file_hash, form.total_chunks
        )
        if not success:
            return json_response(error=error)

        return json_response(data={'status': 'updated', 'file_hash': form.file_hash})

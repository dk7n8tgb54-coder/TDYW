# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""File move view."""

import json
import logging

from django.views.generic import View

from libs import json_response
from libs.tenant_utils import apply_tenant_filter

from ...libs.document_auth import document_auth
from ...libs.document_utils import get_file_model, get_folder_model
from ...libs.naming_utils import generate_unique_logical_name
from ...libs.view_utils import permission_denied_response
from ...services.system_scope_validators import validate_file_move_scope
from ..base import check_public_space_permission, log_operation

logger = logging.getLogger(__name__)


class FileMoveView(View):
    """Move a file by updating its folder relation only."""

    @document_auth('move')
    def post(self, request):
        params, error = self._parse_request(request)
        if error:
            return json_response(error=error)

        is_valid, scope_error = validate_file_move_scope(
            params['system_folder'],
            params['is_public'],
            target_id=params['target_id'],
        )
        if not is_valid:
            return json_response(error=scope_error)

        FileModel = get_file_model(is_public=params['is_public'])
        FolderModel = get_folder_model(is_public=params['is_public'])

        file_obj = self._get_file(FileModel, params, request.user)
        if not file_obj:
            return json_response(error='文件不存在')

        permission_error = self._check_public_permission(request.user, file_obj, params['is_public'])
        if permission_error:
            return permission_error

        is_valid, scope_error = validate_file_move_scope(
            params['system_folder'],
            params['is_public'],
            file_obj=file_obj,
            target_id=params['target_id'],
        )
        if not is_valid:
            return json_response(error=scope_error)

        target = self._get_target_folder(FolderModel, params, request.user)
        if params['target_id'] and not target:
            return json_response(error='目标文件夹不存在')

        current_folder_id = file_obj.folder_id if file_obj.folder else None
        if current_folder_id == params['target_id']:
            return json_response()

        return self._move_file(FileModel, file_obj, target, params, request)

    def _parse_request(self, request):
        try:
            data = getattr(request, '_document_cached_json_body', None) or json.loads(request.body)
        except Exception:
            return None, '参数错误'
        return {
            'file_id': data.get('id'),
            'target_id': data.get('target_id'),
            'is_public': data.get('is_public', False),
            'system_folder': data.get('system_folder'),
        }, None

    def _get_file(self, FileModel, params, user):
        query = FileModel.objects.filter(pk=params['file_id']).order_by()
        if not params['is_public']:
            query = apply_tenant_filter(query, user, strict_mode=True)
        return query.select_related('created_by').first()

    def _check_public_permission(self, user, file_obj, is_public):
        if not is_public:
            return None
        if check_public_space_permission(user, file_obj, 'file', '移动'):
            return None
        return permission_denied_response('公共空间中只能移动自己创建的文件', 'not_owner')

    def _get_target_folder(self, FolderModel, params, user):
        target_id = params['target_id']
        if not target_id:
            return None
        query = FolderModel.objects.filter(pk=target_id).order_by()
        if not params['is_public']:
            query = apply_tenant_filter(query, user, strict_mode=True)
        return query.first()

    def _move_file(self, FileModel, file_obj, target, params, request):
        try:
            file_obj.folder = target
            file_obj.name = generate_unique_logical_name(
                FileModel,
                file_obj.display_name or file_obj.name,
                target,
                request.user,
            )
            file_obj.save(update_fields=['folder', 'name', 'updated_at'])
        except Exception as exc:
            logger.error('[Document] file move failed: %s', exc)
            return json_response(error=f'文件移动失败：{exc}')

        log_operation(
            action='FILE_MOVE',
            user=request.user,
            resource_type='FILE',
            resource_id=file_obj.id,
            is_public=params['is_public'],
            target_folder_id=params['target_id'],
        )
        logger.info('[Document] file moved successfully, id=%s', file_obj.id)
        return json_response()

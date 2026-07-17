# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""Folder move view."""

import json
import logging

from django.views.generic import View
from django.db import transaction

from libs import json_response
from libs.tenant_utils import apply_tenant_filter, check_tenant_unique_name

from ...libs.document_auth import document_auth
from ...libs.document_utils import get_folder_model, is_child_folder
from ...libs.view_utils import permission_denied_response
from ...services.system_scope_validators import (
    validate_folder_move_scope, validate_target_folder_scope,
)
from ..base import check_public_space_permission, log_operation

logger = logging.getLogger(__name__)


class FolderMoveView(View):
    """Move a folder within the current document space."""

    @document_auth('move')
    def post(self, request):
        params, error = self._parse_request(request)
        if error:
            return json_response(error=error)

        ok, scope_error = validate_folder_move_scope(
            params['system_folder'], params['is_public'], params['folder_id'], params['target_id']
        )
        if not ok:
            return json_response(error=scope_error)

        FolderModel = get_folder_model(is_public=params['is_public'])
        folder = self._get_folder(FolderModel, params['folder_id'], params, request.user)
        if not folder:
            return json_response(error='文件夹不存在')

        permission_error = self._check_public_permission(request.user, folder, params['is_public'])
        if permission_error:
            return permission_error

        target, error = self._resolve_target(FolderModel, folder, params, request.user)
        if error:
            return json_response(error=error)

        # 【作用域重校验】写入前在事务内重新校验目标目录作用域，防 TOCTOU
        if params['target_id']:
            ok, err = validate_target_folder_scope(
                params['system_folder'], params['is_public'],
                params['target_id'], allow_root=True,
            )
            if not ok:
                return json_response(error=err)

        with transaction.atomic():
            folder.parent = target
            folder.save()

        log_operation(
            action='FOLDER_MOVE',
            user=request.user,
            resource_type='FOLDER',
            resource_id=folder.id,
            is_public=params['is_public'],
            target_folder_id=params['target_id'],
        )
        logger.info('[Document] folder moved successfully, is_public=%s', params['is_public'])
        return json_response()

    def _parse_request(self, request):
        try:
            data = getattr(request, '_document_cached_json_body', None) or json.loads(request.body)
        except Exception:
            return None, '参数错误'
        folder_id = data.get('id')
        if not folder_id:
            return None, '参数错误'
        return {
            'folder_id': folder_id,
            'target_id': data.get('target_id'),
            'is_public': data.get('is_public', False),
            'system_folder': data.get('system_folder'),
        }, None

    def _get_folder(self, FolderModel, folder_id, params, user):
        query = FolderModel.objects.filter(pk=folder_id).order_by()
        if not params['is_public']:
            query = apply_tenant_filter(query, user, strict_mode=True)
        return query.select_related('created_by').first()

    def _check_public_permission(self, user, folder, is_public):
        if not is_public:
            return None
        if check_public_space_permission(user, folder, 'folder', '移动'):
            return None
        return permission_denied_response('公共空间中只能移动自己创建的文件夹', 'not_owner')

    def _resolve_target(self, FolderModel, folder, params, user):
        target_id = params['target_id']
        if not target_id:
            return self._resolve_root_target(FolderModel, folder, params, user)

        target = self._get_folder(FolderModel, target_id, params, user)
        if not target:
            return None, '目标文件夹不存在'
        if folder.id == target_id or is_child_folder(target.id, folder.id, FolderModel, user, params['is_public']):
            return None, '无法移动到自身或子文件夹中'
        if self._name_exists(FolderModel, folder.name, target_id, params, user):
            return None, '目标位置已存在同名文件夹'
        return target, None

    def _resolve_root_target(self, FolderModel, folder, params, user):
        if self._name_exists(FolderModel, folder.name, None, params, user):
            return None, '根目录已存在同名文件夹'
        return None, None

    def _name_exists(self, FolderModel, name, parent_id, params, user):
        filters = {'name': name}
        if parent_id is None:
            filters['parent__isnull'] = True
        else:
            filters['parent_id'] = parent_id
        is_unique, _ = check_tenant_unique_name(FolderModel, filters, user, params['is_public'])
        return not is_unique

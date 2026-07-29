# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""Folder rename view."""

import json
import logging

from django.views.generic import View

from libs import json_response
from libs.tenant_utils import apply_tenant_filter

from ...libs.document_auth import document_auth
from ...libs.document_utils import get_folder_model
from ...libs.view_utils import permission_denied_response
from ...services.system_scope_validators import validate_folder_operation_scope
from ..base import check_public_space_permission, log_operation, validate_file_name

logger = logging.getLogger(__name__)


class FolderRenameView(View):
    """Rename a folder."""

    @document_auth('rename')
    def post(self, request):
        params, error = self._parse_request(request)
        if error:
            return json_response(error=error)

        error = self._validate_name(params)
        if error:
            return json_response(error=error)

        ok, scope_error = validate_folder_operation_scope(
            params['system_folder'],
            params['is_public'],
            folder_id=params['folder_id'],
            include_root=False,
            protect_root=True,
        )
        if not ok:
            return json_response(error=scope_error)

        FolderModel = get_folder_model(is_public=params['is_public'])
        folder = self._get_folder(FolderModel, params, request.user)
        if not folder:
            return json_response(error='文件夹不存在')

        permission_error = self._check_public_permission(request.user, folder, params['is_public'])
        if permission_error:
            return permission_error

        if self._name_exists(FolderModel, params, folder, request.user):
            return json_response(error='该文件夹名称已存在')

        original_name = folder.name
        folder.name = params['name']
        folder.save()

        log_operation(
            action='FOLDER_RENAME',
            user=request.user,
            request=request,
            resource_type='FOLDER',
            resource_id=folder.id,
            is_public=params['is_public'],
            original_name=original_name,
            new_name=params['name'],
        )
        logger.info('[Document] folder renamed: %s -> %s', original_name, params['name'])
        return json_response()

    def _parse_request(self, request):
        try:
            data = getattr(request, '_document_cached_json_body', None) or json.loads(request.body)
        except Exception:
            return None, '参数错误'
        return {
            'folder_id': data.get('id'),
            'name': data.get('name'),
            'is_public': data.get('is_public', False),
            'system_folder': data.get('system_folder'),
        }, None

    def _validate_name(self, params):
        if not params['folder_id']:
            return '参数错误'
        name = params['name']
        if not name or not name.strip():
            return '文件夹名称不能为空'
        if not validate_file_name(name):
            return '文件夹名称包含非法字符'
        return None

    def _get_folder(self, FolderModel, params, user):
        query = FolderModel.objects.filter(pk=params['folder_id']).order_by()
        if not params['is_public']:
            query = apply_tenant_filter(query, user, strict_mode=True)
        return query.select_related('created_by').first()

    def _check_public_permission(self, user, folder, is_public):
        if not is_public:
            return None
        if check_public_space_permission(user, folder, 'folder', '重命名'):
            return None
        return permission_denied_response('公共空间中只能重命名自己创建的文件夹', 'not_owner')

    def _name_exists(self, FolderModel, params, folder, user):
        query = FolderModel.objects.filter(
            parent_id=folder.parent_id,
            name=params['name'],
        ).exclude(pk=params['folder_id']).order_by()
        if not params['is_public']:
            query = apply_tenant_filter(query, user)
        return query.exists()

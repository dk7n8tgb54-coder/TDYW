# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""File rename view."""

import json
import logging

from django.db import transaction
from django.views.generic import View

from libs import json_response
from libs.tenant_utils import apply_tenant_filter

from ...libs.document_auth import document_auth
from ...libs.document_utils import get_file_model
from ...libs.view_utils import permission_denied_response
from ...services.system_scope_validators import validate_file_operation_scope
from ..base import check_public_space_permission, log_operation, validate_file_name

logger = logging.getLogger(__name__)


class FileRenameView(View):
    """Rename a file display name."""

    @document_auth('rename')
    def post(self, request):
        params, error = self._parse_request(request)
        if error:
            return json_response(error=error)

        error = self._validate_name(params)
        if error:
            return json_response(error=error)

        ok, scope_error = validate_file_operation_scope(
            params['system_folder'], params['is_public']
        )
        if not ok:
            return json_response(error=scope_error)

        FileModel = get_file_model(is_public=params['is_public'])
        file_obj = self._get_file(FileModel, params, request.user)
        if not file_obj:
            return json_response(error='文件不存在')

        ok, scope_error = validate_file_operation_scope(
            params['system_folder'], params['is_public'], file_obj
        )
        if not ok:
            return json_response(error=scope_error)

        permission_error = self._check_public_permission(request.user, file_obj, params['is_public'])
        if permission_error:
            return permission_error

        # 事务内完成 _name_exists 检查 + save，防止 TOCTOU 并发竞态
        with transaction.atomic():
            if self._name_exists(FileModel, params, file_obj, request.user):
                return json_response(error='该文件名称已存在')
            file_obj = FileModel.objects.select_for_update().get(pk=file_obj.pk)
            original_name = file_obj.display_name or file_obj.name
            file_obj.display_name = params['name']
            file_obj.save(update_fields=['display_name'])

        log_operation(
            action='FILE_RENAME',
            user=request.user,
            request=request,
            resource_type='FILE',
            resource_id=file_obj.id,
            is_public=params['is_public'],
            original_name=original_name,
            new_name=params['name'],
        )
        logger.info('[Document] file renamed: %s -> %s', original_name, params['name'])
        return json_response()

    def _parse_request(self, request):
        try:
            data = getattr(request, '_document_cached_json_body', None) or json.loads(request.body)
        except Exception:
            return None, '参数错误'
        return {
            'file_id': data.get('id'),
            'name': data.get('name'),
            'is_public': data.get('is_public', False),
            'system_folder': data.get('system_folder'),
        }, None

    def _validate_name(self, params):
        if not params['file_id']:
            return '参数错误'
        name = params['name']
        if not name or not name.strip():
            return '文件名称不能为空'
        if not validate_file_name(name):
            return '文件名包含非法字符'
        return None

    def _get_file(self, FileModel, params, user):
        query = FileModel.objects.filter(pk=params['file_id']).order_by()
        if not params['is_public']:
            query = apply_tenant_filter(query, user, strict_mode=True)
        return query.select_related('created_by').first()

    def _check_public_permission(self, user, file_obj, is_public):
        if not is_public:
            return None
        if check_public_space_permission(user, file_obj, 'file', '重命名'):
            return None
        return permission_denied_response('公共空间中只能重命名自己创建的文件', 'not_owner')

    def _name_exists(self, FileModel, params, file_obj, user):
        query = FileModel.objects.filter(
            folder_id=file_obj.folder_id,
            display_name=params['name'],
        ).exclude(pk=params['file_id']).order_by()
        if not params['is_public']:
            query = apply_tenant_filter(query, user, strict_mode=True)
        return query.exists()

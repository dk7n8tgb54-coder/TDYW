# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件重命名视图
提供文件重命名功能
"""

import json
import logging
from django.views.generic import View

from libs import json_response, auth
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_file_model
from ..base import validate_file_name, check_public_space_permission, log_operation

logger = logging.getLogger(__name__)


class FileRenameView(View):
    """文件重命名视图"""

    @auth('document.document.rename')
    def post(self, request):
        try:
            data = json.loads(request.body)
            file_id = data.get('id')
            name = data.get('name')
            is_public = data.get('is_public', False)
        except:
            return json_response(error='参数错误')

        if not file_id:
            return json_response(error='参数错误')

        if not name or name.strip() == '':
            return json_response(error='文件名称不能为空')

        # 校验文件名安全性
        if not validate_file_name(name):
            return json_response(error='文件名包含非法字符')

        FileModel = get_file_model(is_public=is_public)

        file_query = FileModel.objects.filter(pk=file_id)
        if not is_public:
            file_query = apply_tenant_filter(file_query, request.user, strict_mode=True)
        file = file_query.select_related('created_by').first()
        
        if not file:
            return json_response(error='文件不存在')

        # 公共空间权限校验
        if is_public and not check_public_space_permission(request.user, file, 'file', '重命名'):
            return json_response(error='公共空间中只能重命名自己创建的文件')

        # 检查同一文件夹下是否存在同名文件（排除自己，添加租户过滤）
        existing_file_query = FileModel.objects.filter(
            folder_id=file.folder_id,
            display_name=name
        ).exclude(pk=file_id)

        if not is_public:
            existing_file_query = apply_tenant_filter(existing_file_query, request.user, strict_mode=True)

        existing_file = existing_file_query.first()

        if existing_file:
            return json_response(error='该文件名称已存在')

        # 更新display_name（用户看到的文件名），不修改物理文件名
        original_display_name = file.display_name or file.name
        file.display_name = name

        file.save()
        
        log_operation(
            action="FILE_RENAME",
            user=request.user,
            resource_type="FILE",
            resource_id=file.id,
            is_public=is_public,
            original_name=original_display_name,
            new_name=name
        )
        logger.info(f'[Document] File display_name renamed: {original_display_name} -> {name}, is_public={is_public}')
        return json_response()

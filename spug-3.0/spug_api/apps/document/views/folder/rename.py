# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件夹重命名视图
提供文件夹重命名功能
"""

import json
import logging
from django.views.generic import View

from libs import json_response, auth
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_folder_model
from ..base import validate_file_name, check_public_space_permission, log_operation

logger = logging.getLogger(__name__)


class FolderRenameView(View):
    """文件夹重命名视图"""

    @auth('document.document.rename')
    def post(self, request):
        try:
            data = json.loads(request.body)
            folder_id = data.get('id')
            name = data.get('name')
            is_public = data.get('is_public', False)
        except:
            return json_response(error='参数错误')

        if not folder_id:
            return json_response(error='参数错误')

        if not name or name.strip() == '':
            return json_response(error='文件夹名称不能为空')

        # 校验文件夹名称安全性
        if not validate_file_name(name):
            return json_response(error='文件夹名称包含非法字符')

        FolderModel = get_folder_model(is_public=is_public)

        folder_query = FolderModel.objects.filter(pk=folder_id)
        if not is_public:
            folder_query = apply_tenant_filter(folder_query, request.user, strict_mode=True)
        folder = folder_query.select_related('created_by').first()
        
        if not folder:
            return json_response(error='文件夹不存在')

        # 公共空间权限校验
        if is_public and not check_public_space_permission(request.user, folder, 'folder', '重命名'):
            return json_response(error='公共空间中只能重命名自己创建的文件夹')

        # 检查同一文件夹下是否存在同名文件夹（排除自己，添加租户过滤）
        existing_folder_query = FolderModel.objects.filter(
            parent_id=folder.parent_id,
            name=name
        ).exclude(pk=folder_id)

        if not is_public:
            existing_folder_query = apply_tenant_filter(existing_folder_query, request.user)

        existing_folder = existing_folder_query.first()

        if existing_folder:
            return json_response(error='该文件夹名称已存在')

        original_name = folder.name
        folder.name = name
        folder.save()
        
        log_operation(
            action="FOLDER_RENAME",
            user=request.user,
            resource_type="FOLDER",
            resource_id=folder.id,
            is_public=is_public,
            original_name=original_name,
            new_name=name
        )
        logger.info(f'[Document] Folder renamed: {original_name} -> {name}, is_public={is_public}')
        return json_response()

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件夹移动视图
提供文件夹移动功能（循环引用检测）
"""

import json
import logging
from django.views.generic import View

from libs import json_response, auth
from libs.tenant_utils import apply_tenant_filter, check_tenant_unique_name
from ...libs.document_utils import get_folder_model, is_child_folder
from ..base import check_public_space_permission, log_operation

logger = logging.getLogger(__name__)


class FolderMoveView(View):
    """文件夹移动视图 - 循环引用检测"""

    @auth('document.document.move')
    def post(self, request):
        try:
            data = json.loads(request.body)
            folder_id = data.get('id')
            target_id = data.get('target_id')
            is_public = data.get('is_public', False)
        except:
            return json_response(error='参数错误')

        if not folder_id:
            return json_response(error='参数错误')

        FolderModel = get_folder_model(is_public=is_public)

        folder_query = FolderModel.objects.filter(pk=folder_id)
        if not is_public:
            folder_query = apply_tenant_filter(folder_query, request.user, strict_mode=True)
        folder = folder_query.select_related('created_by').first()
        
        if not folder:
            return json_response(error='文件夹不存在')

        # 公共空间权限校验
        if is_public and not check_public_space_permission(request.user, folder, 'folder', '移动'):
            return json_response(error='公共空间中只能移动自己创建的文件夹')

        if target_id:
            target_query = FolderModel.objects.filter(pk=target_id)
            if not is_public:
                target_query = apply_tenant_filter(target_query, request.user, strict_mode=True)
            target = target_query.first()
            if not target:
                return json_response(error='目标文件夹不存在')
                
            # 防止循环引用
            if folder.id == target_id or is_child_folder(target.id, folder.id, FolderModel, request.user, is_public):
                return json_response(error='无法移动到自身或子文件夹下')

            # 检查目标位置是否已存在同名文件夹
            is_unique, _ = check_tenant_unique_name(
                FolderModel,
                {'parent_id': target_id, 'name': folder.name},
                request.user,
                is_public
            )
            if not is_unique:
                return json_response(error='目标位置已存在同名文件夹')

            folder.parent = target
        else:
            # 检查根目录下是否已存在同名文件夹
            is_unique, _ = check_tenant_unique_name(
                FolderModel,
                {'parent__isnull': True, 'name': folder.name},
                request.user,
                is_public
            )
            if not is_unique:
                return json_response(error='根目录已存在同名文件夹')

            folder.parent = None
            
        folder.save()
        
        log_operation(
            action="FOLDER_MOVE",
            user=request.user,
            resource_type="FOLDER",
            resource_id=folder.id,
            is_public=is_public,
            target_folder_id=target_id
        )
        logger.info(f'[Document] Folder moved successfully, is_public={is_public}')
        return json_response()

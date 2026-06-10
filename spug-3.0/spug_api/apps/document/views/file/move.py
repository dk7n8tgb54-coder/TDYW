# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件移动视图
提供文件移动功能
"""

import json
import logging
from django.views.generic import View

from libs import json_response, auth
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_folder_model, get_file_model
from ...libs.naming_utils import generate_unique_logical_name
from ...libs.view_utils import permission_denied_response
from ..base import check_public_space_permission, log_operation

logger = logging.getLogger(__name__)


class FileMoveView(View):
    """
    文件移动视图
    
    核心原则：只改 folder_id，不移动物理文件
    - physical_name 终身不变
    - file_path 终身不变
    - 只修改数据库中的 folder 关联
    """

    @auth('document.document.move')
    def post(self, request):
        try:
            data = json.loads(request.body)
            file_id = data.get('id')
            target_id = data.get('target_id')
            is_public = data.get('is_public', False)
        except:
            return json_response(error='参数错误')

        FileModel = get_file_model(is_public=is_public)
        FolderModel = get_folder_model(is_public=is_public)

        # 查询文件
        file_query = FileModel.objects.filter(pk=file_id).order_by()
        if not is_public:
            file_query = apply_tenant_filter(file_query, request.user, strict_mode=True)
        file = file_query.select_related('created_by').first()
        
        if not file:
            return json_response(error='文件不存在')

        # 公共空间权限校验
        if is_public and not check_public_space_permission(request.user, file, 'file', '移动'):
            return permission_denied_response('公共空间中只能移动自己创建的文件', 'not_owner')

        # 查询目标文件夹
        target = None
        if target_id:
            target_query = FolderModel.objects.filter(pk=target_id).order_by()
            if not is_public:
                target_query = apply_tenant_filter(target_query, request.user, strict_mode=True)
            target = target_query.first()
            if not target:
                return json_response(error='目标文件夹不存在')

        # 如果已经在目标文件夹，无需操作
        current_folder_id = file.folder.id if file.folder else None
        if current_folder_id == target_id:
            return json_response()

        # 移动操作：只改 folder_id，不移动物理文件
        try:
            # 1. 更新文件夹关联
            file.folder = target
            
            # 2. 生成新的逻辑名（处理同名冲突）
            try:
                file.name = generate_unique_logical_name(
                    FileModel,
                    file.display_name or file.name,
                    target,
                    request.user
                )
            except Exception as e:
                logger.error(f'[Document] 生成唯一逻辑名失败：{e}')
                return json_response(error='文件移动失败：生成文件名失败')
            
            # 3. physical_name 和 file_path 终身不变
            file.save(update_fields=['folder', 'name', 'updated_at'])
            
            log_operation(
                action="FILE_MOVE",
                user=request.user,
                resource_type="FILE",
                resource_id=file.id,
                is_public=is_public,
                target_folder_id=target_id
            )
            
            logger.info(f'[Document] 文件移动成功：id={file.id}, target_folder={target_id}')
            return json_response()
            
        except Exception as e:
            logger.error(f'[Document] 文件移动失败：{e}')
            return json_response(error=f'文件移动失败：{str(e)}')

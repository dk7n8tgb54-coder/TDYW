# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件夹属性统计视图
递归统计文件夹内所有层级的子文件夹数、文件数和总大小
"""

import logging
from django.views.generic import View
from django.db.models import Sum, Count

from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_folder_model, get_file_model
from ...libs.view_utils import permission_denied_response

logger = logging.getLogger(__name__)


def get_active_descendant_folder_ids(folder_obj, FolderModel):
    """
    BFS 获取文件夹及其所有子孙文件夹ID（仅未删除的）

    Args:
        folder_obj: 起始文件夹对象
        FolderModel: 文件夹模型类

    Returns:
        list: 文件夹ID列表（包含起始文件夹自身）
    """
    folder_ids = []
    queue = [folder_obj]

    while queue:
        current = queue.pop(0)
        folder_ids.append(current.id)
        children = FolderModel.objects.filter(parent=current, is_deleted=False)
        queue.extend(children)

    return folder_ids


class FolderPropertiesView(View):
    """文件夹属性统计（递归所有层级）"""

    @auth('document.document.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=True, help='文件夹ID'),
            Argument('is_public', type=bool, required=False, default=False),
        ).parse(request.GET)

        if error is not None:
            return json_response(error=error)

        FolderModel = get_folder_model(is_public=form.is_public)
        FileModel = get_file_model(is_public=form.is_public)

        # 查找目标文件夹
        query = FolderModel.objects.filter(id=form.id, is_deleted=False)
        if not form.is_public:
            query = apply_tenant_filter(query, request.user, strict_mode=True)

        try:
            folder = query.select_related('created_by').first()
        except Exception:
            folder = None

        if folder is None:
            return json_response(error='文件夹不存在或无权访问')

        # 权限检查：公共空间普通用户只能查看自己创建的
        if form.is_public and not request.user.is_supper:
            if folder.created_by_id != request.user.id:
                return permission_denied_response('无权查看该文件夹属性')

        # BFS 获取所有子孙文件夹ID
        all_folder_ids = get_active_descendant_folder_ids(folder, FolderModel)

        # 子文件夹数量（不含自身）
        sub_folder_count = len(all_folder_ids) - 1

        # 聚合查询：所有层级文件的数量和大小
        file_stats = FileModel.objects.filter(
            folder_id__in=all_folder_ids,
            is_deleted=False,
        ).aggregate(
            total_files=Count('id'),
            total_size=Sum('file_size'),
        )

        total_files = file_stats['total_files'] or 0
        total_size = file_stats['total_size'] or 0

        return json_response({
            'id': folder.id,
            'name': folder.name,
            'parent_id': folder.parent_id,
            'sub_folder_count': sub_folder_count,
            'file_count': total_files,
            'total_size': total_size,
            'created_at': folder.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': folder.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            'created_by': folder.created_by.nickname if folder.created_by else None,
        })

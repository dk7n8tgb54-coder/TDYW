# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件夹/文件属性统计视图
递归统计文件夹内所有层级的子文件夹数、文件数和总大小
同时返回文件/文件夹的完整路径
"""

import logging
from django.views.generic import View
from django.db.models import Sum, Count

from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_folder_model, get_file_model
from ...libs.view_utils import permission_denied_response
from ...libs.document_auth import document_auth
from ...services.system_folder_service import (
    INDUSTRY_RULES_CODE, ensure_folder_in_scope_or_error,
    ensure_file_in_scope_or_error, validate_system_folder_context,
)

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


def _get_folder_path(folder_obj):
    """
    获取文件夹的所在位置路径（即父级链路）
    根目录下的文件夹返回"根目录"，否则返回如"文件夹A/子文件夹B"

    Args:
        folder_obj: 文件夹模型实例

    Returns:
        str: 位置路径字符串
    """
    if folder_obj.parent_id is None:
        return '根目录'
    # get_full_path() 返回的是自身名称+父级链路
    # 我们需要的是父级链路（不含自身），即"所在位置"
    return folder_obj.parent.get_full_path()


class FolderPropertiesView(View):
    """文件夹/文件属性统计（递归所有层级）"""

    @document_auth('view')
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=True, help='文件/文件夹ID'),
            Argument('is_public', type=bool, required=False, default=False),
            Argument('type', type=str, required=False, default='folder', help='类型: folder 或 file'),
            Argument('system_folder', type=str, required=False, default=None),
        ).parse(request.GET)

        if error is not None:
            return json_response(error=error)

        # 行业规章上下文校验
        ok, ctx_err = validate_system_folder_context(form.system_folder, form.is_public)
        if not ok:
            return json_response(error=ctx_err)

        FolderModel = get_folder_model(is_public=form.is_public)
        FileModel = get_file_model(is_public=form.is_public)

        if form.type == 'file':
            return self._get_file_properties(request, FileModel, FolderModel, form)

        # ===== 文件夹属性 =====
        query = FolderModel.objects.filter(id=form.id, is_deleted=False)
        if not form.is_public:
            query = apply_tenant_filter(query, request.user, strict_mode=True)

        try:
            folder = query.select_related('created_by', 'parent').first()
        except Exception:
            folder = None

        if folder is None:
            return json_response(error='文件夹不存在或无权访问')

        # 行业规章范围校验（文件夹）
        if form.system_folder == INDUSTRY_RULES_CODE:
            scope_ok, scope_err = ensure_folder_in_scope_or_error(
                form.id, INDUSTRY_RULES_CODE, include_root=True
            )
            if not scope_ok:
                return json_response(error=scope_err)

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
            'folder_path': _get_folder_path(folder),
            'sub_folder_count': sub_folder_count,
            'file_count': total_files,
            'total_size': total_size,
            'created_at': folder.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': folder.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            'created_by': folder.created_by.nickname if folder.created_by else None,
        })

    def _get_file_properties(self, request, FileModel, FolderModel, form):
        """文件属性统计"""
        query = FileModel.objects.filter(id=form.id, is_deleted=False)
        if not form.is_public:
            query = apply_tenant_filter(query, request.user, strict_mode=True)

        try:
            file_obj = query.select_related('created_by', 'folder').first()
        except Exception:
            file_obj = None

        if file_obj is None:
            return json_response(error='文件不存在或无权访问')

        # 行业规章范围校验（文件）
        if form.system_folder == INDUSTRY_RULES_CODE:
            scope_ok, scope_err = ensure_file_in_scope_or_error(file_obj, INDUSTRY_RULES_CODE)
            if not scope_ok:
                return json_response(error=scope_err)

        # 权限检查：公共空间普通用户只能查看自己创建的
        if form.is_public and not request.user.is_supper:
            if file_obj.created_by_id != request.user.id:
                return permission_denied_response('无权查看该文件属性')

        # 计算所在位置
        if file_obj.folder_id is None:
            folder_path = '根目录'
        else:
            folder_path = file_obj.folder.get_full_path()

        return json_response({
            'id': file_obj.id,
            'name': file_obj.name,
            'display_name': file_obj.display_name if hasattr(file_obj, 'display_name') else None,
            'file_type': file_obj.file_type,
            'size': file_obj.file_size,
            'folder_id': file_obj.folder_id,
            'folder_path': folder_path,
            'created_at': file_obj.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': file_obj.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            'created_by': file_obj.created_by.nickname if file_obj.created_by else None,
        })

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件夹搜索模块
提供递归搜索文件夹和文件的功能

【M4 2026-06-08 决定】FULLTEXT 在当前 MariaDB 10.8 + 默认分词器环境下不可用
- MariaDB 默认分词器对带 _/数字 的混合字符串不切分（视为整 token）
- ngram plugin 需要 SUPER 权限才能 INSTALL，spug 用户无权限
- 折中方案：保留 FULLTEXT helper 函数（_should_use_fulltext / _apply_fulltext_filter）
  作为"未来 ngram 装好后的接口"，但 get() 强制走 LIKE（_apply_fallback_filter）
- 详细分析见 _M4_INFEASIBLE_REPORT.md
- 当前实际行为 = 修复前的 LIKE 行为
"""

import logging
from django.views.generic import View
from django.conf import settings
from django.db.models import Q
from django.db.models.expressions import RawSQL
from django.db import connection

from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter
from ..libs.document_utils import get_folder_model, get_file_model
from ..libs.view_utils import format_file_size
from ..constants import DEFAULT_MAX_FOLDER_DEPTH

logger = logging.getLogger(__name__)


# 【M4 新增】MySQL FULLTEXT 全文索引最小词长（InnoDB 默认 3）
# 关键词长度 < 此值时 FULLTEXT 不命中，需 fallback 到 LIKE
FT_MIN_TOKEN_SIZE = 3


def _get_max_recursion_depth():
    """延迟获取最大递归深度，避免模块导入时访问 settings"""
    from django.conf import settings
    return getattr(settings, 'MAX_FOLDER_RECURSION_DEPTH', DEFAULT_MAX_FOLDER_DEPTH)


def _should_use_fulltext(keyword):
    """
    【M4 新增】判断关键词是否走 FULLTEXT 索引

    决策依据：
    1. 关键词 < FT_MIN_TOKEN_SIZE(3)：FULLTEXT 不索引（InnoDB ft_min_token_size=3）→ fallback LIKE
    2. 关键词含 FULLTEXT 保留字符（+ -><()~*"@:）：BOOLEAN MODE 解析复杂 → fallback LIKE 更稳
    3. 关键词是纯 stopword（如 "the"）：FULLTEXT 默认 stopword 不索引 → fallback LIKE
    4. 其他情况：走 FULLTEXT MATCH AGAINST

    Returns:
        bool: True 走 FULLTEXT，False 走 LIKE
    """
    if not keyword:
        return False
    if len(keyword) < FT_MIN_TOKEN_SIZE:
        return False
    # FULLTEXT 保留字符：+ -><()~*"@:
    ft_reserved = set('+-><()~*"@:')
    if any(c in ft_reserved for c in keyword):
        return False
    return True


def _apply_fulltext_filter(queryset, keyword, fields):
    """
    【M4 新增】对 queryset 追加 FULLTEXT MATCH AGAINST 过滤

    使用 Django RawSQL annotation 替代 extra()，
    MATCH AGAINST 返回相关性分数（>0 表示命中），比 extra(where=[...]) 更安全、更易维护。

    Args:
        queryset: 已构造的 QuerySet
        keyword: 搜索关键词
        fields: 字段名列表（多字段走复合索引）

    Returns:
        QuerySet: 追加了 FULLTEXT 过滤条件的 queryset
    """
    # BOOLEAN MODE: keyword* 前缀匹配，更符合用户预期
    # 例：搜 "doc" → "document" "docx" "docs" 都能命中
    boolean_keyword = f'+{keyword}*'
    match_expr = 'MATCH({}) AGAINST (%s IN BOOLEAN MODE)'.format(', '.join(fields))
    # RawSQL 作为 annotation，MATCH AGAINST 返回相关性分数（float），
    # > 0 即表示命中，等价于 extra(where=[match_expr], params=[boolean_keyword])
    return queryset.annotate(
        _fulltext_rank=RawSQL(match_expr, [boolean_keyword])
    ).filter(_fulltext_rank__gt=0)


def _apply_fallback_filter(queryset, keyword, fields):
    """
    【M4 新增】对 queryset 追加 LIKE 过滤（FULLTEXT 不可用时的 fallback）

    支持多字段 OR 查询：
    - 单字段：name__icontains
    - 多字段：Q(name__icontains) | Q(display_name__icontains)

    Args:
        queryset: 已构造的 QuerySet
        keyword: 搜索关键词
        fields: 字段名列表

    Returns:
        QuerySet: 追加了 LIKE 条件的 queryset
    """
    if len(fields) == 1:
        return queryset.filter(**{f'{fields[0]}__icontains': keyword})
    q = Q()
    for f in fields:
        q |= Q(**{f'{f}__icontains': keyword})
    return queryset.filter(q)


class FolderSearchView(View):
    """递归搜索文件夹和文件（性能优化版）"""
    
    # 搜索限制配置
    MAX_SEARCH_RESULTS = 200  # 最大搜索结果数量
    MAX_FOLDER_IDS = 1000     # 最大搜索文件夹范围

    @auth('document.document.view')
    def get(self, request):
        """
        递归搜索文件夹和文件（支持分页优化）
        
        优化点：
        1. 限制搜索结果数量，防止内存溢出
        2. 限制搜索范围（文件夹数量）
        3. 数据库层面分页
        """
        logger.info(f'[Document] FolderSearchView.get called, user: {request.user.username}')
        form, error = JsonParser(
            Argument('folder_id', type=int, required=False, default=None),
            Argument('keyword', type=str, required=False),
            Argument('is_public', type=bool, required=False, default=False),
            Argument('page', type=int, required=False, default=1),           # 【优化】分页参数
            Argument('page_size', type=int, required=False, default=50),     # 【优化】分页大小
        ).parse(request.GET)

        if error is not None:
            logger.error(f'[Document] Parse error: {error}')
            return json_response(error=error)
        
        if not form.keyword or form.keyword.strip() == '':
            return json_response({'folders': [], 'files': []})

        keyword = form.keyword.strip().lower()
        
        # 分页参数处理
        page = max(1, form.page)
        page_size = min(form.page_size, 100)  # 最大100条
        offset = (page - 1) * page_size

        # 根据 is_public 参数获取对应的模型
        FolderModel = get_folder_model(is_public=form.is_public)
        FileModel = get_file_model(is_public=form.is_public)

        # 获取所有需要搜索的文件夹ID（递归获取子树）
        folder_ids_to_search = self._get_descendant_folder_ids(
            form.folder_id, FolderModel, request.user, form.is_public
        )
        
        # 【优化】限制搜索范围
        if len(folder_ids_to_search) > self.MAX_FOLDER_IDS:
            logger.warning(f'[Document] 搜索范围过大，已限制: {len(folder_ids_to_search)} > {self.MAX_FOLDER_IDS}')
            folder_ids_to_search = list(folder_ids_to_search)[:self.MAX_FOLDER_IDS]

        # 搜索匹配的文件夹（限制数量）
        # 【2026-06-08 决定】FULLTEXT 在 MariaDB 10.8 + 默认分词器 + 业务字段带 _/数字 环境下
        # 不能正确切词（不按 _ 切分），且 ngram plugin 无 SUPER 权限装不上
        # 暂时只用 LIKE（fallback），保留 FULLTEXT helper 函数作为"未来 ngram 装好后的接口"
        # 详细分析见 _M4_INFEASIBLE_REPORT.md
        folders_query = FolderModel.objects.filter(
            id__in=folder_ids_to_search,
        ).select_related('created_by').order_by('-created_at')
        folders_query = _apply_fallback_filter(folders_query, keyword, ['name'])

        # 私有空间：添加租户过滤（严格模式）
        if not form.is_public:
            folders_query = apply_tenant_filter(folders_query, request.user, strict_mode=True)

        # 【优化】限制总数并分页
        total_folders = min(folders_query.count(), self.MAX_SEARCH_RESULTS)
        folders = folders_query[offset:offset + page_size]

        # 搜索匹配的文件（限制数量）
        # 【修复】支持搜索文件夹内和根目录的文件（folder_id=None）
        # 【M4 优化 2026-06-08】name + display_name 任一命中即可
        files_query = FileModel.objects.filter(
            (Q(folder_id__in=folder_ids_to_search) | Q(folder_id=None)),
        ).select_related('created_by').order_by('-created_at')
        files_query = _apply_fallback_filter(files_query, keyword, ['name', 'display_name'])

        # 私有空间：添加租户过滤（严格模式）—— 与 folders_query 保持一致
        # 注意：folder_id=None 的根目录文件也必须做租户隔离，防止跨租户泄露
        if not form.is_public:
            files_query = apply_tenant_filter(files_query, request.user, strict_mode=True)

        # 【优化】限制总数并分页
        total_files = min(files_query.count(), self.MAX_SEARCH_RESULTS)
        files = files_query[offset:offset + page_size]

        # 构建文件夹ID到路径的映射（仅对搜索结果中的文件夹）
        result_folder_ids = {f.id for f in folders} | {f.folder_id for f in files}
        folder_id_to_path = self._build_folder_path_map(result_folder_ids, FolderModel, request.user, form.is_public)

        # 格式化返回结果
        result = {
            'folders': [
                {
                    'id': f.id,
                    'name': f.name,
                    'parent_id': f.parent_id,
                    'path': folder_id_to_path.get(f.id, ''),
                    'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'created_by': f.created_by.nickname if f.created_by else None,
                    'created_by_id': f.created_by_id
                } for f in folders
            ],
            'files': [],
            'pagination': {  # 【优化】添加分页信息
                'page': page,
                'page_size': page_size,
                'total_folders': total_folders,
                'total_files': total_files,
                'has_more': (offset + page_size) < max(total_folders, total_files),
                'limited': folders_query.count() > self.MAX_SEARCH_RESULTS or files_query.count() > self.MAX_SEARCH_RESULTS
            }
        }

        # 格式化文件数据
        for f in files:
            file_size = f.file_size
            # 【2026-06-06 M1 修复】调用统一的 format_file_size 而非内联手写
            # 行为变化：旧实现卡死在 MB（1GB → "1024.00 MB"），新实现按 1024 逐级升级
            # （1GB → "1.00 GB"）。这是改进但需要前端展示侧能接受。
            size = format_file_size(file_size)

            result['files'].append({
                'id': f.id,
                'name': f.name,
                'display_name': f.display_name if hasattr(f, 'display_name') else None,
                'folder_id': f.folder_id,
                'size': size,
                'file_type': f.file_type,
                'path': folder_id_to_path.get(f.folder_id, ''),
                'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'created_by': f.created_by.nickname if f.created_by else None,
                'created_by_id': f.created_by_id
            })

        logger.info(f'[Document] 搜索结果: folders={len(folders)}, files={len(files)}, total_folders={total_folders}, total_files={total_files}')
        return json_response(result)

    def _get_descendant_folder_ids(self, start_folder_id, FolderModel, request_user, is_public):
        """
        获取起始文件夹及其所有后代文件夹的ID列表（广度优先搜索）
        """
        if start_folder_id is None:
            # 从根目录搜索，获取所有文件夹
            query = FolderModel.objects.all().order_by()
            if not is_public:
                query = apply_tenant_filter(query, request_user, strict_mode=True)
            return set(f.id for f in query)

        # 从指定文件夹开始搜索，获取该文件夹及其所有后代
        folder_ids = set([start_folder_id])
        visited_ids = set([start_folder_id])
        queue = [start_folder_id]
        depth = 0
        max_depth = _get_max_recursion_depth()

        while queue and depth < max_depth:
            current_batch_size = len(queue)
            depth += 1

            # 批量查询所有父文件夹的子文件夹（避免 N+1 查询）
            parent_ids = queue[:current_batch_size]
            queue = queue[current_batch_size:]  # 移除当前批次的父文件夹

            # 一次性查询所有子文件夹
            child_folders_query = FolderModel.objects.filter(parent_id__in=parent_ids).order_by()
            if not is_public:
                child_folders_query = apply_tenant_filter(child_folders_query, request_user, strict_mode=True)

            for child in child_folders_query:
                if child.id not in visited_ids:
                    visited_ids.add(child.id)
                    folder_ids.add(child.id)
                    queue.append(child.id)

            # 如果没有找到子文件夹，提前退出
            if not child_folders_query.exists():
                break

        if depth >= max_depth:
            logger.warning(f'[Document] 搜索递归深度超限: {max_depth}, folder_id={start_folder_id}')

        return folder_ids

    def _build_folder_path_map(self, folder_ids, FolderModel, request_user, is_public):
        """
        构建文件夹ID到完整路径的映射
        返回: {folder_id: '父文件夹/子文件夹'}
        """
        folder_id_to_path = {}

        # 查询所有相关文件夹
        folders_query = FolderModel.objects.filter(id__in=folder_ids).select_related('created_by').order_by()
        if not is_public:
            folders_query = apply_tenant_filter(folders_query, request_user, strict_mode=True)

        # 构建 parent_id -> [folders] 的映射
        parent_to_children = {}
        folder_map = {}
        for f in folders_query:
            folder_map[f.id] = f
            parent_id = f.parent_id if f.parent_id else 0
            if parent_id not in parent_to_children:
                parent_to_children[parent_id] = []
            parent_to_children[parent_id].append(f)

        # 为每个文件夹构建路径
        def build_path(folder_id, visited_ids=None):
            if visited_ids is None:
                visited_ids = set()

            if folder_id in folder_id_to_path:
                return folder_id_to_path[folder_id]

            if folder_id in visited_ids:
                logger.warning(f'[Document] 检测到循环引用, folder_id={folder_id}')
                return ''

            visited_ids.add(folder_id)

            folder = folder_map.get(folder_id)
            if not folder:
                return ''

            if folder.parent_id is None:
                folder_id_to_path[folder_id] = folder.name
                return folder.name

            # 递归构建父路径
            parent_path = build_path(folder.parent_id, visited_ids)
            if parent_path:
                folder_id_to_path[folder_id] = f'{parent_path}/{folder.name}'
            else:
                folder_id_to_path[folder_id] = folder.name

            return folder_id_to_path[folder_id]

        for folder_id in folder_ids:
            if folder_id not in folder_id_to_path:
                build_path(folder_id)

        return folder_id_to_path

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
回收站列表视图
获取回收站列表（支持分页优化和缓存）
支持显示文件夹和文件
"""

import logging
from datetime import timedelta
from django.views.generic import View
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.db.models import Q

from libs import json_response, JsonParser, Argument, auth
from ...models import (
    DocumentFilePrivate, DocumentFilePublic,
    DocumentFolderPrivate, DocumentFolderPublic
)
from ...libs.permission_utils import (
    get_folder_and_descendants_iter,
    get_folder_stats_optimized
)

logger = logging.getLogger(__name__)


class RecycleBinView(View):
    """回收站视图（性能优化版）"""
    
    CACHE_TTL = 60  # 缓存60秒
    
    @auth('document.document.view')
    def get(self, request):
        """获取回收站列表"""
        form, error = JsonParser(
            Argument('page', type=int, required=False, default=1),
            Argument('page_size', type=int, required=False, default=20),
            Argument('keyword', required=False),
            Argument('space', required=False, default='all', 
                     filter=lambda x: x in ['private', 'public', 'all'])
        ).parse(request.GET)
        
        if error:
            return json_response(error=error)
        
        page_size = min(form.page_size, 100)
        
        # 管理员不使用缓存
        if request.user.is_supper:
            cache_key = None
            cached_data = None
        else:
            version_key = f'recycle_bin_version:{request.user.id}'
            cache_version = cache.get(version_key, 1)
            cache_key = f'recycle_bin:{request.user.id}:{cache_version}:{form.space}:{form.keyword or ""}:{form.page}:{page_size}'
            cached_data = cache.get(cache_key)
            
        if cached_data:
            return json_response(data=cached_data)
        
        result = self._get_paginated_results(
            request.user, form.space, form.keyword, form.page, page_size
        )
        
        if cache_key:
            cache.set(cache_key, result, self.CACHE_TTL)
        
        return json_response(data=result)
    
    def _get_paginated_results(self, user, space, keyword, page, page_size):
        """分页查询（包含文件夹和文件）"""
        user_tenant_id = getattr(user, 'tenant_id', None)
        
        # 单空间查询
        if space in ['private', 'public']:
            return self._get_single_space_results(
                user, space, keyword, page, page_size, user_tenant_id
            )
        
        # 全部空间
        else:
            return self._get_all_spaces_results(
                user, keyword, page, page_size, user_tenant_id
            )
    
    def _get_single_space_results(self, user, space, keyword, page, page_size, user_tenant_id):
        """获取单空间结果（文件夹+文件）"""
        FileModel = DocumentFilePrivate if space == 'private' else DocumentFilePublic
        FolderModel = DocumentFolderPrivate if space == 'private' else DocumentFolderPublic
        
        # 查询文件夹（只显示顶层文件夹：parent为null或parent未被删除）
        folder_qs = FolderModel.all_objects.filter(
            is_deleted=True
        ).filter(
            Q(parent__isnull=True) | Q(parent__is_deleted=False)
        ).select_related('parent', 'created_by', 'deleted_by')
        
        # 【修改】私密空间完全隔离，超级管理员也不能查看其他租户数据
        # 【修复】公共空间：超级管理员查看所有，普通用户只能查看自己的
        if space == 'private':
            folder_qs = folder_qs.filter(tenant_id=user_tenant_id)
        elif not user.is_supper:
            folder_qs = folder_qs.filter(created_by=user)
        if keyword:
            folder_qs = folder_qs.filter(name__icontains=keyword)
        
        # 查询文件（独立文件，不在已删除文件夹中的）
        file_qs = FileModel.all_objects.filter(is_deleted=True).select_related('folder', 'created_by')
        # 【修改】私密空间完全隔离，超级管理员也不能查看其他租户数据
        # 【修复】公共空间：超级管理员查看所有，普通用户只能查看自己的
        if space == 'private':
            file_qs = file_qs.filter(tenant_id=user_tenant_id)
        elif not user.is_supper:
            file_qs = file_qs.filter(created_by=user)
        # 只显示独立文件（folder为null或folder未删除）
        file_qs = file_qs.filter(Q(folder__isnull=True) | Q(folder__is_deleted=False))
        if keyword:
            file_qs = file_qs.filter(Q(display_name__icontains=keyword) | Q(name__icontains=keyword))
        
        # 合并并排序
        folders = list(folder_qs)
        files = list(file_qs)
        
        # 标记类型
        for f in folders:
            f._item_type = 'folder'
            f._space = space
        for f in files:
            f._item_type = 'file'
            f._space = space
        
        all_items = folders + files
        all_items.sort(key=lambda x: x.deleted_at if x.deleted_at else timezone.now(), reverse=True)
        
        total_count = len(all_items)
        offset = (page - 1) * page_size
        paginated_items = all_items[offset:offset + page_size]
        
        results = []
        for item in paginated_items:
            if getattr(item, '_item_type', 'file') == 'folder':
                results.append(self._format_folder(item, space))
            else:
                results.append(self._format_file(item, space))
        
        return {
            'items': results,
            'total': total_count,
            'page': page,
            'page_size': page_size
        }
    
    def _get_all_spaces_results(self, user, keyword, page, page_size, user_tenant_id):
        """获取所有空间结果"""
        # 私有空间（只显示顶层文件夹：parent为null或parent未被删除）
        private_folder_qs = DocumentFolderPrivate.all_objects.filter(
            is_deleted=True
        ).filter(
            Q(parent__isnull=True) | Q(parent__is_deleted=False)
        ).select_related('parent', 'created_by', 'deleted_by')
        private_file_qs = DocumentFilePrivate.all_objects.filter(is_deleted=True).select_related('folder', 'created_by')
        
        # 公共空间（只显示顶层文件夹）
        public_folder_qs = DocumentFolderPublic.all_objects.filter(
            is_deleted=True
        ).filter(
            Q(parent__isnull=True) | Q(parent__is_deleted=False)
        ).select_related('parent', 'created_by', 'deleted_by')
        public_file_qs = DocumentFilePublic.all_objects.filter(is_deleted=True).select_related('folder', 'created_by')
        
        # 【修改】私密空间完全隔离，超级管理员也不能查看其他租户数据
        # 私有空间过滤
        private_folder_qs = private_folder_qs.filter(tenant_id=user_tenant_id)
        private_file_qs = private_file_qs.filter(tenant_id=user_tenant_id)
        # 【修复】公共空间：超级管理员查看所有，普通用户只能查看自己的
        if not user.is_supper:
            public_folder_qs = public_folder_qs.filter(created_by=user)
            public_file_qs = public_file_qs.filter(created_by=user)
        
        # 关键词过滤
        if keyword:
            private_folder_qs = private_folder_qs.filter(name__icontains=keyword)
            private_file_qs = private_file_qs.filter(Q(display_name__icontains=keyword) | Q(name__icontains=keyword))
            public_folder_qs = public_folder_qs.filter(name__icontains=keyword)
            public_file_qs = public_file_qs.filter(Q(display_name__icontains=keyword) | Q(name__icontains=keyword))
        
        # 文件只显示独立文件
        private_file_qs = private_file_qs.filter(Q(folder__isnull=True) | Q(folder__is_deleted=False))
        public_file_qs = public_file_qs.filter(Q(folder__isnull=True) | Q(folder__is_deleted=False))
        
        # 合并所有数据
        all_items = []
        
        for f in private_folder_qs:
            f._item_type = 'folder'
            f._space = 'private'
            all_items.append(f)
        
        for f in private_file_qs:
            f._item_type = 'file'
            f._space = 'private'
            all_items.append(f)
        
        for f in public_folder_qs:
            f._item_type = 'folder'
            f._space = 'public'
            all_items.append(f)
        
        for f in public_file_qs:
            f._item_type = 'file'
            f._space = 'public'
            all_items.append(f)
        
        # 排序
        all_items.sort(key=lambda x: x.deleted_at if x.deleted_at else timezone.now(), reverse=True)
        
        total_count = len(all_items)
        offset = (page - 1) * page_size
        paginated_items = all_items[offset:offset + page_size]
        
        results = []
        for item in paginated_items:
            space = getattr(item, '_space', 'private')
            if getattr(item, '_item_type', 'file') == 'folder':
                results.append(self._format_folder(item, space))
            else:
                results.append(self._format_file(item, space))
        
        return {
            'items': results,
            'total': total_count,
            'page': page,
            'page_size': page_size
        }
    
    def _format_folder(self, folder_obj, space):
        """格式化文件夹信息"""
        retention_days = getattr(settings, 'RECYCLE_BIN_RETENTION_DAYS', 30)
        days_left = retention_days - (timezone.now() - folder_obj.deleted_at).days
        
        # 统计文件夹内文件数量和大小
        file_count, total_size = self._get_folder_stats(folder_obj, space)
        
        return {
            'id': folder_obj.id,
            'type': 'folder',
            'name': folder_obj.name,
            'space': space,
            'deleted_at': folder_obj.deleted_at.isoformat() if folder_obj.deleted_at else None,
            'retention_days_left': max(0, days_left),
            'file_count': file_count,
            'total_size': total_size,
            'original_parent': {
                'id': folder_obj.parent.id,
                'name': folder_obj.parent.name
            } if folder_obj.parent else None,
            'deleted_by': {
                'id': folder_obj.deleted_by.id,
                'nickname': folder_obj.deleted_by.nickname
            } if folder_obj.deleted_by else None,
            'created_by': {
                'id': folder_obj.created_by.id,
                'nickname': folder_obj.created_by.nickname
            } if folder_obj.created_by else None
        }
    
    def _get_folder_stats(self, folder_obj, space):
        """【优化】获取文件夹统计信息（使用聚合查询避免N+1问题）"""
        # 【优化】使用 permission_utils 中的优化函数
        return get_folder_stats_optimized(folder_obj, space)
    
    def _format_file(self, file_obj, space):
        """格式化文件信息"""
        retention_days = getattr(settings, 'RECYCLE_BIN_RETENTION_DAYS', 30)
        days_left = retention_days - (timezone.now() - file_obj.deleted_at).days
        
        return {
            'id': file_obj.id,
            'type': 'file',
            'name': file_obj.name,
            'display_name': file_obj.display_name,
            'file_size': file_obj.file_size,
            'file_type': file_obj.file_type,
            'space': space,
            'deleted_at': file_obj.deleted_at.isoformat() if file_obj.deleted_at else None,
            'retention_days_left': max(0, days_left),
            'original_folder': {
                'id': file_obj.folder.id,
                'name': file_obj.folder.name
            } if file_obj.folder else None,
            'created_by': {
                'id': file_obj.created_by.id,
                'nickname': file_obj.created_by.nickname
            } if file_obj.created_by else None
        }

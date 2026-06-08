# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
回收站统计视图
获取回收站统计信息（支持文件夹和文件统计）
"""

import logging
from datetime import timedelta
from django.views.generic import View
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from libs import json_response, auth
from ...libs.permission_utils import get_folder_stats_optimized
from ...models import (
    DocumentFilePrivate, DocumentFilePublic,
    DocumentFolderPrivate, DocumentFolderPublic
)

logger = logging.getLogger(__name__)


class RecycleBinStatsView(View):
    """回收站统计视图（支持文件夹和文件统计）"""
    
    @auth('document.document.view')
    def get(self, request):
        """获取回收站统计信息"""
        retention_days = getattr(settings, 'RECYCLE_BIN_RETENTION_DAYS', 30)
        # 【修复】即将过期阈值：删除时间 <= (当前时间 - (保留期-7天)) 的文件即将过期
        # 例如30天保留期，已删除23天的文件还剩7天即将过期
        expiring_threshold = timezone.now() - timedelta(days=retention_days - 7)
        
        user_tenant_id = getattr(request.user, 'tenant_id', '')
        
        # ========== 文件统计 ==========
        # 私有文件统计
        private_file_queryset = DocumentFilePrivate.all_objects.filter(is_deleted=True)
        # 只统计独立文件（不在已删除文件夹中的）
        private_file_queryset = private_file_queryset.filter(
            folder__isnull=True
        ) | private_file_queryset.filter(
            folder__is_deleted=False
        )
        # 【修改】私密空间完全隔离，超级管理员也不能查看其他租户数据
        private_file_queryset = private_file_queryset.filter(tenant_id=user_tenant_id)
        
        private_file_total = private_file_queryset.count()
        private_file_size = private_file_queryset.aggregate(total=Sum('file_size'))['total'] or 0
        # 【修复】deleted_at__lte 表示删除时间早于阈值（已存放超过23天）
        private_file_expiring = private_file_queryset.filter(deleted_at__lte=expiring_threshold).count()
        
        # 公共文件统计
        public_file_total = 0
        public_file_size = 0
        public_file_expiring = 0
        
        if request.user.is_supper:
            public_file_queryset = DocumentFilePublic.all_objects.filter(is_deleted=True)
            public_file_queryset = public_file_queryset.filter(
                folder__isnull=True
            ) | public_file_queryset.filter(
                folder__is_deleted=False
            )
            public_file_total = public_file_queryset.count()
            public_file_size = public_file_queryset.aggregate(total=Sum('file_size'))['total'] or 0
            # 【修复】deleted_at__lte 表示删除时间早于阈值
            public_file_expiring = public_file_queryset.filter(deleted_at__lte=expiring_threshold).count()
        else:
            # 普通用户只能看到自己删除的公共文件
            public_file_queryset = DocumentFilePublic.all_objects.filter(
                is_deleted=True,
                created_by=request.user
            )
            public_file_queryset = public_file_queryset.filter(
                folder__isnull=True
            ) | public_file_queryset.filter(
                folder__is_deleted=False
            )
            public_file_total = public_file_queryset.count()
            public_file_size = public_file_queryset.aggregate(total=Sum('file_size'))['total'] or 0
            # 【修复】deleted_at__lte 表示删除时间早于阈值
            public_file_expiring = public_file_queryset.filter(deleted_at__lte=expiring_threshold).count()
        
        # ========== 【新增】文件夹统计 ==========
        private_folder_total, private_folder_file_count, private_folder_size = self._get_folder_stats(
            DocumentFolderPrivate, user_tenant_id, request.user
        )
        
        public_folder_total, public_folder_file_count, public_folder_size = self._get_public_folder_stats(
            DocumentFolderPublic, request.user
        )
        
        # 计算文件夹内文件的过期数量（简化处理：如果文件夹过期，则内部文件也算过期）
        # 【修改】私密空间完全隔离，超级管理员也不能查看其他租户数据
        private_folder_expiring = DocumentFolderPrivate.all_objects.filter(
            is_deleted=True,
            deleted_at__lte=expiring_threshold,
            tenant_id=user_tenant_id
        )
        private_folder_expiring_count = private_folder_expiring.count()
        
        if request.user.is_supper:
            public_folder_expiring_count = DocumentFolderPublic.all_objects.filter(
                is_deleted=True,
                deleted_at__lte=expiring_threshold
            ).count()
        else:
            public_folder_expiring_count = DocumentFolderPublic.all_objects.filter(
                is_deleted=True,
                deleted_at__lte=expiring_threshold,
                created_by=request.user
            ).count()
        
        return json_response(data={
            # 文件统计
            'file_count': private_file_total + public_file_total,
            'file_size': private_file_size + public_file_size,
            'private_file_count': private_file_total,
            'private_file_size': private_file_size,
            'public_file_count': public_file_total,
            'public_file_size': public_file_size,
            
            # 【新增】文件夹统计
            'folder_count': private_folder_total + public_folder_total,
            'folder_file_count': private_folder_file_count + public_folder_file_count,
            'folder_total_size': private_folder_size + public_folder_size,
            'private_folder_count': private_folder_total,
            'private_folder_file_count': private_folder_file_count,
            'private_folder_size': private_folder_size,
            'public_folder_count': public_folder_total,
            'public_folder_file_count': public_folder_file_count,
            'public_folder_size': public_folder_size,
            
            # 汇总统计
            'total_count': private_file_total + public_file_total + private_folder_total + public_folder_total,
            'total_size': private_file_size + public_file_size + private_folder_size + public_folder_size,
            
            # 即将过期统计（文件夹+文件）
            'expiring_soon': private_file_expiring + public_file_expiring + private_folder_expiring_count + public_folder_expiring_count,
            'file_expiring_soon': private_file_expiring + public_file_expiring,
            'folder_expiring_soon': private_folder_expiring_count + public_folder_expiring_count,
            
            'retention_days': retention_days
        })
    
    def _get_folder_stats(self, FolderModel, user_tenant_id, user):
        """【H1 修复 2026-06-07】获取文件夹统计信息（私有空间）
        使用 permission_utils.get_folder_stats_optimized 替代 N+1 循环
        """
        folder_queryset = FolderModel.all_objects.filter(is_deleted=True)

        # 【修改】私密空间完全隔离，超级管理员也不能查看其他租户数据
        folder_queryset = folder_queryset.filter(tenant_id=user_tenant_id)

        folder_count = folder_queryset.count()

        # 统计文件夹内的文件数量和大小（优化版：BFS + 聚合查询，替代原 N+1 循环）
        total_file_count = 0
        total_size = 0
        space = 'private' if FolderModel == DocumentFolderPrivate else 'public'

        for folder in folder_queryset:
            file_count, folder_size = get_folder_stats_optimized(folder, space)
            total_file_count += file_count
            total_size += folder_size

        return folder_count, total_file_count, total_size

    def _get_public_folder_stats(self, FolderModel, user):
        """【H1 修复 2026-06-07】获取文件夹统计信息（公共空间）
        使用 permission_utils.get_folder_stats_optimized 替代 N+1 循环
        """
        folder_queryset = FolderModel.all_objects.filter(is_deleted=True)

        if not user.is_supper:
            # 公共空间普通用户只能看到自己创建的文件夹
            folder_queryset = folder_queryset.filter(created_by=user)

        folder_count = folder_queryset.count()

        # 统计文件夹内的文件数量和大小（优化版：BFS + 聚合查询，替代原 N+1 循环）
        total_file_count = 0
        total_size = 0
        space = 'public'

        for folder in folder_queryset:
            file_count, folder_size = get_folder_stats_optimized(folder, space)
            total_file_count += file_count
            total_size += folder_size

        return folder_count, total_file_count, total_size

    # 【H1 修复 2026-06-07】删除以下未优化的方法：
    # - _calculate_folder_contents (N+1 循环)
    # - _get_folder_and_descendants (递归)
    # 改用 permission_utils.get_folder_stats_optimized (BFS + 聚合查询)

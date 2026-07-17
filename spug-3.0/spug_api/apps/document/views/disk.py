# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
磁盘使用监控模块
提供磁盘使用率的查询接口
"""

import os
import platform
import shutil
import logging

from django.views.generic import View
from django.conf import settings
from django.db.models import Sum

from libs import json_response, JsonParser, Argument
from libs.tenant_utils import apply_tenant_filter
from ..libs.document_utils import get_file_model
from ..libs.document_auth import document_auth

logger = logging.getLogger(__name__)


class DiskUsageView(View):
    """
    磁盘使用率查询接口
    返回上传目录的磁盘使用情况，区分公共/私有空间
    """
    @document_auth('view')
    def get(self, request):
        """获取磁盘使用率"""
        logger.info(f'[Document] DiskUsageView called, user: {request.user.username}')

        form, error = JsonParser(
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        # 根据 is_public 参数获取对应的模型
        FileModel = get_file_model(is_public=form.is_public)

        # 获取文档存储目录（根据 is_public 区分）
        if form.is_public:
            storage_dir = os.path.join(settings.BASE_DIR, 'storage', 'documents', 'public')
        else:
            storage_dir = os.path.join(settings.BASE_DIR, 'storage', 'documents', 'private', f'user-{request.user.id}')
        
        # 【关键修复】确保存储目录存在，否则 GetDiskFreeSpaceExW 会失败
        try:
            os.makedirs(storage_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f'[Document] 创建存储目录失败: {storage_dir}, 错误: {e}')

        # 【P0-2修复】计算当前空间的文件大小
        # 添加 is_deleted=False 过滤，只统计未删除文件
        try:
            query = FileModel.objects.filter(is_deleted=False)
            if not form.is_public:
                query = apply_tenant_filter(query, request.user)

            total_size = query.aggregate(total_size=Sum('file_size'))['total_size'] or 0
            used_gb = round(total_size / (1024**3), 2)
            logger.info(f'[Document] Disk usage calculated: {used_gb}GB, is_public={form.is_public}, query count={query.count()}')
        except Exception as e:
            logger.error(f'[Document] Error calculating file size: {e}')
            used_gb = 0

        # 获取磁盘使用率（跨平台兼容）
        try:
            if platform.system() == 'Windows':
                # Windows 系统使用 ctypes 调用 GetDiskFreeSpaceExW
                import ctypes
                free_bytes = ctypes.c_ulonglong(0)
                total_bytes = ctypes.c_ulonglong(0)
                available_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    ctypes.c_wchar_p(storage_dir),
                    ctypes.byref(free_bytes),
                    ctypes.byref(total_bytes),
                    ctypes.byref(available_bytes)
                )
                total_disk_bytes = total_bytes.value
                total_disk_gb = round(total_disk_bytes / (1024**3), 2)
                available_gb = round(available_bytes.value / (1024**3), 2)
            else:
                # Linux/Unix 系统使用 shutil.disk_usage
                disk_usage = shutil.disk_usage(storage_dir)
                total_disk_bytes = disk_usage.total
                total_disk_gb = round(total_disk_bytes / (1024**3), 2)
                available_gb = round(disk_usage.free / (1024**3), 2)

            logger.info(f'[Document] Disk usage: {used_gb}GB used, {total_disk_gb}GB total, is_public={form.is_public}')
            return json_response({
                'usage_percent': 0,  # 文件大小占磁盘百分比
                'used_gb': used_gb,  # 当前空间已使用大小
                'total_gb': total_disk_gb,  # 磁盘总大小
                'available_gb': available_gb,  # 磁盘可用大小
                'storage_dir': storage_dir,
                'is_public': form.is_public
            })
        except Exception as e:
            logger.error(f'[Document] Error getting disk usage: {e}')
            # 返回默认值，避免阻塞上传
            return json_response({
                'usage_percent': 0,
                'used_gb': used_gb,
                'total_gb': 0,
                'available_gb': 0,
                'storage_dir': storage_dir,
                'is_public': form.is_public,
                'error': str(e)
            })

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
上传压力监控接口

前端上传模块根据本接口返回的服务器压力等级，动态调整上传并发：
  - normal   : 文件并发 3，分片并发 3
  - busy     : 文件并发 2，分片并发 2
  - critical : 文件并发 1，分片并发 1

压力来源（服务器全局，不按租户隔离，因为压力是物理机共享的）：
  1. 磁盘使用率（storage/documents 所在分区）
  2. 合并队列深度（TransferRecord.status='MERGING' 的数量）
  3. Celery Worker 存活情况

设计原则：
  - 接口必须轻量快速（不调用慢的 inspector.active 等），避免压力接口自身成为压力源
  - 任何子项异常都降级为默认值，绝不阻塞前端上传
"""
import os
import platform
import logging

from django.views.generic import View
from django.conf import settings

from libs import json_response, auth
from ..monitoring import check_celery_health
from ..models import DocumentTransfer

logger = logging.getLogger(__name__)


# ============================================================
# 压力等级判定阈值
# ============================================================
# 磁盘使用率阈值（百分比）
DISK_BUSY_THRESHOLD = 75
DISK_CRITICAL_THRESHOLD = 90

# 合并队列深度阈值（status='MERGING' 的传输记录数）
MERGE_BUSY_THRESHOLD = 4
MERGE_CRITICAL_THRESHOLD = 8

# 各等级对应的建议并发配置
LEVEL_CONFIG = {
    'normal': {'max_concurrent_uploads': 3, 'max_concurrent_chunks': 3},
    'busy': {'max_concurrent_uploads': 2, 'max_concurrent_chunks': 2},
    'critical': {'max_concurrent_uploads': 1, 'max_concurrent_chunks': 1},
}

# 各等级的用户提示文案
LEVEL_MESSAGES = {
    'normal': '',
    'busy': '服务器繁忙，已降低上传并发',
    'critical': '服务器压力较高，已进入低速上传模式',
}


class UploadPressureView(View):
    """
    上传压力状态查询接口
    GET /api/document/upload_pressure/

    返回：
      {
        "level": "normal | busy | critical",
        "max_concurrent_uploads": 3,
        "max_concurrent_chunks": 3,
        "disk_usage_percent": 62,
        "merge_queue_depth": 0,
        "celery_workers": 4,
        "message": ""
      }
    """

    @auth('document.document.view')
    def get(self, request):
        # 1. 磁盘使用率
        disk_usage_percent = self._get_disk_usage_percent()

        # 2. 合并队列深度（全局，不按租户；压力是物理机共享的）
        merge_queue_depth = self._get_merge_queue_depth()

        # 3. Celery Worker 数（兼带存活判断）
        celery_workers = self._get_celery_workers()

        # 4. 综合判定压力等级
        level = self._determine_level(disk_usage_percent, merge_queue_depth, celery_workers)
        config = LEVEL_CONFIG[level]

        return json_response({
            'level': level,
            'max_concurrent_uploads': config['max_concurrent_uploads'],
            'max_concurrent_chunks': config['max_concurrent_chunks'],
            'disk_usage_percent': disk_usage_percent,
            'merge_queue_depth': merge_queue_depth,
            'celery_workers': celery_workers,
            'message': LEVEL_MESSAGES[level],
        })

    # --------------------------------------------------------
    # 子项采集（每项独立 try，异常降级为默认值，不阻断整体）
    # --------------------------------------------------------

    def _get_disk_usage_percent(self):
        """获取 storage/documents 所在分区的磁盘使用率百分比"""
        try:
            storage_dir = os.path.join(settings.BASE_DIR, 'storage', 'documents')
            # 确保目录存在（部分环境可能尚未创建）
            if not os.path.exists(storage_dir):
                storage_dir = settings.BASE_DIR

            if platform.system() == 'Windows':
                import ctypes
                free_bytes = ctypes.c_ulonglong(0)
                total_bytes = ctypes.c_ulonglong(0)
                available_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    ctypes.c_wchar_p(storage_dir),
                    ctypes.byref(free_bytes),
                    ctypes.byref(total_bytes),
                    ctypes.byref(available_bytes),
                )
                total = total_bytes.value
                free = available_bytes.value
            else:
                import shutil
                du = shutil.disk_usage(storage_dir)
                total = du.total
                free = du.free

            if total <= 0:
                return 0
            used = total - free
            return round((used / total) * 100, 1)
        except Exception as e:
            logger.warning(f'[UploadPressure] 获取磁盘使用率失败: {e}')
            return 0

    def _get_merge_queue_depth(self):
        """获取全局合并队列深度（status='MERGING' 的传输记录数）"""
        try:
            return DocumentTransfer.objects.filter(status='MERGING').count()
        except Exception as e:
            logger.warning(f'[UploadPressure] 获取合并队列深度失败: {e}')
            return 0

    def _get_celery_workers(self):
        """获取存活的 Celery Worker 数量（None 表示不可达）"""
        try:
            result = check_celery_health()
            if result.get('status') == 'ok':
                return result.get('workers', 0)
            # Celery 不可达视为严重压力（合并无法进行）
            return 0
        except Exception as e:
            logger.warning(f'[UploadPressure] 获取 Celery 状态失败: {e}')
            return 0

    # --------------------------------------------------------
    # 等级判定
    # --------------------------------------------------------

    def _determine_level(self, disk_percent, merge_depth, celery_workers):
        """
        综合判定压力等级，取各子项中最严重的等级。

        判定规则（任一命中即升级）：
          - critical: 磁盘>=90% 或 合并队列>=8 或 Celery Worker=0
          - busy    : 磁盘>=75% 或 合并队列>=4
          - normal  : 其余
        """
        # Celery 不可达直接 critical（合并任务无法执行）
        if celery_workers == 0:
            return 'critical'

        levels = []
        # 磁盘
        if disk_percent >= DISK_CRITICAL_THRESHOLD:
            levels.append('critical')
        elif disk_percent >= DISK_BUSY_THRESHOLD:
            levels.append('busy')
        else:
            levels.append('normal')

        # 合并队列
        if merge_depth >= MERGE_CRITICAL_THRESHOLD:
            levels.append('critical')
        elif merge_depth >= MERGE_BUSY_THRESHOLD:
            levels.append('busy')
        else:
            levels.append('normal')

        # 取最严重
        if 'critical' in levels:
            return 'critical'
        if 'busy' in levels:
            return 'busy'
        return 'normal'

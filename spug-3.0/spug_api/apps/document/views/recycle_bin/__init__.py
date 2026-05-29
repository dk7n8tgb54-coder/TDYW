# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
回收站功能模块
提供回收站列表查询、文件/文件夹恢复、彻底删除等功能

【目录优化完成】
拆分后文件：
- utils.py: 工具函数（脱敏、限流、权限检查）
- list.py: RecycleBinView
- restore.py: RecycleBinRestoreView
- delete.py: RecycleBinPermanentDeleteView, RecycleBinTaskStatusView
- stats.py: RecycleBinStatsView
- folder_restore.py: RecycleBinFolderRestoreView
- folder_delete.py: RecycleBinFolderPermanentDeleteView
- folder_content.py: RecycleBinFolderContentView
"""

from .list import RecycleBinView
from .restore import RecycleBinRestoreView
from .delete import RecycleBinPermanentDeleteView, RecycleBinTaskStatusView
from .stats import RecycleBinStatsView
from .folder_restore import RecycleBinFolderRestoreView
from .folder_delete import RecycleBinFolderPermanentDeleteView
from .folder_content import RecycleBinFolderContentView

__all__ = [
    'RecycleBinView',
    'RecycleBinRestoreView',
    'RecycleBinPermanentDeleteView',
    'RecycleBinTaskStatusView',
    'RecycleBinStatsView',
    'RecycleBinFolderRestoreView',
    'RecycleBinFolderPermanentDeleteView',
    'RecycleBinFolderContentView',
]

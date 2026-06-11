# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件管理模块
提供文件的删除、上传、下载、预览、复制、移动、重命名等功能
"""

from .views import FileView
from .upload import FileUploadView
from .download import FileDownloadView
from .preview import FilePreviewView, FileTextContentView, OfficePreviewUrlView, PreviewTokenView
from .copy import FileCopyView
from .move import FileMoveView
from .rename import FileRenameView

__all__ = [
    'FileView',
    'FileUploadView',
    'FileDownloadView',
    'FilePreviewView',
    'FileTextContentView',
    'OfficePreviewUrlView',
    'PreviewTokenView',
    'FileCopyView',
    'FileMoveView',
    'FileRenameView',
]

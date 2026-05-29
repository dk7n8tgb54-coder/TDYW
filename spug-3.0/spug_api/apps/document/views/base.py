# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
基础工具函数模块（精简版）

【迁移说明】
原 base.py 中的工具函数已迁移至：
- libs/view_utils.py: 通用视图工具函数
- libs/mime_utils.py: MIME 类型工具

保留此文件以兼容现有导入，但新代码应直接从 libs 导入
"""

# 从新的位置导入，保持向后兼容
from ..libs.view_utils import (
    format_file_size,
    check_public_space_permission,
    log_operation,
    is_safe_path,
    create_model_instance,
    validate_file_name,
    validate_file_upload,
    handle_view_errors,
)
from ..libs.mime_utils import MIME_TYPES, get_mime_type

__all__ = [
    'format_file_size',
    'check_public_space_permission',
    'MIME_TYPES',
    'get_mime_type',
    'handle_view_errors',
    'log_operation',
    'is_safe_path',
    'create_model_instance',
    'validate_file_name',
    'validate_file_upload',
]

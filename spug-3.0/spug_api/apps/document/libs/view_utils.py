# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
视图层工具函数
从 views/base.py 迁移而来
提供文件大小格式化、权限检查、审计日志、文件名验证等
"""

import os
import re
import logging
from functools import wraps

# 从 document_utils 重新导出 is_safe_path，保持 views/base.py 的导入兼容
from ..libs.document_utils import is_safe_path

logger = logging.getLogger(__name__)


def format_file_size(size_bytes):
    """格式化文件大小为可读格式"""
    if size_bytes is None:
        return '未知大小'
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f'{size_bytes:.2f} {unit}'
        size_bytes /= 1024
    return f'{size_bytes:.2f} PB'


def permission_denied_response(message='无权限操作该资源', reason='permission_denied'):
    """
    统一权限错误响应格式

    所有权限相关错误统一返回 {error, code, reason} 三字段结构，
    前端可依赖 code/reason 做标准化处理，不再解析散落文本。

    Args:
        message: 用户可见的错误描述
        reason: 机器可读的错误原因码，用于前端分类处理

    Returns:
        HttpResponse: 统一格式的权限错误响应

    响应格式:
        {
            "data": "",
            "error": "无权限操作该资源",
            "code": 403,
            "reason": "permission_denied"
        }
    """
    from libs import json_response
    response = json_response(error=message, code=403)
    # json_response 不支持 reason 参数，手动注入到响应内容中
    import json
    content = json.loads(response.content)
    content['reason'] = reason
    response.content = json.dumps(content, ensure_ascii=False).encode('utf-8')
    return response


def check_public_space_permission(request_user, resource_obj, resource_type='file', operation='操作'):
    """
    检查公共空间权限（仅管理员或创建人可操作）
    """
    # 超级管理员可以操作所有资源
    if getattr(request_user, 'is_supper', False):
        return True

    # 检查是否为创建人
    if getattr(resource_obj, 'created_by_id', None) != request_user.id:
        logger.warning(
            f'[Document] User {request_user.username} attempting to {operation}他人的公共'
            f'{resource_type} id:{resource_obj.id}'
        )
        return False

    return True


AUDIT_ACTION_MAP = {
    'FILE_UPLOAD': 'create',     'FILE_COPY': 'create',
    'FILE_DELETE': 'delete',
    'FILE_RENAME': 'update',     'FILE_MOVE': 'update',
    'FILE_DOWNLOAD': 'export',
    'FOLDER_DELETE': 'delete',
    'FOLDER_RENAME': 'update',   'FOLDER_MOVE': 'update',
    'FOLDER_DOWNLOAD': 'export', 'FOLDER_COPY': 'create',
}


def log_operation(action, user, resource_type, resource_id, **kwargs):
    """记录文档操作审计日志（写入数据库 audit_logs 表）

    当传入 request 时使用 record_audit_event，自动设置 _audit_handled 标记，
    中间件检测到该标记后跳过，避免重复记录。
    """
    try:
        from apps.logs.audit import record_audit_event, save_audit_log
        request = kwargs.pop('request', None)
        target_name = kwargs.get('file_name') or kwargs.get('folder_name') or ''
        mapped_action = AUDIT_ACTION_MAP.get(action, 'other')

        if request is not None:
            record_audit_event(
                request, mapped_action,
                target_type='document',
                target_id=str(resource_id) if resource_id else '',
                target_name=target_name,
            )
        else:
            save_audit_log(
                user_id=getattr(user, 'id', 0),
                username=getattr(user, 'username', ''),
                action=mapped_action,
                target_type='document',
                target_id=str(resource_id) if resource_id else '',
                target_name=target_name,
                tenant_id=getattr(user, 'tenant_id', 'default'),
            )
    except Exception:
        logger.warning('log_operation failed: action=%s resource_id=%s', action, resource_id, exc_info=True)


def create_model_instance(Model, **kwargs):
    """
    创建模型实例的辅助函数，自动处理 tenant_id 字段
    """
    if hasattr(Model, 'tenant_id') and 'tenant_id' not in kwargs:
        user = kwargs.get('created_by')
        if user and hasattr(user, 'tenant_id'):
            kwargs['tenant_id'] = user.tenant_id or ''
    return Model.objects.create(**kwargs)


def validate_file_name(file_name):
    """校验文件名，防止路径遍历和非法字符"""
    if '..' in file_name:
        return False
    forbidden_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for char in forbidden_chars:
        if char in file_name:
            return False
    if len(file_name) == 0 or len(file_name) > 255:
        return False
    return True


def validate_file_upload(file_name, file_size, max_file_size=None):
    """增强的文件上传验证"""
    if not validate_file_name(file_name):
        return False, "文件名包含非法字符"

    if not isinstance(file_size, (int, float)) or file_size <= 0:
        return False, "文件大小必须为正数"

    if max_file_size and file_size > max_file_size:
        if max_file_size >= 1024 * 1024 * 1024:
            max_gb = max_file_size / (1024 * 1024 * 1024)
            return False, f"文件大小超过限制（最大{max_gb:.0f}GB）"
        else:
            max_mb = max_file_size / (1024 * 1024)
            return False, f"文件大小超过限制（最大{max_mb:.0f}MB）"

    return True, "验证通过"


def handle_view_errors(func):
    """【E-1修复】统一处理视图错误的装饰器

    - ImportError/AttributeError 等启动错误重新抛出，不被吞掉
    - DEBUG 模式下返回详细错误信息
    """
    @wraps(func)
    def wrapper(self, request, *args, **kwargs):
        try:
            return func(self, request, *args, **kwargs)
        except Exception as e:
            import traceback
            from django.conf import settings

            # 【E-1修复】启动错误（ImportError 等）不应被吞掉，重新抛出
            if isinstance(e, (ImportError, AttributeError, ModuleNotFoundError)):
                logger.error(f'[Document] 启动错误（不上报给用户）: {str(e)}')
                logger.error(f'[Document] 异常堆栈:\n{traceback.format_exc()}')
                raise

            logger.error(f'[Document] 未处理的异常: {str(e)}')
            logger.error(f'[Document] 异常堆栈:\n{traceback.format_exc()}')

            # 【E-1修复】DEBUG 模式下返回详细错误
            from libs import json_response
            if getattr(settings, 'DEBUG', False):
                return json_response(error=f'服务器内部错误: {str(e)}', detail=traceback.format_exc())
            return json_response(error='服务器内部错误')
    return wrapper

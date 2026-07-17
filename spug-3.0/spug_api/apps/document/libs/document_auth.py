# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""文档模块上下文权限装饰器

用法：
    @document_auth('view')          # 读类操作
    @document_auth('upload')         # 上传
    @document_auth('download')       # 下载
    @document_auth('delete')         # 删除
    @document_auth('create_folder') # 新建目录
    @document_auth('copy')           # 复制
    @document_auth('move')           # 移动
    @document_auth('rename')         # 重命名

权限规则：
- 请求带 system_folder=party_building_documents 时，要求 document.party_building_document.<op>
- 普通模式（无 system_folder）时，要求 document.document.<op>

这样党建文档用户无需授予 document.document.* 基础权限即可访问资料库接口，
同时普通资料管理用户的行为不受影响（仍走 document.document.*）。
"""
import json
import logging
from functools import wraps

from libs import json_response
from ..services.system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE,
    is_valid_system_folder_code,
    normalize_system_folder_code,
)

logger = logging.getLogger(__name__)


def _extract_system_folder(request):
    """从请求中提取 system_folder 参数（GET / form-data / JSON body）

    对 JSON body 做解析缓存，避免视图重复解析 request.body。
    """
    # 1) query string（GET / DELETE）
    sf = request.GET.get('system_folder')
    if sf:
        return sf

    content_type = (request.content_type or '').lower()

    # 2) multipart form-data
    if 'multipart' in content_type or 'form-urlencoded' in content_type:
        return request.POST.get('system_folder')

    # 3) JSON body
    if request.body:
        cached = getattr(request, '_document_cached_json_body', None)
        if cached is None and not getattr(request, '_document_cached_json_attempted', False):
            try:
                cached = json.loads(request.body)
            except Exception:
                cached = {}
            request._document_cached_json_body = cached
            request._document_cached_json_attempted = True
        if isinstance(cached, dict):
            return cached.get('system_folder')

    return None


def get_request_system_folder(request):
    """供视图层使用的公共方法：取当前请求的 system_folder（规范化后）"""
    sf = _extract_system_folder(request)
    if sf and is_valid_system_folder_code(sf):
        return normalize_system_folder_code(sf)
    return None


def document_auth(operation):
    """上下文权限装饰器

    Args:
        operation: 操作 key（view/upload/download/delete/create_folder/copy/move/rename）
    """
    def decorate(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            user = None
            request = None
            for item in args[:2]:
                if hasattr(item, 'user'):
                    request = item
                    user = item.user
                    break
            if user is None:
                return json_response(error='权限拒绝')

            system_folder = _extract_system_folder(request) if request else None
            if system_folder and is_valid_system_folder_code(system_folder):
                system_folder = normalize_system_folder_code(system_folder)
            if system_folder == PARTY_BUILDING_DOCUMENTS_CODE:
                required = f'document.party_building_document.{operation}'
            else:
                required = f'document.document.{operation}'

            if user.has_perms([required]):
                return view_func(*args, **kwargs)

            logger.info(
                f'[AUTH] 权限拒绝: user={user.username}, required={required}, '
                f'system_folder={system_folder}'
            )
            return json_response(error='权限拒绝')

        return wrapper
    return decorate

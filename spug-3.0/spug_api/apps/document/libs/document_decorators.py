# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文档管理权限校验装饰器
提供文件夹/文件操作权限校验
"""
from functools import wraps
from libs import json_response
from apps.document.libs.document_utils import (
    get_folder_model, get_file_model, is_global_admin
)
from apps.document.models import DocumentFolderPublic, DocumentFilePublic
from apps.document.libs.view_utils import permission_denied_response
import logging

logger = logging.getLogger(__name__)


def document_permission_check(need_create_permission=True):
    """
    文档操作权限校验装饰器

    功能：
    1. 校验用户是否为管理员（管理员可操作所有公共资源）
    2. 公共空间：普通用户只能操作自己创建的资源
    （私有空间已移除）

    Args:
        need_create_permission: 是否需要创建权限（删除/重命名需要，查看/下载不需要）

    使用示例：
        @document_permission_check()
        def delete_folder(request):
            pass

        @document_permission_check(need_create_permission=False)
        def download_file(request):
            pass
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            try:
                # 获取请求参数（私有空间已移除，is_public 始终按 True 处理）
                is_public = True

                # 管理员直接放行
                if is_global_admin(request.user):
                    logger.debug(f'[PERMISSION] 管理员 {request.user.username} 通过权限校验')
                    return view_func(request, *args, **kwargs)

                # 公共空间权限校验
                # 从 kwargs 中获取资源ID
                folder_id = kwargs.get('folder_id')
                file_id = kwargs.get('file_id')

                if folder_id:
                    folder = DocumentFolderPublic.objects.filter(id=folder_id).order_by().first()
                    if not folder:
                        return json_response(error='文件夹不存在', code=404)

                    # 校验是否为创建人
                    if need_create_permission and folder.created_by_id != request.user.id:
                        logger.warning(
                            f'[PERMISSION] 用户 {request.user.username} 尝试操作他人的公共文件夹 ID:{folder_id}'
                        )
                        return permission_denied_response('无权限操作他人的公共资源', 'not_owner')

                elif file_id:
                    file = DocumentFilePublic.objects.filter(id=file_id).order_by().first()
                    if not file:
                        return json_response(error='文件不存在', code=404)

                    # 校验是否为创建人
                    if need_create_permission and file.created_by_id != request.user.id:
                        logger.warning(
                            f'[PERMISSION] 用户 {request.user.username} 尝试操作他人的公共文件 ID:{file_id}'
                        )
                        return permission_denied_response('无权限操作他人的公共资源', 'not_owner')

                logger.debug(
                    f'[PERMISSION] 用户 {request.user.username} 通过权限校验'
                )
                return view_func(request, *args, **kwargs)

            except Exception as e:
                logger.error(f'[PERMISSION] 权限校验异常: {e}')
                return permission_denied_response('权限校验失败', 'permission_check_error')

        return wrapper
    return decorator

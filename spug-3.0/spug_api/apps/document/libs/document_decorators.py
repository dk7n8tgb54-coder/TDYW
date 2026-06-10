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
from apps.document.libs.view_utils import permission_denied_response
import logging

logger = logging.getLogger(__name__)


def document_permission_check(need_create_permission=True):
    """
    文档操作权限校验装饰器

    功能：
    1. 校验用户是否为管理员（管理员可操作所有公共资源）
    2. 公共空间：普通用户只能操作自己创建的资源
    3. 私有空间：用户只能操作自己的私有资源

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
                # 获取请求参数
                is_public = request.GET.get('is_public', 'false').lower() == 'true'

                # 管理员直接放行（公共空间可操作所有，私有空间仅限自己）
                if is_global_admin(request.user):
                    logger.debug(f'[PERMISSION] 管理员 {request.user.username} 通过权限校验 (is_public={is_public})')
                    return view_func(request, *args, **kwargs)

                # 公共空间权限校验
                if is_public:
                    # 从 kwargs 中获取资源ID
                    folder_id = kwargs.get('folder_id')
                    file_id = kwargs.get('file_id')

                    if folder_id:
                        model = get_folder_model(is_public=True)
                        folder = model.objects.filter(id=folder_id).order_by().first()
                        if not folder:
                            return json_response(error='文件夹不存在', code=404)

                        # 校验是否为创建人
                        if need_create_permission and folder.created_by_id != request.user.id:
                            logger.warning(
                                f'[PERMISSION] 用户 {request.user.username} 尝试操作他人的公共文件夹 ID:{folder_id}'
                            )
                            return permission_denied_response('无权限操作他人的公共资源', 'not_owner')

                    elif file_id:
                        model = get_file_model(is_public=True)
                        file = model.objects.filter(id=file_id).order_by().first()
                        if not file:
                            return json_response(error='文件不存在', code=404)

                        # 校验是否为创建人
                        if need_create_permission and file.created_by_id != request.user.id:
                            logger.warning(
                                f'[PERMISSION] 用户 {request.user.username} 尝试操作他人的公共文件 ID:{file_id}'
                            )
                            return permission_denied_response('无权限操作他人的公共资源', 'not_owner')

                # 私有空间权限校验（已在模型层过滤，无需额外校验）
                # 私有空间的查询已经在 views 中通过 created_by_id 过滤

                logger.debug(
                    f'[PERMISSION] 用户 {request.user.username} 通过权限校验 (is_public={is_public})'
                )
                return view_func(request, *args, **kwargs)

            except Exception as e:
                logger.error(f'[PERMISSION] 权限校验异常: {e}')
                return permission_denied_response('权限校验失败', 'permission_check_error')

        return wrapper
    return decorator

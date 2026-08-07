# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
统一文件冲突处理服务
用于上传、复制、移动操作的冲突检测和解决

冲突定义：目标文件夹内存在相同 display_name 的文件即为冲突
统一操作选项：replace（替换）、keep（保留两者）、skip（跳过）
"""
import os
import time
import logging
from django.db import transaction
from libs.tenant_utils import apply_tenant_filter
from libs import json_response

logger = logging.getLogger(__name__)

CONFLICT_ACTIONS = {'replace', 'keep', 'skip'}


def check_display_name_conflict(FileModel, display_name, folder, user, is_public):
    """
    检查目标文件夹内是否存在相同 display_name 的文件

    Args:
        FileModel: 文件模型类（DocumentFilePrivate / DocumentFilePublic）
        display_name: 要检查的显示名称
        folder: 目标文件夹对象（None 表示根目录）
        user: 当前用户
        is_public: 是否公共空间

    Returns:
        冲突的文件对象，无冲突返回 None
    """
    if not display_name:
        return None
    qs = FileModel.objects.filter(display_name=display_name).order_by()
    if folder:
        qs = qs.filter(folder=folder)
    else:
        qs = qs.filter(folder__isnull=True)
    if not is_public:
        qs = apply_tenant_filter(qs, user, strict_mode=True)
    return qs.first()


def generate_unique_display_name(FileModel, original_name, folder, user, is_public):
    """
    生成唯一的 display_name（带 _1, _2 后缀）

    与 naming_utils.generate_unique_logical_name 配合使用，
    确保 name 和 display_name 都唯一。

    Args:
        FileModel: 文件模型类
        original_name: 原始显示名称
        folder: 目标文件夹对象
        user: 当前用户
        is_public: 是否公共空间

    Returns:
        唯一的 display_name
    """
    if not original_name:
        return 'unnamed'
    # 检查原名是否已存在
    existing = check_display_name_conflict(
        FileModel, original_name, folder, user, is_public
    )
    if not existing:
        return original_name
    # 有同名，添加数字后缀
    name_without_ext, ext = os.path.splitext(original_name)
    counter = 1
    while True:
        candidate = f'{name_without_ext}_{counter}{ext}'
        if not check_display_name_conflict(FileModel, candidate, folder, user, is_public):
            return candidate
        counter += 1
        if counter > 999:
            # 超过 999 个同名文件，使用时间戳兜底
            return f'{name_without_ext}_{int(time.time())}{ext}'


def build_conflict_info(existing_file, new_name, new_size=0):
    """
    构建冲突信息结构

    Returns:
        dict: 冲突信息
    """
    return {
        'existing_id': existing_file.id,
        'existing_name': existing_file.display_name or existing_file.name,
        'existing_size': existing_file.file_size or 0,
        'new_name': new_name,
        'new_size': new_size,
        'same_size': (existing_file.file_size or 0) == new_size,
    }


def conflict_response(conflicts):
    """
    构建冲突 HTTP 响应

    当正式接口遇到冲突但未收到合法 conflict_action 时返回此响应。
    前端收到后应弹窗让用户选择。

    Args:
        conflicts: 冲突信息列表

    Returns:
        HttpResponse
    """
    return json_response(data={
        'status': 'conflict',
        'conflicts': conflicts,
    })


def batch_check_conflicts(FileModel, items, folder, user, is_public):
    """
    批量检查多个文件的冲突

    Args:
        FileModel: 文件模型类
        items: [{display_name, file_size, ...}, ...]
        folder: 目标文件夹对象
        user: 当前用户
        is_public: 是否公共空间

    Returns:
        冲突信息列表
    """
    conflicts = []
    for item in items:
        display_name = item.get('display_name') or item.get('name', '')
        file_size = item.get('file_size', 0)
        existing = check_display_name_conflict(
            FileModel, display_name, folder, user, is_public
        )
        if existing:
            conflicts.append(build_conflict_info(existing, display_name, file_size))
    return conflicts

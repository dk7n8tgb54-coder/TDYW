# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
权限检查工具
Permission Checking Utilities

租户操作检查通用函数，用于验证记录是否存在且属于当前租户
"""

import logging
from libs import json_response, human_datetime
from libs.tenant_utils import apply_tenant_filter

logger = logging.getLogger(__name__)


def tenant_operation_check(request, model, record_id, operation='操作'):
    """
    租户操作检查通用函数
    验证记录是否存在且属于当前租户

    参数：
        request: 请求对象
        model: 数据模型类
        record_id: 记录ID
        operation: 操作名称（用于日志）

    返回：
        (queryset, None) - 检查通过，返回过滤后的queryset
        (None, error_response) - 检查失败，返回错误响应

    租户过滤规则（30人内网团队核心场景）：
    1. 通过PK直接操作记录 → 必须加租户过滤（无上下文，易跨租户）
    2. 基于已过滤的record查关联表（如ScheduleSwap→Schedule）→ 不加（record已限定租户）
    3. 批量操作ID列表 → 验证"过滤后数量=原数量"（避免混有跨租户ID）
    4. 所有过滤失败场景 → 统一返回"记录不存在或无权操作"
    """
    queryset = apply_tenant_filter(model.objects.filter(pk=record_id), request.user)
    if not queryset.exists():
        logger.warning(
            f'用户{request.user.username}尝试{operation}跨租户/不存在的{model.__name__}记录{record_id} | '
            f'IP：{request.META.get("REMOTE_ADDR")} | 时间：{human_datetime()}'
        )
        return None, json_response(error='记录不存在或无权操作')
    return queryset, None


def check_ownership(request, record, operation='操作'):
    """
    检查记录所有权（租户隔离）

    参数：
        request: 请求对象
        record: 记录对象
        operation: 操作名称

    返回：
        bool: 是否拥有权限
    """
    user = request.user
    record_tenant_id = getattr(record, 'tenant_id', None)
    user_tenant_id = getattr(user, 'tenant_id', None)

    # 超级管理员有所有权限
    if getattr(user, 'is_supper', False):
        return True

    # 检查租户ID是否匹配
    if record_tenant_id and record_tenant_id != user_tenant_id:
        logger.warning(
            f'用户{user.username}尝试{operation}跨租户记录 | '
            f'用户租户：{user_tenant_id}, 记录租户：{record_tenant_id}'
        )
        return False

    return True


def validate_tenant_access(user, model_class, object_id):
    """
    验证用户是否有权访问指定对象

    参数：
        user: 用户对象
        model_class: 模型类
        object_id: 对象ID

    返回：
        tuple: (has_access, record_or_none)
    """
    queryset = apply_tenant_filter(model_class.objects.filter(pk=object_id), user)
    record = queryset.first()
    return record is not None, record

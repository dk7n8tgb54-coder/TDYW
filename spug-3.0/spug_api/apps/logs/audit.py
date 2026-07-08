# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

"""
审计日志核心工具模块
提供：
1. 线程本地存储（用于Django信号获取当前用户）
2. URL路径 → 操作对象类型映射
3. HTTP方法 → 操作类型映射
4. @audit 装饰器（用于登录/登出/导出等特殊操作）
5. save_audit_log() 辅助函数
"""

import json
import threading
import logging
from functools import wraps

logger = logging.getLogger(__name__)

SENSITIVE_KEYWORDS = (
    'password', 'token', 'secret', 'key', 'private', 'credential',
    'captcha', 'cookie', 'session',
)

# ==================== 线程本地存储 ====================
_audit_local = threading.local()


def set_audit_user(user):
    """设置当前线程的审计用户（从中间件调用）"""
    _audit_local.user = user


def get_audit_user():
    """获取当前线程的审计用户（信号处理器中使用）"""
    return getattr(_audit_local, 'user', None)


def clear_audit_user():
    """清除当前线程的审计用户"""
    if hasattr(_audit_local, 'user'):
        delattr(_audit_local, 'user')


# ==================== URL → 操作对象映射 ====================
# 键：URL路径前缀，值：{'type': 对象类型标识, 'name': 中文名称}
TARGET_MAP = {
    # 账号体系（租户 / 角色 / 用户 / 个人信息 / 认证）
    # 注意：`/account/tenant` 必须放在 `/account/` 系列靠前位置，否则会被更细的子前缀吞掉匹配
    '/account/tenant': {'type': 'tenant', 'name': '租户'},
    '/account/user': {'type': 'user', 'name': '用户'},
    '/account/role': {'type': 'role', 'name': '角色'},
    '/account/self': {'type': 'self', 'name': '个人信息'},
    '/account/login': {'type': 'auth', 'name': '认证'},
    '/account/logout': {'type': 'auth', 'name': '认证'},
    # 业务模块
    '/device/': {'type': 'device', 'name': '设备'},
    '/document/': {'type': 'document', 'name': '文档'},
    '/fault/': {'type': 'fault', 'name': '故障'},
    '/duty/': {'type': 'duty', 'name': '值班'},
    '/interference/': {'type': 'interference', 'name': '干扰'},
    '/runlog/': {'type': 'runlog', 'name': '运行日志'},
    '/radio-license/': {'type': 'radio_license', 'name': '无线电台执照'},
    '/setting/': {'type': 'setting', 'name': '系统设置'},
    '/upgrade/': {'type': 'upgrade', 'name': '升级'},
    '/checksheet/': {'type': 'checksheet', 'name': '检查表'},
    '/home/': {'type': 'home', 'name': '首页'},
    '/exec/': {'type': 'exec', 'name': '执行'},
    '/apis/': {'type': 'api', 'name': 'API'},
    # 审计模块自身（查询/导出不记录，但其他写操作按 audit 类型记录）
    '/logs/': {'type': 'audit', 'name': '操作审计'},
}


# ==================== HTTP方法 → 操作类型映射 ====================
METHOD_ACTION_MAP = {
    'POST': 'create',
    'PUT': 'update',
    'PATCH': 'update',
    'DELETE': 'delete',
}

# 请求体 action 字段 → 审计动作映射
# 用于 POST 携带 action 字段表达真实业务动作的场景（如值班日志 POST {action: 'delete'}）
BODY_ACTION_MAP = {
    'delete': 'delete',
    'export': 'export',
    'import': 'import',
    'approve': 'approve',
}


# ==================== 中间件排除路径 ====================
# 这些路径不记录审计日志
AUDIT_EXCLUDES = [
    '/account/login/',     # 登录由装饰器单独记录
    '/account/login/history/',
    '/logs/audit/',        # 审计日志查询本身不记录
]


def resolve_target(path):
    """根据URL路径解析操作对象类型"""
    for prefix, info in TARGET_MAP.items():
        if prefix in path:
            return info
    return {'type': 'unknown', 'name': '未知'}


def resolve_action(method, body_data=None):
    """根据HTTP方法和请求体解析操作类型

    优先根据请求体中的 action 字段判断业务动作（如 POST + action=delete），
    否则按 HTTP 方法映射。普通 POST 新增仍记录为 create。
    """
    if isinstance(body_data, dict):
        action = str(body_data.get('action') or '').strip().lower()
        if action in BODY_ACTION_MAP:
            return BODY_ACTION_MAP[action]
    return METHOD_ACTION_MAP.get(method, 'other')


def _is_sensitive_field(name):
    if not isinstance(name, str):
        return False
    lower = name.lower()
    return any(keyword in lower for keyword in SENSITIVE_KEYWORDS)


def _truncate_text(value, max_string_length):
    if len(value) <= max_string_length:
        return value
    return value[:max_string_length] + '...'


def sanitize_audit_detail(value, max_string_length=500, max_list_items=20):
    """Recursively redact sensitive fields and keep audit detail compact."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if _is_sensitive_field(key):
                result[key] = '***'
            else:
                result[key] = sanitize_audit_detail(
                    item, max_string_length=max_string_length,
                    max_list_items=max_list_items
                )
        return result
    if isinstance(value, (list, tuple)):
        items = [
            sanitize_audit_detail(
                item, max_string_length=max_string_length,
                max_list_items=max_list_items
            )
            for item in list(value)[:max_list_items]
        ]
        if len(value) > max_list_items:
            items.append({
                '_truncated': len(value) - max_list_items,
                '_total': len(value),
            })
        return items
    if isinstance(value, str):
        return _truncate_text(value, max_string_length)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _truncate_text(str(value), max_string_length)


def _merge_audit_error(detail, error):
    error_text = _truncate_text(str(error), 500)
    if isinstance(detail, dict):
        result = dict(detail)
        result['error'] = error_text
        return result
    if detail in (None, ''):
        return {'error': error_text}
    return {'summary': detail, 'error': error_text}


def record_audit_event(request, action, target_type, target_id=None,
                       target_name=None, detail=None, is_success=True,
                       error=None):
    """Save one concise business audit record and mark request as handled."""
    try:
        from libs.utils import get_request_real_ip

        if error is not None:
            detail = _merge_audit_error(detail, error)
            is_success = False

        sanitized_detail = sanitize_audit_detail(detail)
        if sanitized_detail is not None and not isinstance(sanitized_detail, dict):
            sanitized_detail = {'summary': sanitized_detail}
        user = getattr(request, 'user', None) if request is not None else None
        headers = getattr(request, 'headers', None) if request is not None else None
        ip = get_request_real_ip(headers) if headers else ''

        save_audit_log(
            user_id=getattr(user, 'id', 0) or 0,
            username=getattr(user, 'username', '') or '',
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            detail=sanitized_detail,
            ip=ip,
            is_success=is_success,
            tenant_id=getattr(user, 'tenant_id', 'default') or 'default',
            request_id=getattr(request, '_audit_request_id', None) if request is not None else None,
            user_agent=_extract_user_agent(request) if request is not None else '',
        )
        if request is not None:
            request._audit_handled = True
    except Exception as e:
        logger.error(f'[AUDIT] record audit event failed: {e}', exc_info=True)


def save_audit_log(user_id, username, action, target_type, target_id=None,
                   target_name=None, detail=None, ip='', is_success=True,
                   tenant_id='default', request_hash=None, response_hash=None,
                   request_id=None, user_agent=None):
    """保存审计日志记录

    证据闭环第一阶段增强：
    - 规范化 detail（dict → JSON 字符串）
    - 计算 request_hash（基于存库 detail，未传入时自动计算）
    - 查询同租户上一条日志的 log_hash 作为 prev_hash，构建哈希链
    - 计算并写入 log_hash（覆盖全部关键字段 + prev_hash）

    新增参数均有默认值，向后兼容现有调用方（middleware / audit 装饰器）。
    任何异常都不影响主请求流程，仅记录错误日志。
    """
    try:
        from apps.logs.models import AuditLog
        from apps.logs.hash_chain import (
            compute_request_hash, compute_log_hash_from_values,
        )
        from django.db import transaction
        from django.utils import timezone

        # 1. 规范化 detail：dict → JSON 字符串（与历史行为一致）
        if isinstance(detail, dict):
            detail = json.dumps(detail, ensure_ascii=False)

        # 2. 计算 request_hash：基于存库 detail 内容，证明详情未被篡改
        #    调用方未显式传入时自动计算，保证写入与校验口径一致
        if request_hash is None:
            request_hash = compute_request_hash(detail)
        response_hash = response_hash or ''

        # 3. 在事务内查询同租户上一条日志的 log_hash 作为 prev_hash
        #    内网环境并发量有限，采用乐观查询；偶发并发分叉可通过每日摘要校验发现
        with transaction.atomic():
            last_log = (
                AuditLog.objects
                .filter(tenant_id=tenant_id)
                .order_by('-id')
                .first()
            )
            prev_hash = last_log.log_hash if last_log else ''

            # 4. 显式生成 created_at，保证 log_hash 输入与落库值一致
            created_at = timezone.now()

            # 5. 计算 log_hash（覆盖全部关键字段 + prev_hash）
            log_hash = compute_log_hash_from_values(
                tenant_id=tenant_id,
                user_id=user_id,
                username=username,
                action=action,
                target_type=target_type,
                target_id=target_id,
                target_name=target_name,
                detail=detail,
                ip=ip,
                is_success=is_success,
                created_at=created_at,
                request_hash=request_hash,
                response_hash=response_hash,
                request_id=request_id,
                user_agent=user_agent,
                prev_hash=prev_hash,
            )

            # 6. 落库
            AuditLog.objects.create(
                user_id=user_id,
                username=username,
                action=action,
                target_type=target_type,
                target_id=str(target_id) if target_id else None,
                target_name=target_name,
                detail=detail,
                ip=ip,
                is_success=is_success,
                tenant_id=tenant_id,
                created_at=created_at,
                request_hash=request_hash,
                response_hash=response_hash,
                prev_hash=prev_hash,
                log_hash=log_hash,
                request_id=request_id,
                user_agent=user_agent,
            )
    except Exception as e:
        logger.error(f'[AUDIT] 保存审计日志失败: {e}')


# ==================== 审计装饰器 ====================
def audit(action, target_type=None, target_name=None):
    """
    审计日志装饰器，用于需要细粒度记录的操作（如登录/登出/导出等）

    用法：
        @audit('登录系统', target_type='auth')
        def login(request):
            ...

        @audit('导出PDF', target_type='device', target_name='设备')
        def export_pdf(request):
            ...
    """
    def decorate(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            # 提取request对象
            request = None
            for item in args[:2]:
                if hasattr(item, 'user') or hasattr(item, 'method'):
                    request = item
                    break

            # 执行视图函数
            response = view_func(*args, **kwargs)

            # 记录审计日志
            if request:
                try:
                    user = getattr(request, 'user', None)
                    if user and hasattr(user, 'id'):
                        ip = ''
                        if hasattr(request, 'headers'):
                            from libs.utils import get_request_real_ip
                            ip = get_request_real_ip(request.headers)

                        # 判断操作是否成功（基于响应状态码）
                        is_success = True
                        if hasattr(response, 'status_code') and response.status_code >= 400:
                            is_success = False

                        # 解析target_type
                        _target_type = target_type or 'other'
                        _target_name = target_name or action

                        # 采集证据闭环字段：user_agent / request_id / response_hash
                        from apps.logs.hash_chain import compute_response_hash
                        user_agent = _extract_user_agent(request)
                        request_id = getattr(request, '_audit_request_id', None)
                        response_hash = ''
                        if hasattr(response, 'content'):
                            response_hash = compute_response_hash(response.content)

                        save_audit_log(
                            user_id=user.id,
                            username=user.username,
                            action=_map_action(action),
                            target_type=_target_type,
                            target_name=_target_name,
                            ip=ip,
                            is_success=is_success,
                            tenant_id=getattr(user, 'tenant_id', 'default'),
                            response_hash=response_hash,
                            request_id=request_id,
                            user_agent=user_agent,
                        )
                except Exception as e:
                    logger.error(f'[AUDIT] 装饰器记录审计日志失败: {e}')

            return response
        return wrapper
    return decorate


def _map_action(action_desc):
    """将中文操作描述映射为action字段值"""
    action_lower = action_desc.lower() if isinstance(action_desc, str) else ''
    mapping = {
        '登录': 'login',
        '登出': 'logout',
        '退出': 'logout',
        '创建': 'create',
        '新增': 'create',
            '添加': 'create',
        '修改': 'update',
        '更新': 'update',
        '编辑': 'update',
        '删除': 'delete',
        '导出': 'export',
        '导入': 'import',
        '审批': 'approve',
    }
    for key, value in mapping.items():
        if key in action_desc:
            return value
    return 'other'


def _extract_user_agent(request):
    """从请求中提取 User-Agent，截断至 500 字符以适配字段长度。

    兼容 request.headers（Django 请求）与 request.META 两种取值方式。
    """
    ua = ''
    headers = getattr(request, 'headers', None)
    if headers:
        ua = headers.get('User-Agent') or headers.get('user-agent') or ''
    if not ua:
        meta = getattr(request, 'META', None)
        if meta:
            ua = meta.get('HTTP_USER_AGENT', '')
    return ua[:500] if ua else ''

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
【M12 修复 2026-06-08】统一审计日志工具

提供结构化、JSON 行格式的审计日志输出（与业务 logger 分离）。

设计要点：
1. 顶层函数 audit_log(...)：供 view/celery task 直接调用
2. AuditLogger 类：包装 audit_log，保留面向对象风格
3. 输出到独立 logger 'audit'，便于在 settings.py 中配置独立 handler
   （如单独落盘到 audit.log、上报到 SIEM、推送到 ELK 等）
4. 不抛异常：缺 user_id/tenant_id/request_id/ip 时填 None；target_id=None
   时（批量场景）也能正常工作
5. 返回 JSON 字符串：方便调用方需要时再写入其他存储（DB / 消息队列）

使用示例：
    from libs.audit_logger import audit_log

    # 同步 view（带 request）
    audit_log(
        request=request,
        action='file_delete',
        target_id=file_id,
        status='success',
        target_type='DocumentFile',
    )

    # 异步 task（无 request）
    audit_log(
        action='file_delete_async',
        target_id=None,
        status='pending',
        target_type='DocumentFile',
        user_id=user.id,
        tenant_id=user.tenant_id,
    )
"""
import json
import logging
import uuid
from datetime import datetime

# 关键：与业务 logger 分离
# 业务 logger 通常叫 __name__ / apps.document
# 审计 logger 独立命名为 'audit'，可在 settings.py 中配置独立 handler
logger = logging.getLogger('audit')


def _safe_get(obj, *keys, default=None):
    """安全地按顺序尝试取多个属性名（避免 AttributeError）。"""
    if obj is None:
        return default
    for key in keys:
        if hasattr(obj, key):
            value = getattr(obj, key)
            if value is not None:
                return value
    return default


def _resolve_ip(request_or_ip):
    """
    解析客户端 IP：
    - None / '' → None
    - str → 当作 IP 字符串原样返回
    - Django request → 优先 X-Forwarded-For 第一项，再 X-Real-IP，最后 REMOTE_ADDR
    """
    if request_or_ip is None or request_or_ip == '':
        return None
    if isinstance(request_or_ip, str):
        return request_or_ip or None
    meta = getattr(request_or_ip, 'META', None) or {}
    xff = meta.get('HTTP_X_FORWARDED_FOR')
    if xff:
        first = xff.split(',')[0].strip()
        if first:
            return first
    xri = meta.get('HTTP_X_REAL_IP')
    if xri:
        return xri.strip() or None
    remote = meta.get('REMOTE_ADDR')
    if remote:
        return remote.strip() or None
    return None


def _resolve_request_id(request_or_id):
    """
    解析 request_id：
    - None / '' → 自动生成 uuid4 hex
    - str → 原样返回
    - Django request → 优先 X-Request-ID header，否则自动生成
    """
    if request_or_id is None or request_or_id == '':
        return uuid.uuid4().hex
    if isinstance(request_or_id, str):
        return request_or_id
    meta = getattr(request_or_id, 'META', None) or {}
    rid = meta.get('HTTP_X_REQUEST_ID')
    if rid:
        return rid
    rid = meta.get('request_id')
    if rid:
        return rid
    return uuid.uuid4().hex


def _resolve_target_type(target, target_type):
    """
    解析 target_type 字符串：
    1) 显式传入的 target_type 优先
    2) target 对象的 __class__.__name__
    3) 兜底 'unknown'
    """
    if target_type:
        return str(target_type)
    if target is not None:
        return target.__class__.__name__
    return 'unknown'


def _resolve_user_id(user_or_id):
    """
    解析 user_id：
    - None → None
    - int / str → 原样返回
    - User 对象 → 取 .id
    """
    if user_or_id is None:
        return None
    if isinstance(user_or_id, (int, str)):
        return user_or_id
    return getattr(user_or_id, 'id', None)


def _resolve_tenant_id(user_or_tenant):
    """
    解析 tenant_id：
    - None → None
    - str → 原样返回
    - User 对象 → 取 .tenant_id
    """
    if user_or_tenant is None:
        return None
    if isinstance(user_or_tenant, str):
        return user_or_tenant
    return getattr(user_or_tenant, 'tenant_id', None)


def _resolve_username(user_or_name):
    """从 User 对象或字符串解析 username（仅供日志可读性，不作为审计主字段）。"""
    if user_or_name is None:
        return None
    if isinstance(user_or_name, str):
        return user_or_name
    return getattr(user_or_name, 'username', None)


def audit_log(
    request=None,
    action=None,
    target_id=None,
    status='success',
    target_type=None,
    target=None,
    user=None,
    user_id=None,
    tenant_id=None,
    request_id=None,
    ip=None,
    message=None,
    **extra_fields,
):
    """
    【M12 新增】统一审计日志入口

    Args:
        request: Django HttpRequest（可选），从中解析 ip/request_id/user_id/tenant_id
        action: 操作名（如 'file_delete', 'folder_restore', 'file_upload'）
        target_id: 目标资源 ID（int/str/None，批量时为 None）
        status: 操作状态（'success' / 'failed' / 'pending'，其他值允许但建议用这三个）
        target_type: 资源类型名（str，显式传值优先于 target.__class__.__name__）
        target: 目标对象（ORM 实例等），用于从 __class__.__name__ 推断 target_type
        user: User 对象（可选，log_operation 升级场景用），从中取 .id/.username/.tenant_id
        user_id: 操作用户 ID（int/str/None，缺省从 request.user.id 或 user.id 取）
        tenant_id: 租户 ID（str/None，缺省从 request.user.tenant_id 或 user.tenant_id 取）
        request_id: 请求追踪 ID（str/None，缺省从 X-Request-ID header 取或自动生成）
        ip: 客户端 IP（str/None，缺省从 X-Forwarded-For / REMOTE_ADDR 取）
        message: 人类可读的描述（可选，便于日志检索）
        **extra_fields: 任意额外字段（file_size / file_count / task_id / space 等）

    Returns:
        str: 序列化后的 JSON 字符串（同时通过 'audit' logger 输出）
    """
    # 解析 user 对象（优先级：显式 user_id/tenant_id > user 对象 > request.user）
    username = None
    if user is not None:
        user_id = user_id if user_id is not None else _resolve_user_id(user)
        tenant_id = tenant_id if tenant_id is not None else _resolve_tenant_id(user)

    # 自动从 request 提取未显式提供的字段
    if request is not None:
        user_id = user_id if user_id is not None else _resolve_user_id(getattr(request, 'user', None))
        tenant_id = tenant_id if tenant_id is not None else _resolve_tenant_id(getattr(request, 'user', None))
        request_id = request_id if request_id is not None else _resolve_request_id(request)
        ip = ip if ip is not None else _resolve_ip(request)

    # request_id 兜底：即使没传 request，也自动生成一个（保证非空，方便串联链路）
    if request_id is None:
        request_id = uuid.uuid4().hex

    # 解析 target_type（显式 > target > 'unknown'）
    target_type_resolved = _resolve_target_type(target, target_type)

    # 解析 username（如果之前没解析到）
    if not username:
        if user is not None:
            username = _resolve_username(user)
        elif request is not None:
            username = _resolve_username(getattr(request, 'user', None))

    # 构造审计记录
    record = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'action': action,
        'target_type': target_type_resolved,
        'target_id': target_id,
        'status': status,
        'user_id': user_id,
        'username': username,
        'tenant_id': tenant_id,
        'request_id': request_id,
        'ip': ip,
        'message': message,
    }
    # 合并额外字段（避免覆盖核心字段）
    for k, v in extra_fields.items():
        if k not in record:
            record[k] = v

    # 序列化为 JSON
    try:
        record_str = json.dumps(record, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        # 防御：序列化失败时降级为最简结构
        record_str = json.dumps({
            'timestamp': record.get('timestamp'),
            'action': action,
            'status': 'log_serialization_failed',
            'error': str(exc),
        }, ensure_ascii=False)
        logger.error('audit_log serialization failed: %s', exc)

    # 输出到独立 audit logger
    logger.info(record_str)

    return record_str


class AuditLogger:
    """
    【M12 新增】AuditLogger 类，包装 audit_log 函数
    保留面向对象风格，供习惯 class-based 的代码使用
    """

    def __init__(self, request=None, default_user_id=None, default_tenant_id=None):
        self.request = request
        self.default_user_id = default_user_id
        self.default_tenant_id = default_tenant_id

    def log(self, action, target_id=None, status='success', **kwargs):
        """类方法版 audit_log，保留 self.default_user_id / self.default_tenant_id 上下文"""
        kwargs.setdefault('user_id', self.default_user_id)
        kwargs.setdefault('tenant_id', self.default_tenant_id)
        return audit_log(
            request=self.request,
            action=action,
            target_id=target_id,
            status=status,
            **kwargs,
        )

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

"""
审计日志中间件
自动拦截所有非GET的写操作请求并记录审计日志
与 record_audit_event() 互补：中间件覆盖所有CRUD操作，显式调用覆盖特殊操作（登录/登出/导出等）
"""

import json
import uuid
import logging
from django.utils.deprecation import MiddlewareMixin
from apps.logs.audit import (
    resolve_target, resolve_action, save_audit_log,
    set_audit_user, clear_audit_user, _extract_user_agent, AUDIT_EXCLUDES,
    sanitize_audit_detail,
)
from apps.logs.hash_chain import compute_response_hash
from libs.utils import get_request_real_ip

logger = logging.getLogger(__name__)


# 敏感字段关键词黑名单（小写匹配，只要字段名包含任一关键词即脱敏）。
# 用于在写入审计 detail 前剔除密码、令牌、密钥、私钥、凭证等敏感或半敏感字段。
# 采用关键词匹配而非固定字段名，可覆盖 old_password/new_password/private_key/public_key/
# api_key/spug_push_key/wx_token/access_token 等项目内已存在的衍生命名。
SENSITIVE_KEYWORDS = ('password', 'token', 'secret', 'key', 'private', 'credential')


def _is_sensitive_field(name):
    """判断字段名是否包含敏感关键词（需脱敏）"""
    if not isinstance(name, str):
        return False
    lower = name.lower()
    return any(keyword in lower for keyword in SENSITIVE_KEYWORDS)


class AuditLogMiddleware(MiddlewareMixin):
    """
    审计日志中间件
    - process_request: 设置线程本地用户（供Django信号使用）
    - process_response: 记录写操作的审计日志
    """

    def process_request(self, request):
        """设置线程本地用户信息，并生成请求唯一标识"""
        # 为每个请求生成唯一 request_id，供审计日志关联同请求多条记录
        # 存于 request 对象，中间件与装饰器共用
        request._audit_request_id = uuid.uuid4().hex
        if hasattr(request, 'user') and request.user:
            set_audit_user(request.user)

    def process_response(self, request, response):
        """处理完成后记录审计日志"""
        try:
            self._record_audit(request, response)
        except Exception as e:
            logger.error(f'[AUDIT] 中间件记录审计日志异常: {e}')
            # 指南 3.2 要求 ERROR 触发告警
            try:
                from libs.alert import send_alert
                send_alert(
                    title='审计日志中间件异常',
                    message=f'中间件记录审计日志失败: {e}',
                    level='error',
                    source='middleware',
                )
            except Exception:
                logger.error('[AUDIT] send_alert 也失败了', exc_info=True)
        finally:
            # 清除线程本地用户
            clear_audit_user()
        return response

    def _record_audit(self, request, response):
        """核心记录逻辑"""
        if getattr(request, '_audit_handled', False):
            return

        method = request.method
        path = request.path

        # 只记录写操作（POST/PUT/PATCH/DELETE）
        if method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
            return

        # 跳过排除路径
        for exclude_path in AUDIT_EXCLUDES:
            if exclude_path in path:
                return

        # 跳过静态文件和健康检查
        if path.startswith('/api/document/health') or path.startswith('/document/health'):
            return

        # 获取用户信息
        user = getattr(request, 'user', None)
        if not user or not hasattr(user, 'id'):
            return

        # 解析操作对象
        target_info = resolve_target(path)

        # 解析请求体（用于判断业务 action 和提取详情），解析失败不影响主流程
        body_data = self._parse_body(request)
        action = resolve_action(method, body_data)

        # 解析操作结果：项目通用 json_response(error=...) 默认返回 HTTP 200，
        # 仅靠状态码无法识别业务失败，需解析响应体中的 error 字段
        is_success, error_msg = self._resolve_success_and_error(response)

        # 尝试从响应中提取对象信息
        target_id = None
        target_name = None
        detail = None

        try:
            target_id, target_name, detail = self._extract_detail(
                request, response, target_info, body_data
            )
        except Exception:
            pass  # 提取失败不影响主流程

        # 业务失败时，将错误信息补充到 detail，便于审计页面查看失败原因
        if error_msg and not is_success:
            detail = self._merge_error_into_detail(detail, error_msg)

        # 获取IP
        ip = get_request_real_ip(request.headers) if hasattr(request, 'headers') else ''

        # 采集证据闭环字段
        user_agent = _extract_user_agent(request)
        request_id = getattr(request, '_audit_request_id', None)
        # 响应哈希：流式响应/文件下载无 content 属性时留空
        response_hash = ''
        if hasattr(response, 'content'):
            response_hash = compute_response_hash(response.content)

        # 保存审计日志
        save_audit_log(
            user_id=user.id,
            username=user.username,
            action=action,
            target_type=target_info['type'],
            target_id=target_id,
            target_name=target_name,
            detail=detail,
            ip=ip,
            is_success=is_success,
            tenant_id=getattr(user, 'tenant_id', 'default'),
            response_hash=response_hash,
            request_id=request_id,
            user_agent=user_agent,
        )

    def _parse_body(self, request):
        """解析请求体 JSON，返回 dict；非 JSON 或解析失败返回 None"""
        content_type = request.META.get('CONTENT_TYPE', '')
        if content_type and 'application/json' not in content_type.lower():
            return None
        try:
            body = request.body
            if not body:
                return None
            data = json.loads(body)
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, AttributeError):
            return None

    def _resolve_success_and_error(self, response):
        """根据 HTTP 状态码和响应体判断操作是否成功，并提取错误信息

        项目通用 json_response(error=...) 默认返回 HTTP 200，
        因此需要进一步解析响应体中的 error 字段识别业务失败。
        兼容非 JSON、文件、流式响应，解析失败视为成功，绝不影响主请求。
        """
        # HTTP 状态码 >= 400 直接判失败
        if hasattr(response, 'status_code') and response.status_code >= 400:
            return False, None
        # StreamingHttpResponse / FileResponse 没有 content 属性，无法解析
        if not hasattr(response, 'content'):
            return True, None
        try:
            data = json.loads(response.content)
        except Exception:
            # 非 JSON 响应（文件等），按状态码视为成功
            return True, None
        if not isinstance(data, dict):
            return True, None
        error = data.get('error')
        if error:
            return False, error
        return True, None

    def _merge_error_into_detail(self, detail, error_msg):
        """将业务错误信息合并到 detail 中，便于审计页面展示失败原因"""
        error_msg = str(error_msg)
        if isinstance(detail, dict):
            detail = dict(detail)
            detail['error'] = error_msg
            return detail
        if detail is None:
            return {'error': error_msg}
        # detail 已是字符串，追加错误信息
        return f'{detail} | error: {error_msg}'

    def _extract_from_response(self, response):
        """从响应体中提取目标ID和名称"""
        target_id = None
        target_name = None
        if hasattr(response, 'content'):
            try:
                content = json.loads(response.content)
                data = content.get('data', {})
                if isinstance(data, dict):
                    if data.get('id'):
                        target_id = str(data['id'])
                    for name_field in ('name', 'username', 'title'):
                        if data.get(name_field):
                            target_name = str(data[name_field])
                            break
            except (json.JSONDecodeError, AttributeError):
                pass
        return target_id, target_name

    def _extract_from_request_body(self, request, target_id, target_name, body_data=None):
        """从请求体中提取详情、名称和ID"""
        detail = None
        if request.method not in ('POST', 'PUT', 'PATCH'):
            return target_id, target_name, detail
        content_type = request.META.get('CONTENT_TYPE', '')
        if body_data is None and content_type and 'application/json' not in content_type.lower():
            return target_id, target_name, detail
        try:
            if body_data is None:
                body = request.body
                if not body:
                    return target_id, target_name, detail
                body_data = json.loads(body)
            exclude_fields = {
                'id', 'tenant_id', 'created_at', 'updated_at',
                'created_by_id', 'updated_by_id', 'deleted_by_id',
            }
            # 敏感字段采用关键词黑名单匹配（password/token/secret/key/private/credential），
            # 覆盖 password/old_password/new_password/access_token/private_key/public_key/
            # api_key/spug_push_key/wx_token 等所有衍生命名，避免敏感信息泄露到审计日志。
            detail = {
                k: v for k, v in body_data.items()
                if k not in exclude_fields
            }
            detail = sanitize_audit_detail(detail)
            if not detail:
                detail = None
            if not target_name:
                for name_field in ('name', 'username', 'title', 'nickname'):
                    if body_data.get(name_field):
                        target_name = str(body_data[name_field])
                        break
            if not target_id and body_data.get('id'):
                target_id = str(body_data['id'])
        except (json.JSONDecodeError, AttributeError):
            pass
        return target_id, target_name, detail

    def _extract_id_from_query(self, request):
        """从 query 参数提取对象 ID，支持单个 id 和批量 ids

        项目中大量删除接口使用 DELETE ?id=xxx，需补充从 request.GET 提取。
        批量删除 ?ids=1,2,3 记录为逗号分隔字符串。
        """
        try:
            single_id = request.GET.get('id')
            if single_id:
                return str(single_id)
            ids = request.GET.get('ids')
            if ids:
                return str(ids)
        except Exception:
            pass
        return None

    def _extract_detail(self, request, response, target_info, body_data=None):
        """从请求/响应中提取对象ID、名称和详情"""
        target_id = None
        # 1. 尝试从URL路径提取对象ID（如 /account/user/5/ 中的 5）
        path_parts = request.path.strip('/').split('/')
        if len(path_parts) >= 3 and path_parts[-1].isdigit():
            target_id = path_parts[-1]

        # 2. 尝试从响应体提取信息
        resp_id, target_name = self._extract_from_response(response)
        target_id = target_id or resp_id

        # 3. 尝试从 query 参数提取（DELETE ?id=xxx / 批量 ?ids=1,2,3）
        if not target_id:
            target_id = self._extract_id_from_query(request)

        # 4. 尝试从请求体提取详情
        target_id, target_name, detail = self._extract_from_request_body(
            request, target_id, target_name, body_data
        )

        return target_id, target_name, detail

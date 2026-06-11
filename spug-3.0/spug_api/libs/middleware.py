# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from .utils import json_response, get_request_real_ip
from apps.account.models import User
from apps.setting.utils import AppSetting
import logging
import traceback
import time

logger = logging.getLogger(__name__)

# 预览端点路径前缀（支持 preview_token 认证）
PREVIEW_ENDPOINT_PREFIXES = (
    '/document/preview/',
    '/api/document/preview/',
    '/document/text_content/',
    '/api/document/text_content/',
)


class HandleExceptionMiddleware(MiddlewareMixin):
    """
    Handle view function exceptions securely
    """

    def process_exception(self, request, exception):
        logger.error(
            f'Unhandled exception on {request.method} {request.path}',
            exc_info=True
        )
        if settings.DEBUG:
            return json_response(error='Exception: %s' % exception)
        else:
            return json_response(error='服务器内部错误，请联系管理员')


class AuthenticationMiddleware(MiddlewareMixin):
    """
    Token-based authentication middleware

    Supports two authentication methods:
    1. x-token (header or GET param) — long-lived user session token
    2. preview_token (GET param) — short-lived, file-scoped preview token

    For preview endpoints, preview_token takes precedence over x-token.
    """

    def _resolve_access_token(self, request):
        """根据请求路径和方法决定 access_token 来源

        预览端点 GET 请求：
        - 禁止 URL 中的 x-token（安全风险）
        - 仅允许 header 中的 x-token
        其他请求：
        - header 或 GET 参数中的 x-token 均可

        Returns:
            tuple: (access_token 或 None, 错误响应或 None)
        """
        # 【H-5修复】预览/文本内容端点禁止 GET 参数中的 x-token
        if request.method == 'GET' and self._is_preview_endpoint(request.path):
            if request.GET.get('x-token'):
                logger.warning(
                    f'[AUTH] 拒绝预览端点 URL 中的 x-token: {request.path}'
                )
                response = json_response(error='预览端点禁止在 URL 中使用 x-token，请使用 preview_token 或 header')
                response.status_code = 401
                return None, response
            # 预览端点 GET 不允许从 URL 读 x-token，仅允许从 header 读
            return request.headers.get('x-token'), None

        # 常规 x-token 认证
        return request.headers.get('x-token') or request.GET.get('x-token'), None

    def _authenticate_x_token(self, access_token, request):
        """通过 x-token 认证用户

        Returns:
            User|None: 认证成功返回用户对象，失败返回 None
        """
        if not access_token or len(access_token) != 32:
            return None

        x_real_ip = get_request_real_ip(request.headers)
        user = User.objects.filter(access_token=access_token).first()

        if not user or user.token_expired < time.time() or not user.is_active:
            if user:
                logger.debug(f'[AUTH] Token expired for user {user.username}')
            return None

        # IP 绑定校验
        ip_check_excludes = getattr(settings, 'IP_CHECK_EXCLUDES', ())
        if (x_real_ip == user.last_ip
                or AppSetting.get_default('bind_ip') is False
                or request.path in ip_check_excludes):
            request.user = user
            user.token_expired = time.time() + settings.TOKEN_TTL
            user.save()
            return user

        logger.warning(f'[AUTH] IP mismatch for user {user.username}: '
                       f'expected={user.last_ip}, got={x_real_ip}')
        return None

    def process_request(self, request):
        if request.path in settings.AUTHENTICATION_EXCLUDES:
            return None
        if any(x.match(request.path) for x in settings.AUTHENTICATION_EXCLUDES if hasattr(x, 'match')):
            return None

        # 【H-2修复】预览端点优先使用 preview_token 认证
        preview_token = request.GET.get('preview_token')
        if preview_token and self._is_preview_endpoint(request.path):
            user = self._authenticate_preview_token(preview_token, request)
            if user:
                return None
            # preview_token 无效时，回退到 x-token（向后兼容）

        # 解析 access_token（含预览端点安全限制）
        access_token, error_response = self._resolve_access_token(request)
        if error_response:
            return error_response

        logger.debug(f'[AUTH] Request: {request.method} {request.path}')

        # x-token 认证
        user = self._authenticate_x_token(access_token, request)
        if user:
            return None

        logger.debug(f'[AUTH] Authentication failed for {request.path}')
        response = json_response(error="验证失败，请重新登录")
        response.status_code = 401
        return response

    @staticmethod
    def _is_preview_endpoint(path):
        """判断是否为预览端点（preview_token 适用路径）"""
        return any(path.startswith(prefix) for prefix in PREVIEW_ENDPOINT_PREFIXES)

    @staticmethod
    def _authenticate_preview_token(token, request):
        """
        通过 preview_token 认证用户

        验证流程：
        1. 解析并验证 preview_token 签名和时效
        2. 根据 token 中的 user_id 查找用户
        3. 设置 request.user 和 request.preview_token_data

        Returns:
            User | None: 认证成功返回用户对象，失败返回 None
        """
        from apps.document.libs.preview_token import validate_preview_token

        token_data = validate_preview_token(token)
        if not token_data:
            logger.warning(f'[AUTH] Invalid preview_token for {request.path}')
            return None

        user = User.objects.filter(id=token_data['user_id'], is_active=True).first()
        if not user:
            logger.warning(f'[AUTH] Preview token user not found: user_id={token_data["user_id"]}')
            return None

        # 设置 request 属性，供视图层校验文件 ID 匹配
        request.user = user
        request.preview_token_data = token_data
        logger.debug(f'[AUTH] Preview token auth success: user={user.username}, file_id={token_data["file_id"]}')
        return user

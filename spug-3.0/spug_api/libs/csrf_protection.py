"""
CSRF-like protection for custom token authentication.
Validates Origin/Referer headers for state-changing requests.
"""
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from .utils import json_response
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Paths that skip origin check (internal service calls)
ORIGIN_CHECK_EXCLUDES = (
    '/document/preview/',
    '/document/health/',
    '/api/document/health/',
)


class OriginCheckMiddleware(MiddlewareMixin):
    """
    Verify Origin/Referer header for state-changing requests.
    Prevents cross-origin request forgery when using token auth.
    """

    def _normalize_origin_values(self, value):
        parsed = urlparse(value)
        netloc = parsed.netloc or parsed.path
        host_without_port = netloc.split(':')[0]
        return {value, netloc, host_without_port}

    def _is_safe_origin(self, origin, host, allowed_origins):
        """Check if origin/host is in allowed list."""
        parsed = urlparse(origin)
        check_host = parsed.netloc or parsed.path
        # 去掉端口进行比较，解决非默认端口访问时 Origin 带端口但 Host 不带端口的问题
        check_host_without_port = check_host.split(':')[0]
        host_without_port = host.split(':')[0]
        allowed_values = set()
        for allowed_origin in allowed_origins:
            allowed_values.update(self._normalize_origin_values(allowed_origin))
        return (
            check_host == host
            or check_host_without_port == host_without_port
            or check_host in allowed_values
            or check_host_without_port in allowed_values
            or origin in allowed_values
        )

    def _validate_request_origin(self, request):
        """Validate Origin or Referer header. Returns True if allowed."""
        origin = request.headers.get('Origin', '')
        referer = request.headers.get('Referer', '')

        if not origin and not referer:
            # 【M-3修复】缺失两个头时仍放行（当前使用 x-token Header 认证，
            # 浏览器跨站表单无法携带该头，CSRF 风险较低），
            # 但在生产环境记录警告，便于审计和未来迁移到 Cookie 认证时收紧策略
            if not settings.DEBUG:
                logger.warning(
                    f'[CSRF] State-changing request without Origin/Referer: '
                    f'method={request.method}, path={request.path}'
                )
            return True

        host = request.get_host()
        allowed_origins = getattr(settings, 'ALLOWED_ORIGINS', [])

        if origin:
            return self._is_safe_origin(origin, host, allowed_origins)
        elif referer:
            return self._is_safe_origin(referer, host, allowed_origins)
        return True

    def process_request(self, request):
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return None

        for path in ORIGIN_CHECK_EXCLUDES:
            if request.path.startswith(path):
                return None

        if not hasattr(request, 'user') or not request.user:
            return None

        if self._validate_request_origin(request):
            return None

        if settings.DEBUG:
            origin = request.headers.get('Origin') or request.headers.get('Referer', '')
            logger.warning(f'[CSRF] Origin mismatch: origin={origin}, host={request.get_host()}')
            return None

        origin = request.headers.get('Origin') or request.headers.get('Referer', '')
        logger.warning(f'[CSRF] Blocked request from {origin} to {request.path}')
        return json_response(error='请求来源不合法')

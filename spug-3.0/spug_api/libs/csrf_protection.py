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

    def _is_safe_origin(self, origin, host, allowed_origins):
        """Check if origin/host is in allowed list."""
        parsed = urlparse(origin)
        check_host = parsed.netloc or parsed.path
        return check_host == host or check_host in allowed_origins

    def _validate_request_origin(self, request):
        """Validate Origin or Referer header. Returns True if allowed."""
        origin = request.headers.get('Origin', '')
        referer = request.headers.get('Referer', '')

        if not origin and not referer:
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

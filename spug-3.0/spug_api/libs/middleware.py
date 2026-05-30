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
    """

    def process_request(self, request):
        if request.path in settings.AUTHENTICATION_EXCLUDES:
            return None
        if any(x.match(request.path) for x in settings.AUTHENTICATION_EXCLUDES if hasattr(x, 'match')):
            return None

        access_token = request.headers.get('x-token') or request.GET.get('x-token')
        logger.debug(f'[AUTH] Request: {request.method} {request.path}')

        if access_token and len(access_token) == 32:
            x_real_ip = get_request_real_ip(request.headers)
            user = User.objects.filter(access_token=access_token).first()

            if user and user.token_expired >= time.time() and user.is_active:
                ip_check_excludes = getattr(settings, 'IP_CHECK_EXCLUDES', ())
                if (x_real_ip == user.last_ip
                        or AppSetting.get_default('bind_ip') is False
                        or request.path in ip_check_excludes):
                    request.user = user
                    user.token_expired = time.time() + settings.TOKEN_TTL
                    user.save()
                    return None
                else:
                    logger.warning(f'[AUTH] IP mismatch for user {user.username}: '
                                   f'expected={user.last_ip}, got={x_real_ip}')
            else:
                if user:
                    logger.debug(f'[AUTH] Token expired for user {user.username}')

        logger.debug(f'[AUTH] Authentication failed for {request.path}')
        response = json_response(error="验证失败，请重新登录")
        response.status_code = 401
        return response

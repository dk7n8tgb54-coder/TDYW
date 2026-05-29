# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from .utils import json_response, get_request_real_ip
from apps.account.models import User
from apps.setting.utils import AppSetting
import traceback
import time


class HandleExceptionMiddleware(MiddlewareMixin):
    """
    处理试图函数异常
    """

    def process_exception(self, request, exception):
        traceback.print_exc()
        return json_response(error='Exception: %s' % exception)


class AuthenticationMiddleware(MiddlewareMixin):
    """
    登录验证
    """

    def process_request(self, request):
        if request.path in settings.AUTHENTICATION_EXCLUDES:
            return None
        if any(x.match(request.path) for x in settings.AUTHENTICATION_EXCLUDES if hasattr(x, 'match')):
            return None
        access_token = request.headers.get('x-token') or request.GET.get('x-token')
        print(f'[AUTH] Request path: {request.path}, token: {access_token}')
        if access_token and len(access_token) == 32:
            x_real_ip = get_request_real_ip(request.headers)
            user = User.objects.filter(access_token=access_token).first()
            print(f'[AUTH] User found: {user}, is_active: {user.is_active if user else None}')
            if user and user.token_expired >= time.time() and user.is_active:
                print(f'[AUTH] Token valid, IP check: x_real_ip={x_real_ip}, user.last_ip={user.last_ip}')
                # IP绑定检查：支持跳过IP校验的端点列表
                # 文件预览端点需跳过IP检查，因为kkFileView从Docker内网发起下载请求，
                # 其源IP与用户浏览器IP不同，但token仍有效
                ip_check_excludes = getattr(settings, 'IP_CHECK_EXCLUDES', ())
                if x_real_ip == user.last_ip or AppSetting.get_default('bind_ip') is False or request.path in ip_check_excludes:
                    print(f'[AUTH] Setting request.user, is_supper: {user.is_supper}')
                    request.user = user
                    user.token_expired = time.time() + settings.TOKEN_TTL
                    user.save()
                    return None
                else:
                    print(f'[AUTH] IP mismatch')
            else:
                print(f'[AUTH] Token invalid: token_expired={user.token_expired if user else None}, current_time={time.time()}')
        print(f'[AUTH] Authentication failed')
        response = json_response(error="验证失败，请重新登录")
        response.status_code = 401
        return response

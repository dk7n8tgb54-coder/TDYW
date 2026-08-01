# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import django
from django.core.cache import cache
from django.conf import settings
from libs import JsonParser, Argument, json_response, auth
from libs.utils import generate_random_str
from libs.mail import Mail
from libs.mixins import AdminView
from libs.push import send_login_code
from apps.setting.utils import AppSetting
from apps.setting.models import Setting, KEYS_DEFAULT
from apps.logs.audit import record_audit_event
from copy import deepcopy
import platform

# R13/R17: 需脱敏的敏感配置项
_SENSITIVE_KEYS = {'spug_key', 'api_key'}
_SENSITIVE_SUBFIELDS = {'password', 'token', 'secret', 'key', 'credential'}


def _mask_sensitive_settings(data):
    """脱敏敏感配置项，避免明文返回密码/密钥"""
    result = deepcopy(data)
    for key in _SENSITIVE_KEYS:
        if result.get(key) is not None:
            result[key] = '***'
    mail = result.get('mail_service')
    if isinstance(mail, dict):
        for sub in list(mail.keys()):
            if any(s in sub.lower() for s in _SENSITIVE_SUBFIELDS):
                mail[sub] = '***'
    return result


class SettingView(AdminView):
    def get(self, request):
        response = deepcopy(KEYS_DEFAULT)
        for item in Setting.objects.all():
            response[item.key] = item.real_val
        # R13/R17 修复：脱敏敏感配置后再返回
        return json_response(_mask_sensitive_settings(response))

    def post(self, request):
        form, error = JsonParser(
            Argument('data', type=list, help='缺少必要的参数')
        ).parse(request.body)
        if error is None:
            from django.db import transaction
            # R8 修复：记录变更前值
            before_values = {}
            for item in form.data:
                key = item.get('key')
                if key:
                    before_values[key] = AppSetting.get_default(key)
            with transaction.atomic():
                for item in form.data:
                    AppSetting.set(**item)
            # R8 修复：显式审计日志（含变更前后值）
            record_audit_event(
                request=request,
                action='update',
                target_type='setting',
                target_name='系统设置',
                detail={'changed_keys': [item.get('key') for item in form.data]},
                before_value=before_values,
            )
        return json_response(error=error)


class MFAView(AdminView):
    def get(self, request):
        if not request.user.wx_token:
            return json_response(
                error='检测到当前账户未配置推送标识（账户管理/编辑），请配置后再尝试启用MFA认证，否则可能造成系统无法正常登录。')
        spug_push_key = AppSetting.get_default('spug_push_key')
        if not spug_push_key:
            return json_response(error='检测到当前账户未绑定推送服务，请在系统设置/推送服务设置中绑定推送助手账户。')
        code = generate_random_str(6)
        send_login_code(spug_push_key, request.user.wx_token, code)
        cache.set(f'{request.user.username}:code', code, 300)
        # R15/R18 修复：重置失败计数器
        cache.delete(f'{request.user.username}:code:fail_count')
        return json_response()

    def post(self, request):
        form, error = JsonParser(
            Argument('enable', type=bool, help='参数错误'),
            Argument('code', required=False)
        ).parse(request.body)
        if error is None:
            # R15/R18 修复：检查是否被锁定
            lock_key = f'{request.user.username}:code:lockout'
            if cache.get(lock_key):
                return json_response(error='验证码错误次数过多，请 5 分钟后再试')

            if form.enable:
                if not form.code:
                    return json_response(error='请输入验证码')
                key = f'{request.user.username}:code'
                code = cache.get(key)
                if not code:
                    # R15/R18 修复：验证码失效时也递增失败计数器
                    fail_key = f'{request.user.username}:code:fail_count'
                    fail_count = cache.get(fail_key, 0) + 1
                    cache.set(fail_key, fail_count, 300)
                    if fail_count >= 5:
                        cache.set(lock_key, True, 300)
                        return json_response(error='验证码错误次数过多，已锁定 5 分钟')
                    return json_response(error='验证码已失效，请重新获取')
                if code != form.code:
                    ttl = cache.ttl(key)
                    cache.expire(key, ttl - 100)
                    # R15/R18 修复：递增失败计数器，5 次后锁定 5 分钟
                    fail_key = f'{request.user.username}:code:fail_count'
                    fail_count = cache.get(fail_key, 0) + 1
                    cache.set(fail_key, fail_count, 300)
                    if fail_count >= 5:
                        cache.set(lock_key, True, 300)  # 锁定 5 分钟
                        cache.delete(key)  # 清除验证码
                        return json_response(error='验证码错误次数过多，已锁定 5 分钟')
                    return json_response(error=f'验证码错误，还剩 {5 - fail_count} 次机会')
                # R3 修复：不在此处删除验证码，等 AppSetting.set 成功后再删
            # 先写入配置（若失败则验证码未被消费）
            AppSetting.set('MFA', {'enable': form.enable})
            # R3 修复：配置写入成功后才消费验证码
            if form.enable:
                cache.delete(f'{request.user.username}:code')
                cache.delete(f'{request.user.username}:code:fail_count')
            # R9 修复：MFA 启用/禁用显式审计
            record_audit_event(
                request=request,
                action='update',
                target_type='setting',
                target_name='MFA多因素认证',
                detail={'enable': form.enable},
            )
        return json_response(error=error)





@auth('admin')
def email_test(request):
    form, error = JsonParser(
        Argument('server', help='请输入邮件服务地址'),
        Argument('port', type=int, help='请输入邮件服务端口号'),
        Argument('username', help='请输入邮箱账号'),
        Argument('password', help='请输入密码/授权码'),
    ).parse(request.body)
    if error is None:
        try:
            mail = Mail(**form)
            server = mail.get_server()
            server.quit()
            return json_response()
        except Exception as e:
            error = f'{e}'
    return json_response(error=error)


@auth('admin')
def get_about(request):
    return json_response({
        'python_version': platform.python_version(),
        'system_version': platform.platform(),
        'spug_version': settings.SPUG_VERSION,
        'django_version': django.get_version()
    })




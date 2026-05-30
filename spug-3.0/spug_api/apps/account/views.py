# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import re

from django.core.cache import cache
from django.conf import settings
from django.db.models import Count
from libs.mixins import AdminView, View
from libs import JsonParser, Argument, human_datetime, json_response
from libs.utils import get_request_real_ip, generate_random_str
from libs.tenant_utils import migrate_existing_data
import logging
from apps.account.models import User, Role, History, Tenant
from apps.setting.utils import AppSetting
from apps.account.utils import verify_password

from functools import partial
import user_agents
import ipaddress
import time
import uuid
import json
from apps.logs.audit import save_audit_log

logger = logging.getLogger(__name__)

# 租户ID合法性正则
TENANT_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_\-]{1,50}$')


def validate_tenant_id(tenant_id):
    """校验租户ID格式合法性"""
    if tenant_id and not TENANT_ID_PATTERN.match(tenant_id):
        return '租户ID仅支持字母、数字、下划线、横线，长度1-50'
    return None


class UserView(AdminView):
    # 用户管理细粒度权限：HTTP方法 → 需要的权限
    PERM_MAP = {
        'GET': 'system.account.view',
        'POST': 'system.account.add',
        'PATCH': 'system.account.edit',
        'DELETE': 'system.account.del',
    }

    def get(self, request):
        show_deleted = request.GET.get('show_deleted') == 'true'
        if show_deleted:
            queryset = User.objects.filter(deleted_by_id__isnull=False)
        else:
            queryset = User.objects.filter(deleted_by_id__isnull=True)
        # 非超管只能查看本租户用户
        if not request.user.is_supper:
            queryset = queryset.filter(tenant_id=request.user.tenant_id)
        users = []
        for u in queryset:
            tmp = u.to_dict(excludes=('access_token', 'password_hash'))
            tmp['role_ids'] = [x.id for x in u.roles.all()]
            tmp['password'] = '******'
            users.append(tmp)
        return json_response(users)

    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('username', help='请输入登录名'),
            Argument('password', help='请输入密码'),
            Argument('nickname', help='请输入姓名'),
            Argument('role_ids', type=list, default=[]),
            Argument('wx_token', required=False),
            Argument('tenant_id', required=False, default=None),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        error = self._check_duplicate_username(form)
        if error:
            return json_response(error=error)

        role_ids, password = form.pop('role_ids'), form.pop('password')
        if form.id:
            return self._handle_user_edit(request, form, role_ids, password)
        else:
            return self._handle_user_create(request, form, role_ids, password)

    def _check_duplicate_username(self, form):
        # 仅检查未删除的用户，已删除用户允许同名重建
        user = User.objects.filter(username=form.username, deleted_by_id__isnull=True).first()
        if user:
            if form.id and form.id == user.id:
                return None
            return f'已存在登录名为【{form.username}】的用户，无法重复创建'
        return None

    def _handle_user_edit(self, request, form, role_ids, password):
        user = User.objects.get(pk=form.id)
        if not request.user.is_supper and user.tenant_id != request.user.tenant_id:
            return json_response(error='无权编辑其他租户的用户')
        if not request.user.is_supper and 'tenant_id' in form:
            del form['tenant_id']
        if (request.user.is_supper and form.get('tenant_id')
                and form['tenant_id'] != user.tenant_id):
            self._migrate_user_tenant(user, form['tenant_id'])
        user.update_by_dict(form)
        user.roles.set(role_ids)
        user.set_perms_cache()
        return json_response()

    def _handle_user_create(self, request, form, role_ids, password):
        if not verify_password(password):
            return json_response(error='请设置至少8位包含数字、小写和大写字母、特殊字符的新密码')
        tenant_value, err = self._resolve_tenant_id(request, form)
        if err:
            return json_response(error=err)
        create_fields = {k: v for k, v in form.items()
                         if k not in ('tenant_id', 'password', 'role_ids')}
        user = User.objects.create(
            password_hash=User.make_password(password),
            created_by=request.user,
            tenant_id=tenant_value,
            **create_fields
        )
        user.roles.set(role_ids)
        user.set_perms_cache()
        return json_response()

    def _resolve_tenant_id(self, request, form):
        if request.user.is_supper:
            tenant_value = form.tenant_id or form.username
            err = validate_tenant_id(tenant_value)
            if err:
                return None, err
            return tenant_value, None
        return request.user.tenant_id, None

    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('password', required=False),
            Argument('is_active', type=bool, required=False),
            Argument('tenant_id', required=False),
        ).parse(request.body)
        if error is None:
            user = User.objects.get(pk=form.id)
            # 非超管只能操作本租户用户
            if not request.user.is_supper and user.tenant_id != request.user.tenant_id:
                return json_response(error='无权操作其他租户的用户')
            # 非超管禁止修改 tenant_id
            if not request.user.is_supper and form.tenant_id:
                return json_response(error='无权修改用户租户')
            # 超管修改 tenant_id 时，同步迁移历史数据+清理缓存
            if (request.user.is_supper and form.tenant_id
                    and form.tenant_id != user.tenant_id):
                self._migrate_user_tenant(user, form.tenant_id)
                user.tenant_id = form.tenant_id
            if form.password:
                if not verify_password(form.password):
                    return json_response(error='请设置至少8位包含数字、小写和大写字母、特殊字符的新密码')
                user.token_expired = 0
                user.password_hash = User.make_password(form.pop('password'))
            if form.is_active is not None:
                user.is_active = form.is_active
                cache.delete(user.username)
            user.save()
        return json_response(error=error)

    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            user = User.objects.filter(pk=form.id).first()
            if user:
                # 非超管只能删除本租户用户
                if not request.user.is_supper and user.tenant_id != request.user.tenant_id:
                    return json_response(error='无权操作其他租户的用户')
                if user.id == request.user.id:
                    return json_response(error='无法删除当前登录账户')
                # 执行软删除
                user.is_active = False
                user.deleted_at = human_datetime()
                user.deleted_by = request.user
                user.roles.clear()
                user.save()
        return json_response(error=error)

    @staticmethod
    def get_tenant_choices(request):
        """获取所有已启用的租户列表（供前端下拉选择，仅超管可用）"""
        if not request.user.is_supper:
            return json_response(error='权限拒绝')
        from django.db.models import Count
        tenants = Tenant.objects.filter(is_active=True).order_by('id')
        result = []
        for t in tenants:
            user_count = User.objects.filter(
                tenant_id=t.id,
                deleted_by_id__isnull=True
            ).count()
            result.append({
                'id': t.id,
                'name': t.name,
                'user_count': user_count,
            })
        return json_response(result)

    @staticmethod
    def restore_user(request):
        """恢复已删除的用户"""
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.body)
        if error:
            return json_response(error=error)
        user = User.objects.filter(pk=form.id).first()
        if not user:
            return json_response(error='用户不存在')
        if not user.deleted_by:
            return json_response(error='该用户未被删除')
        # 非超管只能恢复本租户用户
        if not request.user.is_supper and user.tenant_id != request.user.tenant_id:
            return json_response(error='无权操作其他租户的用户')
        # 检查是否有未删除的同名用户
        if User.objects.filter(username=user.username, deleted_by_id__isnull=True).exists():
            return json_response(error=f'已存在登录名为【{user.username}】的用户，无法恢复')
        user.is_active = True
        user.deleted_at = None
        user.deleted_by = None
        user.save()
        return json_response()

    @staticmethod
    def _migrate_user_tenant(user, new_tenant_id):
        """超管修改用户租户时，迁移历史数据+清理缓存"""
        old_tenant_id = user.tenant_id
        migrate_existing_data({user.username: new_tenant_id})
        # 清理排班缓存：同时清理新旧租户
        try:
            from apps.schedule.cache_utils import invalidate_schedule_cache
            if old_tenant_id:
                invalidate_schedule_cache(tenant_id=old_tenant_id)
            invalidate_schedule_cache(tenant_id=new_tenant_id)
        except ImportError:
            pass


class RoleView(AdminView):
    PERM_MAP = {
        'GET': 'system.account.view',
        'POST': 'system.account.edit',
        'PATCH': 'system.account.edit',
        'DELETE': 'system.account.del',
    }

    def get(self, request):
        roles = Role.objects.all()
        return json_response(roles)

    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', help='请输入角色名称'),
            Argument('desc', required=False),
            Argument('is_global_admin', type=bool, default=False)
        ).parse(request.body)
        if error is None:
            if form.id:
                Role.objects.filter(pk=form.id).update(**form)
            else:
                Role.objects.create(created_by=request.user, **form)
        return json_response(error=error)

    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('page_perms', type=dict, required=False),
            Argument('deploy_perms', type=dict, required=False),
            Argument('group_perms', type=list, required=False)
        ).parse(request.body)
        if error is None:
            role = Role.objects.filter(pk=form.pop('id')).first()
            if not role:
                return json_response(error='未找到指定角色')
            if form.page_perms is not None:
                role.page_perms = json.dumps(form.page_perms)
                role.clear_perms_cache()
            if form.deploy_perms is not None:
                role.deploy_perms = json.dumps(form.deploy_perms)
            if form.group_perms is not None:
                role.group_perms = json.dumps(form.group_perms)
            role.user_set.update(token_expired=0)
            role.save()
        return json_response(error=error)

    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误')
        ).parse(request.GET)
        if error is None:
            role = Role.objects.get(pk=form.id)
            if role.user_set.exists():
                return json_response(error='已有用户使用了该角色，请解除关联后再尝试删除')
            role.delete()
        return json_response(error=error)


class TenantView(AdminView):
    """租户管理"""
    PERM_MAP = {
        'GET': 'system.tenant.view',
        'POST': 'system.tenant.add',
        'PATCH': 'system.tenant.edit',
        'DELETE': 'system.tenant.del',
    }

    def get(self, request):
        tenants = Tenant.objects.all().order_by('id')
        return json_response(tenants)

    def post(self, request):
        form, error = JsonParser(
            Argument('id', help='请输入租户标识'),
            Argument('name', help='请输入租户名称'),
            Argument('description', required=False),
        ).parse(request.body)
        if error is None:
            err = validate_tenant_id(form.id)
            if err:
                return json_response(error=err)
            if Tenant.objects.filter(pk=form.id).exists():
                return json_response(error='租户标识已存在')
            Tenant.objects.create(
                id=form.id,
                name=form.name,
                description=form.description or '',
                created_by=request.user,
            )
        return json_response(error=error)

    def patch(self, request):
        form, error = JsonParser(
            Argument('id', help='请指定操作对象'),
            Argument('name', required=False),
            Argument('description', required=False),
            Argument('is_active', type=bool, required=False),
        ).parse(request.body)
        if error is None:
            tenant = Tenant.objects.filter(pk=form.pop('id')).first()
            if not tenant:
                return json_response(error='租户不存在')
            tenant.update_by_dict(form)
        return json_response(error=error)

    def delete(self, request):
        form, error = JsonParser(
            Argument('id', help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            tenant = Tenant.objects.filter(pk=form.id).first()
            if not tenant:
                return json_response(error='租户不存在')
            if User.objects.filter(tenant_id=form.id).exists():
                return json_response(error='该租户下存在用户，无法删除')
            tenant.delete()
        return json_response(error=error)


class SelfView(View):
    def get(self, request):
        data = request.user.to_dict(selects=('nickname', 'wx_token'))
        return json_response(data)

    def patch(self, request):
        form, error = JsonParser(
            Argument('old_password', required=False),
            Argument('new_password', required=False),
            Argument('nickname', required=False, help='请输入昵称'),
            Argument('wx_token', required=False),
        ).parse(request.body)
        if error is None:
            if form.old_password and form.new_password:
                if not verify_password(form.new_password):
                    return json_response(error='请设置至少8位包含数字、小写和大写字母、特殊字符的新密码')

                if request.user.verify_password(form.old_password):
                    request.user.password_hash = User.make_password(form.new_password)
                    request.user.token_expired = 0
                    request.user.save()
                    return json_response()
                else:
                    return json_response(error='原密码错误，请重新输入')
            if form.nickname is not None:
                request.user.nickname = form.nickname
            if form.wx_token is not None:
                request.user.wx_token = form.wx_token
            request.user.save()
        return json_response(error=error)


def login(request):
    form, error = JsonParser(
        Argument('username', help='请输入用户名'),
        Argument('password', help='请输入密码'),
        Argument('captcha', required=False),
        Argument('type', required=False)
    ).parse(request.body)
    if error is None:
        login_type = form.type or 'default'
        handle_response = partial(handle_login_record, request, form.username, login_type)
        x_real_ip = get_request_real_ip(request.headers)

        # IP级别限流：防止分布式暴力破解（30次/小时/IP）
        ip_key = f'login_fail:ip:{x_real_ip}'
        ip_fails = cache.get(ip_key, 0)
        if ip_fails >= 30:
            return handle_response(error='登录尝试过于频繁，请稍后再试')

        # 用户级别限流：防止针对性攻击（5次/15分钟/用户）
        user_key = f'login_fail:user:{form.username}'
        user_fails = cache.get(user_key, 0)
        if user_fails >= 5:
            ttl = cache.ttl(user_key) or 900
            minutes = max(1, ttl // 60)
            return handle_response(error=f'账户已临时锁定，请{minutes}分钟后重试')

        user = User.objects.filter(
            username=form.username, type=login_type, deleted_by_id__isnull=True
        ).first()

        if user and not user.is_active:
            return handle_response(error="账户已被系统禁用")

        if user and user.deleted_by is None:
            if user.verify_password(form.password):
                # 登录成功 - 清除失败计数
                cache.delete(user_key)
                return handle_user_info(handle_response, request, user, form.captcha)

        # 登录失败 - 递增计数器
        cache.set(ip_key, ip_fails + 1, 3600)       # IP: 1小时窗口
        cache.set(user_key, user_fails + 1, 900)    # 用户: 15分钟窗口

        remaining = 5 - user_fails - 1
        if remaining > 0:
            return handle_response(
                error=f"用户名或密码错误，还剩{remaining}次尝试机会"
            )
        else:
            return handle_response(error='账户已临时锁定，请15分钟后重试')

    return json_response(error=error)


def handle_login_record(request, username, login_type, error=None):
    x_real_ip = get_request_real_ip(request.headers)
    user_agent = user_agents.parse(request.headers.get('User-Agent'))
    History.objects.create(
        username=username,
        type=login_type,
        ip=x_real_ip,
        agent=user_agent,
        is_success=False if error else True,
        message=error
    )
    # 记录登录失败审计日志
    if error:
        # 尝试获取用户ID（登录失败时可能没有）
        user = User.objects.filter(username=username, type=login_type, deleted_by_id__isnull=True).first()
        save_audit_log(
            user_id=user.id if user else 0,
            username=username,
            action='login',
            target_type='auth',
            target_name='登录失败',
            detail=error,
            ip=x_real_ip,
            is_success=False,
            tenant_id=getattr(user, 'tenant_id', 'default') if user else 'default',
        )
        return json_response(error=error)


def handle_user_info(handle_response, request, user, captcha):
    cache.delete(user.username)
    key = f'{user.username}:code'
    if captcha:
        code = cache.get(key)
        if not code:
            return handle_response(error='验证码已失效，请重新获取')
        if code != captcha:
            ttl = cache.ttl(key)
            cache.expire(key, ttl - 100)
            return handle_response(error='验证码错误')
        cache.delete(key)
    else:
        mfa = AppSetting.get_default('MFA', {'enable': False})
        if mfa['enable']:
            if not user.wx_token:
                return handle_response(error='已启用登录双重认证，但您的账户未配置推送标识，请联系管理员')
            return handle_response(error='推送服务已移除，MFA认证不可用')

    handle_response()
    x_real_ip = get_request_real_ip(request.headers)
    # SECURITY: Always generate new token on login to prevent session fixation
    user.access_token = uuid.uuid4().hex
    user.token_expired = time.time() + settings.TOKEN_TTL
    user.last_login = human_datetime()
    user.last_ip = x_real_ip
    user.save()
    # 记录登录审计日志
    save_audit_log(
        user_id=user.id,
        username=user.username,
        action='login',
        target_type='auth',
        target_name='登录系统',
        ip=x_real_ip,
        is_success=True,
        tenant_id=getattr(user, 'tenant_id', 'default'),
    )
    verify_ip = AppSetting.get_default('verify_ip', True)
    return json_response({
        'id': user.id,
        'access_token': user.access_token,
        'nickname': user.nickname,
        'is_supper': user.is_supper,
        'tenant_id': user.tenant_id,
        'has_real_ip': x_real_ip and ipaddress.ip_address(x_real_ip).is_global if verify_ip else True,
        'permissions': [] if user.is_supper else list(user.page_perms)
    })


def logout(request):
    # 记录登出审计日志
    user = request.user
    ip = get_request_real_ip(request.headers) if hasattr(request, 'headers') else ''
    save_audit_log(
        user_id=user.id,
        username=user.username,
        action='logout',
        target_type='auth',
        target_name='退出系统',
        ip=ip,
        is_success=True,
        tenant_id=getattr(user, 'tenant_id', 'default'),
    )
    request.user.token_expired = 0
    request.user.save()
    return json_response()

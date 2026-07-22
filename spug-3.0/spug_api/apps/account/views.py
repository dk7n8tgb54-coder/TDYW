# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import re

from django.core.cache import cache
from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from libs.mixins import AdminView, View
from libs import JsonParser, Argument, json_response
from libs.utils import get_request_real_ip, generate_random_str
from libs.tenant_utils import migrate_existing_data
import logging
from apps.account.models import User, Role, History, Tenant
from apps.setting.utils import AppSetting
from apps.account.utils import verify_password
from apps.account.role_permissions import (
    get_assignable_roles,
    get_assignable_roles_for_target,
    get_manageable_role,
    validate_assignable_role_ids,
    validate_page_perms_subset,
    validate_group_perms_subset,
    validate_deploy_perms_subset,
)

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
        users = list(queryset)
        # 超管批量附加账号签名状态（避免列表逐行查询 N+1）
        sig_status_map = {}
        if request.user.is_supper:
            from apps.signature.services import get_account_signature_status_map
            sig_status_map = get_account_signature_status_map([u.id for u in users])
        data = []
        for u in users:
            tmp = u.to_dict(excludes=('access_token', 'password_hash'))
            tmp['role_ids'] = [x.id for x in u.roles.all()]
            tmp['password'] = '******'
            if request.user.is_supper:
                sig = sig_status_map.get(u.id)
                if sig:
                    tmp['signature_status'] = sig['status']
                    tmp['signature_version'] = sig['version']
                else:
                    tmp['signature_status'] = 'none'
                    tmp['signature_version'] = None
            data.append(tmp)
        return json_response(data)

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
        try:
            user = User.objects.get(pk=form.id)
        except User.DoesNotExist:
            logger.error(f'Account: User {form.id} not found for edit')
            return json_response(error='用户不存在')
        if not request.user.is_supper and user.tenant_id != request.user.tenant_id:
            logger.warning(f'Account: User {request.user.username} denied to edit user {user.username} (cross-tenant)')
            return json_response(error='无权编辑其他租户的用户')
        # 普通管理员不能编辑超级管理员账号
        if not request.user.is_supper and user.is_supper:
            logger.warning(f'Account: User {request.user.username} denied to edit super user {user.username}')
            return json_response(error='无权编辑超级管理员账号')
        if not request.user.is_supper and 'tenant_id' in form:
            del form['tenant_id']
        # 计算编辑后的目标 tenant_id，用于校验 role_ids 与目标租户一致性
        # 超管可同时修改 tenant_id 和 role_ids，必须按新 tenant_id 校验
        if request.user.is_supper and form.get('tenant_id'):
            target_tenant_id = form['tenant_id']
        else:
            target_tenant_id = user.tenant_id
        # 先校验 role_ids（含存在性 + 越权 + 租户一致性），
        # 校验通过后再执行迁移租户、更新用户、设置角色，避免中途失败造成状态不一致
        error = validate_assignable_role_ids(request.user, role_ids, target_tenant_id)
        if error:
            logger.warning(
                f'Account: User {request.user.username} denied to assign roles {role_ids} '
                f'to user {user.username} (target_tenant={target_tenant_id}): {error}'
            )
            return json_response(error=error)
        with transaction.atomic():
            if (request.user.is_supper and form.get('tenant_id')
                    and form['tenant_id'] != user.tenant_id):
                self._migrate_user_tenant(user, form['tenant_id'])
            # 过滤 None：JsonParser 对未传字段填 None，update_by_dict 会覆盖 NOT NULL 字段
            update_data = {k: v for k, v in form.items() if v is not None}
            user.update_by_dict(update_data)
            user.roles.set(role_ids)
            user.set_perms_cache()
        return json_response()

    def _handle_user_create(self, request, form, role_ids, password):
        if not verify_password(password):
            logger.warning(f'Account: Password validation failed for new user creation by {request.user.username}')
            return json_response(error='请设置至少8位包含数字、小写和大写字母、特殊字符的新密码')
        # 先解析目标租户，用于校验 role_ids 与目标租户一致性
        tenant_value, err = self._resolve_tenant_id(request, form)
        if err:
            return json_response(error=err)
        # 在创建用户前校验 role_ids，避免先创建用户再失败
        error = validate_assignable_role_ids(request.user, role_ids, tenant_value)
        if error:
            logger.warning(
                f'Account: User {request.user.username} denied to assign roles {role_ids} '
                f'on new user creation (target_tenant={tenant_value}): {error}'
            )
            return json_response(error=error)
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
            try:
                user = User.objects.get(pk=form.id)
            except User.DoesNotExist:
                logger.error(f'Account: User {form.id} not found for patch')
                return json_response(error='用户不存在')
            # 非超管只能操作本租户用户
            if not request.user.is_supper and user.tenant_id != request.user.tenant_id:
                logger.warning(f'Account: User {request.user.username} denied to patch user {user.username} (cross-tenant)')
                return json_response(error='无权操作其他租户的用户')
            # 普通管理员不能操作超级管理员账号（重置密码、禁用等）
            if not request.user.is_supper and user.is_supper:
                logger.warning(f'Account: User {request.user.username} denied to patch super user {user.username}')
                return json_response(error='无权操作超级管理员账号')
            # 非超管禁止修改 tenant_id
            if not request.user.is_supper and form.tenant_id:
                logger.warning(f'Account: User {request.user.username} denied to modify tenant_id')
                return json_response(error='无权修改用户租户')
            # 超管修改 tenant_id 时，同步迁移历史数据+清理缓存
            if (request.user.is_supper and form.tenant_id
                    and form.tenant_id != user.tenant_id):
                self._migrate_user_tenant(user, form.tenant_id)
                user.tenant_id = form.tenant_id
            if form.password:
                if not verify_password(form.password):
                    logger.warning(f'Account: Password validation failed for user {user.username}')
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
                    logger.warning(f'Account: User {request.user.username} denied to delete user {user.username} (cross-tenant)')
                    return json_response(error='无权操作其他租户的用户')
                # 普通管理员不能删除超级管理员账号
                if not request.user.is_supper and user.is_supper:
                    logger.warning(f'Account: User {request.user.username} denied to delete super user {user.username}')
                    return json_response(error='无权删除超级管理员账号')
                if user.id == request.user.id:
                    logger.warning(f'Account: User {request.user.username} tried to delete themselves')
                    return json_response(error='无法删除当前登录账户')
                # 执行软删除
                user.is_active = False
                user.deleted_at = timezone.now()
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
            logger.warning(f'Account: User {form.id} not found for restore')
            return json_response(error='用户不存在')
        if not user.deleted_by:
            logger.warning(f'Account: User {user.username} is not deleted, cannot restore')
            return json_response(error='该用户未被删除')
        # 非超管只能恢复本租户用户
        if not request.user.is_supper and user.tenant_id != request.user.tenant_id:
            logger.warning(f'Account: User {request.user.username} denied to restore user {user.username} (cross-tenant)')
            return json_response(error='无权操作其他租户的用户')
        # 检查是否有未删除的同名用户
        if User.objects.filter(username=user.username, deleted_by_id__isnull=True).exists():
            logger.warning(f'Account: Cannot restore user {user.username}: username already exists')
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
        try:
            migrate_existing_data({user.username: new_tenant_id})
        except Exception as e:
            logger.error(f'Account: Failed to migrate user {user.username} tenant data: {e}', exc_info=True)


class RoleView(AdminView):
    PERM_MAP = {
        'GET': 'system.account.view',
        'POST': 'system.account.edit',
        'PATCH': 'system.account.edit',
        'DELETE': 'system.account.del',
    }

    def get(self, request):
        roles = get_assignable_roles(request.user)
        return json_response(roles)

    def post(self, request):
        raw_body = self._parse_raw_body(request)
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', help='请输入角色名称'),
            Argument('desc', required=False),
            # 边界字段：required=False 无 default，未提交时为 None
            # 创建场景：None 由 _normalize_role_fields 补默认值
            # 编辑场景：None 用 role 现值补齐，避免覆盖现有边界字段
            Argument('is_global_admin', type=bool, required=False),
            Argument('is_system', type=bool, required=False),
            Argument('tenant_id', required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        # 普通管理员不能创建或设置全局管理员角色
        if not request.user.is_supper and form.is_global_admin:
            logger.warning(f'Account: User {request.user.username} denied to create global admin role')
            return json_response(error='无权创建全局管理员角色')

        fields = dict(form)
        role_id = fields.pop('id', None)

        if role_id:
            role = get_manageable_role(request.user, role_id)
            if not role:
                logger.warning(f'Account: Role {role_id} not manageable by user {request.user.username}')
                return json_response(error='角色不存在或无权操作')
            self._normalize_role_fields(fields, request.user, role=role, raw_body=raw_body)
            boundary_changed = any(
                getattr(role, f) != fields.get(f)
                for f in ('is_global_admin', 'tenant_id', 'is_system')
            )
            Role.objects.filter(pk=role_id).update(**fields)
            # 修改了影响授权边界的字段时，刷新关联用户权限缓存和 token
            # 与 patch() 修改权限后的处理保持一致
            if boundary_changed:
                role.clear_perms_cache()
                role.user_set.update(token_expired=0)
        else:
            self._normalize_role_fields(fields, request.user)
            Role.objects.create(created_by=request.user, **fields)
        return json_response()

    @staticmethod
    def _parse_raw_body(request):
        """解析原始请求体，用于区分"未提交 tenant_id"和"显式提交 null"。

        JsonParser 对两种情况都返回 None，无法区分；这里单独解析一次原始 JSON。
        """
        try:
            return json.loads(request.body) if request.body else {}
        except (ValueError, TypeError):
            return {}

    @staticmethod
    def _normalize_role_fields(fields, operator, role=None, raw_body=None):
        """统一处理角色边界字段：补齐未提交值、普通管理员强制覆盖、全局管理员不变量。

        - role 非空（编辑场景）：未提交的边界字段用 role 现值补齐，
          避免旧前端只提交 name/desc 时清空边界字段。
        - role 为空（创建场景）：未提交的边界字段补默认值。
        - 普通管理员：强制 tenant_id=自身租户、is_system=False、is_global_admin=False。
        - 全局管理员不变量：is_global_admin=True 时强制 tenant_id=None、is_system=True，
          与 migration 0006 回填策略一致。
        原地修改 fields 并返回。
        """
        # 补齐未提交的布尔边界字段
        if fields.get('is_global_admin') is None:
            fields['is_global_admin'] = role.is_global_admin if role else False
        if fields.get('is_system') is None:
            fields['is_system'] = role.is_system if role else False
        # tenant_id：编辑场景未提交 key 时保持原值；创建场景未提交为 None（平台级）
        if role is not None and raw_body is not None and 'tenant_id' not in raw_body:
            fields['tenant_id'] = role.tenant_id
        elif role is None and fields.get('tenant_id') is None:
            fields['tenant_id'] = None

        # 普通管理员强制覆盖边界字段
        if not operator.is_supper:
            fields['tenant_id'] = operator.tenant_id
            fields['is_system'] = False
            fields['is_global_admin'] = False

        # 全局管理员角色不变量
        if fields.get('is_global_admin'):
            fields['tenant_id'] = None
            fields['is_system'] = True

        return fields

    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('page_perms', type=dict, required=False),
            Argument('deploy_perms', type=dict, required=False),
            Argument('group_perms', type=list, required=False)
        ).parse(request.body)
        if error:
            return json_response(error=error)

        # 取可管理角色，普通管理员不能修改系统/平台/其他租户角色
        role = get_manageable_role(request.user, form.id)
        if not role:
            logger.warning(f'Account: Role {form.id} not manageable for patch by user {request.user.username}')
            return json_response(error='角色不存在或无权操作')

        # 权限子集校验：普通管理员新权限不能超过自身已有权限
        if form.page_perms is not None:
            err = validate_page_perms_subset(request.user, form.page_perms)
            if err:
                logger.warning(f'Account: User {request.user.username} denied to set page_perms exceeding own scope on role {form.id}')
                return json_response(error=err)
        if form.group_perms is not None:
            err = validate_group_perms_subset(request.user, form.group_perms)
            if err:
                logger.warning(f'Account: User {request.user.username} denied to set group_perms exceeding own scope on role {form.id}')
                return json_response(error=err)
        if form.deploy_perms is not None:
            err = validate_deploy_perms_subset(request.user, form.deploy_perms)
            if err:
                logger.warning(f'Account: User {request.user.username} denied to set deploy_perms exceeding own scope on role {form.id}')
                return json_response(error=err)

        if form.page_perms is not None:
            role.page_perms = json.dumps(form.page_perms)
        if form.deploy_perms is not None:
            role.deploy_perms = json.dumps(form.deploy_perms)
        if form.group_perms is not None:
            role.group_perms = json.dumps(form.group_perms)
        role.user_set.update(token_expired=0)
        # 先持久化再清缓存：save() 会自增 perms_version，
        # 此时并发登录的用户即便在 clear_perms_cache 之后重算，
        # 读到的也是已持久化的新 page_perms，不会把残缺集合写回缓存。
        # clear_perms_cache 作为立即失效优化（避免等下次读取才重算）。
        role.save()
        if form.page_perms is not None:
            role.clear_perms_cache()
        return json_response()

    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误')
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        # 取可管理角色，普通管理员不能删除系统/平台/其他租户角色
        role = get_manageable_role(request.user, form.id)
        if not role:
            logger.warning(f'Account: Role {form.id} not manageable for delete by user {request.user.username}')
            return json_response(error='角色不存在或无权操作')
        if role.user_set.exists():
            logger.warning(f'Account: Role {role.name} has associated users, cannot delete')
            return json_response(error='已有用户使用了该角色，请解除关联后再尝试删除')
        role.delete()
        return json_response()


class AssignableRoleView(AdminView):
    """账号表单可分配角色下拉专用接口。

    仅服务于账号创建/编辑表单的角色下拉展示，不替代 validate_assignable_role_ids
    的安全校验。安全边界仍以用户创建/编辑提交时的后端强校验为准。
    """
    PERM_MAP = {
        'GET': 'system.account.view',
    }

    def get(self, request):
        target_tenant_id = request.GET.get('tenant_id')
        roles = get_assignable_roles_for_target(request.user, target_tenant_id)
        return json_response(roles)


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
                logger.warning(f'Account: Invalid tenant_id format: {form.id}')
                return json_response(error=err)
            if Tenant.objects.filter(pk=form.id).exists():
                logger.warning(f'Account: Tenant id already exists: {form.id}')
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
                logger.warning(f'Account: Tenant not found for patch by user {request.user}')
                return json_response(error='租户不存在')
            # 过滤 None：JsonParser 对未传字段填 None，update_by_dict 会覆盖 NOT NULL 字段
            update_data = {k: v for k, v in form.items() if v is not None}
            tenant.update_by_dict(update_data)
        return json_response(error=error)

    def delete(self, request):
        form, error = JsonParser(
            Argument('id', help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            tenant = Tenant.objects.filter(pk=form.id).first()
            if not tenant:
                logger.warning(f'Account: Tenant not found for delete by user {request.user}')
                return json_response(error='租户不存在')
            if User.objects.filter(tenant_id=form.id).exists():
                logger.warning(f'Account: Cannot delete tenant {form.id}: has associated users')
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
                    logger.warning(f'Account: Password validation failed for user {request.user.username}')
                    return json_response(error='请设置至少8位包含数字、小写和大写字母、特殊字符的新密码')

                if request.user.verify_password(form.old_password):
                    request.user.password_hash = User.make_password(form.new_password)
                    request.user.token_expired = 0
                    request.user.save()
                    return json_response()
                else:
                    logger.warning(f'Account: Wrong old password for user {request.user.username}')
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
        # 租户归属策略（产品定义）：
        # 1. 已存在的租户用户登录失败 → 写入该用户所属租户，租户管理员可见。
        # 2. 不存在的用户名登录失败（含跨租户爆破、未知账号尝试）→ 写入 'default' 全局归档，
        #    仅超管可见，避免普通租户管理员看不到针对本系统的未知账号攻击。
        # 前端审计页面应对非超管用户在筛选"登录"动作时给出说明：未知账号的登录失败仅超管可见。
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
    user.last_login = timezone.now()
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

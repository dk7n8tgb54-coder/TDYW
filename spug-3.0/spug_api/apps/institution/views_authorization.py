# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度管理授权视图（2026-10-31）：逐本账号授权与手册所有者管理

接口约定（nginx 对外前缀 /api/institution/）：
  GET  /manuals/<pk>/authorizations/    授权清单（所有者/平台超管）
  PUT  /manuals/<pk>/authorizations/    整体替换授权（所有者/平台超管；
                                        失权撤销会话）
  GET  /manuals/<pk>/account-options/   授权界面账号候选（所有者/平台超管；
                                        全部启用账号最小清单）
  GET  /manuals/<pk>/owner-candidates/  所有者候选（所有者/平台超管；
                                        启用账号最小清单）
  POST /manuals/<pk>/owner/             指定/移交/接管所有者（当前所有者
                                        或平台超管）

规则（2026-10-31 第二轮权限模型改造）：
- 页面权限 @manual_auth('institution.manual.view') 只门控入口；业务校验
  为所有者（Manual.owner）或平台超管（is_supper）。原"制度管理员"权限码
  已废除，后端不再识别任何管理权限码。普通所有者只管理
  自己的手册；编制/发布授权不足以读取或修改授权配置。
- 所有者可把手册移交给任一启用账号；平台超管可接管任意手册（成为新
  所有者）；原所有者移交后不再因所有者身份保有权能（活跃编辑会话被
  撤销留痕）。移交/接管留操作记录与审计。
- PUT 整体替换：全 False 不保留授权行；失去 can_edit 的账号撤销其
  在该手册全部文件的活跃编辑会话（未落盘内容显式丢弃并留痕）。
- tenant_id 不参与任何判定。
"""
import logging

from django.db import transaction
from django.views.generic import View

from apps.account.models import User
from apps.logs.audit import record_audit_event
from libs import Argument, JsonParser, json_response

from . import authorization_services, serializers, services
from .views import _manual_from_request, manual_auth

logger = logging.getLogger(__name__)


def _check_owner_or_admin(manual, user):
    """授权配置业务校验：手册所有者或平台超管"""
    if (authorization_services.is_manual_owner(user, manual) or
            authorization_services.is_platform_admin(user)):
        return None
    return json_response(error='手册不存在或无权限访问')


def _audit(request, manual, action_kind, **detail):
    record_audit_event(
        request, 'update', services.AUDIT_TARGET_TYPE,
        target_id=manual.id, target_name=manual.name,
        detail={'action_kind': action_kind, 'module': 'institution', **detail})


class ManualAuthorizationsView(View):
    """逐本账号授权（GET 清单 / PUT 整体替换）"""

    @manual_auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        deny = _check_owner_or_admin(manual, request.user)
        if deny:
            return deny
        return json_response(data={
            'items': authorization_services.list_manual_authorizations(manual),
        })

    @manual_auth('institution.manual.view')
    @transaction.atomic
    def put(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        deny = _check_owner_or_admin(manual, request.user)
        if deny:
            return deny
        form, error = JsonParser(
            Argument('items', type=list, required=True, help='请提供授权清单'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        # 注意 form 是 AttrDict（dict 子类）：form.items 会取到 dict.items
        # 方法而非解析结果，必须用键访问
        items, err = _parse_authorization_items(form['items'])
        if err:
            return json_response(error=err)
        result, err = authorization_services.replace_manual_authorizations(
            manual, items, request.user)
        if err:
            return json_response(error=err)
        _audit(request, manual, services.ACTION_AUTHORIZATION_CHANGE,
               revoked_sessions=result['revoked_sessions'],
               lost_edit_accounts=result['lost_edit_accounts'])
        return json_response(data={
            'items': authorization_services.list_manual_authorizations(manual),
            'revoked_sessions': result['revoked_sessions'],
        })


def _parse_authorization_items(raw_items):
    """校验授权清单：合法账号 + 布尔授权位，按账号去重

    Returns:
        tuple: ([(account_id, can_view, can_edit, can_publish)], 错误或 None)
    """
    if not isinstance(raw_items, list):
        return None, '授权参数格式错误'
    seen = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            return None, '授权参数格式错误'
        account_id = raw.get('account_id')
        if not isinstance(account_id, int) or isinstance(account_id, bool):
            return None, '授权账号参数格式错误'
        flags = []
        for key in ('can_view', 'can_edit', 'can_publish'):
            value = raw.get(key, False)
            if not isinstance(value, bool):
                return None, f'{key} 必须为布尔值'
            flags.append(value)
        if account_id in seen:
            return None, '授权清单中存在重复账号'
        seen[account_id] = tuple(flags)
    if seen:
        found = User.objects.filter(
            pk__in=seen, is_active=True).values_list('pk', flat=True)
        missing = set(seen) - set(found)
        if missing:
            return None, '存在无效或已停用的账号'
    return [(a, *flags) for a, flags in seen.items()], None


class OwnerCandidatesView(View):
    """所有者候选（手册所有者/平台超管）：启用账号最小清单（仅 id+name）"""

    @manual_auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not (authorization_services.is_manual_owner(request.user, manual)
                or authorization_services.is_platform_admin(request.user)):
            return json_response(error='手册不存在或无权限访问')
        users = User.objects.filter(is_active=True).order_by('id')
        return json_response(data=[
            {'id': u.id, 'name': u.nickname or u.username} for u in users])


class AccountOptionsView(View):
    """授权界面账号候选（手册所有者或平台超管）：启用账号最小清单

    授权配置允许普通所有者管理自己的手册（GET/PUT authorizations 同
    一门禁），添加授权行需要"可选账号"候选来源。与 owner-candidates
    同口径：全部启用账号、只返回 id+name（昵称，空则账号名）最小字段，
    绝不开放账号管理清单（/api/account/user/ 仍要求 system.account.view）。
    """

    @manual_auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        deny = _check_owner_or_admin(manual, request.user)
        if deny:
            return deny
        users = User.objects.filter(is_active=True).order_by('id')
        return json_response(data=[
            {'id': u.id, 'name': u.nickname or u.username} for u in users])


class ManualOwnerView(View):
    """指定/移交/接管手册所有者（当前所有者或平台超管）

    - 所有者移交：当前所有者把手册移交给任一启用账号（kind=transfer）；
      原所有者此后不再因所有者身份保有权能，其活跃编辑会话被撤销留痕。
    - 超管接管：平台超管把任意手册接管为本人或指定给他人（kind=
      takeover）。移交/接管均写操作记录与审计（含 previous_owner_id/kind）。
    """

    @manual_auth('institution.manual.view')
    @transaction.atomic
    def post(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not (authorization_services.is_manual_owner(request.user, manual)
                or authorization_services.is_platform_admin(request.user)):
            return json_response(error='手册不存在或无权限访问')
        form, error = JsonParser(
            Argument('account_id', type=int, required=True,
                     help='请提供所有者账号'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        if form.account_id == manual.owner_id:
            return json_response(error='新所有者与当前所有者相同')
        account = User.objects.filter(pk=form.account_id, is_active=True).first()
        if not account:
            return json_response(error='所有者账号不存在或已停用')
        previous_owner_id = manual.owner_id
        manual, _ = authorization_services.set_manual_owner(
            manual, account, request.user)
        kind = 'transfer' if previous_owner_id == request.user.id \
            else 'takeover'
        _audit(request, manual, services.ACTION_OWNER_CHANGE,
               owner_id=manual.owner_id,
               previous_owner_id=previous_owner_id, kind=kind)
        return json_response(data=serializers.to_manual_detail(
            manual,
            grant=authorization_services.get_manual_grant(manual, request.user),
            is_owner=authorization_services.is_manual_owner(
                request.user, manual),
            is_admin=authorization_services.is_platform_admin(request.user),
            include_draft=True))

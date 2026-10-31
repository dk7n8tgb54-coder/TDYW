# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度管理授权视图（2026-10-31）：逐本账号授权与手册所有者管理

接口约定（nginx 对外前缀 /api/institution/）：
  GET  /manuals/<pk>/authorizations/    授权清单（所有者/制度管理员）
  PUT  /manuals/<pk>/authorizations/    整体替换授权 + editor_can_view_published
                                        （所有者/制度管理员；失权撤销会话）
  GET  /manuals/<pk>/account-options/   授权界面账号候选（所有者/制度管理员；
                                        全部启用账号最小清单）
  GET  /manuals/<pk>/owner-candidates/  所有者候选（制度管理员；启用账号最小清单）
  POST /manuals/<pk>/owner/             指定/接管/移交所有者（制度管理员）

规则（2026-10-31 授权模型改造）：
- 页面权限 @auth('institution.manual.view') 只门控入口；业务校验为
  所有者（Manual.owner）或制度管理员（institution.manual.admin）。
  普通所有者只管理自己的手册；管理员管理任意手册；编制/发布授权
  不足以读取或修改授权配置。
- 所有者本人不能移交：受控移交仅经管理员（POST owner）。
- PUT 整体替换：全 False 不保留授权行；失去 can_edit 的账号撤销其
  在该手册全部文件的活跃编辑会话（未落盘内容显式丢弃并留痕）。
- tenant_id 不参与任何判定。
"""
import logging

from django.db import transaction
from django.views.generic import View

from apps.account.models import User
from apps.logs.audit import record_audit_event
from libs import Argument, JsonParser, auth, json_response

from . import authorization_services, serializers, services
from .views import _manual_from_request

logger = logging.getLogger(__name__)


def _check_owner_or_admin(manual, user):
    """授权配置业务校验：手册所有者或制度管理员"""
    if (authorization_services.is_manual_owner(user, manual) or
            authorization_services.is_institution_admin(user)):
        return None
    return json_response(error='手册不存在或无权限访问')


def _audit(request, manual, action_kind, **detail):
    record_audit_event(
        request, 'update', services.AUDIT_TARGET_TYPE,
        target_id=manual.id, target_name=manual.name,
        detail={'action_kind': action_kind, 'module': 'institution', **detail})


class ManualAuthorizationsView(View):
    """逐本账号授权（GET 清单 / PUT 整体替换）"""

    @auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        deny = _check_owner_or_admin(manual, request.user)
        if deny:
            return deny
        return json_response(data={
            'items': authorization_services.list_manual_authorizations(manual),
            'editor_can_view_published': manual.editor_can_view_published,
        })

    @auth('institution.manual.view')
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
            Argument('editor_can_view_published', type=bool,
                     default=manual.editor_can_view_published),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        # 注意 form 是 AttrDict（dict 子类）：form.items 会取到 dict.items
        # 方法而非解析结果，必须用键访问
        items, err = _parse_authorization_items(form['items'])
        if err:
            return json_response(error=err)
        result, err = authorization_services.replace_manual_authorizations(
            manual, items, form.editor_can_view_published, request.user)
        if err:
            return json_response(error=err)
        _audit(request, manual, services.ACTION_AUTHORIZATION_CHANGE,
               revoked_sessions=result['revoked_sessions'],
               lost_edit_accounts=result['lost_edit_accounts'])
        return json_response(data={
            'items': authorization_services.list_manual_authorizations(manual),
            'editor_can_view_published': manual.editor_can_view_published,
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
    """所有者候选（制度管理员）：启用账号最小清单（仅 id+name）"""

    @auth('institution.manual.view')
    def get(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not authorization_services.is_institution_admin(request.user):
            return json_response(error='手册不存在或无权限访问')
        users = User.objects.filter(is_active=True).order_by('id')
        return json_response(data=[
            {'id': u.id, 'name': u.nickname or u.username} for u in users])


class AccountOptionsView(View):
    """授权界面账号候选（手册所有者或制度管理员）：启用账号最小清单

    与 owner-candidates（仅管理员，受控移交不走所有者）的差异：授权
    配置本身允许普通所有者管理自己的手册（GET/PUT authorizations 同
    一门禁），添加授权行需要"可选账号"候选来源。与 owner-candidates
    同口径：全部启用账号、只返回 id+name（昵称，空则账号名）最小字段，
    绝不开放账号管理清单（/api/account/user/ 仍要求 system.account.view）。
    """

    @auth('institution.manual.view')
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
    """指定/接管/移交手册所有者（仅制度管理员；所有者本人不能移交）"""

    @auth('institution.manual.view')
    @transaction.atomic
    def post(self, request, pk):
        manual, resp = _manual_from_request(request, pk)
        if resp:
            return resp
        if not authorization_services.is_institution_admin(request.user):
            return json_response(error='手册不存在或无权限访问')
        form, error = JsonParser(
            Argument('account_id', type=int, required=True,
                     help='请提供所有者账号'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        account = User.objects.filter(pk=form.account_id, is_active=True).first()
        if not account:
            return json_response(error='所有者账号不存在或已停用')
        manual, _ = authorization_services.set_manual_owner(
            manual, account, request.user)
        _audit(request, manual, services.ACTION_OWNER_CHANGE,
               owner_id=manual.owner_id,
               previous_owner_id=None)
        return json_response(data=serializers.to_manual_detail(
            manual,
            grant=authorization_services.get_manual_grant(manual, request.user),
            is_owner=authorization_services.is_manual_owner(
                request.user, manual),
            is_admin=True,
            include_draft=True))

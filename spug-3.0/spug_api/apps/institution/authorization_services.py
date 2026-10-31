# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度管理授权服务层（2026-10-31 自 services.py 门控行数拆分）

职责：手册级授权判定（所有者 + 逐本账号授权）、逐本授权管理
（整体替换 + 失权撤销会话）、所有者指定/移交/接管、手册可见性定位。
单向依赖 services（操作记录/账号显示名），services 不反向引用本模块。

两层模型（2026-10-31 第二轮权限模型改造）：
- 系统角色（页面权限码）授予查看/编制/发布等功能资格（@auth 门控）；
- 具体可操作哪本手册由 Manual.owner（所有者）与 ManualAuthorization
  （逐本账号授权）决定。
- **所有者自动拥有该手册范围内全部权限**：查看正式版本和草稿、管理
  账号授权与文件分工、设置/重置编辑密码、编辑任意文件草稿、提交编制、
  发布/废止/回退。按对象范围生效，不要求所有者再持有任何页面权限码
  或逐本授权。
- "admin"概念收敛为平台超管（is_supper）：原"制度管理员"页面权限码
  已废除，后端不再识别任何管理权限码。超管除可见性外不自动取得编辑/发布等
  对象级权能（接管所有者是唯一路径）。
- tenant_id 不参与任何归属/可见/编辑判断（模块铁律，测试钉死）。
"""
from django.db import models, transaction
from django.utils import timezone

from .models import Manual, ManualAuthorization, ManualEditSession
from .services import (_account_display, log_operation,
                       ACTION_AUTHORIZATION_CHANGE, ACTION_OWNER_CHANGE)

# 授权角色类别（my_roles 下发语义沿用：view/edit/publish）
ROLE_VIEW = 'view'
ROLE_EDIT = 'edit'
ROLE_PUBLISH = 'publish'


def is_platform_admin(user):
    """平台超管判定（is_supper）；"制度管理员"权限码已废除"""
    return bool(user.is_supper)


def is_manual_owner(user, manual):
    """手册所有者（对该手册自动拥有范围内全部权限，见模块 docstring）"""
    return bool(getattr(user, 'pk', None)) and manual.owner_id == user.id


def get_manual_grant(manual, user):
    """当前账号在该手册的授权行（无则 None）"""
    if not getattr(user, 'pk', None):
        return None
    return ManualAuthorization.objects.filter(
        manual=manual, account_id=user.id).first()


def _grant_has_any(grant):
    return bool(grant and (grant.can_view or grant.can_edit
                           or grant.can_publish))


def can_manage_manual(user):
    """是否可管理手册元数据（编辑/配置模块权限）

    仅约束"能对可见手册做元数据/删除管理"，内容可见性与编辑
    不再经它放行（2026-10-31）。
    """
    if is_platform_admin(user):
        return True
    return user.has_perms({'institution.manual.edit'}) or \
        user.has_perms({'institution.manual.config'})


def can_view_manual(user, manual):
    """可见手册元数据与详情入口：平台超管 / 所有者 / 授权行任一 True"""
    if is_platform_admin(user) or is_manual_owner(user, manual):
        return True
    return _grant_has_any(get_manual_grant(manual, user))


def can_view_published(user, manual):
    """可见已发布版本：平台超管；所有者；或授权 can_view

    editor_can_view_published 开关已删除（2026-10-31 第二轮）：仅
    can_edit 授权不再可见发布版。
    """
    if is_platform_admin(user) or is_manual_owner(user, manual):
        return True
    grant = get_manual_grant(manual, user)
    return bool(grant and grant.can_view)


def can_edit_manual_files(user, manual):
    """工作区编制资格：所有者；或持有该手册 can_edit 授权

    资格不等于可编辑任意文件——非所有者的内容写路径一律走
    can_edit_file（负责人独占）；所有者例外（可编辑该手册任意文件）。
    """
    if is_manual_owner(user, manual):
        return True
    grant = get_manual_grant(manual, user)
    return bool(grant and grant.can_edit)


def can_edit_file(user, manual, file_entry):
    """内容写路径（会话/保存/editor-config/forcesave/开始修订/草稿建立恢复）：

    手册所有者可编辑该手册任意文件（例外）；否则负责人独占——
    can_edit 授权 + 该文件负责人（密码只是附加验证）。
    平台超管不例外（接管所有者是唯一路径）。
    """
    if is_manual_owner(user, manual):
        return True
    grant = get_manual_grant(manual, user)
    return bool(grant and grant.can_edit and
                file_entry.owner_id == user.id)


def can_publish(user, manual):
    """可发布（发布/废止/回退/预检/长期保留标记）：所有者；或授权
    can_publish（平台超管不因超管身份自动可发布）"""
    if is_manual_owner(user, manual):
        return True
    grant = get_manual_grant(manual, user)
    return bool(grant and grant.can_publish)


def can_view_workspace(user, manual):
    """草稿工作区/待发布清单可见：平台超管 / 所有者 / 编制或发布授权"""
    return (is_platform_admin(user) or is_manual_owner(user, manual) or
            can_edit_manual_files(user, manual) or can_publish(user, manual))


def filter_visible_manuals(queryset, user):
    """按所有者/逐本授权过滤可见手册；平台超管可见全部"""
    if is_platform_admin(user):
        return queryset
    return queryset.filter(
        models.Q(owner=user) |
        (models.Q(account_grants__account=user) &
         (models.Q(account_grants__can_view=True) |
          models.Q(account_grants__can_edit=True) |
          models.Q(account_grants__can_publish=True)))
    ).distinct()


def get_manual_for_user(manual_id, user):
    """取手册并做可见性校验

    Returns:
        tuple: (manual 或 None, 错误消息或 None)
    """
    manual = Manual.objects.filter(pk=manual_id).first()
    if not manual:
        return None, '手册不存在或无权限访问'
    if not can_view_manual(user, manual):
        return None, '手册不存在或无权限访问'
    return manual, None


# ---------------------------------------------------------------------------
# 逐本账号授权管理（所有者/平台超管；整体替换 + 失权撤销会话）

def list_manual_authorizations(manual):
    """手册授权清单（账号显示名回退昵称；空授权行不落库）"""
    rows = ManualAuthorization.objects.filter(manual=manual).select_related(
        'account').order_by('account_id')
    return [{
        'account_id': row.account_id,
        'account_name': _account_display(row.account),
        'can_view': row.can_view,
        'can_edit': row.can_edit,
        'can_publish': row.can_publish,
    } for row in rows]


def _revoke_manual_sessions_for_users(manual, account_ids, reason):
    """撤销指定账号在该手册全部文件的活跃会话；返回撤销数量"""
    if not account_ids:
        return 0
    return ManualEditSession.objects.filter(
        manual=manual, user_id__in=account_ids, revoked_at__isnull=True,
    ).update(revoked_at=timezone.now(), revoked_reason=reason)


def _upsert_manual_grant(manual, existing, keep_ids, lost_edit_ids,
                         account_id, can_view, can_edit, can_publish,
                         operator):
    """整体替换单条授权行：全 False 删行，否则更新/建立

    - 行为与既有实现逐字等价；失去 can_edit 的账号登记进 lost_edit_ids
      （行内重复登记由调用方 sorted(set(...)) 归一）。
    - 须在调用方事务内执行。
    """
    row = existing.get(account_id)
    had_edit = bool(row and row.can_edit)
    if not (can_view or can_edit or can_publish):
        # 全 False：不保留空授权行
        if had_edit:
            lost_edit_ids.append(account_id)
        if row:
            row.delete()
        return
    keep_ids.add(account_id)
    defaults = {'can_view': can_view, 'can_edit': can_edit,
                'can_publish': can_publish, 'updated_by': operator}
    if row:
        for field, value in defaults.items():
            setattr(row, field, value)
        row.save(update_fields=list(defaults))
        if had_edit and not can_edit:
            lost_edit_ids.append(account_id)
    else:
        ManualAuthorization.objects.create(
            manual=manual, account_id=account_id, **defaults)
    if had_edit and not can_edit:
        lost_edit_ids.append(account_id)


@transaction.atomic
def replace_manual_authorizations(manual, items, operator):
    """整体替换手册逐本账号授权（PUT authorizations 权威实现）

    - items: [(account_id, can_view, can_edit, can_publish)]；账号存在性
      与去重由调用方校验。
    - 全 False 的账号不保留授权行（已有行删除）。
    - 整体替换：不在 items 中的既有授权行删除。
    - 失去 can_edit 的账号（含行被删除/清空的）：撤销其在该手册全部
      文件的活跃编辑会话——未落盘内容显式丢弃，撤销原因留痕，操作
      记录记录撤销数量。
    """
    if not isinstance(items, list):
        return None, '授权参数格式错误'
    existing = {row.account_id: row for row in
                ManualAuthorization.objects.filter(manual=manual)}
    keep_ids = set()
    lost_edit_ids = []
    for account_id, can_view, can_edit, can_publish in items:
        _upsert_manual_grant(
            manual, existing, keep_ids, lost_edit_ids,
            account_id, can_view, can_edit, can_publish, operator)
    for account_id, row in existing.items():
        if account_id not in keep_ids:
            if row.can_edit:
                lost_edit_ids.append(account_id)
            row.delete()
    revoked = _revoke_manual_sessions_for_users(
        manual, lost_edit_ids, '编制授权被撤销，编辑会话失效')
    log_operation(
        manual, operator, ACTION_AUTHORIZATION_CHANGE,
        fields=['account_grants'],
        grants=[{'account_id': a, 'can_view': v, 'can_edit': e,
                 'can_publish': p} for a, v, e, p in items],
        revoked_sessions=revoked, lost_edit_accounts=sorted(set(lost_edit_ids)))
    return {'revoked_sessions': revoked,
            'lost_edit_accounts': sorted(set(lost_edit_ids))}, None


@transaction.atomic
def set_manual_owner(manual, account, operator):
    """指定/接管/移交手册所有者（当前所有者或平台超管）

    - kind 判定：operator 为当前所有者 -> 'transfer'（移交）；
      operator 为平台超管 -> 'takeover'（接管）。
    - 写 owner 后撤销原所有者在该手册全部活跃编辑会话（未落盘内容
      显式丢弃并留痕）：原所有者移交后不再因所有者身份保有权能。
    - 操作记录 detail 含 kind/revoked_sessions。
    """
    previous_id = manual.owner_id
    previous_name = _account_display(manual.owner)
    if is_manual_owner(operator, manual):
        kind = 'transfer'
    else:
        kind = 'takeover'
    manual.owner = account
    manual.save(update_fields=['owner'])
    revoked = 0
    if previous_id and previous_id != account.id:
        revoked = _revoke_manual_sessions_for_users(
            manual, [previous_id], '所有者移交，原所有者编辑会话失效')
    log_operation(
        manual, operator, ACTION_OWNER_CHANGE,
        fields=['owner'], kind=kind,
        previous_owner_id=previous_id,
        previous_owner_name=previous_name,
        owner_id=manual.owner_id, owner_name=_account_display(account),
        revoked_sessions=revoked)
    return manual, None


def validate_assignee_for_manual(manual, account):
    """被指派文件负责人必须持有该手册编制授权（can_edit）"""
    if account is None:
        return None
    if not can_edit_manual_files(account, manual):
        return '该账号不具备本手册编制资格'
    return None

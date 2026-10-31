# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度管理授权服务层（2026-10-31 自 services.py 门控行数拆分）

职责：手册级授权判定（所有者 + 逐本账号授权）、逐本授权管理
（整体替换 + 失权撤销会话）、所有者指定/移交、手册可见性定位。
单向依赖 services（操作记录/账号显示名），services 不反向引用本模块。

两层模型：
- 系统角色（页面权限码）授予查看/编制/发布等功能资格（@auth 门控）；
- 具体可操作哪本手册由 Manual.owner（所有者）与 ManualAuthorization
  （逐本账号授权）决定。所有者负责账号授权与文件分工，不因所有者
  身份自动取得正文编辑或发布权；制度管理员（institution.manual.admin）
  可指定/接管/移交所有者与替换任意手册的授权，也不因管理身份取得
  文件编辑或发布权。
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


def is_institution_admin(user):
    """制度管理员：超管或持有 institution.manual.admin 页面权限码"""
    if user.is_supper:
        return True
    return user.has_perms({'institution.manual.admin'})


def is_manual_owner(user, manual):
    """手册所有者（负责该手册的账号授权与文件分工）"""
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

    仅约束"能对可见手册做元数据/密码/删除管理"，内容可见性与编辑
    不再经它放行（2026-10-31）。
    """
    if user.is_supper:
        return True
    return user.has_perms({'institution.manual.edit'}) or \
        user.has_perms({'institution.manual.config'})


def can_view_manual(user, manual):
    """可见手册元数据与详情入口：管理员 / 所有者 / 授权行任一 True"""
    if is_institution_admin(user) or is_manual_owner(user, manual):
        return True
    return _grant_has_any(get_manual_grant(manual, user))


def can_view_published(user, manual):
    """可见已发布版本：管理员；或授权 can_view；
    或授权 can_edit 且本手册允许编制者查看发布版（owner 不自动可见）"""
    if is_institution_admin(user):
        return True
    grant = get_manual_grant(manual, user)
    if grant and grant.can_view:
        return True
    return bool(grant and grant.can_edit and manual.editor_can_view_published)


def can_edit_manual_files(user, manual):
    """工作区编制资格：持有该手册 can_edit 授权

    资格不等于可编辑任意文件——内容写路径一律走 can_edit_file
    （负责人独占）。
    """
    grant = get_manual_grant(manual, user)
    return bool(grant and grant.can_edit)


def can_edit_file(user, manual, file_entry):
    """负责人独占编辑：编制资格 + 该文件负责人（密码只是附加验证）"""
    return can_edit_manual_files(user, manual) and \
        file_entry.owner_id == user.id


def can_publish(user, manual):
    """可发布：持有该手册 can_publish 授权（管理员不因管理身份可发布）"""
    grant = get_manual_grant(manual, user)
    return bool(grant and grant.can_publish)


def can_view_workspace(user, manual):
    """草稿工作区/待发布清单可见：管理员 / 所有者 / 编制或发布授权"""
    return (is_institution_admin(user) or is_manual_owner(user, manual) or
            can_edit_manual_files(user, manual) or can_publish(user, manual))


def filter_visible_manuals(queryset, user):
    """按所有者/逐本授权过滤可见手册；制度管理员可见全部"""
    if is_institution_admin(user):
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
# 逐本账号授权管理（所有者/制度管理员；整体替换 + 失权撤销会话）

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
def replace_manual_authorizations(manual, items, editor_can_view_published,
                                  operator):
    """整体替换手册逐本账号授权（PUT authorizations 权威实现）

    - items: [(account_id, can_view, can_edit, can_publish)]；账号存在性
      与去重由调用方校验。
    - 全 False 的账号不保留授权行（已有行删除）。
    - 整体替换：不在 items 中的既有授权行删除。
    - 失去 can_edit 的账号（含行被删除/清空的）：撤销其在该手册全部
      文件的活跃编辑会话——未落盘内容显式丢弃，撤销原因留痕，操作
      记录记录撤销数量。
    - editor_can_view_published 一并保存。
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
    manual.editor_can_view_published = bool(editor_can_view_published)
    manual.save(update_fields=['editor_can_view_published'])
    log_operation(
        manual, operator, ACTION_AUTHORIZATION_CHANGE,
        fields=['account_grants', 'editor_can_view_published'],
        grants=[{'account_id': a, 'can_view': v, 'can_edit': e,
                 'can_publish': p} for a, v, e, p in items],
        editor_can_view_published=manual.editor_can_view_published,
        revoked_sessions=revoked, lost_edit_accounts=sorted(set(lost_edit_ids)))
    return {'revoked_sessions': revoked,
            'lost_edit_accounts': sorted(set(lost_edit_ids))}, None


@transaction.atomic
def set_manual_owner(manual, account, operator):
    """指定/接管/移交手册所有者（仅制度管理员；受控移交不走所有者）"""
    previous_id = manual.owner_id
    previous_name = _account_display(manual.owner)
    manual.owner = account
    manual.save(update_fields=['owner'])
    log_operation(
        manual, operator, ACTION_OWNER_CHANGE,
        fields=['owner'], previous_owner_id=previous_id,
        previous_owner_name=previous_name,
        owner_id=manual.owner_id, owner_name=_account_display(account))
    return manual, None


def validate_assignee_for_manual(manual, account):
    """被指派文件负责人必须持有该手册编制授权（can_edit）"""
    if account is None:
        return None
    if not can_edit_manual_files(account, manual):
        return '该账号不具备本手册编制资格'
    return None

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度管理序列化（响应组装）"""


def _user_name(user):
    if user is None:
        return ''
    if hasattr(user, 'nickname') and user.nickname:
        return user.nickname
    return getattr(user, 'username', '') or ''


def to_category_dict(obj, with_inactive=False):
    data = {
        'id': obj.id,
        'name': obj.name,
        'sort_order': obj.sort_order,
        'is_active': obj.is_active,
        'created_at': obj.created_at,
    }
    if with_inactive:
        data['manual_count'] = obj.manuals.count()
    return data


def to_version_dict(version, manual=None):
    manual = manual or version.manual
    return {
        'id': version.id,
        'version_no': version.version_no,
        # 兼容镜像列 = 首个文件快照（清单首位）；完整清单见 files
        'file_name': version.original_name,
        'file_size': version.file_size,
        'file_hash': version.file_hash,
        'files': [to_version_file_dict(s)
                  for s in version.files.order_by('sort_order', 'id')],
        'change_note': version.change_note,
        'published_by_name': _user_name(version.published_by),
        'published_at': version.published_at,
        'is_effective': version.is_effective,
        'is_current': manual.current_version_id == version.id,
        # 保留策略状态（2026-10-29）：长期保留标记与整版文件清理状态
        # （'' 未清理 / partial 部分清理不可完整使用 / cleaned 已清理）；
        # is_current=True 的版本永久受保护，清理状态恒为 ''
        'long_term_protected': version.long_term_protected,
        'files_cleaned_at': version.files_cleaned_at,
        'files_clean_status': version.files_clean_status,
        'files_clean_error': version.files_clean_error,
    }


def to_version_file_dict(snapshot):
    """版本文件快照（历史清单条目：名称/顺序/哈希发布后不可变）

    is_cleaned=True 表示该快照物理文件已按保留策略清理，仅存清单与
    哈希元数据，预览/下载不可用。
    """
    return {
        'id': snapshot.id,
        'manual_file_id': snapshot.manual_file_id,
        'file_name': snapshot.display_name,
        'sort_order': snapshot.sort_order,
        'file_size': snapshot.file_size,
        'file_hash': snapshot.file_hash,
        'is_cleaned': snapshot.cleaned_at is not None,
    }


def to_draft_dict(draft):
    if not draft:
        return None
    return {
        'id': draft.id,
        'revision': draft.revision,
        'file_name': draft.original_name,
        'file_size': draft.file_size,
        'file_hash': draft.file_hash,
        'base_version_id': draft.base_version_id,
        # 来源版本号（草稿由版本快照恢复/回退时用于界面展示）
        'base_version_no': draft.base_version.version_no
        if draft.base_version_id else None,
        'last_saved_by_name': _user_name(draft.last_saved_by),
        'last_saved_at': draft.last_saved_at,
        'created_at': draft.created_at,
    }


def to_manual_file_dict(file_entry, draft=None, active_session=None,
                        draft_recovery=None, assignment=None, submission=None):
    """制度文件条目（待发布清单行）：草稿状态 + 编辑占用 + 文件分工

    draft_recovery 仅在草稿缺失时由视图层传入：无草稿文件的恢复途径
    提示（source=current_version 或 none，version_no、requires_reupload、
    note），供草稿工作台渲染对应恢复提示。
    assignment 为文件分工（负责人/分工说明/is_mine），对可见清单的所有
    调用方下发；submission 为"提交编制"状态（含草稿修订号，属草稿域
    信息），仅对工作区可见（编制/发布角色或管理权限）的调用方传入。
    """
    data = {
        'id': file_entry.id,
        'manual_id': file_entry.manual_id,
        'name': file_entry.display_name,
        'sort_order': file_entry.sort_order,
        'is_removed': file_entry.is_removed,
        # 修订进行中：显式持久状态（发布成功才关闭），与"草稿哈希是否
        # 变化"分开表达；前端据此区分「开始修订」与「继续编辑」
        'revision_open': bool(file_entry.revision_open),
        'created_at': file_entry.created_at,
        'draft': to_draft_dict(draft),
        'active_session': active_session,
    }
    if draft_recovery is not None:
        data['draft_recovery'] = draft_recovery
    if assignment is not None:
        data['assignment'] = assignment
    if submission is not None:
        data['submission'] = submission
    return data


def to_chapter_dict(chapter):
    return {
        'id': chapter.id,
        'title': chapter.title,
        'owner_id': chapter.owner_id,
        'owner_name': chapter.owner_name or _user_name(chapter.owner),
        'note': chapter.note,
        'progress': chapter.progress,
        'progress_display': chapter.get_progress_display(),
        'sort_order': chapter.sort_order,
        'submitted_at': chapter.submitted_at,
        'updated_at': chapter.updated_at,
    }


def to_oplog_dict(oplog):
    return {
        'id': oplog.id,
        'user_name': oplog.user_name or _user_name(oplog.user),
        'action': oplog.action,
        'version_id': oplog.version_id,
        'file_id': oplog.file_id,
        'detail': oplog.detail,
        'created_at': oplog.created_at,
    }


def my_manual_roles(grant, is_owner=False):
    """当前账号对该手册的有效角色类别列表（前端按 my_roles 渲染按钮）

    grant 为该账号在本手册的 ManualAuthorization 行（无授权为 None）。
    所有者自动拥有该手册范围内全部权限：返回 ['view','edit','publish']，
    不依赖逐本授权行（2026-10-31 第二轮权限模型）。
    """
    if is_owner:
        return ['view', 'edit', 'publish']
    if not grant:
        return []
    roles = []
    if grant.can_view:
        roles.append('view')
    if grant.can_edit:
        roles.append('edit')
    if grant.can_publish:
        roles.append('publish')
    return roles


def to_manual_list_item(manual, grant=None, is_owner=False, is_admin=False,
                        include_draft=False, work_status=None):
    """手册列表行；draft 摘要仅对超管与所有者返回

    grant 为当前账号在该手册的授权行（视图层预取，无额外查询）；
    is_owner/is_admin 由视图层按授权模型计算（is_admin=平台超管，
    "制度管理员"权限码已废除）。my_roles：所有者恒为 view/edit/publish，
    否则由授权行推导。归属字段为 org_type/org_type_display/org_name
    （2026-10-31 由 owner_* 更名），所有者账号字段 owner_id/owner_name
    与 is_owner/is_admin 同时下发。
    files_count 优先取视图层注解 _active_file_count，未注解时回退查询。
    work_status 为整套工作状态（version_compare.build_manuals_work_status
    的单册结果）：仅对具备草稿访问权（工作区可见口径）的账号由视图层
    传入，仅查看授权为 None——前端不得据修订号/文件名自行推断状态。
    """
    active_file_count = getattr(manual, '_active_file_count', None)
    if active_file_count is None:
        active_file_count = manual.files.filter(is_removed=False).count()
    data = {
        'id': manual.id,
        'name': manual.name,
        'code': manual.code,
        'category_id': manual.category_id,
        'category_name': manual.category.name if manual.category else '',
        'org_type': manual.org_type,
        'org_type_display': manual.get_org_type_display(),
        'org_name': manual.org_name,
        'owner_id': manual.owner_id,
        'owner_name': _user_name(manual.owner),
        'is_owner': bool(is_owner),
        'is_admin': bool(is_admin),
        'status': manual.status,
        'status_display': manual.get_status_display(),
        'files_count': active_file_count,
        'current_version': None,
        'my_roles': my_manual_roles(grant, is_owner),
        'work_status': work_status,
        'created_at': manual.created_at,
        'created_by_name': _user_name(manual.created_by),
    }
    if manual.current_version:
        data['current_version'] = {
            'id': manual.current_version.id,
            'version_no': manual.current_version.version_no,
            'published_at': manual.current_version.published_at,
            'published_by_name': _user_name(manual.current_version.published_by),
        }
    if include_draft:
        # 多文件模型：列表页草稿摘要取首个启用文件的草稿
        first_file = manual.files.filter(is_removed=False).order_by(
            'sort_order', 'id').select_related('draft').first()
        data['draft'] = to_draft_dict(
            getattr(first_file, 'draft', None) if first_file else None)
    else:
        data['draft'] = None
    return data


def to_manual_detail(manual, grant=None, is_owner=False, is_admin=False,
                     include_draft=True):
    data = to_manual_list_item(
        manual, grant=grant, is_owner=is_owner, is_admin=is_admin,
        include_draft=include_draft)
    data.update({
        'has_password': bool(manual.password_hash),
        'password_updated_at': manual.password_updated_at,
        # 是否发布过任何版本（含已废止）：前端据此控制版本历史相关
        # 入口的可见性（草稿缺失时可先在版本历史回退重建）
        'has_versions': manual.versions.exists(),
    })
    return data


def to_session_dict(session, draft):
    return {
        'session_key': session.session_key,
        'expires_at': session.expires_at,
        'revision': draft.revision if draft else 0,
        'file_name': draft.original_name if draft else '',
        'base_version_id': draft.base_version_id if draft else None,
    }


__all__ = [
    'to_category_dict', 'to_version_dict', 'to_version_file_dict',
    'to_draft_dict', 'to_manual_file_dict', 'to_chapter_dict',
    'to_oplog_dict', 'to_manual_list_item', 'to_manual_detail',
    'to_session_dict', 'my_manual_roles',
]

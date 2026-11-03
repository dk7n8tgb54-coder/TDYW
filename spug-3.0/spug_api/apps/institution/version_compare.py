# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""版本对比与变更状态计算（只读展示字段，服务端权威）

为"版本与发布"体验优化（2026-10-29）提供变更语义，全部字段由版本
快照与 SHA256 哈希计算得出，前端不得以文件名或自行推断替代：

- change_type 以同一 manual_file_id 在相邻版本间的 file_hash 比较：
  added=上一版本无此文件（含首个版本的全部文件）/ modified=哈希不同 /
  unchanged=哈希相同（沿用上一版本）/ removed=本版本缺失（上一版本
  存在）；历史版本接口以 removed_items 单独返回被移除文件，不静默隐藏。
- latest_changed_version_no / latest_changed_at：截至该版本（含），
  文件内容最近一次发生变化的版本号与该版本发布时间（首版即视为变化）。
- 发布预检（build_publish_plan）按草稿哈希与当前生效版快照比对，把
  待发布集合分组为 变更/未修改/新增/移除/受阻，供发布确认窗口展示；
  阻断判定仍以发布时 publish_whole_set 的服务端校验为权威。
- 草稿状态总览（build_draft_status，2026-10-29）按同样的哈希比对口径
  输出"逐份文件 草稿 vs 当前生效版本"的关系与整套摘要，供草稿工作区
  与详情页头部展示；权限口径为工作区可见（编制/发布角色或管理权限），
  仅查看角色不可见草稿信息。与发布预检互相独立：本状态只是只读展示，
  不是发布放行凭证。
"""
from collections import Counter
import os

from django.utils import timezone

from . import authorization_services, services, storage
from .models import (
    Manual, ManualDraft, ManualEditSession, ManualFile, ManualSubmission,
    ManualVersion, ManualVersionFile,
)

CHANGE_ADDED = 'added'
CHANGE_MODIFIED = 'modified'
CHANGE_UNCHANGED = 'unchanged'
CHANGE_REMOVED = 'removed'

CHANGE_TYPES = (CHANGE_ADDED, CHANGE_MODIFIED, CHANGE_UNCHANGED, CHANGE_REMOVED)


def get_previous_version(manual, version):
    """该版本的上一发布版本（version_no 紧邻更小）；首版返回 None"""
    return ManualVersion.objects.filter(
        manual_id=manual.id, version_no__lt=version.version_no,
    ).order_by('-version_no').first()


def _classify(snapshot, previous_snapshot):
    """相邻版本快照哈希比较 -> added / unchanged / modified"""
    if previous_snapshot is None:
        return CHANGE_ADDED
    if previous_snapshot.file_hash == snapshot.file_hash:
        return CHANGE_UNCHANGED
    return CHANGE_MODIFIED


def _latest_changed_map(manual, up_to_version_no):
    """截至某版本号（含）每个文件条目最近一次内容变化的版本号

    沿版本链升序逐版比较快照哈希：added/modified 即记录该版本号，
    后续 unchanged 不覆盖。返回 ({manual_file_id: version_no},
    {version_no: ManualVersion})。
    """
    versions = list(ManualVersion.objects.filter(
        manual_id=manual.id, version_no__lte=up_to_version_no,
    ).order_by('version_no'))
    snaps_by_version = {}
    for snap in ManualVersionFile.objects.filter(
            version_id__in=[v.id for v in versions]).order_by('sort_order', 'id'):
        snaps_by_version.setdefault(snap.version_id, []).append(snap)
    latest = {}
    prev_map = {}
    for version in versions:
        for snap in snaps_by_version.get(version.id, []):
            if _classify(snap, prev_map.get(snap.manual_file_id)) != CHANGE_UNCHANGED:
                latest[snap.manual_file_id] = version.version_no
        prev_map = {s.manual_file_id: s for s in snaps_by_version.get(version.id, [])}
    version_by_no = {v.version_no: v for v in versions}
    return latest, version_by_no


def _latest_fields(latest, version_by_no, manual_file_id):
    version_no = latest.get(manual_file_id)
    version = version_by_no.get(version_no) if version_no else None
    return {
        'latest_changed_version_no': version_no,
        'latest_changed_at': version.published_at if version else None,
    }


def compute_version_changes(manual, version):
    """某版本文件清单的变更状态（与上一发布版本逐文件比较）

    Returns:
        dict: {
            'previous_version_no': int 或 None,
            'by_file': {manual_file_id: {change_type, is_changed_from_previous,
                        latest_changed_version_no, latest_changed_at}},
            'removed_items': [上一版本存在、本版本移除的文件行]，
                行含 previous_version_id / previous_snapshot_id，可据以
                预览/下载上一版本中的原快照。
        }
    """
    versions = list(ManualVersion.objects.filter(
        manual_id=manual.id, version_no__lte=version.version_no,
    ).order_by('version_no'))
    index = next((i for i, v in enumerate(versions) if v.id == version.id), None)
    if index is None:
        return {'previous_version_no': None, 'by_file': {}, 'removed_items': []}
    prev_version = versions[index - 1] if index > 0 else None
    snaps_by_version = {}
    for snap in ManualVersionFile.objects.filter(
            version_id__in=[v.id for v in versions]).order_by('sort_order', 'id'):
        snaps_by_version.setdefault(snap.version_id, []).append(snap)
    latest, version_by_no = _latest_changed_map(manual, version.version_no)

    prev_map = ({s.manual_file_id: s
                 for s in snaps_by_version.get(prev_version.id, [])}
                if prev_version else {})
    by_file = {}
    current_ids = set()
    for snap in snaps_by_version.get(version.id, []):
        current_ids.add(snap.manual_file_id)
        change = _classify(snap, prev_map.get(snap.manual_file_id))
        fields = _latest_fields(latest, version_by_no, snap.manual_file_id)
        fields.update({
            'change_type': change,
            'is_changed_from_previous': change != CHANGE_UNCHANGED,
        })
        by_file[snap.manual_file_id] = fields

    removed_items = []
    if prev_version:
        for snap in snaps_by_version.get(prev_version.id, []):
            if snap.manual_file_id in current_ids:
                continue
            row = {
                'file_id': snap.manual_file_id,
                'name': snap.display_name,
                'sort_order': snap.sort_order,
                'file_size': snap.file_size,
                'file_hash': snap.file_hash,
                'change_type': CHANGE_REMOVED,
                'is_changed_from_previous': True,
                'previous_version_id': prev_version.id,
                'previous_snapshot_id': snap.id,
            }
            row.update(_latest_fields(latest, version_by_no, snap.manual_file_id))
            removed_items.append(row)
    return {
        'previous_version_no': prev_version.version_no if prev_version else None,
        'by_file': by_file,
        'removed_items': removed_items,
    }


def compute_file_version_history(manual, file_entry):
    """某制度文件跨全部发布版本的参与记录（"文件变更记录"数据源）

    每行对应一次"包含该文件的发布"，change_type 与相邻上一发布版本中
    同文件快照比较（上一版本不含该文件=added，覆盖被移除后重新纳入）；
    该文件未参与的版本不出现。返回按版本号新→旧排序的 list[dict]，
    行字段 version_id/version_no/change_note/published_at/published_by_name/
    snapshot_id/file_hash/file_size/change_type。
    """
    versions = list(ManualVersion.objects.filter(
        manual_id=manual.id).select_related('published_by').order_by('version_no'))
    snaps = {s.version_id: s for s in ManualVersionFile.objects.filter(
        manual_file_id=file_entry.id, version__manual_id=manual.id)}
    rows = []
    prev_snapshot = None
    for version in versions:
        snap = snaps.get(version.id)
        if snap is None:
            # 该版本不包含此文件：后续重新出现按新增处理
            prev_snapshot = None
            continue
        publisher = version.published_by
        rows.append({
            'version_id': version.id,
            'version_no': version.version_no,
            'change_note': version.change_note,
            'published_at': version.published_at,
            'published_by_name': (
                (publisher.nickname or publisher.username)
                if publisher else ''),
            'snapshot_id': snap.id,
            'file_hash': snap.file_hash,
            'file_size': snap.file_size,
            'change_type': _classify(snap, prev_snapshot),
            # 该次发布快照的物理文件是否已按保留策略清理：清理后仅存
            # 元数据，前端必须关闭预览/下载入口（后端同样拒绝）
            'is_cleaned': snap.cleaned_at is not None,
        })
        prev_snapshot = snap
    rows.reverse()
    return rows


def _publish_blocked_reason(file_entry, draft, user):
    """该文件当前的发布阻断原因；可正常发布返回 None

    reason：no_draft=无草稿 / session_busy=活跃编辑会话（含未完成同步）/
    draft_missing=草稿物理文件缺失或路径非法。
    """
    if not draft or not draft.file_path:
        return {'reason': 'no_draft', 'message': '该文件还没有可发布的草稿'}
    session = file_entry.edit_sessions.filter(
        revoked_at__isnull=True, expires_at__gt=timezone.now(),
    ).order_by('id').first()
    if session:
        return {'reason': 'session_busy',
                'message': '该文件仍有进行中的编辑会话（含未完成的同步）',
                'session': {'is_mine': session.user_id == user.id,
                            'user_name': session.user.username}}
    try:
        src_abs = storage.resolve_absolute_path(draft.file_path)
    except ValueError:
        return {'reason': 'draft_missing', 'message': '草稿路径非法，无法发布'}
    if not os.path.exists(src_abs):
        return {'reason': 'draft_missing',
                'message': '草稿文件不存在或已被清理，请重新编辑后再发布'}
    return None


def _classify_draft_vs_current(draft, snapshot):
    """草稿哈希 vs 当前生效版快照哈希 -> added / unchanged / modified"""
    if snapshot is None:
        return CHANGE_ADDED
    if snapshot.file_hash == draft.file_hash:
        return CHANGE_UNCHANGED
    return CHANGE_MODIFIED


def _owner_display(file_entry):
    """负责人显示名：落库快照优先（账号删除后仍可读），回退账号昵称/账号名"""
    owner_name = file_entry.owner_name
    if not owner_name and file_entry.owner:
        owner_name = (getattr(file_entry.owner, 'nickname', '') or
                      file_entry.owner.username or '')
    return owner_name


def _effective_owner_fields(file_entry):
    """有效负责人增量字段（显式负责人优先，回退手册所有者）"""
    owner = services.effective_owner(file_entry)
    return {
        'effective_owner_id': owner.pk if owner else None,
        'effective_owner_name': services._account_display(owner),
        'owner_assigned': bool(file_entry.owner_id or file_entry.owner_name),
    }


def _plan_row_base(file_entry, draft, user, can_publish=False):
    """发布计划行公共字段：文件结构 + 文件分工（有效负责人与提交状态）

    交接信息全部由服务端计算：owner_id/owner_name（显式分工原值）+
    effective_owner_id/effective_owner_name（owner 为空时回退手册所有者）/
    submission（状态机 payload，含快照提交人/时间）/
    publisher_is_owner（按有效负责人判定，而不是“有发布权就是负责人”）/
    submission_required（本次新增或内容变化且发布人非有效负责人时）/
    content_changed/publish_source（draft/submission/current_version）。
    removed 分组由生效版快照行构造、无文件条目，不带本组字段；草稿缺失
    等原因受阻的行也带本组字段（content_changed 在无法确认时为 False）。
    """
    effective_owner = services.effective_owner(file_entry)
    effective_owner_id = effective_owner.pk if effective_owner else None
    publisher_is_owner = bool(
        effective_owner_id and getattr(user, 'pk', None) and
        effective_owner_id == user.id)
    return {
        'file_id': file_entry.id, 'name': file_entry.display_name,
        'sort_order': file_entry.sort_order,
        'owner_id': file_entry.owner_id,
        'owner_name': _owner_display(file_entry),
        **_effective_owner_fields(file_entry),
        'publisher_is_owner': publisher_is_owner,
        'submission': services.file_submission_state(
            file_entry, draft, user, can_publish=can_publish),
        'submission_required': False,
        'content_changed': False,
        'publish_source': None,
    }


def _publish_plan_rows(manual, user, can_publish=False):
    """发布计划逐文件行（预检内部实现；交接判定由 publish_handoff_blockers
    统一完成，本函数只负责内容关系、来源选择与既有受阻原因）

    每项：{'file_entry', 'draft', 'row', 'change', 'blocked'}。blocked=True
    表示命中既有受阻原因（no_draft/session_busy/draft_missing，沿用原文案、
    优先于交接阻断）；否则 row 已带内容分组字段、change_type 与
    publish_source（未变化=current_version / 本人=草稿 / 他人=提交快照；
    交接未完成时为 None）。
    """
    current = manual.current_version
    current_snaps = ({s.manual_file_id: s for s in current.files.all()}
                     if current else {})
    active_files = list(manual.files.filter(
        is_removed=False).select_related(
        'owner', 'submitted_by', 'manual__owner').order_by(
        'sort_order', 'id'))
    rows = []
    for file_entry in active_files:
        draft = ManualDraft.objects.filter(file=file_entry).first()
        row = _plan_row_base(file_entry, draft, user, can_publish)
        reason = _publish_blocked_reason(file_entry, draft, user)
        if reason:
            row.update(reason)
            row['change_type'] = None
            rows.append({'file_entry': file_entry, 'draft': draft, 'row': row,
                         'change': None, 'blocked': True})
            continue
        snapshot = current_snaps.get(file_entry.id)
        change = _classify_draft_vs_current(draft, snapshot)
        if change == CHANGE_UNCHANGED:
            publish_source = 'current_version'
        elif row['publisher_is_owner']:
            publish_source = 'draft'
        elif row['submission']['state'] == 'submitted':
            publish_source = 'submission'
        else:
            publish_source = None
        row.update({
            'draft_revision': draft.revision,
            'draft_size': draft.file_size,
            'draft_hash': draft.file_hash,
            'current_hash': snapshot.file_hash if snapshot else None,
            'change_type': change,
            'content_changed': change != CHANGE_UNCHANGED,
            'submission_required': (not row['publisher_is_owner'] and
                                    change != CHANGE_UNCHANGED),
            'publish_source': publish_source,
        })
        if snapshot is not None and snapshot.display_name != file_entry.display_name:
            row['renamed'] = True
            row['current_name'] = snapshot.display_name
        rows.append({'file_entry': file_entry, 'draft': draft, 'row': row,
                     'change': change, 'blocked': False})
    return rows


def classify_publish_plan(manual, plan):
    """发布计划逐份内容分类（唯一实现，预检与整套发布共用）

    plan 元素为 (ManualFile, ManualDraft[, src_abs])——预检传二元组、
    publish_whole_set 传 _validate_publishable 的三元组，只取前两项。
    复用 _classify_draft_vs_current：当前生效版无该文件快照=added，
    哈希相同=unchanged，哈希不同=modified；无生效版本时全部 added
    （首次发布语义）。

    Returns:
        list[tuple]: [(file_entry, draft, change_type)]
    """
    current = manual.current_version
    current_snaps = ({s.manual_file_id: s for s in current.files.all()}
                     if current else {})
    classified = []
    for item in plan:
        file_entry, draft = item[0], item[1]
        snapshot = current_snaps.get(file_entry.id)
        classified.append(
            (file_entry, draft,
             _classify_draft_vs_current(draft, snapshot)))
    return classified


def _manifest_base(file_entry, draft, change, effective_owner_id, submission_id=None):
    """manifest 行公共字段（逐文件来源选择的最小固定信息）"""
    return {
        'file': file_entry, 'draft': draft,
        'owner_id': file_entry.owner_id,
        'effective_owner_id': effective_owner_id,
        'change': change,
        'source_snapshot_id': None,
        'submission_id': submission_id,
        'fixed_draft_revision': None,
        'fixed_draft_hash': None,
    }


def _manifest_current_version_entry(file_entry, current_snaps, base):
    """未变化文件：复制当前生效快照（纯改名/排序不改内容，来源不变）"""
    snapshot = current_snaps.get(file_entry.id)
    if snapshot is None:
        return None, '发布计划在计算过程中发生变化，请重试'
    try:
        src_abs = storage.resolve_absolute_path(snapshot.file_path)
    except ValueError:
        return None, f'当前生效版本文件「{snapshot.display_name}」路径非法，无法发布'
    if not os.path.exists(src_abs):
        return None, (f'当前生效版本文件「{snapshot.display_name}」不存在'
                      '或已被清理，无法发布；请先恢复后再试')
    return {**base,
            'source_kind': 'current_version',
            'src_abs': src_abs,
            'source_hash': snapshot.file_hash,
            'source_size': snapshot.file_size,
            'source_snapshot_id': snapshot.id}, None


def _manifest_draft_entry(src_abs, draft, base):
    """发布人=有效负责人：直接纳入当前草稿，固定修订号+哈希"""
    return {**base,
            'source_kind': 'draft',
            'src_abs': src_abs,
            'source_hash': draft.file_hash,
            'source_size': draft.file_size,
            'fixed_draft_revision': draft.revision,
            'fixed_draft_hash': draft.file_hash}, None


def _manifest_submission_entry(file_entry, draft, base):
    """发布人≠有效负责人：只读该负责人有效 pending 快照"""
    submission = services.get_valid_pending_submission(file_entry, draft)
    if not submission:
        return None, (f'文件「{file_entry.display_name}」没有有效的提交待发布核对，'
                      '请负责人重新提交后再发布')
    if submission.file_hash and draft.file_hash and \
            submission.file_hash != draft.file_hash:
        return None, (f'文件「{file_entry.display_name}」提交快照与当前草稿不一致，'
                      '请负责人重新提交后再发布')
    try:
        src_abs = storage.resolve_absolute_path(submission.file_path)
    except ValueError:
        return None, f'提交快照「{submission.original_name}」路径非法，无法发布'
    if not os.path.exists(src_abs):
        return None, (f'提交快照「{submission.original_name}」不存在或已被清理，'
                      '请负责人重新提交后再发布')
    return {**base,
            'source_kind': 'submission',
            'src_abs': src_abs,
            'source_hash': submission.file_hash,
            'source_size': submission.file_size,
            'submission_id': submission.id}, None


def build_publish_manifest(manual, user, plan):
    """整套发布内容来源清单（发布时唯一选择实现，2026-11-03）

    未变化→当前生效快照；变化且发布人=有效负责人→当前草稿；变化且发布人
    ≠有效负责人→有效 pending 提交快照。只选择来源并校验物理存在，不写库；
    落库前由 _commit_publish 用同一函数重算并逐项比对固化签名，防止复制
    期间漂移（任一漂移/失效均清理已复制文件，不消费提交）。

    Returns:
        tuple: (entries 或 None, 错误消息或 None)
    """
    classified = classify_publish_plan(manual, plan)
    current = manual.current_version
    current_snaps = ({s.manual_file_id: s for s in current.files.all()}
                     if current else {})
    entries = []
    for item, (file_entry, draft, change) in zip(plan, classified):
        effective_owner = services.effective_owner(file_entry)
        effective_owner_id = effective_owner.pk if effective_owner else None
        publisher_is_owner = bool(
            effective_owner_id and getattr(user, 'pk', None) and
            effective_owner_id == user.id)
        base = _manifest_base(file_entry, draft, change, effective_owner_id)
        if change == CHANGE_UNCHANGED:
            entry, err = _manifest_current_version_entry(
                file_entry, current_snaps, base)
        elif publisher_is_owner:
            entry, err = _manifest_draft_entry(item[2], draft, base)
        else:
            entry, err = _manifest_submission_entry(file_entry, draft, base)
        if err:
            return None, err
        entries.append(entry)
    return entries, None


def publish_handoff_blockers(manual, user, classified):
    """整套发布的"提交待发布核对"阻断（唯一判定，预检/发布/落库复核共用）

    仅本次新增或内容有变化的文件需要交接：
    - 未变化文件（草稿哈希 == 当前生效快照哈希，含纯改名/排序）不要求
      重复提交；已移除文件不在待发布集合，天然不评估；
    - 有效负责人为空（显式负责人与手册所有者都空）-> unassigned；
    - 发布人就是该文件有效负责人 -> 无需提交（本账号可直接纳入整套发布）；
    - 否则必须有当前有效提交（pending 且 draft_revision == 当前草稿
      revision）：从未提交 -> submission_pending；提交已失效 ->
      submission_stale；撤回/退回后旧快照不可用，同样按未完成交接阻断，
      文案明确状态与原因。
    草稿缺失/物理文件缺失/编辑会话占用由 _publish_blocked_reason 与
    _validate_publishable 优先拦截（既有 reason 与消息保留），本函数不
    重复判断；manual 参数保留供调用方统一签名（判定只依赖文件与用户）。

    Returns:
        list[dict]：file_id/name/reason/message/owner_id/owner_name/
        effective_owner_id/effective_owner_name/submission/
        publisher_is_owner/submission_required/content_changed。
    """
    blockers = []
    for file_entry, draft, change in classified:
        if change == CHANGE_UNCHANGED:
            continue
        effective_owner = services.effective_owner(file_entry)
        effective_owner_id = effective_owner.pk if effective_owner else None
        owner_name = services._account_display(effective_owner)
        publisher_is_owner = bool(
            effective_owner_id and getattr(user, 'pk', None) and
            effective_owner_id == user.id)
        submission = services.file_submission_state(
            file_entry, draft, user, can_publish=True)
        base = {
            'file_id': file_entry.id, 'name': file_entry.display_name,
            'owner_id': file_entry.owner_id,
            'owner_name': _owner_display(file_entry),
            **_effective_owner_fields(file_entry),
            'submission': submission,
            'publisher_is_owner': publisher_is_owner,
            'submission_required': not publisher_is_owner,
            'content_changed': True,
        }
        if effective_owner_id is None:
            blockers.append({**base, 'reason': 'unassigned',
                             'message': (
                                 f'文件「{file_entry.display_name}」未分配有效负责人，'
                                 '本次新增或内容变化须先指定负责人')})
            continue
        if publisher_is_owner:
            continue
        if submission['state'] == 'submitted':
            continue
        status = submission.get('status')
        reason_text = f'负责人「{owner_name}」'
        if submission['state'] == 'stale':
            reason = 'submission_stale'
            message = (f'文件「{file_entry.display_name}」提交待发布核对已失效，'
                       f'请{reason_text}重新提交')
        elif status == 'withdrawn':
            reason = 'submission_pending'
            message = (f'文件「{file_entry.display_name}」的提交已被{reason_text}'
                       '撤回，请重新提交待发布核对')
        elif status == 'returned':
            reason = 'submission_pending'
            reason_detail = submission.get('return_reason') or ''
            tail = f'（退回原因：{reason_detail}）' if reason_detail else ''
            message = (f'文件「{file_entry.display_name}」已被发布人退回修改{tail}，'
                       f'请{reason_text}修改后重新提交待发布核对')
        else:
            reason = 'submission_pending'
            message = (f'文件「{file_entry.display_name}」等待{reason_text}'
                       '提交待发布核对')
        blockers.append({**base, 'reason': reason, 'message': message})
    return blockers


def count_handoff_badge(manual_ids, user_id):
    """菜单红点：待当前用户发布的"已提交待发布核对"文件数（唯一统计口径）

    manual_ids 由调用方按红点可见口径给出（当前用户为所有者或持
    can_publish 授权的启用手册）。统计其中满足全部条件的文件：
    - 未移除；
    - 有效负责人非空且非当前用户（本人是有效负责人的文件本人发布无需交接；
      owner 为空时按手册所有者）；
    - 草稿有效（草稿存在且 file_path 非空）；
    - 存在有效 pending 提交（修订号与当前草稿一致）；
    - 该文件相对当前生效版本为新增或内容变化（无 current_version 视为
      新增；哈希相同=未变化不计，已随发布被消费的提交自然不计）。
    轻量提示计数：不做物理文件 stat，允许数据库哈希比对；权威核对仍在
    publish-preview/publish。
    """
    manual_ids = list(manual_ids)
    if not manual_ids:
        return 0
    files = list(ManualFile.objects.filter(
        manual_id__in=manual_ids, is_removed=False,
        submissions__status=ManualSubmission.STATUS_PENDING,
        draft__file_path__gt='',
    ).select_related('draft', 'owner', 'manual__owner').distinct())
    pending_rows = {
        row.file_id: row for row in ManualSubmission.objects.filter(
            file_id__in=[f.id for f in files],
            status=ManualSubmission.STATUS_PENDING,
        ).order_by('file_id', 'id')
    }
    current_versions = dict(Manual.objects.filter(
        id__in=manual_ids).values_list('id', 'current_version_id'))
    version_ids = {vid for vid in current_versions.values() if vid}
    snaps = {s.manual_file_id: s for s in ManualVersionFile.objects.filter(
        version_id__in=version_ids)}
    count = 0
    for file_entry in files:
        submission = pending_rows.get(file_entry.id)
        if not submission or submission.draft_revision != file_entry.draft.revision:
            continue
        effective_id = services.effective_owner_id(file_entry)
        if effective_id is None or effective_id == user_id:
            continue
        version_id = current_versions.get(file_entry.manual_id)
        snapshot = snaps.get(file_entry.id) if version_id else None
        if version_id is None or snapshot is None:
            # 无生效版本（含废止后）或本版快照不含该文件 = 新增
            count += 1
            continue
        change = _classify_draft_vs_current(file_entry.draft, snapshot)
        if change != CHANGE_UNCHANGED:
            count += 1
    return count


def has_pending_publish_changes(manual, plan):
    """整套发布"有无实际变化"判定（发布端 publish_whole_set 与预检
    can_publish 共用的服务端口径，两处一致）

    plan 是 publish_whole_set 行锁内 _validate_publishable 的产物
    [(file_entry, draft, src_abs)]。当前无生效版本（首次发布或废止后
    再发布）→ 永远视为有变化。否则任一情形即为有变化：
    - 某文件草稿哈希与生效快照不同（内容修改）
    - 生效版无该文件快照（新增文件）
    - 生效版存在的文件已退出待发布集合（移除）
    - 文件显示名与生效快照不同（改名）
    - 双方共有文件的相对次序不同（排序）
    修订进行中（revision_open）本身不是变化：未产生内容/结构变化时
    即使修订开启也不允许发布（拒绝无意义的重复发布，首次发布除外）。
    """
    current = manual.current_version
    if current is None:
        return True
    current_snaps = {s.manual_file_id: s for s in current.files.all()}
    active_ids = [f.id for f, _, _ in plan]
    active_id_set = set(active_ids)
    for file_entry, draft, _ in plan:
        snapshot = current_snaps.get(file_entry.id)
        if snapshot is None:
            return True
        if snapshot.file_hash != draft.file_hash:
            return True
        if snapshot.display_name != file_entry.display_name:
            return True
    if set(current_snaps) - active_id_set:
        return True
    snap_common = [fid for fid in current_snaps if fid in active_id_set]
    return active_ids != snap_common


def _removed_plan_rows(current, current_snaps, active_ids):
    """预检 removed 分组：生效版存在、已退出待发布集合的文件行"""
    if not current:
        return []
    removed = [
        {'file_id': file_id, 'name': snapshot.display_name,
         'sort_order': snapshot.sort_order,
         'file_size': snapshot.file_size,
         'file_hash': snapshot.file_hash,
         'from_version_no': current.version_no}
        for file_id, snapshot in current_snaps.items()
        if file_id not in active_ids
    ]
    removed.sort(key=lambda r: r['sort_order'])
    return removed


def _bucket_plan_rows(row_entries, blockers):
    """把逐文件行按内容分组 / 受阻归类，并统计 blocked reason 计数

    返回 (changed, unchanged, added, blocked, blocker_summary,
    renamed_count, blocked_changed)。既有受阻行（no_draft/session_busy/
    draft_missing）沿用原文案；交接受阻行合并交接字段后进 blocked；其余
    按 change_type 分桶，改名计数只统计未受阻的受影响行。
    blocked_changed 标记"受阻但确属新增/内容变化"的行（交接受阻行本身
    携带 content_changed=True；既有原因行保守为 False），供 has_changes
    汇总——受阻不等于"无变化"，前端不得同时展示"无需重复发布"与受阻
    提示。
    """
    changed, unchanged, added, blocked = [], [], [], []
    buckets = {CHANGE_ADDED: added, CHANGE_UNCHANGED: unchanged,
               CHANGE_MODIFIED: changed}
    blocker_summary = {}
    renamed_count = 0
    blocked_changed = False
    for entry in row_entries:
        row = entry['row']
        if entry['blocked']:
            blocked.append(row)
            reason = row.get('reason')
        else:
            blocker = blockers.get(entry['file_entry'].id)
            if blocker:
                blocked.append({**row, **blocker})
                reason = blocker['reason']
                blocked_changed = blocked_changed or bool(
                    row.get('content_changed'))
            else:
                reason = None
                if row.get('renamed'):
                    renamed_count += 1
                buckets[entry['change']].append(row)
        if reason:
            blocker_summary[reason] = blocker_summary.get(reason, 0) + 1
    return (changed, unchanged, added, blocked, blocker_summary,
            renamed_count, blocked_changed)


def build_publish_plan(manual, user):
    """发布前预检：按草稿与当前生效版快照比对，输出分组发布计划

    分组（全部服务端计算）：
    - changed   本次内容变化（草稿哈希 != 当前生效版同文件快照哈希）
    - unchanged 未修改但会继续纳入新版本（哈希相同，含纯改名/排序）
    - added     新增文件（当前生效版无该文件条目快照）
    - removed   被移除的文件（当前生效版存在、已退出待发布集合）
    - blocked   优先：无草稿 / 草稿文件缺失 / 编辑会话占用（含同步未完
                成），沿用既有 reason 与 message；其次：编制交接未完成
                （unassigned / submission_pending / submission_stale，
                同一判定见 publish_handoff_blockers）。存在任一项时服务端
                将拒绝发布。

    交接字段（除 removed 外所有分行都带）：owner_id / owner_name /
    submission / publisher_is_owner / submission_required / content_changed
    （blocked 中既有原因行保守给 content_changed=False，交接受阻行为 True）。
    有生效版快照的未受阻行携带 renamed/current_name（改名未发布）。

    汇总字段：reordered（共有文件相对次序变化）/ first_publish（当前
    无生效版本）/ has_changes（内容或结构变化：changed/added/removed/
    renamed/reordered 任一非空，或存在"受阻但确属新增/内容变化"的行——
    后者避免新增长期未分配文件时出现 has_changes=False 与 blocked 提示
    自相矛盾）/ can_publish（无受阻且有实际变化——首次发布除外；无变化
    时发布端 publish_whole_set 同样拒绝，两处口径一致，未修改文件不构成
    发布理由）/ blocker_summary（blocked 按 reason 计数，便于前端提示）。
    """
    current = manual.current_version
    current_snaps = ({s.manual_file_id: s for s in current.files.all()}
                     if current else {})
    row_entries = _publish_plan_rows(
        manual, user, authorization_services.can_publish(user, manual))
    ordered_ids = [e['file_entry'].id for e in row_entries]
    active_ids = set(ordered_ids)
    classified = [(e['file_entry'], e['draft'], e['change'])
                  for e in row_entries if not e['blocked']]
    blockers = {b['file_id']: b for b in publish_handoff_blockers(
        manual, user, classified)}
    (changed, unchanged, added, blocked, blocker_summary,
     renamed_count, blocked_changed) = _bucket_plan_rows(row_entries, blockers)
    removed = _removed_plan_rows(current, current_snaps, active_ids)
    reordered = (_draft_reordered(ordered_ids, active_ids, current_snaps)
                 if current else False)
    has_changes = bool(changed or added or removed or renamed_count or
                       reordered or blocked_changed)
    return {
        'current_version_no': current.version_no if current else None,
        'changed': changed, 'unchanged': unchanged, 'added': added,
        'removed': removed, 'blocked': blocked,
        'blocker_summary': blocker_summary,
        'reordered': reordered, 'renamed': renamed_count,
        'first_publish': current is None,
        'has_changes': has_changes,
        'can_publish': (not blocked and
                        (current is None or has_changes)),
    }


# ---------------------------------------------------------------------------
# 草稿状态总览（草稿工作区/详情页头部摘要的数据源，只读展示）

# 逐份文件"草稿 vs 当前生效版本"的关系取值
# unchanged=与生效快照一致 / modified=已修改未发布 / added=新增文件尚未
# 进入生效版本 / awaiting_first_publish=制度尚无生效版本等待首次发布 /
# no_draft=缺草稿 / unconfirmed=暂不能确认（编辑占用或草稿文件缺失）
DRAFT_STATUS_UNCHANGED = CHANGE_UNCHANGED
DRAFT_STATUS_MODIFIED = CHANGE_MODIFIED
DRAFT_STATUS_ADDED = CHANGE_ADDED
DRAFT_STATUS_AWAITING_FIRST_PUBLISH = 'awaiting_first_publish'
DRAFT_STATUS_NO_DRAFT = 'no_draft'
DRAFT_STATUS_UNCONFIRMED = 'unconfirmed'


def _draft_row_blocked(file_entry, draft, user):
    """编辑会话占用/草稿文件缺失 -> unconfirmed 行增量；可确认返回 None

    unconfirmed 表示该文件的内容关系暂不能确认（保存回调可能尚未完成
    或草稿不可发布），调用方绝不能把它归入"无变化"。
    """
    reason = _publish_blocked_reason(file_entry, draft, user)
    if not reason:
        return None
    return {
        'status': DRAFT_STATUS_UNCONFIRMED,
        'unconfirmed_reason': reason['reason'],
        'unconfirmed_message': reason['message'],
        'session': reason.get('session'),
    }


def _draft_row_classified(file_entry, draft, current, snapshot):
    """可确认草稿的内容关系行增量：哈希比较 + 改名标记"""
    row = {'unconfirmed_reason': None, 'unconfirmed_message': None,
           'session': None, 'renamed': False, 'current_name': None}
    if current is None:
        row['status'] = DRAFT_STATUS_AWAITING_FIRST_PUBLISH
    elif snapshot is None:
        row['status'] = DRAFT_STATUS_ADDED
    else:
        row['status'] = _classify_draft_vs_current(draft, snapshot)
        if snapshot.display_name != file_entry.display_name:
            row['renamed'] = True
            row['current_name'] = snapshot.display_name
    return row


def _draft_removed_items(current, current_snaps, active_id_set):
    """生效版存在、已退出待发布集合的文件（移除类待发布变化）"""
    if not current:
        return []
    removed = [
        {'file_id': file_id, 'name': snapshot.display_name,
         'sort_order': snapshot.sort_order,
         'file_size': snapshot.file_size, 'file_hash': snapshot.file_hash,
         'from_version_no': current.version_no}
        for file_id, snapshot in current_snaps.items()
        if file_id not in active_id_set
    ]
    removed.sort(key=lambda r: r['sort_order'])
    return removed


def _draft_reordered(active_ids, active_id_set, current_snaps):
    """双方共有文件在 待发布清单 与 生效版快照 中的相对次序是否不同"""
    active_common = [fid for fid in active_ids if fid in current_snaps]
    snap_common = [fid for fid in current_snaps if fid in active_id_set]
    return active_common != snap_common


def _draft_status_items(active_files, current, current_snaps, user):
    """逐份启用文件的状态行；返回 (items, counts, renamed_count)"""
    counts = Counter()
    items = []
    renamed_count = 0
    for file_entry in active_files:
        base = {'file_id': file_entry.id, 'name': file_entry.display_name,
                'sort_order': file_entry.sort_order,
                # 修订进行中是显式持久状态（发布成功才关闭），与内容
                # 关系分开表达：修订中但内容未变 ≠ 待发布变化
                'revision_open': bool(file_entry.revision_open)}
        draft = ManualDraft.objects.filter(file=file_entry).first()
        if not draft or not draft.file_path:
            counts[DRAFT_STATUS_NO_DRAFT] += 1
            items.append({**base, 'status': DRAFT_STATUS_NO_DRAFT,
                          'has_draft': False, 'draft_revision': None,
                          'draft_size': None, 'renamed': False,
                          'current_name': None,
                          'draft_recovery':
                              services.build_draft_recovery_hint(file_entry)})
            continue
        row = {**base, 'has_draft': True, 'draft_revision': draft.revision,
               'draft_size': draft.file_size, 'draft_hash': draft.file_hash,
               'draft_recovery': None}
        blocked = _draft_row_blocked(file_entry, draft, user)
        if blocked:
            counts[DRAFT_STATUS_UNCONFIRMED] += 1
            items.append({**row, **blocked})
            continue
        classified = _draft_row_classified(
            file_entry, draft, current, current_snaps.get(file_entry.id))
        counts[classified['status']] += 1
        if classified['renamed']:
            renamed_count += 1
        items.append({**row, **classified})
    return items, counts, renamed_count


def _draft_set_summary(active_files, current, counts, removed_items,
                       renamed_count, reordered):
    """整套摘要：计数、是否有待发布变化、是否可确认、是否一致

    revising=修订进行中的文件数（显式持久状态，与内容变化分开）。
    "一致"（已生效、无未发布修改）必须可确认、无缺草稿、无任何待发布
    变化且无进行中的修订——修订开启但内容未变也不声明"一致"。
    """
    revising = sum(1 for f in active_files if f.revision_open)
    if current is None:
        has_pending_changes = bool(active_files)
    else:
        has_pending_changes = bool(
            counts[DRAFT_STATUS_MODIFIED] or counts[DRAFT_STATUS_ADDED]
            or removed_items or renamed_count or reordered)
    determinable = counts[DRAFT_STATUS_UNCONFIRMED] == 0
    # "已生效，无未发布修改"必须可确认且无缺草稿/无待发布变化/无修订进行中，
    # 绝不带病声明
    consistent = bool(
        current is not None and determinable
        and counts[DRAFT_STATUS_NO_DRAFT] == 0 and not has_pending_changes
        and not revising)
    return {
        'total_files': len(active_files),
        'unchanged': counts[DRAFT_STATUS_UNCHANGED],
        'modified': counts[DRAFT_STATUS_MODIFIED],
        'added': counts[DRAFT_STATUS_ADDED],
        'awaiting_first_publish':
            counts[DRAFT_STATUS_AWAITING_FIRST_PUBLISH],
        'no_draft': counts[DRAFT_STATUS_NO_DRAFT],
        'unconfirmed': counts[DRAFT_STATUS_UNCONFIRMED],
        'removed': len(removed_items),
        'renamed': renamed_count,
        'reordered': reordered,
        'revising': revising,
        'has_current_version': current is not None,
        'current_version_no': current.version_no if current else None,
        'has_pending_changes': has_pending_changes,
        'determinable': determinable,
        'consistent': consistent,
    }


def build_draft_status(manual, user):
    """草稿状态总览：逐份文件 草稿 vs 当前生效版本 + 整套待发布变化摘要

    与 build_publish_plan 同口径的内容比较（草稿哈希 vs 生效版快照
    哈希，服务端权威；前端不得以修订号或文件名推断内容是否变化），
    但定位不同：本函数面向状态展示，包含整套结构性变化（移除/改名/
    排序），供编制者与发布者只读查看；发布权威校验仍在
    publish_whole_set 行锁内复核，本状态不是放行凭证。

    - 发布后保留的草稿与新生效版快照哈希一致，自动归入 unchanged。
    - 编辑会话占用（含未完成同步/保存回调）或草稿物理文件缺失：
      status=unconfirmed，绝不冒充"无变化"。

    Returns:
        dict: has_current_version/current_version_no/items（逐份启用
        文件行：file_id/name/sort_order/has_draft/draft_revision/
        draft_size/status/unconfirmed_*/session/renamed/current_name/
        draft_recovery（缺草稿时））/removed_items（生效版存在但已
        移除）/summary（各状态计数 + renamed/reordered + has_pending_
        changes/determinable/consistent）。
    """
    current = manual.current_version
    current_snaps = {}
    if current:
        current_snaps = {s.manual_file_id: s for s in
                         current.files.order_by('sort_order', 'id')}
    active_files = list(manual.files.filter(
        is_removed=False).order_by('sort_order', 'id'))
    active_ids = [f.id for f in active_files]
    items, counts, renamed_count = _draft_status_items(
        active_files, current, current_snaps, user)
    removed_items = _draft_removed_items(
        current, current_snaps, set(active_ids))
    reordered = (_draft_reordered(active_ids, set(active_ids), current_snaps)
                 if current else False)
    return {
        'has_current_version': current is not None,
        'current_version_no': current.version_no if current else None,
        'items': items,
        'removed_items': removed_items,
        'summary': _draft_set_summary(
            active_files, current, counts, removed_items,
            renamed_count, reordered),
    }


# ---------------------------------------------------------------------------
# 制度列表工作状态（列表页"打开即知下一步"的批量只读计算）

# 列表行工作状态枚举（前端只做文案映射，不自行推断）
# synced=已生效无未发布修改（有生效版本、可确认无待发布变化且无修订进行中）/
# awaiting_first_publish=待首次发布 / pending_changes=有文件待发布变化 /
# revising=修订进行中（无待发布变化但修订轮开启）/
# editing=编辑中（会话占用，含未完成同步，状态暂不能确认）/
# missing_draft=缺少草稿 / unverifiable=状态无法确认（草稿文件缺失等，
# 非会话原因）/ no_files=未上传文件
WORK_STATUS_SYNCED = 'synced'
WORK_STATUS_AWAITING_FIRST_PUBLISH = 'awaiting_first_publish'
WORK_STATUS_PENDING_CHANGES = 'pending_changes'
WORK_STATUS_REVISING = 'revising'
WORK_STATUS_EDITING = 'editing'
WORK_STATUS_MISSING_DRAFT = 'missing_draft'
WORK_STATUS_UNVERIFIABLE = 'unverifiable'
WORK_STATUS_NO_FILES = 'no_files'


def _work_status_from_summary(summary, session_busy):
    """整套摘要 -> 列表状态枚举（编辑中优先于其他不可确认原因）

    会话占用（含未完成同步）意味着编辑器可能还有未落盘内容，该文件的
    内容关系暂时无法确认，状态展示为"编辑中"；草稿文件缺失等其余不可
    确认原因为"状态无法确认"。两者都不冒充"已生效/无变化"。
    修订进行中（revising）只在无待发布变化时单独呈现——有待发布变化时
    pending_changes 优先（更接近发布动作）。
    """
    if summary['total_files'] == 0:
        return WORK_STATUS_NO_FILES
    if session_busy:
        return WORK_STATUS_EDITING
    if summary['unconfirmed']:
        return WORK_STATUS_UNVERIFIABLE
    if summary['no_draft']:
        return WORK_STATUS_MISSING_DRAFT
    if not summary['has_current_version']:
        return WORK_STATUS_AWAITING_FIRST_PUBLISH
    if summary['has_pending_changes']:
        return WORK_STATUS_PENDING_CHANGES
    if summary['revising']:
        return WORK_STATUS_REVISING
    return WORK_STATUS_SYNCED


def _batch_count_file_states(active_files, current, current_snaps,
                             drafts_by_file, sessions_by_file):
    """批量逐文件状态计数（与 _draft_status_items 同口径）

    Returns:
        tuple: (counts, session_busy, renamed_count)
    """
    counts = Counter()
    session_busy = 0
    renamed_count = 0
    for file_entry in active_files:
        draft = drafts_by_file.get(file_entry.id)
        if not draft or not draft.file_path:
            counts[DRAFT_STATUS_NO_DRAFT] += 1
            continue
        if sessions_by_file.get(file_entry.id):
            counts[DRAFT_STATUS_UNCONFIRMED] += 1
            session_busy += 1
            continue
        try:
            src_abs = storage.resolve_absolute_path(draft.file_path)
        except ValueError:
            counts[DRAFT_STATUS_UNCONFIRMED] += 1
            continue
        if not os.path.exists(src_abs):
            counts[DRAFT_STATUS_UNCONFIRMED] += 1
            continue
        snapshot = current_snaps.get(file_entry.id)
        if current is None:
            counts[DRAFT_STATUS_AWAITING_FIRST_PUBLISH] += 1
        elif snapshot is None:
            counts[DRAFT_STATUS_ADDED] += 1
        else:
            counts[_classify_draft_vs_current(draft, snapshot)] += 1
            if snapshot.display_name != file_entry.display_name:
                renamed_count += 1
    return counts, session_busy, renamed_count


def _prefetch_work_status_data(manuals):
    """批量预取 状态计算所需的 快照/文件/草稿/会话（各一次查询）"""
    current_ids = [m.current_version_id for m in manuals
                   if m.current_version_id]
    snaps_by_version = {}
    if current_ids:
        for snap in ManualVersionFile.objects.filter(
                version_id__in=current_ids).order_by('sort_order', 'id'):
            snaps_by_version.setdefault(snap.version_id, []).append(snap)
    manual_ids = [m.id for m in manuals]
    files_by_manual = {}
    if manual_ids:
        for file_entry in ManualFile.objects.filter(
                manual_id__in=manual_ids,
                is_removed=False).order_by('sort_order', 'id'):
            files_by_manual.setdefault(file_entry.manual_id, []).append(
                file_entry)
    file_ids = [f.id for rows in files_by_manual.values() for f in rows]
    drafts_by_file = {}
    sessions_by_file = {}
    if file_ids:
        for draft in ManualDraft.objects.filter(file_id__in=file_ids):
            drafts_by_file[draft.file_id] = draft
        # 与 _publish_blocked_reason 同口径：同文件取 id 最小的活跃会话
        for session in ManualEditSession.objects.filter(
                file_id__in=file_ids, revoked_at__isnull=True,
                expires_at__gt=timezone.now()).order_by('id'):
            sessions_by_file.setdefault(session.file_id, session)
    return snaps_by_version, files_by_manual, drafts_by_file, sessions_by_file


def build_manuals_work_status(manuals):
    """制度列表的整套工作状态（批量只读，与 build_draft_status 同口径）

    内容关系（草稿哈希 vs 当前生效版快照哈希）、结构性变化（移除/
    改名/排序）与 unconfirmed 判定复用 build_draft_status 的比较口径，
    仅改为整页批量预取（快照/文件/草稿/会话各一次查询），避免逐手册
    重复实现状态语义；summary 字段与 build_draft_status 的 summary
    完全一致（一致性由测试钉死）。哪些账号可见草稿状态（工作区可见
    口径：编制/发布角色或管理权限）由调用方逐手册判定——仅查看角色
    不下发 work_status。

    Returns:
        dict: {manual_id: {**summary, 'status': 枚举, 'session_busy': n}}
        summary 含 total_files/unchanged/modified/added/awaiting_first_
        publish/no_draft/unconfirmed/removed/renamed/reordered/revising/
        has_current_version/current_version_no/has_pending_changes/
        determinable/consistent。
    """
    manuals = list(manuals)
    (snaps_by_version, files_by_manual,
     drafts_by_file, sessions_by_file) = _prefetch_work_status_data(manuals)
    result = {}
    for manual in manuals:
        current = manual.current_version
        current_snaps = (
            {s.manual_file_id: s for s in snaps_by_version.get(current.id, [])}
            if current else {})
        active_files = files_by_manual.get(manual.id, [])
        active_ids = [f.id for f in active_files]
        counts, session_busy, renamed_count = _batch_count_file_states(
            active_files, current, current_snaps,
            drafts_by_file, sessions_by_file)
        removed_items = _draft_removed_items(
            current, current_snaps, set(active_ids))
        reordered = (_draft_reordered(active_ids, set(active_ids),
                                      current_snaps) if current else False)
        summary = _draft_set_summary(
            active_files, current, counts, removed_items,
            renamed_count, reordered)
        summary['status'] = _work_status_from_summary(summary, session_busy)
        summary['session_busy'] = session_busy
        result[manual.id] = summary
    return result

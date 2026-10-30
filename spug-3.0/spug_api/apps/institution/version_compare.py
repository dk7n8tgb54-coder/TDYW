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

from . import services, storage
from .models import (
    ManualDraft, ManualEditSession, ManualFile, ManualVersion,
    ManualVersionFile,
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


def _plan_row_base(file_entry, draft):
    """发布计划行公共字段：文件结构 + 文件分工（负责人与提交编制状态）

    负责人与提交状态是发布者核对的交接信息（服务端计算，state=
    none/submitted/stale），只作展示——提交与否、是否负责人都不改变
    can_publish 与 publish_whole_set 的任何校验（第一阶段不新增阻断）。
    removed 分组由生效版快照行构造、无文件条目，不带本组字段。
    """
    owner_name = file_entry.owner_name
    if not owner_name and file_entry.owner:
        owner_name = (getattr(file_entry.owner, 'nickname', '') or
                      file_entry.owner.username or '')
    return {
        'file_id': file_entry.id, 'name': file_entry.display_name,
        'sort_order': file_entry.sort_order,
        'owner_name': owner_name,
        'submission': services.file_submission_state(file_entry, draft),
    }


def _publish_plan_row(file_entry, current_snaps, user):
    """单份文件的预检行：受阻增量或 分组行（changed/unchanged/added）

    Returns:
        tuple: (reason_dict 或 None, row_dict, 分组键 change_type)。
        reason 非 None 时该文件进入 blocked 分组，row 为公共字段
        （文件结构+分工），调用方与 reason 合并。
    """
    draft = ManualDraft.objects.filter(file=file_entry).first()
    base = _plan_row_base(file_entry, draft)
    reason = _publish_blocked_reason(file_entry, draft, user)
    if reason:
        return reason, base, None
    snapshot = current_snaps.get(file_entry.id)
    row = {**base, 'draft_revision': draft.revision,
           'draft_size': draft.file_size, 'draft_hash': draft.file_hash,
           'current_hash': snapshot.file_hash if snapshot else None}
    change = _classify_draft_vs_current(draft, snapshot)
    row['change_type'] = change
    if snapshot is not None and snapshot.display_name != file_entry.display_name:
        row['renamed'] = True
        row['current_name'] = snapshot.display_name
    return None, row, change


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


def build_publish_plan(manual, user):
    """发布前预检：按草稿与当前生效版快照比对，输出分组发布计划

    分组（全部服务端计算）：
    - changed   本次内容变化（草稿哈希 != 当前生效版同文件快照哈希）
    - unchanged 未修改但会继续纳入新版本（哈希相同）
    - added     新增文件（当前生效版无该文件条目快照）
    - removed   被移除的文件（当前生效版存在、已退出待发布集合）
    - blocked   无草稿 / 草稿文件缺失 / 编辑会话占用（含同步未完成），
                存在任一项时服务端将拒绝发布

    除 removed 外各分行携带 owner_name 与 submission（文件分工交接
    信息，仅供发布者核对，不参与 can_publish 判定），有生效版快照的
    行携带 renamed/current_name（改名未发布）。

    汇总字段：reordered（共有文件相对次序变化）/ first_publish（当前
    无生效版本）/ has_changes（内容或结构变化：changed/added/removed/
    renamed/reordered 任一非空）/ can_publish（无受阻且有实际变化——
    首次发布除外；无变化时发布端 publish_whole_set 同样拒绝，两处
    口径一致，未修改文件不构成发布理由）。
    """
    current = manual.current_version
    current_snaps = ({s.manual_file_id: s for s in current.files.all()}
                     if current else {})
    active_files = list(manual.files.filter(
        is_removed=False).select_related('owner', 'submitted_by').order_by(
        'sort_order', 'id'))
    ordered_ids = [f.id for f in active_files]
    active_ids = set(ordered_ids)
    changed, unchanged, added, blocked = [], [], [], []
    buckets = {CHANGE_ADDED: added, CHANGE_UNCHANGED: unchanged,
               CHANGE_MODIFIED: changed}
    renamed_count = 0
    for file_entry in active_files:
        reason, row, change = _publish_plan_row(
            file_entry, current_snaps, user)
        if reason:
            blocked.append({**row, **reason})
            continue
        if row.get('renamed'):
            renamed_count += 1
        buckets[change].append(row)
    removed = _removed_plan_rows(current, current_snaps, active_ids)
    reordered = (_draft_reordered(ordered_ids, active_ids, current_snaps)
                 if current else False)
    has_changes = bool(changed or added or removed or renamed_count or reordered)
    return {
        'current_version_no': current.version_no if current else None,
        'changed': changed, 'unchanged': unchanged, 'added': added,
        'removed': removed, 'blocked': blocked,
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

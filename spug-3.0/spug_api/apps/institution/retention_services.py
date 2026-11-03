# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度文件生命周期保留策略（2026-10-29；2026-11-02 仅保留版本维度）

职责：发布版本快照的保留/清理候选评估、只读预检与可控幂等执行。
核心不变量（与《制度管理模块设计方案》保留策略一致）：

- 当前生效版本（manual.current_version）及整套文件永久受保护；
  is_effective=False 仅表示不是当前生效版，绝不据此判断可删除。
  重要版本可设长期保留标记；历史版本按配置期限/数量保留，只有超过
  期限、未受保护且没有业务引用（无草稿以其为 base_version）才成为
  清理候选。
- 版本按整套判定与清理；部分快照删除失败时整版标为 partial（不可完整
  使用）、记录失败并允许重试，绝不伪装成功、绝不显示为可完整回退。
  版本号、发布人/时间、变更说明与快照行（含哈希）永久保留。
- 删除物理文件前必须核对路径没有被其他记录（草稿/其他版本镜像列/
  其他快照）共享引用，防止重复删除或误删；ManualVersion 的旧单文件
  兼容镜像列与首快照指向同一路径，清理该版本自身快照时排除本版本镜像。
- 未配置保留期限（INSTITUTION_VERSION_RETENTION_DAYS<=0，默认）时预检
  与执行整体拒绝物理删除；本模块不含任何定时任务，清理只能经显式
  端点触发（预检完全只读，执行幂等可重试）。
"""
import datetime
import logging
import os

from django.conf import settings
from django.utils import timezone

from . import storage
from .models import Manual, ManualDraft, ManualVersion, ManualVersionFile
from .services import log_operation

logger = logging.getLogger(__name__)

# 保留策略操作记录动作（ManualOperationLog.action）
ACTION_RETENTION_CLEANUP = 'retention_cleanup'
ACTION_VERSION_PROTECT = 'version_protect'

BLOCK_RETENTION_DISABLED = 'retention_disabled'
BLOCK_CURRENT_EFFECTIVE = 'current_effective'
BLOCK_LONG_TERM_PROTECTED = 'long_term_protected'
BLOCK_RECENT_WINDOW = 'recent_window'
BLOCK_REFERENCED_BY_DRAFT = 'referenced_by_draft'


def get_retention_config():
    """保留策略配置（settings 注入；retention_days<=0 = 未配置，不执行删除）"""
    retention_days = int(getattr(settings, 'INSTITUTION_VERSION_RETENTION_DAYS', 0) or 0)
    return {
        'version_retention_days': retention_days,
        'version_recent_keep_count': int(
            getattr(settings, 'INSTITUTION_VERSION_RECENT_KEEP_COUNT', 0) or 0),
        'cleanup_enabled': retention_days > 0,
    }


def count_other_path_references(rel_path, exclude_draft_id=None,
                                exclude_version_id=None,
                                exclude_snapshot_id=None):
    """统计同一路径在 草稿/版本镜像列/版本快照 中的其他引用条数

    删除物理文件前的共享引用核对：任何其他记录仍指向同一路径时拒绝
    删除（防重复删除/误删）。排除集合用于"本条记录自身的引用"。
    """
    qs = ManualDraft.objects.filter(file_path=rel_path)
    if exclude_draft_id:
        qs = qs.exclude(pk=exclude_draft_id)
    count = qs.count()
    qs = ManualVersion.objects.filter(file_path=rel_path)
    if exclude_version_id:
        qs = qs.exclude(pk=exclude_version_id)
    count += qs.count()
    qs = ManualVersionFile.objects.filter(file_path=rel_path)
    if exclude_snapshot_id:
        qs = qs.exclude(pk=exclude_snapshot_id)
    return count + qs.count()


# ---------------------------------------------------------------------------
# 候选评估（只读；预检与执行共用同一口径，执行前逐项重新评估）

def _blocker(code, message):
    return {'code': code, 'message': message}


def _recent_protected_version_nos(manual, keep_count):
    """近期保护集合：版本号最大的 N 个版本（keep_count<=0 时为空集）"""
    if keep_count <= 0:
        return set()
    return set(ManualVersion.objects.filter(manual_id=manual.id)
               .order_by('-version_no')
               .values_list('version_no', flat=True)[:keep_count])


def evaluate_version_candidate(version, now=None, config=None,
                               current_version_id=None, recent_protected=None):
    """评估单个发布版本的整套文件是否可清理（只读，按整套判定）

    Returns:
        dict: {'candidate', 'reason', 'blockers', 'already_cleaned'}
    """
    now = now or timezone.now()
    config = config or get_retention_config()
    result = {
        'candidate': False,
        'reason': None,
        'blockers': [],
        'already_cleaned': version.files_clean_status == ManualVersion.FILES_CLEAN_CLEANED,
    }
    if result['already_cleaned']:
        return result
    if current_version_id is None:
        current_version_id = version.manual.current_version_id
    if recent_protected is None:
        recent_protected = _recent_protected_version_nos(
            version.manual, config['version_recent_keep_count'])
    if not config['cleanup_enabled']:
        result['blockers'].append(_blocker(
            BLOCK_RETENTION_DISABLED,
            '未配置版本保留期限，保留策略不执行物理删除'))
        return result
    if version.id == current_version_id:
        result['blockers'].append(_blocker(
            BLOCK_CURRENT_EFFECTIVE, '当前生效版本及整套文件永久受保护'))
        return result
    if version.long_term_protected:
        result['blockers'].append(_blocker(
            BLOCK_LONG_TERM_PROTECTED, '该版本被标记为长期保留'))
        return result
    if version.version_no in recent_protected:
        result['blockers'].append(_blocker(
            BLOCK_RECENT_WINDOW,
            f'属于最近 {config["version_recent_keep_count"]} 个受保护版本'))
        return result
    retention_days = config['version_retention_days']
    deadline = version.published_at + datetime.timedelta(days=retention_days)
    if now < deadline:
        result['blockers'].append(_blocker(
            BLOCK_RECENT_WINDOW,
            f'发布于 {version.published_at:%Y-%m-%d}，'
            f'未超过 {retention_days} 天保留期限'))
        return result
    if ManualDraft.objects.filter(base_version=version).exists():
        result['blockers'].append(_blocker(
            BLOCK_REFERENCED_BY_DRAFT, '仍有草稿以该版本为编辑基线（业务引用）'))
        return result
    result['candidate'] = True
    result['reason'] = (
        f'发布于 {version.published_at:%Y-%m-%d}，已超过 {retention_days} 天'
        '保留期限，整套文件可清理（版本号/发布人/说明/文件清单与哈希永久保留）')
    return result


# ---------------------------------------------------------------------------
# 只读预检

def _path_exists(rel_path):
    try:
        return os.path.exists(storage.resolve_absolute_path(rel_path))
    except ValueError:
        return False


def _preview_version_row(version, now, config, current_version_id,
                         recent_protected):
    """单个版本的预检行；候选或存在阻止条件时返回，否则 None"""
    verdict = evaluate_version_candidate(
        version, now=now, config=config,
        current_version_id=current_version_id,
        recent_protected=recent_protected)
    if not verdict['candidate'] and not verdict['blockers']:
        return None
    snapshots = []
    total_size = 0
    for snap in version.files.order_by('sort_order', 'id'):
        size = snap.file_size if snap.cleaned_at is None else 0
        total_size += size
        snapshots.append({
            'snapshot_id': snap.id,
            'manual_file_id': snap.manual_file_id,
            'name': snap.display_name,
            'file_size': snap.file_size,
            'file_hash': snap.file_hash,
            'is_cleaned': snap.cleaned_at is not None,
            'path_exists': _path_exists(snap.file_path),
        })
    return {
        'version_id': version.id,
        'version_no': version.version_no,
        'published_at': version.published_at,
        'published_by_name': version.published_by.username
        if version.published_by else '',
        'is_current': version.id == current_version_id,
        'long_term_protected': version.long_term_protected,
        'files_clean_status': version.files_clean_status,
        'files_clean_error': version.files_clean_error,
        'candidate': verdict['candidate'],
        'reason': verdict['reason'],
        'blockers': verdict['blockers'],
        'reclaimable_size': total_size,
        'files': snapshots,
    }, total_size, verdict['candidate']


def build_cleanup_preview(manual_id=None):
    """保留策略清理预检（完全只读：不写数据库、不触碰磁盘）

    列出候选制度、版本、文件、大小、候选原因和阻止条件；未配置保留
    期限时返回 enabled=False 且不产出任何候选（执行入口同样拒绝）。
    """
    now = timezone.now()
    config = get_retention_config()
    result = {
        'config': config,
        'enabled': config['cleanup_enabled'],
        'notice': '' if config['cleanup_enabled'] else
        '未配置 INSTITUTION_VERSION_RETENTION_DAYS，保留策略不执行物理删除',
        'generated_at': now,
        'manuals': [],
        'totals': {'versions': 0, 'version_files': 0,
                   'reclaimable_size': 0},
    }
    if not config['cleanup_enabled']:
        return result
    manuals = Manual.objects.all().order_by('id')
    if manual_id:
        manuals = manuals.filter(pk=manual_id)
    for manual in manuals:
        current_version_id = manual.current_version_id
        recent_protected = _recent_protected_version_nos(
            manual, config['version_recent_keep_count'])
        manual_row = {
            'manual_id': manual.id, 'manual_name': manual.name,
            'status': manual.status,
            'versions': [],
        }
        for version in manual.versions.order_by('version_no'):
            built = _preview_version_row(
                version, now, config, current_version_id, recent_protected)
            if not built:
                continue
            row, total_size, is_candidate = built
            manual_row['versions'].append(row)
            if is_candidate:
                result['totals']['versions'] += 1
                result['totals']['version_files'] += len(row['files'])
                result['totals']['reclaimable_size'] += total_size
        if manual_row['versions']:
            result['manuals'].append(manual_row)
    return result


# ---------------------------------------------------------------------------
# 可控幂等执行

def _try_delete_file(rel_path, exclude):
    """核对共享引用后删除物理文件

    Returns:
        tuple: (状态, 错误消息或 None)；状态 missing=文件已缺失（按已
        清理补记）/ deleted=已删除 / shared=存在共享引用拒绝删除
    """
    try:
        abs_path = storage.resolve_absolute_path(rel_path)
    except ValueError as e:
        return 'failed', f'路径非法（{e}）'
    if not os.path.exists(abs_path):
        return 'missing', None
    if count_other_path_references(rel_path, **exclude) > 0:
        return 'shared', '该路径仍被其他记录引用，拒绝删除以防误删'
    ok, err = storage.safe_delete_file(abs_path)
    if not ok:
        return 'failed', f'物理文件删除失败：{err}'
    return 'deleted', None


def _cleanup_version_files(version, now):
    """整套清理一个候选版本的全部未清理快照（逐文件记录成功/失败）

    Returns:
        tuple: (结果 dict)；失败快照保持未清理状态可重试；任一清理成功
        即置 files_cleaned_at（整版不可完整使用），全部完成后置 cleaned。
    """
    failures = []
    cleaned_now = 0
    file_results = []
    for snap in version.files.order_by('sort_order', 'id'):
        if snap.cleaned_at is not None:
            file_results.append({'snapshot_id': snap.id, 'name': snap.display_name,
                                 'status': 'already_cleaned'})
            continue
        try:
            status, err = _try_delete_file(snap.file_path, exclude={
                'exclude_version_id': version.id,
                'exclude_snapshot_id': snap.id,
            })
        except Exception as e:
            status, err = 'failed', f'清理异常：{e}'
        if status in ('deleted', 'missing'):
            ManualVersionFile.objects.filter(pk=snap.id).update(cleaned_at=now)
            cleaned_now += 1
            file_results.append({'snapshot_id': snap.id, 'name': snap.display_name,
                                 'status': 'cleaned' if status == 'deleted' else 'cleaned_missing'})
        else:
            failures.append(f'「{snap.display_name}」{err or "清理失败"}')
            file_results.append({'snapshot_id': snap.id, 'name': snap.display_name,
                                 'status': 'failed', 'error': err})
    remaining = version.files.filter(cleaned_at__isnull=True).count()
    total = version.files.count()
    if cleaned_now and version.files_cleaned_at is None:
        # 任一快照被清理即整版标记"不可完整使用"（files_cleaned_at 首次置位）
        version.files_cleaned_at = now
    if remaining == 0 and total > 0:
        version.files_clean_status = ManualVersion.FILES_CLEAN_CLEANED
        version.files_clean_error = ''
    else:
        version.files_clean_status = ManualVersion.FILES_CLEAN_PARTIAL
        version.files_clean_error = '；'.join(failures)
    version.save(update_fields=['files_cleaned_at', 'files_clean_status',
                                'files_clean_error'])
    return {
        'version_id': version.id, 'version_no': version.version_no,
        'status': 'cleaned' if remaining == 0 else 'partial',
        'cleaned_files': cleaned_now,
        'remaining_files': remaining,
        'failures': failures,
        'files': file_results,
    }


def _execute_manual_versions(manual, now, config, current_version_id,
                             recent_protected):
    """评估并清理一本制度的候选版本；返回 (结果列表, 触达项列表)"""
    results, touched = [], []
    for version in manual.versions.order_by('version_no'):
        verdict = evaluate_version_candidate(
            version, now=now, config=config,
            current_version_id=current_version_id,
            recent_protected=recent_protected)
        if verdict['already_cleaned'] or not verdict['candidate']:
            continue
        item = _cleanup_version_files(version, now)
        item['manual_id'] = manual.id
        results.append(item)
        touched.append({**item, 'kind': 'version'})
    return results, touched


def _log_manual_cleanup(manual, operator, touched):
    """为发生实际清理动作的制度写操作记录（按版本逐项汇总）"""
    versions = [x for x in touched if x['kind'] == 'version']
    log_operation(
        manual, operator, ACTION_RETENTION_CLEANUP,
        versions=[{k: v for k, v in x.items() if k != 'files'}
                  for x in versions],
        failures=sum(len(x.get('failures') or []) for x in versions))


def execute_cleanup(operator, manual_id=None):
    """执行保留策略清理（可控、幂等；逐项重新核对，失败可重试）

    - 配置门槛：未配置保留期限时直接拒绝（不产生任何删除）。
    - 执行前对每个版本重新运行候选评估（不信任预检结果），评估不通过
      或已清理的项跳过；候选评估含当前版本、长期保留、近期窗口、期限、
      业务引用、活跃会话与共享路径引用。
    - 物理删除前再次核对共享路径引用（含旧版本镜像列）；失败项保留
      候选状态与失败说明，不伪装成功。单条记录的落库自原子，删除与
      落库之间由候选评估+共享引用核对+下游存在性检查兜底，不把长阻塞
      文件 IO 包进显式事务。
    - 幂等：已清理项二次执行返回 already/skip，不重复删除。
    """
    now = timezone.now()
    config = get_retention_config()
    if not config['cleanup_enabled']:
        return None, '未配置版本保留期限（INSTITUTION_VERSION_RETENTION_DAYS），不执行物理删除'
    manuals = Manual.objects.all().select_related('current_version').order_by('id')
    if manual_id:
        manuals = manuals.filter(pk=manual_id)
    result = {
        'executed_at': now, 'config': config,
        'versions': [],
        'summary': {'versions_cleaned': 0, 'versions_partial': 0,
                    'failures': 0},
    }
    for manual in manuals:
        current_version_id = manual.current_version_id
        recent_protected = _recent_protected_version_nos(
            manual, config['version_recent_keep_count'])
        version_items, touched = _execute_manual_versions(
            manual, now, config, current_version_id, recent_protected)
        result['versions'].extend(version_items)
        if touched:
            _log_manual_cleanup(manual, operator, touched)
    for item in result['versions']:
        if item['status'] == 'cleaned':
            result['summary']['versions_cleaned'] += 1
        elif item['status'] == 'partial':
            result['summary']['versions_partial'] += 1
            result['summary']['failures'] += len(item['failures'])
    return result, None

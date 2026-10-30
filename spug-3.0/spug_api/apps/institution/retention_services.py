# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度文件生命周期保留策略（2026-10-29）

职责：原稿与发布版本的保留/清理候选评估、只读预检与可控幂等执行。
核心不变量（与《制度管理模块设计方案》保留策略一致）：

- 原稿保护边界 = 「该文件首次进入成功发布的版本」；在此之前原稿本体
  永久保留。首次发布并经过配置缓冲期后，原稿本体才可成为清理候选；
  记录行与来源元数据（名称/上传人/时间/哈希/路径/清理时间）永久保留。
- 当前生效版本（manual.current_version）及整套文件永久受保护；
  is_effective=False 仅表示不是当前生效版，绝不据此判断可删除。
  重要版本可设长期保留标记；历史版本按配置期限/数量保留，只有超过
  期限、未受保护且没有业务引用（无草稿以其为 base_version）才成为
  清理候选。
- 版本按整套判定与清理；部分快照删除失败时整版标为 partial（不可完整
  使用）、记录失败并允许重试，绝不伪装成功、绝不显示为可完整回退。
  版本号、发布人/时间、变更说明与快照行（含哈希）永久保留。
- 删除物理文件前必须核对路径没有被其他记录（原稿/草稿/其他版本镜像列/
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
from .models import (Manual, ManualDraft, ManualOriginal, ManualVersion,
                     ManualVersionFile)
from .services import get_active_session_for_file, log_operation

logger = logging.getLogger(__name__)

# 保留策略操作记录动作（ManualOperationLog.action）
ACTION_RETENTION_CLEANUP = 'retention_cleanup'
ACTION_VERSION_PROTECT = 'version_protect'

BLOCK_RETENTION_DISABLED = 'retention_disabled'
BLOCK_NEVER_PUBLISHED = 'never_published'
BLOCK_BUFFER_NOT_ELAPSED = 'buffer_not_elapsed'
BLOCK_DRAFT_SOURCE = 'draft_source_reference'
BLOCK_ACTIVE_SESSION = 'active_session'
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
        'original_clean_buffer_days': int(
            getattr(settings, 'INSTITUTION_ORIGINAL_CLEAN_BUFFER_DAYS', 0) or 0),
        'cleanup_enabled': retention_days > 0,
    }


def count_other_path_references(rel_path, exclude_original_id=None,
                                exclude_draft_id=None, exclude_version_id=None,
                                exclude_snapshot_id=None):
    """统计同一路径在 原稿/草稿/版本镜像列/版本快照 中的其他引用条数

    删除物理文件前的共享引用核对：任何其他记录仍指向同一路径时拒绝
    删除（防重复删除/误删）。排除集合用于"本条记录自身的引用"。
    """
    qs = ManualOriginal.objects.filter(file_path=rel_path)
    if exclude_original_id:
        qs = qs.exclude(pk=exclude_original_id)
    count = qs.count()
    qs = ManualDraft.objects.filter(file_path=rel_path)
    if exclude_draft_id:
        qs = qs.exclude(pk=exclude_draft_id)
    count += qs.count()
    qs = ManualVersion.objects.filter(file_path=rel_path)
    if exclude_version_id:
        qs = qs.exclude(pk=exclude_version_id)
    count += qs.count()
    qs = ManualVersionFile.objects.filter(file_path=rel_path)
    if exclude_snapshot_id:
        qs = qs.exclude(pk=exclude_snapshot_id)
    return count + qs.count()


def get_first_published_version(file_entry):
    """该文件首次进入的成功发布版本（version_no 最小的包含快照）；从未发布返回 None"""
    snap = ManualVersionFile.objects.filter(
        manual_file_id=file_entry.id,
        version__manual_id=file_entry.manual_id,
    ).select_related('version').order_by('version__version_no').first()
    return snap.version if snap else None


def has_usable_original(file_entry):
    """该文件是否仍有可用原稿（存在且未清理）"""
    return file_entry.originals.filter(cleaned_at__isnull=True).exists()


# ---------------------------------------------------------------------------
# 候选评估（只读；预检与执行共用同一口径，执行前逐项重新评估）

def _blocker(code, message):
    return {'code': code, 'message': message}


def evaluate_original_candidate(original, now=None, config=None):
    """评估单条原稿是否可清理（只读）

    Returns:
        dict: {'candidate', 'reason', 'blockers', 'already_cleaned',
               'first_published_version_no', 'first_published_at'}
    """
    now = now or timezone.now()
    config = config or get_retention_config()
    first_version = get_first_published_version(original.file)
    result = {
        'candidate': False,
        'reason': None,
        'blockers': [],
        'already_cleaned': original.cleaned_at is not None,
        'first_published_version_no': first_version.version_no if first_version else None,
        'first_published_at': first_version.published_at if first_version else None,
    }
    if original.cleaned_at is not None:
        return result
    if not config['cleanup_enabled']:
        result['blockers'].append(_blocker(
            BLOCK_RETENTION_DISABLED,
            '未配置版本保留期限，保留策略不执行物理删除'))
        return result
    if first_version is None:
        result['blockers'].append(_blocker(
            BLOCK_NEVER_PUBLISHED,
            '该文件尚未进入任何成功发布的版本，原稿本体受保护'))
        return result
    buffer_days = config['original_clean_buffer_days']
    if buffer_days > 0:
        deadline = first_version.published_at + datetime.timedelta(days=buffer_days)
        if now < deadline:
            result['blockers'].append(_blocker(
                BLOCK_BUFFER_NOT_ELAPSED,
                f'首次发布（v{first_version.version_no}）后需经过 '
                f'{buffer_days} 天缓冲期'))
            return result
    if ManualDraft.objects.filter(
            source_original=original).exclude(file_path='').exists():
        result['blockers'].append(_blocker(
            BLOCK_DRAFT_SOURCE,
            '当前草稿仍以该原稿为来源记录，请先重新保存或恢复草稿'))
        return result
    if get_active_session_for_file(original.file):
        result['blockers'].append(_blocker(
            BLOCK_ACTIVE_SESSION, '该文件存在进行中的编辑会话'))
        return result
    result['candidate'] = True
    result['reason'] = (
        f'文件已于 v{first_version.version_no} 首次发布'
        + (f'并超过 {buffer_days} 天缓冲期' if buffer_days else '')
        + '，原稿本体可清理（来源元数据永久保留）')
    return result


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


def _preview_original_row(original, now, config):
    """单条原稿的预检行；候选或存在阻止条件时返回，否则 None"""
    verdict = evaluate_original_candidate(original, now=now, config=config)
    if not verdict['candidate'] and not verdict['blockers']:
        return None
    size = original.file_size if original.cleaned_at is None else 0
    return {
        'original_id': original.id,
        'file_id': original.file_id,
        'file_name': original.original_name,
        'file_size': original.file_size,
        'uploaded_at': original.uploaded_at,
        'uploaded_by_name': original.uploaded_by.username
        if original.uploaded_by else '',
        'is_cleaned': original.cleaned_at is not None,
        'path_exists': _path_exists(original.file_path),
        'candidate': verdict['candidate'],
        'reason': verdict['reason'],
        'blockers': verdict['blockers'],
        'first_published_version_no': verdict['first_published_version_no'],
        'first_published_at': verdict['first_published_at'],
    }, size, verdict['candidate']


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
                   'originals': 0, 'reclaimable_size': 0},
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
            'versions': [], 'originals': [],
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
        originals = ManualOriginal.objects.filter(
            manual=manual).select_related('uploaded_by', 'file')
        for original in originals:
            built = _preview_original_row(original, now, config)
            if not built:
                continue
            row, size, is_candidate = built
            manual_row['originals'].append(row)
            if is_candidate:
                result['totals']['originals'] += 1
                result['totals']['reclaimable_size'] += size
        if manual_row['versions'] or manual_row['originals']:
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


def _cleanup_original(original, now):
    """清理单条候选原稿的物理文件；元数据行保留并标记 cleaned_at"""
    try:
        status, err = _try_delete_file(original.file_path, exclude={
            'exclude_original_id': original.id,
        })
    except Exception as e:
        status, err = 'failed', f'清理异常：{e}'
    if status in ('deleted', 'missing'):
        ManualOriginal.objects.filter(pk=original.id).update(cleaned_at=now)
        return {'original_id': original.id, 'file_id': original.file_id,
                'file_name': original.original_name,
                'status': 'cleaned' if status == 'deleted' else 'cleaned_missing'}
    return {'original_id': original.id, 'file_id': original.file_id,
            'file_name': original.original_name,
            'status': 'failed', 'error': err}


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


def _execute_manual_originals(manual, now, config):
    """评估并清理一本制度的候选原稿；返回 (结果列表, 触达项列表)"""
    results, touched = [], []
    for original in ManualOriginal.objects.filter(
            manual=manual).select_related('file'):
        verdict = evaluate_original_candidate(original, now=now, config=config)
        if not verdict['candidate']:
            continue
        item = _cleanup_original(original, now)
        item['manual_id'] = manual.id
        results.append(item)
        touched.append({**item, 'kind': 'original'})
    return results, touched


def _log_manual_cleanup(manual, operator, touched):
    """为发生实际清理动作的制度写操作记录（版本与原稿分开汇总）"""
    versions = [x for x in touched if x['kind'] == 'version']
    originals = [x for x in touched if x['kind'] == 'original']
    log_operation(
        manual, operator, ACTION_RETENTION_CLEANUP,
        versions=[{k: v for k, v in x.items() if k != 'files'}
                  for x in versions],
        originals=originals,
        failures=sum(len(x.get('failures') or []) for x in versions)
        + sum(1 for x in originals if x.get('status') == 'failed'))


def execute_cleanup(operator, manual_id=None):
    """执行保留策略清理（可控、幂等；逐项重新核对，失败可重试）

    - 配置门槛：未配置保留期限时直接拒绝（不产生任何删除）。
    - 执行前对每个版本/原稿重新运行候选评估（不信任预检结果），评估
      不通过或已清理的项跳过；候选评估含当前版本、长期保留、近期窗口、
      期限、业务引用、草稿来源、活跃会话与保护边界。
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
        'versions': [], 'originals': [],
        'summary': {'versions_cleaned': 0, 'versions_partial': 0,
                    'originals_cleaned': 0, 'failures': 0},
    }
    for manual in manuals:
        current_version_id = manual.current_version_id
        recent_protected = _recent_protected_version_nos(
            manual, config['version_recent_keep_count'])
        version_items, touched = _execute_manual_versions(
            manual, now, config, current_version_id, recent_protected)
        result['versions'].extend(version_items)
        original_items, originals_touched = _execute_manual_originals(
            manual, now, config)
        result['originals'].extend(original_items)
        if touched or originals_touched:
            _log_manual_cleanup(manual, operator, touched + originals_touched)
    for item in result['versions']:
        if item['status'] == 'cleaned':
            result['summary']['versions_cleaned'] += 1
        elif item['status'] == 'partial':
            result['summary']['versions_partial'] += 1
            result['summary']['failures'] += len(item['failures'])
    for item in result['originals']:
        if item['status'].startswith('cleaned'):
            result['summary']['originals_cleaned'] += 1
        else:
            result['summary']['failures'] += 1
    return result, None

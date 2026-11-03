# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""已下线原稿体系的安全清理（2026-11-02）

背景：新增制度文件改为「上传文件直接建立当前草稿」后，原稿记录
（ManualOriginal）与 originals/ 物理目录不再由业务流程产生；迁移
0010_remove_manual_original 只删除 schema（模型/表/草稿来源字段），
本模块负责把存量原稿**数据**安全清理干净：

- 迁移前（旧表 `tdyw_institution_original` 仍存在）：逐条读取原稿
  记录 → 校验路径必须在 originals 根目录内 → 删除物理文件（文件已
  缺失视为已完成）→ 删除该条记录。任一文件删除失败或路径非法时保留
  记录、计入 failures，绝不在失败时报告成功。
- 迁移后（旧表已删除）：只对 originals 根目录做残余文件扫描并清理空
  目录（历史失败/孤儿文件的收尾），不触碰任何数据库记录。
- 两种状态都会在记录处理后再做一次 originals 目录残余扫描，保证重复
  执行安全、不遗留孤儿物理文件。

安全边界（最重要）：
- 只允许操作 `storage.get_institution_storage_base()/originals/` 内的
  文件；相对路径首段必须是 originals、结构为 manual_<id>/...，禁止
  绝对路径、`..` 穿越与 realpath 逃逸（符号链接指向目录外一律拒绝）。
- 绝不删除 drafts/（当前草稿）或 versions/（发布快照）下的文件，也不
  修改任何 ManualDraft/ManualVersion/ManualVersionFile 记录与草稿、版本
  的物理文件；本清理不写操作记录/审计（纯运维入口）。
- dry_run=True 只读：不删除文件、不删除记录，返回 candidates。

使用：`python manage.py purge_institution_originals [--dry-run]
[--manual-id ID]`。推荐部署顺序：先执行清理命令（旧表还在时逐条
「删文件→删记录」），成功后再 migrate 0010；若已先 migrate，命令按
目录扫描收尾，仍可重复执行。
"""
import json
import logging
import os
import posixpath

from django.db import connection

from . import storage

logger = logging.getLogger(__name__)

# 旧原稿表名（迁移 0010 前存在；本模块用原始 SQL 读取，不 import 已删模型）
LEGACY_ORIGINAL_TABLE = 'tdyw_institution_original'


def originals_root():
    """原稿存储根目录绝对路径：<institution storage>/originals/"""
    return os.path.join(storage.get_institution_storage_base(), storage.LEGACY_ORIGINALS_SUBDIR)


def _relative_to_base(abs_path):
    """把绝对路径转为相对 institution 存储根的可读路径（posix 风格）"""
    base = os.path.abspath(storage.get_institution_storage_base())
    try:
        rel = os.path.relpath(os.path.abspath(abs_path), base)
    except ValueError:
        return abs_path
    return rel.replace('\\', '/')


def resolve_original_path(relative_path):
    """把原稿记录的 file_path 解析为绝对路径并做安全校验

    Raises:
        ValueError: 路径为空 / 绝对路径 / 含 .. / 首段不是 originals /
            非 manual_<id>/<年月>/<文件名> 结构 / realpath 逃逸出根目录
    """
    raw = str(relative_path or '').strip().replace('\\', '/')
    if not raw:
        raise ValueError('文件路径为空')
    normalized = posixpath.normpath(raw)
    if normalized.startswith('/') or normalized.startswith('..'):
        raise ValueError('非法文件路径')
    parts = normalized.split('/')
    if len(parts) < 3 or parts[0] != storage.LEGACY_ORIGINALS_SUBDIR:
        raise ValueError('路径不在原稿存储目录内')
    if not parts[1].startswith('manual_') or not parts[1][len('manual_'):].isdigit():
        raise ValueError('路径不在原稿手册目录内')
    abs_path = os.path.join(storage.get_institution_storage_base(), *parts)
    root = originals_root()
    real_root = os.path.realpath(root)
    real_target = os.path.realpath(abs_path)
    try:
        inside = os.path.commonpath([real_root, real_target]) == real_root
    except ValueError:
        inside = False
    if not inside:
        raise ValueError('文件路径超出原稿存储根目录')
    return abs_path


def _legacy_table_exists():
    """旧原稿表是否仍存在（迁移 0010 前 present / 后 absent）"""
    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
    return LEGACY_ORIGINAL_TABLE in tables


def _add_failure(report, abs_path, error):
    report['failures'].append({
        'path': _relative_to_base(abs_path),
        'error': str(error),
    })


def _read_legacy_records(manual_id=None):
    """读取旧表原稿记录（id/manual_id/file_path）；表不存在返回空列表"""
    sql = f'SELECT id, manual_id, file_path FROM {LEGACY_ORIGINAL_TABLE}'
    params = ()
    if manual_id is not None:
        sql += ' WHERE manual_id = %s'
        params = (manual_id,)
    sql += ' ORDER BY id'
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _delete_legacy_record(record_id):
    with connection.cursor() as cursor:
        cursor.execute(
            f'DELETE FROM {LEGACY_ORIGINAL_TABLE} WHERE id = %s', (record_id,))


def _cleanup_records(report, manual_id=None):
    """迁移前模式：逐条清理原稿记录与物理文件（失败保留记录并报告）"""
    records = _read_legacy_records(manual_id)
    report['scanned_records'] += len(records)
    for row in records:
        rel_path = row.get('file_path') or ''
        try:
            abs_path = resolve_original_path(rel_path)
        except ValueError as err:
            _add_failure(report, rel_path, err)
            continue
        if os.path.exists(abs_path):
            report['scanned_files'] += 1
            report['_seen'].add(os.path.normcase(os.path.abspath(abs_path)))
            if report['dry_run']:
                report['candidates'].append(_relative_to_base(abs_path))
            else:
                try:
                    os.remove(abs_path)
                except OSError as err:
                    logger.error('[Institution] purge original failed: %s, error=%s',
                                 abs_path, err)
                    _add_failure(report, abs_path, err)
                    continue
                report['deleted_files'] += 1
        else:
            report['missing_files'] += 1
        if not report['dry_run']:
            try:
                _delete_legacy_record(row['id'])
            except Exception as err:  # noqa: BLE001 - 逐条报告失败，不中断整体
                logger.error('[Institution] delete original record %s failed: %s',
                             row['id'], err)
                _add_failure(report, rel_path, f'记录删除失败：{err}')
                continue
            report['deleted_records'] += 1


def _cleanup_orphan_files(report, manual_id=None):
    """目录扫描模式：清理 originals 根内残余文件与空目录（幂等）"""
    root = originals_root()
    scan_root = root
    if manual_id is not None:
        scan_root = os.path.join(root, f'manual_{manual_id}')
    if not os.path.isdir(scan_root):
        return
    real_root = os.path.realpath(root)
    for dir_path, _dir_names, file_names in os.walk(scan_root, topdown=False):
        for name in file_names:
            abs_path = os.path.join(dir_path, name)
            try:
                real_target = os.path.realpath(abs_path)
                inside = os.path.commonpath(
                    [real_root, real_target]) == real_root
            except ValueError:
                inside = False
            if not inside:
                _add_failure(report, abs_path, '路径超出原稿存储根目录，拒绝删除')
                continue
            seen_key = os.path.normcase(os.path.abspath(abs_path))
            if seen_key in report.get('_seen', ()):
                # 已由旧表记录路径处理过（dry-run 时避免重复计入/重复候选）
                continue
            report['_seen'].add(seen_key)
            report['scanned_files'] += 1
            if report['dry_run']:
                report['candidates'].append(_relative_to_base(abs_path))
                continue
            try:
                os.remove(abs_path)
            except OSError as err:
                logger.error('[Institution] purge orphan original failed: %s, error=%s',
                             abs_path, err)
                _add_failure(report, abs_path, err)
                continue
            report['deleted_files'] += 1
        # 清理空目录（根目录本身保留；非空目录 rmdir 会失败并跳过）
        if os.path.abspath(dir_path) == os.path.abspath(root):
            continue
        if report['dry_run']:
            continue
        try:
            if not os.listdir(dir_path):
                os.rmdir(dir_path)
        except OSError:
            # 目录非空/被占用不影响文件清理结果
            pass


def cleanup_originals(dry_run=False, manual_id=None):
    """幂等清理原稿记录与物理文件；返回报告 dict（见模块 docstring）

    Args:
        dry_run: True 时只扫描、不删除（candidates 仅列出将删除的文件）
        manual_id: 可选，仅清理指定手册的原稿（记录过滤 + manual_<id> 目录）

    Returns:
        dict: 报告键 dry_run/table_state/scanned_records/scanned_files/
            deleted_files/missing_files/deleted_records/failures/candidates/
            success
    """
    report = {
        'dry_run': bool(dry_run),
        'table_state': 'present' if _legacy_table_exists() else 'absent',
        'scanned_records': 0,
        'scanned_files': 0,
        'deleted_files': 0,
        'missing_files': 0,
        'deleted_records': 0,
        'failures': [],
        'candidates': [],
        '_seen': set(),
    }
    if report['table_state'] == 'present':
        _cleanup_records(report, manual_id)
    _cleanup_orphan_files(report, manual_id)
    report.pop('_seen', None)
    report['success'] = not report['failures']
    return report


def format_report(report):
    """报告序列化为可打印 JSON 文本（命令输出与日志共用）"""
    return json.dumps(report, ensure_ascii=False, indent=2)

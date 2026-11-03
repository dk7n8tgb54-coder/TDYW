# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""修订状态服务（开始修订的真实状态动作；自 services.py 门控行数拆分）

职责：已发布文件「开始修订」——开启新一轮修订并复用现有工作副本；
工作副本缺失/损坏/与生效基线不一致时，经用户明确确认后从当前生效
版本快照修复。单向依赖 services（恢复/提示/操作记录），services 不
反向引用本模块。
"""
import os

from . import storage
from .models import Manual, ManualDraft, ManualFile, ManualVersionFile
from .services import (ACTION_REVISION_START, FROZEN_EDIT_ERROR,
                       build_draft_recovery_hint, file_is_frozen,
                       has_published_versions, log_operation,
                       restore_draft_from_current_version)


def start_file_revision(file_entry, user, confirm_repair=False):
    """开始修订：已发布文件开启新一轮修订的真实状态动作

    语义（工作副本持续保留，"修订进行中"是显式持久状态，绝不凭哈希
    相等推断修订已结束或进行中）：
    - 修订已在进行中（revision_open=True）→ 幂等返回 resumed，调用方
      显示"继续编辑"并直接复用工作副本，绝不覆盖；
    - 工作副本健康（存在且与当前生效基线一致，或该文件尚未进入生效
      版本）→ 开启修订并原样复用现有工作副本，正常情况下绝不为开始
      修订再复制一份生效快照；
    - 工作副本缺失、损坏或与当前生效基线不一致 → 返回 needs_repair，
      由调用方明确提示并经 confirm_repair 二次确认后，从当前生效版本
      快照修复（restore_draft_from_current_version force_repair 模式），
      绝不静默改用初始来源，也绝不静默覆盖可能与基线不同的工作副本。

    Returns:
        tuple: (dict, error)。dict 字段 resumed/started/repaired/
        needs_repair/reason/message/draft_recovery。
    """
    manual = file_entry.manual
    if manual.status != Manual.STATUS_ACTIVE:
        return None, '手册已归档，不能开始修订'
    if file_is_frozen(file_entry):
        return None, FROZEN_EDIT_ERROR
    if file_entry.revision_open:
        return {'resumed': True, 'started': False, 'repaired': False,
                'needs_repair': False, 'reason': '', 'message': '',
                'draft_recovery': None}, None

    def _needs_repair(reason, message):
        return {'resumed': False, 'started': False, 'repaired': False,
                'needs_repair': True, 'reason': reason, 'message': message,
                'draft_recovery': build_draft_recovery_hint(file_entry)}, None

    def _repair(reason):
        """经用户确认后从当前生效版本快照修复工作副本（绝不改用初始来源）"""
        draft_repaired, err = restore_draft_from_current_version(
            file_entry, user, force_repair=True, repair_reason=reason)
        if err:
            return None, err
        return {'resumed': False, 'started': True, 'repaired': True,
                'needs_repair': False, 'reason': '', 'message': '',
                'draft_recovery': None}, None

    draft = ManualDraft.objects.filter(file=file_entry).first()
    current = manual.current_version
    snapshot = None
    if current:
        snapshot = ManualVersionFile.objects.filter(
            version=current, manual_file=file_entry).first()

    if not draft or not draft.file_path:
        if snapshot:
            if confirm_repair:
                return _repair('draft_missing')
            return _needs_repair(
                'draft_missing',
                f'该文件的工作副本缺失，将从当前生效版本 v{current.version_no} '
                '的快照恢复（原工作副本内容将被替换）')
        # 防御分支：未进入过生效版本的文件正常默认已开启修订；
        # 无生效快照可自动修复，只能走显式的草稿建立/重建入口
        return _needs_repair(
            'draft_missing',
            '该文件还没有工作副本，请先从初始原稿创建草稿'
            if not has_published_versions(manual) else
            '该文件还没有工作副本，请从历史版本回退或从初始原稿重建')

    try:
        src_abs = storage.resolve_absolute_path(draft.file_path)
        draft_exists = os.path.exists(src_abs)
    except ValueError:
        draft_exists = False
    if snapshot and (not draft_exists or draft.file_hash != snapshot.file_hash):
        if not draft_exists:
            reason = 'draft_corrupt'
            message = (
                f'该文件的工作副本文件缺失，将从当前生效版本 v{current.version_no} '
                '的快照恢复')
        else:
            reason = 'baseline_mismatch'
            message = (
                f'该文件的工作副本与当前生效基线（v{current.version_no}）不一致，'
                '可能存在未发布的修改；确认后将从当前生效版本快照恢复，'
                '未发布的修改将被替换')
        if confirm_repair:
            return _repair(reason)
        return _needs_repair(reason, message)

    # 工作副本健康：开启修订并原样复用，不复制新快照
    ManualFile.objects.filter(pk=file_entry.pk).update(revision_open=True)
    log_operation(
        manual, user, ACTION_REVISION_START, file=file_entry,
        file_id=file_entry.id, file_revision=draft.revision,
        file_name=file_entry.display_name)
    return {'resumed': False, 'started': True, 'repaired': False,
            'needs_repair': False, 'reason': '', 'message': '',
            'draft_recovery': None}, None

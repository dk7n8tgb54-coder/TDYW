# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度管理业务服务层

职责：手册级授权判定（所有者 + 逐本账号授权）、编辑密码与会话、
草稿/发布/回退的文件与数据库编排、操作记录。业务授权完全依据
页面权限码（功能资格）+ 手册所有者/逐本账号授权；tenant_id 不参与
任何判定（仅作为数据模型约定保留）。

页面级权限（module.page.perm）由视图层 @auth 装饰器校验；本层
负责手册级（对象级）授权，两条校验在所有入口独立生效。
"""
import datetime
import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from . import storage
from .models import (Manual, ManualDraft, ManualEditSession, ManualFile,
                     ManualOperationLog, ManualOriginal, ManualVersion,
                     ManualVersionFile)

logger = logging.getLogger(__name__)

# 编辑密码连续失败限制
PASSWORD_MAX_FAILS = 5
PASSWORD_LOCK_MINUTES = 15

# 编辑会话有效期（秒）；保存草稿时滑动续期
EDIT_SESSION_TTL_SECONDS = 2 * 3600

AUDIT_TARGET_TYPE = 'institution_manual'
AUDIT_TARGET_NAME = '制度手册'

# 手册操作记录动作常量（ManualOperationLog.action）
ACTION_CREATE = 'create'
ACTION_UPLOAD_ORIGINAL = 'upload_original'
ACTION_CREATE_DRAFT = 'create_draft'
# 从当前生效版本的文件快照恢复草稿（草稿缺失时的默认恢复路径）
ACTION_RESTORE_DRAFT = 'restore_draft'
ACTION_SAVE_DRAFT = 'save_draft'
ACTION_SESSION_START = 'session_start'
ACTION_SESSION_REVOKE = 'session_revoke'
ACTION_PUBLISH = 'publish'
ACTION_DEPRECATE = 'deprecate'
ACTION_ROLLBACK = 'rollback'
ACTION_PASSWORD_RESET = 'password_reset'
ACTION_CONFIG_CHANGE = 'config_change'
ACTION_CHAPTER_UPDATE = 'chapter_update'
ACTION_FILE_ADD = 'file_add'
ACTION_FILE_ASSIGN = 'file_assign'
ACTION_FILE_SUBMIT = 'file_submit'
ACTION_FILE_RENAME = 'file_rename'
ACTION_FILE_MOVE = 'file_move'
ACTION_FILE_REMOVE = 'file_remove'
# 开始修订（已发布文件的真实状态动作：开启新一轮修订，复用现有工作副本）
ACTION_REVISION_START = 'revision_start'
# 修复工作副本（从当前生效版本快照恢复缺失/损坏/基线不一致的工作副本）
ACTION_REPAIR_DRAFT = 'repair_draft'
# 手册所有者指定/移交（制度管理员，2026-10-31；实现见 authorization_services）
ACTION_OWNER_CHANGE = 'owner_change'
# 逐本账号授权整体替换（所有者/制度管理员，2026-10-31；实现见
# authorization_services）
ACTION_AUTHORIZATION_CHANGE = 'authorization_change'
ACTION_DELETE = 'delete'


def get_manual_file(manual, file_id):
    """取制度文件条目并校验确属当前制度（文件级接口的越权防线）

    Returns:
        tuple: (ManualFile 或 None, 错误消息或 None)
    """
    file_entry = ManualFile.objects.filter(pk=file_id, manual=manual).first()
    if not file_entry:
        return None, '制度文件不存在或无权限访问'
    return file_entry, None


def list_active_files(manual):
    """待发布集合：未移除文件按 sort_order,id 排序

    预取分工关联账号（负责人/提交人快照为空时回退展示昵称），清单与
    发布预检逐行使用，避免 N+1。
    """
    return list(manual.files.filter(is_removed=False).select_related(
        'owner', 'submitted_by').order_by('sort_order', 'id'))


def get_single_active_file(manual):
    """旧单文件 API 委托：唯一启用文件；零个/多个都明确报错

    Returns:
        tuple: (ManualFile 或 None, 错误消息或 None)
    """
    files = list_active_files(manual)
    if len(files) == 1:
        return files[0], None
    if not files:
        return None, '本制度还没有文件，请先上传原稿创建文件'
    return None, '该制度包含多份文件，请使用文件级接口操作具体文件'


def get_active_session_for_file(file_entry):
    """文件的当前活跃编辑会话（占用状态展示用）"""
    return file_entry.edit_sessions.filter(
        revoked_at__isnull=True, expires_at__gt=timezone.now(),
    ).order_by('id').first()


# ---------------------------------------------------------------------------
# 操作记录（手册维度时间线；操作人只到账号）

def log_operation(manual, user, action, version=None, file=None, **detail):
    """写手册操作记录；操作账号快照冗余存储，账号删除后仍可读

    涉及具体文件的动作（保存/增删/改名/排序）同时写入 file 外键，
    detail JSON 冗余 file_id/file_revision 供操作记录页展示。
    """
    ManualOperationLog.objects.create(
        manual=manual,
        user=user if getattr(user, 'pk', None) else None,
        user_name=getattr(user, 'username', '') or '',
        action=action,
        version=version,
        file=file,
        detail=json.dumps(detail, ensure_ascii=False) if detail else '',
    )


# ---------------------------------------------------------------------------
# 编辑密码（只存哈希；失败限制；重置使旧会话失效）

def set_manual_password(manual, password, operator, reason=''):
    """设置/重置编辑密码，并使该手册所有有效编辑会话失效"""
    revoked = revoke_manual_sessions(manual, reason='密码重置')
    manual.password_hash = make_password(password)
    manual.password_updated_at = timezone.now()
    manual.password_fail_count = 0
    manual.password_locked_until = None
    manual.save(update_fields=[
        'password_hash', 'password_updated_at',
        'password_fail_count', 'password_locked_until',
    ])
    log_operation(
        manual, operator, ACTION_PASSWORD_RESET,
        revoked_sessions=revoked, reason=reason or '',
    )
    return revoked


def verify_manual_password(manual, password):
    """校验编辑密码，带失败次数限制

    Returns:
        tuple: (是否通过, 错误消息或 None)
    """
    now = timezone.now()
    if manual.password_locked_until and manual.password_locked_until > now:
        remain = int((manual.password_locked_until - now).total_seconds() // 60) + 1
        return False, f'密码错误次数过多，请约 {remain} 分钟后重试'
    if not manual.password_hash:
        return False, '本手册尚未设置编辑密码，请联系管理员配置'
    if not check_password(password or '', manual.password_hash):
        manual.password_fail_count = (manual.password_fail_count or 0) + 1
        if manual.password_fail_count >= PASSWORD_MAX_FAILS:
            manual.password_locked_until = now + datetime.timedelta(minutes=PASSWORD_LOCK_MINUTES)
            manual.password_fail_count = 0
        manual.save(update_fields=['password_fail_count', 'password_locked_until'])
        return False, '编辑密码错误'
    if manual.password_fail_count or manual.password_locked_until:
        manual.password_fail_count = 0
        manual.password_locked_until = None
        manual.save(update_fields=['password_fail_count', 'password_locked_until'])
    return True, None


# ---------------------------------------------------------------------------
# 编辑会话（文件级单写约束；绑定文件/账号/修订序号/有效期）

def _session_is_active(session, now=None):
    now = now or timezone.now()
    return session.revoked_at is None and session.expires_at > now


def start_edit_session(file_entry, user):
    """开启（或续期本人）文件的编辑会话；同一文件仅一个可写会话

    - 该文件已有他人有效会话：拒绝（不同账号不能并行写同一文件）
    - 同一制度其他文件的会话互不影响，可并行编辑
    - 已有本人有效会话：视为续期返回同一会话（同账号多标签共用，
      保存仍由草稿修订序号阻止旧内容覆盖新内容）
    """
    ManualFile.objects.select_for_update().get(pk=file_entry.pk)
    now = timezone.now()
    active = ManualEditSession.objects.filter(
        file=file_entry, revoked_at__isnull=True, expires_at__gt=now,
    ).order_by('id').first()
    if active and active.user_id != user.id:
        return None, '该文件已有进行中的编辑会话，请稍后再试或联系对方退出'
    if active:
        session = active
    else:
        draft = ManualDraft.objects.filter(file=file_entry).first()
        session = ManualEditSession.objects.create(
            manual=file_entry.manual, file=file_entry, user=user,
            session_key=uuid.uuid4().hex,
            revision_at_start=draft.revision if draft else 0,
            expires_at=now + datetime.timedelta(seconds=EDIT_SESSION_TTL_SECONDS),
        )
    return session, None


def get_active_session(file_entry, user, session_key):
    """校验会话存在且绑定当前文件与账号、未失效未过期"""
    if not session_key:
        return None, '缺少编辑会话，请重新验证密码'
    session = ManualEditSession.objects.filter(
        session_key=session_key, file=file_entry,
    ).first()
    if not session:
        return None, '编辑会话不存在或已失效，请重新验证密码'
    if session.user_id != user.id:
        return None, '编辑会话与当前账号不匹配，请重新验证密码'
    now = timezone.now()
    if session.revoked_at is not None:
        return None, f'编辑会话已失效（{session.revoked_reason or "会话被撤销"}），请重新验证密码'
    if session.expires_at <= now:
        return None, '编辑会话已过期，请重新验证密码'
    return session, None


def touch_session(session):
    """会话滑动续期"""
    session.last_active_at = timezone.now()
    session.expires_at = timezone.now() + datetime.timedelta(seconds=EDIT_SESSION_TTL_SECONDS)
    session.save(update_fields=['last_active_at', 'expires_at'])


def revoke_file_sessions(file_entry, reason='', exclude_key=None):
    """使某文件全部有效编辑会话失效；返回失效数量"""
    now = timezone.now()
    qs = ManualEditSession.objects.filter(file=file_entry, revoked_at__isnull=True)
    if exclude_key:
        qs = qs.exclude(session_key=exclude_key)
    return qs.update(revoked_at=now, revoked_reason=reason or '')


def revoke_manual_sessions(manual, reason='', exclude_key=None):
    """使手册（全部文件）有效编辑会话失效；返回失效数量"""
    now = timezone.now()
    qs = ManualEditSession.objects.filter(manual=manual, revoked_at__isnull=True)
    if exclude_key:
        qs = qs.exclude(session_key=exclude_key)
    return qs.update(revoked_at=now, revoked_reason=reason or '')


# ---------------------------------------------------------------------------
# 草稿 / 发布 / 回退（文件先行，数据库其后；失败补偿）

def _cleanup_replaced_draft_file(rel_path):
    """删除被替换的旧草稿物理文件（事务提交后调用；失败仅记日志）"""
    try:
        abs_path = storage.resolve_absolute_path(rel_path)
    except ValueError:
        logger.warning('[Institution] skip draft cleanup, bad path: %s', rel_path)
        return
    storage.safe_delete_file(abs_path)


# base_version 形参哨兵：不传 = 保留现有 base_version；显式传 None = 清除
# （草稿改由原稿重建时不再指向任何发布版本，来源以 source_original 表达）
_UNSET_BASE_VERSION = object()


@transaction.atomic
def _create_draft_record(file_entry, rel_path, original_name, size, file_hash,
                         user, source_original=None, base_version=_UNSET_BASE_VERSION):
    """创建/替换文件草稿记录；旧草稿文件事务提交后清理

    所有草稿内容变更路径（保存/恢复/回退/原稿重建）都经过本函数——
    任何真实的内容工作都把文件置回"修订进行中"（revision_open=True），
    该状态只在整套发布成功时按发布清单关闭。用 update() 单字段写入，
    不整行覆盖文件条目上的其他并发字段。
    """
    draft = ManualDraft.objects.select_for_update().filter(file=file_entry).first()
    old_rel_path = draft.file_path if draft else ''
    if not draft:
        draft = ManualDraft(manual=file_entry.manual, file=file_entry)
    draft.file_path = rel_path
    draft.original_name = original_name
    draft.file_size = size
    draft.file_hash = file_hash
    draft.source_original = source_original
    if base_version is not _UNSET_BASE_VERSION:
        draft.base_version = base_version
    draft.revision = (draft.revision or 0) + 1
    draft.last_saved_by = user
    draft.last_saved_at = timezone.now()
    draft.save()
    ManualFile.objects.filter(pk=file_entry.pk).update(revision_open=True)
    if old_rel_path and old_rel_path != rel_path:
        # 旧草稿文件已无引用：事务提交后清理（回滚则保留旧文件与旧记录一致）
        transaction.on_commit(
            lambda: _cleanup_replaced_draft_file(old_rel_path))
    return draft


def create_draft_from_original(file_entry, original, user, log_detail=None):
    """以原稿副本创建/重置文件草稿；.doc 原稿先转换为 .docx 工作副本

    原稿文件永不改动：.docx 原稿直接复制，.doc 原稿转换产物落在
    独立临时目录，草稿写入后清理临时目录本身。
    调用方必须先校验 original 属于 file_entry。
    从原稿（重）建草稿后 base_version 清除：草稿内容不再源自任何
    发布版本，来源以 source_original 表达。
    """
    src_abs = storage.resolve_absolute_path(original.file_path)
    ext = storage.extract_extension(original.original_name)
    work_path, tmp_dir, err = ensure_docx_workfile(src_abs, original.original_name)
    if err:
        return None, err
    stored_name = storage.build_stored_name(original.original_name)
    if ext != '.docx':
        stored_name = os.path.splitext(stored_name)[0] + '.docx'
    rel_path = storage.build_relative_path(
        storage.FILE_KIND_DRAFT, file_entry.manual_id, stored_name)
    abs_path = storage.resolve_absolute_path(rel_path)
    try:
        with open(work_path, 'rb') as stream:
            size, file_hash = storage.save_stream_to_path(stream, abs_path)
    except Exception:
        # 物理写入失败不得留下半成品草稿文件，也不得进入数据库写入
        storage.safe_delete_file(abs_path)
        logger.warning('[Institution] draft copy write failed', exc_info=True)
        return None, '草稿文件写入失败，请稍后重试'
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    try:
        with transaction.atomic():
            display = storage.display_name(original.original_name)
            if ext != '.docx':
                display = os.path.splitext(display)[0] + '.docx'
            draft = _create_draft_record(
                file_entry, rel_path, display, size, file_hash,
                user, source_original=original, base_version=None)
            detail = {'file_id': file_entry.id,
                      'file_revision': draft.revision,
                      'source_original_id': original.id}
            if log_detail:
                detail.update(log_detail)
            log_operation(file_entry.manual, user, ACTION_CREATE_DRAFT,
                          file=file_entry, **detail)
    except Exception:
        storage.safe_delete_file(abs_path)
        raise
    return draft, None


def save_file_draft(file_entry, user, uploaded_file, expected_revision):
    """保存文件草稿（新文件落盘 -> 修订序号+1 -> 记录；DB 失败清理文件）"""
    stored_name = storage.build_stored_name(uploaded_file.name)
    rel_path = storage.build_relative_path(
        storage.FILE_KIND_DRAFT, file_entry.manual_id, stored_name)
    abs_path = storage.resolve_absolute_path(rel_path)
    file_hash = storage.save_upload_file(uploaded_file, abs_path)
    size = os.path.getsize(abs_path)
    try:
        with transaction.atomic():
            current = ManualDraft.objects.select_for_update().filter(
                file=file_entry).first()
            if not current or current.revision != expected_revision:
                storage.safe_delete_file(abs_path)
                return None, '草稿已被其他会话更新，请刷新草稿后重试'
            draft = _create_draft_record(
                file_entry, rel_path, storage.display_name(uploaded_file.name),
                size, file_hash, user)
            log_operation(
                file_entry.manual, user, ACTION_SAVE_DRAFT, file=file_entry,
                file_id=file_entry.id, file_revision=draft.revision)
    except Exception:
        storage.safe_delete_file(abs_path)
        raise
    return draft, None


# ---------------------------------------------------------------------------
# 制度文件条目管理（新增/改名/排序/移除；只影响待发布集合）


@transaction.atomic
def create_manual_file(manual, user, uploaded_file, owner=None, note=''):
    """新增制度文件：上传原稿 -> 建条目 -> 以原稿建草稿（可直接编辑）

    条目与原稿记录在一个事务内落库；随后的草稿建立（含 .doc 转换）
    失败只影响该文件的可编辑性，条目与原稿保留，可稍后重试建草稿。
    文件追加到待发布清单末尾。owner/note 为可选的文件分工（新增时
    即可指定负责人，之后可经 assign 接口改派；不指定即"未分配"）。
    Returns:
        tuple: (ManualFile, 错误消息或 None)；草稿未就绪不视为本接口失败
    """
    ext = storage.extract_extension(uploaded_file.name)
    if ext not in storage.ALLOWED_EXTENSIONS:
        return None, '仅支持 .doc / .docx 文件'
    if uploaded_file.size > storage.MAX_FILE_SIZE:
        return None, '文件大小超过限制（100MB）'
    display = storage.display_name(uploaded_file.name)
    original_rel = storage.build_relative_path(
        storage.FILE_KIND_ORIGINAL, manual.id,
        storage.build_stored_name(uploaded_file.name))
    original_abs = storage.resolve_absolute_path(original_rel)
    original_hash = storage.save_upload_file(uploaded_file, original_abs)
    committed = False
    try:
        with transaction.atomic():
            file_entry = ManualFile.objects.create(
                manual=manual, display_name=display,
                sort_order=_next_file_sort_order(manual), created_by=user,
                owner=owner, owner_name=owner.username if owner else '',
                assign_note=(note or '').strip(),
                assigned_at=timezone.now() if owner else None,
                assigned_by=user if owner else None)
            original = ManualOriginal.objects.create(
                manual=manual, file=file_entry, file_path=original_rel,
                original_name=storage.display_name(uploaded_file.name),
                ext=ext, file_size=uploaded_file.size,
                file_hash=original_hash, uploaded_by=user)
            log_operation(
                manual, user, ACTION_FILE_ADD, file=file_entry,
                file_id=file_entry.id, file_name=display)
            log_operation(
                manual, user, ACTION_UPLOAD_ORIGINAL, file=file_entry,
                file_id=file_entry.id, original_id=original.id,
                file_name=storage.display_name(uploaded_file.name))
        committed = True
    except Exception:
        # 事务回滚后补偿清理本次原稿物理文件（记录未落库，文件不得残留）
        storage.safe_delete_file(original_abs)
        raise
    if committed:
        _, draft_err = create_draft_from_original(file_entry, original, user)
        if draft_err:
            # 文件条目与原稿已就绪；仅草稿未建立（可预览/下载原稿，稍后重试）。
            # 明确三段语义：文件已上传、草稿未就绪、暂不可发布。
            return file_entry, f'文件已上传，草稿未就绪，暂不可发布：{draft_err}'
    return file_entry, None


def _next_file_sort_order(manual):
    last = manual.files.filter(is_removed=False).order_by(
        '-sort_order').values_list('sort_order', flat=True).first()
    return (last or 0) + 1


@transaction.atomic
def rename_manual_file(file_entry, new_name, user):
    """文件改名：只影响待发布集合显示名，历史快照名称不变"""
    name = storage.display_name(new_name, fallback_stem='')
    if not name or not name.strip(' ._'):
        return None, '文件名不能为空'
    before = file_entry.display_name
    file_entry.display_name = name
    file_entry.save(update_fields=['display_name'])
    log_operation(
        file_entry.manual, user, ACTION_FILE_RENAME, file=file_entry,
        file_id=file_entry.id, before=before, after=name)
    return file_entry, None


@transaction.atomic
def move_manual_file(manual, file_entry, target_sort, user):
    """文件排序：在待发布清单内移动到目标序位（1 起），其余依次顺延"""
    files = list_active_files(manual)
    if file_entry not in files:
        return None, '制度文件不存在或已移除'
    files.remove(file_entry)
    target_sort = max(1, min(int(target_sort), len(files) + 1))
    files.insert(target_sort - 1, file_entry)
    for idx, f in enumerate(files):
        if f.sort_order != idx + 1:
            f.sort_order = idx + 1
            f.save(update_fields=['sort_order'])
    log_operation(
        manual, user, ACTION_FILE_MOVE, file=file_entry,
        file_id=file_entry.id, position=target_sort)
    return file_entry, None


@transaction.atomic
def remove_manual_file(file_entry, user):
    """移除文件：退出待发布集合，保留条目/原稿/历史快照引用

    - 同一时刻该文件不允许存在活跃编辑会话
    - 最后一份启用文件不可移除（防止发布空制度）
    - 移除后该文件退出全部发布流程，其休眠草稿不再以基线引用（base_version）
      或来源引用（source_original）保护任何历史/原稿文件——回退时会按
      版本快照整体重建草稿，不依赖休眠草稿的旧引用
    """
    manual = file_entry.manual
    if get_active_session_for_file(file_entry):
        return None, '该文件有进行中的编辑会话，请先退出会话再移除'
    active_count = manual.files.filter(is_removed=False).count()
    if not file_entry.is_removed and active_count <= 1:
        return None, '最后一份文件不能移除'
    if not file_entry.is_removed:
        file_entry.is_removed = True
        file_entry.removed_at = timezone.now()
        file_entry.save(update_fields=['is_removed', 'removed_at'])
        ManualDraft.objects.filter(file=file_entry).update(
            base_version=None, source_original=None)
    log_operation(
        manual, user, ACTION_FILE_REMOVE, file=file_entry,
        file_id=file_entry.id, file_name=file_entry.display_name)
    return file_entry, None


# ---------------------------------------------------------------------------
# 文件分工与提交编制（2026-10-29，替代旧章节分工）


@transaction.atomic
def assign_file_owner(file_entry, owner, note, operator, batch=False):
    """指定/改派/清空文件负责人（分工单位=整份文件，每文件至多一名）

    owner=None 表示清空为"未分配"。被指派账号必须持有该手册 can_edit
    编制授权（视图层经 authorization_services.validate_assignee_for_manual
    校验）；此后仅负责人可编辑该文件（负责人独占，编辑密码只是附加验证）。

    改派或清空负责人（owner 变化）时同步：
    - 清除"提交编制"记录：提交是负责人向发布者的一次交接，负责人已
      变更则旧交接不再有效（提交状态由 file_submission_state 按落库
      记录计算，置空即回到"未提交"）；历史交接保留在操作记录中。
    - 撤销该文件的活跃编辑会话（未落盘内容显式丢弃，撤销原因留痕）。
    负责人未变（仅修改分工说明）时保留提交与会话。
    batch=True 时在操作记录中标记批量来源（批量接口逐文件复用本函数）。
    """
    owner_changed = file_entry.owner_id != (owner.pk if owner else None)
    file_entry.owner = owner
    file_entry.owner_name = owner.username if owner else ''
    file_entry.assign_note = (note or '').strip()
    file_entry.assigned_at = timezone.now()
    file_entry.assigned_by = operator if getattr(operator, 'pk', None) else None
    update_fields = [
        'owner', 'owner_name', 'assign_note', 'assigned_at', 'assigned_by']
    if owner_changed:
        file_entry.submission_revision = None
        file_entry.submitted_at = None
        file_entry.submitted_by = None
        update_fields += ['submission_revision', 'submitted_at', 'submitted_by']
    file_entry.save(update_fields=update_fields)
    revoked_sessions = 0
    if owner_changed:
        revoked_sessions = revoke_file_sessions(
            file_entry, reason='文件负责人变更，编辑会话撤销')
    detail = {
        'file_id': file_entry.id, 'file_name': file_entry.display_name,
        'owner_id': file_entry.owner_id, 'owner_name': file_entry.owner_name,
        'note': file_entry.assign_note, 'submission_reset': owner_changed,
        'revoked_sessions': revoked_sessions,
    }
    if batch:
        detail['batch'] = True
    log_operation(
        file_entry.manual, operator, ACTION_FILE_ASSIGN, file=file_entry,
        **detail)
    return file_entry, None


def file_submission_state(file_entry, draft):
    """文件"提交编制"状态（计算式判定；文件清单与发布预检共用）

    - none：从未提交
    - submitted：提交时修订号 == 当前草稿修订号且草稿有效（有效提交）
    - stale：提交后草稿已再次保存/重建/回退/恢复（提交已失效，
      调用方不得再显示"已完成"）
    """
    if not file_entry.submission_revision:
        return {'state': 'none', 'submitted_at': None,
                'submitted_by_name': '',
                'submission_revision': None,
                'draft_revision': draft.revision if draft else None}
    valid = bool(draft and draft.file_path and
                 draft.revision == file_entry.submission_revision)
    return {
        'state': 'submitted' if valid else 'stale',
        'submitted_at': file_entry.submitted_at,
        'submitted_by_name': _account_display(file_entry.submitted_by),
        'submission_revision': file_entry.submission_revision,
        'draft_revision': draft.revision if draft else None,
    }


def _account_display(user):
    if user is None:
        return ''
    return getattr(user, 'nickname', '') or getattr(user, 'username', '') or ''


def submit_file_compilation(file_entry, user):
    """负责人提交编制：记录提交时草稿修订号与时间（明确的交接信息）

    第一阶段不新增发布阻断条件：publish_whole_set 校验保持不变，
    提交状态仅作展示。限制：手册未归档；该文件有有效草稿（记录存在、
    路径合法且物理文件存在）；无活跃编辑会话。可重复提交（以提交时
    最新修订号覆盖；草稿再变更即按 file_submission_state 失效）。
    """
    manual = file_entry.manual
    if manual.status != Manual.STATUS_ACTIVE:
        return None, '手册已归档，不能提交编制'
    if get_active_session_for_file(file_entry):
        return None, '该文件仍有进行中的编辑会话，请先保存并退出会话后再提交'
    draft = ManualDraft.objects.filter(file=file_entry).first()
    if not draft or not draft.file_path:
        return None, '该文件还没有有效草稿，不能提交编制'
    try:
        src_abs = storage.resolve_absolute_path(draft.file_path)
    except ValueError:
        return None, '草稿路径非法，不能提交编制'
    if not os.path.exists(src_abs):
        return None, '草稿文件不存在或已被清理，请重新编辑后再提交'
    file_entry.submission_revision = draft.revision
    file_entry.submitted_at = timezone.now()
    file_entry.submitted_by = user if getattr(user, 'pk', None) else None
    file_entry.save(update_fields=[
        'submission_revision', 'submitted_at', 'submitted_by'])
    log_operation(
        manual, user, ACTION_FILE_SUBMIT, file=file_entry,
        file_id=file_entry.id, file_name=file_entry.display_name,
        file_revision=draft.revision)
    return file_entry, None


def _validate_publishable(manual):
    """整套发布前置校验（调用方需持有手册行锁）

    校验通过返回待发布计划；否则返回 (None, 错误消息)。
    """
    files = list_active_files(manual)
    if not files:
        return None, '当前没有可发布的文件'
    plan = []
    for file_entry in files:
        draft = ManualDraft.objects.filter(file=file_entry).first()
        if not draft or not draft.file_path:
            return None, f'文件「{file_entry.display_name}」还没有可发布的草稿'
        if get_active_session_for_file(file_entry):
            return None, f'文件「{file_entry.display_name}」仍有进行中的编辑会话，请先保存并退出后再发布'
        try:
            src_abs = storage.resolve_absolute_path(draft.file_path)
        except ValueError:
            return None, f'文件「{file_entry.display_name}」草稿路径非法，无法发布'
        if not os.path.exists(src_abs):
            return None, f'文件「{file_entry.display_name}」草稿文件不存在或已被清理，请重新编辑后再发布'
        plan.append((file_entry, draft, src_abs))
    return plan, None


def _cleanup_version_copies(copies):
    """发布失败补偿：清理已复制的版本快照物理文件"""
    for abs_path in copies:
        storage.safe_delete_file(abs_path)


def publish_whole_set(manual, user, change_note):
    """整套发布：以行锁固定清单与顺序，逐份制作不可变快照

    三段式（物理文件不受数据库事务保护，必须显式补偿）：
    1. 行锁内校验并固化清单（文件、草稿、会话状态、目标路径）；已有
       生效版本且无任何内容/结构变化时拒绝（无意义的重复发布）。
    2. 事务外逐份复制草稿 -> versions/（失败清理已复制文件）
    3. 行锁内复核清单与修订号未漂移，写入版本+快照+切换当前版本；
       任一步失败旧生效版保持完整。
    成功收尾（同一事务内）：本次发布清单内文件的本轮修订结束
    （revision_open=False）、清除"提交编制"交接记录（随本版发布被
    消费）、草稿 base_version 指向新版本并解除初始来源引用；工作副本
    一律保留——内容已与本版快照一致，不再作为"未发布草稿"展示。
    发布失败（任一步）不触碰修订状态、草稿与旧生效版本。
    """
    with transaction.atomic():
        locked = Manual.objects.select_for_update().get(pk=manual.pk)
        plan, err = _validate_publishable(locked)
        if err:
            return None, err
        from . import version_compare
        if not version_compare.has_pending_publish_changes(locked, plan):
            return None, '当前没有内容或结构变化，无需重复发布'
        entries = []
        for sort_order, (file_entry, draft, src_abs) in enumerate(plan):
            display = storage.display_name(file_entry.display_name)
            stored_name = storage.build_stored_name(display)
            rel_path = storage.build_relative_path(
                storage.FILE_KIND_VERSION, locked.id, stored_name)
            entries.append({
                'file': file_entry, 'draft': draft, 'src_abs': src_abs,
                'sort_order': sort_order, 'display': display,
                'rel_path': rel_path, 'abs_path': storage.resolve_absolute_path(rel_path),
            })

    # 事务外物理复制（不占数据库事务时长）
    copied = []
    try:
        for entry in entries:
            os.makedirs(os.path.dirname(entry['abs_path']), exist_ok=True)
            shutil.copyfile(entry['src_abs'], entry['abs_path'])
            copied.append(entry['abs_path'])
            entry['file_hash'] = storage.compute_file_hash(entry['abs_path'])
            entry['file_size'] = os.path.getsize(entry['abs_path'])
    except Exception as e:
        _cleanup_version_copies(copied)
        logger.warning('[Institution] publish snapshot copy failed: %s', e)
        return None, '版本快照制作失败，当前生效版本未改变，请稍后重试'

    try:
        return _commit_publish(locked.id, user, change_note, entries, copied)
    except Exception:
        _cleanup_version_copies(copied)
        raise


def _commit_publish(manual_id, user, change_note, entries, copied):
    """发布落库（行锁内复核后写版本+快照+切换当前版本并收尾修订状态）

    复制期间清单/草稿可能变化：复核不通过或落库异常时由调用方清理
    已复制文件（copied 随异常向上传递），旧生效版保持完整。
    """
    with transaction.atomic():
        locked = Manual.objects.select_for_update().get(pk=manual_id)
        plan2, err = _validate_publishable(locked)
        if err:
            _cleanup_version_copies(copied)
            return None, f'发布校验失败：{err}'
        current_ids = [
            (f.id, d.revision) for f, d, _ in plan2]
        planned_ids = [
            (e['file'].id, e['draft'].revision) for e in entries]
        if current_ids != planned_ids:
            _cleanup_version_copies(copied)
            return None, '文件清单或草稿在发布过程中发生变化，请重试'
        last_no = ManualVersion.objects.filter(manual=locked).order_by(
            '-version_no').values_list('version_no', flat=True).first()
        version = ManualVersion.objects.create(
            manual=locked, version_no=(last_no or 0) + 1,
            file_path=entries[0]['rel_path'],
            original_name=entries[0]['display'],
            file_size=entries[0]['file_size'],
            file_hash=entries[0]['file_hash'],
            change_note=change_note, published_by=user,
        )
        ManualVersionFile.objects.bulk_create([
            ManualVersionFile(
                version=version, manual_file_id=e['file'].id,
                display_name=e['display'], sort_order=e['sort_order'],
                file_path=e['rel_path'], file_size=e['file_size'],
                file_hash=e['file_hash'],
            ) for e in entries
        ])
        locked.current_version = version
        locked.save(update_fields=['current_version'])
        for e in entries:
            e['draft'].base_version = version
            # 修订轮随发布结束：工作副本改以本版为基线，解除对初始
            # 来源原稿的保留策略引用（来源历史由 ManualOriginal 记录
            # 与操作记录承载，不丢失）；已结束的旧引用不再保护历史文件
            e['draft'].source_original = None
            e['draft'].save(update_fields=['base_version', 'source_original'])
        # 本次发布清单内文件：修订轮结束 + 清除"提交编制"交接记录
        # （提交随本版发布被消费，不得显示为下一轮的有效交接）。
        # 工作副本保留，仅不再以"未发布草稿"名义展示
        published_file_ids = [e['file'].id for e in entries]
        ManualFile.objects.filter(id__in=published_file_ids).update(
            revision_open=False, submission_revision=None,
            submitted_at=None, submitted_by=None)
        log_operation(
            locked, user, ACTION_PUBLISH, version=version,
            change_note=change_note,
            files=[{'file_id': e['file'].id, 'name': e['display'],
                    'sort_order': e['sort_order'], 'file_hash': e['file_hash']}
                   for e in entries])
        return version, None


@transaction.atomic
def deprecate_current_version(manual, user):
    """废止当前生效版本：仅改变生效状态，不清除历史文件

    废止后制度暂无生效版本：全部启用文件回到"修订进行中"（生效集合
    已不存在，工作内容即待发布内容，重新发布走首次发布语义）。
    """
    version = manual.current_version
    if not version:
        return None, '当前没有生效版本'
    version.is_effective = False
    version.save(update_fields=['is_effective'])
    manual.current_version = None
    manual.save(update_fields=['current_version'])
    ManualFile.objects.filter(manual=manual, is_removed=False).update(
        revision_open=True)
    log_operation(manual, user, ACTION_DEPRECATE, version=version)
    return version, None


def rollback_to_version(manual, version, user):
    """整套回退：以历史版本的有序快照清单重建待发布草稿集合

    - 属于该版本的文件：以快照内容重建草稿（base_version=该版本），
      被移除过的重新纳入清单
    - 不属于该版本的启用文件：退出待发布集合（条目/原稿/历史快照保留）
    - 回退前使手册全部活跃编辑会话失效，避免编辑器在草稿被替换后写入
    - 不覆盖现有发布版；此后发布产生更大版本号
    """
    if version.manual_id != manual.id:
        return None, '版本不存在或无权限访问'
    if version.files_cleaned_at:
        return None, '该版本的文件已按保留策略清理（部分或全部），无法整套回退'
    snapshots = list(version.files.select_related('manual_file').order_by(
        'sort_order', 'id'))
    if not snapshots:
        return None, '该版本没有文件快照，无法回退'
    # 草稿物理复制先于数据库写入（快照文件只读，复制失败不动数据库）
    draft_copies = []
    try:
        for snap in snapshots:
            src_abs = storage.resolve_absolute_path(snap.file_path)
            if not os.path.exists(src_abs):
                return None, f'版本文件「{snap.display_name}」不存在或已被清理，无法回退'
            stored_name = storage.build_stored_name(snap.display_name)
            rel_path = storage.build_relative_path(
                storage.FILE_KIND_DRAFT, manual.id, stored_name)
            abs_path = storage.resolve_absolute_path(rel_path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            shutil.copyfile(src_abs, abs_path)
            draft_copies.append((snap, rel_path, abs_path))
    except Exception:
        for _, _, abs_path in draft_copies:
            storage.safe_delete_file(abs_path)
        logger.warning('[Institution] rollback draft copy failed', exc_info=True)
        return None, '回退草稿制作失败，请稍后重试'

    try:
        with transaction.atomic():
            locked = Manual.objects.select_for_update().get(pk=manual.pk)
            revoke_manual_sessions(locked, reason='整套回退，草稿被重建')
            snapshot_file_ids = {snap.manual_file_id for snap, _, _ in draft_copies}
            now = timezone.now()
            for f in locked.files.filter(is_removed=False).exclude(
                    id__in=snapshot_file_ids):
                f.is_removed = True
                f.removed_at = now
                f.save(update_fields=['is_removed', 'removed_at'])
                # 退出待发布集合的文件：休眠草稿解除基线/来源引用（回退
                # 以版本快照重建，休眠草稿不保护历史文件）
                ManualDraft.objects.filter(file=f).update(
                    base_version=None, source_original=None)
            for idx, (snap, rel_path, _) in enumerate(draft_copies):
                file_entry = snap.manual_file
                if file_entry.is_removed:
                    file_entry.is_removed = False
                    file_entry.removed_at = None
                    file_entry.save(update_fields=['is_removed', 'removed_at'])
                file_entry.sort_order = idx
                file_entry.save(update_fields=['sort_order'])
                _create_draft_record(
                    file_entry, rel_path,
                    storage.display_name(snap.display_name),
                    snap.file_size, snap.file_hash, user, base_version=version)
            log_operation(
                locked, user, ACTION_ROLLBACK, version=version,
                file_count=len(draft_copies),
                files=[{'file_id': snap.manual_file_id,
                        'name': snap.display_name} for snap, _, _ in draft_copies])
            return len(draft_copies), None
    except Exception:
        for _, _, abs_path in draft_copies:
            storage.safe_delete_file(abs_path)
        raise


# ---------------------------------------------------------------------------
# 草稿恢复（草稿缺失时：当前生效版本快照优先，原稿仅限首次或明确重建）

def has_published_versions(manual):
    """制度是否发布过任何版本（含已废止；废止不改写历史）"""
    return manual.versions.exists()


def build_draft_recovery_hint(file_entry):
    """草稿缺失时的恢复途径提示（文件清单行与错误响应共用）

    优先级与 draft/create 默认路径一致：
    - 当前生效版本包含该文件快照 -> source=current_version（默认恢复入口）
    - 制度发布过版本但当前版本不含该文件（后加入）或已废止无生效版本
      -> source=original 且 requires_confirm=True（只能走明确的原稿重建）
    - 制度从未发布过版本 -> source=original（首次建立草稿的正常入口）
    - 该文件原稿已全部按保留策略清理（元数据保留）时附加
      originals_cleaned=True 与说明：原稿本体不可用，重建入口应禁用，
      只能上传新原稿或从版本恢复。
    """
    manual = file_entry.manual
    version = manual.current_version

    def _original_flags(payload):
        originals = file_entry.originals.all()
        if originals and not originals.filter(cleaned_at__isnull=True).exists():
            payload['originals_cleaned'] = True
            payload['note'] = (
                (payload.get('note') + '；' if payload.get('note') else '')
                + '该文件的初始原稿已按保留策略清理（仅存来源元数据），'
                  '不能用于创建或重建草稿，请上传新原稿')
        return payload

    if version:
        if ManualVersionFile.objects.filter(
                version=version, manual_file=file_entry).exists():
            return {
                'source': 'current_version',
                'version_id': version.id,
                'version_no': version.version_no,
            }
        return _original_flags({
            'source': 'original',
            'requires_confirm': True,
            'note': f'当前生效版本（v{version.version_no}）不包含该文件的快照',
        })
    if has_published_versions(manual):
        return _original_flags({
            'source': 'original',
            'requires_confirm': True,
            'note': '制度已发布过版本但当前无生效版本，可从历史版本回退',
        })
    return _original_flags({'source': 'original'})


class _DraftExistsError(Exception):
    """恢复草稿时发现并发已建草稿（事务内判定，外层转业务错误）"""


def restore_draft_from_current_version(file_entry, user, force_repair=False,
                                       repair_reason=''):
    """从当前生效版本的文件快照恢复该文件草稿（默认恢复路径，不猜版本号）

    - 以 manual.current_version 为唯一来源；当前版本不含该文件快照时
      明确报错，绝不静默改用原稿补齐
    - 快照只读：复制到草稿存储生成新工作文件，绝不改写历史发布快照
    - base_version 指向来源版本；source_original 不记录
    - 恢复前使该文件编辑会话失效；产生新的草稿修订号；修订状态置为
      "进行中"（经 _create_draft_record）
    - 文件先行：复制失败不动数据库；落库失败清理已复制文件
    - force_repair=True：修复模式（开始修订发现工作副本缺失/损坏/与
      生效基线不一致时的显式修复），跳过"已有草稿拒绝"检查——调用方
      必须先取得用户明确确认，绝不静默覆盖
    """
    manual = file_entry.manual
    version = manual.current_version
    if not version:
        return None, '当前没有生效版本，无法从当前版本恢复草稿'
    if version.manual_id != manual.id:
        return None, '版本不存在或无权限访问'
    snapshot = ManualVersionFile.objects.filter(
        version=version, manual_file=file_entry).first()
    if not snapshot:
        return None, (f'当前生效版本（v{version.version_no}）不包含文件'
                      f'「{file_entry.display_name}」的快照，不能从当前版本'
                      '恢复草稿；如需以原始上传文件重建请使用明确的高级恢复操作')
    try:
        src_abs = storage.resolve_absolute_path(snapshot.file_path)
    except ValueError:
        return None, f'当前版本文件「{snapshot.display_name}」路径非法，无法恢复草稿'
    if not os.path.exists(src_abs):
        return None, f'当前版本文件「{snapshot.display_name}」不存在或已被清理，无法恢复草稿'
    stored_name = storage.build_stored_name(snapshot.display_name)
    rel_path = storage.build_relative_path(
        storage.FILE_KIND_DRAFT, manual.id, stored_name)
    abs_path = storage.resolve_absolute_path(rel_path)
    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        shutil.copyfile(src_abs, abs_path)
    except Exception:
        logger.warning('[Institution] restore draft copy failed', exc_info=True)
        return None, '恢复草稿制作失败，请稍后重试'
    try:
        with transaction.atomic():
            locked_file = ManualFile.objects.select_for_update().get(
                pk=file_entry.pk)
            # 行锁内权威复核：并发已建草稿则放弃恢复（不得无提示覆盖）；
            # 显式修复模式（force_repair）由调用方保证已获用户确认
            if not force_repair and ManualDraft.objects.filter(
                    file=locked_file).exists():
                raise _DraftExistsError()
            revoke_file_sessions(locked_file, reason='从当前生效版本恢复草稿')
            draft = _create_draft_record(
                locked_file, rel_path,
                storage.display_name(snapshot.display_name),
                snapshot.file_size, snapshot.file_hash, user,
                base_version=version)
            log_operation(
                manual, user,
                ACTION_REPAIR_DRAFT if force_repair else ACTION_RESTORE_DRAFT,
                version=version,
                file=locked_file, file_id=locked_file.id,
                file_revision=draft.revision,
                file_name=snapshot.display_name,
                from_version_no=version.version_no,
                source='current_version',
                **({'repair_reason': repair_reason} if force_repair else {}))
        return draft, None
    except _DraftExistsError:
        storage.safe_delete_file(abs_path)
        return None, '当前文件已有草稿，请继续编辑或明确执行重建'
    except Exception:
        storage.safe_delete_file(abs_path)
        raise


# ---------------------------------------------------------------------------
# .doc -> .docx 工作副本转换（LibreOffice headless）
#
# 注：修订状态动作（开始修订）位于 revision_services.py（门禁行数拆分，
# 复用本模块的恢复/提示/操作记录实现，单向依赖不反向）。

DOC_CONVERT_TIMEOUT_SECONDS = 120


def ensure_docx_workfile(src_abs_path, original_name):
    """确保得到 .docx 工作副本；.doc 原稿经 LibreOffice 转换

    Returns:
        tuple: (工作副本绝对路径 或 None, 需清理的临时目录或 None, 错误消息 或 None)
        .docx 原稿直接返回原文件路径（temp_dir=None，调用方绝不删除）
    """
    ext = storage.extract_extension(original_name)
    if ext == '.docx':
        return src_abs_path, None, None
    tmp_dir = tempfile.mkdtemp(prefix='institution_doc_conv_')
    try:
        # 源文件统一复制为 ASCII 名临时文件再转换：
        # LibreOffice 在部分容器 locale 下无法加载非 ASCII 文件名，
        # 与系统 locale 环境博弈不如固定转换输入，输出名固定 input.docx
        local_input = os.path.join(tmp_dir, f'input{ext}')
        shutil.copyfile(src_abs_path, local_input)
        # as_uri 生成规范的 file:/// URI（第三斜杠+百分号转义），
        # Windows 盘符路径与含空格路径均安全；手工拼 file://<path> 在
        # Windows（缺第三斜杠、反斜杠）与空格路径下必然失效
        profile_uri = (Path(tmp_dir) / 'lo_profile').as_uri()
        result = subprocess.run(
            ['soffice', '--headless', '--norestore',
             # 显式用户 profile：容器内 HOME 可能不存在或不可写，
             # profile 初始化失败会表现为任意源文件 "could not be loaded"
             f'-env:UserInstallation={profile_uri}',
             '--convert-to', 'docx', '--outdir', tmp_dir, local_input],
            capture_output=True, timeout=DOC_CONVERT_TIMEOUT_SECONDS,
        )
        produced = [
            os.path.join(tmp_dir, name) for name in os.listdir(tmp_dir)
            if name.lower().endswith('.docx')
        ]
        if result.returncode != 0 or not produced:
            logger.warning(
                '[Institution] doc->docx convert failed: rc=%s stderr=%s',
                result.returncode, (result.stderr or b'')[:500])
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None, None, '.doc 原稿转换为可编辑副本失败，可预览或下载原稿，请改用 .docx 上传或联系管理员'
        return produced[0], tmp_dir, None
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning('[Institution] doc->docx convert error: %s', e)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None, None, '.doc 转换服务不可用，可预览或下载原稿，请改用 .docx 上传'
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

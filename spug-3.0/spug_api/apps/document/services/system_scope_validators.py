# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""Unified scope validators for document operations.

Design principle — SYMMETRIC, fail-closed scope checks:

* Party-building context  -> object MUST be inside party-building scope.
* Normal public context    -> object MUST NOT be inside ANY system scope.
* Private context         -> private models only, system_folder forbidden.

Source AND target are always validated independently. Normal mode performs the
REVERSE isolation (reject system-scoped objects) so that an attacker cannot
reach party-building content by simply omitting ``system_folder``.

All functions return ``(ok: bool, error_msg: str | None)``.
"""

import logging

from .system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE,
    NORMAL_DOCUMENT_SCOPE_ERROR_MSG,
    PROTECTED_ROOT_MSG,
    SCOPE_ERROR_MSG,
    UPLOAD_TARGET_MSG,
    ensure_file_in_scope_or_error,
    ensure_folder_in_scope_or_error,
    is_file_in_any_system_scope,
    is_folder_in_any_system_scope,
    is_folder_in_scope,
    is_party_building_documents_code,
    is_protected_system_root,
    is_valid_system_folder_code,
    normalize_system_folder_code,
    validate_system_folder_context,
)

logger = logging.getLogger(__name__)

# Unified error message for cross-scope access — avoids leaking object existence.
SCOPE_FORBIDDEN_MSG = '无权访问该资源或资源不存在'


def log_scope_denial(user, action, obj_id, request_scope, actual_scope):
    """Structured security log for cross-scope denial.

    Logs user/tenant/action/object and scope mismatch without exposing tokens,
    file contents or full sensitive paths.
    """
    tenant_id = getattr(user, 'tenant_id', '') if user else ''
    username = getattr(user, 'username', '') if user else ''
    logger.warning(
        '[SCOPE] cross-scope denied: user=%s tenant=%s action=%s obj_id=%s '
        'request_scope=%s actual_scope=%s',
        username, tenant_id, action, obj_id, request_scope, actual_scope,
    )


def normalize_context(system_folder):
    """Normalize a raw system_folder request value to canonical form.

    Returns the canonical code (``''`` for normal mode) or raises ValueError
    when the value is non-empty but not a supported code. This is the single
    place legacy codes are mapped; callers should only compare normalized
    output.
    """
    if not system_folder:
        return ''
    normalized = normalize_system_folder_code(system_folder)
    if normalized not in ('', ) and not is_valid_system_folder_code(normalized):
        raise ValueError('未知的系统目录编码')
    return normalized or ''


def validate_document_context(system_folder, is_public):
    """Validate the request context tuple (fail-closed).

    - private + system_folder -> rejected
    - non-empty unsupported code -> rejected
    - party-building + not public -> rejected
    """
    return validate_system_folder_context(system_folder, is_public)


def validate_file_source_scope(system_folder, is_public, file_obj=None):
    """Validate a file object as the source of an operation.

    Party-building: file must be inside party-building scope.
    Normal public: file must NOT be inside any system scope (reverse isolation).
    """
    ok, error = validate_document_context(system_folder, is_public)
    if not ok:
        return False, error
    if file_obj is None:
        return True, None
    if is_party_building_documents_code(system_folder):
        return ensure_file_in_scope_or_error(file_obj, PARTY_BUILDING_DOCUMENTS_CODE)
    if is_public and is_file_in_any_system_scope(file_obj):
        log_scope_denial(
            None, 'file_source', getattr(file_obj, 'id', None),
            system_folder or '', 'system_scope',
        )
        return False, NORMAL_DOCUMENT_SCOPE_ERROR_MSG
    return True, None


def validate_folder_source_scope(
    system_folder, is_public, folder_id=None, include_root=False, protect_root=False
):
    """Validate a folder object as the source of an operation.

    Party-building: folder must be inside party-building scope; root protected
    when ``protect_root`` is set.
    Normal public: folder must NOT be inside any system scope (reverse isolation).
    """
    ok, error = validate_document_context(system_folder, is_public)
    if not ok:
        return False, error
    if not is_party_building_documents_code(system_folder):
        if is_public and folder_id is not None:
            if is_folder_in_any_system_scope(folder_id, include_root=True):
                log_scope_denial(
                    None, 'folder_source', folder_id,
                    system_folder or '', 'system_scope',
                )
                return False, NORMAL_DOCUMENT_SCOPE_ERROR_MSG
        return True, None
    if folder_id is None:
        return True, None
    if protect_root and is_protected_system_root(folder_id):
        return False, PROTECTED_ROOT_MSG
    return ensure_folder_in_scope_or_error(
        folder_id, PARTY_BUILDING_DOCUMENTS_CODE, include_root=include_root
    )


def validate_target_folder_scope(system_folder, is_public, folder_id, allow_root=True):
    """Validate a target folder for upload / create / copy / move target.

    Party-building: target must be inside party-building scope (root None forbidden).
    Normal public: target must NOT be inside any system scope (reverse isolation).
    Private: system_folder already forbidden by context validation.
    """
    ok, error = validate_document_context(system_folder, is_public)
    if not ok:
        return False, error
    if not is_party_building_documents_code(system_folder):
        # Normal public mode reverse isolation: target must not be a system folder.
        if is_public and folder_id:
            if is_folder_in_any_system_scope(folder_id, include_root=True):
                log_scope_denial(
                    None, 'target_folder', folder_id,
                    system_folder or '', 'system_scope',
                )
                return False, NORMAL_DOCUMENT_SCOPE_ERROR_MSG
        return True, None
    # Party-building mode: root (None) target is forbidden for uploads.
    if not folder_id:
        if allow_root:
            return True, None
        return False, UPLOAD_TARGET_MSG
    if not is_folder_in_scope(folder_id, PARTY_BUILDING_DOCUMENTS_CODE, include_root=True):
        return False, SCOPE_ERROR_MSG
    return True, None


# Backward-compatible aliases (existing call sites use these names).
validate_file_operation_scope = validate_file_source_scope


def validate_folder_operation_scope(
    system_folder, is_public, folder_id=None, include_root=False, protect_root=False
):
    """Backward-compatible alias for :func:`validate_folder_source_scope`."""
    return validate_folder_source_scope(
        system_folder, is_public, folder_id=folder_id,
        include_root=include_root, protect_root=protect_root,
    )


def validate_file_move_scope(system_folder, is_public, file_obj=None, target_id=None):
    """Validate a file move: source scope + target scope (symmetric).

    Cross-scope moves are always rejected. Root None target only allowed when
    the context is normal public AND the business allows root-level files.
    """
    ok, error = validate_file_source_scope(system_folder, is_public, file_obj)
    if not ok:
        return False, error
    if is_party_building_documents_code(system_folder):
        if not target_id:
            return False, '党建文档文件不能移出党建文档目录'
        ok, error = validate_target_folder_scope(
            system_folder, is_public, target_id, allow_root=False
        )
        if not ok:
            return False, error
        return True, None
    # Normal / private mode target check (reverse isolation for public).
    if target_id:
        ok, error = validate_target_folder_scope(
            system_folder, is_public, target_id, allow_root=True
        )
        if not ok:
            return False, error
    return True, None


def validate_folder_move_scope(system_folder, is_public, folder_id, target_id):
    """Validate a folder move: source scope + target scope (symmetric).

    The moved folder itself is protected against being a system root, and the
    target is validated for scope consistency.
    """
    ok, error = validate_folder_source_scope(
        system_folder, is_public, folder_id=folder_id,
        include_root=False, protect_root=True,
    )
    if not ok:
        return False, error
    if is_party_building_documents_code(system_folder):
        if not target_id:
            return False, '党建文档目录不能移出党建文档目录'
        ok, error = validate_target_folder_scope(
            system_folder, is_public, target_id, allow_root=False
        )
        if not ok:
            return False, error
        return True, None
    # Normal / private mode target check (reverse isolation for public).
    if target_id:
        ok, error = validate_target_folder_scope(
            system_folder, is_public, target_id, allow_root=True
        )
        if not ok:
            return False, error
    return True, None


def validate_upload_target_scope(system_folder, is_public, folder_id, require_folder=True):
    """Validate an upload target folder.

    Party-building: folder required and must be inside party-building scope.
    Normal public: folder must NOT be inside any system scope (reverse isolation).
    """
    ok, error = validate_document_context(system_folder, is_public)
    if not ok:
        return False, error
    if not is_party_building_documents_code(system_folder):
        # Normal public reverse isolation: reject system-scoped upload targets.
        if is_public and folder_id:
            if is_folder_in_any_system_scope(folder_id, include_root=True):
                log_scope_denial(
                    None, 'upload_target', folder_id,
                    system_folder or '', 'system_scope',
                )
                return False, NORMAL_DOCUMENT_SCOPE_ERROR_MSG
        return True, None
    if require_folder and not folder_id:
        return False, UPLOAD_TARGET_MSG
    if folder_id and not is_folder_in_scope(
        folder_id, PARTY_BUILDING_DOCUMENTS_CODE, include_root=True
    ):
        return False, SCOPE_ERROR_MSG
    return True, None


def validate_transfer_scope(system_folder, is_public, transfer):
    """Validate that a request context matches a persisted transfer record scope.

    The transfer record's ``system_folder`` is the trusted persisted context.
    Owner + tenant checks are NOT a substitute for scope consistency.
    """
    ok, error = validate_document_context(system_folder, is_public)
    if not ok:
        return False, error
    if transfer is None:
        return False, SCOPE_FORBIDDEN_MSG
    normalized_request = normalize_system_folder_code(system_folder) if system_folder else ''
    normalized_record = (
        normalize_system_folder_code(transfer.system_folder)
        if getattr(transfer, 'system_folder', '') else ''
    )
    if normalized_request != normalized_record:
        log_scope_denial(
            None, 'transfer', getattr(transfer, 'id', None),
            normalized_request, normalized_record,
        )
        return False, SCOPE_FORBIDDEN_MSG
    # is_public on the record must match the request too.
    if bool(transfer.is_public) != bool(is_public):
        log_scope_denial(
            None, 'transfer_is_public', getattr(transfer, 'id', None),
            is_public, transfer.is_public,
        )
        return False, SCOPE_FORBIDDEN_MSG
    return True, None

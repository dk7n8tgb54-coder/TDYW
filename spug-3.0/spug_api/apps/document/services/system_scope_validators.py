"""Small validators for system-folder scoped document operations."""

from .system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE,
    NORMAL_DOCUMENT_SCOPE_ERROR_MSG,
    PROTECTED_ROOT_MSG,
    SCOPE_ERROR_MSG,
    ensure_file_in_scope_or_error,
    ensure_folder_in_scope_or_error,
    is_file_in_any_system_scope,
    is_folder_in_any_system_scope,
    is_folder_in_scope,
    is_party_building_documents_code,
    is_protected_system_root,
    validate_system_folder_context,
)


def validate_file_operation_scope(system_folder, is_public, file_obj=None):
    ok, error = validate_system_folder_context(system_folder, is_public)
    if not ok:
        return False, error
    if is_party_building_documents_code(system_folder) and file_obj is not None:
        return ensure_file_in_scope_or_error(file_obj, PARTY_BUILDING_DOCUMENTS_CODE)
    if not is_party_building_documents_code(system_folder) and is_public and file_obj is not None:
        if is_file_in_any_system_scope(file_obj):
            return False, NORMAL_DOCUMENT_SCOPE_ERROR_MSG
    return True, None


def validate_file_move_scope(system_folder, is_public, file_obj=None, target_id=None):
    ok, error = validate_file_operation_scope(system_folder, is_public, file_obj)
    if not ok:
        return False, error
    if not is_party_building_documents_code(system_folder):
        return True, None
    if not target_id:
        return False, '党建文档文件不能移出党建文档目录'
    if not is_folder_in_scope(target_id, PARTY_BUILDING_DOCUMENTS_CODE, include_root=True):
        return False, SCOPE_ERROR_MSG
    return True, None


def validate_folder_operation_scope(
    system_folder,
    is_public,
    folder_id=None,
    include_root=False,
    protect_root=False,
):
    ok, error = validate_system_folder_context(system_folder, is_public)
    if not ok:
        return False, error
    if not is_party_building_documents_code(system_folder):
        if is_public and folder_id is not None:
            if is_folder_in_any_system_scope(folder_id, include_root=True):
                return False, NORMAL_DOCUMENT_SCOPE_ERROR_MSG
        return True, None
    if folder_id is None:
        return True, None
    if protect_root and is_protected_system_root(folder_id):
        return False, PROTECTED_ROOT_MSG
    return ensure_folder_in_scope_or_error(
        folder_id, PARTY_BUILDING_DOCUMENTS_CODE, include_root=include_root
    )


def validate_folder_move_scope(system_folder, is_public, folder_id, target_id):
    ok, error = validate_folder_operation_scope(
        system_folder,
        is_public,
        folder_id=folder_id,
        include_root=False,
        protect_root=True,
    )
    if not ok:
        return False, error
    if not is_party_building_documents_code(system_folder):
        if is_public and folder_id:
            if is_folder_in_any_system_scope(folder_id, include_root=True):
                return False, NORMAL_DOCUMENT_SCOPE_ERROR_MSG
        return True, None
    if not target_id:
        return False, '党建文档文件不能移出党建文档目录'
    if not is_folder_in_scope(target_id, PARTY_BUILDING_DOCUMENTS_CODE, include_root=True):
        return False, SCOPE_ERROR_MSG
    return True, None


def validate_upload_target_scope(system_folder, is_public, folder_id, require_folder=True):
    ok, error = validate_system_folder_context(system_folder, is_public)
    if not ok:
        return False, error
    if not is_party_building_documents_code(system_folder):
        return True, None
    if require_folder and not folder_id:
        return False, '党建文档文件必须上传到党建文档目录内'
    if not is_folder_in_scope(folder_id, PARTY_BUILDING_DOCUMENTS_CODE, include_root=True):
        return False, SCOPE_ERROR_MSG
    return True, None

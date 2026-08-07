# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""File move view - with conflict handling and physical file migration."""

import os, json, shutil, logging
from django.views.generic import View
from django.db import transaction, IntegrityError
from django.conf import settings
from libs import json_response
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_auth import document_auth
from ...libs.document_utils import (
    get_file_model, get_folder_model, get_document_absolute_path, is_safe_path,
)
from ...libs.naming_utils import generate_unique_logical_name
from ...libs.view_utils import permission_denied_response
from ...services.conflict_service import (
    check_display_name_conflict, generate_unique_display_name,
    build_conflict_info, conflict_response, CONFLICT_ACTIONS,
)
from ...services.system_scope_validators import (
    validate_file_move_scope, validate_target_folder_scope,
)
from ..base import check_public_space_permission, log_operation

logger = logging.getLogger(__name__)
DOC_STORAGE_BASE = os.path.join(settings.BASE_DIR, 'storage', 'documents')


class FileMoveView(View):
    """Move file: update folder, migrate physical file, handle conflicts."""

    @document_auth('move')
    def post(self, request):
        params, error = self._parse_request(request)
        if error:
            return json_response(error=error)

        ok, se = validate_file_move_scope(
            params['system_folder'], params['is_public'], target_id=params['target_id'])
        if not ok:
            return json_response(error=se)

        FileModel = get_file_model(is_public=params['is_public'])
        FolderModel = get_folder_model(is_public=params['is_public'])
        file_obj = self._get_file(FileModel, params, request.user)
        if not file_obj:
            return json_response(error='文件不存在')

        pe = self._check_public_permission(request.user, file_obj, params['is_public'])
        if pe:
            return pe

        ok, se = validate_file_move_scope(
            params['system_folder'], params['is_public'],
            file_obj=file_obj, target_id=params['target_id'])
        if not ok:
            return json_response(error=se)

        target = self._get_target_folder(FolderModel, params, request.user)
        if params['target_id'] and not target:
            return json_response(error='目标文件夹不存在')

        current_folder_id = file_obj.folder_id if file_obj.folder else None
        if current_folder_id == params['target_id']:
            return json_response()

        return self._move_file(FileModel, file_obj, target, params, request)

    def _parse_request(self, request):
        try:
            data = getattr(request, '_document_cached_json_body', None) or json.loads(request.body)
        except Exception:
            return None, '参数错误'
        return {
            'file_id': data.get('id'),
            'target_id': data.get('target_id'),
            'is_public': data.get('is_public', False),
            'system_folder': data.get('system_folder'),
            'conflict_action': data.get('conflict_action'),
        }, None

    def _get_file(self, FileModel, params, user):
        query = FileModel.objects.filter(pk=params['file_id']).order_by()
        if not params['is_public']:
            query = apply_tenant_filter(query, user, strict_mode=True)
        return query.select_related('created_by').first()

    def _check_public_permission(self, user, file_obj, is_public):
        if not is_public:
            return None
        if check_public_space_permission(user, file_obj, 'file', '移动'):
            return None
        return permission_denied_response('公共空间中只能移动自己创建的文件', 'not_owner')

    def _get_target_folder(self, FolderModel, params, user):
        target_id = params['target_id']
        if not target_id:
            return None
        query = FolderModel.objects.filter(pk=target_id).order_by()
        if not params['is_public']:
            query = apply_tenant_filter(query, user, strict_mode=True)
        return query.first()

    def _move_file(self, FileModel, file_obj, target, params, request):
        """Execute move: conflict check -> physical migration -> DB update -> rollback."""
        display_name = file_obj.display_name or file_obj.name
        conflict_action = params.get('conflict_action')

        # 1. 预检冲突
        existing = check_display_name_conflict(
            FileModel, display_name, target, request.user, params['is_public'])
        if existing:
            if not conflict_action or conflict_action not in CONFLICT_ACTIONS:
                ci = build_conflict_info(existing, display_name, file_obj.file_size or 0)
                return conflict_response([ci])
            if conflict_action == 'skip':
                return json_response(data={'status': 'skipped', 'action': 'skip'})

        # 2. 物理文件迁移
        migrate_result = self._migrate_physical_files(
            file_obj, target, params, request, conflict_action)
        if isinstance(migrate_result, dict):
            return migrate_result  # error response
        old_path, old_thumb, new_path, new_thumb, physical_moved = migrate_result

        # 3. DB 更新（事务内重新校验）
        db_error = self._update_file_in_transaction(
            file_obj, FileModel, target, params, request,
            display_name, new_path, new_thumb, old_thumb, old_path,
            existing, conflict_action, physical_moved)
        if db_error:
            return db_error

        # 4. 清理 + 审计
        return self._finalize_move(
            file_obj, existing, conflict_action, params, request,
            old_path, old_thumb, new_path, new_thumb)

    def _migrate_physical_files(self, file_obj, target, params, request, conflict_action):
        """物理文件 + 缩略图迁移，返回 (old_path, old_thumb, new_path, new_thumb, moved) 或 error dict"""
        old_path = file_obj.file_path
        old_thumb = file_obj.thumbnail_path or ''
        target_folder_id = target.id if target else None
        target_dir = get_document_absolute_path(
            is_public=params['is_public'], user_id=request.user.id,
            folder_id=target_folder_id, system_folder=params.get('system_folder'))
        new_path = os.path.join(target_dir, file_obj.physical_name)

        if not is_safe_path(DOC_STORAGE_BASE, new_path):
            return json_response(error='目标路径异常')

        physical_moved = False
        if os.path.normpath(old_path) != os.path.normpath(new_path):
            os.makedirs(target_dir, exist_ok=True)
            if os.path.exists(new_path) and conflict_action != 'replace':
                return json_response(error='目标位置已存在同名物理文件')
            try:
                shutil.move(old_path, new_path)
                physical_moved = True
                logger.info('[Document] Physical file moved: %s -> %s', old_path, new_path)
            except Exception as e:
                logger.error('[Document] Physical file move failed: %s', e)
                return json_response(error=f'物理文件迁移失败: {e}')

        new_thumb = self._migrate_thumbnail(old_thumb, target_dir, physical_moved)
        return old_path, old_thumb, new_path, new_thumb, physical_moved

    @staticmethod
    def _migrate_thumbnail(old_thumb, target_dir, physical_moved):
        """迁移缩略图，返回新路径或空串"""
        if not old_thumb or not physical_moved:
            return old_thumb
        thumb_name = os.path.basename(old_thumb)
        candidate = os.path.join(target_dir, thumb_name)
        if os.path.normpath(old_thumb) == os.path.normpath(candidate):
            return old_thumb
        try:
            if os.path.exists(old_thumb):
                shutil.move(old_thumb, candidate)
                return candidate
        except Exception as e:
            logger.warning('[Document] Thumbnail move failed: %s', e)
        return ''

    def _update_file_in_transaction(self, file_obj, FileModel, target, params, request,
                                    display_name, new_path, new_thumb, old_thumb,
                                    old_path, existing, conflict_action, physical_moved):
        """事务内更新文件记录，返回 error response 或 None"""
        try:
            with transaction.atomic():
                if params['target_id']:
                    ok, err = validate_target_folder_scope(
                        params['system_folder'], params['is_public'],
                        params['target_id'], allow_root=True)
                    if not ok:
                        raise ValueError(err)

                recheck = check_display_name_conflict(
                    FileModel, display_name, target, request.user, params['is_public'])
                if recheck and recheck.id != (existing.id if existing else None):
                    if conflict_action != 'replace':
                        raise ValueError('目标位置已存在同名文件')

                if recheck:
                    if conflict_action == 'replace':
                        recheck.delete()
                    elif conflict_action == 'keep':
                        file_obj.display_name = generate_unique_display_name(
                            FileModel, display_name, target,
                            request.user, params['is_public'])

                file_obj.folder = target
                file_obj.name = generate_unique_logical_name(
                    FileModel, file_obj.display_name or file_obj.name,
                    target, request.user)
                file_obj.file_path = new_path
                update_fields = ['folder', 'name', 'file_path', 'display_name', 'updated_at']
                if new_thumb != old_thumb:
                    file_obj.thumbnail_path = new_thumb
                    update_fields.append('thumbnail_path')
                file_obj.save(update_fields=update_fields)
        except IntegrityError:
            logger.warning('[Document] move IntegrityError, id=%s', file_obj.id)
            self._rollback_physical(old_path, new_path, old_thumb, new_thumb, physical_moved)
            return json_response(error='目标位置已存在同名文件，移动失败')
        except ValueError as e:
            logger.warning('[Document] move scope/conflict error: %s', e)
            self._rollback_physical(old_path, new_path, old_thumb, new_thumb, physical_moved)
            return json_response(error=str(e))
        except Exception as exc:
            logger.error('[Document] file move failed: %s', exc)
            self._rollback_physical(old_path, new_path, old_thumb, new_thumb, physical_moved)
            return json_response(error=f'文件移动失败：{exc}')
        return None

    @staticmethod
    def _finalize_move(file_obj, existing, conflict_action, params, request,
                       old_path, old_thumb, new_path, new_thumb):
        """事务提交后的清理和审计日志"""
        if existing and conflict_action == 'replace':
            transaction.on_commit(lambda: FileMoveView._cleanup_deleted_file(
                existing.file_path, existing.thumbnail_path or ''))

        _act = conflict_action or 'move'
        _fid, _ip, _tid = file_obj.id, params['is_public'], params['target_id']
        transaction.on_commit(lambda: log_operation(
            action='FILE_MOVE', user=request.user, request=request,
            resource_type='FILE', resource_id=_fid,
            is_public=_ip, target_folder_id=_tid))
        logger.info('[Document] file moved: id=%s, action=%s', file_obj.id, _act)
        return json_response(data={'status': 'success', 'action': _act})

    @staticmethod
    def _rollback_physical(old_path, new_path, old_thumb, new_thumb, moved):
        """DB 保存失败时把物理文件移回原位置。"""
        if not moved:
            return
        try:
            if os.path.exists(new_path):
                shutil.move(new_path, old_path)
                logger.info('[Document] Physical file rolled back: %s', old_path)
        except Exception as e:
            logger.error('[Document] Failed to rollback physical file: %s', e)
        if new_thumb and old_thumb and new_thumb != old_thumb:
            try:
                if os.path.exists(new_thumb):
                    shutil.move(new_thumb, old_thumb)
            except Exception as e:
                logger.warning('[Document] Failed to rollback thumbnail: %s', e)

    @staticmethod
    def _cleanup_deleted_file(file_path, thumbnail_path):
        """事务提交后清理被 replace 删除的文件物理文件。"""
        for p in [file_path, thumbnail_path]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                    logger.info('[Document] Cleaned up deleted file: %s', p)
                except Exception as e:
                    logger.warning('[Document] Failed to cleanup deleted file %s: %s', p, e)

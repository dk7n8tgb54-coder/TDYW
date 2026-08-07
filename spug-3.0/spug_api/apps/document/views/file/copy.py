# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件复制视图
提供文件复制功能
"""

import os
import json
import shutil
import logging
from django.views.generic import View
from django.conf import settings
from django.db import IntegrityError, transaction

from libs import json_response, auth
from libs.tenant_utils import apply_tenant_filter
from apps.document.libs.document_utils import get_folder_model, get_file_model, get_document_absolute_path, is_safe_path
from apps.document.libs.naming_utils import generate_physical_name, generate_unique_logical_name, get_file_ext
from apps.document.libs.view_utils import permission_denied_response
from apps.document.libs.document_auth import document_auth
from apps.document.services.conflict_service import (
    check_display_name_conflict, generate_unique_display_name,
    build_conflict_info, conflict_response, CONFLICT_ACTIONS,
)
from apps.document.services.system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE, is_folder_in_scope,
    validate_system_folder_context, SCOPE_ERROR_MSG,
)
from apps.document.services.system_scope_validators import (
    validate_file_source_scope, validate_target_folder_scope,
)
from apps.document.views.base import create_model_instance, check_public_space_permission, log_operation
from apps.document.models import DocumentTransfer
from apps.document.constants import TransferStatus, TransferType

logger = logging.getLogger(__name__)


class FileCopyParamsParser:
    """文件复制参数解析器"""

    @staticmethod
    def parse(request):
        """解析请求参数"""
        try:
            data = getattr(request, '_document_cached_json_body', None) or json.loads(request.body)
            file_id = data.get('id')
            folder_id = data.get('folder_id')
            is_public = data.get('is_public', False)
            system_folder = data.get('system_folder')
            conflict_action = data.get('conflict_action')
            return {
                'file_id': file_id, 'folder_id': folder_id, 'is_public': is_public,
                'system_folder': system_folder, 'conflict_action': conflict_action,
            }, None
        except Exception:
            return None, '参数错误'


class FileCopyValidator:
    """文件复制验证器"""

    @staticmethod
    def validate_source_file(file_id, is_public, user):
        """验证源文件存在性（权限由调用方检查）"""
        FileModel = get_file_model(is_public=is_public)

        file_query = FileModel.objects.filter(pk=file_id).order_by()
        if not is_public:
            file_query = apply_tenant_filter(file_query, user, strict_mode=True)
        file = file_query.select_related('created_by').first()

        if not file:
            logger.error(f'[Document] Source file not found with id: {file_id}')
            return None, '文件不存在'

        return file, None

    @staticmethod
    def validate_target_folder(folder_id, is_public, user):
        """验证目标文件夹"""
        if not folder_id:
            return None, None

        FolderModel = get_folder_model(is_public=is_public)
        folder_query = FolderModel.objects.filter(pk=folder_id).order_by()
        if not is_public:
            folder_query = apply_tenant_filter(folder_query, user, strict_mode=True)
        folder = folder_query.first()

        if not folder:
            logger.error(f'[Document] Target folder not found with id: {folder_id}')
            return None, '目标文件夹不存在'

        return folder, None


class FileNameGenerator:
    """复制文件名生成器"""

    @staticmethod
    def generate(file, folder, is_public, user):
        """生成复制文件的名称"""
        FileModel = get_file_model(is_public=is_public)

        # 获取原始显示名
        original_display_name = file.display_name or file.name
        _, file_ext = get_file_ext(original_display_name)

        # 生成三层文件名
        physical_name = generate_physical_name(file_ext, original_display_name)
        logical_name = generate_unique_logical_name(FileModel, original_display_name, folder, user)

        return {
            'physical_name': physical_name,
            'logical_name': logical_name,
            'original_display_name': original_display_name
        }

    @staticmethod
    def resolve_display_name(original_name, folder, is_public, user, is_same_folder):
        """解析最终显示名称（处理重名）"""
        FileModel = get_file_model(is_public=is_public)

        new_display_name = original_name
        if is_same_folder:
            new_display_name = f'副本_{original_name}'

        # 检查目标文件夹下是否已存在同名显示名称
        existing_file_query = FileModel.objects.filter(
            folder=folder,
            display_name=new_display_name
        ).order_by()
        if not is_public:
            existing_file_query = apply_tenant_filter(existing_file_query, user, strict_mode=True)
        existing_file = existing_file_query.first()

        if existing_file:
            new_display_name = FileNameGenerator._add_numeric_suffix(
                new_display_name, folder, is_public, user
            )

        return new_display_name

    @staticmethod
    def _add_numeric_suffix(display_name, folder, is_public, user):
        """添加数字后缀解决重名"""
        FileModel = get_file_model(is_public=is_public)
        counter = 1
        new_display_name = display_name

        while True:
            name_without_ext, ext = os.path.splitext(display_name)
            new_display_name = f'{name_without_ext}_{counter}{ext}'

            existing_file_query = FileModel.objects.filter(
                folder=folder,
                display_name=new_display_name
            ).order_by()
            if not is_public:
                existing_file_query = apply_tenant_filter(existing_file_query, user, strict_mode=True)

            if not existing_file_query.first():
                break
            counter += 1

        return new_display_name


class FileCopyExecutor:
    """文件复制执行器"""

    @staticmethod
    def copy_physical_file(source_path, target_path):
        """复制物理文件"""
        shutil.copy2(source_path, target_path)
        logger.info(f'[Document] Physical file copied from {source_path} to {target_path}')

    @staticmethod
    def create_file_record(FileModel, logical_name, display_name, physical_name,
                          folder, file_path, source_file, user):
        """创建文件记录"""
        return create_model_instance(FileModel,
            name=logical_name,
            display_name=display_name,
            physical_name=physical_name,
            folder=folder,
            file_path=file_path,
            file_size=source_file.file_size,
            file_type=source_file.file_type,
            created_by=user
        )

    @staticmethod
    def build_upload_dir(is_public, user_id, folder):
        """构建上传目录"""
        upload_dir = get_document_absolute_path(
            is_public=is_public,
            user_id=user_id,
            folder_id=folder.id if folder else None
        )
        os.makedirs(upload_dir, exist_ok=True)
        return upload_dir


class FileCopyLogger:
    """文件复制日志记录器"""

    @staticmethod
    def log_copy_operation(user, new_file, source_file, original_name,
                          new_name, folder, is_public, request=None):
        """记录复制操作日志"""
        log_operation(
            action="FILE_COPY",
            user=user,
            request=request,
            resource_type="FILE",
            resource_id=new_file.id,
            is_public=is_public,
            source_file_id=source_file.id,
            original_display_name=original_name,
            new_display_name=new_name,
            target_folder_id=folder.id if folder else None
        )
        logger.info(f'[Document] File record created successfully, is_public={is_public}')


class FileCopyView(View):
    """文件复制视图"""

    @staticmethod
    def _validate_and_prepare(request):
        """验证复制请求参数、权限、作用域，返回 (ctx, None) 或 (None, error_response)"""
        params, error = FileCopyParamsParser.parse(request)
        if error:
            return None, json_response(error=error)

        file_id = params['file_id']
        if not file_id:
            return None, json_response(error='参数错误')

        is_public = params['is_public']
        system_folder = params.get('system_folder')

        ok, ctx_err = validate_system_folder_context(system_folder, is_public)
        if not ok:
            return None, json_response(error=ctx_err)

        file, error = FileCopyValidator.validate_source_file(file_id, is_public, request.user)
        if error:
            return None, json_response(error=error)

        if is_public and not check_public_space_permission(request.user, file, 'file', '复制'):
            return None, permission_denied_response('公共空间中只能复制自己创建的文件', 'not_owner')

        scope_ok, scope_err = validate_file_source_scope(system_folder, is_public, file)
        if not scope_ok:
            return None, json_response(error=scope_err)

        folder_id = params['folder_id']
        folder, error = FileCopyValidator.validate_target_folder(folder_id, is_public, request.user)
        if error:
            return None, json_response(error=error)

        if folder_id:
            target_ok, target_err = validate_target_folder_scope(
                system_folder, is_public, folder_id, allow_root=True
            )
            if not target_ok:
                return None, json_response(error=target_err)

        return {'file': file, 'folder': folder, 'is_public': is_public,
                'system_folder': system_folder, 'folder_id': folder_id,
                'conflict_action': params.get('conflict_action')}, None

    @document_auth('copy')
    def post(self, request):
        logger.info(f'[Document] FileCopyView.post called, user: {request.user.username}')

        ctx, error = self._validate_and_prepare(request)
        if error:
            return error

        file = ctx['file']
        folder = ctx['folder']
        is_public = ctx['is_public']
        folder_id = ctx['folder_id']
        conflict_action = ctx.get('conflict_action')

        logger.info(f'[Document] Copying file id: {file.id} to folder_id: {folder_id}, is_public={is_public}')

        FileModel = get_file_model(is_public=is_public)
        original_display_name = file.display_name or file.name

        # 冲突检测
        existing = check_display_name_conflict(
            FileModel, original_display_name, folder, request.user, is_public)

        conflict_result = self._handle_conflict(
            existing, conflict_action, original_display_name, file.file_size or 0)
        if conflict_result:
            return conflict_result

        # 确定最终 display_name
        final_display_name = self._resolve_display_name(
            existing, conflict_action, original_display_name, file, folder,
            FileModel, request.user, is_public)

        # 构建上传目录 & 生成文件名
        upload_dir = FileCopyExecutor.build_upload_dir(is_public, request.user.id, folder)
        names = FileNameGenerator.generate(file, folder, is_public, request.user)
        new_file_path = os.path.join(upload_dir, names['physical_name'])

        # 路径安全校验
        path_error = self._validate_paths(file.file_path, new_file_path)
        if path_error:
            return path_error

        logger.info(f'[Document] Generated names: physical={names["physical_name"]}, logical={names["logical_name"]}')

        # 大文件异步复制检查
        file_size = file.file_size or 0
        async_threshold = getattr(settings, 'DOCUMENT_ASYNC_COPY_THRESHOLD', 50 * 1024 * 1024)
        if file_size >= async_threshold:
            return self._submit_async_copy(
                FileModel, file, folder, is_public, request.user, final_display_name,
                names, new_file_path, conflict_action, system_folder=ctx.get('system_folder')
            )

        # 复制物理文件
        try:
            FileCopyExecutor.copy_physical_file(file.file_path, new_file_path)
        except Exception as e:
            logger.error(f'[Document] Physical file copy failed: {e}')
            return json_response(error=f'物理文件复制失败: {e}')

        # 创建文件记录（事务内重新校验冲突）
        new_file, db_error = self._create_record_with_retry(
            FileModel, file, folder, request.user, is_public,
            original_display_name, final_display_name,
            names, new_file_path, existing, conflict_action)
        if db_error:
            return db_error

        # 记录日志
        FileCopyLogger.log_copy_operation(
            request.user, new_file, file,
            original_display_name, final_display_name,
            folder, is_public, request=request
        )

        return json_response(data={'status': 'success', 'action': conflict_action or 'copy'})

    @staticmethod
    def _handle_conflict(existing, conflict_action, display_name, file_size):
        """冲突预检：无 action 时返回冲突信息，skip 时返回跳过响应"""
        if not existing:
            return None
        if not conflict_action or conflict_action not in CONFLICT_ACTIONS:
            ci = build_conflict_info(existing, display_name, file_size)
            return conflict_response([ci])
        if conflict_action == 'skip':
            return json_response(data={'status': 'skipped', 'action': 'skip'})
        return None

    @staticmethod
    def _resolve_display_name(existing, conflict_action, original_display_name,
                              file, folder, FileModel, user, is_public):
        """根据冲突状态和 action 确定最终 display_name"""
        is_same_folder = file.folder == folder
        if conflict_action == 'keep' or (not existing and is_same_folder):
            base_name = f'副本_{original_display_name}' if is_same_folder else original_display_name
            return generate_unique_display_name(FileModel, base_name, folder, user, is_public)
        return original_display_name

    @staticmethod
    def _validate_paths(source_path, target_path):
        """路径安全校验"""
        document_storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
        if not is_safe_path(document_storage_base, source_path):
            logger.error(f'[Document] Unsafe source file path in copy: {source_path}')
            return json_response(error='文件路径异常')
        if not is_safe_path(document_storage_base, target_path):
            logger.error(f'[Document] Unsafe target file path in copy: {target_path}')
            return json_response(error='文件路径异常')
        return None

    def _create_record_with_retry(self, FileModel, file, folder, user, is_public,
                                  original_display_name, final_display_name,
                                  names, new_file_path, existing, conflict_action):
        """事务内创建文件记录，处理并发冲突"""
        try:
            with transaction.atomic():
                recheck = check_display_name_conflict(
                    FileModel, final_display_name, folder, user, is_public)

                if recheck and (not existing or recheck.id != existing.id):
                    self._handle_concurrent_conflict(
                        recheck, conflict_action, FileModel, final_display_name,
                        folder, user, is_public)

                if existing and conflict_action == 'replace':
                    self._delete_conflict_file(existing)

                new_file = FileCopyExecutor.create_file_record(
                    FileModel,
                    generate_unique_logical_name(
                        FileModel, final_display_name, folder, user),
                    final_display_name,
                    names['physical_name'],
                    folder,
                    new_file_path,
                    file,
                    user
                )
            return new_file, None
        except ValueError as e:
            logger.warning('[Document] copy conflict error: %s', e)
            self._cleanup_physical(new_file_path)
            return None, json_response(error=str(e))
        except IntegrityError:
            logger.warning('[Document] file copy failed due to duplicate name, source_id=%s', file.id)
            self._cleanup_physical(new_file_path)
            return None, json_response(error='目标位置已存在同名文件，复制失败')

    @staticmethod
    def _handle_concurrent_conflict(recheck, conflict_action, FileModel,
                                     display_name, folder, user, is_public):
        """事务内检测到并发插入同名文件时的处理"""
        if conflict_action == 'replace':
            _path = recheck.file_path
            _thumb = recheck.thumbnail_path or ''
            recheck.delete()
            transaction.on_commit(lambda: FileCopyView._cleanup_deleted_file(_path, _thumb))
        elif conflict_action == 'keep':
            return generate_unique_display_name(
                FileModel, display_name, folder, user, is_public)
        else:
            raise ValueError('目标位置已存在同名文件')

    @staticmethod
    def _delete_conflict_file(existing):
        """删除冲突文件（事务提交后清理物理文件）"""
        _path = existing.file_path
        _thumb = existing.thumbnail_path or ''
        existing.delete()
        transaction.on_commit(lambda: FileCopyView._cleanup_deleted_file(_path, _thumb))

    @staticmethod
    def _cleanup_physical(file_path):
        """清理已复制的物理文件"""
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            logger.warning('[Document] failed to cleanup physical file: %s', file_path)

    @staticmethod
    def _cleanup_deleted_file(file_path, thumbnail_path):
        """事务提交后清理被 replace 删除的文件物理文件"""
        for p in [file_path, thumbnail_path]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                    logger.info('[Document] Cleaned up deleted file: %s', p)
                except Exception as e:
                    logger.warning('[Document] Failed to cleanup %s: %s', p, e)

    def _submit_async_copy(self, FileModel, source_file, folder, is_public, user,
                           final_display_name, names, new_file_path,
                           conflict_action, system_folder=None):
        """
        提交异步复制任务（大文件）

        1. 创建 DocumentTransfer 记录（PENDING）
        2. 尝试提交 Celery 任务
        3a. Celery 可用 -> 返回 pending 状态
        3b. Celery 不可用 -> 同步降级执行复制
        """
        from apps.document.tasks.async_copy import copy_file_async

        transfer = None
        try:
            transfer = DocumentTransfer.objects.create(
                transfer_type=TransferType.COPY.value,
                status=TransferStatus.PENDING.value,
                file_name=final_display_name,
                file_size=source_file.file_size or 0,
                file_path=new_file_path,
                file_hash=getattr(source_file, 'file_hash', '') or '',
                folder_id=folder.id if folder else None,
                is_public=is_public,
                system_folder=system_folder or '',
                progress=0,
                transferred_size=0,
                source_file_id=source_file.id,
                source_file_path=source_file.file_path,
                conflict_action=conflict_action or '',
                user=user,
                tenant_id=getattr(user, 'tenant_id', '') or '',
            )

            # 尝试提交 Celery 任务
            result = copy_file_async.delay(transfer.id)
            DocumentTransfer.objects.filter(pk=transfer.id).update(
                celery_task_id=result.id
            )

            logger.info(
                '[Document] Async copy submitted, transfer_id=%s, task_id=%s, file_size=%s',
                transfer.id, result.id, source_file.file_size
            )

            return json_response(data={
                'status': 'pending',
                'transfer_id': transfer.id,
                'task_id': result.id,
                'file_name': final_display_name,
                'file_size': source_file.file_size or 0,
                'message': '大文件正在后台复制中',
            })

        except Exception as e:
            logger.warning('[Document] Celery submit failed (%s), fallback to thread', e)

            # Celery 不可用 -> 后台线程降级执行
            if transfer:
                transfer.status = TransferStatus.COPYING.value
                transfer.save(update_fields=['status'])

            import threading

            def _run_copy_in_thread(tid=transfer.id, src_path=source_file.file_path,
                                    dst_path=new_file_path, file_size=source_file.file_size):
                try:
                    from apps.document.tasks.async_copy import copy_file_async
                    copy_file_async.apply((tid,))
                except Exception as inner_e:
                    logger.error('[Document] Thread fallback copy failed: %s', inner_e)
                    DocumentTransfer.objects.filter(pk=tid).update(
                        status=TransferStatus.FAILED.value,
                        error_message=f'复制失败: {inner_e}'[:500],
                    )

            t = threading.Thread(target=_run_copy_in_thread, daemon=True)
            t.start()

            return json_response(data={
                'status': 'pending',
                'transfer_id': transfer.id,
                'task_id': None,
                'file_name': final_display_name,
                'file_size': source_file.file_size or 0,
                'message': '大文件正在后台复制中',
            })

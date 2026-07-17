# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件夹管理模块 - 核心视图
提供文件夹的CRUD和列表查询功能
"""

import os
import time
import json
import shutil
import logging
from django.views.generic import View
from django.db import transaction, IntegrityError

from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_folder_model, get_file_model, get_document_absolute_path
from ...libs.view_utils import permission_denied_response
from ...libs.document_auth import document_auth
from ...services.system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE, get_system_root_folder_id,
    is_folder_in_scope, is_protected_system_root,
    ensure_folder_in_scope_or_error, validate_system_folder_context,
    exclude_system_file_scope, exclude_system_folder_scope,
    is_folder_in_any_system_scope,
    NORMAL_DOCUMENT_SCOPE_ERROR_MSG, SCOPE_ERROR_MSG, PROTECTED_ROOT_MSG,
)
from ...services.system_scope_validators import validate_upload_target_scope
from ..base import create_model_instance, validate_file_name, check_public_space_permission, log_operation

logger = logging.getLogger(__name__)


class FolderView(View):
    """文件夹视图（性能优化版）"""
    
    DEFAULT_PAGE_SIZE = 100
    MAX_PAGE_SIZE = 500

    @document_auth('view')
    def get(self, request):
        """
        获取文件夹列表和文件列表（支持分页优化）
        """
        logger.info(f'[Document] FolderView.get called, user: {request.user.username}')
        form, error = JsonParser(
            Argument('id', type=int, required=False, default=None),
            Argument('all', type=bool, required=False, default=False),
            Argument('is_public', type=bool, required=False, default=False),
            Argument('system_folder', type=str, required=False, default=None),
            Argument('page', type=int, required=False, default=1),
            Argument('page_size', type=int, required=False, default=None),
        ).parse(request.GET)
        
        if error is not None:
            logger.error(f'[Document] Parse error: {error}')
            return json_response(error=error)

        # 党建文档上下文校验
        system_folder = form.system_folder
        ok, ctx_err = validate_system_folder_context(system_folder, form.is_public)
        if not ok:
            return json_response(error=ctx_err)

        # 党建文档模式：id 为空时自动定位到根目录，id 非空时校验在范围内
        if system_folder == PARTY_BUILDING_DOCUMENTS_CODE:
            root_id = get_system_root_folder_id(PARTY_BUILDING_DOCUMENTS_CODE)
            if root_id is None:
                return json_response(error='党建文档系统目录尚未初始化')
            if not form.id:
                form.id = root_id
            elif form.id != root_id and not is_folder_in_scope(form.id, PARTY_BUILDING_DOCUMENTS_CODE, include_root=False):
                return json_response(error=SCOPE_ERROR_MSG)
        elif form.is_public and form.id and is_folder_in_any_system_scope(form.id, include_root=True):
            return json_response(error=NORMAL_DOCUMENT_SCOPE_ERROR_MSG)

        page = max(1, form.page)
        page_size = form.page_size or self.DEFAULT_PAGE_SIZE
        page_size = min(page_size, self.MAX_PAGE_SIZE)

        FolderModel = get_folder_model(is_public=form.is_public)
        FileModel = get_file_model(is_public=form.is_public)

        if not form.id:
            if form.all:
                return self._get_all_folders(request, FolderModel, form.is_public, system_folder)
            else:
                return self._get_root_contents(request, FolderModel, FileModel, form.is_public, page, page_size, system_folder)
        else:
            return self._get_folder_contents(request, FolderModel, FileModel, form.id, form.is_public, page, page_size, system_folder)
    
    def _get_all_folders(self, request, FolderModel, is_public, system_folder=None):
        """获取所有文件夹（树形结构）"""
        query = FolderModel.objects.filter(is_deleted=False).select_related('created_by').order_by('-created_at')
        if not is_public:
            query = apply_tenant_filter(query, request.user, strict_mode=True)

        # 党建文档模式：只返回根目录及其子孙
        if system_folder == PARTY_BUILDING_DOCUMENTS_CODE:
            from ...services.system_folder_service import get_descendant_folder_ids
            scope_ids = get_descendant_folder_ids(PARTY_BUILDING_DOCUMENTS_CODE, include_root=True)
            query = query.filter(id__in=scope_ids)
        elif is_public:
            query = exclude_system_folder_scope(query)

        max_folders = 1000
        folders = query[:max_folders]
        
        result = [
            {
                'id': f.id, 
                'name': f.name, 
                'parent_id': f.parent_id, 
                'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'), 
                'updated_at': f.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
                'created_by': f.created_by.nickname if f.created_by else None, 
                'created_by_id': f.created_by_id
            }
            for f in folders
        ]
        return json_response(result)
    
    def _get_root_contents(self, request, FolderModel, FileModel, is_public, page, page_size, system_folder=None):
        """获取根目录内容（分页优化）"""
        folders_query = FolderModel.objects.filter(parent__isnull=True, is_deleted=False).select_related('created_by').order_by('-created_at')
        if not is_public:
            folders_query = apply_tenant_filter(folders_query, request.user, strict_mode=True)
        elif system_folder != PARTY_BUILDING_DOCUMENTS_CODE:
            folders_query = exclude_system_folder_scope(folders_query)

        files_query = FileModel.objects.filter(folder__isnull=True).select_related('created_by').order_by('-created_at')
        if not is_public:
            files_query = apply_tenant_filter(files_query, request.user, strict_mode=True)
        elif system_folder != PARTY_BUILDING_DOCUMENTS_CODE:
            files_query = exclude_system_file_scope(files_query)

        # 统一分页：文件夹在前，文件在后
        offset = (page - 1) * page_size

        # 先获取所有文件夹，再根据 offset 和 page_size 决定返回哪些
        folders = folders_query[offset:offset + page_size]

        # 【P2-3修复】缓存count结果，避免重复查询
        folder_count = folders_query.count()
        if offset >= folder_count:
            # 跳过所有文件夹，只返回文件
            file_offset = offset - folder_count
            files = files_query[file_offset:file_offset + page_size]
        elif offset + page_size <= folder_count:
            # 只返回文件夹，不返回文件
            files = []
        else:
            # 返回部分文件夹和部分文件
            file_count = offset + page_size - folder_count
            files = files_query[:file_count]

        # 【P2-3修复】使用已缓存的count结果
        total_folders = folder_count
        total_files = files_query.count()
        # 合并分页：文件夹在前、文件在后，has_more 应按两者总数判断
        total_items = total_folders + total_files

        result = {
            'folders': [
                {
                    'id': f.id,
                    'name': f.name,
                    'parent_id': f.parent_id,
                    'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'updated_at': f.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'created_by': f.created_by.nickname if f.created_by else None,
                    'created_by_id': f.created_by_id
                }
                for f in folders
            ],
            'files': [self._format_file(f) for f in files],
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_folders': total_folders,
                'total_files': total_files,
                'has_more': (offset + page_size) < total_items
            }
        }
        return json_response(result)

    def _get_folder_contents(self, request, FolderModel, FileModel, folder_id, is_public, page, page_size, system_folder=None):
        """获取指定文件夹内容（分页优化）"""
        folders_query = FolderModel.objects.filter(parent_id=folder_id, is_deleted=False).select_related('created_by').order_by('-created_at')
        if not is_public:
            folders_query = apply_tenant_filter(folders_query, request.user, strict_mode=True)
        elif system_folder != PARTY_BUILDING_DOCUMENTS_CODE:
            folders_query = exclude_system_folder_scope(folders_query)

        files_query = FileModel.objects.filter(folder_id=folder_id).select_related('created_by').order_by('-created_at')
        if not is_public:
            files_query = apply_tenant_filter(files_query, request.user, strict_mode=True)
        elif system_folder != PARTY_BUILDING_DOCUMENTS_CODE:
            files_query = exclude_system_file_scope(files_query)

        # 统一分页：文件夹在前，文件在后
        offset = (page - 1) * page_size

        # 先获取所有文件夹，再根据 offset 和 page_size 决定返回哪些
        folders = folders_query[offset:offset + page_size]

        # 【P2-3修复】缓存count结果，避免重复查询
        folder_count = folders_query.count()
        if offset >= folder_count:
            # 跳过所有文件夹，只返回文件
            file_offset = offset - folder_count
            files = files_query[file_offset:file_offset + page_size]
        elif offset + page_size <= folder_count:
            # 只返回文件夹，不返回文件
            files = []
        else:
            # 返回部分文件夹和部分文件
            file_count = offset + page_size - folder_count
            files = files_query[:file_count]

        # 【P2-3修复】使用已缓存的count结果
        total_folders = folder_count
        total_files = files_query.count()
        # 合并分页：文件夹在前、文件在后，has_more 应按两者总数判断
        total_items = total_folders + total_files

        result = {
            'folders': [
                {
                    'id': f.id,
                    'name': f.name,
                    'parent_id': f.parent_id,
                    'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'updated_at': f.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'created_by': f.created_by.nickname if f.created_by else None,
                    'created_by_id': f.created_by_id
                }
                for f in folders
            ],
            'files': [self._format_file(f) for f in files],
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_folders': total_folders,
                'total_files': total_files,
                'has_more': (offset + page_size) < total_items
            }
        }
        return json_response(result)

    def _format_file(self, f):
        """格式化文件信息"""
        return {
            'id': f.id,
            'name': f.name,
            'display_name': f.display_name if hasattr(f, 'display_name') else None,
            'size': f.file_size,  # 返回原始字节数，由前端格式化显示
            'file_type': f.file_type,
            'folder_id': f.folder_id,
            'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': f.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            'created_by': f.created_by.nickname if f.created_by else None,
            'created_by_id': f.created_by_id,
            'thumbnail_path': f.thumbnail_path if hasattr(f, 'thumbnail_path') else None,  # 缩略图路径
        }

    @document_auth('create_folder')
    def post(self, request):
        """创建文件夹（幂等：同名同父目录已存在则返回已有 ID）"""
        try:
            data = request._document_cached_json_body if hasattr(request, '_document_cached_json_body') else json.loads(request.body)
            name = data.get('name')
            parent_id = data.get('parent_id')
            is_public = data.get('is_public', False)
            system_folder = data.get('system_folder')
        except Exception as e:
            logger.error(f'解析请求参数失败: {e}')
            return json_response(error='参数错误')

        if not name:
            return json_response(error='请输入文件夹名称')

        if not validate_file_name(name):
            return json_response(error='文件夹名称包含非法字符')

        ok, scope_err = validate_upload_target_scope(system_folder, is_public, parent_id)
        if not ok:
            return json_response(error=scope_err)

        FolderModel = get_folder_model(is_public=is_public)
        parent = None

        if parent_id:
            try:
                parent_id = int(parent_id)
            except (ValueError, TypeError):
                return json_response(error='父文件夹ID无效')

            if parent_id <= 0:
                return json_response(error='父文件夹ID无效')

            parent_query = FolderModel.objects.filter(pk=parent_id, is_deleted=False).order_by()
            if not is_public:
                parent_query = apply_tenant_filter(parent_query, request.user, strict_mode=True)
            parent = parent_query.first()
            if not parent:
                return json_response(error='父文件夹不存在')

        # 幂等创建：先查已有，再创建，撞 unique_key 时再查一次
        existing = self._find_existing_folder(FolderModel, name, parent_id, is_public, request.user)
        if existing:
            return json_response({'id': existing.id, 'created': False})

        try:
            with transaction.atomic():
                if parent:
                    new_folder = create_model_instance(FolderModel, name=name, parent=parent, created_by=request.user)
                else:
                    new_folder = create_model_instance(FolderModel, name=name, created_by=request.user)
            return json_response({'id': new_folder.id, 'created': True})
        except IntegrityError as e:
            # 撞 unique_key：并发创建时另一个请求已插入，再查一次拿已有 ID
            existing = self._find_existing_folder(FolderModel, name, parent_id, is_public, request.user)
            if existing:
                logger.info(f'[FolderView] 并发创建冲突，返回已有文件夹: name={name}, parent_id={parent_id}, id={existing.id}')
                return json_response({'id': existing.id, 'created': False})
            logger.error(f'[FolderView] 创建文件夹唯一键冲突但未找到已有目录: name={name}, parent_id={parent_id}, error={e}')
            return json_response(error='文件夹创建失败，请稍后重试')

    @staticmethod
    def _find_existing_folder(FolderModel, name, parent_id, is_public, user):
        """查找同名同父目录的已有文件夹（幂等创建辅助方法）"""
        qs = FolderModel.objects.filter(name=name, is_deleted=False).order_by()

        if parent_id:
            qs = qs.filter(parent_id=parent_id)
        else:
            qs = qs.filter(parent__isnull=True)

        if not is_public:
            qs = apply_tenant_filter(qs, user, strict_mode=True)
            qs = qs.filter(created_by=user)

        return qs.first()

    @document_auth('delete')
    def delete(self, request):
        """删除文件夹"""
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False),
            Argument('system_folder', type=str, required=False, default=None),
        ).parse(request.GET)
        
        if error is not None:
            return json_response(error=error)

        # 党建文档上下文与根目录保护
        ok, ctx_err = validate_system_folder_context(form.system_folder, form.is_public)
        if not ok:
            return json_response(error=ctx_err)
        if form.system_folder == PARTY_BUILDING_DOCUMENTS_CODE:
            if is_protected_system_root(form.id):
                return json_response(error=PROTECTED_ROOT_MSG)
            scope_ok, scope_err = ensure_folder_in_scope_or_error(
                form.id, PARTY_BUILDING_DOCUMENTS_CODE, include_root=False
            )
            if not scope_ok:
                return json_response(error=scope_err)
            
        FolderModel = get_folder_model(is_public=form.is_public)
        FileModel = get_file_model(is_public=form.is_public)

        folder_query = FolderModel.objects.filter(pk=form.id, is_deleted=False).order_by()
        if not form.is_public:
            folder_query = apply_tenant_filter(folder_query, request.user, strict_mode=True)
        folder = folder_query.first()
        
        if not folder:
            return json_response(error='文件夹不存在')

        # 公共空间权限校验
        if form.is_public and not check_public_space_permission(request.user, folder, 'folder', '删除'):
            return permission_denied_response('公共空间中只能删除自己创建的文件夹', 'not_owner')

        folder_name = folder.name
        folder_id = folder.id
        try:
            self._delete_folder(folder, FolderModel, FileModel, form.is_public, request.user, request.user)
            log_operation(
                action="FOLDER_DELETE",
                user=request.user,
                resource_type="FOLDER",
                resource_id=folder_id,
                is_public=form.is_public,
                folder_name=folder_name
            )
            return json_response()
        except Exception as e:
            logger.error(f'[Document] Error deleting folder {folder_name}: {e}')
            # 【P2-6修复】返回通用错误消息，避免信息泄露
            return json_response(error='文件夹删除失败，请稍后重试')

    def _delete_folder(self, folder, FolderModel, FileModel, is_public, request_user=None, deleted_by=None):
        """递归物理删除文件夹及其内容"""
        start_time = time.time()
        BATCH_SIZE = 50

        # 第一步：递归物理删除子文件夹
        sub_folders_query = FolderModel.objects.filter(parent=folder, is_deleted=False).order_by()
        if request_user and not is_public:
            sub_folders_query = apply_tenant_filter(sub_folders_query, request_user, strict_mode=True)
        sub_folders_count = sub_folders_query.count()
        logger.info(f'[Document] Deleting folder {folder.name} (id={folder.id}) with {sub_folders_count} subfolders')
        
        if sub_folders_count > 0:
            for sub_folder in list(sub_folders_query):
                self._delete_folder(sub_folder, FolderModel, FileModel, is_public, request_user, deleted_by)

        # 第二步：分批物理删除当前文件夹下的文件
        delete_errors = []
        files = folder.files.filter(is_deleted=False).select_related('created_by')
        files_count = files.count()
        logger.info(f'[Document] Deleting {files_count} files in folder {folder.name}')

        # 收集所有文件的父目录，用于删除后兜底清理物理残留目录
        parent_dirs_to_clean = set()

        total_deleted = 0
        for batch_start in range(0, files_count, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, files_count)
            batch_files = files[batch_start:batch_end]
            batch_files_list = list(batch_files)

            try:
                with transaction.atomic():
                    for file in batch_files_list:
                        try:
                            # 删除前收集父目录（兜底清理用）
                            file_path = getattr(file, 'file_path', None)
                            if file_path:
                                parent_dir = os.path.dirname(file_path)
                                if parent_dir:
                                    parent_dirs_to_clean.add(parent_dir)
                            file.delete(hard=True)
                            logger.info(f'[Document] File deleted: {file.name} (id={file.id})')
                        except Exception as e:
                            delete_errors.append(f"文件{file.name}删除失败: {str(e)}")
                            logger.error(f'[Document] Failed to delete file {file.name}: {e}')

                    total_deleted += len(batch_files_list)
                    logger.info(f'[Document] Batch delete progress: {total_deleted}/{files_count} files deleted')

            except Exception as batch_error:
                logger.error(f'[Document] Batch delete failed at batch {batch_start//BATCH_SIZE}: {batch_error}')
                delete_errors.append(f"批次删除失败: {str(batch_error)}")

        # 第三步：删除物理目录 + 文件夹数据库记录
        try:
            from apps.document.services.cleanup_service import (
                PhysicalFolderCleaner, cleanup_parent_dirs_safe
            )
            PhysicalFolderCleaner.delete(
                folder,
                is_public=is_public,
                user_id=getattr(folder, 'created_by_id', None)
            )
            folder.delete(hard=True)
            logger.info(f'[Document] Folder deleted: {folder.name} (id={folder.id})')
        except Exception as e:
            logger.error(f'[Document] Error deleting folder record: {e}')

        # 兜底清理：基于真实 file_path 的父目录清理（即使目录规则变化也能清理残留）
        cleanup_parent_dirs_safe(parent_dirs_to_clean)

        cost = time.time() - start_time
        if cost > 240:
            logger.warning(f'[Document] FolderDelete 耗时过长: folder_id={folder.id}, name={folder.name}, cost={cost:.2f}秒')
        logger.info(f'[Document] Folder {folder.name} (id={folder.id}) deleted successfully, cost={cost:.2f}秒')

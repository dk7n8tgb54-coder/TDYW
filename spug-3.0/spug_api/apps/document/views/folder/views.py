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
from django.db.models import Exists, OuterRef

from libs import json_response, JsonParser, Argument, auth
from ...libs.document_utils import get_document_absolute_path
from ...models import DocumentFolderPublic, DocumentFilePublic
from ...libs.view_utils import permission_denied_response
from ...libs.document_auth import document_auth
from ...constants import DEFAULT_MAX_FOLDER_DEPTH
from ...services.system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE, get_system_root_folder_id,
    is_folder_in_scope, is_protected_system_root,
    ensure_folder_in_scope_or_error, validate_system_folder_context,
    exclude_system_file_scope, exclude_system_folder_scope,
    is_folder_in_any_system_scope, get_descendant_folder_ids,
    NORMAL_DOCUMENT_SCOPE_ERROR_MSG, SCOPE_ERROR_MSG, PROTECTED_ROOT_MSG,
)
from ...services.system_scope_validators import (
    validate_upload_target_scope, validate_folder_source_scope,
)
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
        # 注意：all=true 时不需要自动设置 id（_get_all_folders 会自行处理范围过滤）
        if system_folder == PARTY_BUILDING_DOCUMENTS_CODE:
            root_id = get_system_root_folder_id(PARTY_BUILDING_DOCUMENTS_CODE)
            if root_id is None:
                return json_response(error='党建文档系统目录尚未初始化')
            if not form.id and not form.all:
                form.id = root_id
            elif form.id and form.id != root_id and not is_folder_in_scope(form.id, PARTY_BUILDING_DOCUMENTS_CODE, include_root=False):
                return json_response(error=SCOPE_ERROR_MSG)
        elif form.id and is_folder_in_any_system_scope(form.id, include_root=True):
            return json_response(error=NORMAL_DOCUMENT_SCOPE_ERROR_MSG)

        page = max(1, form.page)
        page_size = form.page_size or self.DEFAULT_PAGE_SIZE
        page_size = min(page_size, self.MAX_PAGE_SIZE)

        FolderModel = DocumentFolderPublic
        FileModel = DocumentFilePublic

        if not form.id:
            if form.all:
                return self._get_all_folders(request, FolderModel, form.is_public, system_folder)
            else:
                return self._get_root_contents(request, FolderModel, FileModel, form.is_public, page, page_size, system_folder)
        else:
            return self._get_folder_contents(request, FolderModel, FileModel, form.id, form.is_public, page, page_size, system_folder)
    
    def _get_all_folders(self, request, FolderModel, is_public, system_folder=None):
        """获取所有文件夹（树形结构）"""
        query = FolderModel.objects.all().select_related('created_by').order_by('name', 'id')
        # 党建文档模式：只返回根目录及其子孙
        if system_folder == PARTY_BUILDING_DOCUMENTS_CODE:
            scope_ids = get_descendant_folder_ids(PARTY_BUILDING_DOCUMENTS_CODE, include_root=True)
            query = query.filter(id__in=scope_ids)
        else:
            query = exclude_system_folder_scope(query)

        # 标注 has_children（Exists 子查询，避免 N+1）
        query = self._annotate_has_children(query, FolderModel, request, is_public, system_folder)

        max_folders = 1000
        folders = query[:max_folders]
        
        result = [self._format_folder(f) for f in folders]
        return json_response(result)
    
    def _get_root_contents(self, request, FolderModel, FileModel, is_public, page, page_size, system_folder=None):
        """获取根目录内容（分页优化）"""
        folders_query = FolderModel.objects.filter(parent__isnull=True).select_related('created_by').order_by('name', 'id')
        if system_folder != PARTY_BUILDING_DOCUMENTS_CODE:
            folders_query = exclude_system_folder_scope(folders_query)

        # 标注 has_children（Exists 子查询，避免 N+1）
        folders_query = self._annotate_has_children(folders_query, FolderModel, request, is_public, system_folder)

        files_query = FileModel.objects.filter(folder__isnull=True).select_related('created_by').order_by('display_name', 'id')
        if system_folder != PARTY_BUILDING_DOCUMENTS_CODE:
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
            'folders': [self._format_folder(f) for f in folders],
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
        folders_query = FolderModel.objects.filter(parent_id=folder_id).select_related('created_by').order_by('name', 'id')
        if system_folder != PARTY_BUILDING_DOCUMENTS_CODE:
            folders_query = exclude_system_folder_scope(folders_query)

        # 标注 has_children（Exists 子查询，避免 N+1）
        folders_query = self._annotate_has_children(folders_query, FolderModel, request, is_public, system_folder)

        files_query = FileModel.objects.filter(folder_id=folder_id).select_related('created_by').order_by('display_name', 'id')
        if system_folder != PARTY_BUILDING_DOCUMENTS_CODE:
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
            'folders': [self._format_folder(f) for f in folders],
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

    def _annotate_has_children(self, folders_query, FolderModel, request, is_public, system_folder):
        """为文件夹查询标注 has_children（Exists 子查询，避免 N+1）。

        子目录存在性严格遵守目录接口的可见范围（fail-closed）：
        - 普通公共空间：排除系统目录作用域的子目录
        - 党建文档：仅党建根目录子树内的子目录
        - 软删除子目录不计入；文件不计入，仅直接子文件夹决定 has_children
        """
        children_qs = FolderModel.objects.filter(
            parent_id=OuterRef('pk'),
        )
        if system_folder == PARTY_BUILDING_DOCUMENTS_CODE:
            scope_ids = get_descendant_folder_ids(PARTY_BUILDING_DOCUMENTS_CODE, include_root=True)
            if scope_ids:
                children_qs = children_qs.filter(id__in=scope_ids)
            else:
                children_qs = children_qs.none()
        else:
            # 普通公共空间：排除系统目录作用域
            children_qs = exclude_system_folder_scope(children_qs)
        return folders_query.annotate(has_children=Exists(children_qs))

    def _format_folder(self, f):
        """格式化文件夹信息（含 has_children，向后兼容）"""
        return {
            'id': f.id,
            'name': f.name,
            'parent_id': f.parent_id,
            'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': f.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            'created_by': f.created_by.nickname if f.created_by else None,
            'created_by_id': f.created_by_id,
            'has_children': bool(getattr(f, 'has_children', False)),
        }

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

        FolderModel = DocumentFolderPublic
        parent = None

        if parent_id:
            try:
                parent_id = int(parent_id)
            except (ValueError, TypeError):
                return json_response(error='父文件夹ID无效')

            if parent_id <= 0:
                return json_response(error='父文件夹ID无效')

            parent_query = FolderModel.objects.filter(pk=parent_id).order_by()
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
            # R3 修复：添加文件夹创建审计日志
            _folder_id = new_folder.id
            _is_public = is_public
            _user = request.user
            _req = request
            _name = name
            transaction.on_commit(lambda: log_operation(
                action='FOLDER_CREATE',
                user=_user,
                request=_req,
                resource_type='FOLDER',
                resource_id=_folder_id,
                is_public=_is_public,
                folder_name=_name,
            ))
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
        qs = FolderModel.objects.filter(name=name).order_by()

        if parent_id:
            qs = qs.filter(parent_id=parent_id)
        else:
            qs = qs.filter(parent__isnull=True)

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

        # 党建文档上下文与根目录保护（统一：党建正向 + 普通反向隔离）
        ok, ctx_err = validate_system_folder_context(form.system_folder, form.is_public)
        if not ok:
            return json_response(error=ctx_err)
        scope_ok, scope_err = validate_folder_source_scope(
            form.system_folder, form.is_public, folder_id=form.id,
            include_root=False, protect_root=True,
        )
        if not scope_ok:
            return json_response(error=scope_err)
            
        FolderModel = DocumentFolderPublic
        FileModel = DocumentFilePublic

        folder_query = FolderModel.objects.filter(pk=form.id).order_by()
        folder = folder_query.first()
        
        if not folder:
            return json_response(error='文件夹不存在')

        # 公共空间权限校验
        if not check_public_space_permission(request.user, folder, 'folder', '删除'):
            return permission_denied_response('公共空间中只能删除自己创建的文件夹', 'not_owner')

        folder_name = folder.name
        folder_id = folder.id
        try:
            # R9 修复：外层事务保护，确保递归删除中途失败时回滚所有 DB 变更
            with transaction.atomic():
                self._delete_folder(folder, FolderModel, FileModel, form.is_public, request.user, request.user)
            # R3 修复：audit log 移到 on_commit，确保事务提交后才记录
            _is_public = form.is_public
            _user = request.user
            _req = request
            transaction.on_commit(lambda: log_operation(
                action="FOLDER_DELETE",
                user=_user,
                request=_req,
                resource_type="FOLDER",
                resource_id=folder_id,
                is_public=_is_public,
                folder_name=folder_name,
            ))
            return json_response()
        except Exception as e:
            logger.error(f'[Document] Error deleting folder {folder_name}: {e}')
            # 【P2-6修复】返回通用错误消息，避免信息泄露
            return json_response(error='文件夹删除失败，请稍后重试')

    # R6 修复：递归删除深度限制，防极深嵌套触发 RecursionError
    MAX_FOLDER_DEPTH = DEFAULT_MAX_FOLDER_DEPTH

    def _delete_folder(self, folder, FolderModel, FileModel, is_public, request_user=None, deleted_by=None, _depth=0):
        """递归物理删除文件夹及其内容

        R6 修复：添加 _depth 参数，超过 MAX_FOLDER_DEPTH 时抛异常防止栈溢出。
        """
        if _depth > self.MAX_FOLDER_DEPTH:
            raise RuntimeError(
                f'文件夹嵌套深度超过上限 {self.MAX_FOLDER_DEPTH}，'
                f'可能存在循环引用（folder_id={folder.id}）'
            )
        start_time = time.time()
        BATCH_SIZE = 50

        # 第一步：递归物理删除子文件夹
        sub_folders_query = FolderModel.objects.filter(parent=folder).order_by()
        sub_folders_count = sub_folders_query.count()
        logger.info(f'[Document] Deleting folder {folder.name} (id={folder.id}) with {sub_folders_count} subfolders')
        
        if sub_folders_count > 0:
            for sub_folder in list(sub_folders_query):
                self._delete_folder(sub_folder, FolderModel, FileModel, is_public, request_user, deleted_by, _depth=_depth + 1)

        # 第二步：分批物理删除当前文件夹下的文件
        base_files_qs = folder.files.all().select_related('created_by')
        files_count = base_files_qs.count()
        logger.info(f'[Document] Deleting {files_count} files in folder {folder.name}')

        parent_dirs_to_clean = set()
        delete_errors = self._batch_delete_files(
            base_files_qs, files_count, BATCH_SIZE, is_public,
            request_user, parent_dirs_to_clean
        )

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
            folder.delete()
            logger.info(f'[Document] Folder deleted: {folder.name} (id={folder.id})')
        except Exception as e:
            logger.error(f'[Document] Error deleting folder record: {e}')

        # 兜底清理：基于真实 file_path 的父目录清理（即使目录规则变化也能清理残留）
        cleanup_parent_dirs_safe(parent_dirs_to_clean)

        cost = time.time() - start_time
        if cost > 240:
            logger.warning(f'[Document] FolderDelete 耗时过长: folder_id={folder.id}, name={folder.name}, cost={cost:.2f}秒')
        logger.info(f'[Document] Folder {folder.name} (id={folder.id}) deleted successfully, cost={cost:.2f}秒')

    def _batch_delete_files(self, base_files_qs, files_count, batch_size, is_public, request_user, parent_dirs_to_clean):
        """分批物理删除文件，返回错误列表"""
        delete_errors = []
        failed_file_ids = set()
        max_iterations = (files_count // batch_size) + 10
        iteration = 0
        total_deleted = 0

        while True:
            iteration += 1
            if iteration > max_iterations:
                logger.warning(f'[Document] Folder delete exceeded safety iteration limit (iter={iteration})')
                break

            batch_files_list = list(base_files_qs.exclude(id__in=failed_file_ids)[:batch_size])
            if not batch_files_list:
                break

            batch_success_count = 0
            try:
                with transaction.atomic():
                    for file in batch_files_list:
                        try:
                            file_path = getattr(file, 'file_path', None)
                            if file_path:
                                parent_dir = os.path.dirname(file_path)
                                if parent_dir:
                                    parent_dirs_to_clean.add(parent_dir)
                            file.delete()
                            batch_success_count += 1
                            logger.info(f'[Document] File deleted: {file.name} (id={file.id})')
                            _file_id = file.id
                            _file_name = file.name
                            _is_public = is_public
                            _user = request_user
                            transaction.on_commit(lambda _fid=_file_id, _fn=_file_name, _ip=_is_public, _u=_user: log_operation(
                                action="FILE_DELETE", user=_u, resource_type="FILE",
                                resource_id=_fid, is_public=_ip, file_name=_fn,
                            ))
                        except Exception as e:
                            failed_file_ids.add(file.id)
                            delete_errors.append(f"文件{file.name}删除失败: {str(e)}")
                            logger.error(f'[Document] Failed to delete file {file.name}: {e}')
                    total_deleted += batch_success_count
                    logger.info(f'[Document] Batch delete progress: {total_deleted}/{files_count} files deleted')
            except Exception as batch_error:
                logger.error(f'[Document] Batch delete failed (iter={iteration}): {batch_error}')
                delete_errors.append(f"批次删除失败: {str(batch_error)}")
                break

        return delete_errors

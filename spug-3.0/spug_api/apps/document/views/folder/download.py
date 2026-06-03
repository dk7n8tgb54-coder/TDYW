# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件夹下载视图
提供文件夹打包下载功能
"""

import os
import zipfile
import tempfile
import logging
from django.conf import settings
from django.views.generic import View
from django.http import StreamingHttpResponse
from urllib.parse import quote

from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_folder_model, get_file_model, is_safe_path
from ..base import log_operation

logger = logging.getLogger(__name__)


class FolderDownloadView(View):
    """文件夹下载视图 - ZIP打包"""

    @auth('document.document.view')
    def get(self, request):
        logger.info(f'[Document] FolderDownloadView.get called, user: {request.user.username}')
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)
        
        if error is not None:
            logger.error(f'[Document] Download parse error: {error}')
            return json_response(error=error)
            
        FolderModel = get_folder_model(is_public=form.is_public)
        FileModel = get_file_model(is_public=form.is_public)

        logger.info(f'[Document] Downloading folder id: {form.id}, is_public={form.is_public}')
        folder_query = FolderModel.objects.filter(pk=form.id)
        if not form.is_public:
            folder_query = apply_tenant_filter(folder_query, request.user, strict_mode=True)
        folder = folder_query.select_related('created_by').first()
        
        if not folder:
            logger.error(f'[Document] Folder not found with id: {form.id}')
            return json_response(error='文件夹不存在')

        # 【P0-1修复】使用临时文件替代内存缓冲区，避免大文件夹下载OOM
        zip_path = None
        try:
            # 创建临时 ZIP 文件（不依赖 Windows 文件锁）
            zip_fd, zip_path = tempfile.mkstemp(suffix='.zip', prefix='spug_folder_')
            os.close(zip_fd)  # mkstemp 返回已打开的 fd，需要关闭

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                self._add_folder_to_zip(folder, zipf, '', FolderModel, FileModel, form.is_public, request.user)

            encoded_foldername = quote(folder.name)
            zip_size = os.path.getsize(zip_path)

            # 【P0-1修复】使用 StreamingHttpResponse 流式传输，内存占用恒定 ~64KB
            response = StreamingHttpResponse(
                self._file_iterator(zip_path, chunk_size=65536),
                content_type='application/zip'
            )
            response['Content-Disposition'] = f'attachment; filename="{encoded_foldername}.zip"; filename*=UTF-8\'\'{encoded_foldername}.zip'
            response['Content-Length'] = zip_size

            # 响应结束后清理临时文件
            def cleanup_zip():
                if zip_path and os.path.exists(zip_path):
                    try:
                        os.remove(zip_path)
                    except OSError:
                        pass

            response.on_close = cleanup_zip

            log_operation(
                action="FOLDER_DOWNLOAD",
                user=request.user,
                resource_type="FOLDER",
                resource_id=folder.id,
                is_public=form.is_public,
                folder_name=folder.name
            )
            logger.info(f'[Document] Folder download streaming: {folder.name}.zip ({zip_size} bytes), is_public={form.is_public}')
            return response

        except Exception as e:
            # 异常时清理临时文件
            if zip_path and os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
            logger.error(f'[Document] Folder download failed: {folder.name}, error={e}', exc_info=True)
            raise

    def _add_folder_to_zip(self, folder, zipf, path, FolderModel, FileModel, is_public, request_user=None, visited=None):
        """【P0-2修复】使用 BFS 批量查询替代递归，解决 N+1 查询问题

        修复前：每递归一层触发 2 次 DB 查询（文件 + 子文件夹），深度嵌套时指数增长
        修复后：仅 2 次批量查询（文件夹 + 文件），查询次数从 O(N) 降至 O(1)

        Args:
            folder: 根文件夹对象
            zipf: ZipFile 对象
            path: ZIP 内部路径前缀
            FolderModel: 文件夹模型类
            FileModel: 文件模型类
            is_public: 是否公共空间
            request_user: 当前用户（用于租户过滤）
            visited: 已访问文件夹 ID 集合（用于检测循环引用）
        """
        if visited is None:
            visited = set()

        # BFS 收集所有文件夹
        folder_map, folder_children, folder_paths = self._bfs_collect_folders(
            folder, path, FolderModel, is_public, request_user, visited
        )

        # 批量查询所有文件
        files_by_folder = self._batch_query_files(
            folder_map.keys(), FolderModel, FileModel, is_public, request_user
        )

        # ZIP 写入阶段
        self._write_folders_to_zip(
            folder, folder_map, folder_children, folder_paths, files_by_folder, zipf
        )

    def _bfs_collect_folders(self, folder, path, FolderModel, is_public, request_user, visited):
        """BFS 收集所有文件夹及其路径结构"""
        folder_map = {}
        folder_children = {}
        folder_paths = {}

        queue = [folder]
        visited.add(folder.id)
        root_path = path

        while queue:
            current = queue.pop(0)
            folder_map[current.id] = current

            if current.id == folder.id:
                current_zip_path = f'{path}{current.name}/'
            else:
                parent_path = folder_paths.get(current.parent_id, root_path)
                current_zip_path = f'{parent_path}{current.name}/'
            folder_paths[current.id] = current_zip_path

            children_query = FolderModel.objects.filter(parent=current)
            if request_user and not is_public:
                children_query = apply_tenant_filter(children_query, request_user)
            children = list(children_query.select_related('created_by'))

            folder_children[current.id] = []
            for child in children:
                if child.id not in visited:
                    visited.add(child.id)
                    folder_children[current.id].append(child.id)
                    queue.append(child)

        return folder_map, folder_children, folder_paths

    def _batch_query_files(self, folder_ids, FolderModel, FileModel, is_public, request_user):
        """批量查询所有文件并按 folder_id 分组"""
        files_query = FileModel.objects.filter(folder_id__in=list(folder_ids))
        if request_user and not is_public:
            files_query = apply_tenant_filter(files_query, request_user)

        files_by_folder = {}
        for file in files_query.select_related('created_by'):
            files_by_folder.setdefault(file.folder_id, []).append(file)
        return files_by_folder

    def _write_folders_to_zip(self, folder, folder_map, folder_children, folder_paths, files_by_folder, zipf):
        """将文件夹结构写入 ZIP（无 DB 查询）"""
        stack = [folder.id]
        while stack:
            folder_id = stack.pop()
            current_folder = folder_map[folder_id]
            current_path = folder_paths[folder_id]

            for file in files_by_folder.get(folder_id, []):
                # 【P2-2修复】路径安全检查，防止路径遍历攻击
                document_storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
                if not is_safe_path(document_storage_base, file.file_path):
                    logger.warning(f'[Document] Unsafe file path skipped: {file.file_path}')
                    continue
                if os.path.exists(file.file_path):
                    zipf.write(file.file_path, f'{current_path}{file.name}')
                    logger.info(f'[Document] Added file to ZIP: {current_path}{file.name}')
                else:
                    logger.warning(f'[Document] File not found: {file.file_path}')

            # 将子文件夹入栈（逆序保证顺序正确）
            for child_id in reversed(folder_children.get(folder_id, [])):
                stack.append(child_id)

    def _file_iterator(self, file_path, chunk_size=65536):
        """【P0-1修复】分块文件迭代器，用于 StreamingHttpResponse 流式传输"""
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

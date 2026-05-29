# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件夹下载视图
提供文件夹打包下载功能
"""

import os
import io
import zipfile
import logging
from django.views.generic import View
from django.http import HttpResponse
from urllib.parse import quote

from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_folder_model, get_file_model
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

        # 创建内存中的 ZIP 文件
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            self._add_folder_to_zip(folder, zipf, '', FolderModel, FileModel, form.is_public, request.user)

        zip_buffer.seek(0)

        # 创建响应
        response = HttpResponse(zip_buffer.read())
        encoded_foldername = quote(folder.name)
        response['Content-Disposition'] = f'attachment; filename="{encoded_foldername}.zip"; filename*=UTF-8\'\'{encoded_foldername}.zip'
        response['Content-Type'] = 'application/zip'
        
        log_operation(
            action="FOLDER_DOWNLOAD",
            user=request.user,
            resource_type="FOLDER",
            resource_id=folder.id,
            is_public=form.is_public,
            folder_name=folder.name
        )
        logger.info(f'[Document] Folder download successful: {folder.name}.zip, is_public={form.is_public}')
        return response

    def _add_folder_to_zip(self, folder, zipf, path, FolderModel, FileModel, is_public, request_user=None, visited=None):
        """递归将文件夹及其内容添加到 ZIP 文件"""
        # 初始化已访问集合
        if visited is None:
            visited = set()

        # 检查循环引用
        if folder.id in visited:
            logger.warning(f'[Document] 检测到循环引用，跳过文件夹: {folder.name} (id={folder.id})')
            return
        visited.add(folder.id)

        # 构建当前文件夹在 ZIP 中的路径
        current_path = f'{path}{folder.name}/'

        # 添加文件夹中的所有文件
        files_query = FileModel.objects.filter(folder=folder)
        if request_user and not is_public:
            files_query = apply_tenant_filter(files_query, request_user)
        for file in files_query:
            if os.path.exists(file.file_path):
                zipf.write(file.file_path, f'{current_path}{file.name}')
                logger.info(f'[Document] Added file to ZIP: {current_path}{file.name}')
            else:
                logger.warning(f'[Document] File not found: {file.file_path}')

        # 递归处理子文件夹
        sub_folders_query = FolderModel.objects.filter(parent=folder)
        if request_user and not is_public:
            sub_folders_query = apply_tenant_filter(sub_folders_query, request_user)
        for sub_folder in sub_folders_query:
            self._add_folder_to_zip(sub_folder, zipf, current_path, FolderModel, FileModel, is_public, request_user, visited)

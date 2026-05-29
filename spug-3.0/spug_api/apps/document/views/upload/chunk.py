# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
分片上传视图
处理文件分片上传
【P2优化】添加_SUCCESS_标记文件和Redis缓存支持
"""

import os
import logging
from django.views.generic import View
from django.conf import settings

from libs import json_response, auth
from apps.document.constants import DEFAULT_MAX_FILE_SIZE
from .validators import (
    ChunkUploadValidator, FolderValidator,
    TransferRecordValidator, ChunkStorageManager
)
from apps.document.libs.chunk_cache import (
    get_chunk_cache_manager, get_success_marker_manager
)

logger = logging.getLogger(__name__)


def _get_max_file_size():
    """延迟获取配置，避免模块导入时访问 settings"""
    return getattr(settings, 'MAX_DOCUMENT_FILE_SIZE', DEFAULT_MAX_FILE_SIZE)


class FileChunkUploadView(View):
    """文件分片上传"""

    @auth('document.document.upload')
    def post(self, request):
        """处理文件分片上传"""

        # 1. 验证请求参数
        params, error = ChunkUploadValidator.validate_request_params(request)
        if error:
            return json_response(error=error)

        # 2. 验证文件哈希
        is_valid, error = ChunkUploadValidator.validate_file_hash(params['file_hash'])
        if not is_valid:
            return json_response(error=error)

        # 3. 验证文件
        is_valid, error = ChunkUploadValidator.validate_file(
            params['file_name'], params['file_size'], _get_max_file_size()
        )
        if not is_valid:
            return json_response(error=error)

        # 4. 验证文件夹
        folder, error = FolderValidator.validate_folder(
            params['folder_id'], params['is_public'], request.user
        )
        if error:
            return json_response(error=error)

        # 5. 获取分片文件
        chunk_file = request.FILES.get('file')
        if not chunk_file:
            return json_response(error='未接收到文件分片')

        # 6. 【P1-1修复】校验传输记录
        is_valid, error = TransferRecordValidator.validate_transfer_record(
            params['file_hash'], params['file_size'], params['total_chunks'],
            request.user, params['is_public']
        )
        if not is_valid:
            return json_response(error=error)

        # 7. 获取并验证分片目录
        chunk_dir, error = ChunkStorageManager.get_and_validate_chunk_dir(
            params['file_hash'], params['is_public'], request.user
        )
        if error:
            return json_response(error=error)

        # 8. 保存分片文件
        chunk_path, error = ChunkStorageManager.save_chunk_file(
            chunk_file, chunk_dir, params['chunk_index']
        )
        if error:
            return json_response(error=error)

        # 【P2优化】更新Redis缓存
        try:
            cache_manager = get_chunk_cache_manager(
                params['file_hash'], request.user.id, params['is_public']
            )
            cache_manager.update_cache_after_upload(
                params['chunk_index'], params['total_chunks']
            )
        except Exception as e:
            logger.warning(f'[ChunkUpload] 更新缓存失败: {e}')

        # 【P2优化】如果是最后一个分片，生成_SUCCESS_标记文件
        if params['chunk_index'] == params['total_chunks'] - 1:
            try:
                marker_manager = get_success_marker_manager(chunk_dir)
                marker_manager.create(params['total_chunks'], params['file_hash'])
            except Exception as e:
                logger.warning(f'[ChunkUpload] 创建标记文件失败: {e}')

        return json_response(data={
            'chunk_index': params['chunk_index'],
            'status': 'uploaded',
            'chunk_path': chunk_path
        })

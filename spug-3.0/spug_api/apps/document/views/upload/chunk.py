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

from libs import json_response
from apps.document.constants import DEFAULT_MAX_FILE_SIZE
from apps.document.libs.document_auth import document_auth
from apps.document.services.system_scope_validators import validate_upload_target_scope
from .validators import (
    ChunkUploadValidator, FolderValidator,
    TransferRecordValidator, TransferOwnershipValidator, ChunkStorageManager
)
from apps.document.libs.chunk_cache import (
    get_chunk_cache_manager, get_success_marker_manager
)

logger = logging.getLogger(__name__)


def _get_max_file_size():
    """延迟获取配置，避免模块导入时访问 settings"""
    return getattr(settings, 'MAX_DOCUMENT_FILE_SIZE', DEFAULT_MAX_FILE_SIZE)


def _parse_transfer_id(request):
    """解析并校验 transfer_id 参数

    【H-3加强】客户端传了 transfer_id 但格式非法（如 'abc'）时直接拒绝，
    避免降级到 legacy chunk 目录（与已迁移用户的隔离状态不一致）

    Returns:
        tuple: (transfer_id 或 None, 错误消息或 None)
    """
    raw_transfer_id = request.POST.get('transfer_id')
    if raw_transfer_id in (None, ''):
        return None, None
    try:
        return int(raw_transfer_id), None
    except (ValueError, TypeError):
        logger.warning(
            f'[ChunkUpload] 非法 transfer_id: raw={raw_transfer_id!r}, user={request.user.id}'
        )
        return None, '非法的 transfer_id 格式'


def _validate_chunk_size(request, chunk_path, chunk_index):
    """校验分片大小，检测传输损坏

    Returns:
        str|None: 错误消息或 None
    """
    request_chunk_size = request.POST.get('chunk_size')
    if not request_chunk_size or not chunk_path:
        return None
    try:
        actual_size = os.path.getsize(chunk_path)
        expected_size = int(request_chunk_size)
        if actual_size != expected_size:
            try:
                os.remove(chunk_path)
            except OSError:
                pass
            logger.error(
                f'[ChunkUpload] 分片大小校验失败: expected={expected_size}, '
                f'actual={actual_size}, chunk={chunk_index}'
            )
            return '分片校验失败：大小不匹配'
    except (ValueError, TypeError):
        pass  # chunk_size 参数无效，跳过校验
    return None


class FileChunkUploadView(View):
    """文件分片上传"""

    @document_auth('upload')
    def post(self, request):
        """处理文件分片上传"""

        # 1. 验证请求参数
        params, error = ChunkUploadValidator.validate_request_params(request)
        if error:
            return json_response(error=error)

        ok, scope_err = validate_upload_target_scope(
            request.POST.get('system_folder'),
            params['is_public'],
            params['folder_id'],
        )
        if not ok:
            return json_response(error=scope_err)

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
            request.user, params['is_public'], system_folder=params.get('system_folder')
        )
        if not is_valid:
            return json_response(error=error)

        # 7. 获取并验证分片目录
        # 【路径隔离】提取 transfer_id 用于分片目录隔离
        transfer_id, error = _parse_transfer_id(request)
        if error:
            return json_response(error=error)

        # 【H-3修复】使用 transfer_id 前必须先校验归属，防止 IDOR
        is_valid, error = TransferOwnershipValidator.validate(
            transfer_id, params['file_hash'], params['is_public'], request.user,
            system_folder=params.get('system_folder'),
        )
        if not is_valid:
            return json_response(error=error)

        chunk_dir, error = ChunkStorageManager.get_and_validate_chunk_dir(
            params['file_hash'],
            params['is_public'],
            request.user,
            transfer_id=transfer_id,
            system_folder=params.get('system_folder'),
        )
        if error:
            return json_response(error=error)

        # 8. 保存分片文件
        chunk_path, error = ChunkStorageManager.save_chunk_file(
            chunk_file, chunk_dir, params['chunk_index']
        )
        if error:
            return json_response(error=error)

        # 9. 校验分片大小
        error = _validate_chunk_size(request, chunk_path, params['chunk_index'])
        if error:
            return json_response(error=error)

        # 10. 更新Redis缓存 + 最后一个分片生成标记文件
        self._update_cache_and_marker(params, chunk_dir, transfer_id, request.user.id)

        return json_response(data={
            'chunk_index': params['chunk_index'],
            'status': 'uploaded',
            'chunk_path': chunk_path
        })

    @staticmethod
    def _update_cache_and_marker(params, chunk_dir, transfer_id, user_id):
        """更新Redis缓存，最后一个分片时生成_SUCCESS_标记文件"""
        # 【P2优化+优化4】更新Redis缓存（包含 transfer_id 隔离）
        try:
            cache_manager = get_chunk_cache_manager(
                params['file_hash'], user_id, params['is_public'],
                transfer_id=transfer_id
            )
            cache_manager.update_cache_after_upload(
                params['chunk_index'], params['total_chunks']
            )
        except Exception as e:
            logger.warning(f'[ChunkUpload] 更新缓存失败: {e}')

        # 【P2修复】如果是最后一个编号分片，验证全部分片存在后再生成_SUCCESS_标记
        if params['chunk_index'] == params['total_chunks'] - 1:
            try:
                # 【P2修复】验证所有分片文件确实存在，防止乱序上传时标记提前创建
                missing_chunks = []
                for i in range(params['total_chunks']):
                    chunk_file = os.path.join(chunk_dir, f'chunk_{i}')
                    if not os.path.exists(chunk_file):
                        missing_chunks.append(i)

                if missing_chunks:
                    logger.warning(
                        f'[ChunkUpload] Last chunk arrived but {len(missing_chunks)} chunks missing: '
                        f'{missing_chunks[:10]}..., deferring _SUCCESS_ marker creation'
                    )
                else:
                    marker_manager = get_success_marker_manager(chunk_dir)
                    marker_manager.create(params['total_chunks'], params['file_hash'])
            except Exception as e:
                logger.warning(f'[ChunkUpload] 创建标记文件失败: {e}')

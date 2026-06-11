# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
断点续传检查视图
检查已上传分片接口（断点续传）
【P2优化】使用_SUCCESS_标记文件和Redis缓存提升性能
"""
import os
import logging
from django.views.generic import View

from libs import json_response, auth, JsonParser, Argument
from apps.document.libs.document_utils import get_chunk_dir_path
from apps.document.constants import TransferStatus
from apps.document.views.upload.chunk_checker import (
    ChunkScanner, MergeStatusChecker, ResumeUploadValidator
)
from apps.document.libs.chunk_cache import (
    get_chunk_cache_manager, get_success_marker_manager
)
from .resume_strategies import (
    SuccessMarkerStrategy, RedisCacheStrategy, FilesystemScanStrategy,
    ChunkStrategyContext
)
from .error_code_mapper import ErrorCodeMapper

logger = logging.getLogger(__name__)


class CheckUploadedChunksView(View):
    """检查已上传分片接口（断点续传）"""

    # 类常量：响应模板（统一响应结构）
    BASE_RESPONSE_TEMPLATE = {
        'exists': False,
        'uploaded_chunks': [],
        'count': 0,
        'total_chunks': 0,
        'all_chunks_ready': False,
        'can_merge_directly': False,
        'error_code': None,
        'missing_chunks': [],
        'message': '',
        'merge_status': None,
        'merge_task_id': None,
        'task_id': None,
    }

    @auth('document.document.view')
    def post(self, request):
        """检查已上传分片 - 优化版"""
        # 1. 参数解析
        form, error = self._parse_request(request)
        if error:
            return json_response(error=error)

        # 2. 校验传输记录
        is_valid, error_response = self._validate_transfer(form, request.user)
        if not is_valid:
            return json_response(error_response)

        # 3. 获取分片目录
        chunk_dir = self._get_chunk_dir(form, request.user)
        if not chunk_dir:
            return self._build_not_found_response(form.total_chunks or 0)

        # 4. 获取已上传分片（策略模式）
        uploaded_chunks, all_ready, strategy_name = self._get_uploaded_chunks(
            chunk_dir, form, request.user
        )
        logger.debug(f'[Resume] Strategy hit: {strategy_name}')

        # 5. 检查合并状态
        merge_info = MergeStatusChecker.check_merge_status(chunk_dir, form.file_hash)
        can_merge = self._check_can_merge(form, request.user, all_ready)
        error_code = self._extract_error_code(form, request.user)

        # 6. 构建响应
        return self._build_success_response(
            uploaded_chunks, form.total_chunks or 0, all_ready,
            can_merge, error_code, merge_info
        )

    def _parse_request(self, request):
        """解析请求参数"""
        return JsonParser(
            Argument('file_hash', type=str, required=True, help='文件哈希(MD5)'),
            Argument('file_size', type=int, required=False, help='文件大小'),
            Argument('total_chunks', type=int, required=False, help='总分片数'),
            Argument('is_public', type=bool, required=False, default=False),
            Argument('transfer_id', type=int, required=False, help='传输记录ID'),
        ).parse(request.body)

    def _validate_transfer(self, form, user):
        """校验传输记录"""
        return ResumeUploadValidator.validate_against_transfer(
            form.file_hash, form.file_size, form.total_chunks,
            user, form.is_public
        )

    def _get_chunk_dir(self, form, user):
        """
        获取分片目录

        【P1修复-三轮】明确语义（"读哪里写哪里"原则）：

        1. 没传 transfer_id → 旧路径（老客户端兼容）
        2. 传了 transfer_id 但归属校验失败 → return None（前端从头传）
        3. 传了 transfer_id 且归属通过 + 新物理目录存在 → 用新目录
        4. 传了 transfer_id 且归属通过 + 新物理目录不存在 → return None（前端从头传）
           原因：绝对**不能**回退到旧路径，否则会"读旧分片、写新分片"，分片被拆成两份。
           因为 chunk.py 上传分片时严格按 transfer_id 写新目录，merge 时也只读新目录。
        """
        try:
            transfer_id = getattr(form, 'transfer_id', None)
            if transfer_id:
                # 【H-3修复】使用 transfer_id 前必须先校验归属，防止 IDOR
                from apps.document.views.upload.validators import TransferOwnershipValidator
                is_valid, error_msg = TransferOwnershipValidator.validate(
                    transfer_id, form.file_hash, form.is_public, user
                )
                if not is_valid:
                    logger.warning(f'[Document][Resume] transfer_id ownership check failed: {error_msg}')
                    return None
                chunk_dir = get_chunk_dir_path(form.file_hash, form.is_public, user, transfer_id=transfer_id)
                if os.path.exists(chunk_dir):
                    return chunk_dir
                # 【P1修复-三轮】新目录不存在时**不**回退 legacy。
                # 旧路径上残留的分片属于"上一个 transfer（如果存在）"，不是当前 transfer 的；
                # 让前端从头传（写入新目录）才能保持分片在同一目录。
                logger.info(
                    f'[Document][Resume] transfer_id={transfer_id} 新目录不存在，前端需要从头传'
                )
                return None
            # 没传 transfer_id → 走老逻辑（兼容老客户端）
            chunk_dir = get_chunk_dir_path(form.file_hash, form.is_public, user)
            return chunk_dir if os.path.exists(chunk_dir) else None
        except Exception as e:
            logger.error(f'[Document][Resume] Get chunk dir failed: {e}')
            return None

    def _build_not_found_response(self, total_chunks: int):
        """构建分片目录不存在响应"""
        response = self.BASE_RESPONSE_TEMPLATE.copy()
        response.update({
            'exists': False,
            'total_chunks': total_chunks,
            'message': '未找到分片目录'
        })
        return json_response(response)

    def _get_uploaded_chunks(self, chunk_dir, form, user):
        """
        获取已上传分片列表（策略模式）
        优先级：_SUCCESS_标记 > Redis缓存 > 文件扫描
        """
        context = ChunkStrategyContext()
        context.add_strategy(SuccessMarkerStrategy(get_success_marker_manager))
        context.add_strategy(RedisCacheStrategy(get_chunk_cache_manager))
        context.add_strategy(FilesystemScanStrategy(
            ChunkScanner, get_chunk_cache_manager
        ))

        # 【优化4】传递 transfer_id 用于缓存隔离
        transfer_id = getattr(form, 'transfer_id', None)

        return context.execute(
            chunk_dir, form.file_hash, user.id,
            form.is_public, form.total_chunks or 0,
            transfer_id=transfer_id
        )

    def _check_can_merge(self, form, user, all_ready):
        """检查是否可以直接合并"""
        if not (all_ready and form.transfer_id):
            return False

        try:
            from apps.document.models import DocumentTransfer
            from apps.document.views.upload.validators import TransferOwnershipValidator
            is_valid, _ = TransferOwnershipValidator.validate(
                form.transfer_id, form.file_hash, form.is_public, user
            )
            if not is_valid:
                return False

            transfer = DocumentTransfer.objects.get(id=form.transfer_id)

            return transfer.status in [
                TransferStatus.MERGING.value,
                TransferStatus.FAILED.value
            ]
        except DocumentTransfer.DoesNotExist:
            return False
        except Exception as e:
            logger.warning(f'[Resume] 检查合并状态失败: {e}')
            return False

    def _extract_error_code(self, form, user):
        """提取错误码（使用配置化映射表）"""
        if not form.transfer_id:
            return None

        try:
            from apps.document.models import DocumentTransfer
            from apps.document.views.upload.validators import TransferOwnershipValidator
            is_valid, _ = TransferOwnershipValidator.validate(
                form.transfer_id, form.file_hash, form.is_public, user
            )
            if not is_valid:
                return None

            transfer = DocumentTransfer.objects.get(id=form.transfer_id)

            if transfer.status != TransferStatus.FAILED.value:
                return None

            return ErrorCodeMapper.map(transfer.error_message)

        except DocumentTransfer.DoesNotExist:
            return None
        except Exception as e:
            logger.warning(f'[Resume] 获取错误码失败: {e}')
            return None

    def _build_success_response(self, uploaded_chunks, total, all_ready,
                                 can_merge, error_code, merge_info):
        """构建成功响应"""
        response = self.BASE_RESPONSE_TEMPLATE.copy()
        response.update({
            'exists': True,
            'uploaded_chunks': uploaded_chunks,
            'count': len(uploaded_chunks),
            'total_chunks': total,
            'all_chunks_ready': all_ready,
            'can_merge_directly': can_merge,
            'error_code': error_code,
            'missing_chunks': [
                i for i in range(total)
                if i not in uploaded_chunks
            ],
            'message': f'找到 {len(uploaded_chunks)} 个已上传分片',
        })
        response.update(merge_info)
        return json_response(response)

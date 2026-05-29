# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
分片清理层 - 统一处理分片文件清理
"""
import os
import logging
from typing import Dict, List
from django.conf import settings

logger = logging.getLogger(__name__)


class ChunkCleanupService:
    """分片清理服务 - 统一处理分片文件清理"""

    @classmethod
    def cleanup_safe(cls, transfer) -> Dict:
        """
        安全清理分片文件

        Args:
            transfer: DocumentTransfer对象

        Returns:
            Dict: 清理结果 {'id': int, 'status': str, 'error': str(optional)}
        """
        # 无需清理的情况
        if not (transfer.file_hash and transfer.total_chunks > 0):
            return {'id': transfer.id, 'status': 'skipped'}

        try:
            cls._cleanup_transfer_chunks(transfer)
            return {'id': transfer.id, 'status': 'cleaned'}
        except Exception as e:
            logger.warning(f'[Celery] Chunk cleanup failed for {transfer.id}: {e}')
            return {'id': transfer.id, 'status': 'failed', 'error': str(e)}

    @classmethod
    def _cleanup_transfer_chunks(cls, transfer):
        """
        清理传输记录的分片文件

        优先使用项目中已有的 ChunkCleanupManager
        """
        try:
            from apps.document.views.transfer.transfer_manager import ChunkCleanupManager
            ChunkCleanupManager.cleanup_transfer_chunks(transfer)
        except ImportError:
            # 降级到本地实现
            cls._local_cleanup_transfer_chunks(transfer)

    @classmethod
    def _local_cleanup_transfer_chunks(cls, transfer):
        """本地分片清理实现（降级方案）"""
        import shutil
        from apps.document.libs.document_utils import get_chunk_dir_path

        class TempUser:
            def __init__(self, user_id, tenant_id):
                self.id = user_id
                self.tenant_id = tenant_id

        temp_user = TempUser(
            transfer.user_id or 'anonymous',
            transfer.tenant_id or getattr(settings, 'DEFAULT_TENANT_ID', 'default')
        )
        chunk_dir = get_chunk_dir_path(transfer.file_hash, transfer.is_public, temp_user)

        chunk_base_dir = os.path.join(settings.BASE_DIR, 'storage', 'document_chunks')
        if chunk_dir.startswith(chunk_base_dir) and os.path.exists(chunk_dir):
            shutil.rmtree(chunk_dir, ignore_errors=True)
            logger.info(f'[Celery] Cleaned up chunks: {chunk_dir}')

    @classmethod
    def count_cleaned(cls, results: List[Dict]) -> int:
        """统计成功清理的数量"""
        return len([r for r in results if r.get('status') == 'cleaned'])

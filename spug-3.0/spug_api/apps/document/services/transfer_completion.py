"""
传输完成统一入口服务。

所有将 transfer.status 设为 COMPLETED 的路径必须经过 TransferCompletionService.complete()，
确保状态转换、file_path 完整性、字段一致性。

调用方：
  - Celery 合并任务 (merge.py TransferStatusUpdater)
  - 普通上传 (file_upload_service.py FileUploadService)
  - HTTP 视图 (status.py TransferCompleteView / TransferStatusUpdateView)
"""
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


class TransferCompletionService:
    """统一的传输完成入口"""

    @staticmethod
    def complete(transfer, file_path=None, file_size=None, source='unknown'):
        """
        将传输记录标记为 COMPLETED。

        参数:
            transfer: DocumentTransfer 实例（调用方负责获取和权限校验）
            file_path: 文件路径（Celery / FileUploadService 传入；
                       HTTP 视图不传，使用 transfer.file_path）
            file_size: 文件大小（可选，默认用 transfer.file_size）
            source: 调用来源标识，用于日志追踪

        返回:
            (success: bool, error: str | None)
        """
        from ..constants import TransferStatus, is_valid_status_transition

        # 1. 幂等：已经是 COMPLETED
        if transfer.status == TransferStatus.COMPLETED.value:
            logger.debug(f'[TransferCompletion] transfer {transfer.id} 已是 COMPLETED (source={source})')
            return True, None

        # 2. 状态转换检查
        current_enum = next((s for s in TransferStatus if s.value == transfer.status), None)
        if not current_enum:
            return False, f'无效的当前状态: {transfer.status}'
        if not is_valid_status_transition(current_enum, TransferStatus.COMPLETED):
            return False, f'无效的状态转换: {transfer.status} -> {TransferStatus.COMPLETED.value}'

        # 3. file_path 必须有值（来自参数或已设置的 transfer.file_path）
        effective_file_path = file_path or transfer.file_path
        if not effective_file_path:
            # 【兜底修复】竞态场景：同 file_hash 的另一个传输已完成但当前传输未同步 file_path
            # 尝试从同 hash 的 COMPLETED 记录中获取 file_path
            if transfer.file_hash:
                from apps.document.models import DocumentTransfer
                sibling = DocumentTransfer.objects.filter(
                    file_hash=transfer.file_hash,
                    status=TransferStatus.COMPLETED.value,
                ).exclude(id=transfer.id).exclude(file_path='').exclude(file_path__isnull=True).first()
                if sibling and sibling.file_path:
                    effective_file_path = sibling.file_path
                    logger.info(
                        f'[TransferCompletion] transfer {transfer.id} file_path 为空，'
                        f'从同 hash 记录 {sibling.id} 获取 file_path={effective_file_path[:50]}'
                    )
            if not effective_file_path:
                logger.warning(
                    f'[TransferCompletion] transfer {transfer.id} file_path 为空 '
                    f'(source={source}, status={transfer.status})'
                )
                return False, '文件上传未成功（文件记录未创建）'

        # 4. 统一设置所有完成字段
        transfer.status = TransferStatus.COMPLETED.value
        # file_path 优先用参数，其次用 sibling 查到的 effective_file_path
        transfer.file_path = file_path or effective_file_path
        transfer.progress = 100
        transfer.transferred_size = file_size or transfer.file_size
        transfer.uploaded_chunks = transfer.total_chunks
        transfer.completed_at = timezone.now()
        transfer.save()

        logger.info(f'[TransferCompletion] transfer {transfer.id} completed (source={source})')
        return True, None

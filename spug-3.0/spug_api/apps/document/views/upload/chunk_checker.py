"""
分片检查模块
处理断点续传相关的分片扫描和状态检查
"""

import os
import json
import glob
import logging
from django.conf import settings

from apps.document.constants import TransferStatus
from apps.document.libs.document_utils import get_merge_task_storage_base_path
from .validators import HashValidator

logger = logging.getLogger(__name__)

# 【P2-2修复】合并任务目录路径常量
MERGE_TASKS_DIR_NAME = 'document_merge_tasks'
MERGE_TASKS_BASE_PATH_PARTS = ('storage', MERGE_TASKS_DIR_NAME)


class ChunkScanner:
    """分片扫描器。

    扫描分片上传目录，识别已上传的分片文件，用于断点续传功能。
    """

    @staticmethod
    def scan_uploaded_chunks(chunk_dir):
        """扫描已上传的分片文件。

        遍历分片目录，识别所有以".part"结尾的分片文件，返回已上传的分片索引列表。

        Args:
            chunk_dir: 分片存储目录路径

        Returns:
            tuple: (已上传分片索引列表或None, 错误消息或None)
        """
        uploaded_chunks = []

        try:
            for filename in os.listdir(chunk_dir):
                if filename.endswith('.part'):
                    try:
                        chunk_index = int(filename.replace('.part', ''))
                        uploaded_chunks.append(chunk_index)
                    except (ValueError, IndexError):
                        continue
        except OSError as e:
            logger.error(f'[Document] Error scanning chunk directory: {e}')
            return None, '扫描分片目录失败'

        uploaded_chunks.sort()
        logger.info(f'[Document] Found uploaded chunks: {len(uploaded_chunks)}')
        return uploaded_chunks, None


class MergeStatusChecker:
    """合并状态检查器。

    检查文件合并任务的当前状态，用于断点续传时判断是否需要重新触发合并。
    """

    @staticmethod
    def check_merge_status(chunk_dir, file_hash, system_folder=None):
        """检查文件合并状态。

        读取分片目录中的合并状态文件，获取当前合并任务的进度信息。

        Args:
            chunk_dir: 分片存储目录路径
            file_hash: 文件哈希值

        Returns:
            dict: 包含以下键的字典：
                - merge_status: 合并状态字符串（'merging'/'completed'/'failed'等）或None
                - merge_task_id: 合并任务ID或None
                - task_id: Celery任务ID或None
        """
        result = {
            'merge_status': None,
            'merge_task_id': None,
            'task_id': None
        }

        status_file = os.path.join(chunk_dir, '.merge_status')

        if not os.path.exists(status_file):
            return result

        try:
            with open(status_file, 'r') as f:
                result['merge_status'] = f.read().strip()

            if result['merge_status'].upper() == TransferStatus.MERGING.value:
                task_info = MergeStatusChecker._get_task_info(
                    file_hash,
                    system_folder=system_folder,
                )
                result.update(task_info)

        except (IOError, OSError) as e:
            logger.warning(f'[Document][ChunkChecker] Failed to read status file: {e}')

        return result

    @staticmethod
    def _get_task_info(file_hash, system_folder=None):
        """获取合并任务信息。

        根据文件哈希查找对应的任务文件，提取Celery任务ID。

        Args:
            file_hash: 文件哈希值

        Returns:
            dict: 包含merge_task_id和task_id的字典
        """
        result = {'merge_task_id': None, 'task_id': None}

        merge_task_dir = get_merge_task_storage_base_path(system_folder)
        if not os.path.exists(merge_task_dir):
            return result

        task_files = glob.glob(os.path.join(merge_task_dir, f"{file_hash}_*.task"))
        if not task_files:
            return result

        latest_task_file = max(task_files, key=os.path.getmtime)
        result['merge_task_id'] = os.path.basename(latest_task_file).replace('.task', '')

        # 读取任务文件获取 Celery task_id
        try:
            with open(latest_task_file, 'r') as tf:
                task_data = json.loads(tf.read())
                result['task_id'] = task_data.get('task_id')
        except (IOError, OSError, json.JSONDecodeError) as e:
            logger.warning(f'[Document][ChunkChecker] Failed to read task file: {e}')

        return result


class ResumeUploadValidator:
    """断点续传验证器。

    验证断点续传请求的参数，确保文件哈希、大小等信息符合要求。
    """

    @staticmethod
    def validate_request(request):
        """验证断点续传请求参数。

        Args:
            request: HTTP请求对象

        Returns:
            tuple: (参数字典或None, 错误消息或None)
        """
        from libs import JsonParser, Argument

        form, error = JsonParser(
            Argument('file_hash', type=str, required=True, help='文件哈希(MD5)'),
            Argument('file_size', type=int, required=False, help='文件大小'),
            Argument('total_chunks', type=int, required=False, help='总分片数'),
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.body)

        if error:
            return None, error

        # 验证哈希格式
        if not HashValidator.validate(form.file_hash):
            return None, '非法的文件哈希值'

        return {
            'file_hash': form.file_hash,
            'file_size': form.file_size,
            'total_chunks': form.total_chunks,
            'is_public': form.is_public
        }, None

    @staticmethod
    def validate_against_transfer(file_hash, file_size, total_chunks, user, is_public, system_folder=None):
        """【P0-1修复】校验传输记录的文件大小和总分片数。

        用于断点续传时验证客户端提供的文件元数据是否与服务器记录一致。

        修复点：
        1. 添加排序和状态过滤，确保匹配到最新的未完成记录
        2. 异常时返回False而非True，避免掩盖问题

        Args:
            file_hash: 文件哈希值
            file_size: 文件大小（字节），可为None
            total_chunks: 总分片数，可为None
            user: 当前用户对象
            is_public: 是否为公共空间

        Returns:
            tuple: (bool是否有效, dict错误响应或None)
        """
        if file_size is None and total_chunks is None:
            return True, None

        try:
            from apps.document.models import DocumentTransfer
            from apps.document.constants import TransferStatus
            from apps.document.services.system_folder_service import normalize_system_folder_code

            normalized_sf = normalize_system_folder_code(system_folder) if system_folder else ''

            # 【P0-1修复】按创建时间倒序，只匹配未完成的记录
            transfer = DocumentTransfer.objects.filter(
                file_hash=file_hash,
                user=user,
                is_public=is_public,
                system_folder=normalized_sf,
                status__in=[
                    TransferStatus.PENDING.value,
                    TransferStatus.UPLOADING.value,
                    TransferStatus.PAUSED.value
                ]
            ).order_by('-created_at').first()

            if not transfer:
                return True, None

            if file_size is not None and transfer.file_size != file_size:
                logger.warning(f'[Document][ChunkChecker] File size mismatch: transfer={transfer.file_size}, request={file_size}')
                return False, {
                    'exists': False,
                    'uploaded_chunks': [],
                    'error': '文件大小已修改，请重新上传'
                }

            if total_chunks is not None and transfer.total_chunks != total_chunks:
                logger.warning(f'[Document][ChunkChecker] Chunk count mismatch: transfer={transfer.total_chunks}, request={total_chunks}')
                return False, {
                    'exists': False,
                    'uploaded_chunks': [],
                    'error': '分片总数已修改，请重新上传'
                }

            return True, None

        except Exception as e:
            logger.error(f'[Document][ChunkChecker] Failed to validate transfer record: {e}', exc_info=True)
            # 【P0-1修复】异常时返回False，不能掩盖问题
            # 【P2-4修复】返回通用错误消息，避免信息泄露
            return False, {
                'exists': False,
                'uploaded_chunks': [],
                'error': '验证传输记录失败，请稍后重试'
            }

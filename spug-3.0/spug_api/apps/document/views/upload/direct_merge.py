# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
直接合并视图
支持合并失败后直接触发合并（无需重新上传分片）

【P0-Day1实现】核心特性：
1. 幂等性：同一transfer_id多次调用只执行一次合并
2. 并发安全：select_for_update + 事务防止竞态条件
3. 分片验证：确保所有分片存在后才提交合并任务
"""

import os
import time
import json
import logging
from django.views.generic import View
from django.db import transaction
from django.conf import settings

from libs import json_response, auth, JsonParser, Argument
from apps.document.libs.document_utils import get_chunk_dir_path
from apps.document.constants import TransferStatus
from apps.document.views.base import validate_file_name
from apps.document.views.upload.validators import HashValidator, FolderValidator

logger = logging.getLogger(__name__)

# 【P2-2修复】合并任务目录路径常量
MERGE_TASKS_DIR_NAME = 'document_merge_tasks'
MERGE_TASKS_BASE_PATH_PARTS = ('storage', MERGE_TASKS_DIR_NAME)


class DirectMergeView(View):
    """直接触发合并视图
    
    用于分片都已上传但合并失败的情况，支持直接重新触发合并
    无需重新上传所有分片
    """

    @auth('document.document.upload')
    def post(self, request):
        """处理直接合并请求
        
        【P0-Day1关键修复】
        1. 使用select_for_update防止并发重复提交
        2. 幂等性检查：已合并/合并中的任务直接返回
        3. 事务包裹确保状态一致性
        """
        # 1. 解析并验证参数
        form, error = JsonParser(
            Argument('transfer_id', type=int, required=True, help='传输记录ID'),
            Argument('folder_id', type=int, required=True, help='文件夹ID'),
            Argument('file_name', type=str, required=True, help='文件名'),
            Argument('file_hash', type=str, required=True, help='文件哈希'),
            Argument('total_chunks', type=int, required=True, help='总分片数'),
            Argument('is_public', type=bool, default=False, help='是否公共空间'),
            Argument('file_size', type=int, required=False, help='文件大小'),
        ).parse(request.body)
        
        if error:
            return json_response(error=error)

        # 2. 验证文件名
        if not validate_file_name(form.file_name):
            return json_response(error='文件名包含非法字符')

        # 3. 验证哈希
        if not HashValidator.validate(form.file_hash):
            return json_response(error='非法的文件哈希值')

        try:
            from apps.document.models import DocumentTransfer
            from apps.document.tasks import merge_file_chunks
            from apps.document.libs.naming_utils import generate_file_names
            from apps.document.libs.document_utils import get_file_model, get_document_absolute_path

            # 【P0-Day1核心修复】使用事务+悲观锁防止并发竞态条件
            with transaction.atomic():
                # 3.1 验证传输记录（加锁）
                try:
                    transfer = DocumentTransfer.objects.select_for_update().get(
                        id=form.transfer_id,
                        user=request.user
                    )
                except DocumentTransfer.DoesNotExist:
                    return json_response(error='传输记录不存在')

                # 【P0-Day1核心修复】幂等性检查：如果已经在合并中，直接返回当前任务
                if transfer.status == TransferStatus.MERGING.value and transfer.celery_task_id:
                    logger.info(f'[DirectMerge] 幂等性命中: transfer={form.transfer_id} 已在合并中')
                    return json_response(data={
                        'task_id': transfer.celery_task_id,
                        'status': 'merging',
                        'message': '合并任务进行中',
                        'is_idempotent': True  # 标记为幂等响应
                    })

                # 【P0-Day1核心修复】如果已完成，返回完成状态
                if transfer.status == TransferStatus.COMPLETED.value:
                    return json_response(data={
                        'status': 'completed',
                        'message': '文件已合并完成',
                        'file_id': transfer.file_id,
                        'is_idempotent': True
                    })

                # 3.2 验证分片目录和分片完整性
                chunk_dir, error = self._validate_chunks(
                    form.file_hash, form.is_public, request.user, form.total_chunks
                )
                if error:
                    return json_response(error=error)

                # 3.3 验证文件夹
                folder, error = FolderValidator.validate_folder(
                    form.folder_id, form.is_public, request.user
                )
                if error:
                    return json_response(error=error)

                # 3.4 构建文件存储路径
                FileModel = get_file_model(is_public=form.is_public)
                names = generate_file_names(FileModel, form.file_name, folder, request.user)
                
                upload_dir = get_document_absolute_path(
                    is_public=form.is_public,
                    user_id=request.user.id,
                    folder_id=form.folder_id
                )
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, names['physical_name'])

                # 3.5 创建合并状态文件
                status_file = os.path.join(chunk_dir, '.merge_status')
                with open(status_file, 'w') as f:
                    f.write(TransferStatus.MERGING.value.lower())

                # 3.6 提交Celery合并任务
                timestamp = int(time.time())
                merge_task_id = f"{form.file_hash}_{timestamp}"
                merge_task_file = os.path.join(
                    settings.BASE_DIR, *MERGE_TASKS_BASE_PATH_PARTS,
                    f"{merge_task_id}.task"
                )
                os.makedirs(os.path.dirname(merge_task_file), exist_ok=True)

                job_data = {
                    'file_name': form.file_name,
                    'file_hash': form.file_hash,
                    'file_path': file_path,
                    'physical_name': names['physical_name'],
                    'logical_name': names['logical_name'],
                    'display_name': names['display_name'],
                    'chunk_dir': chunk_dir,
                    'file_size': form.file_size or transfer.file_size,
                    'total_chunks': form.total_chunks,
                    'folder_id': form.folder_id,
                    'is_public': form.is_public,
                    'user_id': request.user.id,
                    'username': request.user.username,
                    'tenant_id': getattr(request.user, 'tenant_id', None),
                    'transfer_id': form.transfer_id,
                    'timestamp': timestamp,
                    'start_time': time.time()
                }

                task = merge_file_chunks.delay(job_data)

                # 3.7 更新传输记录状态
                transfer.status = TransferStatus.MERGING.value
                transfer.celery_task_id = task.id
                transfer.save()

                # 3.8 写入任务文件
                try:
                    with open(merge_task_file, 'w') as f:
                        f.write(json.dumps({
                            'status': TransferStatus.PENDING.value.lower(),
                            'file_name': form.file_name,
                            'file_hash': form.file_hash,
                            'user': request.user.username,
                            'is_public': form.is_public,
                            'start_time': time.time(),
                            'task_id': task.id
                        }))
                except Exception as file_error:
                    logger.error(f'[DirectMerge] Write task file failed: {file_error}')

            # 事务结束，返回成功
            logger.info(f'[DirectMerge] 合并任务已提交: transfer={form.transfer_id}, task={task.id}')
            
            return json_response(data={
                'task_id': task.id,
                'merge_task_id': merge_task_id,
                'status': 'merging',
                'message': '合并任务已提交',
                'is_idempotent': False
            })

        except Exception as e:
            logger.error(f'[DirectMerge] 直接合并失败: {e}', exc_info=True)
            return json_response(error='提交合并任务失败，请稍后重试')

    def _validate_chunks(self, file_hash, is_public, user, total_chunks):
        """验证分片目录和分片完整性
        
        Returns:
            tuple: (chunk_dir或None, error_message或None)
        """
        try:
            chunk_dir = get_chunk_dir_path(file_hash, is_public, user)
        except ValueError:
            return None, '非法的文件哈希值'

        if not os.path.exists(chunk_dir):
            return None, '分片目录不存在，可能已被清理，请重新上传'

        # 检查所有分片是否存在
        missing_chunks = []
        for i in range(total_chunks):
            chunk_path = os.path.join(chunk_dir, f'{i}.part')
            if not os.path.exists(chunk_path):
                missing_chunks.append(i)

        if missing_chunks:
            return None, f'分片不完整，缺少: {missing_chunks}'

        return chunk_dir, None

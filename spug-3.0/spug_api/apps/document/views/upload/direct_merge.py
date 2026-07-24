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
from uuid import uuid4
from django.views.generic import View
from django.db import transaction
from django.conf import settings

from libs import json_response, JsonParser, Argument
from apps.document.libs.document_utils import get_merge_task_file_path
from apps.document.constants import TransferStatus
from apps.document.libs.document_auth import document_auth
from apps.document.services.system_scope_validators import validate_upload_target_scope
from apps.document.views.base import validate_file_name
from apps.document.views.upload.validators import HashValidator, FolderValidator, TransferOwnershipValidator

logger = logging.getLogger(__name__)

# 【P2-2修复】合并任务目录路径常量
MERGE_TASKS_DIR_NAME = 'document_merge_tasks'
MERGE_TASKS_BASE_PATH_PARTS = ('storage', MERGE_TASKS_DIR_NAME)


class DirectMergeView(View):
    """直接触发合并视图
    
    用于分片都已上传但合并失败的情况，支持直接重新触发合并
    无需重新上传所有分片
    """

    @staticmethod
    def _parse_form(request):
        form, error = JsonParser(
            Argument('transfer_id', type=int, required=True, help='传输记录ID'),
            Argument('folder_id', type=int, required=True, help='文件夹ID'),
            Argument('file_name', type=str, required=True, help='文件名'),
            Argument('file_hash', type=str, required=True, help='文件哈希'),
            Argument('total_chunks', type=int, required=True, help='总分片数'),
            Argument('is_public', type=bool, default=False, help='是否公共空间'),
            Argument('file_size', type=int, required=False, help='文件大小'),
            Argument('system_folder', type=str, required=False, default=None),
        ).parse(request.body)
        if error:
            return None, json_response(error=error)

        ok, scope_error = validate_upload_target_scope(
            form.system_folder,
            form.is_public,
            form.folder_id,
        )
        if not ok:
            return None, json_response(error=scope_error)
        if not validate_file_name(form.file_name):
            return None, json_response(error='文件名包含非法字符')
        if not HashValidator.validate(form.file_hash):
            return None, json_response(error='非法的文件哈希值')
        return form, None

    @document_auth('upload')
    def post(self, request):
        """处理直接合并请求

        【P0-Day1关键修复】
        1. 使用select_for_update防止并发重复提交
        2. 幂等性检查：已合并/合并中的任务直接返回
        3. 事务包裹确保状态一致性
        """
        form, error_response = self._parse_form(request)
        if error_response is not None:
            return error_response

        try:
            from apps.document.models import DocumentTransfer
            from apps.document.tasks import merge_file_chunks
            from apps.document.libs.naming_utils import generate_file_names
            from apps.document.libs.document_utils import get_file_model, get_document_absolute_path

            # 【P0-Day1核心修复】使用事务+悲观锁防止并发竞态条件
            with transaction.atomic():
                # 【H-3 加强】把 TransferOwnershipValidator 移进事务,锁前再校一次
                # 单一校验源：业务规则变更只改 TransferOwnershipValidator 一处
                # TOCTOU 防御：4 维校验与加锁在同一个事务内,毫秒级窗口被覆盖
                is_valid, error = TransferOwnershipValidator.validate(
                    form.transfer_id, form.file_hash, form.is_public, request.user,
                    system_folder=form.system_folder,
                )
                if not is_valid:
                    return json_response(error=error)

                # 3.1 验证传输记录（加锁）
                # 锁内仅按 id 查：完整归属刚在校验器里过过,select_for_update 只承担并发互斥
                try:
                    transfer = DocumentTransfer.objects.select_for_update().get(
                        id=form.transfer_id
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
                        'file_path': transfer.file_path,
                        'is_idempotent': True
                    })

                # 3.2 验证分片目录和分片完整性
                chunk_dir, error = self._validate_chunks(
                    form.file_hash, form.is_public, request.user, form.total_chunks,
                    transfer_id=form.transfer_id,
                    system_folder=form.system_folder,
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
                    folder_id=form.folder_id,
                    system_folder=form.system_folder,
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
                merge_task_file = get_merge_task_file_path(
                    merge_task_id,
                    system_folder=form.system_folder,
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
                    'system_folder': form.system_folder,
                    'timestamp': timestamp,
                    'start_time': time.time()
                }

                task_id = str(uuid4())

                # 3.7 更新传输记录状态
                transfer.status = TransferStatus.MERGING.value
                transfer.celery_task_id = task_id
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
                            'system_folder': form.system_folder,
                            'start_time': time.time(),
                            'task_id': task_id
                        }))
                except Exception as file_error:
                    logger.error(f'[DirectMerge] Write task file failed: {file_error}')

                # ATOMIC_REQUESTS/atomic 提交成功后再投递，避免 worker 读取未提交状态。
                def dispatch_after_commit():
                    try:
                        merge_file_chunks.apply_async(args=[job_data], task_id=task_id)
                    except Exception as dispatch_error:
                        DocumentTransfer.objects.filter(
                            pk=transfer.pk, celery_task_id=task_id,
                        ).update(
                            status=TransferStatus.FAILED.value,
                            error_message=f'合并任务投递失败: {dispatch_error}',
                        )
                        logger.error(
                            f'[DirectMerge] Dispatch after commit failed: transfer={transfer.pk}, '
                            f'task={task_id}, error={dispatch_error}', exc_info=True,
                        )

                transaction.on_commit(dispatch_after_commit)

            # 事务结束，返回成功
            logger.info(f'[DirectMerge] 合并任务已登记: transfer={form.transfer_id}, task={task_id}')
            
            return json_response(data={
                'task_id': task_id,
                'merge_task_id': merge_task_id,
                'status': 'merging',
                'message': '合并任务已提交',
                'is_idempotent': False
            })

        except Exception as e:
            logger.error(f'[DirectMerge] 直接合并失败: {e}', exc_info=True)
            return json_response(error='提交合并任务失败，请稍后重试')

    def _validate_chunks(
        self,
        file_hash,
        is_public,
        user,
        total_chunks,
        transfer_id=None,
        system_folder=None,
    ):
        """验证分片目录和分片完整性

        【分片路径策略 — 有意设计的不一致】
        - resume.py：拒绝 legacy fallback（return None 让前端从头传）
        - chunk.py（上传分片）：严格走 transfer_id 新目录，禁止 fallback
        - merge.py / direct_merge.py（本入口）：**允许 legacy fallback**
          原因：direct_merge 是"读取历史分片入口"，兼容老用户升级到新逻辑前的失败任务。
          这些任务的历史分片还在旧目录里，拒绝 fallback 会让它们永远合并不了。

        【P1修复】统一调用 ChunkStorageManager.get_and_validate_chunk_dir，
        direct_merge 是"读取历史分片"，所以显式传 allow_legacy_fallback=True。
        """
        from apps.document.views.upload.validators import ChunkStorageManager

        chunk_dir, error = ChunkStorageManager.get_and_validate_chunk_dir(
            file_hash, is_public, user,
            transfer_id=transfer_id,
            allow_legacy_fallback=True,
            system_folder=system_folder,
        )
        if error:
            return None, error
        if not chunk_dir or not os.path.exists(chunk_dir):
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

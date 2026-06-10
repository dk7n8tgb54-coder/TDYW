# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
批量传输操作视图
批量暂停、恢复、取消、删除（支持幂等性校验）
"""

import logging
from django.views.generic import View
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from libs import json_response, JsonParser, Argument, auth
from ...libs.idempotency_utils import IdempotencyChecker

logger = logging.getLogger(__name__)


class TransferBatchPauseView(View):
    """批量暂停传输"""

    @auth('document.document.upload')
    @transaction.atomic
    def post(self, request):
        from ...models import DocumentTransfer
        from ...constants import TransferStatus, is_valid_status_transition
        
        try:
            form, error = JsonParser(
                Argument('transfer_ids', type=list, required=True)
            ).parse(request.body)

            if error:
                return json_response(error=error)

            transfer_ids = form.transfer_ids
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            # 批量查询
            all_transfers = DocumentTransfer.objects.filter(id__in=transfer_ids).order_by()
            
            # 【P2-5修复】简化权限校验逻辑，提高可读性
            if is_supper:
                # 超级管理员可以操作所有记录
                permitted_transfers = all_transfers
            else:
                # 普通用户只能操作自己的记录
                permitted_transfers = all_transfers.filter(
                    user=request.user,
                    tenant_id=request_tenant_id
                )

            updated_count = 0
            success_ids = []
            skipped_ids = []
            skipped_reasons = {}

            for transfer in permitted_transfers:
                if transfer.status == TransferStatus.PAUSED.value:
                    success_ids.append(transfer.id)
                    updated_count += 1
                    continue
                
                current_status_enum = next((s for s in TransferStatus if s.value == transfer.status), None)
                target_status_enum = TransferStatus.PAUSED
                if current_status_enum and is_valid_status_transition(current_status_enum, target_status_enum):
                    transfer.status = TransferStatus.PAUSED.value
                    transfer.save()
                    success_ids.append(transfer.id)
                    updated_count += 1
                else:
                    skipped_ids.append(transfer.id)
                    skipped_reasons[transfer.id] = f'无效状态转换: {transfer.status} -> PAUSED'

            return json_response(data={
                'updated': updated_count,
                'success_ids': success_ids,
                'skipped_ids': skipped_ids,
                'skipped_reasons': skipped_reasons
            })

        except Exception as e:
            logger.error(f'[Document] Error in batch pause: {e}')
            # 【P2-6修复】返回通用错误消息，避免信息泄露
            return json_response(error='批量暂停失败，请稍后重试')


class TransferBatchResumeView(View):
    """批量恢复传输"""

    @auth('document.document.upload')
    @transaction.atomic
    def post(self, request):
        from ...models import DocumentTransfer
        from ...constants import TransferStatus, is_valid_status_transition
        
        try:
            form, error = JsonParser(
                Argument('transfer_ids', type=list, required=True)
            ).parse(request.body)

            if error:
                return json_response(error=error)

            transfer_ids = form.transfer_ids
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            all_transfers = DocumentTransfer.objects.filter(id__in=transfer_ids).order_by()

            # 【P2-5修复】简化权限校验逻辑，提高可读性
            if is_supper:
                permitted_transfers = all_transfers
            else:
                permitted_transfers = all_transfers.filter(
                    user=request.user,
                    tenant_id=request_tenant_id
                )

            updated_count = 0
            success_ids = []
            skipped_ids = []
            skipped_reasons = {}

            for transfer in permitted_transfers:
                # 幂等处理：已是UPLOADING/DOWNLOADING视为成功
                if transfer.status in [TransferStatus.UPLOADING.value, TransferStatus.DOWNLOADING.value]:
                    success_ids.append(transfer.id)
                    updated_count += 1
                    continue

                # 【P0修复】跳过终态任务（COMPLETED/CANCELED），避免无效状态转换
                if transfer.status in [TransferStatus.COMPLETED.value, TransferStatus.CANCELED.value]:
                    skipped_ids.append(transfer.id)
                    skipped_reasons[transfer.id] = f'任务已是终态: {transfer.status}'
                    continue

                # 根据传输类型决定恢复目标状态：下载任务恢复为DOWNLOADING，上传任务恢复为UPLOADING
                current_status_enum = next((s for s in TransferStatus if s.value == transfer.status), None)
                target_status_enum = TransferStatus.DOWNLOADING if transfer.transfer_type == 'DOWNLOAD' else TransferStatus.UPLOADING
                if current_status_enum and is_valid_status_transition(current_status_enum, target_status_enum):
                    transfer.status = target_status_enum.value
                    transfer.error_message = ''
                    if not transfer.started_at:
                        transfer.started_at = timezone.now()
                    transfer.save()
                    success_ids.append(transfer.id)
                    updated_count += 1
                else:
                    skipped_ids.append(transfer.id)
                    skipped_reasons[transfer.id] = f'无效状态转换: {transfer.status} -> {target_status_enum.value}'

            return json_response(data={
                'updated': updated_count,
                'success_ids': success_ids,
                'skipped_ids': skipped_ids,
                'skipped_reasons': skipped_reasons
            })

        except Exception as e:
            logger.error(f'[Document] Error in batch resume: {e}')
            # 【P2-6修复】返回通用错误消息，避免信息泄露
            return json_response(error='批量恢复失败，请稍后重试')


class TransferBatchCancelView(View):
    """批量取消传输（Celery异步版本，支持幂等性校验）"""

    @auth('document.document.upload')
    def post(self, request):
        try:
            form, error = JsonParser(
                Argument('transfer_ids', type=list, required=True),
                Argument('idempotent_key', required=False)  # 【新增】幂等键
            ).parse(request.body)

            if error:
                return json_response(error=error)

            transfer_ids = form.transfer_ids
            request_tenant_id = getattr(request.user, 'tenant_id', '')

            # 【新增】幂等性检查
            idempotency_checker = IdempotencyChecker('transfer:batch_cancel', ttl=300)
            if form.idempotent_key:
                cached_result = idempotency_checker.check(form.idempotent_key)
                if cached_result:
                    logger.info(f'[Transfer] 批量取消幂等性命中: user={request.user.username}')
                    return json_response(data=cached_result)

            from ...tasks import batch_cancel_transfers
            task = batch_cancel_transfers.delay(
                transfer_ids=transfer_ids,
                request_user_id=request.user.id,
                request_tenant_id=request_tenant_id
            )

            response_data = {
                'task_id': task.id,
                'status': 'pending',
                'message': f'批量取消任务已提交'
            }

            # 【新增】缓存幂等结果（5分钟）
            if form.idempotent_key:
                idempotency_checker.cache(response_data)

            return json_response(data=response_data)

        except Exception as e:
            logger.error(f'[Document] Error in batch cancel: {e}')
            # 【P2-6修复】返回通用错误消息，避免信息泄露
            return json_response(error='批量取消失败，请稍后重试')


class TransferBatchDeleteView(View):
    """批量删除传输记录（Celery异步版本，支持幂等性校验）"""

    @auth('document.document.upload')
    def post(self, request):
        try:
            form, error = JsonParser(
                Argument('transfer_ids', type=list, required=True),
                Argument('idempotent_key', required=False)  # 【新增】幂等键
            ).parse(request.body)

            if error:
                return json_response(error=error)

            transfer_ids = form.transfer_ids
            request_tenant_id = getattr(request.user, 'tenant_id', '') or ''

            # 【新增】幂等性检查
            idempotency_checker = IdempotencyChecker('transfer:batch_delete', ttl=300)
            if form.idempotent_key:
                cached_result = idempotency_checker.check(form.idempotent_key)
                if cached_result:
                    logger.info(f'[Transfer] 批量删除传输记录幂等性命中: user={request.user.username}')
                    return json_response(data=cached_result)

            from ...tasks import batch_delete_transfers
            task = batch_delete_transfers.delay(
                transfer_ids=transfer_ids,
                request_user_id=request.user.id,
                request_tenant_id=request_tenant_id
            )

            response_data = {
                'task_id': task.id,
                'status': 'pending',
                'message': f'批量删除任务已提交'
            }

            # 【新增】缓存幂等结果（5分钟）
            if form.idempotent_key:
                idempotency_checker.cache(response_data)

            return json_response(data=response_data)

        except Exception as e:
            logger.error(f'[Document] Error in batch delete: {e}')
            # 【P2-6修复】返回通用错误消息，避免信息泄露
            return json_response(error='批量删除失败，请稍后重试')

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
传输状态管理视图
完成传输、标记失败、更新状态
"""

import logging
from django.views.generic import View
from django.utils import timezone

from libs import json_response, JsonParser, Argument, auth
from apps.document.libs.view_utils import permission_denied_response

logger = logging.getLogger(__name__)


class TransferCompleteView(View):
    """完成传输"""

    @auth('document.document.upload')
    def post(self, request, transfer_id):
        from ...models import DocumentTransfer
        from ...constants import TransferStatus, is_valid_status_transition
        
        try:
            transfer = DocumentTransfer.objects.get(id=transfer_id)

            # 权限检查
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            if (transfer.user != request.user and not is_supper) or \
               (transfer.tenant_id != request_tenant_id and not is_supper):
                return permission_denied_response('无权操作此传输记录', 'not_owner')

            # 幂等性校验
            if transfer.status == TransferStatus.COMPLETED.value:
                return json_response(data={'status': TransferStatus.COMPLETED.value.lower()})

            # 状态转换验证（统一走常量规则）
            current_status_enum = next((s for s in TransferStatus if s.value == transfer.status), None)
            target_status_enum = TransferStatus.COMPLETED
            if not current_status_enum or not is_valid_status_transition(current_status_enum, target_status_enum):
                return json_response(error=f'无效的状态转换：{transfer.status} -> COMPLETED')

            # 更新状态为完成
            transfer.status = TransferStatus.COMPLETED.value
            transfer.progress = 100
            transfer.transferred_size = transfer.file_size
            transfer.uploaded_chunks = transfer.total_chunks
            transfer.completed_at = timezone.now()
            transfer.save()

            return json_response(data={'status': TransferStatus.COMPLETED.value.lower()})

        except DocumentTransfer.DoesNotExist:
            return json_response(error='传输记录不存在')
        except Exception as e:
            logger.error(f'[Document] Error completing transfer: {e}')
            return json_response(error=f'完成传输失败: {str(e)}')


class TransferFailView(View):
    """标记传输失败"""

    @auth('document.document.upload')
    def post(self, request, transfer_id):
        from ...models import DocumentTransfer
        from ...constants import TransferStatus, is_valid_status_transition
        
        try:
            form, error = JsonParser(
                Argument('error_message', type=str, required=False, help='错误信息'),
            ).parse(request.body)

            if error:
                return json_response(error=error)

            transfer = DocumentTransfer.objects.get(id=transfer_id)

            # 权限检查
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            if (transfer.user != request.user and not is_supper) or \
               (transfer.tenant_id != request_tenant_id and not is_supper):
                return permission_denied_response('无权操作此传输记录', 'not_owner')

            # 幂等性校验
            if transfer.status == TransferStatus.FAILED.value:
                return json_response(data={'status': TransferStatus.FAILED.value.lower()})

            # 【P0修复】添加状态转换验证，防止从终态直接标记为失败
            current_status_enum = next((s for s in TransferStatus if s.value == transfer.status), None)
            target_status_enum = TransferStatus.FAILED
            
            # 定义允许转换为FAILED的状态列表
            ALLOWED_TO_FAIL = [
                TransferStatus.PENDING,
                TransferStatus.UPLOADING,
                TransferStatus.DOWNLOADING,
                TransferStatus.PAUSED,
                TransferStatus.MERGING
            ]
            
            if current_status_enum not in ALLOWED_TO_FAIL:
                logger.warning(f'[Document] 非法状态转换尝试: {transfer.status} -> FAILED')
                return json_response(error=f'不能从 {transfer.status} 状态标记为失败')
            
            # 使用统一的状态转换验证
            if not is_valid_status_transition(current_status_enum, target_status_enum):
                return json_response(error=f'无效的状态转换：{transfer.status} -> FAILED')

            # 更新状态为失败
            transfer.status = TransferStatus.FAILED.value
            transfer.error_message = form.error_message or '上传失败'
            transfer.save()

            return json_response(data={'status': TransferStatus.FAILED.value.lower()})

        except DocumentTransfer.DoesNotExist:
            return json_response(error='传输记录不存在')
        except Exception as e:
            logger.error(f'[Document] Error marking transfer as failed: {e}')
            return json_response(error='标记传输失败失败，请稍后重试')


class TransferStatusUpdateView(View):
    """更新传输状态"""

    @auth('document.document.upload')
    def post(self, request, transfer_id):
        from ...models import DocumentTransfer
        from ...constants import TransferStatus, is_valid_status_transition
        
        try:
            form, error = JsonParser(
                Argument('status', type=str, required=True, help='新状态'),
            ).parse(request.body)

            if error:
                return json_response(error=error)

            transfer = DocumentTransfer.objects.get(id=transfer_id)

            # 权限检查
            request_tenant_id = getattr(request.user, 'tenant_id', '')
            is_supper = getattr(request.user, 'is_supper', False)

            if (transfer.user != request.user and not is_supper) or \
               (transfer.tenant_id != request_tenant_id and not is_supper):
                return permission_denied_response('无权更新此传输记录', 'not_owner')

            # 状态流转验证
            current_status = transfer.status
            new_status = form.status

            # 【幂等性校验】如果当前状态已经是目标状态，直接返回成功
            if current_status == new_status:
                return json_response(data={'status': new_status})

            current_status_enum = next((s for s in TransferStatus if s.value == current_status), None)
            new_status_enum = next((s for s in TransferStatus if s.value == new_status), None)

            if current_status_enum and new_status_enum:
                if not is_valid_status_transition(current_status_enum, new_status_enum):
                    return json_response(error=f'无效的状态转换：{current_status} -> {new_status}')
            else:
                return json_response(error='无效的状态值')

            transfer.status = new_status
            if new_status == TransferStatus.UPLOADING.value:
                if not transfer.started_at:
                    transfer.started_at = timezone.now()

            transfer.save()
            return json_response(data={'status': new_status})

        except DocumentTransfer.DoesNotExist:
            return json_response(error='传输记录不存在')
        except Exception as e:
            logger.error(f'[Document] Error updating transfer status: {e}')
            return json_response(error=f'更新传输状态失败: {str(e)}')

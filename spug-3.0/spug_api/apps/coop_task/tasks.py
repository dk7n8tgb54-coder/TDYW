# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""协作任务后台维护任务

- cleanup_expired_task_attachments: 到期任务的附件物理清理

到期定义（三选一，均以任务结束时间为准）：
- 已完成任务：completed_at 早于 now - COOP_TASK_FILE_RETENTION_DAYS
- 已作废任务：updated_at（作废时间）早于 cutoff
- 已删除任务：deleted_at 早于 cutoff

清理范围：仅附件的物理文件与附件记录（EvidenceAttachment），
任务/材料/分派/交付明细/审计记录全部保留，协作过程始终可查。
幂等性：文件删除失败的附件保留记录，下次运行自动重试。
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.evidence.attachment_service import AttachmentService
from apps.evidence.models import EvidenceAttachment

from .models import (
    CoopTask, CoopTaskItem, CoopTaskDelivery,
    TASK_STATUS_COMPLETED, TASK_STATUS_VOIDED,
)

logger = logging.getLogger(__name__)

# 单次运行最多清理的附件数，超出部分留待下次运行，避免单次任务执行过长
CLEANUP_BATCH_SIZE = 500


def _find_expired_task_ids(cutoff):
    """返回结束时间早于 cutoff 的到期任务ID（含软删除任务）"""
    return list(CoopTask.objects.all_with_deleted().filter(
        Q(status=TASK_STATUS_COMPLETED, completed_at__lt=cutoff)
        | Q(status=TASK_STATUS_VOIDED, updated_at__lt=cutoff)
        | Q(is_deleted=True, deleted_at__lt=cutoff),
    ).values_list('id', flat=True))


def _find_expired_attachments(task_ids):
    """返回到期任务名下的全部附件（交付明细附件 + 材料模板）"""
    if not task_ids:
        return EvidenceAttachment.objects.none()
    delivery_ids = list(CoopTaskDelivery.objects.filter(
        assignment__task_id__in=task_ids).values_list('id', flat=True))
    item_ids = list(CoopTaskItem.objects.filter(
        task_id__in=task_ids).values_list('id', flat=True))
    cond = Q()
    if delivery_ids:
        cond |= Q(object_type='delivery', object_id__in=[str(x) for x in delivery_ids])
    if item_ids:
        cond |= Q(object_type='item_template', object_id__in=[str(x) for x in item_ids])
    return EvidenceAttachment.objects.filter(module='coop_task').filter(cond)


@shared_task
def cleanup_expired_task_attachments():
    """清理到期任务的附件文件（任务与交付记录保留）"""
    retention_days = int(getattr(settings, 'COOP_TASK_FILE_RETENTION_DAYS', 365))
    cutoff = timezone.now() - timedelta(days=retention_days)
    task_ids = _find_expired_task_ids(cutoff)
    if not task_ids:
        logger.info('[CoopTask] 到期任务附件清理: 无到期任务（保留期=%s天）', retention_days)
        return {'expired_tasks': 0, 'deleted': 0, 'failed': 0}

    attachments = _find_expired_attachments(task_ids)[:CLEANUP_BATCH_SIZE]
    deleted, failed = 0, 0
    for att in attachments:
        error = AttachmentService.hard_delete(att)
        if error:
            failed += 1
            logger.warning('[CoopTask] 附件清理失败，保留记录下次重试: id=%s path=%s err=%s',
                           att.id, att.file_path, error)
        else:
            deleted += 1
    logger.info('[CoopTask] 到期任务附件清理完成: 到期任务=%s 删除附件=%s 失败=%s 保留期=%s天',
                len(task_ids), deleted, failed, retention_days)
    return {'expired_tasks': len(task_ids), 'deleted': deleted, 'failed': failed}

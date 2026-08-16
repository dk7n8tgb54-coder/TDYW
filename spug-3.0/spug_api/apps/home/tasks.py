# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""公告模块 Celery 异步任务"""
import logging
from celery import shared_task

from django.utils import timezone
from apps.home.models import Announcement, STATUS_PUBLISHED, STATUS_EXPIRED
from apps.logs.audit import log_celery_audit

logger = logging.getLogger(__name__)


@shared_task
def sync_announcement_status():
    """将超过生效结束时间且仍为已发布的公告置为已过期

    接口已实时计算 computed_status 兜底，本任务仅用于保持管理端存储状态准确。
    """
    now = timezone.now()
    updated = Announcement.objects.filter(
        is_deleted=False,
        status=STATUS_PUBLISHED,
        effective_end_at__isnull=False,  # 排除长期有效（空）；DateTimeField 不能与空字符串比较
        effective_end_at__lt=now,        # 已到失效时间
    ).update(status=STATUS_EXPIRED)
    if updated > 0:
        log_celery_audit('update', 'home',
                         target_name='公告自动过期',
                         detail={'expired_count': updated})
    return updated

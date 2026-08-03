# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""提醒事项模块 Celery 异步任务"""
import logging
from celery import shared_task

from django.utils import timezone
from apps.reminder.models import Reminder, ReminderLog
from apps.logs.audit import log_celery_audit

logger = logging.getLogger(__name__)


@shared_task
def check_reminders():
    """检查并发送提醒事项

    每 5 分钟运行一次。对于每条启用的提醒规则：
    1. 判断今天是否命中（matches_today：目标日 + 重复周期）
    2. 命中则为每个接收人创建一条 Log 记录（date_key 唯一约束防重复）
    """
    now = timezone.now()
    today = now.date()
    date_key = now.strftime('%Y-%m-%d')

    reminders = Reminder.objects.filter(enabled=True, is_deleted=False)
    sent_count = 0

    for reminder in reminders:
        if not reminder.matches_today(today):
            continue

        recipients = reminder.get_recipients()
        for user_info in recipients:
            uid = user_info.get('id')
            if not uid:
                continue
            try:
                _, created = ReminderLog.objects.get_or_create(
                    reminder_id=reminder.id,
                    user_id=uid,
                    date_key=date_key,
                    defaults={
                        'user_name': user_info.get('nickname', ''),
                        'is_acked': False,
                    }
                )
                if created:
                    sent_count += 1
            except Exception as e:
                logger.warning('提醒事项记录创建失败 reminder=%s user=%s: %s',
                               reminder.id, uid, e)

    if sent_count > 0:
        log_celery_audit('create', 'reminder',
                         target_name='提醒事项发送',
                         detail={'sent_count': sent_count, 'date_key': date_key})
    return sent_count

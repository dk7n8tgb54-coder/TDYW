# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import logging
from datetime import date, datetime

from celery import shared_task
from django.utils import timezone

from django.utils import timezone
from apps.contract_agreement.models import ContractAgreement
from apps.logs.audit import log_celery_audit

logger = logging.getLogger(__name__)


def _as_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.strptime(value, '%Y-%m-%d').date()
    return value


def calculate_agreement_status(valid_end_date, today=None):
    """计算合同协议状态（两态）和剩余天数。

    Returns:
        tuple: (status, days_left)
            status: 'normal' / 'expired'（expired 前端显示为已关闭）
            days_left: 剩余天数（负数=已过截止日期）
    """
    if today is None:
        today = date.today()
    valid_end_date = _as_date(valid_end_date)
    days_left = (valid_end_date - today).days

    if days_left < 0:
        return 'expired', days_left
    return 'normal', days_left


def scan_single_contract_agreement(agreement, today=None):
    """扫描单条合同协议，更新两态 status 和扫描时间。"""
    if today is None:
        today = timezone.now().date()
    status, days_left = calculate_agreement_status(agreement.valid_end_date, today)

    update_data = {'last_remind_at': timezone.now()}
    updated = False
    if agreement.status != status:
        update_data['status'] = status
        agreement.status = status
        updated = True

    ContractAgreement.objects.filter(pk=agreement.id).update(**update_data)
    agreement.last_remind_at = update_data['last_remind_at']

    logger.info(
        '[ContractAgreement] scan one: agreement=%s, status=%s, days_left=%s, updated=%s',
        agreement.id, status, days_left, updated,
    )
    return {
        'status': status,
        'days_left': days_left,
        'updated': updated,
    }


@shared_task(bind=True, soft_time_limit=300, time_limit=600, queue='contract_agreement')
def scan_contract_agreement_expiration(self):
    """扫描全部合同协议到期状态。"""
    today = timezone.now().date()
    agreements = ContractAgreement.objects.all().select_related('created_by')
    total = agreements.count()
    updated_count = 0

    for agreement in agreements:
        result = scan_single_contract_agreement(agreement, today)
        if result['updated']:
            updated_count += 1

    logger.info('[ContractAgreement] scan all finished: total=%s, updated=%s', total, updated_count)
    if updated_count > 0:
        log_celery_audit('update', 'contract_agreement',
                         target_name='合同协议到期状态扫描',
                         detail={'total': total, 'updated': updated_count})
    return {'total': total, 'updated': updated_count}

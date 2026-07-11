# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import logging
from datetime import date, datetime

from celery import shared_task
from django.utils import timezone

from libs import human_datetime
from apps.contract_agreement.models import (
    ContractAgreement,
    EXPIRING_DAYS_THRESHOLD,
)

logger = logging.getLogger(__name__)


def _as_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.strptime(value, '%Y-%m-%d').date()
    return value


def calculate_agreement_status(valid_end_date, today=None):
    """计算合同协议业务状态、提醒状态和剩余天数。"""
    if today is None:
        today = date.today()
    valid_end_date = _as_date(valid_end_date)
    days_left = (valid_end_date - today).days

    business_status = (
        ContractAgreement.STATUS_EXPIRED
        if days_left < 0
        else ContractAgreement.STATUS_ACTIVE
    )
    if days_left < 0:
        remind_status = 'expired'
    elif days_left <= EXPIRING_DAYS_THRESHOLD:
        remind_status = 'expiring'
    else:
        remind_status = 'normal'
    return business_status, remind_status, days_left


def scan_single_contract_agreement(agreement, today=None):
    """扫描单条合同协议，更新业务状态和扫描时间。"""
    if today is None:
        today = timezone.now().date()
    business_status, remind_status, days_left = calculate_agreement_status(
        agreement.valid_end_date, today)

    update_data = {'last_remind_at': human_datetime()}
    updated = False
    if agreement.status != business_status:
        update_data['status'] = business_status
        agreement.status = business_status
        updated = True

    ContractAgreement.objects.filter(pk=agreement.id).update(**update_data)
    agreement.last_remind_at = update_data['last_remind_at']

    logger.info(
        '[ContractAgreement] scan one: agreement=%s, status=%s, remind_status=%s, days_left=%s, updated=%s',
        agreement.id, business_status, remind_status, days_left, updated,
    )
    return {
        'status': business_status,
        'remind_status': remind_status,
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
    return {'total': total, 'updated': updated_count}

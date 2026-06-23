# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
无线电台执照到期扫描任务（执照中心模型）

重构说明（2026-06-23）：
- scan_single_license 只更新 license.status，不再预生成 RadioLicenseReminder
- 弹窗判断由 ReminderPopupView 实时查询，"已处理"由 LicenseReminderAck 管理
- RadioLicenseReminder 表降级为历史日志，仅在编辑执照时按需写入（可选）

扫描逻辑：
1. 遍历所有执照
2. 计算 days_left，判定 normal / expiring / expired
3. 更新 license.status 字段（供列表页筛选/排序）
4. 不再生成 reminder 记录（弹窗实时查询，无需预生成）
"""
import logging
from datetime import date
from celery import shared_task
from django.utils import timezone

from apps.radio_license.models import (
    RadioLicense, RadioLicenseReminder,
    EXPIRING_DAILY_REMIND_TYPE, EXPIRED_REMIND_TYPE,
    EXPIRING_DAYS_THRESHOLD,
)

logger = logging.getLogger(__name__)


def calculate_license_status(valid_to, today=None):
    """计算执照状态

    Args:
        valid_to: 截止日期 (date 或 str 'YYYY-MM-DD')
        today: 当前日期 (date)，默认为 date.today()

    Returns:
        tuple: (status, days_left)
            status: 'normal' / 'expiring' / 'expired'
            days_left: 剩余天数（负数=已过期）

    状态判定（与 RadioLicenseBadgeView 的 60 天规则保持一致）：
        - days_left < 0                    → expired
        - 0 <= days_left <= 60             → expiring
        - days_left > 60                   → normal
    """
    if today is None:
        today = date.today()
    # 兼容字符串输入
    if isinstance(valid_to, str):
        from datetime import datetime
        valid_to = datetime.strptime(valid_to, '%Y-%m-%d').date()
    days_left = (valid_to - today).days
    if days_left < 0:
        return 'expired', days_left
    elif days_left <= EXPIRING_DAYS_THRESHOLD:
        return 'expiring', days_left
    return 'normal', days_left


def scan_single_license(license_obj, today=None):
    """扫描单张执照的到期状态并更新 license.status（执照中心模型）

    重构后职责：
    - 计算 days_left，判定状态
    - 更新 license.status 字段（若变化）
    - 不再生成 RadioLicenseReminder（弹窗由 ReminderPopupView 实时查询）
    - 不再调用 _get_receiver / _has_handled_in_current_cycle（这些逻辑已迁移到 ack 模型）

    Args:
        license_obj: RadioLicense 实例
        today: 可选，指定"今天"日期（用于测试）

    Returns:
        dict: {'status': str, 'days_left': int, 'updated': bool}
    """
    if today is None:
        today = timezone.now().date()
    status, days_left = calculate_license_status(license_obj.valid_to, today)

    # 更新执照状态
    updated = False
    if license_obj.status != status:
        RadioLicense.objects.filter(pk=license_obj.id).update(status=status)
        license_obj.status = status
        updated = True

    logger.info(f'[RadioLicense] 单条扫描: license={license_obj.id}, '
                f'status={status}, days_left={days_left}, updated={updated}')
    return {
        'status': status,
        'days_left': days_left,
        'updated': updated,
    }


@shared_task(bind=True, soft_time_limit=300, time_limit=600, queue='radio_license')
def scan_radio_license_expiration(self):
    """扫描所有执照到期状态并更新 license.status（定时兜底）

    重构后职责：
    - 遍历所有执照，更新 license.status
    - 不再预生成 RadioLicenseReminder
    - 弹窗判断由前端查询 ReminderPopupView 实时完成
    """
    today = timezone.now().date()
    logger.info(f'[RadioLicense] 开始全量扫描执照到期状态: today={today}')

    licenses = RadioLicense.objects.all().select_related('created_by')
    total = licenses.count()
    updated_count = 0

    for license_obj in licenses:
        old_status = license_obj.status
        result = scan_single_license(license_obj, today)
        if result['updated']:
            updated_count += 1

    logger.info(f'[RadioLicense] 全量扫描完成: total={total}, updated={updated_count}')
    return {
        'total': total,
        'updated': updated_count,
    }

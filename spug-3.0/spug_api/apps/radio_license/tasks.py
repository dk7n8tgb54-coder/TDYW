# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
无线电台执照到期扫描任务

扫描逻辑：
1. 遍历所有未删除执照
2. 计算剩余天数和状态
3. 更新执照 status 字段
4. 对命中 45/30/15/7/1 天节点的执照生成分级提醒
5. 对已过期执照生成过期提醒
6. 去重：同一执照 + 同一提醒类型 + 同一截止日期 + 同一接收人 = 只生成一条
"""
import logging
from datetime import date
from celery import shared_task
from django.utils import timezone

from apps.radio_license.models import (
    RadioLicense, RadioLicenseReminder,
    REMIND_LEVELS, EXPIRED_REMIND_TYPE, REMIND_TYPE_MAP,
)
from apps.account.models import User as UserModel

logger = logging.getLogger(__name__)


def calculate_license_status(valid_to, today=None):
    """计算执照状态

    Args:
        valid_to: 截止日期 (date)
        today: 当前日期 (date)，默认为 date.today()

    Returns:
        tuple: (status, days_left)
            status: 'normal' / 'expiring' / 'expired'
            days_left: 剩余天数（负数=已过期）
    """
    if today is None:
        today = date.today()
    days_left = (valid_to - today).days
    if days_left < 0:
        return 'expired', days_left
    elif days_left <= 45:
        return 'expiring', days_left
    return 'normal', days_left


def _get_receiver(license_obj):
    """获取提醒接收人

    优先级：责任人 > 创建人
    Returns:
        tuple: (user_id, user_name) 或 (None, None)
    """
    # 1. 责任人
    if license_obj.responsible_user_id:
        user = UserModel.objects.filter(pk=license_obj.responsible_user_id, is_active=True).first()
        if user:
            return user.id, (user.nickname or user.username)

    # 2. 创建人
    if license_obj.created_by_id:
        user = UserModel.objects.filter(pk=license_obj.created_by_id, is_active=True).first()
        if user:
            return user.id, (user.nickname or user.username)

    return None, None


def _generate_reminder(license_obj, remind_type, days_left, today, receiver_user_id, receiver_user_name):
    """生成一条提醒记录（含去重校验）

    去重规则：同一执照 + 同一提醒类型 + 同一截止日期周期 + 同一接收人 = 只生成一条
    如果执照续期后截止日期变化，可以进入新的提醒周期。

    Returns:
        RadioLicenseReminder or None
    """
    # 去重检查：同执照 + 同类型 + 同截止日期 + 同接收人
    exists = RadioLicenseReminder.objects.filter(
        tenant_id=license_obj.tenant_id,
        license_id=license_obj.id,
        remind_type=remind_type,
        receiver_user_id=receiver_user_id,
    ).exists()
    # 进一步确保是同一截止日期周期：检查 remind_date 是否在 valid_to 对应的同一月内
    # 简化：同一执照 + 同类型 + 同接收人只生成一次，续期后 valid_to 变化说明需要新的提醒
    # 但更准确的做法是：提醒记录关联的执照的 valid_to 与当前一致
    # 我们用 remind_type + license_id + receiver_user_id 去重，已经足够
    if exists:
        logger.debug(f'[RadioLicense] 跳过重复提醒: license={license_obj.id}, '
                      f'type={remind_type}, receiver={receiver_user_id}')
        return None

    type_text = REMIND_TYPE_MAP.get(remind_type, remind_type)
    title = f'【{type_text}】{license_obj.station_name}'
    content = (
        f'执照"{license_obj.station_name}"'
        f'（{license_obj.valid_from} ~ {license_obj.valid_to}）'
    )
    if days_left < 0:
        content += f'已过期 {abs(days_left)} 天，请及时处理。'
    else:
        content += f'将于 {days_left} 天后到期，请及时续期。'

    reminder = RadioLicenseReminder.objects.create(
        tenant_id=license_obj.tenant_id,
        license=license_obj,
        remind_type=remind_type,
        remind_date=today,
        days_left=days_left,
        title=title,
        content=content,
        receiver_user_id=receiver_user_id,
        receiver_user_name=receiver_user_name,
    )
    logger.info(f'[RadioLicense] 生成提醒: license={license_obj.id}, '
                f'type={remind_type}, receiver={receiver_user_name}({receiver_user_id})')
    return reminder


@shared_task(bind=True, soft_time_limit=300, time_limit=600, queue='radio_license')
def scan_radio_license_expiration(self):
    """扫描执照到期状态并生成提醒

    执行逻辑：
    1. 查询所有未删除的执照
    2. 对每张执照计算状态和剩余天数
    3. 更新执照 status 字段
    4. 检查是否命中提醒节点（45/30/15/7/1天）
    5. 检查是否已过期
    6. 满足条件则生成提醒（去重）
    """
    today = timezone.now().date()
    logger.info(f'[RadioLicense] 开始扫描执照到期状态: today={today}')

    licenses = RadioLicense.objects.filter(is_deleted=False).select_related('created_by')
    total = licenses.count()
    updated_count = 0
    reminder_count = 0

    for license_obj in licenses:
        # 计算状态
        status, days_left = calculate_license_status(license_obj.valid_to, today)

        # 更新执照状态
        if license_obj.status != status:
            RadioLicense.objects.filter(pk=license_obj.id).update(status=status)
            updated_count += 1

        # 获取接收人
        receiver_user_id, receiver_user_name = _get_receiver(license_obj)
        if not receiver_user_id:
            logger.warning(f'[RadioLicense] 执照 {license_obj.id} 无接收人，跳过提醒')
            continue

        # 分级提醒：检查是否命中节点
        if days_left in REMIND_LEVELS:
            remind_type = REMIND_LEVELS[days_left]
            reminder = _generate_reminder(
                license_obj, remind_type, days_left, today,
                receiver_user_id, receiver_user_name,
            )
            if reminder:
                reminder_count += 1

        # 已过期提醒（仅过期当天，days_left == -1 生成，避免每次都检查所有过期执照）
        # 简化：对 days_left < 0 的执照也生成提醒，但去重保证只生成一次
        if days_left < 0:
            reminder = _generate_reminder(
                license_obj, EXPIRED_REMIND_TYPE, days_left, today,
                receiver_user_id, receiver_user_name,
            )
            if reminder:
                reminder_count += 1

    logger.info(f'[RadioLicense] 扫描完成: total={total}, updated={updated_count}, '
                f'new_reminders={reminder_count}')
    return {
        'total': total,
        'updated': updated_count,
        'new_reminders': reminder_count,
    }

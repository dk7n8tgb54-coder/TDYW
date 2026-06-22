# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
无线电台执照到期扫描任务

扫描逻辑：
1. 遍历所有执照
2. 计算剩余天数和状态（0 <= days_left <= 60 = expiring，< 0 = expired，> 60 = normal）
3. 更新执照 status 字段
4. 即将到期（0 <= days_left <= 60）：每天为责任人生成一条 expiring_daily 提醒
5. 已过期（days_left < 0）：生成一条 expired 提醒（同执照同接收人只生成一次）
6. 若该执照当前 valid_to 周期内已存在 is_handled=True 的处理记录，不再生成新提醒
7. 去重：
   - expiring_daily：同执照 + 同接收人 + 同 remind_date = 只生成一条（满足每日提醒）
   - expired：同执照 + 同接收人 + 同 remind_type = 只生成一条
"""
import logging
from datetime import date
from celery import shared_task
from django.utils import timezone

from apps.radio_license.models import (
    RadioLicense, RadioLicenseReminder,
    EXPIRING_DAILY_REMIND_TYPE, EXPIRED_REMIND_TYPE, REMIND_TYPE_MAP,
    EXPIRING_DAYS_THRESHOLD,
)
from apps.account.models import User as UserModel

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


def _get_receiver(license_obj):
    """获取提醒接收人（仅责任人）

    业务规则：提醒只发送给执照绑定的责任人账号。
    - 责任人有效（账号存在且启用）→ 发送给该账号
    - 责任人无效（账号不存在 / 已禁用）→ 跳过本次提醒，WARN 日志告警

    Returns:
        tuple: (user_id, user_name) 或 (None, None)
    """
    if not license_obj.responsible_user_id:
        logger.warning(
            f'[RadioLicense] 执照 {license_obj.id} 未绑定责任人，跳过提醒（请补录责任人）'
        )
        return None, None

    user = UserModel.objects.filter(
        pk=license_obj.responsible_user_id, is_active=True
    ).first()
    if not user:
        logger.warning(
            f'[RadioLicense] 执照 {license_obj.id} 的责任人账号 '
            f'({license_obj.responsible_user_id}) 不存在或已禁用，跳过提醒'
        )
        return None, None

    return user.id, (user.nickname or user.username)


def _generate_reminder(license_obj, remind_type, days_left, today, receiver_user_id, receiver_user_name):
    """生成一条提醒记录（含去重校验）

    去重规则：
    - expiring_daily：同一执照 + 同一接收人 + 同一 remind_date + 未处理 = 只生成一条
      （满足"每天提醒"需求，定时任务多次执行不会重复；
       已作废/已处理的旧记录不参与去重，保证编辑 valid_to 后可生成新内容提醒）
    - expired：同一执照 + 同一接收人 + 同一 remind_type = 只生成一条
      （同一过期周期只提醒一次，续期后 valid_to 变化视为新周期）

    Returns:
        RadioLicenseReminder or None
    """
    # 去重检查
    dedup_filter = {
        'tenant_id': license_obj.tenant_id,
        'license_id': license_obj.id,
        'remind_type': remind_type,
        'receiver_user_id': receiver_user_id,
    }
    # 每日提醒额外按 remind_date + 未处理去重，确保每天可生成新一条
    if remind_type == EXPIRING_DAILY_REMIND_TYPE:
        dedup_filter['remind_date'] = today
        dedup_filter['is_handled'] = False
    exists = RadioLicenseReminder.objects.filter(**dedup_filter).exists()
    if exists:
        logger.debug(f'[RadioLicense] 跳过重复提醒: license={license_obj.id}, '
                      f'type={remind_type}, receiver={receiver_user_id}, date={today}')
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
                f'type={remind_type}, receiver={receiver_user_name}({receiver_user_id}), '
                f'days_left={days_left}')
    return reminder


def _has_handled_in_current_cycle(license_obj):
    """检查该执照当前 valid_to 周期内是否已存在 is_handled=True 的处理记录

    业务含义：用户已针对本周期到期事项点击"已处理"，则不再生成新提醒。
    续期后 valid_to 变化视为新周期，旧的处理记录不会阻止新提醒。

    判断方式：通过 reminder 的 remind_date + days_left 反推该提醒对应的
    valid_to，与执照当前 valid_to 比较来区分周期（无需新增字段/迁移）。

    Returns:
        bool
    """
    from datetime import timedelta
    handled = RadioLicenseReminder.objects.filter(
        tenant_id=license_obj.tenant_id,
        license_id=license_obj.id,
        is_handled=True,
    ).values_list('remind_date', 'days_left')
    for remind_date, days_left in handled:
        if remind_date and days_left is not None:
            # days_left = valid_to - remind_date → valid_to = remind_date + days_left
            if remind_date + timedelta(days=days_left) == license_obj.valid_to:
                return True
    return False


def scan_single_license(license_obj, today=None):
    """扫描单张执照的到期状态并生成提醒

    用于事件驱动场景（新增/编辑执照时即时触发），
    与 scan_radio_license_expiration（定时全量扫描）互补。

    Args:
        license_obj: RadioLicense 实例（需有 valid_to, status 等字段）
        today: 可选，指定"今天"日期（用于测试），默认 timezone.now().date()

    Returns:
        dict: {'status': str, 'days_left': int, 'new_reminders': int}
    """
    if today is None:
        today = timezone.now().date()
    status, days_left = calculate_license_status(license_obj.valid_to, today)

    # 更新执照状态
    if license_obj.status != status:
        RadioLicense.objects.filter(pk=license_obj.id).update(status=status)
        license_obj.status = status

    # 获取接收人
    receiver_user_id, receiver_user_name = _get_receiver(license_obj)
    reminder_count = 0

    if not receiver_user_id:
        logger.debug(f'[RadioLicense] 执照 {license_obj.id} 无接收人，跳过提醒')
        logger.info(f'[RadioLicense] 单条扫描: license={license_obj.id}, '
                    f'status={status}, days_left={days_left}, new_reminders=0')
        return {
            'status': status,
            'days_left': days_left,
            'new_reminders': 0,
        }

    # 若本周期已被处理，不再生成新提醒
    if _has_handled_in_current_cycle(license_obj):
        logger.debug(f'[RadioLicense] 执照 {license_obj.id} 本周期已处理，跳过提醒生成')
        logger.info(f'[RadioLicense] 单条扫描: license={license_obj.id}, '
                    f'status={status}, days_left={days_left}, new_reminders=0 (handled)')
        return {
            'status': status,
            'days_left': days_left,
            'new_reminders': 0,
        }

    # 即将到期：每天生成一条 expiring_daily 提醒
    if status == 'expiring':
        reminder = _generate_reminder(
            license_obj, EXPIRING_DAILY_REMIND_TYPE, days_left, today,
            receiver_user_id, receiver_user_name,
        )
        if reminder:
            reminder_count += 1
    # 已过期：生成 expired 提醒（同周期一次）
    elif status == 'expired':
        reminder = _generate_reminder(
            license_obj, EXPIRED_REMIND_TYPE, days_left, today,
            receiver_user_id, receiver_user_name,
        )
        if reminder:
            reminder_count += 1

    logger.info(f'[RadioLicense] 单条扫描: license={license_obj.id}, '
                f'status={status}, days_left={days_left}, new_reminders={reminder_count}')
    return {
        'status': status,
        'days_left': days_left,
        'new_reminders': reminder_count,
    }


@shared_task(bind=True, soft_time_limit=300, time_limit=600, queue='radio_license')
def scan_radio_license_expiration(self):
    """扫描所有执照到期状态并生成提醒（定时兜底）

    执行逻辑：
    1. 查询所有执照
    2. 对每张执照调用 scan_single_license
    3. 汇总统计
    """
    today = timezone.now().date()
    logger.info(f'[RadioLicense] 开始全量扫描执照到期状态: today={today}')

    licenses = RadioLicense.objects.all().select_related('created_by')
    total = licenses.count()
    updated_count = 0
    reminder_count = 0

    for license_obj in licenses:
        old_status = license_obj.status
        result = scan_single_license(license_obj)
        if result['status'] != old_status:
            updated_count += 1
        reminder_count += result['new_reminders']

    logger.info(f'[RadioLicense] 全量扫描完成: total={total}, updated={updated_count}, '
                f'new_reminders={reminder_count}')
    return {
        'total': total,
        'updated': updated_count,
        'new_reminders': reminder_count,
    }

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""提醒事项模块数据模型"""
import json
import logging

from django.db import models
from libs.mixins import ModelMixin
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id

logger = logging.getLogger(__name__)

REPEAT_NONE = 'none'
REPEAT_DAILY = 'daily'
REPEAT_WEEKLY = 'weekly'
REPEAT_MONTHLY = 'monthly'
REPEAT_YEARLY = 'yearly'

REPEAT_TYPES = (
    (REPEAT_NONE, '不重复'),
    (REPEAT_DAILY, '每N天'),
    (REPEAT_WEEKLY, '每N周'),
    (REPEAT_MONTHLY, '每N月'),
    (REPEAT_YEARLY, '每N年'),
)


class Reminder(models.Model, TenantModelMixin):
    """提醒事项规则（tdyw_reminders）

    管理员配置一条规则，指定事件名称、目标日、重复周期、接收人列表和提醒文案。
    用户前端轮询 pending 接口获取未确认的提醒（懒创建），点击"我去写了"后 ACK。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    name = models.CharField(max_length=100, help_text='事件名称')
    enabled = models.BooleanField(default=True, help_text='是否启用')

    # 目标日（首次提醒日期）
    target_date = models.DateField(help_text='目标日')

    # 重复周期
    repeat_type = models.CharField(
        max_length=10, default=REPEAT_NONE, choices=REPEAT_TYPES, help_text='重复类型'
    )
    repeat_interval = models.IntegerField(default=1, help_text='重复间隔（N天/N周/N月/N年）')

    # 提醒内容
    content = models.TextField(blank=True, default='', help_text='提醒正文')

    # 接收人快照 JSON: [{"id":1,"nickname":"张三"}, ...]
    recipient_users = models.TextField(default='[]', help_text='接收人JSON列表')
    # 操作人快照
    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')
    created_by_id = models.IntegerField(null=True, blank=True, help_text='创建人ID')
    created_by_name = models.CharField(max_length=100, default='', help_text='创建人姓名快照')
    updated_at = models.DateTimeField(null=True, blank=True, help_text='更新时间')
    updated_by_id = models.IntegerField(null=True, blank=True, help_text='更新人ID')
    updated_by_name = models.CharField(max_length=100, default='', help_text='更新人姓名快照')

    # 软删除
    is_deleted = models.BooleanField(default=False, help_text='软删除标识')
    deleted_at = models.DateTimeField(null=True, blank=True, help_text='删除时间')
    deleted_by_id = models.IntegerField(null=True, blank=True, help_text='删除人ID')
    deleted_by_name = models.CharField(max_length=100, default='', help_text='删除人姓名快照')

    def to_view(self):
        tmp = self.to_dict()
        try:
            tmp['recipient_users'] = json.loads(self.recipient_users)
        except (json.JSONDecodeError, TypeError):
            tmp['recipient_users'] = []
        if self.target_date:
            tmp['target_date'] = self.target_date.strftime('%Y-%m-%d')
        return tmp

    def get_recipients(self):
        """解析接收人列表"""
        try:
            return json.loads(self.recipient_users)
        except (json.JSONDecodeError, TypeError):
            return []

    def matches_today(self, today=None):
        """判断今天是否命中此提醒规则

        - none: 仅 target_date 当天
        - daily: (today - target_date).days % interval == 0 且 >= 0
        - weekly: (today - target_date).days % (7*interval) == 0 且 >= 0
        - monthly: today.day == target_date.day 且月份差 % interval == 0
        - yearly: today.month/day == target_date.month/day 且年份差 % interval == 0
        """
        from datetime import date as date_cls
        today = today or date_cls.today()
        td = self.target_date
        if not td:
            return False
        if today < td:
            return False
        if self.repeat_type == REPEAT_NONE:
            return today == td
        delta_days = (today - td).days
        if self.repeat_type == REPEAT_DAILY:
            return delta_days % max(self.repeat_interval, 1) == 0
        if self.repeat_type == REPEAT_WEEKLY:
            return delta_days % (7 * max(self.repeat_interval, 1)) == 0
        if self.repeat_type == REPEAT_MONTHLY:
            if today.day != td.day:
                return False
            months_diff = (today.year - td.year) * 12 + (today.month - td.month)
            return months_diff % max(self.repeat_interval, 1) == 0
        if self.repeat_type == REPEAT_YEARLY:
            if today.month != td.month or today.day != td.day:
                return False
            years_diff = today.year - td.year
            return years_diff % max(self.repeat_interval, 1) == 0
        return False

    def __repr__(self):
        return '<Reminder %s %s>' % (self.id, self.name)

    class Meta:
        db_table = 'tdyw_reminders'
        verbose_name = '提醒事项'
        verbose_name_plural = '提醒事项'
        ordering = ('-id',)
        indexes = [
            models.Index(fields=['enabled', 'is_deleted'], name='wr_enabled_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(repeat_interval__gte=1),
                name='ck_reminder_interval_gte1',
            ),
        ]


class ReminderLog(models.Model, ModelMixin):
    """提醒事项发送/确认记录（tdyw_reminder_logs）

    每条记录 = 某规则在某天对某用户的一次提醒。
    唯一约束 (reminder_id, user_id, date_key) 保证同一天不重复发送。
    is_acked=True 表示用户已点击"我去写了"。
    """
    reminder = models.ForeignKey(
        Reminder, models.CASCADE, related_name='logs', help_text='关联提醒规则'
    )
    user_id = models.IntegerField(help_text='接收人ID')
    user_name = models.CharField(max_length=100, default='', help_text='接收人姓名快照')
    date_key = models.CharField(max_length=10, help_text='日期标识，格式 2026-08-03')

    is_acked = models.BooleanField(default=False, help_text='是否已确认')
    acked_at = models.DateTimeField(null=True, blank=True, help_text='确认时间')

    sent_at = models.DateTimeField(auto_now_add=True, help_text='发送时间')

    def to_view(self):
        return {
            'id': self.id,
            'reminder_id': self.reminder_id,
            'reminder_name': self.reminder.name if self.reminder_id else '',
            'content': self.reminder.content if self.reminder_id else '',
            'user_id': self.user_id,
            'user_name': self.user_name,
            'date_key': self.date_key,
            'is_acked': self.is_acked,
            'acked_at': self.acked_at,
            'sent_at': self.sent_at,
        }

    def __repr__(self):
        return '<ReminderLog %s/%s/%s>' % (self.reminder_id, self.user_id, self.date_key)

    class Meta:
        db_table = 'tdyw_reminder_logs'
        verbose_name = '提醒事项记录'
        verbose_name_plural = '提醒事项记录'
        ordering = ('-sent_at',)
        constraints = [
            models.UniqueConstraint(
                fields=['reminder_id', 'user_id', 'date_key'],
                name='uniq_reminder_log',
            ),
            models.CheckConstraint(
                check=models.Q(is_acked=False) | models.Q(acked_at__isnull=False),
                name='ck_reminder_log_acked_at',
            ),
        ]
        indexes = [
            models.Index(fields=['user_id', 'is_acked'], name='wr_log_user_idx'),
            models.Index(fields=['date_key', 'user_id'], name='wr_log_date_idx'),
        ]

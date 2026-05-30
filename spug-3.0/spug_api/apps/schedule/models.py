# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from libs import human_datetime
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
from apps.account.models import User
import json
import logging

logger = logging.getLogger(__name__)


class ScheduleStaff(models.Model, TenantModelMixin):
    """排班人员"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    user_id = models.IntegerField()
    user_id = models.IntegerField()
    user_name = models.CharField(max_length=100)
    department = models.CharField(max_length=100, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    unavailable_dates = models.TextField(default='[]', help_text='JSON数组，不可值班日期列表')
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<ScheduleStaff %r>' % self.user_name

    def to_view(self):
        tmp = self.to_dict()
        try:
            tmp['unavailable_dates'] = json.loads(self.unavailable_dates) if self.unavailable_dates else []
        except (json.JSONDecodeError, TypeError, AttributeError):
            tmp['unavailable_dates'] = []
            logger.warning(f'排班人员{self.id}的unavailable_dates字段JSON格式错误，已置空 | 时间：{self.updated_at or self.created_at}')
        return tmp

    class Meta:
        db_table = 'tdyw_schedule_staff'
        verbose_name = '排班人员'
        verbose_name_plural = '排班人员'
        ordering = ('-id',)
        # P1-3: 添加索引优化查询性能
        indexes = [
            models.Index(fields=['tenant_id', 'is_active'], name='idx_staff_tnt_active'),
            models.Index(fields=['user_id'], name='idx_staff_user'),
        ]


class ScheduleShift(models.Model, TenantModelMixin):
    """班次规则"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    name = models.CharField(max_length=100)
    work_days = models.IntegerField(null=True, blank=True, help_text='工作天数')
    rest_days = models.IntegerField(null=True, blank=True, help_text='休息天数')
    shift_type = models.CharField(max_length=50, help_text='班次类型: work_rest(上X休Y), custom(自定义)')
    description = models.TextField(null=True, blank=True)
    color = models.CharField(max_length=20, null=True, blank=True, help_text='颜色标记')
    is_default = models.BooleanField(default=False)
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<ScheduleShift %r>' % self.name

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_schedule_shift'
        verbose_name = '班次规则'
        verbose_name_plural = '班次规则'
        ordering = ('-id',)
        # P1-3: 添加索引优化查询性能
        indexes = [
            models.Index(fields=['tenant_id'], name='idx_shift_tnt'),
            models.Index(fields=['is_default'], name='idx_shift_default'),
        ]


class ScheduleShiftTime(models.Model, TenantModelMixin):
    """班次时间配置"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    shift_id = models.IntegerField()
    shift_name = models.CharField(max_length=100)
    start_time = models.CharField(max_length=20)
    end_time = models.CharField(max_length=20)
    color = models.CharField(max_length=20, null=True, blank=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<ScheduleShiftTime %r>' % self.shift_name

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_schedule_shift_time'
        verbose_name = '班次时间配置'
        verbose_name_plural = '班次时间配置'
        ordering = ('sort_order', 'id',)
        # P1-3: 添加索引优化查询性能
        indexes = [
            models.Index(fields=['tenant_id', 'shift_id'], name='idx_st_tnt_shift'),
            models.Index(fields=['shift_id'], name='idx_st_shift'),
        ]


class Schedule(models.Model, TenantModelMixin):
    """排班表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    staff_id = models.IntegerField()
    staff_name = models.CharField(max_length=100)
    schedule_date = models.CharField(max_length=20)
    shift_id = models.IntegerField()
    shift_name = models.CharField(max_length=100)
    shift_time_id = models.IntegerField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<Schedule %r> %r>' % (self.staff_name, self.schedule_date)

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_schedule'
        verbose_name = '排班表'
        verbose_name_plural = '排班表'
        ordering = ('schedule_date', 'id',)
        # P1-3: 添加复合索引优化查询性能
        indexes = [
            models.Index(fields=['tenant_id', 'schedule_date', 'staff_id'], name='idx_sched_tnt_date_staff'),
            models.Index(fields=['schedule_date', 'staff_id'], name='idx_sched_date_staff'),
            models.Index(fields=['staff_id'], name='idx_sched_staff'),
        ]


class ScheduleSwap(models.Model, TenantModelMixin):
    """换班记录"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    from_staff_id = models.IntegerField()
    from_staff_name = models.CharField(max_length=100)
    to_staff_id = models.IntegerField()
    to_staff_name = models.CharField(max_length=100)
    from_date = models.CharField(max_length=20, help_text='申请人换班日期')
    to_date = models.CharField(max_length=20, help_text='被换人换班日期')
    schedule_date = models.CharField(max_length=20, null=True, blank=True, help_text='兼容旧字段')
    from_shift_id = models.IntegerField()
    from_shift_name = models.CharField(max_length=100)
    to_shift_id = models.IntegerField()
    to_shift_name = models.CharField(max_length=100)
    reason = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, default='pending', help_text='pending待审批, approved已通过, rejected已拒绝, cancelled已取消')
    approved_by = models.ForeignKey(User, models.SET_NULL, related_name='+', null=True, blank=True)
    approved_by_name = models.CharField(max_length=100, null=True, blank=True)
    approved_at = models.CharField(max_length=20, null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<ScheduleSwap %r>' % f'{self.from_staff_name} <-> {self.to_staff_name}'

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_schedule_swap'
        verbose_name = '换班记录'
        verbose_name_plural = '换班记录'
        ordering = ('-created_at', '-id',)
        # P1-3: 添加复合索引优化查询性能
        indexes = [
            models.Index(fields=['tenant_id', 'from_date', 'to_date'], name='idx_swap_tnt_dates'),
            models.Index(fields=['from_staff_id', 'to_staff_id'], name='idx_swap_staffs'),
            models.Index(fields=['status'], name='idx_swap_status'),
            models.Index(fields=['from_date', 'to_date'], name='idx_swap_dates'),
        ]


class ScheduleSubstitute(models.Model, TenantModelMixin):
    """替班记录"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    original_staff_id = models.IntegerField()
    original_staff_name = models.CharField(max_length=100)
    substitute_staff_id = models.IntegerField()
    substitute_staff_name = models.CharField(max_length=100)
    schedule_date = models.CharField(max_length=20)
    shift_id = models.IntegerField()
    shift_name = models.CharField(max_length=100)
    reason = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, default='pending', help_text='pending待审批, approved已通过, rejected已拒绝, cancelled已取消')
    approved_by = models.ForeignKey(User, models.SET_NULL, related_name='+', null=True, blank=True)
    approved_by_name = models.CharField(max_length=100, null=True, blank=True)
    approved_at = models.CharField(max_length=20, null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<ScheduleSubstitute %r>' % f'{self.substitute_staff_name} 替 {self.original_staff_name}'

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_schedule_substitute'
        verbose_name = '替班记录'
        verbose_name_plural = '替班记录'
        ordering = ('-created_at', '-id',)
        # P1-3: 添加复合索引优化查询性能
        indexes = [
            models.Index(fields=['tenant_id', 'schedule_date', 'status'], name='idx_sub_tnt_date_stat'),
            models.Index(fields=['original_staff_id', 'substitute_staff_id'], name='idx_sub_staffs'),
            models.Index(fields=['schedule_date'], name='idx_sub_date'),
            models.Index(fields=['status'], name='idx_sub_status'),
        ]

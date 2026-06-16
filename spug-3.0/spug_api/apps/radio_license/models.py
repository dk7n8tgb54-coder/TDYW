# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from libs import human_datetime
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
from apps.account.models import User


class RadioLicense(models.Model, TenantModelMixin):
    """无线电台执照主表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    # ---- 业务字段 ----
    station_name = models.CharField(max_length=100, help_text='台站名称')
    purpose = models.CharField(max_length=500, default='', help_text='用途')
    valid_from = models.DateField(help_text='起始日期')
    valid_to = models.DateField(help_text='截止日期')
    responsible_user_id = models.IntegerField(null=True, help_text='责任人ID')
    responsible_user_name = models.CharField(max_length=100, default='', help_text='责任人姓名')
    status = models.CharField(max_length=20, default='normal', help_text='状态: normal/expiring/expired')
    last_remind_at = models.CharField(max_length=20, null=True, help_text='最近提醒时间')

    # ---- 通用字段 ----
    is_deleted = models.BooleanField(default=False, help_text='是否已删除')
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<RadioLicense %r>' % self.station_name

    def to_view(self):
        return self.to_dict(excludes=('is_deleted',))

    class Meta:
        db_table = 'tdyw_radio_license'
        verbose_name = '无线电台执照'
        verbose_name_plural = '无线电台执照'
        ordering = ('-created_at', '-id')
        indexes = [
            models.Index(fields=['tenant_id', '-created_at', '-id']),
            models.Index(fields=['tenant_id', 'valid_to']),
        ]


class RadioLicenseFrequency(models.Model, TenantModelMixin):
    """无线电台执照频率明细表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    # ---- 业务字段 ----
    license = models.ForeignKey(RadioLicense, models.CASCADE, related_name='frequencies', help_text='执照')
    frequency_value = models.DecimalField(max_digits=12, decimal_places=4, help_text='频率数值')
    frequency_unit = models.CharField(max_length=20, default='MHz', help_text='频率单位: MHz/kHz/GHz')
    frequency_text = models.CharField(max_length=100, default='', help_text='原始显示文本')
    remark = models.CharField(max_length=200, default='', help_text='备注')
    sort_order = models.IntegerField(default=0, help_text='排序')

    # ---- 通用字段 ----
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')

    def __repr__(self):
        return '<RadioLicenseFrequency %s %s>' % (self.frequency_value, self.frequency_unit)

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_radio_license_frequency'
        verbose_name = '执照频率明细'
        verbose_name_plural = '执照频率明细'
        ordering = ('license', 'sort_order', 'id')
        indexes = [
            models.Index(fields=['tenant_id', 'license']),
        ]

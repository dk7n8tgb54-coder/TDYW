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
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<RadioLicense %r>' % self.station_name

    def to_view(self):
        return self.to_dict()

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


# ==================== 提醒相关常量 ====================

# 提醒级别：剩余天数 -> 提醒类型映射
REMIND_LEVELS = {
    45: 'expiring_45',
    30: 'expiring_30',
    15: 'expiring_15',
    7: 'expiring_7',
    1: 'expiring_1',
}

# 已过期提醒类型
EXPIRED_REMIND_TYPE = 'expired'

# 提醒类型中文映射
REMIND_TYPE_MAP = {
    'expiring_45': '即将到期（45天）',
    'expiring_30': '即将到期（30天）',
    'expiring_15': '即将到期（15天）',
    'expiring_7': '即将到期（7天）',
    'expiring_1': '即将到期（1天）',
    'expired': '已过期',
}


class RadioLicenseReminder(models.Model, TenantModelMixin):
    """无线电台执照提醒记录表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    # ---- 业务字段 ----
    license = models.ForeignKey(RadioLicense, models.CASCADE, related_name='reminders', help_text='执照')
    remind_type = models.CharField(max_length=30, help_text='提醒类型: expiring_45/expiring_30/.../expired')
    remind_date = models.DateField(help_text='提醒日期')
    days_left = models.IntegerField(help_text='剩余天数')
    title = models.CharField(max_length=200, help_text='标题')
    content = models.TextField(default='', help_text='内容')
    receiver_user_id = models.IntegerField(help_text='接收人ID')
    receiver_user_name = models.CharField(max_length=100, default='', help_text='接收人姓名')
    is_read = models.BooleanField(default=False, help_text='是否已读')
    is_handled = models.BooleanField(default=False, help_text='是否已处理')

    # ---- 通用字段 ----
    created_at = models.CharField(max_length=20, default=human_datetime)

    def __repr__(self):
        return '<RadioLicenseReminder %s %s>' % (self.remind_type, self.title)

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_radio_license_reminder'
        verbose_name = '执照提醒'
        verbose_name_plural = '执照提醒'
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['tenant_id', 'license']),
            models.Index(fields=['tenant_id', 'receiver_user_id', 'is_read']),
            # 去重索引：同一执照 + 同一提醒类型 + 同一截止日期周期 + 同一接收人
            models.Index(fields=['tenant_id', 'license', 'remind_type', 'receiver_user_id']),
        ]


ATTACHMENT_TYPE_CHOICES = (
    ('license', '执照'),
    ('permit', '许可证'),
    ('approval', '许可批复'),
    ('other', '其他'),
)

# 允许上传的文件扩展名
ALLOWED_FILE_EXTENSIONS = [
    '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.zip', '.rar', '.7z',
]

# 最大文件大小（MB）
MAX_FILE_SIZE_MB = 50


class RadioLicenseAttachment(models.Model, TenantModelMixin):
    """无线电台执照附件表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    # ---- 业务字段 ----
    license = models.ForeignKey(RadioLicense, models.CASCADE, related_name='attachments', help_text='执照')
    attachment_type = models.CharField(max_length=30, choices=ATTACHMENT_TYPE_CHOICES, default='other', help_text='附件类型')
    file_name = models.CharField(max_length=255, help_text='原始文件名')
    file_path = models.CharField(max_length=500, help_text='存储路径')
    file_size = models.BigIntegerField(default=0, help_text='文件大小(字节)')
    file_ext = models.CharField(max_length=20, default='', help_text='文件扩展名')

    # ---- 通用字段 ----
    created_at = models.CharField(max_length=20, default=human_datetime)
    uploaded_by = models.ForeignKey(User, models.PROTECT, related_name='+', help_text='上传人')

    def __repr__(self):
        return '<RadioLicenseAttachment %s>' % self.file_name

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_radio_license_attachment'
        verbose_name = '执照附件'
        verbose_name_plural = '执照附件'
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['tenant_id', 'license']),
        ]

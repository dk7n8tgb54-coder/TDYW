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

# 即将到期天数阈值：到期前 60 天内即为"即将到期"
EXPIRING_DAYS_THRESHOLD = 60

# 当前使用的提醒类型
EXPIRING_DAILY_REMIND_TYPE = 'expiring_daily'   # 即将到期每日提醒（0 <= days_left <= 60）
EXPIRED_REMIND_TYPE = 'expired'                  # 已过期提醒（days_left < 0）

# 历史分级提醒类型映射（仅用于历史数据展示/兼容，新生成提醒不再使用）
REMIND_LEVELS = {
    45: 'expiring_45',
    30: 'expiring_30',
    15: 'expiring_15',
    7: 'expiring_7',
    1: 'expiring_1',
}

# 提醒类型中文映射（含历史类型，保证旧数据在前端能正确显示）
REMIND_TYPE_MAP = {
    # 新版（每日提醒）
    'expiring_daily': '即将到期',
    'expired': '已过期',
    # 兼容旧版分级提醒（历史数据）
    'expiring_45': '即将到期（45天）',
    'expiring_30': '即将到期（30天）',
    'expiring_15': '即将到期（15天）',
    'expiring_7': '即将到期（7天）',
    'expiring_1': '即将到期（1天）',
}


class RadioLicenseReminder(models.Model, TenantModelMixin):
    """无线电台执照提醒记录表（历史日志，只增不改）

    重构说明（2026-06-23 执照中心模型）：
    - 本表降级为"通知历史日志"，仅供提醒记录页查阅历史
    - 弹窗判断、days_left、"已处理"状态全部迁移到 LicenseReminderAck
    - 不再由定时任务预生成（tasks.scan_single_license 只更新 license.status）
    - 保留旧数据供审计，新数据由编辑执照时的即时扫描按需写入

    字段 days_left / content 为生成时快照，不保证实时，展示时需重新计算。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    # ---- 业务字段 ----
    license = models.ForeignKey(RadioLicense, models.CASCADE, related_name='reminders', help_text='执照')
    remind_type = models.CharField(max_length=30, help_text='提醒类型: expiring_daily/expired（历史含 expiring_45/30/15/7/1）')
    remind_date = models.DateField(help_text='提醒日期')
    days_left = models.IntegerField(help_text='剩余天数（生成时快照，非实时）')
    title = models.CharField(max_length=200, help_text='标题')
    content = models.TextField(default='', help_text='内容（生成时快照，非实时）')
    receiver_user_id = models.IntegerField(help_text='接收人ID')
    receiver_user_name = models.CharField(max_length=100, default='', help_text='接收人姓名')
    is_read = models.BooleanField(default=False, help_text='是否已读')
    is_handled = models.BooleanField(default=False, help_text='是否已处理（历史字段，新逻辑用 LicenseReminderAck）')

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


class LicenseReminderAck(models.Model, TenantModelMixin):
    """执照提醒"已处理"确认记录（执照中心模型核心表）

    设计原则：
    - 派生数据不存储：days_left/content 不在此表，弹窗实时算
    - 状态与事件分离：此表是"用户确认状态"，RadioLicenseReminder 是"通知事件日志"
    - 续期失效靠数据本身：ack_valid_to 记录确认时的 valid_to，
      license.valid_to 变化（续期）后 ack 自动失效，无需手动作废

    弹窗判断逻辑（ReminderPopupView）：
        license.status IN (expiring, expired)
        AND NOT EXISTS ack WHERE license_id=X AND user_id=Y AND ack_valid_to=license.valid_to

    用户点"已处理"→ 写一条 ack（license_id + user_id + ack_valid_to=license.valid_to）
    用户续期（valid_to 变）→ 旧 ack 的 ack_valid_to != 新 valid_to → 自动失效 → 重新弹窗
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    # ---- 业务字段 ----
    license = models.ForeignKey(RadioLicense, models.CASCADE, related_name='reminder_acks', help_text='执照')
    user_id = models.IntegerField(help_text='确认处理的用户ID')
    user_name = models.CharField(max_length=100, default='', help_text='确认处理的用户姓名')
    ack_valid_to = models.DateField(help_text='确认时执照的截止日期（用于续期后自动失效）')

    # ---- 通用字段 ----
    created_at = models.CharField(max_length=20, default=human_datetime)

    def __repr__(self):
        return '<LicenseReminderAck license=%s user=%s valid_to=%s>' % (self.license_id, self.user_id, self.ack_valid_to)

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_radio_license_reminder_ack'
        verbose_name = '执照提醒确认'
        verbose_name_plural = '执照提醒确认'
        ordering = ('-created_at',)
        indexes = [
            # 弹窗查询主索引：按用户查未失效的 ack
            models.Index(fields=['tenant_id', 'user_id', 'license'], name='tdyw_rlra_user_idx'),
        ]
        constraints = [
            # 唯一约束：同一用户对同一执照同一 valid_to 周期只确认一次
            models.UniqueConstraint(
                fields=['tenant_id', 'license_id', 'user_id', 'ack_valid_to'],
                name='uniq_license_user_valid_to',
            ),
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

    # ==== 证据闭环第三阶段：附件哈希 + 软删除 ====
    file_hash_sha256 = models.CharField(max_length=64, default='', db_index=True, help_text='文件 SHA256')
    file_hash_md5 = models.CharField(max_length=32, default='', help_text='文件 MD5（兼容旧系统）')
    uploaded_by_name = models.CharField(max_length=100, default='', help_text='上传人姓名快照')
    is_deleted = models.BooleanField(default=False, help_text='是否已删除（软删除）')
    deleted_by_id = models.IntegerField(null=True, blank=True, help_text='删除人账号 ID')
    deleted_by_name = models.CharField(max_length=100, default='', help_text='删除人姓名快照')
    deleted_at = models.CharField(max_length=20, null=True, blank=True, help_text='删除时间')
    delete_reason = models.CharField(max_length=500, default='', blank=True, help_text='删除原因')

    # ---- 通用字段 ----
    created_at = models.CharField(max_length=20, default=human_datetime)
    uploaded_by = models.ForeignKey(User, models.PROTECT, related_name='+', help_text='上传人')

    def __repr__(self):
        return '<RadioLicenseAttachment %s>' % self.file_name

    def to_view(self):
        tmp = self.to_dict(excludes=('is_deleted',))
        return tmp

    class Meta:
        db_table = 'tdyw_radio_license_attachment'
        verbose_name = '执照附件'
        verbose_name_plural = '执照附件'
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['tenant_id', 'license']),
            models.Index(fields=['file_hash_sha256'], name='rl_att_sha256_idx'),
        ]


# ==================== 证据闭环第三阶段：执照版本历史 ====================

class RadioLicenseVersion(models.Model, TenantModelMixin):
    """无线电台执照版本历史表（每次修改核心字段前保存修改前快照）

    设计原则：
    - 修改执照核心字段前先保存修改前版本
    - 版本号按执照递增
    - snapshot_json 包含修改前完整字段
    - snapshot_hash 用于证明快照未被篡改
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    # ---- 业务字段 ----
    license = models.ForeignKey(RadioLicense, models.CASCADE, related_name='versions', help_text='执照')
    version_no = models.IntegerField(help_text='版本号（按执照递增）')
    snapshot_json = models.TextField(help_text='修改前完整字段快照 JSON')
    changed_fields = models.TextField(default='', help_text='本次变更字段列表（逗号分隔）')
    change_reason = models.CharField(max_length=500, default='', blank=True, help_text='变更原因')

    # ---- 修改人身份快照 ----
    changed_by_id = models.IntegerField(null=True, blank=True, help_text='修改人账号 ID')
    changed_by_name = models.CharField(max_length=100, default='', help_text='修改人姓名快照')
    changed_at = models.CharField(max_length=20, help_text='修改时间')

    # ---- 快照哈希 ----
    snapshot_hash = models.CharField(max_length=64, default='', help_text='快照哈希(SHA256)')

    def __repr__(self):
        return '<RadioLicenseVersion license=%s v=%s>' % (self.license_id, self.version_no)

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_radio_license_version'
        verbose_name = '执照版本'
        verbose_name_plural = '执照版本'
        ordering = ('-version_no', '-id')
        indexes = [
            models.Index(fields=['tenant_id', 'license'], name='rl_ver_license_idx'),
        ]

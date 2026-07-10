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

# 当前弹窗提醒类型
EXPIRING_DAILY_REMIND_TYPE = 'expiring_daily'   # 即将到期每日提醒（0 <= days_left <= 60）
EXPIRED_REMIND_TYPE = 'expired'                  # 已过期提醒（days_left < 0）


class LicenseReminderAck(models.Model, TenantModelMixin):
    """执照提醒"已处理"确认记录（执照中心模型核心表）

    设计原则：
    - 派生数据不存储：days_left/content 不在此表，弹窗实时算
    - 此表只保存"用户确认状态"，不保存提醒历史日志
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

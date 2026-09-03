# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models

from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
from apps.account.models import User


class ContractAgreement(models.Model, TenantModelMixin):
    """合同协议主表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    TYPE_DEVICE_PURCHASE = 'device_purchase'
    TYPE_INFO_ACCESS = 'info_access'
    TYPE_SERVICE_GUARANTEE = 'service_guarantee'

    CONTRACT_TYPE_CHOICES = (
        (TYPE_DEVICE_PURCHASE, '设备采购合同'),
        (TYPE_INFO_ACCESS, '信息引接合同'),
        (TYPE_SERVICE_GUARANTEE, '服务保障协议'),
    )

    STATUS_NORMAL = 'normal'
    STATUS_EXPIRING = 'expiring'
    STATUS_EXPIRED = 'expired'
    STATUS_CHOICES = (
        (STATUS_NORMAL, '正常'),
        (STATUS_EXPIRING, '即将到期'),
        (STATUS_EXPIRED, '已关闭'),
    )

    # ---- 业务字段 ----
    contract_name = models.CharField(max_length=200, help_text='合同名称')
    contract_no = models.CharField(max_length=100, default='', blank=True, help_text='合同编号')
    contract_type = models.CharField(max_length=30, choices=CONTRACT_TYPE_CHOICES, help_text='类型')
    valid_start_date = models.DateField(help_text='起始日期')
    valid_end_date = models.DateField(help_text='截止日期')
    has_fee = models.BooleanField(default=False, help_text='是否有费用')
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text='费用金额')
    fee_currency = models.CharField(max_length=10, default='人民币', help_text='币种')
    fee_detail = models.TextField(default='', blank=True, help_text='费用详细数据')
    signing_party = models.CharField(max_length=500, help_text='签约方')
    responsible_user_id = models.IntegerField(null=True, help_text='责任人ID')
    responsible_user_name = models.CharField(max_length=100, default='', help_text='责任人姓名')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_NORMAL,
        help_text='状态: normal/expiring/expired（expired 显示为已关闭）',
    )
    remark = models.TextField(default='', blank=True, help_text='备注')
    last_remind_at = models.DateTimeField(null=True, blank=True, help_text='最近提醒扫描时间')

    # ---- 通用字段 ----
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True)

    def __repr__(self):
        return '<ContractAgreement %r>' % self.contract_name

    def to_view(self):
        return self.to_dict()

    @property
    def contract_type_display(self):
        return dict(self.CONTRACT_TYPE_CHOICES).get(self.contract_type, self.contract_type)

    class Meta:
        db_table = 'tdyw_contract_agreement'
        verbose_name = '合同协议'
        verbose_name_plural = '合同协议'
        ordering = ('-created_at', '-id')
        indexes = [
            models.Index(fields=['tenant_id', '-created_at', '-id'], name='tdyw_contra_tenant_8811a0_idx'),
            models.Index(fields=['tenant_id', 'contract_type'], name='tdyw_contra_tenant_f8adba_idx'),
            models.Index(fields=['tenant_id', 'status'], name='tdyw_contra_tenant_1880dc_idx'),
            models.Index(fields=['tenant_id', 'valid_end_date'], name='tdyw_contra_tenant_f97a10_idx'),
            models.Index(fields=['tenant_id', 'has_fee'], name='tdyw_contra_tenant_a34e30_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(contract_type__in=['device_purchase', 'info_access', 'service_guarantee']),
                name='contract_type_valid',
            ),
            models.CheckConstraint(
                check=models.Q(status__in=['normal', 'expiring', 'expired']),
                name='contract_status_valid',
            ),
            models.CheckConstraint(
                check=models.Q(valid_end_date__gte=models.F('valid_start_date')),
                name='contract_date_order_valid',
            ),
            models.CheckConstraint(
                check=(
                    models.Q(has_fee=False) |
                    models.Q(fee_amount__isnull=False, fee_amount__gte=0)
                ),
                name='contract_fee_valid',
            ),
        ]


EXPIRING_DAYS_THRESHOLD = 60


class ContractAgreementReminderAck(models.Model, TenantModelMixin):
    """合同协议到期提醒确认记录"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    agreement = models.ForeignKey(
        ContractAgreement, models.CASCADE, related_name='reminder_acks', help_text='合同协议')
    user_id = models.IntegerField(help_text='确认处理的用户ID')
    user_name = models.CharField(max_length=100, default='', help_text='确认处理的用户名称')
    ack_valid_to = models.DateField(help_text='确认时合同的截止日期（用于续期后自动失效）')
    created_at = models.DateTimeField(auto_now_add=True)

    def __repr__(self):
        return '<ContractAgreementReminderAck agreement=%s user=%s valid_to=%s>' % (
            self.agreement_id, self.user_id, self.ack_valid_to)

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_contract_agreement_reminder_ack'
        verbose_name = '合同协议提醒确认'
        verbose_name_plural = '合同协议提醒确认'
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['tenant_id', 'user_id', 'agreement'], name='tdyw_cara_user_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'agreement_id', 'user_id', 'ack_valid_to'],
                name='uniq_contract_user_valid_end',
            ),
        ]

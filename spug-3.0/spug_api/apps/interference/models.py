# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
from apps.account.models import User
import logging

logger = logging.getLogger(__name__)


# 干扰记录状态（保留 choices 供 to_view/约束使用；状态流转功能已移除）
INTERFERENCE_STATUS_CHOICES = (
    ('draft', '草稿'),
    ('submitted', '已提交'),
    ('reviewed', '已复核'),
    ('reported', '已上报'),
    ('handled', '已处置'),
    ('closed', '已关闭'),
    ('voided', '已作废'),
)


class Interference(models.Model, TenantModelMixin):
    """干扰记录表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    serial_number = models.IntegerField(default=0)
    frequency = models.CharField(max_length=100)
    report_dept = models.CharField(max_length=100)
    datetime = models.DateTimeField(null=True, blank=True)
    coordinates = models.CharField(max_length=200)
    interference_type = models.CharField(max_length=100)
    phenomenon = models.TextField()
    flight_number = models.CharField(max_length=100, null=True, blank=True)
    aircraft_type = models.CharField(max_length=100, null=True, blank=True)
    is_reported = models.CharField(max_length=10, default='否')

    # ==== 证据闭环第三阶段：状态流转 ====
    status = models.CharField(
        max_length=20, choices=INTERFERENCE_STATUS_CHOICES, default='draft',
        help_text='状态：draft/submitted/reviewed/reported/handled/closed/voided')
    # 提交人身份快照
    submitted_by_id = models.IntegerField(null=True, blank=True, help_text='提交人账号ID')
    submitted_by_name = models.CharField(max_length=100, default='', help_text='提交人姓名快照')
    submitted_at = models.DateTimeField(null=True, blank=True, help_text='提交时间')
    # 复核
    reviewed_by_id = models.IntegerField(null=True, blank=True, help_text='复核人账号ID')
    reviewed_by_name = models.CharField(max_length=100, default='', help_text='复核人姓名快照')
    reviewed_at = models.DateTimeField(null=True, blank=True, help_text='复核时间')
    review_comment = models.TextField(null=True, blank=True, help_text='复核意见')
    # 上报（替代 is_reported 的结构化字段，保留 is_reported 兼容旧数据）
    reported_at = models.DateTimeField(null=True, blank=True, help_text='上报时间')
    reported_by_id = models.IntegerField(null=True, blank=True, help_text='上报人账号ID')
    reported_by_name = models.CharField(max_length=100, default='', help_text='上报人姓名快照')
    report_channel = models.CharField(max_length=100, default='', blank=True, help_text='上报渠道')
    report_no = models.CharField(max_length=100, default='', blank=True, help_text='上报编号')
    # 处置
    handled_by_id = models.IntegerField(null=True, blank=True, help_text='处置人账号ID')
    handled_by_name = models.CharField(max_length=100, default='', help_text='处置人姓名快照')
    handled_at = models.DateTimeField(null=True, blank=True, help_text='处置时间')
    # 关闭
    closed_by_id = models.IntegerField(null=True, blank=True, help_text='关闭人账号ID')
    closed_by_name = models.CharField(max_length=100, default='', help_text='关闭人姓名快照')
    closed_at = models.DateTimeField(null=True, blank=True, help_text='关闭时间')
    close_summary = models.TextField(null=True, blank=True, help_text='关闭总结')
    # 作废
    voided_by_id = models.IntegerField(null=True, blank=True, help_text='作废人账号ID')
    voided_by_name = models.CharField(max_length=100, default='', help_text='作废人姓名快照')
    voided_at = models.DateTimeField(null=True, blank=True, help_text='作废时间')
    void_reason = models.CharField(max_length=500, default='', blank=True, help_text='作废原因')
    # 快照哈希（提交时计算，证明提交后未被篡改）
    snapshot_hash = models.CharField(max_length=64, default='', help_text='提交快照哈希(SHA256)')

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<Interference %r>' % self.frequency

    def to_view(self):
        tmp = self.to_dict()
        # 附加状态文本
        status_map = dict(INTERFERENCE_STATUS_CHOICES)
        tmp['status_text'] = status_map.get(self.status, self.status)
        return tmp

    class Meta:
        db_table = 'tdyw_interferences'
        verbose_name = '干扰记录'
        verbose_name_plural = '干扰记录'
        ordering = ('serial_number', '-datetime', '-id',)
        indexes = [
            models.Index(fields=['tenant_id', 'status'], name='inter_status_idx'),
            models.Index(fields=['tenant_id', '-datetime', '-id'], name='inter_time_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(status__in=[item[0] for item in INTERFERENCE_STATUS_CHOICES]),
                name='interference_status_valid',
            ),
            models.CheckConstraint(
                check=(
                    models.Q(status='draft') |
                    models.Q(status='voided') |
                    (
                        models.Q(submitted_by_id__isnull=False) &
                        models.Q(submitted_at__isnull=False) &
                        ~models.Q(submitted_by_name='') &
                        ~models.Q(snapshot_hash='')
                    )
                ),
                name='interference_submit_fields',
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(status__in=['reviewed', 'reported', 'handled', 'closed']) |
                    (
                        models.Q(reviewed_by_id__isnull=False) &
                        models.Q(reviewed_at__isnull=False) &
                        ~models.Q(reviewed_by_name='')
                    )
                ),
                name='interference_review_fields',
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(status__in=['reported', 'handled', 'closed']) |
                    (
                        models.Q(reported_by_id__isnull=False) &
                        models.Q(reported_at__isnull=False) &
                        ~models.Q(reported_by_name='')
                    )
                ),
                name='interference_report_fields',
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(status__in=['handled', 'closed']) |
                    (
                        models.Q(handled_by_id__isnull=False) &
                        models.Q(handled_at__isnull=False) &
                        ~models.Q(handled_by_name='')
                    )
                ),
                name='interference_handle_fields',
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(status='closed') |
                    (
                        models.Q(closed_by_id__isnull=False) &
                        models.Q(closed_at__isnull=False) &
                        ~models.Q(closed_by_name='') &
                        ~models.Q(close_summary__isnull=True) &
                        ~models.Q(close_summary='')
                    )
                ),
                name='interference_close_fields',
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(status='voided') |
                    (
                        models.Q(voided_by_id__isnull=False) &
                        models.Q(voided_at__isnull=False) &
                        ~models.Q(voided_by_name='') &
                        ~models.Q(void_reason='')
                    )
                ),
                name='interference_void_fields',
            ),
        ]

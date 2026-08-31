# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from decimal import Decimal

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

# ==== 双业务类型：告警高度 / 持续时间单位定义 ====
# 不做任何数值换算：保存用户录入的原始数值，并在 UI/导出/详情中显式标注单位。
ALTITUDE_UNIT_CHOICES = (
    ('m', '米'),
    ('ft', '英尺'),
)
ALTITUDE_UNIT_TEXT = dict(ALTITUDE_UNIT_CHOICES)

DURATION_UNIT_CHOICES = (
    ('s', '秒'),
    ('min', '分钟'),
    ('h', '小时'),
)
DURATION_UNIT_TEXT = dict(DURATION_UNIT_CHOICES)


def format_decimal(value):
    """格式化 Decimal：去掉多余的尾随 0（1200.00 -> 1200），None 返回空串。"""
    if value is None:
        return ''
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    normalized = format(value, 'f')
    if '.' in normalized:
        normalized = normalized.rstrip('0').rstrip('.')
    return normalized or '0'


class Interference(models.Model, TenantModelMixin):
    """干扰记录表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    serial_number = models.IntegerField(default=0)
    frequency = models.CharField(max_length=100)
    report_dept = models.CharField(max_length=100)
    datetime = models.DateTimeField(null=False, blank=False)
    coordinates = models.CharField(max_length=200)
    interference_type = models.CharField(max_length=100)
    phenomenon = models.TextField()
    flight_number = models.CharField(max_length=100, blank=True, default='')
    aircraft_type = models.CharField(max_length=100, blank=True, default='')
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
    review_comment = models.TextField(blank=True, help_text='复核意见', default='')
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
    close_summary = models.TextField(blank=True, help_text='关闭总结', default='')
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
    is_deleted = models.BooleanField(default=False, help_text='软删除标识')
    deleted_at = models.DateTimeField(null=True, blank=True, help_text='删除时间')

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


# ====================================================================
# 干扰管理双业务类型（2026-08 拆分）
#
# 业务边界：一条事件只能是「地面无线电通信异常/干扰」或「空中干扰」
# 之一，不存在同一事件同时具有两类详情的情况。两类业务使用独立数据表，
# 通过共享抽象基类复用租户隔离、创建/更新/软删除、审计等公共字段，
# 不使用 nullable 字段构造万能表。
#
# 业务定位：纯记录型台账，无状态流转；处置方式/原因分析为普通选填字段。
#
# 历史兼容：旧 Interference 模型与 tdyw_interferences 表原样保留，
# 历史数据不做自动归类，可通过人工甄别后另行迁移。
# ====================================================================


class InterferenceBusinessBase(models.Model, TenantModelMixin):
    """干扰管理双业务类型共享抽象基类。

    仅包含两类业务共同拥有的字段（日期时间/航班号/机型/现象）以及
    租户、审计、软删除字段。业务差异字段由子模型自行声明。
    """
    # 显式声明（与旧 Interference 模型一致），确保具体子类获得租户过滤 Manager
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    datetime = models.DateTimeField(null=False, blank=False, verbose_name='日期时间')
    flight_number = models.CharField(
        max_length=100, blank=True, default='', verbose_name='航班号')
    aircraft_type = models.CharField(
        max_length=100, blank=True, default='', verbose_name='机型')
    phenomenon = models.TextField(verbose_name='现象')

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)
    is_deleted = models.BooleanField(default=False, help_text='软删除标识')
    deleted_at = models.DateTimeField(null=True, blank=True, help_text='删除时间')

    class Meta:
        abstract = True


class BridgeInterferenceRecord(InterferenceBusinessBase):
    """地面无线电通信异常/干扰记录（纯记录型，无状态流转）。

    字段语义约定：
    - location（位置/机位）：廊桥/航站楼位置或具体机位编号，二者合一登记。
    """
    aircraft_no = models.CharField(
        max_length=100, blank=True, default='', verbose_name='机号')
    location = models.CharField(
        max_length=200, blank=True, default='', verbose_name='位置/机位',
        help_text='廊桥/航站楼位置或具体机位编号')
    frequency = models.CharField(
        max_length=100, blank=True, default='', verbose_name='频率')
    remark = models.TextField(blank=True, default='', verbose_name='备注')

    def __repr__(self):
        return '<BridgeInterferenceRecord %r>' % self.flight_number

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_bridge_interference_records'
        verbose_name = '地面无线电通信异常/干扰记录'
        verbose_name_plural = '地面无线电通信异常/干扰记录'
        ordering = ('-datetime', '-id')
        indexes = [
            models.Index(fields=['tenant_id', '-datetime', '-id'], name='bridge_time_idx'),
        ]


class AirInterferenceRecord(InterferenceBusinessBase):
    """空中干扰记录（纯记录型，无状态流转）。

    首次登记必填：日期时间/航班号/现象；处置方式、原因分析为选填字段，
    供后续补充，不做任何状态强制。
    """
    route = models.CharField(
        max_length=200, blank=True, default='', verbose_name='航线')
    runway = models.CharField(
        max_length=100, blank=True, default='', verbose_name='使用跑道')
    approach_procedure = models.CharField(
        max_length=100, blank=True, default='', verbose_name='使用进近程序')
    alert_form = models.CharField(
        max_length=100, blank=True, default='', verbose_name='被扰频率')
    alert_altitude = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        verbose_name='告警高度', help_text='原始录入数值，不换算；单位见 alert_altitude_unit')
    alert_altitude_unit = models.CharField(
        max_length=10, choices=ALTITUDE_UNIT_CHOICES, default='m',
        verbose_name='告警高度单位')
    alert_segment = models.CharField(
        max_length=200, blank=True, default='', verbose_name='告警航段')
    duration = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='持续时间', help_text='原始录入数值，不换算；单位见 duration_unit')
    duration_unit = models.CharField(
        max_length=10, choices=DURATION_UNIT_CHOICES, default='min',
        verbose_name='持续时间单位')
    handling_method = models.TextField(
        blank=True, default='', verbose_name='处置方式')
    cause_analysis = models.TextField(
        blank=True, default='', verbose_name='原因分析')

    def __repr__(self):
        return '<AirInterferenceRecord %r>' % self.flight_number

    @property
    def alert_altitude_text(self):
        if self.alert_altitude is None:
            return ''
        return '%s%s' % (format_decimal(self.alert_altitude),
                         ALTITUDE_UNIT_TEXT.get(self.alert_altitude_unit, self.alert_altitude_unit))

    @property
    def duration_text(self):
        if self.duration is None:
            return ''
        return '%s%s' % (format_decimal(self.duration),
                         DURATION_UNIT_TEXT.get(self.duration_unit, self.duration_unit))

    def to_view(self):
        tmp = self.to_dict()
        tmp['alert_altitude_text'] = self.alert_altitude_text
        tmp['duration_text'] = self.duration_text
        # 告警摘要：列表页扫描用（被扰频率 / 告警高度 / 告警航段）
        tmp['alert_summary'] = ' / '.join(
            part for part in (self.alert_form, self.alert_altitude_text, self.alert_segment) if part)
        # 跑道/进近程序：列表页合并展示
        tmp['runway_approach_text'] = ' / '.join(
            part for part in (self.runway, self.approach_procedure) if part)
        return tmp

    class Meta:
        db_table = 'tdyw_air_interference_records'
        verbose_name = '空中干扰记录'
        verbose_name_plural = '空中干扰记录'
        ordering = ('-datetime', '-id')
        indexes = [
            models.Index(fields=['tenant_id', '-datetime', '-id'], name='air_time_idx'),
        ]
        constraints = [
            # 告警高度/持续时间：有数值时必须携带合法单位，且数值必须为正
            models.CheckConstraint(
                check=(
                    models.Q(alert_altitude__isnull=True) |
                    ~models.Q(alert_altitude_unit='')
                ),
                name='air_interference_altitude_unit',
            ),
            models.CheckConstraint(
                check=(
                    models.Q(alert_altitude__isnull=True) |
                    models.Q(alert_altitude__gt=0)
                ),
                name='air_interference_altitude_positive',
            ),
            models.CheckConstraint(
                check=(
                    models.Q(duration__isnull=True) |
                    ~models.Q(duration_unit='')
                ),
                name='air_interference_duration_unit',
            ),
            models.CheckConstraint(
                check=(
                    models.Q(duration__isnull=True) |
                    models.Q(duration__gt=0)
                ),
                name='air_interference_duration_positive',
            ),
        ]

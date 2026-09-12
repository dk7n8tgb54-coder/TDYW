# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""干扰管理最终数据模型。

事件是事实记录，调查是可选的分析专题；两者通过关联表连接。地面和空中
专属字段分别放在共享主键明细表中，避免把两种场景拼成一张宽表。
"""

from collections import Counter
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.account.models import User
from libs.tenant_base_model import (
    TenantModelManager,
    TenantModelMixin,
    make_tenant_id,
)


SCENE_CODE_CHOICES = (
    ('ground', '地面'),
    ('air', '空中'),
    ('cross', '跨场景'),
    ('unknown', '未知'),
)
SCENE_CODE_TEXT = dict(SCENE_CODE_CHOICES)

CLASSIFICATION_STATUS_CHOICES = (
    ('pending', '待分类'),
    ('confirmed', '已确认'),
)
CLASSIFICATION_STATUS_TEXT = dict(CLASSIFICATION_STATUS_CHOICES)

INTERFERENCE_KIND_CODE_CHOICES = (
    ('noise', '杂音'),
    ('intermittent', '间歇中断'),
    ('communication_loss', '完全失联'),
    ('frequency_occupy', '频率占用'),
    ('blocking', '阻塞'),
    ('false_alarm', '虚警'),
    ('other', '其他'),
    ('unknown', '未知'),
)
INTERFERENCE_KIND_CODE_TEXT = dict(INTERFERENCE_KIND_CODE_CHOICES)

AFFECTED_SYSTEM_CODE_CHOICES = (
    ('communication', '通信'),
    ('navigation', '导航'),
    ('surveillance', '监视'),
    ('datalink', '数据链'),
    ('equipment', '设备电磁兼容'),
    ('other', '其他'),
)
AFFECTED_SYSTEM_CODE_TEXT = dict(AFFECTED_SYSTEM_CODE_CHOICES)

SOURCE_TYPE_CODE_CHOICES = (
    ('ground_equipment', '地面设备'),
    ('vehicle_power', '车辆/电源'),
    ('aircraft_equipment', '机载设备'),
    ('external_transmitter', '外部发射源'),
    ('environment', '环境'),
    ('unknown', '未知'),
)
SOURCE_TYPE_CODE_TEXT = dict(SOURCE_TYPE_CODE_CHOICES)

INVESTIGATION_STATUS_CHOICES = (
    ('draft', '草稿'),
    ('observing', '持续观察'),
    ('measuring', '测量中'),
    ('concluded', '已形成结论'),
    ('closed', '已结束'),
    ('cancelled', '已取消'),
)
INVESTIGATION_STATUS_TEXT = dict(INVESTIGATION_STATUS_CHOICES)

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
    """返回适合展示的十进制文本。"""
    if value is None:
        return ''
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    value = format(value, 'f')
    if '.' in value:
        value = value.rstrip('0').rstrip('.')
    return value or '0'


class SoftDeleteTenantModel(models.Model, TenantModelMixin):
    """需要租户隔离和软删除的干扰对象公共字段。"""

    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class InterferenceEvent(SoftDeleteTenantModel):
    """一次干扰事实事件。"""

    datetime = models.DateTimeField(verbose_name='发生时间')
    scene_code = models.CharField(
        max_length=20, choices=SCENE_CODE_CHOICES, default='unknown',
        verbose_name='发生场景')
    classification_status = models.CharField(
        max_length=20, choices=CLASSIFICATION_STATUS_CHOICES, default='pending',
        verbose_name='分类状态')
    interference_kind_code = models.CharField(
        max_length=40, choices=INTERFERENCE_KIND_CODE_CHOICES, default='unknown',
        verbose_name='具体干扰类型')
    affected_system_code = models.CharField(
        max_length=40, choices=AFFECTED_SYSTEM_CODE_CHOICES, default='other',
        verbose_name='受影响系统')
    source_type_code = models.CharField(
        max_length=40, choices=SOURCE_TYPE_CODE_CHOICES, default='unknown',
        verbose_name='疑似干扰源')
    flight_number = models.CharField(max_length=100, blank=True, default='')
    aircraft_no = models.CharField(max_length=100, blank=True, default='')
    aircraft_type = models.CharField(max_length=100, blank=True, default='')
    phenomenon = models.TextField(blank=True, default='')
    initial_assessment = models.TextField(blank=True, default='')
    remark = models.TextField(blank=True, default='')

    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        """对已确认事件校验明细边界（跨表完整性由写入服务补齐）。"""
        super().clean()
        if self.scene_code not in dict(SCENE_CODE_CHOICES):
            raise ValidationError({'scene_code': '无效的发生场景'})
        if self.classification_status not in dict(CLASSIFICATION_STATUS_CHOICES):
            raise ValidationError({'classification_status': '无效的分类状态'})
        if not self.pk or self.classification_status != 'confirmed':
            return
        ground_exists = GroundInterferenceDetail.objects.filter(
            event_id=self.pk, is_deleted=False).exists()
        air_exists = AirInterferenceDetail.objects.filter(
            event_id=self.pk, is_deleted=False).exists()
        if self.scene_code == 'ground' and (not ground_exists or air_exists):
            raise ValidationError('地面事件必须只有地面明细')
        if self.scene_code == 'air' and (not air_exists or ground_exists):
            raise ValidationError('空中事件必须只有空中明细')
        if self.scene_code == 'unknown' and (ground_exists or air_exists):
            raise ValidationError('未知场景事件不能存在专属明细')

    def to_view(self, include_details=True):
        result = {
            'id': self.id,
            'datetime': self.datetime,
            'scene_code': self.scene_code,
            'scene_text': SCENE_CODE_TEXT.get(self.scene_code, self.scene_code),
            'classification_status': self.classification_status,
            'classification_status_text': CLASSIFICATION_STATUS_TEXT.get(
                self.classification_status, self.classification_status),
            'interference_kind_code': self.interference_kind_code,
            'interference_kind_text': INTERFERENCE_KIND_CODE_TEXT.get(
                self.interference_kind_code, self.interference_kind_code),
            'affected_system_code': self.affected_system_code,
            'affected_system_text': AFFECTED_SYSTEM_CODE_TEXT.get(
                self.affected_system_code, self.affected_system_code),
            'source_type_code': self.source_type_code,
            'source_type_text': SOURCE_TYPE_CODE_TEXT.get(
                self.source_type_code, self.source_type_code),
            'flight_number': self.flight_number,
            'aircraft_no': self.aircraft_no,
            'aircraft_type': self.aircraft_type,
            'phenomenon': self.phenomenon,
            'initial_assessment': self.initial_assessment,
            'remark': self.remark,
            'created_by': self.created_by_id,
            'created_at': self.created_at,
            'updated_by': self.updated_by_id,
            'updated_at': self.updated_at,
        }
        if include_details:
            ground = GroundInterferenceDetail.objects.filter(
                event_id=self.pk, is_deleted=False).first()
            air = AirInterferenceDetail.objects.filter(
                event_id=self.pk, is_deleted=False).first()
            result['ground_detail'] = ground.to_view() if ground else None
            result['air_detail'] = air.to_view() if air else None
            result['investigation_ids'] = list(
                InvestigationEvent.objects.filter(
                    event_id=self.pk, is_deleted=False,
                    investigation__is_deleted=False,
                ).values_list('investigation_id', flat=True)
            )
        return result

    class Meta:
        db_table = 'tdyw_interference_events'
        verbose_name = '干扰事件'
        verbose_name_plural = '干扰事件'
        ordering = ('-datetime', '-id')
        indexes = [
            models.Index(fields=['tenant_id', '-datetime', '-id'],
                         name='inter_event_time_idx'),
            models.Index(fields=['tenant_id', 'scene_code'],
                         name='inter_event_scene_idx'),
            models.Index(fields=['tenant_id', 'classification_status'],
                         name='inter_event_class_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(scene_code__in=[x[0] for x in SCENE_CODE_CHOICES]),
                name='inter_event_scene_valid'),
            models.CheckConstraint(
                check=models.Q(
                    classification_status__in=[x[0] for x in CLASSIFICATION_STATUS_CHOICES]),
                name='inter_event_class_valid'),
            models.CheckConstraint(
                check=models.Q(
                    interference_kind_code__in=[x[0] for x in INTERFERENCE_KIND_CODE_CHOICES]),
                name='inter_event_kind_valid'),
            models.CheckConstraint(
                check=models.Q(
                    affected_system_code__in=[x[0] for x in AFFECTED_SYSTEM_CODE_CHOICES]),
                name='inter_event_system_valid'),
            models.CheckConstraint(
                check=models.Q(
                    source_type_code__in=[x[0] for x in SOURCE_TYPE_CODE_CHOICES]),
                name='inter_event_source_valid'),
        ]


class GroundInterferenceDetail(SoftDeleteTenantModel):
    """地面专属明细，共享事件主键。"""

    event = models.OneToOneField(
        InterferenceEvent,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name='ground_detail',
    )
    location = models.CharField(max_length=200, blank=True, default='')
    frequency = models.CharField(max_length=100, blank=True, default='')
    ground_equipment = models.CharField(max_length=200, blank=True, default='')
    remark = models.TextField(blank=True, default='')

    def clean(self):
        if self.event_id and self.event.scene_code not in ('ground', 'cross'):
            raise ValidationError('当前事件场景不允许地面明细')

    def to_view(self):
        return {
            'location': self.location,
            'frequency': self.frequency,
            'ground_equipment': self.ground_equipment,
            'remark': self.remark,
        }

    class Meta:
        db_table = 'tdyw_ground_interference_details'
        verbose_name = '地面干扰明细'
        verbose_name_plural = '地面干扰明细'


class AirInterferenceDetail(SoftDeleteTenantModel):
    """空中专属明细，共享事件主键。"""

    event = models.OneToOneField(
        InterferenceEvent,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name='air_detail',
    )
    route = models.CharField(max_length=200, blank=True, default='')
    alert_frequency = models.CharField(max_length=100, blank=True, default='')
    alert_altitude = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True)
    alert_altitude_unit = models.CharField(
        max_length=10, choices=ALTITUDE_UNIT_CHOICES, default='m')
    alert_segment = models.CharField(max_length=200, blank=True, default='')
    duration = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True)
    duration_unit = models.CharField(
        max_length=10, choices=DURATION_UNIT_CHOICES, default='min')

    def clean(self):
        if self.event_id and self.event.scene_code not in ('air', 'cross'):
            raise ValidationError('当前事件场景不允许空中明细')
        if self.alert_altitude is not None and self.alert_altitude <= 0:
            raise ValidationError({'alert_altitude': '告警高度必须大于0'})
        if self.duration is not None and self.duration <= 0:
            raise ValidationError({'duration': '持续时间必须大于0'})

    def to_view(self):
        return {
            'route': self.route,
            'alert_frequency': self.alert_frequency,
            'alert_altitude': self.alert_altitude,
            'alert_altitude_unit': self.alert_altitude_unit,
            'alert_altitude_text': (
                '%s%s' % (format_decimal(self.alert_altitude),
                          ALTITUDE_UNIT_TEXT.get(self.alert_altitude_unit,
                                                 self.alert_altitude_unit))
                if self.alert_altitude is not None else ''),
            'alert_segment': self.alert_segment,
            'duration': self.duration,
            'duration_unit': self.duration_unit,
            'duration_text': (
                '%s%s' % (format_decimal(self.duration),
                          DURATION_UNIT_TEXT.get(self.duration_unit,
                                                self.duration_unit))
                if self.duration is not None else ''),
        }

    class Meta:
        db_table = 'tdyw_air_interference_details'
        verbose_name = '空中干扰明细'
        verbose_name_plural = '空中干扰明细'
        constraints = [
            models.CheckConstraint(
                check=models.Q(alert_altitude__isnull=True) |
                models.Q(alert_altitude__gt=0),
                name='air_detail_altitude_positive'),
            models.CheckConstraint(
                check=models.Q(duration__isnull=True) | models.Q(duration__gt=0),
                name='air_detail_duration_positive'),
        ]


class InterferenceInvestigation(SoftDeleteTenantModel):
    """可选的规律调查专题。"""

    name = models.CharField(max_length=200)
    scope = models.TextField(blank=True, default='')
    owner = models.CharField(max_length=100, blank=True, default='')
    trigger_reason = models.TextField(blank=True, default='')
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=INVESTIGATION_STATUS_CHOICES, default='draft')
    conclusion = models.TextField(blank=True, default='')
    follow_up_advice = models.TextField(blank=True, default='')
    remark = models.TextField(blank=True, default='')

    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    def to_view(self):
        links = list(InvestigationEvent.objects.filter(
            investigation_id=self.pk, is_deleted=False, event__is_deleted=False
        ).select_related('event').order_by('event__datetime', 'event_id'))
        event_ids = [link.event_id for link in links]
        ground_by_event = {
            detail.event_id: detail for detail in GroundInterferenceDetail.objects.filter(
                event_id__in=event_ids, is_deleted=False)
        }
        air_by_event = {
            detail.event_id: detail for detail in AirInterferenceDetail.objects.filter(
                event_id__in=event_ids, is_deleted=False)
        }

        def most_common(values):
            values = [str(value).strip() for value in values if str(value or '').strip()]
            return Counter(values).most_common(1)[0][0] if values else ''

        primary_locations = []
        primary_frequencies = []
        for event_id in event_ids:
            ground = ground_by_event.get(event_id)
            air = air_by_event.get(event_id)
            if ground:
                primary_locations.append(ground.location)
                primary_frequencies.append(ground.frequency)
            if air:
                # Air records use route/segment as their location context.
                primary_locations.append(air.route or air.alert_segment)
                primary_frequencies.append(air.alert_frequency)
        first_event = links[0] if links else None
        last_event = links[-1] if links else None
        return {
            'id': self.id,
            'name': self.name,
            'scope': self.scope,
            'owner': self.owner,
            'trigger_reason': self.trigger_reason,
            'start_at': self.start_at,
            'end_at': self.end_at,
            'status': self.status,
            'status_text': INVESTIGATION_STATUS_TEXT.get(self.status, self.status),
            'conclusion': self.conclusion,
            'follow_up_advice': self.follow_up_advice,
            'remark': self.remark,
            'event_count': len(links),
            'first_event_datetime': first_event.event.datetime if first_event else None,
            'last_event_datetime': last_event.event.datetime if last_event else None,
            'primary_location': most_common(primary_locations),
            'primary_frequency': most_common(primary_frequencies),
            'created_by': self.created_by_id,
            'created_at': self.created_at,
            'updated_by': self.updated_by_id,
            'updated_at': self.updated_at,
        }

    class Meta:
        db_table = 'tdyw_interference_investigations'
        verbose_name = '干扰规律调查'
        verbose_name_plural = '干扰规律调查'
        ordering = ('-created_at', '-id')
        indexes = [
            models.Index(fields=['tenant_id', 'status'], name='inter_inv_status_idx'),
            models.Index(fields=['tenant_id', '-created_at', '-id'],
                         name='inter_inv_time_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(status__in=[x[0] for x in INVESTIGATION_STATUS_CHOICES]),
                name='inter_inv_status_valid'),
        ]


class InvestigationEvent(SoftDeleteTenantModel):
    """调查专题与事件的多对多关联。"""

    investigation = models.ForeignKey(
        InterferenceInvestigation,
        on_delete=models.CASCADE,
        related_name='event_links',
    )
    event = models.ForeignKey(
        InterferenceEvent,
        on_delete=models.CASCADE,
        related_name='investigation_links',
    )
    sequence = models.PositiveIntegerField(default=0)
    relevance_note = models.TextField(blank=True, default='')
    linked_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True)

    class Meta:
        db_table = 'tdyw_interference_investigation_events'
        verbose_name = '调查事件关联'
        verbose_name_plural = '调查事件关联'
        constraints = [
            models.UniqueConstraint(
                fields=['investigation', 'event'], name='inter_inv_event_unique'),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'investigation'],
                         name='inter_inv_event_inv_idx'),
            models.Index(fields=['tenant_id', 'event'],
                         name='inter_inv_event_evt_idx'),
        ]


class SpectrumMeasurement(SoftDeleteTenantModel):
    """调查专题下的一条频谱仪测量记录。"""

    investigation = models.ForeignKey(
        InterferenceInvestigation,
        on_delete=models.CASCADE,
        related_name='measurements',
    )
    measured_at = models.DateTimeField()
    location = models.CharField(max_length=200, blank=True, default='')
    instrument_model = models.CharField(max_length=200, blank=True, default='')
    instrument_no = models.CharField(max_length=100, blank=True, default='')
    frequency_range = models.CharField(max_length=200, blank=True, default='')
    center_frequency = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True)
    bandwidth = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True)
    field_strength = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True)
    power = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True)
    measurement_unit = models.CharField(max_length=50, blank=True, default='')
    antenna_polarization = models.CharField(max_length=100, blank=True, default='')
    result = models.TextField(blank=True, default='')
    conclusion = models.TextField(blank=True, default='')
    remark = models.TextField(blank=True, default='')

    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    def to_view(self):
        return {
            'id': self.id,
            'investigation_id': self.investigation_id,
            'measured_at': self.measured_at,
            'location': self.location,
            'instrument_model': self.instrument_model,
            'instrument_no': self.instrument_no,
            'frequency_range': self.frequency_range,
            'center_frequency': self.center_frequency,
            'bandwidth': self.bandwidth,
            'field_strength': self.field_strength,
            'power': self.power,
            'measurement_unit': self.measurement_unit,
            'antenna_polarization': self.antenna_polarization,
            'result': self.result,
            'conclusion': self.conclusion,
            'remark': self.remark,
            'created_by': self.created_by_id,
            'created_at': self.created_at,
            'updated_by': self.updated_by_id,
            'updated_at': self.updated_at,
        }

    class Meta:
        db_table = 'tdyw_spectrum_measurements'
        verbose_name = '频谱仪测量记录'
        verbose_name_plural = '频谱仪测量记录'
        ordering = ('-measured_at', '-id')
        indexes = [
            models.Index(fields=['tenant_id', 'investigation', '-measured_at'],
                         name='inter_measure_inv_idx'),
        ]


__all__ = [
    'InterferenceEvent', 'GroundInterferenceDetail', 'AirInterferenceDetail',
    'InterferenceInvestigation', 'InvestigationEvent', 'SpectrumMeasurement',
    'SCENE_CODE_CHOICES', 'CLASSIFICATION_STATUS_CHOICES',
    'INTERFERENCE_KIND_CODE_CHOICES', 'AFFECTED_SYSTEM_CODE_CHOICES',
    'SOURCE_TYPE_CODE_CHOICES', 'INVESTIGATION_STATUS_CHOICES',
    'ALTITUDE_UNIT_CHOICES', 'DURATION_UNIT_CHOICES',
    'SCENE_CODE_TEXT', 'CLASSIFICATION_STATUS_TEXT',
    'INTERFERENCE_KIND_CODE_TEXT', 'AFFECTED_SYSTEM_CODE_TEXT',
    'SOURCE_TYPE_CODE_TEXT', 'INVESTIGATION_STATUS_TEXT',
    'ALTITUDE_UNIT_TEXT', 'DURATION_UNIT_TEXT', 'format_decimal',
]

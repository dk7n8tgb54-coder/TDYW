# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""干扰管理最终数据模型。

事件是事实记录，调查是可选的分析专题；两者通过关联表连接。地面和空中
专属字段分别放在共享主键明细表中，避免把两种场景拼成一张宽表。
"""

import re
from collections import Counter

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
    # 2026-10-02 用户定名：cross 场景显示为「地面+空中」（存储值不变）
    ('cross', '地面+空中'),
    ('unknown', '未知'),
)
SCENE_CODE_TEXT = dict(SCENE_CODE_CHOICES)

# 干扰分类选项分组（2026-10-25 起三个分类下拉从固定枚举改为选项表维护）
CATEGORY_GROUP_KIND = 'interference_kind'
CATEGORY_GROUP_SYSTEM = 'affected_system'
CATEGORY_GROUP_SOURCE = 'source_type'
CATEGORY_GROUP_CHOICES = (
    (CATEGORY_GROUP_KIND, '具体干扰类型'),
    (CATEGORY_GROUP_SYSTEM, '受影响系统'),
    (CATEGORY_GROUP_SOURCE, '疑似干扰源'),
)
CATEGORY_GROUP_TEXT = dict(CATEGORY_GROUP_CHOICES)

# 稳定编码规则：小写字母开头，仅小写字母/数字/下划线
CATEGORY_CODE_PATTERN = re.compile(r'^[a-z][a-z0-9_]*$')

# 规律调查生命周期（2026-10-26 三态收敛）：调查只由用户从选中记录主动
# 发起，保存后即 investigating；状态只能通过「结束调查」「取消调查」两个
# 业务动作变更（见 investigation_actions），通用创建/编辑路径 fail-closed。
INVESTIGATION_STATUS_CHOICES = (
    ('investigating', '调查中'),
    ('ended', '已结束'),
    ('cancelled', '已取消'),
)
INVESTIGATION_STATUS_TEXT = dict(INVESTIGATION_STATUS_CHOICES)

# 「结束调查」动作的业务结论：发现规律/未发现规律/暂无法确认。
# 历史行 result 保持空串，禁止从自由文本 conclusion 推断。
INVESTIGATION_RESULT_CHOICES = (
    ('found', '发现规律'),
    ('not_found', '未发现规律'),
    ('undetermined', '暂无法确认'),
)
INVESTIGATION_RESULT_TEXT = dict(INVESTIGATION_RESULT_CHOICES)


class SoftDeleteTenantModel(models.Model, TenantModelMixin):
    """需要租户隔离和软删除的干扰对象公共字段。"""

    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class InterferenceCategoryOption(models.Model):
    """干扰分类选项：全平台共用的字典数据，仅超级管理员维护。

    - 不带租户字段，所有租户的事件共用同一套选项；
    - 编码一经使用即不可删除或复用：已被任何事件（含跨租户、含软删除）
      引用的选项拒绝删除，从未被引用的选项允许物理删除；
    - 停用（is_active=False）后不再供新事件选择，历史事件仍按名称显示；
    - unknown 编码是新建事件的缺省分类值，任何分组下都不允许删除；
    - created_by 可空：迁移播种的系统内置选项没有维护人。
    """

    group = models.CharField(
        max_length=32, choices=CATEGORY_GROUP_CHOICES, verbose_name='分组')
    code = models.CharField(max_length=40, verbose_name='稳定编码')
    name = models.CharField(max_length=100, verbose_name='名称')
    sort_id = models.IntegerField(default=0, verbose_name='排序')
    is_active = models.BooleanField(default=True, verbose_name='启用')
    created_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        if self.group not in CATEGORY_GROUP_TEXT:
            raise ValidationError({'group': '无效的选项分组'})
        if not self.code or not CATEGORY_CODE_PATTERN.match(self.code):
            raise ValidationError({
                'code': '编码必须以小写字母开头，仅含小写字母、数字和下划线'})
        if not self.name or not self.name.strip():
            raise ValidationError({'name': '请输入选项名称'})

    def to_view(self):
        return {
            'id': self.id,
            'group': self.group,
            'group_text': CATEGORY_GROUP_TEXT.get(self.group, self.group),
            'code': self.code,
            'name': self.name,
            'sort_id': self.sort_id,
            'is_active': self.is_active,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

    class Meta:
        db_table = 'tdyw_interference_category_options'
        verbose_name = '干扰分类选项'
        verbose_name_plural = '干扰分类选项'
        ordering = ('group', 'sort_id', 'id')
        constraints = [
            models.UniqueConstraint(
                fields=['group', 'code'], name='inter_cat_group_code_unique'),
        ]


class InterferenceEvent(SoftDeleteTenantModel):
    """一次干扰事实事件。

    三个分类字段（具体干扰类型/受影响系统/疑似干扰源）不再绑定固定枚举，
    取值由 InterferenceCategoryOption 选项表在写入层校验；数据库层仅保留
    非空与长度约束，历史编码按选项表名称显示。
    """

    datetime = models.DateTimeField(verbose_name='发生时间')
    scene_code = models.CharField(
        max_length=20, choices=SCENE_CODE_CHOICES, default='unknown',
        verbose_name='发生场景')
    interference_kind_code = models.CharField(
        max_length=40, default='unknown', verbose_name='具体干扰类型')
    affected_system_code = models.CharField(
        max_length=40, default='unknown', verbose_name='受影响系统')
    source_type_code = models.CharField(
        max_length=40, default='unknown', verbose_name='疑似干扰源')
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
        """校验场景取值（跨表明细一致性由写入服务补齐）。"""
        super().clean()
        if self.scene_code not in SCENE_CODE_TEXT:
            raise ValidationError({'scene_code': '无效的发生场景'})

    def to_view(self, include_details=True, category_maps=None):
        if category_maps is None:
            from apps.interference import category_services
            category_maps = category_services.load_category_text_maps()
        result = {
            'id': self.id,
            'datetime': self.datetime,
            'scene_code': self.scene_code,
            'scene_text': SCENE_CODE_TEXT.get(self.scene_code, self.scene_code),
            'interference_kind_code': self.interference_kind_code,
            'interference_kind_text': category_maps['interference_kind'].get(
                self.interference_kind_code, self.interference_kind_code),
            'affected_system_code': self.affected_system_code,
            'affected_system_text': category_maps['affected_system'].get(
                self.affected_system_code, self.affected_system_code),
            'source_type_code': self.source_type_code,
            'source_type_text': category_maps['source_type'].get(
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
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(scene_code__in=[x[0] for x in SCENE_CODE_CHOICES]),
                name='inter_event_scene_valid'),
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
    alert_segment = models.CharField(max_length=200, blank=True, default='')
    duration = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True)

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
            'alert_segment': self.alert_segment,
            'duration': self.duration,
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
        max_length=20, choices=INVESTIGATION_STATUS_CHOICES,
        default='investigating')
    result = models.CharField(
        max_length=20, choices=INVESTIGATION_RESULT_CHOICES,
        blank=True, default='', verbose_name='调查结果')
    cancel_reason = models.TextField(blank=True, default='', verbose_name='取消原因')
    conclusion = models.TextField(blank=True, default='')
    follow_up_advice = models.TextField(blank=True, default='')
    remark = models.TextField(blank=True, default='')

    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def _load_view_context(cls, investigation_ids):
        """批量加载序列化所需的关联与明细（列表页避免逐条 N+1）。

        查询语义与单条 to_view 完全一致：有效关联（关联与事件均未删除）
        按事件发生时间排序，地面/空中明细按事件批量取一次。
        """
        links = list(InvestigationEvent.objects.filter(
            investigation_id__in=investigation_ids, is_deleted=False,
            event__is_deleted=False,
        ).select_related('event').order_by('event__datetime', 'event_id'))
        links_by_investigation = {}
        for link in links:
            links_by_investigation.setdefault(link.investigation_id, []).append(link)
        event_ids = [link.event_id for link in links]
        ground_by_event = {
            detail.event_id: detail for detail in GroundInterferenceDetail.objects.filter(
                event_id__in=event_ids, is_deleted=False)
        }
        air_by_event = {
            detail.event_id: detail for detail in AirInterferenceDetail.objects.filter(
                event_id__in=event_ids, is_deleted=False)
        }
        return links_by_investigation, ground_by_event, air_by_event

    def _build_view(self, links, ground_by_event, air_by_event):
        event_ids = [link.event_id for link in links]

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
            'result': self.result,
            'result_text': INVESTIGATION_RESULT_TEXT.get(self.result, self.result),
            'cancel_reason': self.cancel_reason,
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

    def to_view(self):
        links_by_investigation, ground_by_event, air_by_event = (
            self._load_view_context([self.pk]))
        return self._build_view(
            links_by_investigation.get(self.pk, []),
            ground_by_event, air_by_event)

    @classmethod
    def serialize_list(cls, investigations):
        """列表页批量序列化：每页固定 3 次查询替代逐条 to_view 的 N+1。"""
        investigations = list(investigations)
        if not investigations:
            return []
        links_by_investigation, ground_by_event, air_by_event = (
            cls._load_view_context([item.id for item in investigations]))
        return [
            item._build_view(
                links_by_investigation.get(item.id, []),
                ground_by_event, air_by_event)
            for item in investigations
        ]

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
    'InterferenceCategoryOption',
    'SCENE_CODE_CHOICES', 'SCENE_CODE_TEXT', 'INVESTIGATION_STATUS_CHOICES',
    'INVESTIGATION_STATUS_TEXT', 'INVESTIGATION_RESULT_CHOICES',
    'INVESTIGATION_RESULT_TEXT', 'CATEGORY_GROUP_KIND', 'CATEGORY_GROUP_SYSTEM',
    'CATEGORY_GROUP_SOURCE', 'CATEGORY_GROUP_CHOICES', 'CATEGORY_GROUP_TEXT',
    'CATEGORY_CODE_PATTERN',
]

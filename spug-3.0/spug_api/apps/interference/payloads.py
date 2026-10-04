"""干扰事件请求负载的字段清洗、解析与校验辅助函数。

仅供本模块 views.py 使用：负责把请求体数据清洗为可入库的字段值，
不承载任何数据库写入或外部副作用。
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone

from apps.interference.models import (
    AFFECTED_SYSTEM_CODE_CHOICES,
    CLASSIFICATION_STATUS_CHOICES,
    INTERFERENCE_KIND_CODE_CHOICES,
    SCENE_CODE_CHOICES,
    SOURCE_TYPE_CODE_CHOICES,
)


def parse_datetime(value, field='datetime'):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace('T', ' ')
        parsed = None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                raise ValueError(f'{field}格式必须为 YYYY-MM-DD HH:MM[:SS]')
    else:
        raise ValueError(f'请输入{field}')
    if settings.USE_TZ and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    elif not settings.USE_TZ and timezone.is_aware(parsed):
        parsed = timezone.make_naive(parsed, timezone.get_current_timezone())
    return parsed


def parse_optional_datetime(value, field):
    if value in (None, ''):
        return None
    return parse_datetime(value, field)


def parse_decimal(value, field, positive=False):
    if value in (None, ''):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{field}必须为数字')
    if positive and result <= 0:
        raise ValueError(f'{field}必须大于0')
    return result


def choice_error(value, choices, field):
    if value not in dict(choices):
        return f'{field}值无效'
    return None


def event_public_values(data, existing):
    """收集公共字段、应用默认值并解析校验，返回 ``(values, error)``。"""
    if not isinstance(data, dict):
        return None, '请求体必须是 JSON 对象'
    values = {}
    public_fields = (
        'datetime', 'scene_code', 'classification_status',
        'interference_kind_code', 'affected_system_code', 'source_type_code',
        'flight_number', 'aircraft_no', 'aircraft_type', 'phenomenon',
        'initial_assessment', 'remark',
    )
    for field in public_fields:
        if field in data:
            values[field] = '' if data[field] is None and field not in ('datetime',) else data[field]
    if existing is not None:
        values.setdefault('scene_code', existing.scene_code)
        values.setdefault('classification_status', existing.classification_status)
        values.setdefault('interference_kind_code', existing.interference_kind_code)
        values.setdefault('affected_system_code', existing.affected_system_code)
        values.setdefault('source_type_code', existing.source_type_code)
    else:
        values.setdefault('scene_code', 'unknown')
        values.setdefault('classification_status', 'pending')
        values.setdefault('interference_kind_code', 'unknown')
        values.setdefault('affected_system_code', 'other')
        values.setdefault('source_type_code', 'unknown')
    if 'datetime' in values:
        try:
            values['datetime'] = parse_datetime(values['datetime'])
        except ValueError as exc:
            return None, str(exc)
    elif existing is None:
        return None, '请输入发生时间'
    for field, choices, label in (
        ('scene_code', SCENE_CODE_CHOICES, '发生场景'),
        ('classification_status', CLASSIFICATION_STATUS_CHOICES, '分类状态'),
        ('interference_kind_code', INTERFERENCE_KIND_CODE_CHOICES, '具体干扰类型'),
        ('affected_system_code', AFFECTED_SYSTEM_CODE_CHOICES, '受影响系统'),
        ('source_type_code', SOURCE_TYPE_CODE_CHOICES, '疑似干扰源'),
    ):
        error = choice_error(values.get(field), choices, label)
        if error:
            return None, error
    return values, None


def event_detail_inputs(data):
    """提取地面/空中明细入参，兼容旧版扁平参数。"""
    ground = data.get('ground_detail') if 'ground_detail' in data else None
    air = data.get('air_detail') if 'air_detail' in data else None
    if 'ground_detail' not in data:
        legacy_ground = {k: data[k] for k in (
            'location', 'frequency', 'ground_equipment',
        ) if k in data}
        if legacy_ground:
            ground = legacy_ground
    if 'air_detail' not in data:
        # 单位字段已下线，但保留在收集清单里让旧参数在明细规范化时显式报错
        legacy_air = {k: data[k] for k in (
            'route', 'alert_frequency', 'alert_altitude', 'alert_altitude_unit',
            'alert_segment', 'duration', 'duration_unit',
        ) if k in data}
        if legacy_air:
            air = legacy_air
    return ground, air


def validate_detail_types(ground, air):
    """校验明细入参必须是对象。"""
    if ground is not None and not isinstance(ground, dict):
        return '地面明细必须是对象'
    if air is not None and not isinstance(air, dict):
        return '空中明细必须是对象'
    return None


def validate_scene_detail_mix(scene, ground, air):
    """校验场景与明细入参的组合约束。"""
    if scene == 'ground' and air is not None:
        return '地面事件不能包含空中明细'
    if scene == 'air' and ground is not None:
        return '空中事件不能包含地面明细'
    if scene == 'unknown' and (ground is not None or air is not None):
        return '未知场景暂不能填写专属明细'
    return None


def validate_confirmed_inputs(classification_status, scene, ground, air, existing):
    """已确认事件对明细入参的必填要求（仅创建时强制）。"""
    if classification_status != 'confirmed':
        return None
    if scene == 'ground' and ground is None and existing is None:
        return '已确认的地面事件必须填写地面明细'
    if scene == 'air' and air is None and existing is None:
        return '已确认的空中事件必须填写空中明细'
    if scene == 'cross' and ground is None and air is None and existing is None:
        return '已确认的地面+空中事件至少需要一类明细'
    return None


def event_payload(data, existing=None):
    """清洗公共字段和明细，返回 ``(values, ground, air, error)``。"""
    values, error = event_public_values(data, existing)
    if error:
        return None, None, None, error
    ground, air = event_detail_inputs(data)
    error = validate_detail_types(ground, air)
    if error:
        return None, None, None, error
    error = validate_scene_detail_mix(values['scene_code'], ground, air)
    if error:
        return None, None, None, error
    error = validate_confirmed_inputs(
        values['classification_status'], values['scene_code'], ground, air, existing)
    if error:
        return None, None, None, error
    return values, ground, air, None

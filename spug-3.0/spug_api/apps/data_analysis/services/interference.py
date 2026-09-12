"""基于 InterferenceEvent 的干扰统计服务。"""

from django.db.models import Count

from apps.interference.models import (
    InterferenceEvent,
    InterferenceInvestigation,
    InvestigationEvent,
    SpectrumMeasurement,
)
from libs.tenant_utils import apply_tenant_filter

from .common import (
    build_distribution,
    build_meta,
    build_monthly_trend,
    make_range_filter,
)


def get_interference_analysis(user, start_date, end_date):
    """返回事件、调查和频谱测量的统一聚合结果。

    统计只从事件主表聚合，因此跨场景事件、明细表和调查关联都不会重复计数。
    """
    event_base = apply_tenant_filter(
        InterferenceEvent.objects.filter(is_deleted=False), user)
    event_range = make_range_filter(start_date, end_date, 'datetime')
    events = event_base.filter(event_range)

    investigation_base = apply_tenant_filter(
        InterferenceInvestigation.objects.filter(is_deleted=False), user)
    measurement_base = apply_tenant_filter(
        SpectrumMeasurement.objects.filter(
            is_deleted=False, investigation__is_deleted=False), user)
    investigation_range = make_range_filter(start_date, end_date, 'created_at')
    measurement_range = make_range_filter(start_date, end_date, 'measured_at')

    by_scene = build_distribution(events, 'scene_code')
    by_kind = build_distribution(events, 'interference_kind_code')
    by_system = build_distribution(events, 'affected_system_code')
    by_source = build_distribution(events, 'source_type_code')
    return {
        'meta': build_meta(start_date, end_date),
        'summary': {
            'record_count': events.count(),
            'investigation_count': investigation_base.filter(investigation_range).count(),
            'measurement_count': measurement_base.filter(measurement_range).count(),
            'ground_count': events.filter(scene_code='ground').count(),
            'air_count': events.filter(scene_code='air').count(),
            'cross_count': events.filter(scene_code='cross').count(),
            'unknown_count': events.filter(scene_code='unknown').count(),
            'pending_count': events.filter(classification_status='pending').count(),
            'confirmed_count': events.filter(classification_status='confirmed').count(),
        },
        'trends': {
            'record_monthly': build_monthly_trend(
                event_base, 'datetime', start_date, end_date),
            'investigation_monthly': build_monthly_trend(
                investigation_base, 'created_at', start_date, end_date),
            'measurement_monthly': build_monthly_trend(
                measurement_base, 'measured_at', start_date, end_date),
        },
        'distributions': {
            'by_scene': by_scene,
            'by_interference_kind': by_kind,
            'by_affected_system': by_system,
            'by_source_type': by_source,
        },
    }

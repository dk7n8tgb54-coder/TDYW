"""故障分析服务。"""
from django.db.models import Count, Q

from apps.fault.models import FaultRecord, FaultPart
from libs.tenant_utils import apply_tenant_filter
from .common import (
    make_range_filter, build_distribution, build_monthly_trend, build_meta, calc_rate,
)


def get_fault_analysis(user, start_date, end_date):
    """获取故障分析数据。"""
    fault_range = make_range_filter(start_date, end_date, 'fault_date')
    part_range = make_range_filter(start_date, end_date, 'date')

    # 故障记录基础 QuerySet
    fault_qs = apply_tenant_filter(
        FaultRecord.objects.filter(is_deleted=False).filter(fault_range), user
    )
    record_count = fault_qs.count()

    # 故障件基础 QuerySet
    part_qs = apply_tenant_filter(
        FaultPart.objects.filter(is_deleted=False).filter(part_range), user
    )
    part_count = part_qs.count()
    archived_part_count = part_qs.exclude(archive_date__isnull=True).count()
    unarchived_part_count = part_qs.filter(archive_date__isnull=True).count()

    # 月度趋势
    record_monthly = build_monthly_trend(
        apply_tenant_filter(FaultRecord.objects.filter(is_deleted=False), user),
        'fault_date', start_date, end_date
    )
    part_monthly = build_monthly_trend(
        apply_tenant_filter(FaultPart.objects.filter(is_deleted=False), user),
        'date', start_date, end_date
    )

    # 分布
    record_by_level = build_distribution(fault_qs, 'fault_level')
    record_by_system = build_distribution(fault_qs, 'system_name')
    part_by_status = build_distribution(part_qs, 'status')
    part_by_system = build_distribution(part_qs, 'system_name')

    return {
        'meta': build_meta(start_date, end_date),
        'summary': {
            'record_count': record_count,
            'part_count': part_count,
            'archived_part_count': archived_part_count,
            'unarchived_part_count': unarchived_part_count,
            'archive_rate': calc_rate(archived_part_count, part_count),
        },
        'trends': {
            'record_monthly': record_monthly,
            'part_monthly': part_monthly,
        },
        'distributions': {
            'record_by_level': record_by_level,
            'record_by_system': record_by_system,
            'part_by_status': part_by_status,
            'part_by_system': part_by_system,
        },
    }

"""干扰分析服务。"""
from django.db.models import Count, Q

from apps.interference.models import Interference
from libs.tenant_utils import apply_tenant_filter
from .common import (
    make_range_filter, build_distribution, build_monthly_trend, build_meta, calc_rate,
)


def get_interference_analysis(user, start_date, end_date):
    """获取干扰分析数据。"""
    interference_range = make_range_filter(start_date, end_date, 'datetime')

    interference_qs = apply_tenant_filter(
        Interference.objects.filter(is_deleted=False).filter(interference_range), user
    )
    record_count = interference_qs.count()
    reported_count = interference_qs.filter(is_reported='是').count()
    unreported_count = record_count - reported_count

    # 月度趋势
    record_monthly = build_monthly_trend(
        apply_tenant_filter(Interference.objects.filter(is_deleted=False), user),
        'datetime', start_date, end_date
    )

    # 分布
    by_type = build_distribution(interference_qs, 'interference_type')
    by_frequency = build_distribution(interference_qs, 'frequency')
    by_status = build_distribution(interference_qs, 'status')
    by_report_department = build_distribution(interference_qs, 'report_dept')

    return {
        'meta': build_meta(start_date, end_date),
        'summary': {
            'record_count': record_count,
            'reported_count': reported_count,
            'unreported_count': unreported_count,
            'report_rate': calc_rate(reported_count, record_count),
        },
        'trends': {
            'record_monthly': record_monthly,
        },
        'distributions': {
            'by_type': by_type,
            'by_frequency': by_frequency,
            'by_status': by_status,
            'by_report_department': by_report_department,
        },
    }

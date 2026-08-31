"""干扰分析服务。

2026-08 双业务拆分：干扰分析分别统计「地面无线电通信异常/干扰」与
「空中干扰」两类记录并给出总量；两类业务各自的明细字段不混入同一张统计表，
仅按记录类型分列共同摘要（月度趋势）。
"""
from apps.interference.models import (
    Interference, BridgeInterferenceRecord, AirInterferenceRecord,
)
from libs.tenant_utils import apply_tenant_filter
from .common import (
    make_range_filter, build_distribution, build_monthly_trend, build_meta, calc_rate,
)

# (key, 中文名, 模型) —— 两类业务统一遍历，避免逻辑分叉
BUSINESS_RECORD_SPECS = (
    ('bridge', '地面无线电通信异常/干扰', BridgeInterferenceRecord),
    ('air', '空中干扰', AirInterferenceRecord),
)


def get_interference_analysis(user, start_date, end_date):
    """获取干扰分析数据（双业务类型）。"""
    interference_range = make_range_filter(start_date, end_date, 'datetime')

    summary = {}
    trends = {}
    record_count = 0
    for key, _label, model in BUSINESS_RECORD_SPECS:
        qs = apply_tenant_filter(
            model.objects.filter(is_deleted=False).filter(interference_range), user
        )
        count = qs.count()
        record_count += count
        summary[f'{key}_count'] = count

        # 月度趋势（按类型分列）
        trends[f'{key}_monthly'] = build_monthly_trend(
            apply_tenant_filter(model.objects.filter(is_deleted=False), user),
            'datetime', start_date, end_date
        )

    # 保留旧 Interference 表的统计维度，兼容既有数据分析调用方。
    legacy_qs = apply_tenant_filter(
        Interference.objects.filter(is_deleted=False).filter(interference_range), user
    )
    legacy_count = legacy_qs.count()
    reported_count = legacy_qs.filter(is_reported='是').count()
    record_count += legacy_count
    summary.update({
        'legacy_record_count': legacy_count,
        'reported_count': reported_count,
        'unreported_count': legacy_count - reported_count,
        'report_rate': calc_rate(reported_count, legacy_count),
    })
    trends['record_monthly'] = build_monthly_trend(
        apply_tenant_filter(Interference.objects.filter(is_deleted=False), user),
        'datetime', start_date, end_date
    )

    summary['record_count'] = record_count

    return {
        'meta': build_meta(start_date, end_date),
        'summary': summary,
        'trends': trends,
        'distributions': {
            'by_type': build_distribution(legacy_qs, 'interference_type'),
            'by_frequency': build_distribution(legacy_qs, 'frequency'),
            'by_status': build_distribution(legacy_qs, 'status'),
            'by_report_department': build_distribution(legacy_qs, 'report_dept'),
        },
    }

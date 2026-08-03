"""设备分析服务。"""
from django.db.models import Count, Q

from apps.device.models import DeviceResume
from libs.tenant_utils import apply_tenant_filter
from .common import (
    make_range_filter, build_distribution, build_monthly_trend, build_meta,
)

# 设备状态映射
STATUS_LABELS = {
    '1': '正常',
    '2': '故障',
    '3': '维修中',
    '4': '停用',
    '5': '报废',
}


def get_device_analysis(user, start_date, end_date):
    """获取设备分析数据。"""
    created_range = make_range_filter(start_date, end_date, 'created_at')

    # 设备当前快照（不受日期范围限制）
    device_qs = apply_tenant_filter(
        DeviceResume.objects.filter(is_deleted=False), user
    )
    total_snapshot = device_qs.count()

    # 按状态统计
    status_counts = {}
    raw_status = (
        device_qs.values('current_status')
        .annotate(count=Count('id'))
        .order_by('current_status')
    )
    for row in raw_status:
        code = row['current_status'] or ''
        label = STATUS_LABELS.get(code, code or '未填写')
        status_counts[label] = status_counts.get(label, 0) + row['count']

    by_status = [
        {'name': name, 'count': count, 'percent': round(count / total_snapshot * 100, 1) if total_snapshot > 0 else 0.0}
        for name, count in sorted(status_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    # 区间内新增设备数
    created_in_period_qs = apply_tenant_filter(
        DeviceResume.objects.filter(is_deleted=False).filter(created_range), user
    )
    created_in_period = created_in_period_qs.count()

    # 月度趋势（新增设备）
    created_monthly = build_monthly_trend(
        apply_tenant_filter(DeviceResume.objects.filter(is_deleted=False), user),
        'created_at', start_date, end_date
    )

    # 分布
    by_model = build_distribution(device_qs, 'device_model')
    by_manufacturer = build_distribution(device_qs, 'manufacturer')
    by_use_unit = build_distribution(device_qs, 'use_unit')

    return {
        'meta': build_meta(start_date, end_date),
        'summary': {
            'total_snapshot': total_snapshot,
            'normal_snapshot': status_counts.get('正常', 0),
            'fault_snapshot': status_counts.get('故障', 0),
            'repairing_snapshot': status_counts.get('维修中', 0),
            'disabled_snapshot': status_counts.get('停用', 0),
            'scrapped_snapshot': status_counts.get('报废', 0),
            'created_in_period': created_in_period,
        },
        'trends': {
            'created_monthly': created_monthly,
        },
        'distributions': {
            'by_status': by_status,
            'by_model': by_model,
            'by_manufacturer': by_manufacturer,
            'by_use_unit': by_use_unit,
        },
    }

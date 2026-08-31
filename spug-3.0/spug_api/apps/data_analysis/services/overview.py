"""总览分析服务。"""
import datetime
from django.db.models import Count, Q

from apps.device.models import DeviceResume
from apps.fault.models import FaultRecord
from apps.interference.models import BridgeInterferenceRecord, AirInterferenceRecord
from apps.upgrade.models import UpgradeRecord
from apps.upgrade.constants import UpgradeStatus
from libs.tenant_utils import apply_tenant_filter
from .common import (
    make_range_filter, build_monthly_trend, build_meta, calc_rate,
)


def get_overview(user, start_date, end_date):
    """获取总览数据。"""
    range_filter = make_range_filter(start_date, end_date, 'created_at')
    fault_range = make_range_filter(start_date, end_date, 'fault_date')
    interference_range = make_range_filter(start_date, end_date, 'datetime')
    upgrade_range = make_range_filter(start_date, end_date, 'upgrade_time')

    # 设备当前快照（不受日期范围限制）
    device_qs = apply_tenant_filter(
        DeviceResume.objects.filter(is_deleted=False), user
    )
    device_total = device_qs.count()
    device_normal = device_qs.filter(current_status='1').count()
    device_fault = device_qs.filter(current_status='2').count()

    # 故障记录数（区间内）
    fault_qs = apply_tenant_filter(
        FaultRecord.objects.filter(is_deleted=False).filter(fault_range), user
    )
    fault_count = fault_qs.count()

    # 干扰记录数（区间内，双业务类型：分别统计并给出总量）
    bridge_qs = apply_tenant_filter(
        BridgeInterferenceRecord.objects.filter(is_deleted=False).filter(interference_range), user
    )
    air_qs = apply_tenant_filter(
        AirInterferenceRecord.objects.filter(is_deleted=False).filter(interference_range), user
    )
    bridge_count = bridge_qs.count()
    air_count = air_qs.count()
    interference_count = bridge_count + air_count

    # 升级记录（区间内）
    upgrade_qs = apply_tenant_filter(
        UpgradeRecord.objects.filter(is_deleted=False).filter(upgrade_range), user
    )
    upgrade_count = upgrade_qs.count()
    upgrade_completed = upgrade_qs.filter(status=UpgradeStatus.COMPLETED).count()

    # 月度趋势
    fault_monthly = build_monthly_trend(
        apply_tenant_filter(
            FaultRecord.objects.filter(is_deleted=False), user
        ),
        'fault_date', start_date, end_date
    )
    interference_monthly = _build_interference_total_monthly(user, start_date, end_date)
    upgrade_monthly = build_monthly_trend(
        apply_tenant_filter(
            UpgradeRecord.objects.filter(is_deleted=False), user
        ),
        'upgrade_time', start_date, end_date
    )

    return {
        'meta': build_meta(start_date, end_date),
        'summary': {
            'device_total_snapshot': device_total,
            'device_normal_snapshot': device_normal,
            'device_fault_snapshot': device_fault,
            'fault_record_count': fault_count,
            'interference_record_count': interference_count,
            'interference_bridge_count': bridge_count,
            'interference_air_count': air_count,
            'upgrade_record_count': upgrade_count,
            'upgrade_completed_count': upgrade_completed,
            'upgrade_completion_rate': calc_rate(upgrade_completed, upgrade_count),
        },
        'trends': {
            'fault_monthly': fault_monthly,
            'interference_monthly': interference_monthly,
            'upgrade_monthly': upgrade_monthly,
        },
    }


def _build_interference_total_monthly(user, start_date, end_date):
    """两类干扰记录合计月度趋势（仅共同摘要，不混合业务明细字段）。"""
    monthly = {}
    for model in (BridgeInterferenceRecord, AirInterferenceRecord):
        for row in build_monthly_trend(
                apply_tenant_filter(model.objects.filter(is_deleted=False), user),
                'datetime', start_date, end_date):
            monthly[row['month']] = monthly.get(row['month'], 0) + row['count']
    return [{'month': month, 'count': count}
            for month, count in sorted(monthly.items())]

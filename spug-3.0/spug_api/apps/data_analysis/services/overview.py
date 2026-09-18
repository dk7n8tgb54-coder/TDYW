"""总览分析服务。"""
import datetime
from django.db.models import Count, Q

from apps.device.models import DeviceResume
from apps.interference.models import InterferenceEvent
from apps.upgrade.models import UpgradeRecord
from apps.upgrade.constants import UpgradeStatus
from libs.tenant_utils import apply_tenant_filter
from .common import (
    make_range_filter, build_monthly_trend, build_meta, calc_rate,
)


def get_overview(user, start_date, end_date):
    """获取总览数据。"""
    range_filter = make_range_filter(start_date, end_date, 'created_at')
    interference_range = make_range_filter(start_date, end_date, 'datetime')
    upgrade_range = make_range_filter(start_date, end_date, 'upgrade_time')

    # 设备当前快照（不受日期范围限制）
    device_qs = apply_tenant_filter(
        DeviceResume.objects.filter(is_deleted=False), user
    )
    device_total = device_qs.count()
    device_normal = device_qs.filter(current_status='1').count()
    device_fault = device_qs.filter(current_status='2').count()

    # 干扰记录数统一从事件主表统计，明细表不会造成重复计数。
    interference_qs = apply_tenant_filter(
        InterferenceEvent.objects.filter(is_deleted=False).filter(interference_range), user
    )
    interference_count = interference_qs.count()
    ground_count = interference_qs.filter(scene_code='ground').count()
    air_count = interference_qs.filter(scene_code='air').count()

    # 升级记录（区间内）
    upgrade_qs = apply_tenant_filter(
        UpgradeRecord.objects.filter(is_deleted=False).filter(upgrade_range), user
    )
    upgrade_count = upgrade_qs.count()
    upgrade_completed = upgrade_qs.filter(status=UpgradeStatus.COMPLETED).count()

    # 月度趋势
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
            'interference_record_count': interference_count,
            'interference_ground_count': ground_count,
            'interference_air_count': air_count,
            'upgrade_record_count': upgrade_count,
            'upgrade_completed_count': upgrade_completed,
            'upgrade_completion_rate': calc_rate(upgrade_completed, upgrade_count),
        },
        'trends': {
            'interference_monthly': interference_monthly,
            'upgrade_monthly': upgrade_monthly,
        },
    }


def _build_interference_total_monthly(user, start_date, end_date):
    """事件主表月度趋势。"""
    return build_monthly_trend(
        apply_tenant_filter(InterferenceEvent.objects.filter(is_deleted=False), user),
        'datetime', start_date, end_date,
    )

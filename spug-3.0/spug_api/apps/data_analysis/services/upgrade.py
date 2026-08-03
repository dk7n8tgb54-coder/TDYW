"""升级分析服务。"""
from django.db.models import Count, Q

from apps.upgrade.models import UpgradeRecord
from apps.upgrade.constants import UpgradeStatus
from libs.tenant_utils import apply_tenant_filter
from .common import (
    make_range_filter, build_distribution, build_monthly_trend, build_meta, calc_rate,
)


def get_upgrade_analysis(user, start_date, end_date):
    """获取升级分析数据。"""
    upgrade_range = make_range_filter(start_date, end_date, 'upgrade_time')

    upgrade_qs = apply_tenant_filter(
        UpgradeRecord.objects.filter(is_deleted=False).filter(upgrade_range), user
    )
    record_count = upgrade_qs.count()
    in_progress_count = upgrade_qs.filter(status=UpgradeStatus.IN_PROGRESS).count()
    completed_count = upgrade_qs.filter(status=UpgradeStatus.COMPLETED).count()
    rolled_back_count = upgrade_qs.filter(status=UpgradeStatus.ROLLED_BACK).count()

    # 月度趋势
    record_monthly = build_monthly_trend(
        apply_tenant_filter(UpgradeRecord.objects.filter(is_deleted=False), user),
        'upgrade_time', start_date, end_date
    )

    # 分布
    by_status = build_distribution(upgrade_qs, 'status')
    by_type = build_distribution(upgrade_qs, 'upgrade_type')
    by_system = build_distribution(upgrade_qs, 'system')

    return {
        'meta': build_meta(start_date, end_date),
        'summary': {
            'record_count': record_count,
            'in_progress_count': in_progress_count,
            'completed_count': completed_count,
            'rolled_back_count': rolled_back_count,
            'completion_rate': calc_rate(completed_count, record_count),
        },
        'trends': {
            'record_monthly': record_monthly,
        },
        'distributions': {
            'by_status': by_status,
            'by_type': by_type,
            'by_system': by_system,
        },
    }

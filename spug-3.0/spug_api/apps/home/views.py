# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import logging
from django.views.generic import View
from libs.utils import json_response
from libs.parser import JsonParser, Argument
from libs.decorators import auth
from libs.tenant_utils import apply_tenant_filter
import json

logger = logging.getLogger(__name__)


@auth('dashboard.dashboard.view')
def get_statistic(request):
    from datetime import timedelta
    from django.db.models import Count
    from django.utils import timezone
    from django.core.cache import cache

    # Redis 缓存：60 秒，按租户分键，避免并发用户重复查询
    tenant_id = getattr(request.user, 'tenant_id', 'default')
    cache_key = f'dashboard:{tenant_id}'
    cached = cache.get(cache_key)
    if cached is not None:
        return json_response(cached)

    # 用 datetime 范围替代 __startswith/__date，确保走 B-tree 索引
    from libs.date_utils import today_range, month_range
    now = timezone.now()
    today_start, today_end = today_range(now)
    month_start, next_month_start = month_range(now)
    data = {}

    # 1. 运行日志统计
    try:
        from apps.runlog.models import RunLog
        runlog_qs = apply_tenant_filter(RunLog.objects, request.user)
        today_events = runlog_qs.filter(created_at__gte=today_start, created_at__lt=today_end)
        data['runlog'] = {
            'today_total': today_events.count(),
            'today_resolved': runlog_qs.filter(
                status='resolved',
                updated_at__gte=today_start,
                updated_at__lt=today_end,
            ).count(),
            'in_progress_total': runlog_qs.filter(status='in_progress').count(),
            'severity_stats': list(
                runlog_qs.filter(status='in_progress')
                .values('severity')
                .annotate(count=Count('id'))
            ),
            'recent_pending': list(
                runlog_qs.filter(status='in_progress')
                .values('id', 'event_title', 'severity', 'created_at')
                .order_by('-created_at')[:8]
            ),
        }
    except Exception:
        logger.exception('[dashboard] runlog 统计失败')
        data['runlog'] = {}

    # 2. 故障处置概览
    try:
        from apps.fault.models import FaultRecord
        fault_qs = apply_tenant_filter(FaultRecord.objects, request.user)
        today_faults = fault_qs.filter(fault_date__gte=today_start, fault_date__lt=today_end)
        data['fault'] = {
            'today_total': today_faults.count(),
            'level_stats': list(
                today_faults.values('fault_level')
                .annotate(count=Count('id'))
            ),
            'total_all': fault_qs.count(),
        }
    except Exception:
        logger.exception('[dashboard] fault 统计失败')
        data['fault'] = {}

    # 3. 系统升级动态
    try:
        from apps.upgrade.models import UpgradeRecord
        upgrade_qs = apply_tenant_filter(UpgradeRecord.objects, request.user)
        upgrade_statuses = list(
            upgrade_qs.values('status').annotate(count=Count('id'))
        )
        monthly_upgrades = upgrade_qs.filter(
            upgrade_time__gte=month_start,
            upgrade_time__lt=next_month_start,
        )
        data['upgrade'] = {
            'total': upgrade_qs.count(),
            'status_stats': upgrade_statuses,
            'this_month': monthly_upgrades.count(),
            'recent': list(
                upgrade_qs.order_by('-created_at')[:5].values(
                    'id', 'upgrade_no', 'system', 'status', 'upgrade_time'
                )
            ),
        }
    except Exception:
        logger.exception('[dashboard] upgrade 统计失败')
        data['upgrade'] = {}

    # 4. 干扰信息今日统计
    try:
        from apps.interference.models import Interference
        interference_qs = apply_tenant_filter(Interference.objects, request.user)
        today_interference = interference_qs.filter(
            datetime__gte=today_start,
            datetime__lt=today_end,
        )
        data['interference'] = {
            'today_total': today_interference.count(),
            'type_stats': list(
                today_interference.values('interference_type')
                .annotate(count=Count('id'))
            ),
            'reported_count': today_interference.filter(is_reported='是').count(),
            'unreported_count': today_interference.filter(is_reported='否').count(),
        }
    except Exception:
        logger.exception('[dashboard] interference 统计失败')
        data['interference'] = {}

    # 5. 资料库今日新增文件
    try:
        from apps.document.models import DocumentFilePrivate, DocumentFilePublic
        private_files = apply_tenant_filter(DocumentFilePrivate.objects, request.user)
        public_files = DocumentFilePublic.objects.all()
        today_private = private_files.filter(
            created_at__gte=today_start, created_at__lt=today_end
        ).count()
        today_public = public_files.filter(
            created_at__gte=today_start, created_at__lt=today_end
        ).count()
        data['document'] = {
            'today_private': today_private,
            'today_public': today_public,
            'today_total': today_private + today_public,
        }
    except Exception:
        logger.exception('[dashboard] document 统计失败')
        data['document'] = {}

    cache.set(cache_key, data, 60)
    return json_response(data)

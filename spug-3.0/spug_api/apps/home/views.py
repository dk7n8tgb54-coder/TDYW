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
    from datetime import date, datetime
    from django.db.models import Count
    from django.utils import timezone
    today = date.today().strftime('%Y-%m-%d')
    today_date = timezone.now().date()
    this_month = date.today().strftime('%Y-%m')
    data = {}

    # 1. 运行日志统计
    try:
        from apps.runlog.models import RunLog
        runlog_qs = apply_tenant_filter(RunLog.objects, request.user)
        today_events = runlog_qs.filter(created_at__startswith=today)
        data['runlog'] = {
            'today_total': today_events.count(),
            'today_resolved': runlog_qs.filter(
                status='resolved',
                updated_at__startswith=today
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
        today_faults = fault_qs.filter(fault_date__startswith=today)
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
        monthly_upgrades = upgrade_qs.filter(upgrade_time__startswith=this_month)
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
        today_interference = interference_qs.filter(datetime__startswith=today)
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
        data['document'] = {
            'today_private': private_files.filter(created_at__date=today_date).count(),
            'today_public': public_files.filter(created_at__date=today_date).count(),
            'today_total': private_files.filter(created_at__date=today_date).count()
                          + public_files.filter(created_at__date=today_date).count(),
        }
    except Exception:
        logger.exception('[dashboard] document 统计失败')
        data['document'] = {}

    return json_response(data)

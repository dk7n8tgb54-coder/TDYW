# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import logging
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from django.views.generic import View
from libs.utils import json_response
from libs.parser import JsonParser, Argument
from libs.decorators import auth
from libs.mixins import AdminView
from libs.tenant_utils import apply_tenant_filter
from apps.home.models import Alert, AlertRead
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


def _alert_to_view(alert):
    if alert.status == alert.STATUS_RESOLVED:
        display_status = 'resolved'
    else:
        display_status = 'read' if alert.is_read else 'unread'
    resolver = alert.resolved_by
    return {
        'id': alert.id,
        'title': alert.title,
        'message': alert.message,
        'level': alert.level,
        'status': display_status,
        'source': alert.source,
        'alert_key': alert.alert_key,
        'created_at': alert.created_at,
        'resolved_at': alert.resolved_at,
        'resolved_by': resolver.nickname or resolver.username if resolver else '',
    }


class AlertListView(AdminView):
    PERM_MAP = {'GET': 'system.alert.view'}

    def get(self, request):
        form, error = JsonParser(
            Argument('page', type=int, default=1, required=False),
            Argument('page_size', type=int, default=20, required=False),
            Argument('level', required=False),
            Argument('status', required=False),
            Argument('source', required=False),
            Argument('keyword', required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        page = max(form.page, 1)
        page_size = min(max(form.page_size, 10), 100)
        read_query = AlertRead.objects.filter(alert_id=OuterRef('pk'), user_id=request.user.id)
        queryset = Alert.objects.select_related('resolved_by').annotate(
            is_read=Exists(read_query)
        )

        if form.level:
            if form.level not in dict(Alert.LEVEL_CHOICES):
                return json_response(error='无效的告警级别')
            queryset = queryset.filter(level=form.level)
        if form.source:
            queryset = queryset.filter(source=form.source)
        if form.keyword:
            queryset = queryset.filter(
                Q(title__icontains=form.keyword)
                | Q(message__icontains=form.keyword)
                | Q(alert_key__icontains=form.keyword)
            )
        if form.status:
            if form.status == 'resolved':
                queryset = queryset.filter(status=Alert.STATUS_RESOLVED)
            elif form.status == 'read':
                queryset = queryset.filter(status=Alert.STATUS_ACTIVE, is_read=True)
            elif form.status == 'unread':
                queryset = queryset.filter(status=Alert.STATUS_ACTIVE, is_read=False)
            else:
                return json_response(error='无效的告警状态')

        unread = Alert.objects.filter(status=Alert.STATUS_ACTIVE).annotate(
            is_read=Exists(read_query)
        ).filter(is_read=False)
        summary = unread.aggregate(
            unread_count=Count('id'),
            error_count=Count('id', filter=Q(level=Alert.LEVEL_ERROR)),
            warning_count=Count('id', filter=Q(level=Alert.LEVEL_WARNING)),
            info_count=Count('id', filter=Q(level=Alert.LEVEL_INFO)),
        )

        total = queryset.count()
        start = (page - 1) * page_size
        items = [_alert_to_view(item) for item in queryset[start:start + page_size]]
        return json_response({
            'items': items,
            'total': total,
            'page': page,
            'page_size': page_size,
            'summary': summary,
        })


class AlertMarkReadView(AdminView):
    PERM_MAP = {'POST': 'system.alert.view'}

    def post(self, request):
        form, error = JsonParser(
            Argument('ids', type=list, default=[], required=False),
            Argument('all', type=bool, default=False, required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        if not form.all and not form.ids:
            return json_response(error='请选择需要标记的告警')

        if form.all:
            alert_ids = Alert.objects.filter(status=Alert.STATUS_ACTIVE).values_list('id', flat=True)
        else:
            try:
                ids = {int(item) for item in form.ids if int(item) > 0}
            except (TypeError, ValueError):
                return json_response(error='告警 ID 格式错误')
            alert_ids = Alert.objects.filter(
                id__in=ids, status=Alert.STATUS_ACTIVE
            ).values_list('id', flat=True)

        records = [AlertRead(alert_id=alert_id, user_id=request.user.id) for alert_id in alert_ids]
        AlertRead.objects.bulk_create(records, ignore_conflicts=True, batch_size=500)
        return json_response({'marked_count': len(records)})


class AlertResolveView(AdminView):
    PERM_MAP = {'POST': 'system.alert.resolve'}

    def post(self, request, pk):
        with transaction.atomic():
            alert = Alert.objects.select_for_update().filter(pk=pk).first()
            if not alert:
                return json_response(error='告警不存在')
            if alert.status != Alert.STATUS_RESOLVED:
                alert.status = Alert.STATUS_RESOLVED
                alert.resolved_at = timezone.now()
                alert.resolved_by = request.user
                alert.save(update_fields=['status', 'resolved_at', 'resolved_by'])
        AlertRead.objects.get_or_create(alert_id=pk, user_id=request.user.id)
        return json_response()

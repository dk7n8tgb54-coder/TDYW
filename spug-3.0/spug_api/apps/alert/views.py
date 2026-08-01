# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License
import logging
import json
from io import StringIO
from django.core.management import call_command
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from libs.utils import json_response
from libs.parser import JsonParser, Argument
from libs.mixins import AdminView
from apps.alert.models import Alert, AlertRead

logger = logging.getLogger(__name__)


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
            from datetime import timedelta
            # keyword 搜索限制最近 180 天，避免全表扫描
            keyword_cutoff = timezone.now() - timedelta(days=180)
            queryset = queryset.filter(
                Q(title__icontains=form.keyword)
                | Q(alert_key__icontains=form.keyword),
                created_at__gte=keyword_cutoff,
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

    BATCH_SIZE = 500

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
            alert_ids_qs = Alert.objects.filter(status=Alert.STATUS_ACTIVE).values_list('id', flat=True)
        else:
            try:
                ids = {int(item) for item in form.ids if int(item) > 0}
            except (TypeError, ValueError):
                return json_response(error='告警 ID 格式错误')
            alert_ids_qs = Alert.objects.filter(
                id__in=ids, status=Alert.STATUS_ACTIVE
            ).values_list('id', flat=True)

        # 使用 iterator() 流式处理，避免全量加载到内存
        total_marked = 0
        batch = []
        for alert_id in alert_ids_qs.iterator(self.BATCH_SIZE):
            batch.append(AlertRead(alert_id=alert_id, user_id=request.user.id))
            if len(batch) >= self.BATCH_SIZE:
                AlertRead.objects.bulk_create(batch, ignore_conflicts=True, batch_size=self.BATCH_SIZE)
                total_marked += len(batch)
                batch = []
        if batch:
            AlertRead.objects.bulk_create(batch, ignore_conflicts=True, batch_size=self.BATCH_SIZE)
            total_marked += len(batch)
        return json_response({'marked_count': total_marked})


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


class DataQualityCheckView(AdminView):
    """运行数据质量巡检并返回结果"""
    PERM_MAP = {'GET': 'system.alert.view'}

    def get(self, request):
        # stdout=StringIO() 抑制系统检查等额外输出，用返回值获取纯 JSON
        result_str = call_command('data_quality_check', json=True, no_alert=True, stdout=StringIO())
        try:
            result = json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            return json_response(error='巡检结果解析失败')
        return json_response(result)


class AlertTrendView(AdminView):
    """磁盘趋势数据 API，从 Redis ZSet 读取历史指标返回给前端图表"""
    PERM_MAP = {'GET': 'system.alert.view'}

    # 支持查询的指标白名单
    METRIC_NAMES = {
        'disk:documents': '文档存储',
        'disk:chunks': '分片存储',
        'disk:media': '媒体存储',
    }

    def get(self, request):
        form, error = JsonParser(
            Argument('hours', type=int, default=24, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        hours = min(max(form.hours, 1), 168)  # 限制 1-168h（7天）
        from libs.trend import get_trend

        series = []
        for name, label in self.METRIC_NAMES.items():
            trend = get_trend(name, hours)
            if not trend:
                continue
            series.append({
                'name': name,
                'label': label,
                'points': [
                    {'time': ts, 'value': val}
                    for ts, val in trend
                ],
            })

        return json_response({'series': series, 'hours': hours})

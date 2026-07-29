# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""运行日志统计概览服务（第一阶段：轻量聚合统计）。

设计要点：
- 全部使用数据库聚合查询（aggregate / values + annotate），不加载明细。
- 租户隔离由调用方传入 user，内部统一 apply_tenant_filter。
- KPI 卡片基于"非时间筛选"查询集（反映全局当前态）；
  分布/趋势基于"含时间范围"查询集（默认最近 30 天）。
- 不修改运行日志任何业务表与业务流程，仅只读统计。
"""
import logging
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

logger = logging.getLogger(__name__)

# 运行日志状态枚举（与 models.py 保持一致）
UNCLOSED_STATUSES = ['in_progress', 'resolved', 'verified']  # 未闭环：处理中/已解决/已验证
ARCHIVED_STATUS = 'closed'                                   # 已归档
VOIDED_STATUS = 'voided'                                     # 已作废

SEVERITY_LABELS = {'P0': '紧急', 'P1': '重要', 'P2': '一般'}
STATUS_LABELS = {
    'in_progress': '处理中',
    'resolved': '已解决',
    'verified': '已验证',
    'closed': '已归档',
    'voided': '已作废',
}

DEFAULT_RANGE_DAYS = 30          # 默认统计最近 30 天
UNCLOSED_LIST_LIMIT = 20         # 未闭环事件列表最多条数
SYSTEM_TOP_N = 10                # 关联系统排行 Top N


class RunLogStatisticsService:
    """运行日志统计概览服务"""

    @staticmethod
    def get_overview(user, filters=None):
        """获取统计概览数据。

        Args:
            user: 当前请求用户，用于租户隔离。
            filters: 筛选参数字典，支持 start_date/end_date/event_type/system_name/severity/status。

        Returns:
            dict: 包含 kpi / by_status / by_severity / by_type / by_system / trend / unclosed_list。
        """
        from .models import RunLog

        filters = filters or {}
        now = timezone.now()
        today = now.date()

        # 基础查询集（租户隔离）
        base_qs = apply_tenant_filter(RunLog.objects.all(), user)

        # 非时间筛选条件查询集（KPI / 未闭环列表使用）
        non_time_qs = RunLogStatisticsService._apply_non_time_filters(base_qs, filters)

        # 含时间范围筛选查询集（分布 / 趋势使用，默认最近 30 天）
        range_qs, range_start, range_end = RunLogStatisticsService._apply_range(
            non_time_qs, filters, now
        )

        # === 1. KPI 卡片（一次聚合，反映当前态）===
        kpi = RunLogStatisticsService._get_kpi(non_time_qs, today)

        # === 2. 按状态分布（受时间范围筛选）===
        by_status = RunLogStatisticsService._get_distribution(
            range_qs, 'status', STATUS_LABELS
        )

        # === 3. 按级别分布（受时间范围筛选）===
        by_severity = RunLogStatisticsService._get_distribution(
            range_qs, 'severity', SEVERITY_LABELS
        )

        # === 4. 按事件类型分布（受时间范围筛选）===
        by_type = RunLogStatisticsService._get_distribution(range_qs, 'event_type', None)

        # === 5. 按关联系统排行 Top N（受时间范围筛选）===
        by_system = RunLogStatisticsService._get_system_ranking(range_qs)

        # === 6. 最近 N 天事件趋势（受非时间筛选 + 时间范围）===
        trend = RunLogStatisticsService._get_trend(range_qs, range_start, range_end)

        # === 7. 未闭环事件列表（受非时间筛选，按创建时间倒序）===
        unclosed_list = RunLogStatisticsService._get_unclosed_list(non_time_qs)

        return {
            'range': {
                'start_date': range_start.strftime('%Y-%m-%d'),
                'end_date': range_end.strftime('%Y-%m-%d'),
            },
            'kpi': kpi,
            'by_status': by_status,
            'by_severity': by_severity,
            'by_type': by_type,
            'by_system': by_system,
            'trend': trend,
            'unclosed_list': unclosed_list,
        }

    # ------------------------------------------------------------------
    # 筛选条件
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_non_time_filters(queryset, filters):
        """应用非时间筛选条件（event_type / system_name / severity / status）。"""
        if filters.get('event_type'):
            queryset = queryset.filter(event_type=filters['event_type'])
        if filters.get('system_name'):
            queryset = queryset.filter(system_name__icontains=filters['system_name'])
        if filters.get('severity'):
            queryset = queryset.filter(severity=filters['severity'])
        if filters.get('status'):
            queryset = queryset.filter(status=filters['status'])
        return queryset

    @staticmethod
    def _apply_range(queryset, filters, now):
        """应用时间范围筛选，返回 (queryset, start_date, end_date)。

        默认最近 DEFAULT_RANGE_DAYS 天。
        """
        start_date = filters.get('start_date')
        end_date = filters.get('end_date')
        today = now.date()

        if start_date:
            from datetime import datetime as _dt
            try:
                start_date = _dt.strptime(start_date, '%Y-%m-%d').date()
            except ValueError:
                start_date = None
        if end_date:
            from datetime import datetime as _dt
            try:
                end_date = _dt.strptime(end_date, '%Y-%m-%d').date()
            except ValueError:
                end_date = None

        # 默认最近 30 天
        if not start_date and not end_date:
            start_date = today - timedelta(days=DEFAULT_RANGE_DAYS - 1)
            end_date = today
        elif start_date and not end_date:
            end_date = today
        elif end_date and not start_date:
            start_date = end_date - timedelta(days=DEFAULT_RANGE_DAYS - 1)

        # 用 datetime 范围替代 __date，确保走 B-tree 索引
        from libs.date_utils import date_to_datetime
        range_start = date_to_datetime(start_date)
        range_end = date_to_datetime(end_date + timedelta(days=1))
        queryset = queryset.filter(
            created_at__gte=range_start,
            created_at__lt=range_end,
        )
        return queryset, start_date, end_date

    # ------------------------------------------------------------------
    # 统计计算
    # ------------------------------------------------------------------
    @staticmethod
    def _get_kpi(queryset, today):
        """KPI 卡片：事件总数 / 今日新增 / 本月新增 / 未闭环 / 已归档 / P0+P1。

        一次 aggregate 完成，减少数据库往返。
        """
        # 用 datetime 范围替代 __date/__year/__month，确保走 B-tree 索引
        from libs.date_utils import date_to_datetime, date_range
        today_start = date_to_datetime(today)
        tomorrow_start = today_start + timedelta(days=1)
        month_start = date_to_datetime(today.replace(day=1))
        next_month_start = (month_start + timedelta(days=32)).replace(day=1)

        agg = queryset.aggregate(
            total=Count('id'),
            today_new=Count('id', filter=Q(created_at__gte=today_start,
                                           created_at__lt=tomorrow_start)),
            month_new=Count('id', filter=Q(created_at__gte=month_start,
                                           created_at__lt=next_month_start)),
            unclosed=Count('id', filter=Q(status__in=UNCLOSED_STATUSES)),
            archived=Count('id', filter=Q(status=ARCHIVED_STATUS)),
            p0=Count('id', filter=Q(severity='P0')),
            p1=Count('id', filter=Q(severity='P1')),
            high_priority=Count('id', filter=Q(severity__in=['P0', 'P1'])),
        )
        return {
            'total': agg['total'] or 0,
            'today_new': agg['today_new'] or 0,
            'month_new': agg['month_new'] or 0,
            'unclosed': agg['unclosed'] or 0,
            'archived': agg['archived'] or 0,
            'p0': agg['p0'] or 0,
            'p1': agg['p1'] or 0,
            'high_priority': agg['high_priority'] or 0,
        }

    @staticmethod
    def _get_distribution(queryset, field, label_map):
        """分组分布统计，返回 [{key, label, count, percent}]。"""
        total = queryset.count()
        rows = list(
            queryset.values(field).annotate(count=Count('id')).order_by('-count')
        )
        result = []
        for row in rows:
            key = row.get(field) or '未分类'
            count = row['count']
            result.append({
                'key': key,
                'label': label_map.get(key, key) if label_map else key,
                'count': count,
                'percent': round(count / total * 100, 1) if total > 0 else 0,
            })
        return result

    @staticmethod
    def _get_system_ranking(queryset):
        """关联系统排行 Top N。"""
        rows = list(
            queryset.values('system_name')
            .annotate(count=Count('id'))
            .order_by('-count')[:SYSTEM_TOP_N]
        )
        return [{'system_name': r['system_name'] or '未指定', 'count': r['count']}
                for r in rows]

    @staticmethod
    def _get_trend(queryset, start_date, end_date):
        """最近 N 天事件趋势，按日期正序，补齐空日期。"""
        # GROUP BY DATE() 在此可接受：queryset 已由 created_at__gte/__lt 过滤，
        # DATE() 仅作用于小结果集，不影响 WHERE 走索引
        rows = list(
            queryset.values('created_at__date').annotate(count=Count('id'))
        )
        count_map = {r['created_at__date']: r['count'] for r in rows}

        trend = []
        cur = start_date
        while cur <= end_date:
            trend.append({
                'date': cur.strftime('%Y-%m-%d'),
                'count': count_map.get(cur, 0),
            })
            cur += timedelta(days=1)
        return trend

    @staticmethod
    def _get_unclosed_list(queryset):
        """未闭环事件列表（最近 UNCLOSED_LIST_LIMIT 条，按创建时间倒序）。"""
        rows = list(
            queryset.filter(status__in=UNCLOSED_STATUSES)
            .order_by('-created_at', '-id')
            .values('id', 'event_title', 'event_type', 'system_name',
                    'severity', 'status', 'created_at')
            [:UNCLOSED_LIST_LIMIT]
        )
        # 补充中文标签，便于前端直接展示
        for r in rows:
            r['severity_label'] = SEVERITY_LABELS.get(r['severity'], r['severity'])
            r['status_label'] = STATUS_LABELS.get(r['status'], r['status'])
            if r.get('created_at'):
                r['created_at'] = r['created_at'].strftime('%Y-%m-%d %H:%M')
        return rows

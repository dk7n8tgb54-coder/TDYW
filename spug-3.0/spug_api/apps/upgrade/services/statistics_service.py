# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
统计服务 - 后端计算，前端只负责展示

upgrade_time 为 DateTimeField，趋势统计使用逐日范围查询以走索引。
"""
import logging
from datetime import timedelta
from django.db.models import Count

from libs.tenant_utils import apply_tenant_filter

logger = logging.getLogger(__name__)


class StatisticsService:
    """统计服务"""

    @staticmethod
    def get_statistics(user, filters=None):
        """获取统计数据

        Args:
            user: 当前请求用户
            filters: 筛选参数字典

        Returns:
            dict: {total_count, by_type, by_system, trend}
        """
        from ..models import UpgradeRecord

        queryset = apply_tenant_filter(UpgradeRecord.objects.all(), user)

        # 应用筛选
        if filters:
            queryset = StatisticsService._apply_filters(queryset, filters)

        total = queryset.count()

        # 按类型统计
        by_type = list(
            queryset.values('upgrade_type')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        for item in by_type:
            item['percent'] = round(item['count'] / total * 100) if total > 0 else 0

        # 按系统统计
        by_system = list(
            queryset.values('system')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        for item in by_system:
            item['percent'] = round(item['count'] / total * 100) if total > 0 else 0

        # 趋势统计（按日期）- upgrade_time 是 DateTimeField，用范围查询走索引
        trend = StatisticsService._get_trend(queryset)

        return {
            'total_count': total,
            'by_type': by_type,
            'by_system': by_system,
            'trend': trend,
        }

    @staticmethod
    def _get_trend(queryset):
        """获取趋势统计数据（使用逐日范围查询避免 DATE() 函数绕过索引）。

        策略：
        - 日期跨度 <= 365 天：逐日 __gte/__lt 范围查询，每次走索引
        - 日期跨度 > 365 天：回退 TruncDate（单次查询但需临时表）
        """
        try:
            from datetime import datetime as dt
            from django.db.models.functions import TruncDate

            # 获取日期范围
            first = queryset.order_by('upgrade_time').first()
            last = queryset.order_by('-upgrade_time').first()
            if not first or not last or not first.upgrade_time or not last.upgrade_time:
                return []

            start_date = first.upgrade_time.date()
            end_date = last.upgrade_time.date()

            # 跨度超过 365 天时回退 TruncDate（避免 N 次查询）
            delta = (end_date - start_date).days
            if delta > 365:
                return list(
                    queryset.annotate(date=TruncDate('upgrade_time'))
                    .values('date')
                    .annotate(count=Count('id'))
                    .order_by('date')
                )

            # 小范围：逐日范围查询（走索引，无 Using temporary）
            trend = []
            current = start_date
            while current <= end_date:
                next_date = current + timedelta(days=1)
                count = queryset.filter(
                    upgrade_time__gte=current,
                    upgrade_time__lt=next_date,
                ).count()
                if count > 0:
                    trend.append({'date': current.isoformat(), 'count': count})
                current = next_date

            return trend
        except Exception as e:
            logger.warning(f'[Upgrade] 趋势统计失败: {e}')
            return []

    @staticmethod
    def _apply_filters(queryset, filters):
        """应用筛选条件"""
        if filters.get('system'):
            queryset = queryset.filter(system=filters['system'])
        if filters.get('start_date') and filters.get('end_date'):
            queryset = queryset.filter(
                upgrade_time__gte=filters['start_date'],
                upgrade_time__lte=filters['end_date'],
            )
        return queryset

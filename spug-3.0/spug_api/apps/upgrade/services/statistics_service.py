# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
统计服务 - 后端计算，前端只负责展示

当前模型 upgrade_time 为 CharField，使用 extra/date() 函数提取日期。
"""
import logging
from django.db.models import Count
from django.db import connection

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

        # 趋势统计（按日期）- upgrade_time 是 CharField，用 extra 提取日期部分
        trend = StatisticsService._get_trend(queryset)

        return {
            'total_count': total,
            'by_type': by_type,
            'by_system': by_system,
            'trend': trend,
        }

    @staticmethod
    def _get_trend(queryset):
        """获取趋势统计数据（upgrade_time 是 CharField 格式 'YYYY-MM-DD HH:MM:SS'）"""
        try:
            # MySQL: DATE() 函数提取日期部分
            # SQLite: date() 函数提取日期部分
            if connection.vendor == 'sqlite':
                date_expr = "date(upgrade_time)"
            else:
                date_expr = "DATE(upgrade_time)"

            trend = list(
                queryset.extra({'date': date_expr})
                .values('date')
                .annotate(count=Count('id'))
                .order_by('date')
            )
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

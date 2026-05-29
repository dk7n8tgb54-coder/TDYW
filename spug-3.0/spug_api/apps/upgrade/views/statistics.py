# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""后端统计接口"""
from django.views import View
from libs import json_response, auth
from apps.upgrade.services.statistics_service import StatisticsService


class StatisticsView(View):
    """获取统计数据"""

    @auth('upgrade.upgrade.view')
    def get(self, request):
        filters = {}
        if request.GET.get('system'):
            filters['system'] = request.GET.get('system')
        if request.GET.get('start_date') and request.GET.get('end_date'):
            filters['start_date'] = request.GET.get('start_date')
            filters['end_date'] = request.GET.get('end_date')

        data = StatisticsService.get_statistics(
            user=request.user,
            filters=filters if filters else None,
        )
        return json_response(data)

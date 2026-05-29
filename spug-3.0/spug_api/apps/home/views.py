# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from libs.utils import json_response
from libs.parser import JsonParser, Argument
from libs.decorators import auth
from libs.tenant_utils import apply_tenant_filter
import json


@auth('dashboard.dashboard.view')
def get_statistic(request):
    data = {}
    return json_response(data)


class DutyTodayView(View):
    """今日值班视图 - 工作台专用"""
    @auth('dashboard.dashboard.view')
    def get(self, request):
        """获取今日值班记录"""
        from datetime import date
        from apps.schedule.models import Schedule
        today = date.today().strftime('%Y-%m-%d')
        # 从排班表获取今日值班人员
        records = apply_tenant_filter(Schedule.objects.filter(schedule_date__startswith=today), request.user)
        return json_response([x.to_view() for x in records])

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级表单列表视图"""
from django.views import View
from libs import json_response, auth, Argument, JsonParser
from apps.upgrade.services.record_service import RecordService


class RecordListView(View):
    """获取升级表单列表（分页）"""

    @auth('upgrade.upgrade.view')
    def get(self, request):
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))

        filters = {}
        if request.GET.get('status'):
            filters['status'] = request.GET.get('status')
        if request.GET.get('system'):
            filters['system'] = request.GET.get('system')
        if request.GET.get('upgrade_type'):
            filters['upgrade_type'] = request.GET.get('upgrade_type')
        if request.GET.get('owner'):
            filters['owner'] = request.GET.get('owner')
        if request.GET.get('start_date') and request.GET.get('end_date'):
            filters['start_date'] = request.GET.get('start_date')
            filters['end_date'] = request.GET.get('end_date')

        result = RecordService.get_list(
            user=request.user,
            filters=filters if filters else None,
            page=page,
            page_size=page_size,
        )
        return json_response(result)

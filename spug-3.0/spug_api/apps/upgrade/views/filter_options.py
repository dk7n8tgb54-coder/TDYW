# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""筛选选项接口"""
from django.views import View
from libs import json_response, auth
from apps.upgrade.services.record_service import RecordService


class FilterOptionsView(View):
    """获取筛选选项（去重值列表）"""

    @auth('upgrade.upgrade.view')
    def get(self, request):
        data = RecordService.get_filter_options(request.user)
        return json_response(data)

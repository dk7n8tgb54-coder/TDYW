# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级表单详情视图"""
from django.views import View
from libs import json_response, auth
from apps.upgrade.services.record_service import RecordService


class RecordDetailView(View):
    """获取升级表单详情"""

    @auth('upgrade.upgrade.view')
    def get(self, request, pk):
        data, error = RecordService.get_detail(pk, request.user)
        if error:
            return json_response(error=error, status=404)
        return json_response(data)

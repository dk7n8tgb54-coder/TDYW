# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级表单删除视图"""
from django.views import View
from libs import json_response, auth
from apps.upgrade.services.record_service import RecordService


class RecordDeleteView(View):
    """删除升级表单"""

    @auth('upgrade.upgrade.del')
    def delete(self, request, pk):
        error = RecordService.delete_record(pk, request.user)
        if error:
            return json_response(error=error)
        return json_response()

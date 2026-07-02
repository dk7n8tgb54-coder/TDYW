# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级表单更新视图"""
from django.views import View
from libs import json_response, auth, Argument, JsonParser
from apps.upgrade.services.record_service import RecordService


class RecordUpdateView(View):
    """更新升级表单"""

    @auth('upgrade.upgrade.edit')
    def put(self, request, pk):
        form, error = JsonParser(
            Argument('title', required=False),
            Argument('system', required=False),
            Argument('upgrade_type', required=False),
            Argument('version', required=False),
            Argument('upgrade_time', required=False),
            Argument('status', required=False),
            Argument('owner', required=False),
            Argument('upgrade_content', required=False),
            Argument('impact_scope', required=False),
            Argument('risk_desc', required=False),
            Argument('rollback_plan', required=False),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        record, error = RecordService.update_record(
            record_id=pk,
            user=request.user,
            data=form,
        )

        if error:
            return json_response(error=error)

        return json_response()

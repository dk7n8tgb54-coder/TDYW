# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级表单创建视图"""
from django.views import View
from libs import json_response, auth, Argument, JsonParser
from apps.upgrade.services.record_service import RecordService


class RecordCreateView(View):
    """创建升级表单"""

    @auth('upgrade.upgrade.add')
    def post(self, request):
        form, error = JsonParser(
            Argument('upgrade_no', required=False, help='升级单号（不传则自动生成）'),
            Argument('system', help='请输入系统'),
            Argument('upgrade_type', help='请选择升级类型'),
            Argument('version', help='请输入版本'),
            Argument('upgrade_time', help='请选择升级时间'),
            Argument('status', help='请选择状态'),
            Argument('owner', help='请输入负责人'),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        record, error = RecordService.create_record(
            user=request.user,
            record_data=form,
        )

        if error:
            return json_response(error=error)

        # 返回详情
        data, _ = RecordService.get_detail(record.id, request.user)
        return json_response(data)

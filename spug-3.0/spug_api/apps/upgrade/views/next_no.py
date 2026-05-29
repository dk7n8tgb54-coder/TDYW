# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""获取下一个升级单号"""
from django.views import View
from libs import json_response, auth
from apps.upgrade.services.record_service import RecordService


class NextUpgradeNoView(View):
    """获取自动生成的升级单号预览"""

    @auth('upgrade.upgrade.add')
    def get(self, request):
        upgrade_no = RecordService.generate_upgrade_no(request.user)
        return json_response({'upgrade_no': upgrade_no})

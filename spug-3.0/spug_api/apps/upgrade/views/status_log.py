# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级状态日志视图 - 时间线记录/查询/删除"""
import logging

from django.views import View

from libs import json_response, auth, Argument, JsonParser
from libs.tenant_utils import apply_tenant_filter

from ..models import UpgradeRecord
from ..services.status_log_service import StatusLogService

logger = logging.getLogger(__name__)


def _get_record(record_id, user):
    """获取升级表单（带租户过滤），不存在返回 None"""
    return apply_tenant_filter(
        UpgradeRecord.objects.filter(pk=record_id), user
    ).first()


class StatusLogListView(View):
    """状态日志列表 / 动作选项"""

    @auth('upgrade.upgrade.view')
    def get(self, request, record_id):
        # action=options 时返回动作选项列表
        if request.GET.get('action') == 'options':
            return json_response(StatusLogService.get_action_options())

        record = _get_record(record_id, request.user)
        if record is None:
            return json_response(error='升级表单不存在或无权限访问')
        data = StatusLogService.get_logs(record_id, request.user)
        return json_response(data)

    @auth('upgrade.upgrade.edit')
    def post(self, request, record_id):
        record = _get_record(record_id, request.user)
        if record is None:
            return json_response(error='升级表单不存在或无权限访问')

        form, error = JsonParser(
            Argument('action', help='请选择动作类型'),
            Argument('remark', required=False, default=''),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        log, error = StatusLogService.add_log(
            upgrade_id=record_id,
            user=request.user,
            action=form.action,
            remark=form.remark,
        )
        if error:
            return json_response(error=error)

        return json_response({
            'id': log.id,
            'action': log.action,
            'created_at': log.created_at,
        })


class StatusLogDeleteView(View):
    """删除状态日志"""

    @auth('upgrade.upgrade.edit')
    def delete(self, request, pk):
        error = StatusLogService.delete_log(pk, request.user)
        if error:
            return json_response(error=error)
        return json_response()

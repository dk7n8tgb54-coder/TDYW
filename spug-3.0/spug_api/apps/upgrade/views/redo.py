# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""从某阶段重新执行视图 - 预览/执行（预览与执行同口径，执行端重新校验）"""
import logging

from django.views import View

from libs import json_response, auth, Argument, JsonParser
from libs.tenant_utils import apply_tenant_filter
from apps.logs.audit import record_audit_event

from ..models import UpgradeRecord
from ..services.redo_service import RedoFromService

logger = logging.getLogger(__name__)


def _get_record(record_id, user):
    return apply_tenant_filter(
        UpgradeRecord.objects.filter(pk=record_id), user
    ).first()


class RedoPreviewView(View):
    """预览"从某阶段重新执行"的影响范围（真实步骤数据）"""

    @auth('upgrade.upgrade.view')
    def get(self, request, record_id):
        record = _get_record(record_id, request.user)
        if record is None:
            return json_response(error='升级表单不存在或无权限访问')
        target_phase = (request.GET.get('target_phase') or '').strip()
        if not target_phase:
            return json_response(error='请指定目标阶段')
        data, error = RedoFromService.preview(
            upgrade_id=record_id, user=request.user, target_phase=target_phase)
        if error:
            return json_response(error=error)
        return json_response(data)


class RedoExecuteView(View):
    """执行"从某阶段重新执行"：目标阶段及后续阶段重新执行，前面阶段保持原状

    - 只重置工作清单，不代表软件/配置/数据库已实际回滚；
    - 存在后续已完成阶段时必须显式选择 redo/keep（keep 须填理由）；
    - 预览与执行使用同一阶段顺序与统计口径，后端重新校验。
    """

    @auth('upgrade.upgrade.edit')
    def post(self, request, record_id):
        record = _get_record(record_id, request.user)
        if record is None:
            return json_response(error='升级表单不存在或无权限访问')

        form, error = JsonParser(
            Argument('target_phase', help='请指定目标阶段'),
            Argument('later_action', required=False, default=None),
            Argument('later_reason', required=False, default=''),
            Argument('note', required=False, default=''),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        log, error = RedoFromService.execute(
            upgrade_id=record_id,
            user=request.user,
            target_phase=(form.target_phase or '').strip(),
            later_action=form.later_action,
            later_reason=form.later_reason,
            note=form.note,
        )
        if error:
            return json_response(error=error)

        record_audit_event(
            request, 'update', 'upgrade_redo_from',
            target_id=str(record_id),
            target_name=f'从【{form.target_phase}】重新执行',
            detail={'upgrade_id': record_id,
                    'target_phase': form.target_phase,
                    'later_action': form.later_action,
                    'log_id': log.id if log else None}
        )
        return json_response(log.id and {'id': log.id} or {})

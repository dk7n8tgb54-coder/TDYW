# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""升级失败处理视图 - 失败单列表/开始重做/更正失败"""
import logging

from django.views import View

from libs import json_response, auth, Argument, JsonParser
from libs.tenant_utils import apply_tenant_filter
from apps.logs.audit import record_audit_event

from ..models import UpgradeRecord
from ..services.failure_service import FailureService

logger = logging.getLogger(__name__)


def _get_record(record_id, user):
    return apply_tenant_filter(
        UpgradeRecord.objects.filter(pk=record_id), user
    ).first()


def _to_int_list(values):
    """宽容解析步骤 id 列表（int/数字字符串），非法项剔除"""
    result = []
    for v in values or []:
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            result.append(v)
        elif isinstance(v, str) and v.strip().isdigit():
            result.append(int(v.strip()))
    return result


class FailureListView(View):
    """失败处理单列表"""

    @auth('upgrade.upgrade.view')
    def get(self, request, record_id):
        record = _get_record(record_id, request.user)
        if record is None:
            return json_response(error='升级表单不存在或无权限访问')
        data = FailureService.get_failures(record_id, request.user)
        return json_response(data)


class FailureStartRedoView(View):
    """开始重做：选定重做范围（部分步骤/整个阶段），解除失败阻塞"""

    @auth('upgrade.upgrade.edit')
    def post(self, request, record_id, pk):
        record = _get_record(record_id, request.user)
        if record is None:
            return json_response(error='升级表单不存在或无权限访问')

        form, error = JsonParser(
            Argument('step_ids', type=list, required=False, default=[]),
            Argument('all_steps', required=False, default=False, type=bool),
            Argument('note', required=False, default=''),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        result, error = FailureService.start_redo(
            upgrade_id=record_id,
            failure_id=pk,
            user=request.user,
            step_ids=_to_int_list(form.step_ids),
            all_steps=form.all_steps,
            note=form.note,
        )
        if error:
            return json_response(error=error)

        record_audit_event(
            request, 'update', 'upgrade_failure_redo',
            target_id=str(pk),
            target_name='失败处理-开始重做',
            detail={'failure_id': pk, 'upgrade_id': record_id, **(result or {})}
        )
        return json_response(result)


class FailureCorrectView(View):
    """更正失败记录（误标场景）：填写原因，追加更正事件，原失败事件保留"""

    @auth('upgrade.upgrade.edit')
    def post(self, request, record_id, pk):
        record = _get_record(record_id, request.user)
        if record is None:
            return json_response(error='升级表单不存在或无权限访问')

        form, error = JsonParser(
            Argument('reason', help='请填写更正原因'),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        log, error = FailureService.correct_failure(
            upgrade_id=record_id,
            failure_id=pk,
            user=request.user,
            reason=form.reason,
        )
        if error:
            return json_response(error=error)

        record_audit_event(
            request, 'update', 'upgrade_failure_correct',
            target_id=str(pk),
            target_name='失败处理-更正失败记录',
            detail={'failure_id': pk, 'upgrade_id': record_id,
                    'log_id': log.id if log else None}
        )
        return json_response()

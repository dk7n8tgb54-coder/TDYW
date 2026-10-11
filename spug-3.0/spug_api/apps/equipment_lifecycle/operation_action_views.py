# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""设备全生命周期——运行与故障记录状态动作视图（2026-10-11 合并改造）。

承载与状态机/健康重算绑定的动作接口（均行锁 + 状态校验 + 审计，涉及健康
重算的动作在 health_recalc_lock 内 + 单事务完成）：
- complete          异常事件"完成跟进"：跟进中 → 已完成（可重新跟进）；
- identify-fault    异常事件"认定正式故障"：原记录类型变更为 fault、状态进入
                    处置中，保留描述/登记人/附件/全部进展，不创建第二张单；
- recover           正式故障"确认恢复并结案"：处置中 → 已关闭，恢复时间/
                    恢复确认人/结案说明/最终原因分析一次性校验写入；
- cancel            正式故障"撤销登记"：处置中 → 已撤销（原因必填留痕），
                    退出有效统计与健康状态计算；
- reason-analysis   正式故障原因分析专用更新（处置中可修改，已关闭只读）。

日常运行不提供任何状态动作（恒为已记录，后端独立拒绝）。
权限（后端独立校验）：
- complete          operation_record.complete
- identify-fault    operation_record.identify_fault
- recover           operation_record.recover 且同时具备 close（双权限 AND）
- cancel            operation_record.cancel
- reason-analysis   operation_record.edit
"""
import json

from django.db import transaction
from django.utils import timezone
from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle import operation_services
from apps.equipment_lifecycle.operation_models import (
    RECORD_STATUS_CANCELLED,
    RECORD_STATUS_CLOSED,
    RECORD_STATUS_COMPLETED,
    RECORD_STATUS_HANDLING,
    RECORD_TYPE_ABNORMAL,
    RECORD_TYPE_ROUTINE,
)
from apps.equipment_lifecycle.operation_views import (
    AUDIT_TARGET_RECORD,
    _get_record_for_user,
    _parse_dt,
    _read_json_body,
    _record_audit_summary,
    _record_detail_response,
    _reject_retired_params,
    _validate_affects_and_impact,
)


class RecordActionBaseView(View):
    """状态动作视图公共流程：行锁 + 状态校验 + 审计。"""

    ERROR_NOT_FOUND = '记录不存在'

    def get_record_locked(self, request, pk):
        return _get_record_for_user(pk, request.user, for_update=True)

    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        error = _reject_retired_params(body)
        if error:
            return json_response(error=error)
        with transaction.atomic():
            record = self.get_record_locked(request, pk)
            if not record:
                return json_response(error=self.ERROR_NOT_FOUND)
            before_status = record.status
            error = self.handle_locked(request, record, body)
            if error:
                return json_response(error=error)
            record_audit_event(request, 'update', AUDIT_TARGET_RECORD,
                               record.id, record.record_no,
                               before_value={'status': before_status},
                               after_value=_record_audit_summary(record))
            record.refresh_from_db()
        return _record_detail_response(record)

    def handle_locked(self, request, record, body):
        raise NotImplementedError


class RecordCompleteView(RecordActionBaseView):
    """完成跟进：跟进中 → 已完成（异常事件；可重新跟进，不提供普通关闭）。

    重新跟进不设独立端点：追加统一进展即重新跟进（progress 端点）。
    """

    @auth('equipment_lifecycle.operation_record.complete')
    def post(self, request, pk):
        return super().post(request, pk)

    def handle_locked(self, request, record, body):
        if record.record_type != RECORD_TYPE_ABNORMAL:
            return '只有异常事件记录支持完成跟进'
        if record.status == RECORD_STATUS_COMPLETED:
            return '记录已完成，不能重复完成跟进'
        if not record.can_transition_to(RECORD_STATUS_COMPLETED):
            return '当前状态不能完成跟进（仅跟进中的记录可完成跟进）'
        record.status = RECORD_STATUS_COMPLETED
        # 首次完成跟进时间（统计平均处理时长用；重新跟进后再次完成不覆盖）
        if record.resolved_at is None:
            record.resolved_at = timezone.now()
        record.updated_at = timezone.now()
        record.updated_by = request.user
        record.save(update_fields=['status', 'resolved_at', 'updated_at', 'updated_by'])
        return None


class RecordIdentifyFaultView(View):
    """异常事件认定正式故障（原记录原地变更，不创建第二张单）。

    - 仅异常事件且处于 已记录/跟进中 可认定；
    - 认定时补充故障所需字段：是否影响系统运行（默认不影响）、影响程度
      （影响运行时必填）、原因分析（选填）、对象快照（选填）；
    - 保留原描述（情况描述即故障现象）、登记人、附件与全部进展；
    - 行锁防并发重复认定；持健康重算锁 + 单事务，同事务重算健康状态；
    - 后端独立校验 identify_fault 权限。
    """

    @auth('equipment_lifecycle.operation_record.identify_fault')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        error = _reject_retired_params(body)
        if error:
            return json_response(error=error)
        form, error = JsonParser(
            Argument('occurred_at', type=str, required=False, default='',
                     help='故障发生时间（选填，缺省沿用记录原发生时间）'),
            Argument('affects_system_operation', type=bool, required=False, default=False,
                     help='是否影响系统运行，默认不影响（部件故障）'),
            Argument('impact_status', type=str, required=False, default='',
                     help='系统影响程度：影响系统运行时必填（降级/故障/中断）'),
            Argument('reason_analysis', type=str, required=False, default='',
                     help='初步原因分析（选填）'),
            Argument('fault_object_name', type=str, required=False, default=''),
            Argument('fault_object_model', type=str, required=False, default=''),
            Argument('fault_object_sn', type=str, required=False, default=''),
        ).parse(body)
        if error:
            return json_response(error=error)
        occurred_at = None
        if form.occurred_at:
            occurred_at = _parse_dt(form.occurred_at)
            if not occurred_at:
                return json_response(error='故障发生时间格式不正确')
            if occurred_at > timezone.now():
                return json_response(error='故障发生时间不能晚于当前时间')
        affects, impact_status, err = _validate_affects_and_impact(form)
        if err:
            return json_response(error=err)
        try:
            with operation_services.health_recalc_lock():
                with transaction.atomic():
                    record = _get_record_for_user(pk, request.user, for_update=True)
                    if not record:
                        return json_response(error='记录不存在')
                    record = operation_services.identify_record_as_fault(
                        record=record,
                        created_by=request.user,
                        occurred_at=occurred_at,
                        affects_system_operation=affects,
                        impact_status=impact_status,
                        reason_analysis=form.reason_analysis or '',
                        fault_object_name=form.fault_object_name or '',
                        fault_object_model=form.fault_object_model or '',
                        fault_object_sn=form.fault_object_sn or '',
                        request=request,
                    )
                    record_audit_event(request, 'update', AUDIT_TARGET_RECORD,
                                       record.id, record.record_no,
                                       after_value={
                                           'action': 'identify_fault',
                                           'record_type': record.record_type,
                                           'status': record.status,
                                           'affects_system_operation':
                                               record.affects_system_operation,
                                           'impact_status': record.impact_status,
                                       })
                    record.refresh_from_db()
        except (operation_services.HealthRecalcLockTimeout,
                operation_services.IdentifyFaultError) as exc:
            return json_response(error=str(exc))
        return _record_detail_response(record)


def _resolve_final_reason(record, form):
    """结案最终原因解析：未提交时保留原值；选择"原因未明"必须填写未明说明。

    返回 (reason_analysis, reason_unknown, error)。
    """
    final_reason = (form.reason_analysis if form.reason_analysis is not None
                    else record.reason_analysis) or ''
    final_reason = final_reason.strip()[:2000]
    final_unknown = (bool(form.reason_unknown)
                     if form.reason_unknown is not None else record.reason_unknown)
    if final_unknown and not final_reason:
        return '', False, '选择"原因未明"时请填写未明说明（目前排查情况）'
    return final_reason, final_unknown, None


class RecordRecoverView(View):
    """确认恢复并结案（正式故障）：处置中 → 已关闭，单次事务。

    - 恢复时间/恢复确认人/结案说明一次性校验写入（结案说明必填）；
    - 最终原因分析随结案一并提交：默认回填处置中的原因分析，可修改或改为
      "原因未明"+未明说明；未提交时保留原值；
    - 仅处置中的故障可结案：已关闭/已撤销不能重复结案（终态保护）；
    - 健康状态重算在同一事务内执行一次；
    - 合并操作须同时具备 recover 与 close 两项权限（后端独立校验）。
    """

    @auth('equipment_lifecycle.operation_record.recover')
    def post(self, request, pk):
        if not request.user.has_perms(['equipment_lifecycle.operation_record.close']):
            return json_response(error='权限拒绝')
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        error = _reject_retired_params(body)
        if error:
            return json_response(error=error)
        try:
            with operation_services.health_recalc_lock():
                with transaction.atomic():
                    record = _get_record_for_user(pk, request.user, for_update=True)
                    if not record:
                        return json_response(error='记录不存在')
                    before_status = record.status
                    before_summary = _record_audit_summary(record)
                    error = self._recover_locked(request, record, body)
                    if error:
                        return json_response(error=error)
                    record_audit_event(request, 'update', AUDIT_TARGET_RECORD,
                                       record.id, record.record_no,
                                       before_value={
                                           **before_summary,
                                           'status': before_status,
                                       },
                                       after_value=_record_audit_summary(record))
                    record.refresh_from_db()
        except operation_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        return _record_detail_response(record)

    @staticmethod
    def _recover_locked(request, record, body):
        form, error = JsonParser(
            Argument('recovered_at', type=str, required=True, help='恢复时间'),
            Argument('recovered_by_name', type=str, required=False, default=None,
                     help='恢复确认人姓名（手动输入必填，多人以顿号分隔）'),
            Argument('recovery_close_note', type=str, required=True,
                     help='结案说明（不能为空或纯空格）'),
            Argument('reason_analysis', type=str, required=False, default=None,
                     help='最终原因分析（未提交时保留原值）'),
            Argument('reason_unknown', type=bool, required=False, default=None,
                     help='原因未明：确实无法确定原因时为 True，未提交时保留原值'),
        ).parse(body)
        if error:
            return error
        if record.record_type != 'fault' or record.status != RECORD_STATUS_HANDLING:
            return '只有处置中的正式故障才能确认恢复并结案'
        recovered_at = _parse_dt(form.recovered_at)
        if not recovered_at:
            return '恢复时间格式不正确，应为 YYYY-MM-DD HH:MM'
        if recovered_at < record.occurred_at:
            return '恢复时间不能早于故障发生时间'
        if recovered_at > timezone.now():
            return '恢复时间不能晚于当前时间'
        recovered_by_name = (form.recovered_by_name or '').strip()
        if not recovered_by_name:
            return '恢复确认人不能为空'
        recovery_close_note = (form.recovery_close_note or '').strip()
        if not recovery_close_note:
            return '结案说明不能为空'
        final_reason, final_unknown, reason_error = _resolve_final_reason(record, form)
        if reason_error:
            return reason_error
        record.recovered_at = recovered_at
        record.recovery_close_note = recovery_close_note[:3000]
        record.recovered_by_name = recovered_by_name[:200]
        record.recovered_confirmed_at = timezone.now()
        record.reason_analysis = final_reason
        record.reason_unknown = final_unknown
        record.status = RECORD_STATUS_CLOSED
        record.updated_at = timezone.now()
        record.updated_by = request.user
        record.save()
        # 健康状态重算只执行一次（同事务，以全部有效影响的重新查询结果为准）
        operation_services.recompute_systems_health(
            record.tenant_id, [record.system_id], request=request,
            audit_reason='确认恢复并结案 ' + record.record_no)
        return None


class RecordCancelView(View):
    """撤销故障登记（正式故障）：处置中 → 已撤销，不物理删除。

    - 用于撤销错误或重复的故障登记：撤销后历史记录保留可追溯，
      该记录退出有效统计与健康状态计算；
    - 仅处置中的故障可撤销：已关闭不能撤销，已撤销为终态不能重复撤销；
    - 撤销原因必填，撤销人/撤销时间落库留痕。
    """

    @auth('equipment_lifecycle.operation_record.cancel')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        try:
            with operation_services.health_recalc_lock():
                with transaction.atomic():
                    record = _get_record_for_user(pk, request.user, for_update=True)
                    if not record:
                        return json_response(error='记录不存在')
                    before_status = record.status
                    form, error = JsonParser(
                        Argument('cancel_reason', type=str, required=True, help='撤销原因'),
                    ).parse(body)
                    if error:
                        return json_response(error=error)
                    if not form.cancel_reason.strip():
                        return json_response(error='撤销原因不能为空')
                    if record.record_type != 'fault':
                        return json_response(error='只有正式故障支持撤销登记')
                    if record.status == RECORD_STATUS_CLOSED:
                        return json_response(error='已关闭的故障不能撤销：已关闭表示真实故障已完成结案')
                    if record.status != RECORD_STATUS_HANDLING:
                        return json_response(error='该故障登记已撤销，不能重复撤销')
                    before_summary = _record_audit_summary(record)
                    record.status = RECORD_STATUS_CANCELLED
                    record.cancel_reason = form.cancel_reason.strip()[:200]
                    record.cancelled_at = timezone.now()
                    record.cancelled_by = request.user
                    record.updated_at = timezone.now()
                    record.updated_by = request.user
                    record.save()
                    operation_services.recompute_systems_health(
                        record.tenant_id, [record.system_id], request=request,
                        audit_reason='故障撤销登记 ' + record.record_no)
                    record_audit_event(request, 'delete', AUDIT_TARGET_RECORD,
                                       record.id, record.record_no,
                                       before_value={**before_summary,
                                                     'status': before_status},
                                       after_value=_record_audit_summary(record))
                    record.refresh_from_db()
        except operation_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        return _record_detail_response(record)


class RecordReasonAnalysisView(View):
    """原因分析专用更新（正式故障）：详情页"补充原因分析/修改"弹窗保存出口。

    - 只处理原因分析（reason_analysis + reason_unknown），不要求重新提交
      系统/发生时间等无关字段；
    - 仅处置中的故障可修改：已关闭为终态（最终原因只读）、已撤销封闭；
    - "原因未明"勾选后未明说明仍存入 reason_analysis，且必须填写说明；
    - 原因分析不影响系统健康状态，不触发重算；复用 edit 权限与审计。
    """

    @auth('equipment_lifecycle.operation_record.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        error = _reject_retired_params(body)
        if error:
            return json_response(error=error)
        form, error = JsonParser(
            Argument('reason_analysis', type=str, required=False, default='',
                     help='原因分析文本（原因未明时为未明说明）'),
            Argument('reason_unknown', type=bool, required=False, default=False,
                     help='原因未明：确实无法确定原因时为 True'),
        ).parse(body)
        if error:
            return json_response(error=error)
        reason_analysis = (form.reason_analysis or '').strip()[:2000]
        reason_unknown = bool(form.reason_unknown)
        if reason_unknown and not reason_analysis:
            return json_response(error='选择"原因未明"时请填写未明说明（目前排查情况）')
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='记录不存在')
            if record.record_type == RECORD_TYPE_ROUTINE or not record.is_fault:
                return json_response(error='只有正式故障支持原因分析')
            if record.status != RECORD_STATUS_HANDLING:
                return json_response(error='已关闭或已撤销的故障不能修改原因分析')
            before_summary = _record_audit_summary(record)
            record.reason_analysis = reason_analysis
            record.reason_unknown = reason_unknown
            record.updated_at = timezone.now()
            record.updated_by = request.user
            record.save(update_fields=['reason_analysis', 'reason_unknown',
                                       'updated_at', 'updated_by'])
            record_audit_event(request, 'update', AUDIT_TARGET_RECORD, record.id,
                               record.record_no, before_value=before_summary,
                               after_value=_record_audit_summary(record))
        record.refresh_from_db()
        return _record_detail_response(record)

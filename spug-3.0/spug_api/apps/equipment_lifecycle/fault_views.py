# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——系统故障处置与系统健康状态联动视图（步骤 3.1，单系统简化）。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.fault.view|add|edit|handle|recover|close|del|export

设计要点：
- 一张故障单只关联一个故障系统；业务关联一律使用系统 ID（LifecycleSystem 主键），
  页面仅显示名称，不建设主/受影响系统等跨系统关系；
- 故障系统提交时由后端重新查询校验（租户、可用性），
  不信任前端传来的名称或状态；
- 状态流转只经动作接口（start/recover/close/cancel），普通编辑不允许改状态；
- 所有改变有效故障影响的写操作在 health_recalc_lock 内 + 单事务中完成，
  系统健康状态由 fault_services 统一重算（同事务写入）；
- 创建接口以业务字段窗口期查重 + 唯一编号约束防重复提交；
- 首报表单精简（2026-09）：手工新增只保留核心字段；编辑未提交对象名称/
  型号/序列号等旧设备字段时保留原值，不静默清空历史数据；
- 字段退役（2026-09-29）：处置负责人（handler）、发现方式（discovery）、
  级别（level）、影响范围（impact_scope）、故障位置（fault_location）字段
  已整体删除，相关入参/筛选/导出列一并移除；旧参数出现即拒绝，不静默忽略；
- 人员字段（2026-09）：故障登记人 registrar_name 与恢复确认人
  recovered_by_name 均为手动输入姓名（实际登记/确认的人，手工操作必填、
  不预填当前用户，可与 created_by 登录账号不同）；处理进展的进展记录人
  recorder_name 同为手动输入姓名（见 fault_progress_views）。均只表示
  "谁登记/谁确认/谁记录"，姓名为文本快照、不关联 User（实际操作人可能
  没有系统账号）；台账异常转故障等程序化入口由服务层自动登记操作人姓名；
- 写操作记录业务审计（record_audit_event）。

2026-09-30 工单功能整体删除：本模块自 work_order_views.py 接管
"台账异常明细转故障"视图（LedgerItemConvertToFaultView，故障链路），
故障生成维修工单/台账异常转工单等工单链路一并删除。
"""
import csv
import io
import json
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from libs.idempotency import check_recent_duplicate
from libs.tenant_utils import apply_tenant_filter
from apps.logs.audit import record_audit_event
from apps.equipment_lifecycle import event_services, fault_services
from apps.equipment_lifecycle.models import (
    ITEM_RESULT_ABNORMAL,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_RETURNED,
    LEDGER_STATUS_VOID,
    LEGACY_LEDGER_TYPE_INSPECTION,
    LEDGER_TYPE_TEXT,
    LifecycleSystem,
    OperationLedgerItem,
    SystemFault,
)

AUDIT_TARGET_FAULT = 'el_system_fault'
AUDIT_TARGET_HEALTH = fault_services.AUDIT_TARGET_HEALTH

# 允许普通编辑与追加处理进展的故障状态（closed/cancelled 均不允许）
EDITABLE_FAULT_STATUSES = (
    SystemFault.STATUS_PENDING, SystemFault.STATUS_HANDLING, SystemFault.STATUS_RECOVERED,
)
# 允许作废的状态（已关闭为终态，不可再作废）
CANCELLABLE_FAULT_STATUSES = EDITABLE_FAULT_STATUSES

DATETIME_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%dT%H:%M', '%Y-%m-%d')

IDEMPOTENCY_WINDOW_SECONDS = 30


def _read_json_body(request):
    try:
        body = json.loads(request.body.decode('utf-8')) if request.body else {}
    except (ValueError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _parse_dt(value):
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    return None


def _get_fault_for_user(pk, user, for_update=False):
    qs = apply_tenant_filter(SystemFault.objects.select_related('system'), user)
    if for_update:
        qs = qs.select_for_update()
    return qs.filter(pk=pk).first()


def _get_active_system_for_user(pk, user):
    """取本租户可用（未停用）系统：新建/变更故障关联只允许选择可用系统。"""
    return apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(
        pk=pk, is_active=True).first()


# 已随字段删除下线的旧参数（单系统简化 + 2026-09 字段退役）：
# 出现即拒绝，不静默忽略（避免旧客户端提交的字段被无声丢弃）
REMOVED_FAULT_PARAMS = (
    'affected_systems', 'discovery', 'level', 'impact_scope', 'fault_location', 'handler_id',
)


def _validate_removed_params_rejected(body):
    """旧参数已随字段删除下线：出现即拒绝，不静默忽略。"""
    present = [name for name in REMOVED_FAULT_PARAMS if name in body]
    if present:
        return '故障已不再支持参数：' + '、'.join(present) + '，请更新后重新提交'
    return None


def _validate_affects_and_impact(form, fallback_affects=False, fallback_impact=''):
    """校验"影响系统运行"开关与影响程度，返回 (affects, impact_status, error)。

    默认"部件故障但不影响系统运行"：affects=False 时影响程度强制存空串；
    仅明确选择影响系统运行时，才要求影响程度（降级/故障/中断）。
    编辑场景开关未显式提交时（fallback 传入原故障取值）保持原影响设置不变，
    避免旧载荷编辑静默把"影响运行"的故障翻转成"不影响运行"。
    """
    if form.affects_system_operation is None:
        return bool(fallback_affects), fallback_impact or '', None
    affects = bool(form.affects_system_operation)
    impact_status = (form.impact_status or '').strip()
    if affects:
        if impact_status not in SystemFault.IMPACT_TEXT_MAP:
            return False, '', '影响系统运行时必须选择影响程度（降级/故障/中断）'
    else:
        impact_status = ''
    return affects, impact_status, None


def _validate_fault_fields(form):
    """校验故障发生时间，返回 (occurred_at, error)。

    发现方式/级别/处置负责人字段已删除（2026-09），仅校验发生时间。
    """
    occurred_at = _parse_dt(form.occurred_at)
    if not occurred_at:
        return None, '故障发生时间格式不正确，应为 YYYY-MM-DD HH:MM'
    if occurred_at > timezone.now():
        return None, '故障发生时间不能晚于当前时间'
    return occurred_at, None


def _validate_fault_system(form, request, for_update=False, fault=None):
    """校验故障系统，返回 (system, error)。"""
    system = _get_active_system_for_user(form.system, request.user)
    if not system:
        if for_update and fault and fault.system_id == form.system:
            # 未变更的故障系统即使是停用系统也保持原关联（历史故障继续可查）
            system = fault.system
        else:
            return None, '故障系统不存在、已停用或无权限'
    return system, None


def _fault_audit_summary(fault):
    summary = {
        'fault_no': fault.fault_no,
        'status': fault.status,
        'system': fault.system_name,
        'affects_system_operation': fault.affects_system_operation,
        'impact_status': fault.impact_status,
    }
    if fault.status == SystemFault.STATUS_CANCELLED and fault.cancel_reason:
        summary['cancel_reason'] = fault.cancel_reason
    return summary


def _fault_optional_fields(form):
    """故障可选文本字段规范化（strip 限长由创建服务统一处理）。"""
    return {
        'fault_object_name': form.fault_object_name or '',
        'fault_object_model': form.fault_object_model or '',
        'fault_object_sn': form.fault_object_sn or '',
        'reason_analysis': form.reason_analysis or '',
    }


def _apply_fault_text_fields(fault, form):
    """编辑故障时写入可选文本字段（统一 strip 限长）。

    未提交（None）的字段保留原值：精简后的表单不再携带对象型号/序列号等
    历史字段，编辑旧故障时不得静默清空历史数据。
    """
    if form.fault_object_name is not None:
        fault.fault_object_name = form.fault_object_name.strip()[:100]
    if form.fault_object_model is not None:
        fault.fault_object_model = form.fault_object_model.strip()[:100]
    if form.fault_object_sn is not None:
        fault.fault_object_sn = form.fault_object_sn.strip()[:100]
    if form.reason_analysis is not None:
        fault.reason_analysis = form.reason_analysis.strip()[:2000]


class FaultView(View):
    """故障列表 / 新增。"""

    @auth('equipment_lifecycle.fault.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('system', type=int, required=False),
            Argument('status', type=str, required=False),
            Argument('keyword', type=str, required=False),
            Argument('occurred_from', type=str, required=False),
            Argument('occurred_to', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        query = apply_tenant_filter(SystemFault.objects.all(), request.user)
        if form.status:
            if form.status not in SystemFault.STATUS_TEXT_MAP:
                return json_response(error='故障状态筛选值不合法')
            query = query.filter(status=form.status)
        if form.system:
            query = query.filter(system_id=form.system)
        if form.keyword:
            query = query.filter(
                Q(fault_no__icontains=form.keyword) | Q(phenomenon__icontains=form.keyword) |
                Q(system_name__icontains=form.keyword))
        # 时间筛选用 __gte/__lt（项目禁用 DateTimeField __date 等查询）
        occurred_from = _parse_dt(form.occurred_from) if form.occurred_from else None
        occurred_to = _parse_dt(form.occurred_to) if form.occurred_to else None
        if form.occurred_from and not occurred_from:
            return json_response(error='发生时间起始格式不正确')
        if form.occurred_to and not occurred_to:
            return json_response(error='发生时间截止格式不正确')
        if occurred_from:
            query = query.filter(occurred_at__gte=occurred_from)
        if occurred_to:
            query = query.filter(occurred_at__lt=occurred_to)

        from libs.pagination import paginate
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.fault.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        form, error = JsonParser(
            Argument('system', type=int, required=True, help='故障系统ID'),
            Argument('affects_system_operation', type=bool, required=False, default=False,
                     help='是否影响系统运行，默认不影响（部件故障/离线维修）'),
            Argument('impact_status', type=str, required=False, default='',
                     help='系统影响程度：影响系统运行时必填（降级/故障/中断）'),
            Argument('occurred_at', type=str, required=True, help='故障发生时间'),
            Argument('phenomenon', type=str, required=True, help='故障现象'),
            Argument('fault_object_name', type=str, required=False, default=''),
            Argument('fault_object_model', type=str, required=False, default=''),
            Argument('fault_object_sn', type=str, required=False, default=''),
            Argument('reason_analysis', type=str, required=False, default=''),
            Argument('registrar_name', type=str, required=False, default=None,
                     help='故障登记人姓名（手动输入必填，不预填；实际添加本条故障记录的人，'
                          '多人以顿号分隔；与登录账号审计字段 created_by 独立）'),
        ).parse(body)
        if error:
            return json_response(error=error)
        err = _validate_removed_params_rejected(body)
        if err:
            return json_response(error=err)

        system, err = _validate_fault_system(form, request)
        if err:
            return json_response(error=err)
        occurred_at, err = _validate_fault_fields(form)
        if err:
            return json_response(error=err)
        affects, impact_status, err = _validate_affects_and_impact(form)
        if err:
            return json_response(error=err)
        phenomenon = form.phenomenon.strip()
        if not phenomenon:
            return json_response(error='故障现象不能为空')
        # 登记人手动输入必填（不默认当前登录用户）
        registrar_name = (form.registrar_name or '').strip()
        if not registrar_name:
            return json_response(error='故障登记人不能为空')

        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    # 防重复提交：同租户/同系统/同发生时间/同现象在窗口期内视为重复
                    if check_recent_duplicate(SystemFault, {
                        'tenant_id': request.user.tenant_id,
                        'system_id': system.id,
                        'occurred_at': occurred_at,
                        'phenomenon': phenomenon,
                    }, window_seconds=IDEMPOTENCY_WINDOW_SECONDS):
                        return json_response(error='请勿重复提交相同故障')
                    # 统一走正式故障创建服务（台账异常转故障复用同一路径）
                    fault = fault_services.create_fault_record(
                        tenant_id=request.user.tenant_id,
                        created_by=request.user,
                        system=system,
                        affects_system_operation=affects,
                        impact_status=impact_status,
                        occurred_at=occurred_at,
                        phenomenon=phenomenon,
                        registrar_name=registrar_name,
                        **_fault_optional_fields(form),
                        source_type=SystemFault.SOURCE_MANUAL,
                        request=request,
                    )
                    record_audit_event(request, 'create', AUDIT_TARGET_FAULT, fault.id,
                                       fault.fault_no, after_value=_fault_audit_summary(fault))
        except (fault_services.HealthRecalcLockTimeout,
                fault_services.FaultNoExhausted) as exc:
            return json_response(error=str(exc))
        return json_response(fault.to_detail_view())


class FaultDetailView(View):
    """故障详情 / 编辑未关闭故障。"""

    @auth('equipment_lifecycle.fault.view')
    def get(self, request, pk):
        fault = _get_fault_for_user(pk, request.user)
        if not fault:
            return json_response(error='故障记录不存在')
        return json_response(fault.to_detail_view())

    @auth('equipment_lifecycle.fault.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        form, error = JsonParser(
            Argument('system', type=int, required=True, help='故障系统ID'),
            Argument('affects_system_operation', type=bool, required=False, default=None,
                     help='是否影响系统运行；编辑未提交时保留原值'),
            Argument('impact_status', type=str, required=False, default='',
                     help='系统影响程度：影响系统运行时必填（降级/故障/中断）'),
            Argument('occurred_at', type=str, required=True, help='故障发生时间'),
            Argument('phenomenon', type=str, required=True, help='故障现象'),
            Argument('fault_object_name', type=str, required=False, default=None),
            Argument('fault_object_model', type=str, required=False, default=None),
            Argument('fault_object_sn', type=str, required=False, default=None),
            Argument('reason_analysis', type=str, required=False, default=None),
        ).parse(body)
        if error:
            return json_response(error=error)
        err = _validate_removed_params_rejected(body)
        if err:
            return json_response(error=err)

        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    fault = _get_fault_for_user(pk, request.user, for_update=True)
                    if not fault:
                        return json_response(error='故障记录不存在')
                    if fault.status not in EDITABLE_FAULT_STATUSES:
                        return json_response(error='已关闭或已作废的故障不能编辑')
                    # 修改前后的系统都需要重算（影响可能消失或新增）
                    related_ids = {fault.system_id}

                    system, err = _validate_fault_system(
                        form, request, for_update=True, fault=fault)
                    if err:
                        return json_response(error=err)
                    occurred_at, err = _validate_fault_fields(form)
                    if err:
                        return json_response(error=err)
                    affects, impact_status, err = _validate_affects_and_impact(
                        form, fallback_affects=fault.affects_system_operation,
                        fallback_impact=fault.impact_status)
                    if err:
                        return json_response(error=err)
                    phenomenon = form.phenomenon.strip()
                    if not phenomenon:
                        return json_response(error='故障现象不能为空')

                    before_summary = _fault_audit_summary(fault)
                    old_system = fault.system
                    fault.system = system
                    fault.affects_system_operation = affects
                    fault.impact_status = impact_status
                    fault.system_code = system.system_code
                    fault.system_name = system.name
                    fault.system_location = system.install_location
                    fault.occurred_at = occurred_at
                    fault.phenomenon = phenomenon[:2000]
                    _apply_fault_text_fields(fault, form)
                    fault.updated_at = timezone.now()
                    fault.updated_by = request.user
                    fault.save()

                    related_ids.add(system.id)
                    fault_services.recompute_systems_health(
                        request.user.tenant_id, related_ids, request=request,
                        audit_reason='编辑故障 ' + fault.fault_no)
                    record_audit_event(request, 'update', AUDIT_TARGET_FAULT, fault.id,
                                       fault.fault_no, before_value=before_summary,
                                       after_value=_fault_audit_summary(fault))
                    fault.refresh_from_db()
        except fault_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        return json_response(fault.to_detail_view())


class FaultActionBaseView(View):
    """状态动作视图公共流程：行锁 + 状态校验 + 同事务重算 + 审计。"""

    ACTION_NAME = ''

    def get_fault_locked(self, request, pk):
        return _get_fault_for_user(pk, request.user, for_update=True)

    def post(self, request, pk):
        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    fault = self.get_fault_locked(request, pk)
                    if not fault:
                        return json_response(error='故障记录不存在')
                    before_status = fault.status
                    error = self.handle_locked(request, fault)
                    if error:
                        return json_response(error=error)
                    record_audit_event(request, self.audit_action, AUDIT_TARGET_FAULT,
                                       fault.id, fault.fault_no,
                                       before_value={'status': before_status},
                                       after_value=_fault_audit_summary(fault))
        except fault_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        fault.refresh_from_db()
        return json_response(fault.to_detail_view())

    def handle_locked(self, request, fault):
        raise NotImplementedError

    def recompute(self, request, fault, reason):
        fault_services.recompute_systems_health(
            fault.tenant_id, [fault.system_id], request=request, audit_reason=reason)


class FaultStartView(FaultActionBaseView):
    """开始处置：待处置 → 处置中。"""

    ACTION_NAME = '开始处置'
    audit_action = 'update'

    @auth('equipment_lifecycle.fault.handle')
    def post(self, request, pk):
        return super().post(request, pk)

    def handle_locked(self, request, fault):
        if fault.status != SystemFault.STATUS_PENDING:
            return '只有待处置的故障才能开始处置'
        body = _read_json_body(request) or {}
        # 处置负责人字段已删除（2026-09）：旧客户端提交 handler_id 显式拒绝
        if 'handler_id' in body:
            return '故障已不再支持参数：handler_id，请更新后重新提交'
        fault.status = SystemFault.STATUS_HANDLING
        fault.updated_at = timezone.now()
        fault.updated_by = request.user
        fault.save(update_fields=['status', 'updated_at', 'updated_by'])
        self.recompute(request, fault, '开始处置 ' + fault.fault_no)
        return None


class FaultRecoverView(FaultActionBaseView):
    """确认恢复：处置中 → 已恢复（未恢复确认的故障不能关闭）。"""

    ACTION_NAME = '确认恢复'
    audit_action = 'update'

    @auth('equipment_lifecycle.fault.recover')
    def post(self, request, pk):
        return super().post(request, pk)

    def handle_locked(self, request, fault):
        if fault.status != SystemFault.STATUS_HANDLING:
            return '只有处置中的故障才能确认恢复'
        body = _read_json_body(request) or {}
        form, error = JsonParser(
            Argument('recovered_at', type=str, required=True, help='恢复时间'),
            Argument('recovered_by_name', type=str, required=False, default=None,
                     help='恢复确认人姓名（手动输入必填，不预填；实际确认恢复的人，'
                          '多人以顿号分隔；与登录账号审计字段独立，不关联 User）'),
            Argument('recover_confirm', type=str, required=True, help='恢复确认信息'),
            Argument('final_result', type=str, required=False, default=''),
        ).parse(body)
        if error:
            return error
        recovered_at = _parse_dt(form.recovered_at)
        if not recovered_at:
            return '恢复时间格式不正确，应为 YYYY-MM-DD HH:MM'
        if recovered_at < fault.occurred_at:
            return '恢复时间不能早于故障发生时间'
        # 恢复确认人手动输入必填（不默认当前登录用户，参照故障登记人口径）
        recovered_by_name = (form.recovered_by_name or '').strip()
        if not recovered_by_name:
            return '恢复确认人不能为空'
        if not form.recover_confirm.strip():
            return '恢复确认信息不能为空'
        fault.status = SystemFault.STATUS_RECOVERED
        fault.recovered_at = recovered_at
        fault.recover_confirm = form.recover_confirm.strip()[:1000]
        fault.recovered_by_name = recovered_by_name[:200]
        fault.recovered_confirmed_at = timezone.now()
        if form.final_result and form.final_result.strip():
            fault.final_result = form.final_result.strip()[:2000]
        fault.updated_at = timezone.now()
        fault.updated_by = request.user
        fault.save()
        # 步骤 3.4：恢复确认履历（主体 + 受影响，同一事务）
        event_services.record_fault_lifecycle_events(
            fault, 'recover', occurred_at=recovered_at, created_by=request.user)
        self.recompute(request, fault, '故障恢复 ' + fault.fault_no)
        return None


class FaultCloseView(FaultActionBaseView):
    """关闭故障：已恢复 → 已关闭（须已填写恢复时间、确认人与最终结果）。"""

    ACTION_NAME = '关闭'
    audit_action = 'update'

    @auth('equipment_lifecycle.fault.close')
    def post(self, request, pk):
        return super().post(request, pk)

    def handle_locked(self, request, fault):
        if fault.status != SystemFault.STATUS_RECOVERED:
            return '只有已恢复（完成恢复确认）的故障才能关闭'
        body = _read_json_body(request) or {}
        form, error = JsonParser(
            Argument('final_result', type=str, required=False, default=''),
        ).parse(body)
        if error:
            return error
        final_result = (form.final_result or fault.final_result or '').strip()
        if not final_result:
            return '未填写最终结果，不能关闭'
        if not fault.recovered_at or not fault.recovered_by_name.strip() \
                or not fault.recover_confirm.strip():
            return '缺少恢复时间、恢复确认人或恢复确认信息，不能关闭'
        fault.final_result = final_result[:2000]
        fault.status = SystemFault.STATUS_CLOSED
        fault.updated_at = timezone.now()
        fault.updated_by = request.user
        fault.save()
        # 步骤 3.4：故障关闭履历（主体 + 受影响，同一事务）
        event_services.record_fault_lifecycle_events(
            fault, 'close', created_by=request.user)
        self.recompute(request, fault, '故障关闭 ' + fault.fault_no)
        return None


class FaultCancelView(FaultActionBaseView):
    """受控作废（del 权限）：不物理删除，已作废故障不参与健康状态计算。"""

    ACTION_NAME = '作废'
    audit_action = 'delete'

    @auth('equipment_lifecycle.fault.del')
    def post(self, request, pk):
        return super().post(request, pk)

    def handle_locked(self, request, fault):
        if fault.status not in CANCELLABLE_FAULT_STATUSES:
            return '已关闭的故障不能作废'
        body = _read_json_body(request) or {}
        form, error = JsonParser(
            Argument('cancel_reason', type=str, required=True, help='作废原因'),
        ).parse(body)
        if error:
            return error
        if not form.cancel_reason.strip():
            return '作废原因不能为空'
        fault.status = SystemFault.STATUS_CANCELLED
        fault.cancel_reason = form.cancel_reason.strip()[:200]
        fault.updated_at = timezone.now()
        fault.updated_by = request.user
        fault.save()
        # 步骤 3.4：受控作废履历（追加新事件，原事件保留；主体 + 受影响）
        event_services.record_fault_lifecycle_events(
            fault, 'cancel', detail={'cancel_reason': fault.cancel_reason},
            created_by=request.user)
        self.recompute(request, fault, '故障作废 ' + fault.fault_no)
        return None


class FaultCandidateSystemsView(View):
    """故障表单系统候选项：本租户可用系统（请求只提交系统 ID）。"""

    @auth('equipment_lifecycle.fault.view')
    def get(self, request):
        systems = apply_tenant_filter(
            LifecycleSystem.objects.all(), request.user
        ).filter(is_active=True).order_by('system_code')
        return json_response({'data': [{
            'id': s.id,
            'system_code': s.system_code,
            'name': s.name,
            'install_location': s.install_location,
        } for s in systems]})


class SystemFaultListView(View):
    """按系统查询故障（系统详情"故障记录"页签，单系统简化）。

    只返回故障系统为当前系统的故障，不再区分主体/受影响角色。
    """

    @auth('equipment_lifecycle.fault.view')
    def get(self, request, pk):
        system = apply_tenant_filter(LifecycleSystem.objects.all(), request.user).filter(
            pk=pk).first()
        if not system:
            return json_response(error='系统不存在')
        query = apply_tenant_filter(SystemFault.objects.all(), request.user).filter(
            system=system)
        from libs.pagination import paginate
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })


class FaultExportView(View):
    @auth('equipment_lifecycle.fault.export')
    def get(self, request):
        query = apply_tenant_filter(SystemFault.objects.all(), request.user)
        status = request.GET.get('status')
        if status and status in SystemFault.STATUS_TEXT_MAP:
            query = query.filter(status=status)
        headers = ['故障编号', '故障系统', '系统编号', '影响状态', '状态',
                   '发生时间', '故障现象', '恢复时间', '最终结果',
                   '故障登记人', '恢复确认人']
        rows = []
        for item in query:
            rows.append([
                item.fault_no,
                item.system_name,
                item.system_code,
                item.IMPACT_TEXT_MAP.get(item.impact_status, ''),
                item.STATUS_TEXT_MAP.get(item.status, item.status),
                item.occurred_at.strftime('%Y-%m-%d %H:%M') if item.occurred_at else '',
                item.phenomenon,
                item.recovered_at.strftime('%Y-%m-%d %H:%M') if item.recovered_at else '',
                item.final_result,
                item.registrar_name or '',
                item.recovered_by_name or '',
            ])
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        writer.writerows(rows)
        response = HttpResponse('\ufeff' + buf.getvalue(), content_type='text/csv; charset=utf-8')
        stamp = timezone.now().strftime('%Y%m%d%H%M%S')
        response['Content-Disposition'] = f'attachment; filename=el_faults_{stamp}.csv'
        record_audit_event(request, 'export', AUDIT_TARGET_FAULT, '', '',
                           after_value={'total': len(rows)})
        return response


# ======================================================================
# 台账异常明细转故障（自 work_order_views.py 迁入，2026-09-30 工单下线）
# ----------------------------------------------------------------------

# 台账异常明细可转故障的台账状态（草稿/退回/作废不可转）
CONVERTIBLE_LEDGER_STATUSES = ('submitted', 'reviewed')


def _item_value_text(item):
    """台账明细填写值文本（转入单据的现象描述用）。"""
    if item.input_type == 'number' and item.value_number is not None:
        unit = item.unit_snapshot or ''
        return f'{item.value_number}{unit}'
    if item.input_type == 'boolean' and item.value_bool is not None:
        return '是' if item.value_bool else '否'
    return item.value_text or ''


def _get_ledger_item_for_convert(ledger_pk, item_pk, user, for_update=False):
    """重新查询台账与明细并校验：URL 匹配、同租户、可转故障状态。

    返回 (item, ledger, error)。转换前必须重新查询台账和明细状态，
    不信任前端传来的状态。
    """
    qs = OperationLedgerItem.objects.select_related('ledger', 'system')
    if for_update:
        qs = qs.select_for_update()
    if not getattr(user, 'is_supper', False):
        qs = qs.filter(tenant_id=user.tenant_id)
    item = qs.filter(pk=item_pk, ledger_id=ledger_pk).first()
    if not item:
        return None, None, '台账明细不存在'
    ledger = item.ledger
    # 旧巡检台账类型已删除（旧巡检台账下线改造）：异常转故障一律显式拒绝；
    # 周月/季维护不受影响。
    if ledger.ledger_type == LEGACY_LEDGER_TYPE_INSPECTION:
        return None, None, '旧巡检台账（历史）已删除，不能转故障'
    if ledger.status in (LEDGER_STATUS_DRAFT, LEDGER_STATUS_RETURNED, LEDGER_STATUS_VOID):
        return None, None, '草稿、已退回或已作废的台账不能转故障'
    if ledger.status not in CONVERTIBLE_LEDGER_STATUSES:
        return None, None, '当前台账状态不能转故障'
    if item.result != ITEM_RESULT_ABNORMAL:
        return None, None, '只有结果为"异常"的明细可以转故障'
    return item, ledger, None


def _check_item_redispose(item, user, re_dispose_reason):
    """异常明细再次转故障校验：拒绝或要求重新处置原因。

    返回 error（None 表示允许）。规则：
    - 已存在未取消故障 → 一律拒绝（不能静默重复创建）；
    - 仅存在已取消故障 → 必须填写重新处置原因；
    - 首次处置 → 直接放行。
    （原"已转故障后再转工单"分支已随工单功能删除）
    """
    reason = (re_dispose_reason or '').strip()
    existing = SystemFault.objects.filter(
        tenant_id=user.tenant_id, source_ledger_item=item).order_by('-id')
    active = existing.exclude(status=SystemFault.STATUS_CANCELLED).first()
    latest = existing.first()
    if active:
        return f'该异常明细已转故障（{active.fault_no}），不能重复转换'
    if latest and not reason:
        return '该异常明细曾转故障（目标已作废）。如需重新处置请填写重新处置原因'
    return None


def _resolve_convert_payload(body, item, ledger):
    """解析并校验台账异常转故障载荷，返回 (params, error)。

    params 包含 occurred_at/affects_system_operation/impact_status/phenomenon。
    """
    # 发现方式/级别字段已删除（2026-09）：旧客户端提交显式拒绝
    removed = [k for k in ('discovery', 'level') if k in body]
    if removed:
        return None, '故障已不再支持参数：' + '、'.join(removed) + '，请更新后重新提交'
    form, error = JsonParser(
        Argument('occurred_at', type=str, required=False, default=''),
        Argument('affects_system_operation', type=bool, required=False, default=False,
                 help='是否影响系统运行，默认不影响（部件故障）'),
        Argument('impact_status', type=str, required=False, default='',
                 help='系统影响程度：影响系统运行时必填（降级/故障/中断）'),
        Argument('phenomenon', type=str, required=False, default=''),
        Argument('re_dispose_reason', type=str, required=False, default=''),
    ).parse(body)
    if error:
        return None, error

    occurred_at = _parse_dt(form.occurred_at) if form.occurred_at else None
    if form.occurred_at and not occurred_at:
        return None, '故障发生时间格式不正确'
    if not occurred_at:
        occurred_at = item.executed_at
    if not occurred_at:
        # 明细无独立执行时间时取台账实际执行日期（USE_TZ=False 直接取本地 naive）
        occurred_at = datetime.combine(ledger.executed_date, datetime.min.time())
    if occurred_at > timezone.now():
        return None, '故障发生时间不能晚于当前时间'
    # 默认"部件故障但不影响系统运行"；仅明确选择影响运行时才要求影响程度
    affects = bool(form.affects_system_operation)
    if affects:
        if form.impact_status not in SystemFault.IMPACT_TEXT_MAP:
            return None, '影响系统运行时必须选择影响程度（降级/故障/中断）'
        impact_status = form.impact_status
    else:
        impact_status = ''

    phenomenon = (form.phenomenon or '').strip()
    if not phenomenon:
        phenomenon = _compose_phenomenon(item, ledger)
    return {
        'occurred_at': occurred_at,
        'affects_system_operation': affects,
        'impact_status': impact_status,
        'phenomenon': phenomenon,
    }, None


def _compose_phenomenon(item, ledger):
    """由台账明细组装默认故障现象：台账类型/编号 + 检查项 + 异常说明
    + 实测值 + 现场处理内容。"""
    ledger_label = f'{LEDGER_TYPE_TEXT.get(ledger.ledger_type, ledger.ledger_type)} {ledger.ledger_no}'
    parts = [f'[{ledger_label}] {item.item_name_snapshot}']
    parts.append(item.abnormal_desc or '发现异常')
    value_text = _item_value_text(item)
    if value_text:
        parts.append(f'实测值：{value_text}')
    if item.onsite_action:
        parts.append(f'现场处理：{item.onsite_action}')
    return '；'.join(parts)[:2000]


class LedgerItemConvertToFaultView(View):
    """台账异常明细转故障（台账详情"转故障"操作）。

    - 只有结果为"异常"的明细可以转故障；草稿/退回/作废台账不能转；
    - 故障系统固定为明细所属系统；
    - 带入台账类型、编号、检查项、异常说明、实测值与现场处理内容；
    - 必须调用步骤 3.1 的正式故障创建服务（fault_services.create_fault_record），
      转换与来源关系保存处于同一事务；
    - 同一异常明细默认只允许直接生成一张故障；目标已作废后重新处置须填写原因。
    """

    @auth('equipment_lifecycle.ledger.handle_exception')
    def post(self, request, ledger_pk, item_pk):
        if not request.user.has_perms(['equipment_lifecycle.fault.add']):
            return json_response(error='权限拒绝')
        body = _read_json_body(request) or {}
        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    item, ledger, error = _get_ledger_item_for_convert(
                        ledger_pk, item_pk, request.user, for_update=True)
                    if error:
                        return json_response(error=error)
                    error = _check_item_redispose(
                        item, request.user, body.get('re_dispose_reason'))
                    if error:
                        return json_response(error=error)
                    params, error = _resolve_convert_payload(body, item, ledger)
                    if error:
                        return json_response(error=error)

                    fault = fault_services.create_fault_record(
                        tenant_id=request.user.tenant_id,
                        created_by=request.user,
                        system=item.system,
                        source_type='ledger_item',
                        source_ledger_item=item,
                        request=request,
                        **params,
                    )
                    # 步骤 3.4：台账异常处置履历（来源 ledger_item，与转换同一事务）
                    event_services.record_ledger_convert_event(
                        item, ledger, 'convert_to_fault', target_no=fault.fault_no,
                        created_by=request.user)
                    record_audit_event(request, 'create', AUDIT_TARGET_FAULT,
                                       fault.id, fault.fault_no,
                                       after_value={
                                           'action': 'convert_from_ledger_item',
                                           'ledger_no': ledger.ledger_no,
                                           'ledger_item_id': item.id,
                                           'item_name': item.item_name_snapshot,
                                           'status': fault.status,
                                           're_dispose_reason': (
                                               body.get('re_dispose_reason') or '').strip()[:200],
                                       })
        except (fault_services.HealthRecalcLockTimeout,
                fault_services.FaultNoExhausted) as exc:
            return json_response(error=str(exc))
        fault_data = SystemFault.objects.select_related('system').get(pk=fault.id)
        return json_response(fault_data.to_detail_view())

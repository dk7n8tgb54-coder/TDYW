# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——系统故障管理与系统健康状态联动视图（步骤 3.1，单系统简化）。

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
- 首报表单精简（2026-09）：手工新增故障 discovery 缺省"人工报告"、level 缺省
  "一般"，两字段不再必填；编辑未提交 discovery/level 及历史设备字段
  （影响范围/故障位置/对象名称/型号/序列号）时保留原值，不静默清空历史数据；
- 写操作记录业务审计（record_audit_event）。
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
from apps.account.models import User
from apps.logs.audit import record_audit_event
from apps.evidence.attachment_service import (
    AttachmentService, DefaultAttachmentConfig, ATTACHMENT_DELETE_DENIED_ERROR,
)
from apps.evidence.models import EvidenceAttachment

from apps.equipment_lifecycle import event_services, fault_services
from apps.equipment_lifecycle.models import (
    LifecycleSystem,
    SystemFault,
    SystemFaultHandlingRecord,
)

AUDIT_TARGET_FAULT = 'el_system_fault'
AUDIT_TARGET_HEALTH = fault_services.AUDIT_TARGET_HEALTH

# 处置记录附件归属标识（复用 EvidenceAttachment 体系，不新建文件存储）
FAULT_ATTACHMENT_MODULE = 'equipment_lifecycle'
FAULT_ATTACHMENT_OBJECT_TYPE = 'el_fault_handling'

# 允许普通编辑与追加处置记录的故障状态（closed/cancelled 均不允许）
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


def _get_record_for_user(fault, rid, user, for_update=False):
    qs = apply_tenant_filter(SystemFaultHandlingRecord.objects.all(), user)
    if for_update:
        qs = qs.select_for_update()
    return qs.filter(pk=rid, fault=fault).first()


def _get_active_system_for_user(pk, user):
    """取本租户可用（未停用）系统：新建/变更故障关联只允许选择可用系统。"""
    return apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(
        pk=pk, is_active=True).first()


def _validate_affected_systems_rejected(body):
    """旧参数已随单系统简化删除：出现即拒绝，不静默忽略。"""
    if 'affected_systems' in body:
        return '故障已不再支持受影响系统，请只提交一个故障系统'
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


def _validate_fault_fields(form, request, for_update=False, fault=None):
    """校验故障公共字段，返回 (occurred_at, handler, error)。

    discovery/level 允许缺省（None=编辑保留原值，创建由 JsonParser 补默认值），
    仅显式提交时校验取值合法性。
    """
    occurred_at = _parse_dt(form.occurred_at)
    if not occurred_at:
        return None, None, '故障发生时间格式不正确，应为 YYYY-MM-DD HH:MM'
    if occurred_at > timezone.now():
        return None, None, '故障发生时间不能晚于当前时间'
    if form.level is not None and form.level not in SystemFault.LEVEL_TEXT_MAP:
        return None, None, '故障级别不合法'
    if form.discovery is not None and form.discovery not in SystemFault.DISCOVERY_TEXT_MAP:
        return None, None, '故障发现方式不合法'
    handler = request.user
    if form.handler_id:
        handler = apply_tenant_filter(User.objects.all(), request.user).filter(
            pk=form.handler_id).first()
        if not handler:
            return None, None, '处置负责人不存在或无权限'
    return occurred_at, handler, None


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


def _generate_fault_no(tenant_id):
    """生成租户内当日序号故障编号 GZ{yyyymmdd}-{seq:04d}（须在持锁事务内调用）。"""
    # USE_TZ=False 下 timezone.localdate() 会对 naive now 抛错，直接取本地日期
    prefix = 'GZ' + timezone.now().date().strftime('%Y%m%d') + '-'
    existing = set(SystemFault.objects.filter(
        tenant_id=tenant_id, fault_no__startswith=prefix).values_list('fault_no', flat=True))
    index = len(existing) + 1
    while f'{prefix}{index:04d}' in existing:
        index += 1
    return f'{prefix}{index:04d}'


def _fault_audit_summary(fault):
    summary = {
        'fault_no': fault.fault_no,
        'status': fault.status,
        'system': fault.system_name,
        'affects_system_operation': fault.affects_system_operation,
        'impact_status': fault.impact_status,
        'level': fault.level,
    }
    if fault.status == SystemFault.STATUS_CANCELLED and fault.cancel_reason:
        summary['cancel_reason'] = fault.cancel_reason
    return summary


def _fault_optional_fields(form):
    """故障可选文本字段规范化（strip 限长由创建服务统一处理）。"""
    return {
        'impact_scope': form.impact_scope or '',
        'fault_location': form.fault_location or '',
        'fault_object_name': form.fault_object_name or '',
        'fault_object_model': form.fault_object_model or '',
        'fault_object_sn': form.fault_object_sn or '',
        'reason_analysis': form.reason_analysis or '',
    }


def _apply_fault_text_fields(fault, form):
    """编辑故障时写入可选文本字段（统一 strip 限长）。

    未提交（None）的字段保留原值：精简后的表单不再携带影响范围/故障位置/
    对象型号/序列号等历史字段，编辑旧故障时不得静默清空历史数据。
    """
    if form.impact_scope is not None:
        fault.impact_scope = form.impact_scope.strip()[:1000]
    if form.fault_location is not None:
        fault.fault_location = form.fault_location.strip()[:200]
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
            Argument('level', type=str, required=False),
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
        if form.level:
            if form.level not in SystemFault.LEVEL_TEXT_MAP:
                return json_response(error='故障级别筛选值不合法')
            query = query.filter(level=form.level)
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
            Argument('discovery', type=str, required=False, default=SystemFault.DISCOVERY_REPORT,
                     help='故障发现方式，缺省人工报告（首报表单不再必填）'),
            Argument('level', type=str, required=False, default=SystemFault.LEVEL_MINOR,
                     help='故障级别，缺省一般（首报表单不再必填）'),
            Argument('phenomenon', type=str, required=True, help='故障现象'),
            Argument('impact_scope', type=str, required=False, default=''),
            Argument('fault_location', type=str, required=False, default=''),
            Argument('fault_object_name', type=str, required=False, default=''),
            Argument('fault_object_model', type=str, required=False, default=''),
            Argument('fault_object_sn', type=str, required=False, default=''),
            Argument('reason_analysis', type=str, required=False, default=''),
            Argument('handler_id', type=int, required=False, default=None),
        ).parse(body)
        if error:
            return json_response(error=error)
        err = _validate_affected_systems_rejected(body)
        if err:
            return json_response(error=err)

        system, err = _validate_fault_system(form, request)
        if err:
            return json_response(error=err)
        occurred_at, handler, err = _validate_fault_fields(form, request)
        if err:
            return json_response(error=err)
        affects, impact_status, err = _validate_affects_and_impact(form)
        if err:
            return json_response(error=err)
        phenomenon = form.phenomenon.strip()
        if not phenomenon:
            return json_response(error='故障现象不能为空')

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
                        discovery=form.discovery,
                        level=form.level,
                        phenomenon=phenomenon,
                        handler=handler,
                        **_fault_optional_fields(form),
                        source_type=SystemFault.SOURCE_MANUAL,
                        request=request,
                    )
                    record_audit_event(request, 'create', AUDIT_TARGET_FAULT, fault.id,
                                       fault.fault_no, after_value=_fault_audit_summary(fault))
        except fault_services.HealthRecalcLockTimeout as exc:
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
            Argument('discovery', type=str, required=False, default=None,
                     help='故障发现方式；编辑未提交时保留原值'),
            Argument('level', type=str, required=False, default=None,
                     help='故障级别；编辑未提交时保留原值'),
            Argument('phenomenon', type=str, required=True, help='故障现象'),
            Argument('impact_scope', type=str, required=False, default=None),
            Argument('fault_location', type=str, required=False, default=None),
            Argument('fault_object_name', type=str, required=False, default=None),
            Argument('fault_object_model', type=str, required=False, default=None),
            Argument('fault_object_sn', type=str, required=False, default=None),
            Argument('reason_analysis', type=str, required=False, default=None),
            Argument('handler_id', type=int, required=False, default=None),
        ).parse(body)
        if error:
            return json_response(error=error)
        err = _validate_affected_systems_rejected(body)
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
                    occurred_at, handler, err = _validate_fault_fields(
                        form, request, for_update=True, fault=fault)
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
                    # 未提交的发现方式/级别保留原值（精简表单编辑不携带）
                    if form.discovery is not None:
                        fault.discovery = form.discovery
                    if form.level is not None:
                        fault.level = form.level
                    fault.phenomenon = phenomenon[:2000]
                    _apply_fault_text_fields(fault, form)
                    fault.handler = handler
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
        handler_id = body.get('handler_id')
        fault.status = SystemFault.STATUS_HANDLING
        if handler_id:
            handler = apply_tenant_filter(User.objects.all(), request.user).filter(
                pk=handler_id).first()
            if not handler:
                return '处置负责人不存在或无权限'
            fault.handler = handler
        elif not fault.handler_id:
            fault.handler = request.user
        fault.updated_at = timezone.now()
        fault.updated_by = request.user
        fault.save(update_fields=['status', 'handler', 'updated_at', 'updated_by'])
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
        if not form.recover_confirm.strip():
            return '恢复确认信息不能为空'
        fault.status = SystemFault.STATUS_RECOVERED
        fault.recovered_at = recovered_at
        fault.recover_confirm = form.recover_confirm.strip()[:1000]
        fault.recovered_by = request.user
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
        if not fault.recovered_at or not fault.recovered_by or not fault.recover_confirm.strip():
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


class FaultHandlingRecordView(View):
    """处置记录：按处置时间正序的时间线 / 追加记录。"""

    @auth('equipment_lifecycle.fault.view')
    def get(self, request, pk):
        fault = _get_fault_for_user(pk, request.user)
        if not fault:
            return json_response(error='故障记录不存在')
        query = apply_tenant_filter(SystemFaultHandlingRecord.objects.all(), request.user).filter(
            fault=fault)
        from libs.pagination import paginate
        page, page_size = paginate(request, default_page_size=100)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.fault.handle')
    def post(self, request, pk):
        form, error = JsonParser(
            Argument('handled_at', type=str, required=True, help='处置时间'),
            Argument('content', type=str, required=True, help='处置内容'),
            Argument('result', type=str, required=False, default=''),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        handled_at = _parse_dt(form.handled_at)
        if not handled_at:
            return json_response(error='处置时间格式不正确，应为 YYYY-MM-DD HH:MM')
        content = form.content.strip()
        if not content:
            return json_response(error='处置内容不能为空')
        with fault_services.health_recalc_lock():
            with transaction.atomic():
                fault = _get_fault_for_user(pk, request.user, for_update=True)
                if not fault:
                    return json_response(error='故障记录不存在')
                if fault.status not in EDITABLE_FAULT_STATUSES:
                    return json_response(error='已关闭或已作废的故障不能追加处置记录')
                record = SystemFaultHandlingRecord.objects.create(
                    tenant_id=fault.tenant_id,
                    fault=fault,
                    handled_at=handled_at,
                    handler=request.user,
                    content=content[:2000],
                    result=(form.result or '').strip()[:200],
                )
                record_audit_event(request, 'create', AUDIT_TARGET_FAULT, fault.id,
                                   fault.fault_no,
                                   after_value={'action': 'add_handling_record',
                                                'record_id': record.id,
                                                'handled_at': handled_at.isoformat(sep=' ',
                                                                                   timespec='minutes')})
        return json_response(record.to_view())


class FaultHandlingRecordDetailView(View):
    """处置记录更正：保存原内容、修改内容和更正原因，不静默覆盖。"""

    @auth('equipment_lifecycle.fault.edit')
    def put(self, request, pk, rid):
        form, error = JsonParser(
            Argument('handled_at', type=str, required=False, default=None),
            Argument('content', type=str, required=True, help='处置内容'),
            Argument('result', type=str, required=False, default=''),
            Argument('correction_reason', type=str, required=True, help='更正原因'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        content = form.content.strip()
        if not content:
            return json_response(error='处置内容不能为空')
        correction_reason = form.correction_reason.strip()
        if not correction_reason:
            return json_response(error='更正原因不能为空')
        handled_at = None
        if form.handled_at:
            handled_at = _parse_dt(form.handled_at)
            if not handled_at:
                return json_response(error='处置时间格式不正确，应为 YYYY-MM-DD HH:MM')
        with fault_services.health_recalc_lock():
            with transaction.atomic():
                fault = _get_fault_for_user(pk, request.user, for_update=True)
                if not fault:
                    return json_response(error='故障记录不存在')
                if fault.status not in EDITABLE_FAULT_STATUSES:
                    return json_response(error='已关闭或已作废的故障不能更正处置记录')
                record = _get_record_for_user(fault, rid, request.user, for_update=True)
                if not record:
                    return json_response(error='处置记录不存在')
                corrections = record.get_corrections()
                corrections.append({
                    'old': record.content,
                    'new': content[:2000],
                    'reason': correction_reason[:500],
                    'by': request.user.username,
                    'at': timezone.now().isoformat(sep=' ', timespec='minutes'),
                })
                record.content = content[:2000]
                record.result = (form.result or '').strip()[:200]
                if handled_at:
                    record.handled_at = handled_at
                record.corrections = json.dumps(corrections, ensure_ascii=False)
                record.save()
                record_audit_event(request, 'update', AUDIT_TARGET_FAULT, fault.id,
                                   fault.fault_no,
                                   after_value={'action': 'correct_handling_record',
                                                'record_id': record.id,
                                                'reason': correction_reason[:200]})
        return json_response(record.to_view())


class FaultHandlingAttachmentView(View):
    """处置记录附件（复用 EvidenceAttachment 能力）。

    访问前先校验处置记录所属故障存在且属于当前租户。
    """

    @auth('equipment_lifecycle.fault.view')
    def get(self, request, pk, rid):
        fault = _get_fault_for_user(pk, request.user)
        if not fault:
            return json_response(error='故障记录不存在')
        record = _get_record_for_user(fault, rid, request.user)
        if not record:
            return json_response(error='处置记录不存在')
        attachments = AttachmentService.list(
            request.user, FAULT_ATTACHMENT_MODULE, FAULT_ATTACHMENT_OBJECT_TYPE, record.id)
        return json_response({'data': attachments})

    @auth('equipment_lifecycle.fault.handle')
    def post(self, request, pk, rid):
        with fault_services.health_recalc_lock():
            with transaction.atomic():
                fault = _get_fault_for_user(pk, request.user, for_update=True)
                if not fault:
                    return json_response(error='故障记录不存在')
                if fault.status not in EDITABLE_FAULT_STATUSES:
                    return json_response(error='已关闭或已作废的故障不能上传处置附件')
                record = _get_record_for_user(fault, rid, request.user)
                if not record:
                    return json_response(error='处置记录不存在')
                file = request.FILES.get('file')
                if not file:
                    return json_response(error='缺少上传文件')
                att, error = AttachmentService.upload(
                    file, request.user, FAULT_ATTACHMENT_MODULE, FAULT_ATTACHMENT_OBJECT_TYPE,
                    record.id, config=DefaultAttachmentConfig, owner_tenant_id=fault.tenant_id)
                if error:
                    return json_response(error=error)
                record_audit_event(request, 'create', AUDIT_TARGET_FAULT, fault.id,
                                   fault.fault_no,
                                   after_value={'action': 'upload_handling_attachment',
                                                'record_id': record.id,
                                                'file_name': att.file_name})
        return json_response(att.to_view())


class FaultHandlingAttachmentDetailView(View):
    @auth('equipment_lifecycle.fault.edit')
    def delete(self, request, pk, rid, aid):
        with fault_services.health_recalc_lock():
            with transaction.atomic():
                fault = _get_fault_for_user(pk, request.user, for_update=True)
                if not fault:
                    return json_response(error='故障记录不存在')
                if fault.status not in EDITABLE_FAULT_STATUSES:
                    return json_response(error='已关闭或已作废的故障不能删除处置附件')
                record = _get_record_for_user(fault, rid, request.user)
                if not record:
                    return json_response(error='处置记录不存在')
                att = apply_tenant_filter(
                    EvidenceAttachment.objects.filter(is_deleted=False), request.user
                ).filter(pk=aid, module=FAULT_ATTACHMENT_MODULE,
                         object_type=FAULT_ATTACHMENT_OBJECT_TYPE,
                         object_id=str(record.id)).first()
                if not att:
                    return json_response(error=ATTACHMENT_DELETE_DENIED_ERROR)
                error = AttachmentService.soft_delete(
                    request.user, aid, FAULT_ATTACHMENT_MODULE, FAULT_ATTACHMENT_OBJECT_TYPE,
                    reason='故障处置记录附件删除')
                if error:
                    return json_response(error=error)
                record_audit_event(request, 'delete', AUDIT_TARGET_FAULT, fault.id,
                                   fault.fault_no,
                                   after_value={'action': 'delete_handling_attachment',
                                                'record_id': record.id,
                                                'file_name': att.file_name})
        return json_response({})


class FaultHandlingAttachmentDownloadView(View):
    @auth('equipment_lifecycle.fault.view')
    def get(self, request, pk, rid, aid):
        fault = _get_fault_for_user(pk, request.user)
        if not fault:
            return json_response(error='故障记录不存在')
        record = _get_record_for_user(fault, rid, request.user)
        if not record:
            return json_response(error='处置记录不存在')
        response, error = AttachmentService.download_response(
            request.user, aid, FAULT_ATTACHMENT_MODULE, FAULT_ATTACHMENT_OBJECT_TYPE)
        if error:
            return json_response(error=error)
        return response


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
        level = request.GET.get('level')
        if level and level in SystemFault.LEVEL_TEXT_MAP:
            query = query.filter(level=level)
        headers = ['故障编号', '故障系统', '系统编号', '影响状态', '故障级别', '状态',
                   '发生时间', '发现方式', '故障现象', '恢复时间', '最终结果', '处置负责人']
        rows = []
        for item in query:
            rows.append([
                item.fault_no,
                item.system_name,
                item.system_code,
                item.IMPACT_TEXT_MAP.get(item.impact_status, ''),
                item.LEVEL_TEXT_MAP.get(item.level, item.level),
                item.STATUS_TEXT_MAP.get(item.status, item.status),
                item.occurred_at.strftime('%Y-%m-%d %H:%M') if item.occurred_at else '',
                item.DISCOVERY_TEXT_MAP.get(item.discovery, item.discovery),
                item.phenomenon,
                item.recovered_at.strftime('%Y-%m-%d %H:%M') if item.recovered_at else '',
                item.final_result,
                item.handler.username if item.handler_id else '',
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

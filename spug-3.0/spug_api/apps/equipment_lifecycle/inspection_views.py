# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""值班巡检视图（今日巡检改造）。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.inspection.view|add|edit|submit|del|handle_exception
- equipment_lifecycle.inspection_template.view|add|edit|del

业务规则（与 inspection_services 一致）：
- 巡检单唯一范围 = 值班日 + 巡检模板，值班人员登记在单上；
- 四个固定轮次（第四轮次日 06:30 归属前一值班日），不记录实际填写时间；
- 巡检单不关联系统：异常转故障/工单时必须由用户选择系统并经后端校验
  （存在/本租户/未停用），不能由设备名称推断系统；
- 转换在 health_recalc_lock + 同一事务内完成，履历事件落目标系统，
  来源关系双向可追溯，重复转换被拒绝或要求重新处置原因。
"""
import json as _json
from datetime import datetime

from django.db import transaction
from django.utils import timezone
from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from libs.export_utils import (
    build_excel_response,
    build_export_error_response,
    check_export_limit,
)
from libs.tenant_utils import apply_tenant_filter
from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle import event_services, fault_services, inspection_services
from apps.equipment_lifecycle import inspection_export
from apps.equipment_lifecycle.inspection_services import InspectionValidationError
from apps.equipment_lifecycle.models import (
    InspectionDutySheet,
    InspectionRecord,
    InspectionTemplate,
    LifecycleSystem,
    SystemFault,
    SystemWorkOrder,
)

AUDIT_TARGET_INSPECTION_SHEET = 'el_inspection_sheet'
AUDIT_TARGET_INSPECTION_TEMPLATE = 'el_inspection_template'
AUDIT_TARGET_FAULT = 'el_system_fault'
AUDIT_TARGET_WORK_ORDER = 'el_work_order'

DATETIME_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%dT%H:%M', '%Y-%m-%d')


def _read_json_body(request):
    try:
        return _json.loads(request.body.decode('utf-8')) if request.body else {}
    except Exception:
        return None


def _require_perm(user, code):
    """显式单项权限校验（has_perms 为任一匹配语义，双权限动作分别调用）。"""
    return user.has_perms([code])


def _parse_dt(value):
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    return None


def _error(exc):
    return json_response(error=str(exc))


class InspectionTemplateView(View):
    """巡检模板列表 / 聚合创建（模板 → 设备名称 → 检查内容）。"""

    @auth('equipment_lifecycle.inspection_template.view')
    def get(self, request):
        keyword = (request.GET.get('keyword') or '').strip()
        qs = inspection_services.get_templates_for_user(request.user)
        if keyword:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=keyword) | Q(description__icontains=keyword))
        from libs.pagination import paginate
        page, page_size = paginate(request)
        total = qs.count()
        templates = qs[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [t.to_view(with_counts=True) for t in templates],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.inspection_template.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        try:
            template = inspection_services.create_template(request.user, body)
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'create', AUDIT_TARGET_INSPECTION_TEMPLATE,
                           template.id, template.name, after_value=template.to_view())
        return json_response(inspection_services.get_template_tree(template))


class InspectionTemplateDetailView(View):
    """巡检模板详情 / 聚合编辑 / 删除。"""

    @auth('equipment_lifecycle.inspection_template.view')
    def get(self, request, pk):
        template = inspection_services.get_templates_for_user(request.user).filter(pk=pk).first()
        if not template:
            return json_response(error='巡检模板不存在')
        return json_response(inspection_services.get_template_tree(template))

    @auth('equipment_lifecycle.inspection_template.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        try:
            template = inspection_services.update_template(request.user, pk, body)
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'update', AUDIT_TARGET_INSPECTION_TEMPLATE,
                           template.id, template.name, after_value=template.to_view())
        return json_response(inspection_services.get_template_tree(template))

    @auth('equipment_lifecycle.inspection_template.del')
    def delete(self, request, pk):
        try:
            template = inspection_services.get_templates_for_user(request.user).filter(
                pk=pk).first()
            if not template:
                return json_response(error='巡检模板不存在')
            used = InspectionDutySheet.objects.filter(template=template).exists()
            if used:
                return json_response(error='该模板已被巡检单引用，请停用而非删除')
            template.delete()
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'delete', AUDIT_TARGET_INSPECTION_TEMPLATE,
                           pk, template.name)
        return json_response()


class InspectionTemplateActiveView(View):
    """巡检模板启用/停用。"""

    @auth('equipment_lifecycle.inspection_template.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        try:
            template = inspection_services.toggle_template_active(
                request.user, pk, bool(body.get('is_active')))
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'other', AUDIT_TARGET_INSPECTION_TEMPLATE,
                           template.id, template.name,
                           after_value={'is_active': template.is_active})
        return json_response(template.to_view())


class InspectionTemplateAvailableView(View):
    """可用巡检模板树（巡检工作台渲染设备/检查内容，仅启用模板与启用条目）。"""

    @auth('equipment_lifecycle.inspection.view')
    def get(self, request):
        templates = inspection_services.get_templates_for_user(
            request.user, only_active=True).order_by('name')
        return json_response({
            'data': [inspection_services.get_template_tree(t, only_active=True)
                     for t in templates],
        })


class InspectionCandidateSystemsView(View):
    """巡检转单目标系统候选项：本租户可用系统。

    巡检单不关联系统，转换时才选择系统；本端点只需 inspection.view 权限，
    供转故障/转工单弹窗使用（不依赖 fault.view 或 work_order.view）。
    """

    @auth('equipment_lifecycle.inspection.view')
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


class InspectionSheetView(View):
    """值班巡检单列表 / 创建（值班日 + 模板 唯一，client_token 幂等）。"""

    @auth('equipment_lifecycle.inspection.view')
    def get(self, request):
        from libs.pagination import paginate
        form, error = JsonParser(
            Argument('duty_from', type=str, required=False),
            Argument('duty_to', type=str, required=False),
            Argument('duty_date', type=str, required=False),
            Argument('template', type=int, required=False),
            Argument('status', type=str, required=False),
            Argument('keyword', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        qs = apply_tenant_filter(
            InspectionDutySheet.objects.select_related('template'), request.user)
        qs, error = _filter_sheet_queryset(qs, form)
        if error:
            return json_response(error=error)
        page, page_size = paginate(request)
        total = qs.count()
        sheets = qs[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [s.to_view() for s in sheets],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.inspection.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        try:
            sheet = inspection_services.create_sheet(request.user, body)
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'create', AUDIT_TARGET_INSPECTION_SHEET,
                           sheet.id, sheet.sheet_no, after_value={
                               'sheet_no': sheet.sheet_no,
                               'duty_date': str(sheet.duty_date),
                               'template': sheet.template.name,
                           })
        return json_response(sheet.to_detail_view())


def _sheet_keyword_q(keyword):
    from django.db.models import Q
    return Q(sheet_no__icontains=keyword) | Q(template__name__icontains=keyword)


def _filter_sheet_queryset(qs, form):
    """按查询参数过滤巡检单列表，返回 (queryset, error)。"""
    if form.duty_date:
        qs = qs.filter(duty_date=inspection_services.parse_duty_date(form.duty_date))
    duty_from = _parse_dt(form.duty_from + ' 00:00') if form.duty_from else None
    duty_to = _parse_dt(form.duty_to + ' 00:00') if form.duty_to else None
    if form.duty_from and not duty_from:
        return None, '值班日起始格式不正确'
    if form.duty_to and not duty_to:
        return None, '值班日截止格式不正确'
    if duty_from:
        qs = qs.filter(duty_date__gte=duty_from.date())
    if duty_to:
        qs = qs.filter(duty_date__lte=duty_to.date())
    if form.template:
        qs = qs.filter(template_id=form.template)
    if form.status:
        if form.status not in ('draft', 'submitted', 'void'):
            return None, '状态筛选值不合法'
        qs = qs.filter(status=form.status)
    if form.keyword:
        qs = qs.filter(_sheet_keyword_q(form.keyword))
    return qs, None


class InspectionSheetDetailView(View):
    """巡检单详情 / 草稿编辑（值班人员 + 单轮记录 upsert，version 乐观锁；
    一次请求只允许提交一个轮次，已记录轮次由后端拒绝再次修改）。"""

    @auth('equipment_lifecycle.inspection.view')
    def get(self, request, pk):
        try:
            sheet = inspection_services.get_sheet_for_user(request.user, pk)
        except InspectionValidationError as exc:
            return _error(exc)
        data = sheet.to_detail_view()
        data['records'] = inspection_services.append_record_disposition(
            request.user.tenant_id, data['records'])
        return json_response(data)

    @auth('equipment_lifecycle.inspection.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        try:
            sheet = inspection_services.update_sheet(request.user, pk, body)
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'update', AUDIT_TARGET_INSPECTION_SHEET,
                           sheet.id, sheet.sheet_no, after_value={
                               'version': sheet.version,
                               'record_count': sheet.records.count(),
                           })
        data = sheet.to_detail_view()
        data['records'] = inspection_services.append_record_disposition(
            request.user.tenant_id, data['records'])
        return json_response(data)


class InspectionSheetSubmitView(View):
    """提交巡检单（记录/提交分离，提交后不可再修改）。"""

    @auth('equipment_lifecycle.inspection.submit')
    def post(self, request, pk):
        try:
            sheet = inspection_services.submit_sheet(request.user, pk)
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'other', AUDIT_TARGET_INSPECTION_SHEET,
                           sheet.id, sheet.sheet_no,
                           after_value={'status': sheet.status})
        return json_response(sheet.to_detail_view())


class InspectionSheetVoidView(View):
    """受控作废巡检单（留档可查，释放当日唯一占用）。"""

    @auth('equipment_lifecycle.inspection.del')
    def post(self, request, pk):
        body = _read_json_body(request) or {}
        try:
            sheet = inspection_services.void_sheet(request.user, pk, body.get('void_reason'))
        except InspectionValidationError as exc:
            return _error(exc)
        record_audit_event(request, 'other', AUDIT_TARGET_INSPECTION_SHEET,
                           sheet.id, sheet.sheet_no,
                           after_value={'status': sheet.status,
                                        'void_reason': sheet.void_reason})
        return json_response(sheet.to_detail_view())


class _InspectionConvertBaseView(View):
    """巡检异常转故障/工单公共流程：锁 + 事务 + 重新校验 + 追溯。"""

    KIND = 'fault'

    def _convert(self, request, sheet_pk, record_pk):
        raise NotImplementedError

    def post(self, request, sheet_pk, record_pk):
        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    return self._convert(request, sheet_pk, record_pk)
        except fault_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        except InspectionValidationError as exc:
            return json_response(error=str(exc))


def _validate_convert_system(request, body):
    """转换目标系统校验：必须显式选择，且存在/本租户/未停用。

    巡检单不关联系统，设备名称不能推断系统：系统只能由用户在转换时选择。
    """
    system_id = body.get('system')
    if not system_id:
        return None, '请选择系统（巡检单不关联系统，转换目标系统必须显式选择）'
    system = apply_tenant_filter(LifecycleSystem.objects.all(), request.user).filter(
        pk=system_id, is_active=True).first()
    if not system:
        return None, '系统不存在、已停用或无权限'
    return system, None


def _validate_affects_and_impact(body):
    """转换默认"不影响系统运行"；明确选择影响运行时必须给出影响程度。"""
    affects = bool(body.get('affects_system_operation'))
    impact_status = (body.get('impact_status') or '').strip()
    if affects:
        if impact_status not in SystemFault.IMPACT_TEXT_MAP:
            return False, '', '影响系统运行时必须选择影响程度（降级/故障/中断）'
    else:
        impact_status = ''
    return affects, impact_status, None


def _validate_occurred_at(body):
    occurred_at = _parse_dt(body.get('occurred_at')) if body.get('occurred_at') else None
    if body.get('occurred_at') and not occurred_at:
        return None, '故障发生时间格式不正确'
    if not occurred_at:
        occurred_at = timezone.now()
    if occurred_at > timezone.now():
        return None, '故障发生时间不能晚于当前时间'
    return occurred_at, None


class InspectionRecordConvertToFaultView(_InspectionConvertBaseView):
    """巡检异常明细转故障（明细上"转故障"操作）。

    - 仅已提交巡检单中结果为"异常"的明细可以转；
    - 系统必须由用户显式选择（后端校验存在/本租户/未停用）；
    - 默认"部件故障但不影响系统运行"，明确选择影响运行时按影响程度参与计算；
    - 同一来源关系保存在同一事务，履历事件落目标系统，双向可追溯。
    """

    @auth('equipment_lifecycle.inspection.handle_exception')
    def post(self, request, sheet_pk, record_pk):
        if not _require_perm(request.user, 'equipment_lifecycle.fault.add'):
            return json_response(error='权限拒绝')
        return super().post(request, sheet_pk, record_pk)

    def _convert(self, request, sheet_pk, record_pk):
        body = _read_json_body(request) or {}
        record, sheet, error = inspection_services.get_record_for_convert(
            request.user, sheet_pk, record_pk, for_update=True)
        if error:
            return json_response(error=error)
        error = inspection_services.check_record_redispose(
            record, request.user, body.get('re_dispose_reason'), 'fault')
        if error:
            return json_response(error=error)
        system, error = _validate_convert_system(request, body)
        if error:
            return json_response(error=error)
        affects, impact_status, error = _validate_affects_and_impact(body)
        if error:
            return json_response(error=error)
        occurred_at, error = _validate_occurred_at(body)
        if error:
            return json_response(error=error)
        discovery = body.get('discovery') or SystemFault.DISCOVERY_PATROL
        if discovery not in SystemFault.DISCOVERY_TEXT_MAP:
            return json_response(error='故障发现方式不合法')
        level = body.get('level') or SystemFault.LEVEL_MINOR
        if level not in SystemFault.LEVEL_TEXT_MAP:
            return json_response(error='故障级别不合法')
        phenomenon = (body.get('phenomenon') or '').strip()
        if not phenomenon:
            phenomenon = inspection_services.compose_abnormal_phenomenon(record, sheet)

        fault = fault_services.create_fault_record(
            tenant_id=request.user.tenant_id,
            created_by=request.user,
            system=system,
            affects_system_operation=affects,
            impact_status=impact_status,
            occurred_at=occurred_at,
            discovery=discovery,
            level=level,
            phenomenon=phenomenon,
            source_type='inspection_record',
            source_inspection_record=record,
            request=request,
        )
        event_services.record_inspection_convert_event(
            record, sheet, system, 'convert_to_fault', target_no=fault.fault_no,
            detail={'re_dispose_reason': (body.get('re_dispose_reason') or '').strip()[:200]},
            created_by=request.user)
        record_audit_event(request, 'create', AUDIT_TARGET_FAULT,
                           fault.id, fault.fault_no,
                           after_value={
                               'action': 'convert_from_inspection_record',
                               'sheet_no': sheet.sheet_no,
                               'inspection_record_id': record.id,
                               'item_name': record.item_name_snapshot,
                               'status': fault.status,
                               're_dispose_reason': (
                                   body.get('re_dispose_reason') or '').strip()[:200],
                           })
        return json_response(fault.to_detail_view())


def _validate_order_form(form):
    """工单转换载荷校验：类型/优先级/布尔与计划时间区间。返回 (start, end, error)。"""
    if form.work_type not in SystemWorkOrder.TYPE_TEXT_MAP:
        return None, None, '工单类型不合法'
    if form.priority not in SystemWorkOrder.PRIORITY_TEXT_MAP:
        return None, None, '优先级不合法'
    if not isinstance(form.affects_system_operation, bool):
        return None, None, '作业期间是否影响系统运行必须为布尔值'
    planned_start = _parse_dt(form.planned_start) if form.planned_start else None
    planned_end = _parse_dt(form.planned_end) if form.planned_end else None
    if form.planned_start and not planned_start:
        return None, None, '计划开始时间格式不正确'
    if form.planned_end and not planned_end:
        return None, None, '计划结束时间格式不正确'
    if planned_start and planned_end and planned_end < planned_start:
        return None, None, '计划结束时间不能早于计划开始时间'
    return planned_start, planned_end, None


def _create_inspection_work_order(request, record, sheet, system, form,
                                  client_token, planned_start, planned_end):
    """创建巡检异常转出的维修工单，并落巡检转换履历与审计事件。"""
    from apps.equipment_lifecycle import work_order_services
    title = (form.title or '').strip()
    if not title:
        title = f'{record.item_name_snapshot} 巡检异常维修'[:100]
    work_requirement = (form.work_requirement or '').strip()
    if not work_requirement:
        work_requirement = inspection_services.compose_abnormal_phenomenon(record, sheet)
    order = work_order_services.create_work_order_record(
        tenant_id=request.user.tenant_id,
        created_by=request.user,
        title=title,
        work_type=form.work_type,
        priority=form.priority,
        source_type='inspection_record',
        source_inspection_record=record,
        source_no=sheet.sheet_no,
        system=system,
        affects_system_operation=form.affects_system_operation,
        work_location=(form.work_location or '').strip(),
        work_requirement=work_requirement[:2000],
        work_steps=(form.work_steps or '').strip()[:2000],
        material_note=(form.material_note or '').strip()[:500],
        planned_start=planned_start,
        planned_end=planned_end,
        client_token=client_token,
        request=request,
    )
    event_services.record_inspection_convert_event(
        record, sheet, system, 'convert_to_work_order', target_no=order.work_no,
        detail={'re_dispose_reason': (form.re_dispose_reason or '').strip()[:200]},
        created_by=request.user)
    record_audit_event(request, 'create', AUDIT_TARGET_WORK_ORDER,
                       order.id, order.work_no,
                       after_value={
                           'action': 'convert_from_inspection_record',
                           'sheet_no': sheet.sheet_no,
                           'inspection_record_id': record.id,
                           'item_name': record.item_name_snapshot,
                           'status': order.status,
                           're_dispose_reason': (
                               form.re_dispose_reason or '').strip()[:200],
                       })
    return order


class InspectionRecordConvertToWorkOrderView(_InspectionConvertBaseView):
    """巡检异常明细直接转工单（明细上"转工单"操作）。

    - 系统必须由用户显式选择；作业期间影响系统运行默认"否"；
    - 幂等：同 client_token 视为同一请求返回已有工单；
    - 重复转换拒绝，目标已作废后重新处置须填写原因。
    """

    @auth('equipment_lifecycle.inspection.handle_exception')
    def post(self, request, sheet_pk, record_pk):
        if not _require_perm(request.user, 'equipment_lifecycle.work_order.add'):
            return json_response(error='权限拒绝')
        return super().post(request, sheet_pk, record_pk)

    def _convert(self, request, sheet_pk, record_pk):
        from apps.equipment_lifecycle import work_order_services
        body = _read_json_body(request) or {}
        record, sheet, error = inspection_services.get_record_for_convert(
            request.user, sheet_pk, record_pk, for_update=True)
        if error:
            return json_response(error=error)
        client_token = (body.get('client_token') or '').strip()[:64]
        existing = work_order_services.find_existing_by_token(
            request.user.tenant_id, client_token,
            source_type='inspection_record', source_object=record)
        if existing:
            return json_response(existing.to_detail_view())
        error = inspection_services.check_record_redispose(
            record, request.user, body.get('re_dispose_reason'), 'work_order')
        if error:
            return json_response(error=error)
        system, error = _validate_convert_system(request, body)
        if error:
            return json_response(error=error)
        form, error = JsonParser(
            Argument('title', type=str, required=False, default=''),
            Argument('work_type', type=str, required=False,
                     default=SystemWorkOrder.TYPE_REPAIR),
            Argument('priority', type=str, required=False,
                     default=SystemWorkOrder.PRIORITY_NORMAL),
            Argument('affects_system_operation', type=bool, required=False,
                     default=False),
            Argument('work_location', type=str, required=False, default=''),
            Argument('work_requirement', type=str, required=False, default=''),
            Argument('work_steps', type=str, required=False, default=''),
            Argument('material_note', type=str, required=False, default=''),
            Argument('planned_start', type=str, required=False, default=None),
            Argument('planned_end', type=str, required=False, default=None),
            Argument('client_token', type=str, required=False, default=''),
            Argument('re_dispose_reason', type=str, required=False, default=''),
        ).parse(body)
        if error:
            return json_response(error=error)
        planned_start, planned_end, error = _validate_order_form(form)
        if error:
            return json_response(error=error)
        order = _create_inspection_work_order(
            request, record, sheet, system, form, client_token,
            planned_start, planned_end)
        return json_response(order.to_detail_view())


# ----------------------------------------------------------------------
# 巡检单导出（独立 export 权限，后端独立校验；导出为只读行为）
# ----------------------------------------------------------------------

class InspectionSheetExportView(View):
    """巡检单列表 Excel 导出：复用列表筛选条件，导出筛选范围内全部数据。"""

    @auth('equipment_lifecycle.inspection.export')
    def get(self, request):
        form, error = JsonParser(
            Argument('duty_from', type=str, required=False),
            Argument('duty_to', type=str, required=False),
            Argument('duty_date', type=str, required=False),
            Argument('template', type=int, required=False),
            Argument('status', type=str, required=False),
            Argument('keyword', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        qs = apply_tenant_filter(
            InspectionDutySheet.objects.select_related('template')
                .prefetch_related('persons', 'records'), request.user)
        qs, error = _filter_sheet_queryset(qs, form)
        if error:
            return json_response(error=error)
        count, error_resp = check_export_limit(qs)
        if error_resp:
            return error_resp
        if count == 0:
            return build_export_error_response('当前筛选条件下没有可导出的数据')
        record_audit_event(request, 'export', AUDIT_TARGET_INSPECTION_SHEET, '', '',
                           after_value={
                               'export_type': 'list_xlsx',
                               'count': count,
                               'filters': {
                                   'duty_from': form.duty_from or '',
                                   'duty_to': form.duty_to or '',
                                   'duty_date': form.duty_date or '',
                                   'template': form.template or '',
                                   'status': form.status or '',
                                   'keyword': form.keyword or '',
                               },
                           })
        return build_excel_response(
            inspection_export.export_filename('巡检单记录', 'xlsx'),
            inspection_export.LIST_SHEET_NAME,
            inspection_export.LIST_COLUMNS,
            inspection_export.build_list_rows(qs))


class InspectionSheetDetailExportBaseView(View):
    """巡检单详情导出基类：Excel（四轮矩阵双工作表）与 PDF（A4 纵向）。

    导出内容以巡检单已保存数据为准（快照 + recorded_rounds 最终状态），
    不包含明细实际填写时间，也没有迟填/逾期标记。
    """

    export_format = 'xlsx'

    @auth('equipment_lifecycle.inspection.export')
    def get(self, request, pk):
        try:
            sheet = inspection_services.get_sheet_for_user(request.user, pk)
        except InspectionValidationError as exc:
            return _error(exc)
        detail = sheet.to_detail_view()
        detail['records'] = inspection_services.append_record_disposition(
            request.user.tenant_id, detail['records'])
        response = inspection_export.build_detail_response(detail, self.export_format)
        record_audit_event(request, 'export', AUDIT_TARGET_INSPECTION_SHEET, sheet.id,
                           sheet.sheet_no,
                           after_value={'export_type': self.export_format,
                                        'duty_date': str(sheet.duty_date)})
        return response


class InspectionSheetDetailExportXlsxView(InspectionSheetDetailExportBaseView):
    """巡检单详情 Excel 导出（巡查单信息 + 四轮巡检明细）。"""

    export_format = 'xlsx'


class InspectionSheetDetailExportPdfView(InspectionSheetDetailExportBaseView):
    """巡检单详情 PDF 导出（巡检单专用 ReportLab 版式）。"""

    export_format = 'pdf'


class InspectionSheetBatchExportBaseView(View):
    """巡检单批量详情导出基类：按列表筛选条件导出全部匹配巡检单。

    - Excel：一个工作簿（巡检单汇总 + 每单"信息_单号/明细_单号"两个工作表）；
    - PDF：一个 ReportLab 文档流连续生成的合并 PDF（每单从新页开始）；
    - 后端重新执行筛选与租户隔离，不受分页参数影响，不信任前端详情数据；
    - Excel/PDF 数量上限分别校验（inspection_export.batch_export_limit）；
    - 无匹配数据返回统一业务错误；导出为只读行为，不修改任何业务数据。
    """

    export_format = 'xlsx'

    @auth('equipment_lifecycle.inspection.export')
    def get(self, request):
        form, error = JsonParser(
            Argument('duty_from', type=str, required=False),
            Argument('duty_to', type=str, required=False),
            Argument('duty_date', type=str, required=False),
            Argument('template', type=int, required=False),
            Argument('status', type=str, required=False),
            Argument('keyword', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        qs = apply_tenant_filter(
            InspectionDutySheet.objects.select_related(
                'template', 'submitted_by', 'created_by')
                .prefetch_related('persons', 'records'), request.user)
        qs, error = _filter_sheet_queryset(qs, form)
        if error:
            return json_response(error=error)
        count = qs.count()
        limit_error = inspection_export.check_batch_export_limit(
            count, self.export_format)
        if limit_error:
            return build_export_error_response(limit_error)
        if count == 0:
            return build_export_error_response('当前筛选条件下没有可导出的数据')
        sheets = list(qs)
        details = [sheet.to_detail_view() for sheet in sheets]
        inspection_services.append_batch_record_disposition(
            request.user.tenant_id, details)
        response = inspection_export.build_batch_detail_response(
            sheets, details, self.export_format)
        record_audit_event(request, 'export', AUDIT_TARGET_INSPECTION_SHEET, '', '',
                           after_value={
                               'export_type': f'batch_detail_{self.export_format}',
                               'count': len(sheets),
                               'filters': {
                                   'duty_from': form.duty_from or '',
                                   'duty_to': form.duty_to or '',
                                   'duty_date': form.duty_date or '',
                                   'template': form.template or '',
                                   'status': form.status or '',
                                   'keyword': form.keyword or '',
                               },
                           })
        return response


class InspectionSheetBatchExportXlsxView(InspectionSheetBatchExportBaseView):
    """巡检单批量详情 Excel 导出（汇总 + 每单双工作表，上限默认 500 条）。"""

    export_format = 'xlsx'


class InspectionSheetBatchExportPdfView(InspectionSheetBatchExportBaseView):
    """巡检单批量详情 PDF 导出（合并文档流，上限默认 100 条）。"""

    export_format = 'pdf'

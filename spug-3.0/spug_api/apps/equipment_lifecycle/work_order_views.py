# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——系统工单管理与异常转单视图（步骤 3.3，单账号协同流程）。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.work_order.view|add|edit|execute|close|del|export
- equipment_lifecycle.ledger.handle_exception（台账异常处置）

说明（2026-09 单账号协同流程改造）：
- 系统由多人共用一个账号操作，派发/接单/开始执行/提交复核/复核通过/复核退回
  环节已整体下线：对应视图与路由已删除（历史工单的派发/接单/复核字段保留展示）；
- 新工单创建即执行中（actual_start 自动记录），不要求负责人与参与人，
  不创建参与人员记录；
- 执行中通过 POST /work-orders/<id>/complete/ 完成工单（须已填写处理结果与
  处理记录），完成后进入"已完成"，可再关闭；取消仅限执行中（及历史兼容状态）。

双权限动作（has_perms 为任一匹配语义，须在视图内显式分别校验）：
- 故障生成维修工单：work_order.add + fault.view
- 台账异常转故障：ledger.handle_exception + fault.add
- 台账异常转工单：ledger.handle_exception + work_order.add

设计要点：
- 一张工单只关联一个作业系统，不建设跨系统影响关系；
- 作业系统/来源对象一律提交并存储稳定 ID，后端重新查询校验
  （租户、可用性、状态），不信任前端传来的名称、租户、状态和快照；
- affects_system_operation（作业期间是否影响系统运行）由后端保存前
  重新校验布尔类型；只有执行中且为真的故障维修工单才参与"维修中"计算；
- 状态流转只经动作接口，由后端状态机（SystemWorkOrder.STATE_TRANSITIONS）
  校验；普通编辑接口（PUT）仅限待派发（历史）/执行中工单且不得修改状态；
- 所有改变健康状态影响的工单操作在 health_recalc_lock + 单事务中完成，
  系统状态由 fault_services 统一重算（同事务写入）；
- 创建/转单以 client_token 幂等 + 窗口查重防重复，重复请求不产生重复数据；
- 写操作记录业务审计（record_audit_event）；删除权限仅执行受控取消，
  不物理删除。
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
from libs.pagination import paginate

from apps.logs.audit import record_audit_event
from apps.evidence.attachment_service import (
    AttachmentService, DefaultAttachmentConfig, ATTACHMENT_DELETE_DENIED_ERROR,
)
from apps.evidence.models import EvidenceAttachment

from apps.account.models import User
from apps.equipment_lifecycle import event_services, fault_services, work_order_services
from apps.equipment_lifecycle.fault_views import _parse_dt
from apps.equipment_lifecycle.models import (
    ITEM_RESULT_ABNORMAL,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_RETURNED,
    LEDGER_STATUS_VOID,
    LEGACY_LEDGER_TYPE_INSPECTION,
    LEDGER_TYPE_TEXT,
    LifecycleSystem,
    MAINTENANCE_SUBTYPE_DEFAULT,
    OperationLedger,
    OperationLedgerItem,
    RETIRED_WORK_TYPE_HINTS,
    SystemFault,
    SystemWorkOrder,
    WORK_ORDER_CREATABLE_TYPE_VALUES,
)
from apps.equipment_lifecycle.views import _read_json_body
from apps.equipment_lifecycle.work_order_services import (
    AUDIT_TARGET_WORK_ORDER,
    WORK_ORDER_ATTACHMENT_MODULE,
    WORK_ORDER_ATTACHMENT_OBJECT_TYPE,
    WorkOrderValidationError,
)

# 提交复核/追加处理记录允许的状态（仅执行中）
RECORD_ALLOWED_STATUSES = (SystemWorkOrder.STATUS_EXECUTING,)

IDEMPOTENCY_WINDOW_SECONDS = 30

# 台账异常明细可转单的台账状态（草稿/退回/作废不可转单）
CONVERTIBLE_LEDGER_STATUSES = (
    'submitted', 'reviewed',
)

DISPOSITION_STATUS_TEXT = {
    'none': '未处置',
    'converted_fault': '已转故障',
    'converted_work_order': '已转工单',
    'target_cancelled': '处置目标已取消或作废',
}


def _require_perm(user, code):
    """显式单项权限校验（has_perms 为任一匹配语义，双权限动作分别调用）。"""
    return user.has_perms([code])


def _validate_work_type_for_create(work_type):
    """顶层工单类型收敛校验（2026-09）：历史类型仅保留展示与筛选，
    新建/编辑不再允许选择。返回错误文案（None 表示合法）。"""
    if work_type not in SystemWorkOrder.TYPE_TEXT_MAP:
        return '工单类型不合法'
    if work_type not in WORK_ORDER_CREATABLE_TYPE_VALUES:
        hint = RETIRED_WORK_TYPE_HINTS.get(work_type)
        return f'工单类型已下线：{hint}' if hint else '工单类型已下线，不能再选择'
    return None


def _validate_maintenance_subtype(work_type, value):
    """维护二级分类校验与规范化（工单类型收敛）。

    - 专项维护：未传默认"一般维护"；传值必须合法（不静默吞掉非法值）；
    - 其他顶层类型：无业务含义，统一落默认值。
    返回 (subtype, error)。
    """
    if work_type == SystemWorkOrder.TYPE_SPECIAL_MAINTENANCE:
        if value in (None, ''):
            return MAINTENANCE_SUBTYPE_DEFAULT, None
        if value not in SystemWorkOrder.SUBTYPE_TEXT_MAP:
            return None, '维护分类不合法'
        return value, None
    return MAINTENANCE_SUBTYPE_DEFAULT, None


def _validate_affected_systems_rejected(body):
    """旧参数已随单系统简化删除：出现即拒绝，不静默忽略。"""
    if 'affected_system_ids' in body or 'affected_systems' in body:
        return '工单已不再支持受影响系统，请只提交一个作业系统'
    return None


def _get_order_for_user(pk, user, for_update=False):
    qs = SystemWorkOrder.objects.all()
    if for_update:
        qs = qs.select_for_update()
    if not getattr(user, 'is_supper', False):
        qs = qs.filter(tenant_id=user.tenant_id)
    return qs.filter(pk=pk).first()


def _get_active_system_for_user(pk, user):
    """取本租户可用（未停用）系统：新建/变更工单关联只允许选择可用系统。"""
    return LifecycleSystem.objects.filter(
        tenant_id=user.tenant_id, pk=pk, is_active=True).first()


def _get_system_for_user(pk, user):
    if not getattr(user, 'is_supper', False):
        return LifecycleSystem.objects.filter(tenant_id=user.tenant_id, pk=pk).first()
    return LifecycleSystem.objects.filter(pk=pk).first()


def _clean_text(value, limit):
    """可选文本字段规范化（None 视为空串，去首尾空白并限长）。"""
    return (value or '').strip()[:limit]


def _parse_planned_range(form):
    """解析计划起止时间并校验先后关系，返回 (start, end, error)。"""
    planned_start = _parse_dt(form.planned_start) if form.planned_start else None
    planned_end = _parse_dt(form.planned_end) if form.planned_end else None
    if form.planned_start and not planned_start:
        return None, None, '计划开始时间格式不正确'
    if form.planned_end and not planned_end:
        return None, None, '计划结束时间格式不正确'
    if planned_start and planned_end and planned_end < planned_start:
        return None, None, '计划结束时间不能早于计划开始时间'
    return planned_start, planned_end, None


def _resolve_affects_default(form):
    """影响运行缺省语义：未传为不影响；显式传值必须为布尔。返回 (affects, error)。"""
    if form.affects_system_operation is None:
        return False, None
    if not isinstance(form.affects_system_operation, bool):
        return None, '作业期间是否影响系统运行必须为布尔值'
    return bool(form.affects_system_operation), None


def _default_work_object_desc(fault):
    """故障转工单的作业对象描述默认值（对象名称/型号/编号以 / 连接）。"""
    parts = [fault.fault_object_name, fault.fault_object_model, fault.fault_object_sn]
    return ' / '.join(p for p in parts if p)


def _validate_order_fields(body, request, for_update=False, order=None):
    """校验工单业务字段（创建与编辑共用），返回 (data, error)。

    data 包含：title/work_type/maintenance_subtype/priority/system/
    affects_system_operation/planned_start/planned_end/work_requirement/
    work_steps/work_location/work_object_desc/material_note/client_token。
    状态字段一律忽略：普通编辑接口不得修改状态。
    """
    form, error = JsonParser(
        Argument('title', type=str, required=True, help='工单标题'),
        Argument('work_type', type=str, required=True, help='工单类型'),
        Argument('maintenance_subtype', type=str, required=False, default=None),
        Argument('priority', type=str, required=False, default=SystemWorkOrder.PRIORITY_NORMAL),
        Argument('system', type=int, required=True, help='作业系统ID'),
        Argument('affects_system_operation', type=bool, required=False, default=False),
        Argument('work_location', type=str, required=False, default=''),
        Argument('work_object_desc', type=str, required=False, default=''),
        Argument('planned_start', type=str, required=False, default=None),
        Argument('planned_end', type=str, required=False, default=None),
        Argument('work_requirement', type=str, required=False, default=''),
        Argument('work_steps', type=str, required=False, default=''),
        Argument('material_note', type=str, required=False, default=''),
        Argument('client_token', type=str, required=False, default=''),
    ).parse(body)
    if error:
        return None, error

    title = (form.title or '').strip()
    if not title:
        return None, '工单标题不能为空'
    # 顶层工单类型收敛：历史类型仅保留展示，新建/编辑拒绝再选
    error = _validate_work_type_for_create(form.work_type)
    if error:
        return None, error
    maintenance_subtype, error = _validate_maintenance_subtype(
        form.work_type, form.maintenance_subtype)
    if error:
        return None, error
    if form.priority not in SystemWorkOrder.PRIORITY_TEXT_MAP:
        return None, '优先级不合法'
    # 作业期间是否影响系统运行：后端重新校验布尔类型（不信任前端任意值）
    if not isinstance(form.affects_system_operation, bool):
        return None, '作业期间是否影响系统运行必须为布尔值'

    # 作业系统：以稳定 ID 重新查询（租户 + 可用性；编辑未变更时保持历史关联）
    system = _get_active_system_for_user(form.system, request.user)
    if not system:
        if for_update and order and order.system_id == form.system:
            system = order.system  # 未变更的作业系统即使停用也保持原关联
        else:
            return None, '作业系统不存在、已停用或无权限'

    planned_start, planned_end, error = _parse_planned_range(form)
    if error:
        return None, error

    return {
        'title': title,
        'work_type': form.work_type,
        'maintenance_subtype': maintenance_subtype,
        'priority': form.priority,
        'system': system,
        'affects_system_operation': bool(form.affects_system_operation),
        'planned_start': planned_start,
        'planned_end': planned_end,
        'work_requirement': _clean_text(form.work_requirement, 2000),
        'work_steps': _clean_text(form.work_steps, 2000),
        'work_location': _clean_text(form.work_location, 200),
        'work_object_desc': _clean_text(form.work_object_desc, 1000),
        'material_note': _clean_text(form.material_note, 500),
        'client_token': _clean_text(form.client_token, 64),
    }, None


def _order_audit_summary(order):
    return {
        'work_no': order.work_no,
        'title': order.title,
        'work_type': order.work_type,
        'maintenance_subtype': order.maintenance_subtype,
        'status': order.status,
        'priority': order.priority,
        'system': order.system_name,
        'affects_system_operation': order.affects_system_operation,
        'owner': order.owner.username if order.owner_id else '',
        'source_type': order.source_type,
        'source_no': order.source_no,
    }


def _item_value_text(item):
    """台账明细填写值文本（转入单据的现象描述用）。"""
    if item.input_type == 'number' and item.value_number is not None:
        unit = item.unit_snapshot or ''
        return f'{item.value_number}{unit}'
    if item.input_type == 'boolean' and item.value_bool is not None:
        return '是' if item.value_bool else '否'
    return item.value_text or ''


def _get_ledger_item_for_convert(ledger_pk, item_pk, user, for_update=False):
    """重新查询台账与明细并校验：URL 匹配、同租户、可转单状态。

    返回 (item, ledger, error)。转单前必须重新查询台账和明细状态，
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
    # 旧巡检台账类型已删除（旧巡检台账下线改造）：异常转单一律显式拒绝，
    # 新巡检走 /inspection-sheets/.../convert-* 独立接口；周月/季维护不受影响。
    if ledger.ledger_type == LEGACY_LEDGER_TYPE_INSPECTION:
        return None, None, '旧巡检台账（历史）已删除，不能转故障或转工单'
    if ledger.status in (LEDGER_STATUS_DRAFT, LEDGER_STATUS_RETURNED, LEDGER_STATUS_VOID):
        return None, None, '草稿、已退回或已作废的台账不能转单'
    if ledger.status not in CONVERTIBLE_LEDGER_STATUSES:
        return None, None, '当前台账状态不能转单'
    if item.result != ITEM_RESULT_ABNORMAL:
        return None, None, '只有结果为"异常"的明细可以转单'
    return item, ledger, None


def _check_item_redispose(item, user, re_dispose_reason, kind):
    """异常明细再次转单校验（任务十四：拒绝或要求重新处置原因）。

    返回 error（None 表示允许）。规则：
    - 已存在同来源的未取消{kind} → 一律拒绝（不能静默重复创建）；
    - 仅存在已取消{kind}（或已有未取消故障而转工单）→ 必须填写重新处置原因；
    - 首次处置 → 直接放行。
    """
    reason = (re_dispose_reason or '').strip()
    if kind == 'fault':
        existing = SystemFault.objects.filter(
            tenant_id=user.tenant_id, source_ledger_item=item).order_by('-id')
        active = existing.exclude(status=SystemFault.STATUS_CANCELLED).first()
        latest = existing.first()
        if active:
            return f'该异常明细已转故障（{active.fault_no}），不能重复转换；后续处理请从该故障生成维修工单'
        if latest and not reason:
            return '该异常明细曾转故障（目标已作废）。如需重新处置请填写重新处置原因'
        return None
    # kind == 'work_order'
    existing_orders = SystemWorkOrder.objects.filter(
        tenant_id=user.tenant_id, source_ledger_item=item).order_by('-id')
    active_order = existing_orders.exclude(
        status=SystemWorkOrder.STATUS_CANCELLED).first()
    latest_order = existing_orders.first()
    if active_order:
        return f'该异常明细已转工单（{active_order.work_no}），不能重复转换'
    active_fault = SystemFault.objects.filter(
        tenant_id=user.tenant_id, source_ledger_item=item).exclude(
        status=SystemFault.STATUS_CANCELLED).first()
    if active_fault:
        if not reason:
            return (f'该异常明细已转故障（{active_fault.fault_no}）。'
                    f'维修工单应从该故障生成；如确需直接转工单请填写重新处置原因')
        return None
    if latest_order and not reason:
        return '该异常明细曾转工单（目标已作废）。如需重新处置请填写重新处置原因'
    return None


class WorkOrderView(View):
    """工单列表 / 人工创建。"""

    @auth('equipment_lifecycle.work_order.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('status', type=str, required=False),
            Argument('work_type', type=str, required=False),
            Argument('priority', type=str, required=False),
            Argument('system', type=int, required=False),
            Argument('source_type', type=str, required=False),
            Argument('keyword', type=str, required=False),
            Argument('planned_from', type=str, required=False),
            Argument('planned_to', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        query = SystemWorkOrder.objects.all()
        if not getattr(request.user, 'is_supper', False):
            query = query.filter(tenant_id=request.user.tenant_id)
        if form.status:
            if form.status not in SystemWorkOrder.STATUS_TEXT_MAP:
                return json_response(error='工单状态筛选值不合法')
            query = query.filter(status=form.status)
        if form.work_type:
            if form.work_type not in SystemWorkOrder.TYPE_TEXT_MAP:
                return json_response(error='工单类型筛选值不合法')
            query = query.filter(work_type=form.work_type)
        if form.priority:
            if form.priority not in SystemWorkOrder.PRIORITY_TEXT_MAP:
                return json_response(error='优先级筛选值不合法')
            query = query.filter(priority=form.priority)
        if form.source_type:
            if form.source_type not in SystemWorkOrder.SOURCE_TEXT_MAP:
                return json_response(error='来源类型筛选值不合法')
            query = query.filter(source_type=form.source_type)
        if form.system:
            query = query.filter(system_id=form.system)
        if form.keyword:
            query = query.filter(
                Q(work_no__icontains=form.keyword) | Q(title__icontains=form.keyword) |
                Q(system_name__icontains=form.keyword) |
                Q(source_no__icontains=form.keyword))
        planned_from = _parse_dt(form.planned_from) if form.planned_from else None
        planned_to = _parse_dt(form.planned_to) if form.planned_to else None
        if form.planned_from and not planned_from:
            return json_response(error='计划开始时间起始格式不正确')
        if form.planned_to and not planned_to:
            return json_response(error='计划开始时间截止格式不正确')
        if planned_from:
            query = query.filter(planned_start__gte=planned_from)
        if planned_to:
            query = query.filter(planned_start__lt=planned_to)

        page, page_size = paginate(request)
        total = query.count()
        records = query.select_related('owner')[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.work_order.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        err = _validate_affected_systems_rejected(body)
        if err:
            return json_response(error=err)
        data, error = _validate_order_fields(body, request)
        if error:
            return json_response(error=error)

        # 幂等：同 client_token 视为同一请求，返回已有工单
        existing = work_order_services.find_existing_by_token(
            request.user.tenant_id, data['client_token'])
        if existing:
            return json_response(existing.to_detail_view())

        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    # 防重复提交后备：同租户/同作业系统/同标题窗口期内视为重复
                    if check_recent_duplicate(SystemWorkOrder, {
                        'tenant_id': request.user.tenant_id,
                        'system_id': data['system'].id,
                        'title': data['title'],
                    }, window_seconds=IDEMPOTENCY_WINDOW_SECONDS):
                        return json_response(error='请勿重复提交相同工单')
                    order = work_order_services.create_work_order_record(
                        tenant_id=request.user.tenant_id,
                        created_by=request.user,
                        request=request,
                        **data,
                    )
                    record_audit_event(request, 'create', AUDIT_TARGET_WORK_ORDER,
                                       order.id, order.work_no,
                                       after_value=_order_audit_summary(order))
        except fault_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        return json_response(order.to_detail_view())


class WorkOrderDetailView(View):
    """工单详情 / 编辑（历史待派发或执行中工单）。"""

    @auth('equipment_lifecycle.work_order.view')
    def get(self, request, pk):
        order = _get_order_for_user(pk, request.user)
        if not order:
            return json_response(error='工单不存在')
        return json_response(order.to_detail_view())

    @auth('equipment_lifecycle.work_order.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        err = _validate_affected_systems_rejected(body)
        if err:
            return json_response(error=err)
        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    order = _get_order_for_user(pk, request.user, for_update=True)
                    if not order:
                        return json_response(error='工单不存在')
                    if order.status not in SystemWorkOrder.EDITABLE_STATUSES:
                        return json_response(error='只有待派发（历史）或执行中的工单可以编辑')
                    data, error = _validate_order_fields(
                        body, request, for_update=True, order=order)
                    if error:
                        return json_response(error=error)
                    before_summary = _order_audit_summary(order)
                    old_system_id = order.system_id
                    order.title = data['title']
                    order.work_type = data['work_type']
                    order.maintenance_subtype = data['maintenance_subtype']
                    order.priority = data['priority']
                    order.system = data['system']
                    order.system_code = data['system'].system_code
                    order.system_name = data['system'].name
                    order.system_location = data['system'].install_location
                    order.affects_system_operation = data['affects_system_operation']
                    order.work_location = data['work_location']
                    order.work_object_desc = data['work_object_desc']
                    order.planned_start = data['planned_start']
                    order.planned_end = data['planned_end']
                    order.work_requirement = data['work_requirement']
                    order.work_steps = data['work_steps']
                    order.material_note = data['material_note']
                    order.updated_at = timezone.now()
                    order.updated_by = request.user
                    order.save()

                    related_ids = {old_system_id, order.system_id}
                    fault_services.recompute_systems_health(
                        request.user.tenant_id, related_ids, request=request,
                        audit_reason='编辑工单 ' + order.work_no)
                    record_audit_event(request, 'update', AUDIT_TARGET_WORK_ORDER,
                                       order.id, order.work_no,
                                       before_value=before_summary,
                                       after_value=_order_audit_summary(order))
                    order.refresh_from_db()
        except fault_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        return json_response(order.to_detail_view())


class WorkOrderActionBaseView(View):
    """工单状态动作公共流程：行锁 + 状态机校验 + 同事务健康重算 + 审计。

    handle_locked 可通过 self.audit_extra 附加审计 after_value 内容
    （视图实例每请求新建，实例属性安全）。
    """

    ACTION_NAME = ''
    audit_action = 'update'
    # 是否在动作后重算作业系统健康状态（默认重算，幂等无害）
    recompute_after = True
    audit_extra = None

    def post(self, request, pk):
        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    order = _get_order_for_user(pk, request.user, for_update=True)
                    if not order:
                        return json_response(error='工单不存在')
                    before_status = order.status
                    self.audit_extra = None
                    error = self.handle_locked(request, order)
                    if error:
                        return json_response(error=error)
                    if self.recompute_after:
                        fault_services.recompute_systems_health(
                            order.tenant_id, [order.system_id], request=request,
                            audit_reason=f'{self.ACTION_NAME} ' + order.work_no)
                    record_audit_event(request, self.audit_action, AUDIT_TARGET_WORK_ORDER,
                                       order.id, order.work_no,
                                       before_value={'status': before_status},
                                       after_value={**_order_audit_summary(order),
                                                    **(self.audit_extra or {})})
        except fault_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        order.refresh_from_db()
        return json_response(order.to_detail_view())

    def handle_locked(self, request, order):
        raise NotImplementedError


class WorkOrderCompleteView(WorkOrderActionBaseView):
    """完成工单：执行中 → 已完成（单账号协同流程，无复核环节）。

    - 校验：工单处于执行中、已填写处理结果、存在至少一条处理记录；
      工时与系统中断时间为选填浮点数（沿用原提交复核字段的校验规则）；
    - 保存处理结果/工时/系统中断时间，写入 actual_end 与完成操作账号
      completed_by / completed_at；不写 reviewer / reviewed_at
      （历史复核语义不得伪造）；
    - 同事务写入工单完成履历（SystemEvent 'complete'），审计记录原状态、
      新状态、处理结果是否填写与实际完成时间；
    - 行锁 + 状态机校验保证并发与幂等：重复提交因状态已非执行中被拒绝。
    """

    ACTION_NAME = '完成工单'

    @auth('equipment_lifecycle.work_order.execute')
    def post(self, request, pk):
        return super().post(request, pk)

    def handle_locked(self, request, order):
        if order.status != SystemWorkOrder.STATUS_EXECUTING:
            return '只有执行中的工单可以完成工单'
        body = _read_json_body(request) or {}
        form, error = JsonParser(
            Argument('process_result', type=str, required=True, help='处理结果'),
            Argument('work_hours', type=float, required=False, default=None),
            Argument('interrupt_hours', type=float, required=False, default=None),
        ).parse(body)
        if error:
            return error
        process_result = (form.process_result or '').strip()
        if not process_result:
            return '完成工单前必须填写处理结果'
        if not order.handling_records.exists():
            return '完成工单前必须填写处理过程（处理记录）'
        now = timezone.now()
        order.process_result = process_result[:2000]
        if form.work_hours is not None:
            order.work_hours = form.work_hours
        if form.interrupt_hours is not None:
            order.interrupt_hours = form.interrupt_hours
        order.status = SystemWorkOrder.STATUS_COMPLETED
        order.actual_end = now
        order.completed_by = request.user
        order.completed_at = now
        order.updated_at = now
        order.updated_by = request.user
        order.save(update_fields=['process_result', 'work_hours', 'interrupt_hours',
                                  'status', 'actual_end', 'completed_by', 'completed_at',
                                  'updated_at', 'updated_by'])
        self.audit_extra = {
            'action': 'complete_work_order',
            'process_result_filled': True,
            'actual_end': order.actual_end.strftime('%Y-%m-%d %H:%M:%S'),
        }
        # 步骤 3.4：工单完成履历（只落作业系统，同一事务）
        event_services.record_work_order_lifecycle_events(
            order, 'complete', occurred_at=order.actual_end, created_by=request.user)
        return None


class WorkOrderCloseView(WorkOrderActionBaseView):
    """关闭：已完成 → 已关闭（关闭前必须确认结果完整）。"""

    ACTION_NAME = '关闭'

    @auth('equipment_lifecycle.work_order.close')
    def post(self, request, pk):
        return super().post(request, pk)

    def handle_locked(self, request, order):
        if order.status != SystemWorkOrder.STATUS_COMPLETED:
            return '只有已完成的工单可以关闭'
        if not (order.process_result or '').strip():
            return '处理结果不完整，不能关闭'
        order.status = SystemWorkOrder.STATUS_CLOSED
        order.closed_by = request.user
        order.closed_at = timezone.now()
        order.updated_at = timezone.now()
        order.updated_by = request.user
        order.save(update_fields=['status', 'closed_by', 'closed_at', 'updated_at', 'updated_by'])
        return None


class WorkOrderCancelView(WorkOrderActionBaseView):
    """受控取消（del 权限）：不物理删除，已取消工单不参与健康状态计算。"""

    ACTION_NAME = '取消'
    audit_action = 'delete'

    @auth('equipment_lifecycle.work_order.del')
    def post(self, request, pk):
        return super().post(request, pk)

    def handle_locked(self, request, order):
        if order.status not in SystemWorkOrder.CANCELLABLE_STATUSES:
            return '已完成或已关闭的工单不能取消'
        body = _read_json_body(request) or {}
        form, error = JsonParser(
            Argument('cancel_reason', type=str, required=True, help='取消原因'),
        ).parse(body)
        if error:
            return error
        reason = (form.cancel_reason or '').strip()
        if not reason:
            return '取消必须填写原因'
        order.status = SystemWorkOrder.STATUS_CANCELLED
        order.cancelled_by = request.user
        order.cancelled_at = timezone.now()
        order.cancel_reason = reason[:500]
        order.updated_at = timezone.now()
        order.updated_by = request.user
        order.save(update_fields=['status', 'cancelled_by', 'cancelled_at', 'cancel_reason',
                                  'updated_at', 'updated_by'])
        # 步骤 3.4：工单取消履历（追加新事件，原事件保留）
        event_services.record_work_order_lifecycle_events(
            order, 'cancel', detail={'cancel_reason': order.cancel_reason},
            created_by=request.user)
        return None


class WorkOrderHandlingRecordView(View):
    """工单处理记录：按处理时间正序的时间线 / 追加记录（仅执行中）。"""

    @auth('equipment_lifecycle.work_order.view')
    def get(self, request, pk):
        order = _get_order_for_user(pk, request.user)
        if not order:
            return json_response(error='工单不存在')
        query = order.handling_records.all()
        page, page_size = paginate(request, default_page_size=100)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.work_order.execute')
    def post(self, request, pk):
        form, error = JsonParser(
            Argument('handled_at', type=str, required=True, help='处理时间'),
            Argument('content', type=str, required=True, help='处理内容'),
            Argument('result', type=str, required=False, default=''),
            Argument('work_hours', type=float, required=False, default=None),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        handled_at = _parse_dt(form.handled_at)
        if not handled_at:
            return json_response(error='处理时间格式不正确，应为 YYYY-MM-DD HH:MM')
        content = (form.content or '').strip()
        if not content:
            return json_response(error='处理内容不能为空')
        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    order = _get_order_for_user(pk, request.user, for_update=True)
                    if not order:
                        return json_response(error='工单不存在')
                    if order.status not in RECORD_ALLOWED_STATUSES:
                        return json_response(error='只有执行中的工单可以追加处理记录')
                    record = order.handling_records.create(
                        tenant_id=order.tenant_id,
                        work_order=order,
                        handled_at=handled_at,
                        handler=request.user,
                        content=content[:2000],
                        result=(form.result or '').strip()[:200],
                        work_hours=form.work_hours,
                    )
                    record_audit_event(request, 'create', AUDIT_TARGET_WORK_ORDER,
                                       order.id, order.work_no,
                                       after_value={'action': 'add_handling_record',
                                                    'record_id': record.id})
        except fault_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        return json_response(record.to_view())


class WorkOrderHandlingRecordDetailView(View):
    """工单处理记录更正：保存原内容、新内容和更正原因，不静默覆盖。"""

    @auth('equipment_lifecycle.work_order.edit')
    def put(self, request, pk, rid):
        form, error = JsonParser(
            Argument('handled_at', type=str, required=False, default=None),
            Argument('content', type=str, required=True, help='处理内容'),
            Argument('result', type=str, required=False, default=''),
            Argument('correction_reason', type=str, required=True, help='更正原因'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        content = (form.content or '').strip()
        if not content:
            return json_response(error='处理内容不能为空')
        correction_reason = (form.correction_reason or '').strip()
        if not correction_reason:
            return json_response(error='更正原因不能为空')
        handled_at = None
        if form.handled_at:
            handled_at = _parse_dt(form.handled_at)
            if not handled_at:
                return json_response(error='处理时间格式不正确，应为 YYYY-MM-DD HH:MM')
        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    order = _get_order_for_user(pk, request.user, for_update=True)
                    if not order:
                        return json_response(error='工单不存在')
                    if order.status not in RECORD_ALLOWED_STATUSES:
                        return json_response(error='只有执行中的工单可以更正处理记录')
                    record = order.handling_records.filter(pk=rid).first()
                    if not record:
                        return json_response(error='处理记录不存在')
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
                    record_audit_event(request, 'update', AUDIT_TARGET_WORK_ORDER,
                                       order.id, order.work_no,
                                       after_value={'action': 'correct_handling_record',
                                                    'record_id': record.id,
                                                    'reason': correction_reason[:200]})
        except fault_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        return json_response(record.to_view())


class WorkOrderHandlingAttachmentView(View):
    """工单处理记录附件（复用 EvidenceAttachment 能力）。

    访问前先校验处理记录所属工单存在且属于当前租户。
    """

    @auth('equipment_lifecycle.work_order.view')
    def get(self, request, pk, rid):
        order = _get_order_for_user(pk, request.user)
        if not order:
            return json_response(error='工单不存在')
        record = order.handling_records.filter(pk=rid).first()
        if not record:
            return json_response(error='处理记录不存在')
        attachments = AttachmentService.list(
            request.user, WORK_ORDER_ATTACHMENT_MODULE,
            WORK_ORDER_ATTACHMENT_OBJECT_TYPE, record.id)
        return json_response({'data': attachments})

    @auth('equipment_lifecycle.work_order.execute')
    def post(self, request, pk, rid):
        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    order = _get_order_for_user(pk, request.user, for_update=True)
                    if not order:
                        return json_response(error='工单不存在')
                    if order.status not in RECORD_ALLOWED_STATUSES:
                        return json_response(error='只有执行中的工单可以上传处理附件')
                    record = order.handling_records.filter(pk=rid).first()
                    if not record:
                        return json_response(error='处理记录不存在')
                    file = request.FILES.get('file')
                    if not file:
                        return json_response(error='缺少上传文件')
                    att, error = AttachmentService.upload(
                        file, request.user, WORK_ORDER_ATTACHMENT_MODULE,
                        WORK_ORDER_ATTACHMENT_OBJECT_TYPE, record.id,
                        config=DefaultAttachmentConfig, owner_tenant_id=order.tenant_id)
                    if error:
                        return json_response(error=error)
                    record_audit_event(request, 'create', AUDIT_TARGET_WORK_ORDER,
                                       order.id, order.work_no,
                                       after_value={'action': 'upload_handling_attachment',
                                                    'record_id': record.id,
                                                    'file_name': att.file_name})
        except fault_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        return json_response(att.to_view())


class WorkOrderHandlingAttachmentDetailView(View):
    @auth('equipment_lifecycle.work_order.edit')
    def delete(self, request, pk, rid, aid):
        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    order = _get_order_for_user(pk, request.user, for_update=True)
                    if not order:
                        return json_response(error='工单不存在')
                    if order.status not in RECORD_ALLOWED_STATUSES:
                        return json_response(error='只有执行中的工单可以删除处理附件')
                    record = order.handling_records.filter(pk=rid).first()
                    if not record:
                        return json_response(error='处理记录不存在')
                    att = EvidenceAttachment.objects.filter(
                        tenant_id=order.tenant_id, is_deleted=False, pk=aid,
                        module=WORK_ORDER_ATTACHMENT_MODULE,
                        object_type=WORK_ORDER_ATTACHMENT_OBJECT_TYPE,
                        object_id=str(record.id)).first()
                    if not att:
                        return json_response(error=ATTACHMENT_DELETE_DENIED_ERROR)
                    error = AttachmentService.soft_delete(
                        request.user, aid, WORK_ORDER_ATTACHMENT_MODULE,
                        WORK_ORDER_ATTACHMENT_OBJECT_TYPE, reason='工单处理记录附件删除')
                    if error:
                        return json_response(error=error)
                    record_audit_event(request, 'delete', AUDIT_TARGET_WORK_ORDER,
                                       order.id, order.work_no,
                                       after_value={'action': 'delete_handling_attachment',
                                                    'record_id': record.id,
                                                    'file_name': att.file_name})
        except fault_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        return json_response({})


class WorkOrderHandlingAttachmentDownloadView(View):
    @auth('equipment_lifecycle.work_order.view')
    def get(self, request, pk, rid, aid):
        order = _get_order_for_user(pk, request.user)
        if not order:
            return json_response(error='工单不存在')
        record = order.handling_records.filter(pk=rid).first()
        if not record:
            return json_response(error='处理记录不存在')
        response, error = AttachmentService.download_response(
            request.user, aid, WORK_ORDER_ATTACHMENT_MODULE,
            WORK_ORDER_ATTACHMENT_OBJECT_TYPE)
        if error:
            return json_response(error=error)
        return response


class WorkOrderCandidateSystemsView(View):
    """工单表单系统候选项：本租户可用系统（请求只提交系统 ID）。"""

    @auth('equipment_lifecycle.work_order.view')
    def get(self, request):
        systems = LifecycleSystem.objects.filter(
            tenant_id=request.user.tenant_id, is_active=True).order_by('system_code')
        return json_response({'data': [{
            'id': s.id,
            'system_code': s.system_code,
            'name': s.name,
            'install_location': s.install_location,
        } for s in systems]})


class WorkOrderCandidateUsersView(View):
    """人员候选项：当前租户内有效账户（值班巡检人员选择等场景复用；
    工单不再指派负责人/参与人，历史派发弹窗已下线）。"""

    @auth('equipment_lifecycle.work_order.view')
    def get(self, request):
        users = User.objects.filter(
            tenant_id=request.user.tenant_id, is_active=True,
            deleted_at__isnull=True).order_by('username')
        return json_response({'data': [{
            'id': u.id,
            'username': u.username,
            'nickname': u.nickname or u.username,
        } for u in users]})


class FaultWorkOrdersView(View):
    """按故障查询其生成的工单（故障详情"关联工单"页签）。"""

    @auth('equipment_lifecycle.work_order.view')
    def get(self, request, pk):
        if not _require_perm(request.user, 'equipment_lifecycle.fault.view'):
            return json_response(error='权限拒绝')
        if not getattr(request.user, 'is_supper', False):
            fault = SystemFault.objects.filter(tenant_id=request.user.tenant_id, pk=pk).first()
        else:
            fault = SystemFault.objects.filter(pk=pk).first()
        if not fault:
            return json_response(error='故障记录不存在')
        query = SystemWorkOrder.objects.filter(
            tenant_id=fault.tenant_id, source_type='fault', source_fault=fault)
        page, page_size = paginate(request, default_page_size=50)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })


class FaultCreateWorkOrderView(View):
    """故障生成维修工单（故障详情"生成维修工单"操作）。

    - 只有未作废的有效故障可以生成工单；
    - 一个故障允许生成多张维修工单（不用来源唯一约束阻止）；
    - 每次创建请求必须携带幂等键（client_token），重复提交返回已有工单；
    - 作业期间影响系统运行默认为"否"（拆下部件离线维修不改变系统状态），
      仅用户明确选择影响运行时才参与健康状态计算；
    - 工单完成不自动关闭来源故障（故障恢复由步骤 3.1 流程确认）。
    """

    @auth('equipment_lifecycle.work_order.add')
    def post(self, request, pk):
        if not _require_perm(request.user, 'equipment_lifecycle.fault.view'):
            return json_response(error='权限拒绝')
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        err = _validate_affected_systems_rejected(body)
        if err:
            return json_response(error=err)
        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    fault_qs = SystemFault.objects.select_for_update().select_related(
                        'system')
                    if not getattr(request.user, 'is_supper', False):
                        fault_qs = fault_qs.filter(tenant_id=request.user.tenant_id)
                    fault = fault_qs.filter(pk=pk).first()
                    if not fault:
                        return json_response(error='故障记录不存在')
                    if fault.status == SystemFault.STATUS_CANCELLED:
                        return json_response(error='已作废的故障不能生成工单')

                    client_token = (body.get('client_token') or '').strip()[:64]
                    existing = work_order_services.find_existing_by_token(
                        request.user.tenant_id, client_token,
                        source_type='fault', source_object=fault)
                    if existing:
                        return json_response(existing.to_detail_view())

                    data, error = self._build_data(body, request, fault)
                    if error:
                        return json_response(error=error)
                    order = work_order_services.create_work_order_record(
                        tenant_id=request.user.tenant_id,
                        created_by=request.user,
                        source_type='fault',
                        source_fault=fault,
                        source_no=fault.fault_no,
                        request=request,
                        **data,
                    )
                    record_audit_event(request, 'create', AUDIT_TARGET_WORK_ORDER,
                                       order.id, order.work_no,
                                       after_value={**_order_audit_summary(order),
                                                    'source_fault': fault.fault_no})
        except fault_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        return json_response(order.to_detail_view())

    def _build_data(self, body, request, fault):
        """校验故障转工单载荷，返回 (create_work_order_record 参数, error)。"""
        form, error = JsonParser(
            Argument('title', type=str, required=False, default=''),
            Argument('work_type', type=str, required=False, default=SystemWorkOrder.TYPE_REPAIR),
            Argument('priority', type=str, required=False, default=SystemWorkOrder.PRIORITY_NORMAL),
            Argument('system', type=int, required=False, default=None),
            Argument('affects_system_operation', type=bool, required=False, default=None),
            Argument('work_location', type=str, required=False, default=''),
            Argument('work_object_desc', type=str, required=False, default=''),
            Argument('planned_start', type=str, required=False, default=None),
            Argument('planned_end', type=str, required=False, default=None),
            Argument('work_requirement', type=str, required=False, default=''),
            Argument('work_steps', type=str, required=False, default=''),
            Argument('material_note', type=str, required=False, default=''),
        ).parse(body)
        if error:
            return None, error

        title = _clean_text(form.title, 100) or f'{fault.fault_no} 维修工单'
        # 故障生成的工单固定为故障维修类型（2026-09 类型收敛：专项维护等
        # 类型不应从故障生成；历史版本曾允许传任意合法类型，现显式拒绝）
        if form.work_type != SystemWorkOrder.TYPE_REPAIR:
            return None, '故障生成的工单固定为故障维修类型'
        if form.priority not in SystemWorkOrder.PRIORITY_TEXT_MAP:
            return None, '优先级不合法'

        # 作业系统固定默认为故障所属系统；不接受改派其他系统（需要时单独建单）
        if form.system is not None and form.system != fault.system_id:
            return None, '工单系统固定为故障所属系统，不能指定其他系统'
        system = fault.system

        # 影响运行默认值：默认"作业期间不影响系统运行"（拆下部件离线维修不改变系统状态）。
        # 只有用户明确选择影响运行时才参与健康状态计算，前端默认值与后端一致。
        affects, error = _resolve_affects_default(form)
        if error:
            return None, error

        planned_start, planned_end, error = _parse_planned_range(form)
        if error:
            return None, error

        # 默认带入故障现象与故障位置
        work_requirement = (_clean_text(form.work_requirement, 2000)
                            or fault.phenomenon)[:2000]
        work_object_desc = (_clean_text(form.work_object_desc, 1000)
                            or _default_work_object_desc(fault))[:1000]

        return ({
            'title': title,
            'work_type': form.work_type,
            'priority': form.priority,
            'system': system,
            'affects_system_operation': affects,
            'planned_start': planned_start,
            'planned_end': planned_end,
            'work_requirement': work_requirement,
            'work_steps': _clean_text(form.work_steps, 2000),
            'work_location': (_clean_text(form.work_location, 200)
                              or fault.fault_location)[:200],
            'work_object_desc': work_object_desc,
            'material_note': _clean_text(form.material_note, 500),
            'client_token': _clean_text(body.get('client_token'), 64),
        }, None)


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
        if not _require_perm(request.user, 'equipment_lifecycle.fault.add'):
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
                        item, request.user, body.get('re_dispose_reason'), 'fault')
                    if error:
                        return json_response(error=error)

                    form, error = JsonParser(
                        Argument('occurred_at', type=str, required=False, default=''),
                        Argument('discovery', type=str, required=False,
                                 default=SystemFault.DISCOVERY_PATROL),
                        Argument('level', type=str, required=False,
                                 default=SystemFault.LEVEL_MINOR),
                        Argument('affects_system_operation', type=bool, required=False, default=False,
                                 help='是否影响系统运行，默认不影响（部件故障）'),
                        Argument('impact_status', type=str, required=False, default='',
                                 help='系统影响程度：影响系统运行时必填（降级/故障/中断）'),
                        Argument('phenomenon', type=str, required=False, default=''),
                        Argument('re_dispose_reason', type=str, required=False, default=''),
                    ).parse(body)
                    if error:
                        return json_response(error=error)

                    occurred_at = _parse_dt(form.occurred_at) if form.occurred_at else None
                    if form.occurred_at and not occurred_at:
                        return json_response(error='故障发生时间格式不正确')
                    if not occurred_at:
                        occurred_at = item.executed_at
                    if not occurred_at:
                        # 明细无独立执行时间时取台账实际执行日期（USE_TZ=False 直接取本地 naive）
                        occurred_at = datetime.combine(ledger.executed_date, datetime.min.time())
                    if occurred_at > timezone.now():
                        return json_response(error='故障发生时间不能晚于当前时间')
                    if form.discovery not in SystemFault.DISCOVERY_TEXT_MAP:
                        return json_response(error='故障发现方式不合法')
                    if form.level not in SystemFault.LEVEL_TEXT_MAP:
                        return json_response(error='故障级别不合法')
                    # 默认"部件故障但不影响系统运行"；仅明确选择影响运行时才要求影响程度
                    affects = bool(form.affects_system_operation)
                    if affects:
                        if form.impact_status not in SystemFault.IMPACT_TEXT_MAP:
                            return json_response(error='影响系统运行时必须选择影响程度（降级/故障/中断）')
                        impact_status = form.impact_status
                    else:
                        impact_status = ''

                    phenomenon = (form.phenomenon or '').strip()
                    if not phenomenon:
                        phenomenon = self._compose_phenomenon(item, ledger)

                    fault = fault_services.create_fault_record(
                        tenant_id=request.user.tenant_id,
                        created_by=request.user,
                        system=item.system,
                        affects_system_operation=affects,
                        impact_status=impact_status,
                        occurred_at=occurred_at,
                        discovery=form.discovery,
                        level=form.level,
                        phenomenon=phenomenon,
                        fault_location='',
                        source_type='ledger_item',
                        source_ledger_item=item,
                        request=request,
                    )
                    # 步骤 3.4：台账异常处置履历（来源 ledger_item，与转单同一事务）
                    event_services.record_ledger_convert_event(
                        item, ledger, 'convert_to_fault', target_no=fault.fault_no,
                        created_by=request.user)
                    record_audit_event(request, 'create', 'el_system_fault',
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
        except fault_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        fault_data = SystemFault.objects.select_related('system').get(pk=fault.id)
        return json_response(fault_data.to_detail_view())

    def _compose_phenomenon(self, item, ledger):
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


class LedgerItemConvertToWorkOrderView(View):
    """台账异常明细直接转工单（台账详情"转工单"操作）。

    - 只有结果为"异常"的有效明细可以转工单；作业系统固定为明细所属系统；
    - 工单类型由用户明确选择（默认专项维护；2026-09 类型收敛后新建只允许
      故障维修/专项维护），支持携带维护分类 maintenance_subtype；
    - 带入台账、检查项、位置、异常说明、实测值和现场处理内容；
    - 一次操作不得同时直接创建故障和工单；重复提交不产生重复工单；
    - 已完成直接处置（已转故障/工单）再次转单须填写重新处置原因。
    """

    @auth('equipment_lifecycle.ledger.handle_exception')
    def post(self, request, ledger_pk, item_pk):
        if not _require_perm(request.user, 'equipment_lifecycle.work_order.add'):
            return json_response(error='权限拒绝')
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        err = _validate_affected_systems_rejected(body)
        if err:
            return json_response(error=err)
        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    item, ledger, error = _get_ledger_item_for_convert(
                        ledger_pk, item_pk, request.user, for_update=True)
                    if error:
                        return json_response(error=error)
                    # 幂等：同 client_token 视为同一请求，先于重新处置校验返回已有工单
                    client_token = (body.get('client_token') or '').strip()[:64]
                    existing = work_order_services.find_existing_by_token(
                        request.user.tenant_id, client_token,
                        source_type='ledger_item', source_object=item)
                    if existing:
                        return json_response(existing.to_detail_view())
                    error = _check_item_redispose(
                        item, request.user, body.get('re_dispose_reason'), 'work_order')
                    if error:
                        return json_response(error=error)

                    data, error = _validate_convert_to_order_payload(body, item, ledger)
                    if error:
                        return json_response(error=error)

                    order = work_order_services.create_work_order_record(
                        tenant_id=request.user.tenant_id,
                        created_by=request.user,
                        source_type='ledger_item',
                        source_ledger_item=item,
                        source_no=ledger.ledger_no,
                        client_token=client_token,
                        request=request,
                        **data,
                    )
                    # 步骤 3.4：台账异常处置履历（来源 ledger_item，与转单同一事务）
                    re_dispose_reason = (body.get('re_dispose_reason') or '').strip()[:200]
                    event_services.record_ledger_convert_event(
                        item, ledger, 'convert_to_work_order', target_no=order.work_no,
                        detail={'re_dispose_reason': re_dispose_reason},
                        created_by=request.user)
                    record_audit_event(request, 'create', AUDIT_TARGET_WORK_ORDER,
                                       order.id, order.work_no,
                                       after_value={**_order_audit_summary(order),
                                                    'source_ledger_no': ledger.ledger_no,
                                                    'source_ledger_item_id': item.id,
                                                    're_dispose_reason': re_dispose_reason})
        except fault_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        return json_response(order.to_detail_view())


def _default_convert_title_and_requirement(form, item, ledger):
    """台账转工单的标题与作业要求默认组装（未填写时带入台账上下文）。"""
    title = (form.title or '').strip()
    if not title:
        title = f'{item.item_name_snapshot} 异常处理'[:100]
    work_requirement = (form.work_requirement or '').strip()
    if not work_requirement:
        work_requirement = LedgerItemConvertToFaultView._compose_phenomenon(
            None, item, ledger)
    return title, work_requirement


def _validate_convert_to_order_payload(body, item, ledger):
    """台账异常转工单载荷校验与字段组装（2026-09 类型收敛）。

    返回 (data, error)。data 为 create_work_order_record 的业务字段：
    类型收敛校验（拒绝已下线顶层类型）、维护分类规范化、计划时间解析、
    标题与作业要求默认组装集中在此，post 只编排事务与副作用。
    """
    form, error = JsonParser(
        Argument('title', type=str, required=False, default=''),
        Argument('work_type', type=str, required=False,
                 default=SystemWorkOrder.TYPE_SPECIAL_MAINTENANCE),
        Argument('maintenance_subtype', type=str, required=False, default=None),
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
        return None, error
    # 顶层工单类型收敛：历史类型仅保留展示，转单拒绝再选
    type_error = _validate_work_type_for_create(form.work_type)
    if type_error:
        return None, type_error
    maintenance_subtype, subtype_error = _validate_maintenance_subtype(
        form.work_type, form.maintenance_subtype)
    if subtype_error:
        return None, subtype_error
    if form.priority not in SystemWorkOrder.PRIORITY_TEXT_MAP:
        return None, '优先级不合法'
    if not isinstance(form.affects_system_operation, bool):
        return None, '作业期间是否影响系统运行必须为布尔值'
    if 'target_system' in body and body.get('target_system') not in (None, item.system_id):
        return None, '工单系统固定为明细所属系统，不能指定其他系统'
    planned_start, planned_end, error = _parse_planned_range(form)
    if error:
        return None, error

    title, work_requirement = _default_convert_title_and_requirement(form, item, ledger)

    return ({
        'title': title,
        'work_type': form.work_type,
        'maintenance_subtype': maintenance_subtype,
        'priority': form.priority,
        'system': item.system,
        'affects_system_operation': form.affects_system_operation,
        'work_location': (form.work_location or '').strip(),
        'work_requirement': work_requirement[:2000],
        'work_steps': (form.work_steps or '').strip()[:2000],
        'material_note': (form.material_note or '').strip()[:500],
        'planned_start': planned_start,
        'planned_end': planned_end,
    }, None)


def _work_order_export_row(item):
    """工单导出单行文本（维护分类仅专项维护有业务含义，其他类型留空）。"""
    return [
        item.work_no,
        item.title,
        item.TYPE_TEXT_MAP.get(item.work_type, item.work_type),
        (item.SUBTYPE_TEXT_MAP.get(item.maintenance_subtype, item.maintenance_subtype)
         if item.work_type == SystemWorkOrder.TYPE_SPECIAL_MAINTENANCE else ''),
        item.PRIORITY_TEXT_MAP.get(item.priority, item.priority),
        item.STATUS_TEXT_MAP.get(item.status, item.status),
        item.system_name,
        item.system_code,
        item.work_location,
        item.SOURCE_TEXT_MAP.get(item.source_type, item.source_type),
        item.source_no,
        item.owner.username if item.owner_id else '',
        item.planned_start.strftime('%Y-%m-%d %H:%M') if item.planned_start else '',
        item.planned_end.strftime('%Y-%m-%d %H:%M') if item.planned_end else '',
        item.actual_start.strftime('%Y-%m-%d %H:%M') if item.actual_start else '',
        item.actual_end.strftime('%Y-%m-%d %H:%M') if item.actual_end else '',
        item.process_result,
        item.work_hours if item.work_hours is not None else '',
        item.interrupt_hours if item.interrupt_hours is not None else '',
        item.created_at.strftime('%Y-%m-%d %H:%M') if item.created_at else '',
    ]


class SystemWorkOrdersView(View):
    """按系统查询工单（系统详情"工单"页签，单系统简化）。

    只返回作业系统为当前系统（租户内）的工单，不泄露其他系统的数据，
    不再区分目标/受影响角色。
    """

    @auth('equipment_lifecycle.work_order.view')
    def get(self, request, pk):
        system = _get_system_for_user(pk, request.user)
        if not system:
            return json_response(error='系统不存在')
        query = SystemWorkOrder.objects.filter(
            tenant_id=system.tenant_id, system=system)
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })


class WorkOrderExportView(View):
    @auth('equipment_lifecycle.work_order.export')
    def get(self, request):
        query = SystemWorkOrder.objects.all()
        if not getattr(request.user, 'is_supper', False):
            query = query.filter(tenant_id=request.user.tenant_id)
        status = request.GET.get('status')
        if status and status in SystemWorkOrder.STATUS_TEXT_MAP:
            query = query.filter(status=status)
        work_type = request.GET.get('work_type')
        if work_type and work_type in SystemWorkOrder.TYPE_TEXT_MAP:
            query = query.filter(work_type=work_type)
        headers = ['工单编号', '标题', '工单类型', '维护分类', '优先级', '状态', '作业系统', '系统编号',
                   '作业位置', '来源类型', '来源单据', '负责人', '计划开始', '计划结束',
                   '实际开始', '实际完成', '处理结果', '工时(小时)', '中断时间(小时)', '创建时间']
        rows = [_work_order_export_row(item)
                for item in query.select_related('owner').order_by('-created_at', '-id')]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        writer.writerows(rows)
        response = HttpResponse('\ufeff' + buf.getvalue(), content_type='text/csv; charset=utf-8')
        stamp = timezone.now().strftime('%Y%m%d%H%M%S')
        response['Content-Disposition'] = f'attachment; filename=el_work_orders_{stamp}.csv'
        record_audit_event(request, 'export', AUDIT_TARGET_WORK_ORDER, '', '',
                           after_value={'total': len(rows)})
        return response

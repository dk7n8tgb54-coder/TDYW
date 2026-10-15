# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""设备全生命周期——运行处置记录视图（2026-10-11 合并改造）。

合并原"故障处置"（fault_views）与"运行记录"（runtime_record_views）为统一
模块"运行处置记录"：一张统一主表（SystemOperationRecord）承载
一般记录（routine）/ 异常事件（abnormal）/ 设备故障（fault）三类记录，
一张统一进展表（SystemOperationProgress）承载全部处理进展。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.operation_record.
  view|add|add_fault|edit|progress|complete|identify_fault|recover|close|
  cancel|del|export

设计要点：
- 新建只要求 系统/发生时间/标题/情况描述/登记人；设备故障另有故障专用
  字段（影响系统运行/影响程度/对象快照/原因分析），仅在直接登记故障或
  异常事件认定故障时提交；
- 状态流转只经动作接口（complete/identify-fault/recover/cancel）与追加
  统一进展（首条进展进入跟进中等，见 operation_progress_views），普通编辑
  不允许改状态与记录类型；
- 一般记录：创建后恒为"已记录"，允许补充进展但不进入故障状态机，可删除
  （物理删除 + 审计留痕 + 附件联动软删）；
- 设备故障：创建或认定后进入"处置中"；确认恢复并结案（recover，须同时
  具备 recover 与 close 权限）后为"已关闭"；错误/重复登记可填写原因
  受控撤销（cancel）；
- 只有设备故障且处置中、并明确影响系统运行时才参与系统健康状态计算
  （operation_services 统一重算，健康锁 + 单事务）；
- 创建幂等：client_token 命中同租户已有记录直接返回 + 业务字段窗口期查重；
  编号在 el_operation_record_no 全局锁内生成；
- 已撤销（cancelled）记录退出默认列表/导出/系统页签，显式指定
  status=cancelled 时返回（历史可查、只读）；
- 附件复用 EvidenceAttachment（module=equipment_lifecycle,
  object_type=el_operation_record, object_id=记录ID）；
- 写操作记录业务审计（record_audit_event）。
- 原"系统履历"（SystemEvent）已整体退役：本模块不写任何履历事件。
"""
import json
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from libs.idempotency import check_recent_duplicate
from libs.tenant_utils import apply_tenant_filter
from apps.evidence.attachment_service import AttachmentService
from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle import operation_services
from apps.equipment_lifecycle.operation_models import (
    FAULT_IMPACT_TEXT_MAP,
    RECORD_CATEGORY_TEXT_MAP,
    RECORD_STATUS_CANCELLED,
    RECORD_STATUS_FOLLOWING_UP,
    RECORD_STATUS_HANDLING,
    RECORD_STATUS_TEXT_MAP,
    RECORD_TYPE_ABNORMAL,
    RECORD_TYPE_FAULT,
    RECORD_TYPE_ROUTINE,
    RECORD_TYPE_TEXT_MAP,
    SystemOperationRecord,
)
from apps.equipment_lifecycle.models import LifecycleSystem

AUDIT_TARGET_RECORD = operation_services.AUDIT_TARGET_RECORD

DATETIME_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%dT%H:%M', '%Y-%m-%d')

IDEMPOTENCY_WINDOW_SECONDS = 30

# 记录附件归属标识（复用 EvidenceAttachment 体系，不新建文件存储）
RECORD_ATTACHMENT_MODULE = 'equipment_lifecycle'
RECORD_ATTACHMENT_OBJECT_TYPE = 'el_operation_record'

# 已随合并改造退役的旧参数：出现即拒绝，不静默忽略（旧字段旧接口一律不再支持）
RETIRED_RECORD_PARAMS = (
    # 原故障模块已退役字段与编号
    'affected_systems', 'discovery', 'level', 'fault_location', 'handler_id',
    'fault_no', 'phenomenon', 'fault_component_name',
    # 原运行记录模块已退役字段
    'record_no', 'measures_taken', 'handling_result', 'needs_follow_up',
    'initial_reason', 'impact_scope', 'object_name', 'object_model',
    'importance', 'importance_reason', 'follow_up_name', 'planned_handle_at',
    'triaged_at', 'triaged_by_name', 'triage_note',
    # 原结案/进展已删除参数
    'recover_confirm', 'final_result', 'progress_type', 'result',
)


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


def _parse_dt_end_inclusive(value):
    """解析时间范围"截止"取值并包含所选整分钟，返回用于 __lt 的排他边界。

    用户按分钟粒度选择（YYYY-MM-DD HH:MM / YYYY-MM-DDTHH:MM）时，期望
    截止时间当分钟的记录（XX:XX:00 - XX:XX:59.999）全部包含在结果内：
    边界右移一分钟；显式携带秒的取值保持原样；仅日期（YYYY-MM-DD）按
    当天结束（右移一天）处理，与"包含该日"的直觉一致。解析失败返回 None。
    """
    parsed = _parse_dt(value) if value else None
    if parsed is None:
        return None
    for fmt in DATETIME_FORMATS:
        try:
            datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
        if fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M'):
            return parsed + timedelta(minutes=1)
        if fmt == '%Y-%m-%d':
            return parsed + timedelta(days=1)
        return parsed
    return parsed


def _reject_retired_params(body):
    """请求体包含已退役参数时返回错误消息，否则返回 None。"""
    if isinstance(body, dict):
        present = [name for name in RETIRED_RECORD_PARAMS if name in body]
        if present:
            return '记录已不再支持参数：' + '、'.join(present) + '，请更新后重新提交'
    return None


def _get_record_for_user(pk, user, for_update=False):
    qs = apply_tenant_filter(
        SystemOperationRecord.objects.select_related('system'), user)
    if for_update:
        qs = qs.select_for_update()
    return qs.filter(pk=pk).first()


def _get_active_system_for_user(pk, user):
    """取本租户可用（未停用）系统：新建/变更关联只允许选择可用系统。"""
    return apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(
        pk=pk, is_active=True).first()


def _validate_occurred_at(value):
    """校验发生时间，返回 (occurred_at, error)。"""
    occurred_at = _parse_dt(value)
    if not occurred_at:
        return None, '发生时间格式不正确，应为 YYYY-MM-DD HH:MM'
    if occurred_at > timezone.now():
        return None, '发生时间不能晚于当前时间'
    return occurred_at, None


def _validate_record_type(value):
    """记录类型取值校验，返回 (record_type, error)。"""
    if not value:
        return None, '请选择记录类型'
    if value not in RECORD_TYPE_TEXT_MAP:
        return None, '记录类型取值不合法'
    return value, None


def _validate_category_value(category):
    """异常类别取值校验，返回错误消息或 None（空串=未选择，合法）。"""
    if category and category not in RECORD_CATEGORY_TEXT_MAP:
        return '异常类别取值不合法'
    return None


def _validate_affects_and_impact(form, fallback_affects=False, fallback_impact=''):
    """校验"影响系统运行"开关与影响程度，返回 (affects, impact_status, error)。

    默认"部件故障但不影响系统运行"：affects=False 时影响程度强制存空串；
    编辑场景开关未显式提交时（fallback 传入原值）保持原影响设置不变。
    """
    if form.affects_system_operation is None:
        return bool(fallback_affects), fallback_impact or '', None
    affects = bool(form.affects_system_operation)
    impact_status = (form.impact_status or '').strip()
    if affects:
        if impact_status not in FAULT_IMPACT_TEXT_MAP:
            return False, '', '影响系统运行时必须选择影响程度（降级/故障/中断）'
    else:
        impact_status = ''
    return affects, impact_status, None


def _validate_registrar_name(form):
    """登记人手动输入必填（不默认当前登录用户），返回清洗后的姓名或错误。"""
    registrar_name = (form.registrar_name or '').strip()
    if not registrar_name:
        return None, '登记人不能为空'
    return registrar_name, None


def _apply_occurred_range(query, form):
    """解析并应用发生时间范围筛选（__gte/__lt），返回 (query, error)。

    截止时间按用户所选整分钟包含该分钟记录（_parse_dt_end_inclusive）。
    """
    occurred_from = _parse_dt(form.occurred_from) if form.occurred_from else None
    occurred_to = _parse_dt_end_inclusive(form.occurred_to) if form.occurred_to else None
    if form.occurred_from and not occurred_from:
        return query, '发生时间起始格式不正确'
    if form.occurred_to and not occurred_to:
        return query, '发生时间截止格式不正确'
    if occurred_from:
        query = query.filter(occurred_at__gte=occurred_from)
    if occurred_to:
        query = query.filter(occurred_at__lt=occurred_to)
    return query, None


def _filter_records(query, form):
    """列表筛选（类型/状态/系统/类别/关键词 + 时间范围），返回 (query, error)。"""
    if form.record_type:
        if form.record_type not in RECORD_TYPE_TEXT_MAP:
            return None, '记录类型筛选值不合法'
        query = query.filter(record_type=form.record_type)
    if form.status:
        if form.status not in RECORD_STATUS_TEXT_MAP:
            return None, '记录状态筛选值不合法'
        query = query.filter(status=form.status)
    else:
        # 默认排除已撤销（登记不再有效的记录退出日常主列表，显式筛选才返回）
        query = query.exclude(status=RECORD_STATUS_CANCELLED)
    if form.system:
        query = query.filter(system_id=form.system)
    if form.category:
        if form.category not in RECORD_CATEGORY_TEXT_MAP:
            return None, '异常类别筛选值不合法'
        query = query.filter(category=form.category)
    if form.keyword:
        query = query.filter(
            Q(record_no__icontains=form.keyword) | Q(title__icontains=form.keyword) |
            Q(description__icontains=form.keyword) | Q(system_name__icontains=form.keyword))
    return _apply_occurred_range(query, form)


def _record_audit_summary(record):
    return {
        'record_no': record.record_no,
        'record_type': record.record_type,
        'status': record.status,
        'system': record.system_name,
        'affects_system_operation': record.affects_system_operation,
        'impact_status': record.impact_status,
        'registrar_name': record.registrar_name,
    }


def _record_detail_response(record):
    """详情响应统一出口：详情字段 + 统一进展概览（后端统计口径）。

    duration_seconds 随详情返回（2026-10-14 起"持续时间"由列表展示移至
    详情展示）：口径与列表行一致 = 最新进展时间 - 发生时间，无进展或
    差值为负时为 None（前端显示"-"）。
    """
    data = record.to_detail_view()
    overview = operation_services.progress_overview(record)
    overview['duration_seconds'] = operation_services.duration_seconds(
        record.occurred_at, overview.get('latest_progress_at'))
    data.update(overview)
    return json_response(data)


def _record_list_rows(records, overview_map):
    """列表行序列化统一出口：主表摘要 + 进展概览 + 持续时间（计算展示字段）。

    latest_progress_at 为全部进展处理时间的最大值（progress_overview_map
    单次聚合，非创建时间/ID 口径）；duration_seconds = 最新进展时间 -
    发生时间（operation_services.duration_seconds），无进展或为负时为
    None（前端显示"-"）。不新增数据库字段。
    """
    rows = []
    for r in records:
        overview = dict(overview_map.get(r.id, {}))
        overview['duration_seconds'] = operation_services.duration_seconds(
            r.occurred_at, overview.get('latest_progress_at'))
        rows.append({**r.to_view(), **overview})
    return rows


def _validate_create_category(record_type, category):
    """创建时异常类别校验：设备故障不支持填写（强制空串），其余类型值域校验。"""
    if record_type == RECORD_TYPE_FAULT:
        if category:
            return None, '设备故障不支持填写异常类别'
        return '', None
    category, err = category, _validate_category_value(category)
    return (None, err) if err else (category, None)


def _validate_create_payload(request, form):
    """创建载荷统一校验，返回 (error, params)。

    权限边界：直接登记设备故障须单独授权（后端独立校验，不依赖前端隐藏）；
    设备故障不支持异常类别；不影响系统运行时影响程度强制空串。
    """
    record_type, err = _validate_record_type(form.record_type)
    if err:
        return err, None
    if record_type == RECORD_TYPE_FAULT and not request.user.has_perms(
            ['equipment_lifecycle.operation_record.add_fault']):
        return '权限拒绝', None
    system = _get_active_system_for_user(form.system, request.user)
    if not system:
        return '所属系统不存在、已停用或无权限', None
    occurred_at, err = _validate_occurred_at(form.occurred_at)
    if err:
        return err, None
    title = (form.title or '').strip()
    if not title:
        return '标题不能为空', None
    description = (form.description or '').strip()
    if not description:
        return '情况描述不能为空', None
    registrar_name, err = _validate_registrar_name(form)
    if err:
        return err, None
    category, err = _validate_create_category(record_type, (form.category or '').strip())
    if err:
        return err, None
    affects, impact_status, err = _validate_affects_and_impact(form)
    if err:
        return err, None
    return None, {
        'record_type': record_type,
        'system': system,
        'occurred_at': occurred_at,
        'title': title,
        'description': description,
        'registrar_name': registrar_name,
        'category': category,
        'affects': affects,
        'impact_status': impact_status,
        'client_token': (form.client_token or '').strip()[:64],
    }


class RecordView(View):
    """统一记录列表 / 新增。"""

    CREATE_FORM_ARGS = (
        Argument('record_type', type=str, required=True, help='记录类型'),
        Argument('system', type=int, required=True, help='所属系统ID'),
        Argument('occurred_at', type=str, required=True, help='发生时间'),
        Argument('title', type=str, required=True, help='标题'),
        Argument('description', type=str, required=True, help='情况描述'),
        Argument('registrar_name', type=str, required=False, default='',
                 help='登记人姓名（手动输入必填，多人以顿号分隔）'),
        Argument('category', type=str, required=False, default='',
                 help='异常类别（一般记录/异常事件选填）'),
        Argument('affects_system_operation', type=bool, required=False, default=False,
                 help='是否影响系统运行（仅设备故障）'),
        Argument('impact_status', type=str, required=False, default='',
                 help='系统影响程度（仅设备故障）'),
        Argument('fault_object_name', type=str, required=False, default=''),
        Argument('fault_object_model', type=str, required=False, default=''),
        Argument('fault_object_sn', type=str, required=False, default=''),
        Argument('reason_analysis', type=str, required=False, default=''),
        Argument('client_token', type=str, required=False, default=''),
    )

    @auth('equipment_lifecycle.operation_record.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('system', type=int, required=False),
            Argument('status', type=str, required=False),
            Argument('category', type=str, required=False),
            Argument('record_type', type=str, required=False),
            Argument('keyword', type=str, required=False),
            Argument('occurred_from', type=str, required=False),
            Argument('occurred_to', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        query, error = _filter_records(
            apply_tenant_filter(
                SystemOperationRecord.objects.select_related('created_by'), request.user),
            form)
        if error:
            return json_response(error=error)
        from libs.pagination import paginate
        page, page_size = paginate(request)
        total = query.count()
        records = list(query[(page - 1) * page_size: page * page_size])
        # 进展概览后端聚合（单次 IN 查询，随本页记录合并返回，附持续时间）
        overview_map = operation_services.progress_overview_map([r.id for r in records])
        return json_response({
            'data': _record_list_rows(records, overview_map),
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.operation_record.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        error = _reject_retired_params(body)
        if error:
            return json_response(error=error)
        form, error = JsonParser(*self.CREATE_FORM_ARGS).parse(body)
        if error:
            return json_response(error=error)
        error, params = _validate_create_payload(request, form)
        if error:
            return json_response(error=error)

        try:
            with operation_services.record_no_lock():
                with transaction.atomic():
                    if params['record_type'] == RECORD_TYPE_FAULT:
                        # 故障创建涉及健康重算：叠加健康锁（锁序：编号锁 → 健康锁）
                        with operation_services.health_recalc_lock():
                            record, dup_error = self._create_locked(request, form, **params)
                    else:
                        record, dup_error = self._create_locked(request, form, **params)
        except (operation_services.RecordLockTimeout,
                operation_services.RecordNoExhausted,
                operation_services.HealthRecalcLockTimeout) as exc:
            return json_response(error=str(exc))
        if dup_error:
            return json_response(error=dup_error)
        return _record_detail_response(record)

    @staticmethod
    def _create_locked(request, form, record_type, system, occurred_at, title,
                       description, registrar_name, category, affects,
                       impact_status, client_token):
        """锁内创建：幂等令牌 + 窗口期查重 + 统一创建服务 + 审计。

        返回 (record, error)：幂等令牌命中返回已有记录；窗口期查重命中返回
        (None, 错误消息)。
        """
        if client_token:
            exists = apply_tenant_filter(
                SystemOperationRecord.objects.all(), request.user
            ).filter(client_token=client_token).first()
            if exists:
                return exists, None
        dup_fields = {
            'tenant_id': request.user.tenant_id,
            'system_id': system.id,
            'occurred_at': occurred_at,
        }
        if record_type == RECORD_TYPE_FAULT:
            dup_fields['description'] = description.strip()
        else:
            dup_fields['title'] = title.strip()
        if check_recent_duplicate(
                SystemOperationRecord, dup_fields,
                window_seconds=IDEMPOTENCY_WINDOW_SECONDS):
            return None, '请勿重复提交相同记录'
        record = operation_services.create_operation_record(
            tenant_id=request.user.tenant_id,
            created_by=request.user,
            system=system,
            record_type=record_type,
            occurred_at=occurred_at,
            title=title,
            description=description,
            registrar_name=registrar_name,
            client_token=client_token,
            category=category,
            affects_system_operation=affects,
            impact_status=impact_status,
            fault_object_name=form.fault_object_name or '',
            fault_object_model=form.fault_object_model or '',
            fault_object_sn=form.fault_object_sn or '',
            reason_analysis=form.reason_analysis or '',
            request=request,
        )
        record_audit_event(request, 'create', AUDIT_TARGET_RECORD, record.id,
                           record.record_no, after_value=_record_audit_summary(record))
        return record, None


class RecordDetailView(View):
    """统一记录详情 / 编辑 / 删除（仅一般记录）。"""

    @auth('equipment_lifecycle.operation_record.view')
    def get(self, request, pk):
        record = _get_record_for_user(pk, request.user)
        if not record:
            return json_response(error='记录不存在')
        return _record_detail_response(record)

    @auth('equipment_lifecycle.operation_record.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        error = _reject_retired_params(body)
        if error:
            return json_response(error=error)
        form, error = JsonParser(
            Argument('system', type=int, required=True, help='所属系统ID'),
            Argument('occurred_at', type=str, required=True, help='发生时间'),
            Argument('title', type=str, required=True, help='标题'),
            Argument('description', type=str, required=True, help='情况描述'),
            Argument('category', type=str, required=False, default=None,
                     help='异常类别；未提交时保留原值'),
            Argument('affects_system_operation', type=bool, required=False, default=None,
                     help='是否影响系统运行（仅设备故障）；未提交时保留原值'),
            Argument('impact_status', type=str, required=False, default='',
                     help='系统影响程度（仅设备故障）'),
            Argument('fault_object_name', type=str, required=False, default=None),
            Argument('fault_object_model', type=str, required=False, default=None),
            Argument('fault_object_sn', type=str, required=False, default=None),
            Argument('reason_analysis', type=str, required=False, default=None),
        ).parse(body)
        if error:
            return json_response(error=error)
        if form.category is not None:
            err = _validate_category_value((form.category or '').strip())
            if err:
                return json_response(error=err)
        try:
            with operation_services.health_recalc_lock():
                with transaction.atomic():
                    response = self._edit_locked(request, pk, form, body)
        except operation_services.HealthRecalcLockTimeout as exc:
            return json_response(error=str(exc))
        return response

    def _edit_locked(self, request, pk, form, body):
        """锁内编辑：按记录类型校验与写库；故障编辑同事务重算健康状态。"""
        record = _get_record_for_user(pk, request.user, for_update=True)
        if not record:
            return json_response(error='记录不存在')
        if record.status not in record.editable_statuses:
            return json_response(error='当前状态的记录不能编辑')
        # 记录类型创建后不可修改（认定故障走专用动作接口）
        if 'record_type' in body:
            return json_response(error='记录类型创建后不可修改')
        system, occurred_at, title, description, err = _validate_edit_fields(
            request, form, record)
        if err:
            return json_response(error=err)
        affects = impact_status = None
        if record.is_fault:
            affects, impact_status, err = _validate_affects_and_impact(
                form, fallback_affects=record.affects_system_operation,
                fallback_impact=record.impact_status)
            if err:
                return json_response(error=err)

        before_summary = _record_audit_summary(record)
        _apply_edit_fields(request, record, form, system, occurred_at,
                           title, description, affects, impact_status)
        record_audit_event(request, 'update', AUDIT_TARGET_RECORD, record.id,
                           record.record_no, before_value=before_summary,
                           after_value=_record_audit_summary(record))
        record.refresh_from_db()
        return _record_detail_response(record)

    @auth('equipment_lifecycle.operation_record.del')
    def delete(self, request, pk):
        """删除记录：仅一般记录可删除（异常事件处置留痕，设备故障走撤销）。

        物理删除 + 审计留痕；附件走 AttachmentService.soft_delete_by_object
        软删留痕，物理文件在事务提交后异步清理。
        """
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='记录不存在')
            if record.record_type != RECORD_TYPE_ROUTINE:
                return json_response(error='仅一般记录支持删除')
            before_summary = _record_audit_summary(record)
            # Model.delete() 后实例 pk 被清空：审计与附件归属用的记录 ID 先取
            record_id = record.id
            AttachmentService.soft_delete_by_object(
                request.user, RECORD_ATTACHMENT_MODULE, RECORD_ATTACHMENT_OBJECT_TYPE,
                record_id, reason='运行处置记录删除联动清理', delete_file=True)
            record.delete()
            record_audit_event(request, 'delete', AUDIT_TARGET_RECORD,
                               record_id, before_summary.get('record_no'),
                               before_value=before_summary)
        return json_response({'id': int(pk)})


def _validate_edit_fields(request, form, record):
    """编辑载荷校验，返回 (system, occurred_at, title, description, error)。"""
    system = _get_active_system_for_user(form.system, request.user)
    if not system:
        if record.system_id == form.system:
            # 未变更的关联系统即使是停用系统也保持原关联（历史记录可继续查询）
            system = record.system
        else:
            return None, None, None, None, '所属系统不存在、已停用或无权限'
    occurred_at, err = _validate_occurred_at(form.occurred_at)
    if err:
        return None, None, None, None, err
    title = (form.title or '').strip()
    if not title:
        return None, None, None, None, '标题不能为空'
    description = (form.description or '').strip()
    if not description:
        return None, None, None, None, '情况描述不能为空'
    return system, occurred_at, title, description, None


def _apply_edit_fields(request, record, form, system, occurred_at, title,
                       description, affects, impact_status):
    """写库：公共字段 + 按记录类型追加故障/异常字段（影响设置已在上游校验）；
    故障编辑同事务重算相关系统（修改前与修改后）健康状态。"""
    # 旧系统 ID 先取：record.system 即将被改写，重算集合须含修改前系统
    old_system_id = record.system_id
    record.system = system
    record.system_code = system.system_code
    record.system_name = system.name
    record.system_location = system.install_location
    record.occurred_at = occurred_at
    record.title = title[:200]
    record.description = description[:2000]
    if record.is_fault:
        record.affects_system_operation = affects
        record.impact_status = impact_status
        if form.fault_object_name is not None:
            record.fault_object_name = form.fault_object_name.strip()[:100]
        if form.fault_object_model is not None:
            record.fault_object_model = form.fault_object_model.strip()[:100]
        if form.fault_object_sn is not None:
            record.fault_object_sn = form.fault_object_sn.strip()[:100]
        if form.reason_analysis is not None:
            record.reason_analysis = form.reason_analysis.strip()[:2000]
    else:
        if form.category is not None:
            record.category = (form.category or '').strip()[:20]
    record.updated_at = timezone.now()
    record.updated_by = request.user
    record.save()
    if record.is_fault:
        # 修改前后的系统都需要重算（影响可能消失或新增）
        operation_services.recompute_systems_health(
            record.tenant_id, {old_system_id, system.id}, request=request,
            audit_reason='编辑故障 ' + record.record_no)


class RecordCandidateSystemsView(View):
    """记录表单系统候选项：本租户可用系统（请求只提交系统 ID）。"""

    @auth('equipment_lifecycle.operation_record.view')
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


class SystemRecordListView(View):
    """按系统查询统一记录（系统档案详情页签）。

    支持记录类型/状态/异常类别/关键词/时间范围筛选；
    默认排除已撤销记录，显式指定 status 时按指定状态返回。
    """

    @auth('equipment_lifecycle.operation_record.view')
    def get(self, request, pk):
        system = apply_tenant_filter(LifecycleSystem.objects.all(), request.user).filter(
            pk=pk).first()
        if not system:
            return json_response(error='系统不存在')
        form, error = JsonParser(
            Argument('system', type=int, required=False),
            Argument('status', type=str, required=False),
            Argument('category', type=str, required=False),
            Argument('record_type', type=str, required=False),
            Argument('keyword', type=str, required=False),
            Argument('occurred_from', type=str, required=False),
            Argument('occurred_to', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        query, error = _filter_records(
            apply_tenant_filter(
                SystemOperationRecord.objects.select_related('created_by'), request.user),
            form)
        if error:
            return json_response(error=error)
        query = query.filter(system=system)
        latest_occurred_at = (
            query.order_by('-occurred_at', '-id').values_list('occurred_at', flat=True).first())
        from libs.pagination import paginate
        page, page_size = paginate(request)
        total = query.count()
        records = list(query[(page - 1) * page_size: page * page_size])
        overview_map = operation_services.progress_overview_map([r.id for r in records])
        return json_response({
            'data': _record_list_rows(records, overview_map),
            'total': total, 'page': page, 'page_size': page_size,
            'latest_occurred_at': latest_occurred_at,
        })


class RecordExportView(View):
    """统一记录导出（xlsx）：单工作表，记录基础列纵向合并、进展逐行展平。

    导出范围与列表筛选完全一致：记录类型/状态/系统/异常类别/关键词/
    发生时间范围全部生效（与主列表同一 _filter_records 口径，截止时间
    同样包含所选整分钟）；默认只导出未撤销记录，显式指定 status 时按
    指定状态导出。进展列（处理时间/处理人/处理内容）跟随记录，工作簿
    构建见 operation_services（build_record_export_workbook）。
    """

    @auth('equipment_lifecycle.operation_record.export')
    def get(self, request):
        form, error = JsonParser(
            Argument('system', type=int, required=False),
            Argument('status', type=str, required=False),
            Argument('category', type=str, required=False),
            Argument('record_type', type=str, required=False),
            Argument('keyword', type=str, required=False),
            Argument('occurred_from', type=str, required=False),
            Argument('occurred_to', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        query, error = _filter_records(
            apply_tenant_filter(SystemOperationRecord.objects.all(), request.user),
            form)
        if error:
            return json_response(error=error)
        records = list(query)
        content, progress_rows = operation_services.build_record_export_workbook(
            records)
        response = HttpResponse(
            content, content_type=operation_services.RECORD_EXPORT_CONTENT_TYPE)
        stamp = timezone.now().strftime('%Y%m%d%H%M%S')
        response['Content-Disposition'] = f'attachment; filename=el_records_{stamp}.xlsx'
        record_audit_event(request, 'export', AUDIT_TARGET_RECORD, '', '',
                           after_value={'total': len(records),
                                        'progress_rows': progress_rows})
        return response


# 待办口径：真正需要用户持续处理的两类记录——跟进中的异常事件与
# 处置中的设备故障；完成跟进/认定故障/确认恢复并结案/撤销后自然移出。
TODO_OPEN_STATUSES = (RECORD_STATUS_FOLLOWING_UP, RECORD_STATUS_HANDLING)


class RecordTodoView(View):
    """统一记录待办列表：跟进中异常事件 + 处置中设备故障。

    - 分页返回（page/page_size，单页上限 100），不做静默截断：
      全量可翻页，页外数据通过分页可达；
    - 附带全量分组计数 counts（跟进中异常事件/处置中故障，不随
      record_type 筛选变化），供前端展示分组数量；
    - 按最近更新优先排序（updated_at/created_at/id 降序，MariaDB DESC
      时 NULL 最后，未更新过的记录按创建时间兜底）；
    - record_type 可选筛选（abnormal/fault），前端分组视图复用；
    - 只做条件查询，由前端进入待办页签时触发，不做周期轮询。
    """

    @auth('equipment_lifecycle.operation_record.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('record_type', type=str, required=False, default=''),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        record_type = form.record_type or ''
        if record_type and record_type not in RECORD_TYPE_TEXT_MAP:
            return json_response(error='记录类型筛选值不合法')
        query = apply_tenant_filter(
            SystemOperationRecord.objects.all(), request.user
        ).filter(status__in=TODO_OPEN_STATUSES)
        # 分组计数在整个待办范围上统计（不随 record_type 筛选变化），
        # 前端始终能展示"跟进中异常事件 X 条 / 处置中故障 Y 条"
        counts_map = dict(
            query.values_list('status').annotate(total=Count('id')).order_by())
        counts = {
            'following_up': counts_map.get(RECORD_STATUS_FOLLOWING_UP, 0),
            'handling': counts_map.get(RECORD_STATUS_HANDLING, 0),
        }
        counts['total'] = counts['following_up'] + counts['handling']
        if record_type:
            query = query.filter(record_type=record_type)
        from libs.pagination import paginate
        page, page_size = paginate(request, default_page_size=20, max_page_size=100)
        total = query.count()
        rows = list(query.order_by('-updated_at', '-created_at', '-id')[
            (page - 1) * page_size: page * page_size])
        return json_response({
            'data': [r.to_view() for r in rows],
            'total': total, 'page': page, 'page_size': page_size,
            'counts': counts,
        })


class RecordStatisticsView(View):
    """统一记录只读统计（默认近 30 天，时间范围 __gte/__lt）。

    record_type 口径筛选：未传时统计全部类型；仅使用统一记录数据，
    巡视/维护/配置变更/升级不混入。
    """

    @auth('equipment_lifecycle.operation_record.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('occurred_from', type=str, required=False, default=''),
            Argument('occurred_to', type=str, required=False, default=''),
            Argument('record_type', type=str, required=False, default='',
                     help='记录类型筛选（routine/abnormal/fault；未传统计全部）'),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        record_type = None
        if form.record_type:
            record_type, err = _validate_record_type(form.record_type)
            if err:
                return json_response(error=err)
        now = timezone.now()
        occurred_to = now + timedelta(days=1)
        occurred_from = now - timedelta(days=30)
        if form.occurred_from:
            occurred_from = _parse_dt(form.occurred_from)
            if not occurred_from:
                return json_response(error='发生时间起始格式不正确')
        if form.occurred_to:
            # 与列表筛选同口径：截止时间按所选整分钟包含该分钟记录
            occurred_to = _parse_dt_end_inclusive(form.occurred_to)
            if not occurred_to:
                return json_response(error='发生时间截止格式不正确')
        if occurred_from >= occurred_to:
            return json_response(error='统计开始时间必须早于截止时间')
        stats = operation_services.compute_operation_statistics(
            request.user.tenant_id, occurred_from, occurred_to,
            record_type=record_type)
        stats['occurred_from'] = occurred_from
        stats['occurred_to'] = occurred_to
        stats['record_type'] = record_type
        stats['stale_days'] = operation_services.STALE_OPEN_DAYS
        return json_response(stats)

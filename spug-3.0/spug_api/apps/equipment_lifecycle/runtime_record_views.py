# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""设备全生命周期——运行记录视图（2026-10，第一版）。

定位：异常与运行情况的统一录入入口，用户不必先判断"故障/事件/其他类型"。
巡视与维护、系统升级、配置变更仍由各自模块负责，不进入运行记录。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.runtime_record.view|add|edit|resolve|close|convert_fault|important

设计要点：
- 新建只要求 系统/发生时间/标题/情况描述；其余字段选填或默认值；
- 状态流转只经动作接口（follow-up/resolve/close/convert-to-fault），普通编辑
  不允许改状态；converted_fault/closed 为终态（正式处置以 SystemFault 为准）；
- 创建幂等：client_token 命中同租户已有记录直接返回 + 业务字段窗口期查重；
  编号在 el_runtime_record_no 全局锁内生成（当日序号 max+1，防并发撞号）；
- 转为故障持健康重算锁（fault_services.create_fault_record 同事务重算），
  行锁防同一记录并发重复转换；
- 履历（SystemEvent）只由服务层按规则生成（影响运行/标记重要/转为故障），
  本模块不提供任何手工创建履历的接口；
- 附件复用 EvidenceAttachment（module=equipment_lifecycle,
  object_type=el_runtime_record, object_id=记录ID），访问前先校验父记录
  存在且属于当前租户；
- 写操作记录业务审计（record_audit_event）。

依赖说明：_parse_dt/_read_json_body 自 fault_views 引入（单向依赖，
fault_views 不回引本模块），路由见 urls.py。
"""
import json

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from libs.idempotency import check_recent_duplicate
from libs.tenant_utils import apply_tenant_filter
from apps.evidence.attachment_service import (
    AttachmentService, DefaultAttachmentConfig, ATTACHMENT_DELETE_DENIED_ERROR,
)
from apps.evidence.models import EvidenceAttachment
from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle import event_services, fault_services, runtime_record_services
from apps.equipment_lifecycle.models import (
    EDITABLE_RUNTIME_RECORD_STATUSES,
    RUNTIME_RECORD_STATUS_CLOSED,
    RUNTIME_RECORD_STATUS_CONVERTED_FAULT,
    RUNTIME_RECORD_STATUS_FOLLOWING_UP,
    RUNTIME_RECORD_STATUS_RECORDED,
    RUNTIME_RECORD_STATUS_RESOLVED,
    RUNTIME_RECORD_STATUS_VALUES,
    RUNTIME_CATEGORY_TEXT_MAP,
    LifecycleSystem,
    SystemFault,
    SystemRuntimeRecord,
    SystemRuntimeRecordProgress,
)
from apps.equipment_lifecycle.fault_views import _parse_dt, _read_json_body

AUDIT_TARGET_RUNTIME_RECORD = 'el_runtime_record'
IDEMPOTENCY_WINDOW_SECONDS = 30

# 运行记录附件归属标识（复用 EvidenceAttachment 体系，不新建文件存储）
RUNTIME_ATTACHMENT_MODULE = 'equipment_lifecycle'
RUNTIME_ATTACHMENT_OBJECT_TYPE = 'el_runtime_record'

# GET 查询串布尔筛选值映射（needs_follow_up=yes|no）
BOOL_FILTER_MAP = {'yes': True, 'true': True, 'no': False, 'false': False}


def _get_record_for_user(pk, user, for_update=False):
    qs = apply_tenant_filter(SystemRuntimeRecord.objects.select_related('system'), user)
    if for_update:
        qs = qs.select_for_update()
    return qs.filter(pk=pk).first()


def _get_active_system_for_user(pk, user):
    """取本租户可用（未停用）系统：新建/变更关联只允许选择可用系统。"""
    return apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(
        pk=pk, is_active=True).first()


def _validate_affects_and_impact(affects, impact_status):
    """校验影响开关与影响程度，返回 (affects, impact_status, error)。

    不影响系统运行时影响程度强制存空串；影响运行时必须选择程度。
    """
    affects = bool(affects)
    impact_status = (impact_status or '').strip()
    if affects:
        if impact_status not in SystemRuntimeRecord.IMPACT_TEXT_MAP:
            return False, '', '影响系统运行时必须选择影响程度（降级/故障/中断）'
    else:
        impact_status = ''
    return affects, impact_status, None


def _validate_occurred_at(value):
    """校验发生时间，返回 (occurred_at, error)。"""
    occurred_at = _parse_dt(value)
    if not occurred_at:
        return None, '发生时间格式不正确，应为 YYYY-MM-DD HH:MM'
    if occurred_at > timezone.now():
        return None, '发生时间不能晚于当前时间'
    return occurred_at, None


def _validate_base_fields(form, request, for_update=False, record=None):
    """校验新建/编辑共用字段，返回 (system, occurred_at, title, description,
    affects, impact_status, error)。

    - 所属系统必须为本租户可用系统；编辑未变更系统时保持原关联（历史记录
      可继续查询停用系统）；
    - 标题与情况描述必填；
    - 影响开关/程度在未显式提交时（编辑场景）保留原值。
    """
    system = _get_active_system_for_user(form.system, request.user)
    if not system:
        if for_update and record and record.system_id == form.system:
            system = record.system
        else:
            return None, None, None, None, None, None, '所属系统不存在、已停用或无权限'
    occurred_at, err = _validate_occurred_at(form.occurred_at)
    if err:
        return None, None, None, None, None, None, err
    title = (form.title or '').strip()
    if not title:
        return None, None, None, None, None, None, '标题不能为空'
    description = (form.description or '').strip()
    if not description:
        return None, None, None, None, None, None, '情况描述不能为空'
    affects = record.affects_system_operation if record else False
    impact_status = record.impact_status if record else ''
    if form.affects_system_operation is not None or record is None:
        affects, impact_status, err = _validate_affects_and_impact(
            form.affects_system_operation, form.impact_status)
        if err:
            return None, None, None, None, None, None, err
    return system, occurred_at, title, description, affects, impact_status, None


ENUM_FILTER_DEFS = (
    # (参数名, 合法值集合, 错误消息)
    ('status', SystemRuntimeRecord.STATUS_TEXT_MAP, '运行记录状态筛选值不合法'),
    ('importance', SystemRuntimeRecord.IMPORTANCE_TEXT_MAP, '重要程度筛选值不合法'),
    ('impact', SystemRuntimeRecord.IMPACT_TEXT_MAP, '影响程度筛选值不合法'),
    ('category', RUNTIME_CATEGORY_TEXT_MAP, '异常类别筛选值不合法'),
)


def _filter_runtime_records(query, form):
    """列表筛选（枚举 + 关键词 + 时间范围），返回 (query, error)。

    时间筛选用 __gte/__lt（项目禁用 DateTimeField __date 等查询）。
    """
    for name, valid_map, error_msg in ENUM_FILTER_DEFS:
        value = getattr(form, name)
        if not value:
            continue
        if value not in valid_map:
            return None, error_msg
        if name == 'impact':
            query = query.filter(affects_system_operation=True, impact_status=value)
        else:
            query = query.filter(**{name: value})
    if form.system:
        query = query.filter(system_id=form.system)
    if form.needs_follow_up:
        follow_value = BOOL_FILTER_MAP.get(form.needs_follow_up.strip().lower())
        if follow_value is None:
            return None, '是否需要跟进筛选值不合法'
        query = query.filter(needs_follow_up=follow_value)
    if form.repeated:
        repeated_value = BOOL_FILTER_MAP.get(form.repeated.strip().lower())
        if repeated_value is None:
            return None, '重复发生筛选值不合法'
        query = query.filter(is_repeated=repeated_value)
    if form.keyword:
        query = query.filter(
            Q(record_no__icontains=form.keyword) | Q(title__icontains=form.keyword) |
            Q(description__icontains=form.keyword) | Q(system_name__icontains=form.keyword) |
            Q(object_name__icontains=form.keyword))
    return _filter_occurred_range(query, form)


def _filter_occurred_range(query, form):
    """发生时间范围筛选：__gte 起始 / __lt 截止。"""
    occurred_from = _parse_dt(form.occurred_from) if form.occurred_from else None
    occurred_to = _parse_dt(form.occurred_to) if form.occurred_to else None
    if form.occurred_from and not occurred_from:
        return None, '发生时间起始格式不正确'
    if form.occurred_to and not occurred_to:
        return None, '发生时间截止格式不正确'
    if occurred_from:
        query = query.filter(occurred_at__gte=occurred_from)
    if occurred_to:
        query = query.filter(occurred_at__lt=occurred_to)
    return query, None


def _validate_category_value(category):
    """异常类别取值校验，返回错误消息或 None（空串=未选择，合法）。"""
    if category and category not in RUNTIME_CATEGORY_TEXT_MAP:
        return '异常类别取值不合法'
    return None


def _find_create_duplicate(request, client_token, system, occurred_at, title):
    """创建幂等检查：令牌命中返回 'duplicate:<id>'，窗口期查重返回错误消息，
    可创建返回 None。"""
    if client_token:
        exists = apply_tenant_filter(
            SystemRuntimeRecord.objects.all(), request.user
        ).filter(client_token=client_token).first()
        if exists:
            return f'duplicate:{exists.id}'
    # 窗口期业务查重：同租户/同系统/同发生时间/同标题视为重复
    if check_recent_duplicate(SystemRuntimeRecord, {
        'tenant_id': request.user.tenant_id,
        'system_id': system.id,
        'occurred_at': occurred_at,
        'title': title,
    }, window_seconds=IDEMPOTENCY_WINDOW_SECONDS):
        return '请勿重复提交相同运行记录'
    return None


def _apply_structured_fields(record, form):
    """编辑时写入结构化补充字段（仅在显式提交时覆盖，未提交保留原值）。"""
    if form.object_name is not None:
        record.object_name = form.object_name.strip()[:100]
    if form.object_model is not None:
        record.object_model = form.object_model.strip()[:100]
    if form.category is not None:
        record.category = (form.category or '').strip()[:20]
    if form.initial_reason is not None:
        record.initial_reason = form.initial_reason.strip()[:500]
    if form.impact_scope is not None:
        record.impact_scope = form.impact_scope.strip()[:200]


def _record_audit_summary(record):
    return {
        'record_no': record.record_no,
        'status': record.status,
        'system': record.system_name,
        'affects_system_operation': record.affects_system_operation,
        'impact_status': record.impact_status,
        'importance': record.importance,
    }


class RuntimeRecordView(View):
    """运行记录列表 / 新增。"""

    @auth('equipment_lifecycle.runtime_record.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('system', type=int, required=False),
            Argument('status', type=str, required=False),
            Argument('needs_follow_up', type=str, required=False),
            Argument('importance', type=str, required=False),
            Argument('impact', type=str, required=False),
            Argument('category', type=str, required=False),
            Argument('repeated', type=str, required=False),
            Argument('keyword', type=str, required=False),
            Argument('occurred_from', type=str, required=False),
            Argument('occurred_to', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        query, error = _filter_runtime_records(
            apply_tenant_filter(SystemRuntimeRecord.objects.all(), request.user), form)
        if error:
            return json_response(error=error)
        # 双向重复关联数量（第二版：重复问题在列表即可发现）
        query = query.annotate(
            duplicate_count=Count('duplicate_links', distinct=True)
            + Count('inbound_duplicate_links', distinct=True))

        from libs.pagination import paginate
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.runtime_record.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        form, error = JsonParser(
            Argument('system', type=int, required=True, help='所属系统ID'),
            Argument('occurred_at', type=str, required=True, help='发生时间'),
            Argument('title', type=str, required=True, help='标题'),
            Argument('description', type=str, required=True, help='情况描述'),
            Argument('needs_follow_up', type=bool, required=False, default=False),
            Argument('affects_system_operation', type=bool, required=False, default=False),
            Argument('impact_status', type=str, required=False, default=''),
            Argument('measures_taken', type=str, required=False, default=''),
            Argument('handling_result', type=str, required=False, default=''),
            Argument('importance', type=str, required=False, default='normal',
                     help='重要程度：normal 普通（默认）/ important 重要（须填原因）'),
            Argument('importance_reason', type=str, required=False, default=''),
            Argument('object_name', type=str, required=False, default='',
                     help='具体对象名称（选填）'),
            Argument('object_model', type=str, required=False, default='',
                     help='对象型号或编号（选填）'),
            Argument('category', type=str, required=False, default='',
                     help='异常类别（选填，空串=未选择）'),
            Argument('initial_reason', type=str, required=False, default='',
                     help='初步原因（选填）'),
            Argument('impact_scope', type=str, required=False, default='',
                     help='影响范围（选填）'),
            Argument('client_token', type=str, required=False, default=''),
        ).parse(body)
        if error:
            return json_response(error=error)

        (system, occurred_at, title, description,
         affects, impact_status, err) = _validate_base_fields(form, request)
        if err:
            return json_response(error=err)
        importance = (form.importance or 'normal').strip()
        if importance not in SystemRuntimeRecord.IMPORTANCE_TEXT_MAP:
            return json_response(error='重要程度取值不合法')
        importance_reason = (form.importance_reason or '').strip()
        if importance == SystemRuntimeRecord.IMPORTANCE_IMPORTANT and not importance_reason:
            return json_response(error='标记重要时必须填写原因')
        category = (form.category or '').strip()
        error = _validate_category_value(category)
        if error:
            return json_response(error=error)
        client_token = (form.client_token or '').strip()[:64]

        try:
            with runtime_record_services.runtime_record_no_lock():
                with transaction.atomic():
                    dup = _find_create_duplicate(
                        request, client_token, system, occurred_at, title)
                    if dup:
                        if dup.startswith('duplicate:'):
                            existed = SystemRuntimeRecord.objects.get(
                                pk=int(dup.split(':', 1)[1]))
                            return json_response(existed.to_detail_view())
                        return json_response(error=dup)
                    record = runtime_record_services.create_runtime_record(
                        tenant_id=request.user.tenant_id,
                        created_by=request.user,
                        system=system,
                        occurred_at=occurred_at,
                        title=title,
                        description=description,
                        client_token=client_token,
                        needs_follow_up=form.needs_follow_up,
                        affects_system_operation=affects,
                        impact_status=impact_status,
                        measures_taken=form.measures_taken,
                        handling_result=form.handling_result,
                        importance=importance,
                        importance_reason=importance_reason,
                        object_name=form.object_name,
                        object_model=form.object_model,
                        category=category,
                        initial_reason=form.initial_reason,
                        impact_scope=form.impact_scope,
                        request=request,
                    )
                    record_audit_event(request, 'create', AUDIT_TARGET_RUNTIME_RECORD,
                                       record.id, record.record_no,
                                       after_value=_record_audit_summary(record))
        except (runtime_record_services.RuntimeRecordLockTimeout,
                runtime_record_services.RuntimeRecordNoExhausted) as exc:
            return json_response(error=str(exc))
        return json_response(record.to_detail_view())


class RuntimeRecordDetailView(View):
    """运行记录详情 / 编辑尚未关闭的记录。"""

    @auth('equipment_lifecycle.runtime_record.view')
    def get(self, request, pk):
        record = _get_record_for_user(pk, request.user)
        if not record:
            return json_response(error='运行记录不存在')
        return json_response(record.to_detail_view())

    @auth('equipment_lifecycle.runtime_record.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        form, error = JsonParser(
            Argument('system', type=int, required=True, help='所属系统ID'),
            Argument('occurred_at', type=str, required=True, help='发生时间'),
            Argument('title', type=str, required=True, help='标题'),
            Argument('description', type=str, required=True, help='情况描述'),
            Argument('needs_follow_up', type=bool, required=False, default=None,
                     help='是否需要跟进；未提交时保留原值'),
            Argument('affects_system_operation', type=bool, required=False, default=None,
                     help='是否影响系统运行；未提交时保留原值'),
            Argument('impact_status', type=str, required=False, default=''),
            Argument('measures_taken', type=str, required=False, default=None),
            Argument('handling_result', type=str, required=False, default=None),
            Argument('object_name', type=str, required=False, default=None,
                     help='具体对象名称；未提交时保留原值'),
            Argument('object_model', type=str, required=False, default=None,
                     help='对象型号或编号；未提交时保留原值'),
            Argument('category', type=str, required=False, default=None,
                     help='异常类别；未提交时保留原值'),
            Argument('initial_reason', type=str, required=False, default=None,
                     help='初步原因；未提交时保留原值'),
            Argument('impact_scope', type=str, required=False, default=None,
                     help='影响范围；未提交时保留原值'),
        ).parse(body)
        if error:
            return json_response(error=error)

        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='运行记录不存在')
            if record.status not in EDITABLE_RUNTIME_RECORD_STATUSES:
                return json_response(error='已关闭或已转故障的运行记录不能编辑')
            (system, occurred_at, title, description,
             affects, impact_status, err) = _validate_base_fields(
                form, request, for_update=True, record=record)
            if err:
                return json_response(error=err)
            if form.category is not None:
                error = _validate_category_value((form.category or '').strip())
                if error:
                    return json_response(error=error)

            before_summary = _record_audit_summary(record)
            record.system = system
            record.system_code = system.system_code
            record.system_name = system.name
            record.system_location = system.install_location
            record.occurred_at = occurred_at
            record.title = title[:200]
            record.description = description[:2000]
            if form.needs_follow_up is not None:
                record.needs_follow_up = bool(form.needs_follow_up)
            record.affects_system_operation = affects
            record.impact_status = impact_status
            if form.measures_taken is not None:
                record.measures_taken = form.measures_taken.strip()[:1000]
            if form.handling_result is not None:
                record.handling_result = form.handling_result.strip()[:1000]
            _apply_structured_fields(record, form)
            record.updated_at = timezone.now()
            record.updated_by = request.user
            record.save()
            record_audit_event(request, 'update', AUDIT_TARGET_RUNTIME_RECORD,
                               record.id, record.record_no,
                               before_value=before_summary,
                               after_value=_record_audit_summary(record))
            record.refresh_from_db()
        return json_response(record.to_detail_view())


class RuntimeRecordProgressView(View):
    """运行记录处理进展：按处理时间正序的时间线 / 追加进展。"""

    @auth('equipment_lifecycle.runtime_record.view')
    def get(self, request, pk):
        record = _get_record_for_user(pk, request.user)
        if not record:
            return json_response(error='运行记录不存在')
        query = apply_tenant_filter(
            SystemRuntimeRecordProgress.objects.all(), request.user).filter(record=record)
        from libs.pagination import paginate
        page, page_size = paginate(request, default_page_size=100)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.runtime_record.edit')
    def post(self, request, pk):
        form, error = JsonParser(
            Argument('handled_at', type=str, required=False, default=None,
                     help='处理时间，缺省为当前时间'),
            Argument('content', type=str, required=True, help='处理内容'),
            Argument('result', type=str, required=False, default=''),
            Argument('work_hours', type=float, required=False, default=None,
                     help='本次工时（小时，选填）'),
            Argument('handler_name', type=str, required=False, default=None,
                     help='处理人姓名（手动输入，实际处理的人；缺省当前登录用户显示姓名）'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        handled_at = _parse_dt(form.handled_at) if form.handled_at else timezone.now()
        if not handled_at:
            return json_response(error='处理时间格式不正确，应为 YYYY-MM-DD HH:MM')
        if handled_at > timezone.now():
            return json_response(error='处理时间不能晚于当前时间')
        content = form.content.strip()
        if not content:
            return json_response(error='处理内容不能为空')
        if form.work_hours is not None and form.work_hours < 0:
            return json_response(error='工时不能为负数')
        handler_name = (form.handler_name or '').strip()[:200]
        if not handler_name:
            handler_name = fault_services.user_display_name(request.user)
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='运行记录不存在')
            if record.status not in EDITABLE_RUNTIME_RECORD_STATUSES:
                return json_response(error='已关闭或已转故障的运行记录不能追加处理进展')
            progress = SystemRuntimeRecordProgress.objects.create(
                tenant_id=record.tenant_id,
                record=record,
                handled_at=handled_at,
                handler=request.user,
                handler_name=handler_name,
                content=content[:2000],
                result=(form.result or '').strip()[:200],
                work_hours=form.work_hours,
            )
            record_audit_event(request, 'create', AUDIT_TARGET_RUNTIME_RECORD,
                               record.id, record.record_no,
                               after_value={'action': 'add_progress',
                                            'progress_id': progress.id,
                                            'handler_name': progress.handler_name,
                                            'handled_at': handled_at.isoformat(
                                                sep=' ', timespec='minutes')})
        return json_response(progress.to_view())


class RuntimeRecordProgressDetailView(View):
    """处理进展更正：保存原内容、修改内容和更正原因，不静默覆盖。"""

    @auth('equipment_lifecycle.runtime_record.edit')
    def put(self, request, pk, rid):
        form, error = JsonParser(
            Argument('handled_at', type=str, required=False, default=None),
            Argument('content', type=str, required=True, help='处理内容'),
            Argument('result', type=str, required=False, default=''),
            Argument('work_hours', type=float, required=False, default=None,
                     help='本次工时（小时）；未提交时保留原值'),
            Argument('handler_name', type=str, required=False, default=None,
                     help='处理人姓名（手动输入）；未提交时保留原值'),
            Argument('correction_reason', type=str, required=True, help='更正原因'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        content = form.content.strip()
        if not content:
            return json_response(error='处理内容不能为空')
        correction_reason = form.correction_reason.strip()
        if not correction_reason:
            return json_response(error='更正原因不能为空')
        handled_at = None
        if form.handled_at:
            handled_at = _parse_dt(form.handled_at)
            if not handled_at:
                return json_response(error='处理时间格式不正确，应为 YYYY-MM-DD HH:MM')
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='运行记录不存在')
            if record.status not in EDITABLE_RUNTIME_RECORD_STATUSES:
                return json_response(error='已关闭或已转故障的运行记录不能更正处理进展')
            progress = apply_tenant_filter(
                SystemRuntimeRecordProgress.objects.all(), request.user
            ).filter(pk=rid, record=record).first()
            if not progress:
                return json_response(error='处理进展不存在')
            corrections = progress.get_corrections()
            corrections.append({
                'old': progress.content,
                'new': content[:2000],
                'reason': correction_reason[:500],
                'by': request.user.username,
                'at': timezone.now().isoformat(sep=' ', timespec='minutes'),
            })
            progress.content = content[:2000]
            if form.handler_name is not None:
                handler_name = form.handler_name.strip()[:200]
                if not handler_name:
                    return json_response(error='处理人不能为空')
                progress.handler_name = handler_name
            progress.result = (form.result or '').strip()[:200]
            if form.work_hours is not None:
                if form.work_hours < 0:
                    return json_response(error='工时不能为负数')
                progress.work_hours = form.work_hours
            if handled_at:
                progress.handled_at = handled_at
            progress.corrections = json.dumps(corrections, ensure_ascii=False)
            progress.save()
            record_audit_event(request, 'update', AUDIT_TARGET_RUNTIME_RECORD,
                               record.id, record.record_no,
                               after_value={'action': 'correct_progress',
                                            'progress_id': progress.id,
                                            'reason': correction_reason[:200]})
        return json_response(progress.to_view())


class RuntimeRecordActionBaseView(View):
    """状态动作视图公共流程：行锁 + 状态校验 + 审计。"""

    ERROR_NOT_FOUND = '运行记录不存在'

    def get_record_locked(self, request, pk):
        return _get_record_for_user(pk, request.user, for_update=True)

    def post(self, request, pk):
        with transaction.atomic():
            record = self.get_record_locked(request, pk)
            if not record:
                return json_response(error=self.ERROR_NOT_FOUND)
            before_status = record.status
            error = self.handle_locked(request, record)
            if error:
                return json_response(error=error)
            record_audit_event(request, 'update', AUDIT_TARGET_RUNTIME_RECORD,
                               record.id, record.record_no,
                               before_value={'status': before_status},
                               after_value=_record_audit_summary(record))
            record.refresh_from_db()
        return json_response(record.to_detail_view())

    def handle_locked(self, request, record):
        raise NotImplementedError


class RuntimeRecordFollowUpView(RuntimeRecordActionBaseView):
    """标记需要跟进：recorded/resolved等 → following_up（第二版支持指定跟进人与计划时间）。

    已处于跟进中的记录：未携带任何跟进字段时维持第一版"重复标记"拒绝；
    携带 follow_up_name/planned_handle_at 时仅更新跟进安排（不重复流转状态）。
    """

    @auth('equipment_lifecycle.runtime_record.edit')
    def post(self, request, pk):
        return super().post(request, pk)

    def handle_locked(self, request, record):
        body = _read_json_body(request) or {}
        form, error = JsonParser(
            Argument('follow_up_name', type=str, required=False, default=''),
            Argument('planned_handle_at', type=str, required=False, default=''),
        ).parse(body)
        if error:
            return error
        follow_up_name = (form.follow_up_name or '').strip()
        planned_handle_at = None
        if form.planned_handle_at:
            planned_handle_at = _parse_dt(form.planned_handle_at)
            if not planned_handle_at:
                return '计划处理时间格式不正确，应为 YYYY-MM-DD HH:MM'
        if record.status == RUNTIME_RECORD_STATUS_FOLLOWING_UP:
            if not follow_up_name and not form.planned_handle_at:
                return '运行记录已处于跟进中状态'
        else:
            if not record.can_transition_to(RUNTIME_RECORD_STATUS_FOLLOWING_UP):
                return '当前状态不能标记为需要跟进'
            record.status = RUNTIME_RECORD_STATUS_FOLLOWING_UP
            record.needs_follow_up = True
        if follow_up_name:
            record.follow_up_name = follow_up_name[:100]
        if form.planned_handle_at:
            record.planned_handle_at = planned_handle_at
        record.updated_at = timezone.now()
        record.updated_by = request.user
        record.save(update_fields=['status', 'needs_follow_up', 'follow_up_name',
                                   'planned_handle_at', 'updated_at', 'updated_by'])
        return None


class RuntimeRecordResolveView(RuntimeRecordActionBaseView):
    """标记已处理：recorded/following_up → resolved（可选补填处理结果）。"""

    @auth('equipment_lifecycle.runtime_record.resolve')
    def post(self, request, pk):
        return super().post(request, pk)

    def handle_locked(self, request, record):
        if record.status == RUNTIME_RECORD_STATUS_RESOLVED:
            return '运行记录已处于已处理状态'
        if not record.can_transition_to(RUNTIME_RECORD_STATUS_RESOLVED):
            return '当前状态不能标记为已处理'
        body = _read_json_body(request) or {}
        form, error = JsonParser(
            Argument('handling_result', type=str, required=False, default=''),
            Argument('measures_taken', type=str, required=False, default=''),
        ).parse(body)
        if error:
            return error
        record.status = RUNTIME_RECORD_STATUS_RESOLVED
        record.needs_follow_up = False
        # 首次标记已处理时间（第二版统计平均处理时长用；重新跟进后再次处理不覆盖）
        if record.resolved_at is None:
            record.resolved_at = timezone.now()
        if (form.handling_result or '').strip():
            record.handling_result = form.handling_result.strip()[:1000]
        if (form.measures_taken or '').strip():
            record.measures_taken = form.measures_taken.strip()[:1000]
        record.updated_at = timezone.now()
        record.updated_by = request.user
        record.save(update_fields=['status', 'needs_follow_up', 'resolved_at',
                                   'handling_result',
                                   'measures_taken', 'updated_at', 'updated_by'])
        return None


class RuntimeRecordCloseView(RuntimeRecordActionBaseView):
    """关闭运行记录：recorded/following_up/resolved → closed（终态）。"""

    @auth('equipment_lifecycle.runtime_record.close')
    def post(self, request, pk):
        return super().post(request, pk)

    def handle_locked(self, request, record):
        if record.status == RUNTIME_RECORD_STATUS_CLOSED:
            return '运行记录已关闭，不能重复关闭'
        if record.status == RUNTIME_RECORD_STATUS_CONVERTED_FAULT:
            return '已转故障的运行记录由故障负责后续处理，不能关闭'
        if not record.can_transition_to(RUNTIME_RECORD_STATUS_CLOSED):
            return '当前状态不能关闭'
        body = _read_json_body(request) or {}
        form, error = JsonParser(
            Argument('handling_result', type=str, required=False, default=''),
        ).parse(body)
        if error:
            return error
        record.status = RUNTIME_RECORD_STATUS_CLOSED
        record.needs_follow_up = False
        if (form.handling_result or '').strip():
            record.handling_result = form.handling_result.strip()[:1000]
        record.updated_at = timezone.now()
        record.updated_by = request.user
        record.save(update_fields=['status', 'needs_follow_up', 'handling_result',
                                   'updated_at', 'updated_by'])
        return None


class RuntimeRecordMarkImportantView(View):
    """标记重要（仅普通 → 重要升级时生成履历，须填原因，重复标记拒绝）。"""

    @auth('equipment_lifecycle.runtime_record.important')
    def post(self, request, pk):
        form, error = JsonParser(
            Argument('importance_reason', type=str, required=True, help='重要标记原因'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        importance_reason = form.importance_reason.strip()
        if not importance_reason:
            return json_response(error='标记重要时必须填写原因')
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='运行记录不存在')
            if record.status not in EDITABLE_RUNTIME_RECORD_STATUSES:
                return json_response(error='已关闭或已转故障的运行记录不能标记重要')
            if record.importance == SystemRuntimeRecord.IMPORTANCE_IMPORTANT:
                # 重复标记拒绝：不生成重复履历，也不覆盖首次标记原因
                return json_response(error='该运行记录已标记为重要')
            record.importance = SystemRuntimeRecord.IMPORTANCE_IMPORTANT
            record.importance_reason = importance_reason[:500]
            record.importance_marked_at = timezone.now()
            record.importance_marked_by = request.user
            record.save(update_fields=['importance', 'importance_reason',
                                       'importance_marked_at', 'importance_marked_by'])
            # 履历：只在普通 → 重要升级这一次生成（不伪造历史事件）
            event_services.record_runtime_record_event(
                record, 'mark_important', '运行记录标记重要',
                detail={'importance_reason': record.importance_reason},
                created_by=request.user,
            )
            record_audit_event(request, 'update', AUDIT_TARGET_RUNTIME_RECORD,
                               record.id, record.record_no,
                               before_value={'importance': 'normal'},
                               after_value=_record_audit_summary(record))
            record.refresh_from_db()
        return json_response(record.to_detail_view())


class RuntimeRecordConvertToFaultView(View):
    """运行记录转为正式故障。

    - 双权限：runtime_record.convert_fault + fault.add（生成正式故障单）；
    - 持健康重算锁 + 行锁，转换/状态流转/履历同一事务，防并发重复转换；
    - 已存在未作废故障拒绝；仅存在已作废故障须填重新处置原因；
    - 转换后记录状态为 converted_fault（终态），后续处理以 SystemFault 为准。
    """

    @auth('equipment_lifecycle.runtime_record.convert_fault')
    def post(self, request, pk):
        if not request.user.has_perms(['equipment_lifecycle.fault.add']):
            return json_response(error='权限拒绝')
        body = _read_json_body(request) or {}
        form, error = JsonParser(
            Argument('occurred_at', type=str, required=False, default=''),
            Argument('affects_system_operation', type=bool, required=False, default=None),
            Argument('impact_status', type=str, required=False, default=None),
            Argument('phenomenon', type=str, required=False, default=''),
            Argument('re_dispose_reason', type=str, required=False, default=''),
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
        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    record = _get_record_for_user(pk, request.user, for_update=True)
                    if not record:
                        return json_response(error='运行记录不存在')
                    fault = runtime_record_services.convert_runtime_record_to_fault(
                        record=record,
                        created_by=request.user,
                        request=request,
                        occurred_at=occurred_at,
                        affects_system_operation=form.affects_system_operation,
                        impact_status=form.impact_status,
                        phenomenon=form.phenomenon,
                        re_dispose_reason=form.re_dispose_reason,
                    )
                    record_audit_event(request, 'create', AUDIT_TARGET_RUNTIME_RECORD,
                                       record.id, record.record_no,
                                       after_value={
                                           'action': 'convert_to_fault',
                                           'fault_no': fault.fault_no,
                                           're_dispose_reason': (
                                               form.re_dispose_reason or '').strip()[:200],
                                       })
        except (fault_services.HealthRecalcLockTimeout,
                fault_services.FaultNoExhausted,
                runtime_record_services.RuntimeRecordConvertError) as exc:
            return json_response(error=str(exc))
        fault_data = SystemFault.objects.select_related('system').get(pk=fault.id)
        return json_response(fault_data.to_detail_view())


class SystemRuntimeRecordsView(View):
    """按系统查询运行记录（系统详情"运行记录"页签，第二版支持筛选与重复统计）。

    - 可按标题/对象名称/编号关键词、异常类别与发生时间范围筛选历史运行记录；
    - 每行携带双向重复关联数量（duplicate_count），并返回最近发生时间摘要。
    """

    @auth('equipment_lifecycle.runtime_record.view')
    def get(self, request, pk):
        system = apply_tenant_filter(LifecycleSystem.objects.all(), request.user).filter(
            pk=pk).first()
        if not system:
            return json_response(error='系统不存在')
        form, error = JsonParser(
            Argument('keyword', type=str, required=False),
            Argument('category', type=str, required=False),
            Argument('occurred_from', type=str, required=False),
            Argument('occurred_to', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        query = apply_tenant_filter(SystemRuntimeRecord.objects.all(), request.user).filter(
            system=system)
        if form.category:
            if form.category not in RUNTIME_CATEGORY_TEXT_MAP:
                return json_response(error='异常类别筛选值不合法')
            query = query.filter(category=form.category)
        if form.keyword:
            query = query.filter(
                Q(record_no__icontains=form.keyword) | Q(title__icontains=form.keyword) |
                Q(object_name__icontains=form.keyword))
        query, error = _filter_occurred_range(query, form)
        if error:
            return json_response(error=error)
        query = query.annotate(
            duplicate_count=Count('duplicate_links', distinct=True)
            + Count('inbound_duplicate_links', distinct=True))
        latest_occurred_at = (
            query.order_by('-occurred_at', '-id').values_list('occurred_at', flat=True).first())
        from libs.pagination import paginate
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
            'latest_occurred_at': latest_occurred_at,
        })

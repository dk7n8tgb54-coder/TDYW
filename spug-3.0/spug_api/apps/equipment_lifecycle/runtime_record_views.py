# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""设备全生命周期——运行记录视图（2026-10，第一版）。

定位：异常与运行情况的统一录入入口，用户不必先判断"故障/事件/其他类型"。
巡视与维护、系统升级、配置变更仍由各自模块负责，不进入运行记录。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.runtime_record.view|add|edit|resolve|convert_fault

设计要点：
- 新建只要求 系统/发生时间/标题/情况描述；其余字段选填或默认值；
- 状态流转只经动作接口（resolve/convert-to-fault）与追加处理进展（首条
  跟进记录进入跟进中；已完成追加进展即重新跟进），普通编辑不允许改状态；
  converted_fault 为终态（正式处置以 SystemFault 为准）；
- 第四版（2026-10-05）研判不再是必经步骤，用户可见状态只有 已记录/
  跟进中/已完成/已转故障：新建成功即已记录（可长期保留，不作为待办），
  追加首条处理进展即进入跟进中，resolve 端点即"完成跟进"（following_up
  → completed，可重新跟进），转故障为独立动作（recorded/following_up 均
  可直接转换）；旧研判（triage）/关闭（close）兼容端点已随 2026-10-06
  旧状态归一（迁移 0007）整体删除；
- 具体对象名称/对象型号/影响系统运行（含影响程度）/标记重要字段已删除
  （2026-10-06，迁移 0006），相关入参与"标记重要"端点一并移除；
- 创建幂等：client_token 命中同租户已有记录直接返回 + 业务字段窗口期查重；
  编号在 el_runtime_record_no 全局锁内生成（当日序号 max+1，防并发撞号）；
- 转为故障持健康重算锁（fault_services.create_fault_record 同事务重算），
  行锁防同一记录并发重复转换；
- 履历（SystemEvent）只由服务层按规则生成（转为故障），本模块不提供任何
  手工创建履历的接口；
- 附件复用 EvidenceAttachment（module=equipment_lifecycle,
  object_type=el_runtime_record, object_id=记录ID），访问前先校验父记录
  存在且属于当前租户；
- 写操作记录业务审计（record_audit_event）。

依赖说明：_parse_dt/_read_json_body 自 fault_views 引入（单向依赖，
fault_views 不回引本模块），路由见 urls.py。
"""
import json

from django.db import transaction
from django.db.models import Q
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

from apps.equipment_lifecycle import fault_services, runtime_record_services
from apps.equipment_lifecycle.models import (
    EDITABLE_RUNTIME_RECORD_STATUSES,
    RUNTIME_RECORD_STATUS_COMPLETED,
    RUNTIME_RECORD_STATUS_CONVERTED_FAULT,
    RUNTIME_RECORD_STATUS_FOLLOWING_UP,
    RUNTIME_RECORD_STATUS_RECORDED,
    RUNTIME_RECORD_TYPE_ABNORMAL,
    RUNTIME_RECORD_TYPE_ROUTINE,
    RUNTIME_RECORD_TYPE_TEXT_MAP,
    RUNTIME_CATEGORY_TEXT_MAP,
    LifecycleSystem,
    SystemFault,
    SystemRuntimeRecord,
    SystemRuntimeRecordProgress,
)
# 详情出口复用故障视图的统一响应（详情字段 + 处理进展概览统计）
from apps.equipment_lifecycle.fault_views import (
    _fault_detail_response, _parse_dt, _read_json_body,
)

AUDIT_TARGET_RUNTIME_RECORD = 'el_runtime_record'
IDEMPOTENCY_WINDOW_SECONDS = 30

# 运行记录附件归属标识（复用 EvidenceAttachment 体系，不新建文件存储）
RUNTIME_ATTACHMENT_MODULE = 'equipment_lifecycle'
RUNTIME_ATTACHMENT_OBJECT_TYPE = 'el_runtime_record'

# GET 查询串布尔筛选值映射（needs_follow_up=yes|no）
BOOL_FILTER_MAP = {'yes': True, 'true': True, 'no': False, 'false': False}

# 已删除字段（2026-10-06 迁移 0006：具体对象名称/对象型号编号/影响系统运行/
# 影响程度/重要程度；迁移 0009：跟进人/计划处理时间（跟进计划）与处理进展的
# 处理结果/本次工时；迁移 0010：研判快照字段）。请求体出现任一旧参数即拒绝，
# 不静默忽略。
RETIRED_RUNTIME_RECORD_PARAMS = (
    'affects_system_operation', 'impact_status',
    'object_name', 'object_model',
    'importance', 'importance_reason',
    'follow_up_name', 'planned_handle_at',
    'result', 'work_hours',
    'triaged_at', 'triaged_by_name', 'triage_note',
)


def _reject_retired_params(body):
    """请求体包含已删除字段时返回错误消息，否则返回 None。"""
    if isinstance(body, dict):
        for key in RETIRED_RUNTIME_RECORD_PARAMS:
            if key in body:
                return f'字段 {key} 已删除，请更新请求参数'
    return None


def _get_record_for_user(pk, user, for_update=False):
    qs = apply_tenant_filter(SystemRuntimeRecord.objects.select_related('system'), user)
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


def _validate_base_fields(form, request, for_update=False, record=None):
    """校验新建/编辑共用字段，返回 (system, occurred_at, title, description, error)。

    - 所属系统必须为本租户可用系统；编辑未变更系统时保持原关联（历史记录
      可继续查询停用系统）；
    - 标题与情况描述必填。
    """
    system = _get_active_system_for_user(form.system, request.user)
    if not system:
        if for_update and record and record.system_id == form.system:
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


ENUM_FILTER_DEFS = (
    # (参数名, 合法值集合, 错误消息)
    ('status', SystemRuntimeRecord.STATUS_TEXT_MAP, '运行记录状态筛选值不合法'),
    ('category', RUNTIME_CATEGORY_TEXT_MAP, '异常类别筛选值不合法'),
    ('record_type', RUNTIME_RECORD_TYPE_TEXT_MAP, '记录类型筛选值不合法'),
)


def _filter_runtime_records(query, form):
    """列表筛选（枚举 + 关键词 + 时间范围），返回 (query, error)。

    时间筛选用 __gte/__lt（项目禁用 DateTimeField __date 等查询）。
    状态筛选取值为四状态原值（recorded/following_up/completed/
    converted_fault）；旧状态值不在合法集合内，直接拒绝。
    """
    for name, valid_map, error_msg in ENUM_FILTER_DEFS:
        value = getattr(form, name)
        if not value:
            continue
        if value not in valid_map:
            return None, error_msg
        query = query.filter(**{name: value})
    if form.system:
        query = query.filter(system_id=form.system)
    if form.needs_follow_up:
        follow_value = BOOL_FILTER_MAP.get(form.needs_follow_up.strip().lower())
        if follow_value is None:
            return None, '是否需要跟进筛选值不合法'
        query = query.filter(needs_follow_up=follow_value)
    if form.keyword:
        query = query.filter(
            Q(record_no__icontains=form.keyword) | Q(title__icontains=form.keyword) |
            Q(description__icontains=form.keyword) | Q(system_name__icontains=form.keyword))
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


def _validate_record_type(value):
    """记录类型取值校验，返回 (record_type, error)。

    空串/None 按 abnormal 兼容（旧请求未传 record_type 的历史口径）。
    """
    if not value:
        return RUNTIME_RECORD_TYPE_ABNORMAL, None
    if value not in RUNTIME_RECORD_TYPE_TEXT_MAP:
        return None, '记录类型取值不合法'
    return value, None


def _reject_routine_only_field(record_type, form, name, error):
    """routine 记录携带异常专属字段时拒绝（后端独立校验，不依赖前端隐藏）。"""
    if record_type == RUNTIME_RECORD_TYPE_ROUTINE and form and getattr(form, name, None):
        return error
    return None


def _reject_routine_extra_fields(record_type, form):
    """routine 记录携带异常专属入参（初步原因/影响范围/跟进标记）时校验，
    返回错误消息或 None。"""
    error = _reject_routine_only_field(
        record_type, form, 'initial_reason', '日常运行记录不支持填写初步原因')
    if not error:
        error = _reject_routine_only_field(
            record_type, form, 'impact_scope', '日常运行记录不支持填写影响范围')
    if not error and getattr(form, 'needs_follow_up', None):
        error = '日常运行记录不支持跟进标记'
    return error


def _validate_create_type_fields(form):
    """创建时的记录类型校验，返回 (error, record_type)。"""
    record_type, err = _validate_record_type(form.record_type)
    if err:
        return err, None
    if record_type == RUNTIME_RECORD_TYPE_ROUTINE:
        # 日常运行记录不进入异常流程：异常研判字段与跟进标记一律拒绝
        # （后端独立校验，不依赖前端隐藏；旧请求不传 record_type 不受影响）
        error = _reject_routine_extra_fields(record_type, form)
        if error:
            return error, None
    return None, record_type


def _validate_update_type_fields(record, form):
    """编辑时的记录类型校验，返回错误消息或 None。

    - record_type 创建后不可修改（提交不一致值即拒绝，避免日常记录与
      异常记录的状态语义互相污染）；
    - routine 记录拒绝异常研判字段与跟进标记。
    """
    if form.record_type:
        if form.record_type != record.record_type:
            return '记录类型创建后不可修改'
        err = _validate_record_type(form.record_type)[1]
        if err:
            return err
    if record.record_type == RUNTIME_RECORD_TYPE_ROUTINE:
        error = _reject_routine_extra_fields(record.record_type, form)
        if error:
            return error
    return None


def _validate_and_clean_create_fields(form):
    """新建附加字段校验与清洗（登记人/异常类别）。

    返回 (error, cleaned)；cleaned 含清洗后的 registrar_name/category，
    error 非 None 时为 None。
    登记人手动输入必填（不默认当前登录用户，参照故障登记人口径）。
    """
    registrar_name = (form.registrar_name or '').strip()
    if not registrar_name:
        return '登记人不能为空', None
    category = (form.category or '').strip()
    error = _validate_category_value(category)
    if error:
        return error, None
    return None, {
        'registrar_name': registrar_name,
        'category': category,
    }


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
        'registrar_name': record.registrar_name,
    }


class RuntimeRecordView(View):
    """运行记录列表 / 新增。"""

    @auth('equipment_lifecycle.runtime_record.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('system', type=int, required=False),
            Argument('status', type=str, required=False),
            Argument('needs_follow_up', type=str, required=False),
            Argument('category', type=str, required=False),
            Argument('record_type', type=str, required=False),
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
        error = _reject_retired_params(body)
        if error:
            return json_response(error=error)
        form, error = JsonParser(
            Argument('system', type=int, required=True, help='所属系统ID'),
            Argument('occurred_at', type=str, required=True, help='发生时间'),
            Argument('title', type=str, required=True, help='标题'),
            Argument('description', type=str, required=True, help='情况描述'),
            Argument('registrar_name', type=str, required=False, default='',
                     help='登记人姓名（手动输入必填，多人以顿号分隔；'
                          '实际添加本条运行记录的人，与登录账号独立）'),
            Argument('needs_follow_up', type=bool, required=False, default=False),
            Argument('measures_taken', type=str, required=False, default=''),
            Argument('handling_result', type=str, required=False, default=''),
            Argument('category', type=str, required=False, default='',
                     help='异常类别（选填，空串=未选择）'),
            Argument('initial_reason', type=str, required=False, default='',
                     help='初步原因（选填）'),
            Argument('impact_scope', type=str, required=False, default='',
                     help='影响范围（选填）'),
            Argument('record_type', type=str, required=False, default='',
                     help='记录类型（routine日常运行/abnormal异常事件；'
                          '未传时按abnormal兼容处理）'),
            Argument('client_token', type=str, required=False, default=''),
        ).parse(body)
        if error:
            return json_response(error=error)

        (system, occurred_at, title, description, err) = _validate_base_fields(
            form, request)
        if err:
            return json_response(error=err)
        error, extra = _validate_and_clean_create_fields(form)
        if error:
            return json_response(error=error)
        error, record_type = _validate_create_type_fields(form)
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
                        registrar_name=extra['registrar_name'],
                        client_token=client_token,
                        needs_follow_up=form.needs_follow_up,
                        measures_taken=form.measures_taken,
                        handling_result=form.handling_result,
                        category=extra['category'],
                        initial_reason=form.initial_reason,
                        impact_scope=form.impact_scope,
                        record_type=record_type,
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
        error = _reject_retired_params(body)
        if error:
            return json_response(error=error)
        form, error = JsonParser(
            Argument('system', type=int, required=True, help='所属系统ID'),
            Argument('occurred_at', type=str, required=True, help='发生时间'),
            Argument('title', type=str, required=True, help='标题'),
            Argument('description', type=str, required=True, help='情况描述'),
            Argument('needs_follow_up', type=bool, required=False, default=None,
                     help='是否需要跟进；未提交时保留原值'),
            Argument('measures_taken', type=str, required=False, default=None),
            Argument('handling_result', type=str, required=False, default=None),
            Argument('category', type=str, required=False, default=None,
                     help='异常类别；未提交时保留原值'),
            Argument('initial_reason', type=str, required=False, default=None,
                     help='初步原因；未提交时保留原值'),
            Argument('impact_scope', type=str, required=False, default=None,
                     help='影响范围；未提交时保留原值'),
            Argument('record_type', type=str, required=False, default=None,
                     help='记录类型；创建后不可修改，提交不一致值即拒绝'),
        ).parse(body)
        if error:
            return json_response(error=error)

        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='运行记录不存在')
            if record.status not in EDITABLE_RUNTIME_RECORD_STATUSES:
                return json_response(error='已转故障的运行记录不能编辑')
            (system, occurred_at, title, description, err) = _validate_base_fields(
                form, request, for_update=True, record=record)
            if err:
                return json_response(error=err)
            if form.category is not None:
                error = _validate_category_value((form.category or '').strip())
                if error:
                    return json_response(error=error)
            # 记录类型不可变 + routine 专属字段拒绝
            error = _validate_update_type_fields(record, form)
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

    @auth('equipment_lifecycle.runtime_record.del')
    def delete(self, request, pk):
        """删除运行记录（2026-10-07）：仅日常运行记录可删除。

        - 异常事件记录不提供删除（处置留痕要求，与既有口径一致）；
        - 物理删除 + 审计留痕（业务主表默认删除语义）；附件走
          AttachmentService.soft_delete_by_object 软删留痕，物理文件在
          事务提交后异步清理（失败仅留孤儿文件，不回滚数据库）。
        """
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='运行记录不存在')
            if record.record_type != RUNTIME_RECORD_TYPE_ROUTINE:
                return json_response(error='仅日常运行记录支持删除')
            before_summary = _record_audit_summary(record)
            # Model.delete() 后实例 pk 被清空：审计与附件归属用的记录 ID 先取
            record_id = record.id
            AttachmentService.soft_delete_by_object(
                request.user, RUNTIME_ATTACHMENT_MODULE, RUNTIME_ATTACHMENT_OBJECT_TYPE,
                record_id, reason='运行记录删除联动清理', delete_file=True)
            record.delete()
            record_audit_event(request, 'delete', AUDIT_TARGET_RUNTIME_RECORD,
                               record_id, before_summary.get('record_no'),
                               before_value=before_summary)
        return json_response({'id': int(pk)})


class RuntimeRecordProgressView(View):
    """运行记录处理进展：按处理时间正序的时间线 / 追加进展。

    追加进展即"跟进"动作本身（第四版 2026-10-05，研判不再是必经步骤）：
    已记录的记录保存第一条跟进记录后自动进入跟进中（following_up）；
    已完成（completed）追加进展即重新跟进，重新进入跟进中（2026-10-06
    跟进计划删除后"追加进展"是唯一的跟进/重新跟进入口）；终态（已转故障）
    拒绝追加。
    """

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
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        error = _reject_retired_params(body)
        if error:
            return json_response(error=error)
        form, error = JsonParser(
            Argument('handled_at', type=str, required=False, default=None,
                     help='处理时间，缺省为当前时间'),
            Argument('content', type=str, required=True, help='处理内容'),
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
        handler_name = (form.handler_name or '').strip()[:200]
        if not handler_name:
            handler_name = fault_services.user_display_name(request.user)
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='运行记录不存在')
            if record.record_type == RUNTIME_RECORD_TYPE_ROUTINE:
                # 后端独立校验记录类型：日常运行记录不进入跟进流程
                return json_response(error='日常运行记录不支持追加处理进展')
            if record.status not in EDITABLE_RUNTIME_RECORD_STATUSES:
                return json_response(error='已转故障的运行记录不能追加处理进展')
            progress = SystemRuntimeRecordProgress.objects.create(
                tenant_id=record.tenant_id,
                record=record,
                handled_at=handled_at,
                handler=request.user,
                handler_name=handler_name,
                content=content[:2000],
            )
            # 首条跟进记录即进入跟进中（recorded → following_up）；
            # 已完成追加进展即重新跟进（completed → following_up，可再次完成），
            # 终态已被上方可编辑校验拒绝
            if record.status in (RUNTIME_RECORD_STATUS_RECORDED,
                                 RUNTIME_RECORD_STATUS_COMPLETED):
                record.status = RUNTIME_RECORD_STATUS_FOLLOWING_UP
                record.needs_follow_up = True
                record.updated_at = timezone.now()
                record.updated_by = request.user
                record.save(update_fields=['status', 'needs_follow_up',
                                           'updated_at', 'updated_by'])
            record_audit_event(request, 'create', AUDIT_TARGET_RUNTIME_RECORD,
                               record.id, record.record_no,
                               after_value={'action': 'add_progress',
                                            'progress_id': progress.id,
                                            'handler_name': progress.handler_name,
                                            'handled_at': handled_at.isoformat(
                                                sep=' ', timespec='minutes'),
                                            'record_status': record.status})
        return json_response(progress.to_view())


class RuntimeRecordProgressDetailView(View):
    """处理进展更正：保存原内容、修改内容和更正原因，不静默覆盖。"""

    @auth('equipment_lifecycle.runtime_record.edit')
    def put(self, request, pk, rid):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        error = _reject_retired_params(body)
        if error:
            return json_response(error=error)
        form, error = JsonParser(
            Argument('handled_at', type=str, required=False, default=None),
            Argument('content', type=str, required=True, help='处理内容'),
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
                return json_response(error='已转故障的运行记录不能更正处理进展')
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


class RuntimeRecordResolveView(RuntimeRecordActionBaseView):
    """完成跟进：following_up → completed（已完成，可重新跟进；可选补填处理结果）。

    resolve 端点即"完成跟进"，直接进入已完成，不提供普通关闭动作。
    重新跟进（completed → following_up）不设独立端点：追加处理进展即
    重新跟进（RuntimeRecordProgressView，2026-10-06 跟进计划删除）。
    """

    @auth('equipment_lifecycle.runtime_record.resolve')
    def post(self, request, pk):
        return super().post(request, pk)

    def handle_locked(self, request, record):
        if record.record_type == RUNTIME_RECORD_TYPE_ROUTINE:
            return '日常运行记录不支持完成跟进'
        if record.status == RUNTIME_RECORD_STATUS_COMPLETED:
            return '运行记录已完成，不能重复完成跟进'
        if not record.can_transition_to(RUNTIME_RECORD_STATUS_COMPLETED):
            return '当前状态不能完成跟进（仅跟进中的记录可完成跟进）'
        body = _read_json_body(request) or {}
        form, error = JsonParser(
            Argument('handling_result', type=str, required=False, default=''),
            Argument('measures_taken', type=str, required=False, default=''),
        ).parse(body)
        if error:
            return error
        record.status = RUNTIME_RECORD_STATUS_COMPLETED
        record.needs_follow_up = False
        # 首次完成跟进时间（统计平均处理时长用；重新跟进后再次完成不覆盖）
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


class RuntimeRecordConvertToFaultView(View):
    """运行记录转为正式故障（独立业务动作，第四版 2026-10-05）。

    - 转故障不依赖研判：已记录（recorded）与跟进中（following_up）均可直接
      转换（旧研判弹窗内联转换端点已随 2026-10-06 状态归一整体删除）；
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
        error = _reject_retired_params(body)
        if error:
            return json_response(error=error)
        form, error = JsonParser(
            Argument('occurred_at', type=str, required=False, default=''),
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
                    if record.record_type == RUNTIME_RECORD_TYPE_ROUTINE:
                        # 后端独立校验记录类型：日常运行记录不能转正式故障
                        return json_response(error='日常运行记录不能转为正式故障')
                    fault = runtime_record_services.convert_runtime_record_to_fault(
                        record=record,
                        created_by=request.user,
                        request=request,
                        occurred_at=occurred_at,
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
        return _fault_detail_response(fault_data)


class SystemRuntimeRecordsView(View):
    """按系统查询运行记录（系统详情"运行记录"页签，支持筛选）。

    - 可按标题/编号关键词、异常类别与发生时间范围筛选历史运行记录；
    - 返回最近发生时间摘要。
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
            Argument('record_type', type=str, required=False),
            Argument('occurred_from', type=str, required=False),
            Argument('occurred_to', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        query = apply_tenant_filter(SystemRuntimeRecord.objects.all(), request.user).filter(
            system=system)
        if form.record_type:
            if form.record_type not in RUNTIME_RECORD_TYPE_TEXT_MAP:
                return json_response(error='记录类型筛选值不合法')
            query = query.filter(record_type=form.record_type)
        if form.category:
            if form.category not in RUNTIME_CATEGORY_TEXT_MAP:
                return json_response(error='异常类别筛选值不合法')
            query = query.filter(category=form.category)
        if form.keyword:
            query = query.filter(
                Q(record_no__icontains=form.keyword) | Q(title__icontains=form.keyword))
        query, error = _filter_occurred_range(query, form)
        if error:
            return json_response(error=error)
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

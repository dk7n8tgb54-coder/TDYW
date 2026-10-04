# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""设备全生命周期——运行记录第二版视图（2026-10）：研判、重复问题、待办与统计。

定位：用户先快速记录运行情况（新建成功即"已记录"，可长期保留，不作为待办）；
研判为可选动作，由其决定是否跟进或转正式故障；
不把运行记录扩展为第二套故障处置系统（正式处置以 SystemFault 为准）。

本文件承载第二版新增能力（与第一版 runtime_record_views 单向依赖，
复用其取数/校验/审计助手；fault_views._parse_dt/_read_json_body 沿用第一版引入）：
- 研判（triage）：一次动作写入研判人/时间/说明、影响判定、跟进结论、
  标记重要与转正式故障；转故障与台账/巡检/运行记录转故障共用同一转换服务；
- 标记无需跟进（no-follow-up）：研判结论的快捷动作；
- 重复问题：相似记录查询、双向关联/解除关联、标记重复发生
  （仅建立关联与标记，不合并记录、不自动生成故障或履历）；
- 待办列表：只含跟进中记录（超期/跟进人/计划时间筛选），关闭或转故障自然移出；
- 统计查询：只读，仅使用运行记录数据（巡视/维护/配置变更/升级不混入）。

权限（后端独立校验，前端仅控制展示）：
- equipment_lifecycle.runtime_record.triage：研判 / 标记无需跟进
- equipment_lifecycle.runtime_record.link：相似记录关联 / 取消关联 / 标记重复发生
- view / resolve / close / convert_fault / important 沿用第一版编码

并发与一致性：
- 研判（含内联转故障）与重复标记在行锁 + 事务内执行；研判转故障另持健康重算锁；
- 重复关联依赖 (tenant, record, duplicate) 唯一约束 + 双向存在性校验；
- 所有写动作记录业务审计（record_audit_event），研判动作同样入审计。
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from libs.tenant_utils import apply_tenant_filter
from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle import event_services, fault_services, runtime_record_services
from apps.equipment_lifecycle.models import (
    EDITABLE_RUNTIME_RECORD_STATUSES,
    RUNTIME_RECORD_STATUS_CLOSED,
    RUNTIME_RECORD_STATUS_CONVERTED_FAULT,
    RUNTIME_RECORD_STATUS_FOLLOWING_UP,
    RUNTIME_RECORD_STATUS_NO_FOLLOW_UP,
    RUNTIME_CATEGORY_TEXT_MAP,
    TRIAGEABLE_RUNTIME_RECORD_STATUSES,
    SystemRuntimeRecord,
    SystemRuntimeRecordDuplicateLink,
)
from apps.equipment_lifecycle.fault_views import _parse_dt, _read_json_body
from apps.equipment_lifecycle.runtime_record_views import (
    _get_record_for_user,
    _record_audit_summary,
    _validate_affects_and_impact,
    RuntimeRecordActionBaseView,
)

# 待办列表单次返回上限（跟进中记录量级小，超出说明积压，应先处置再查看）
TODO_LIST_LIMIT = 200
# 相似记录查询单次返回上限
SIMILAR_LIST_LIMIT = 50
# 相似记录默认时间窗口（发生时间前后各 N 天，可按天调整）
SIMILAR_DEFAULT_WINDOW_DAYS = 30
SIMILAR_MAX_WINDOW_DAYS = 365


# 研判转故障与独立"转为故障"端点同一权限要求（生成正式故障单需 fault.add）
TRIAGE_FAULT_ADD_PERM = 'equipment_lifecycle.fault.add'
TRIAGE_IMPORTANT_PERM = 'equipment_lifecycle.runtime_record.important'


def _parse_triage_form(body):
    """解析研判请求体，返回 (form, error)。"""
    return JsonParser(
        Argument('needs_follow_up', type=bool, required=False, default=False,
                 help='研判结论：是否需要跟进'),
        Argument('follow_up_name', type=str, required=False, default='',
                 help='跟进人（研判为跟进中时可指定）'),
        Argument('planned_handle_at', type=str, required=False, default='',
                 help='计划处理时间（研判为跟进中时可指定）'),
        Argument('affects_system_operation', type=bool, required=False, default=None,
                 help='是否影响系统运行；未提交时保留原值'),
        Argument('impact_status', type=str, required=False, default=''),
        Argument('convert_to_fault', type=bool, required=False, default=False,
                 help='研判结论：转为正式故障'),
        Argument('re_dispose_reason', type=str, required=False, default='',
                 help='重新处置原因（关联故障已作废后再次转换时必填）'),
        Argument('mark_important', type=bool, required=False, default=False,
                 help='是否纳入重要运行履历'),
        Argument('importance_reason', type=str, required=False, default=''),
        Argument('triage_note', type=str, required=False, default=''),
        Argument('triaged_by_name', type=str, required=False, default='',
                 help='研判人姓名（缺省当前登录用户显示姓名）'),
        Argument('triaged_at', type=str, required=False, default='',
                 help='研判时间（缺省当前时间，不能晚于当前时间）'),
    ).parse(body)


def _validate_triage_semantics(request, form):
    """研判业务规则校验（结论互斥/必填说明/权限），返回错误消息或 None。"""
    if form.convert_to_fault and form.needs_follow_up:
        return '转为正式故障后由故障单负责后续处置，不能同时标记需要跟进'
    if form.convert_to_fault and not request.user.has_perms([TRIAGE_FAULT_ADD_PERM]):
        return '权限拒绝'
    if form.convert_to_fault and not (form.triage_note or '').strip():
        return '转为正式故障时必须填写研判说明'
    if form.mark_important and not (form.importance_reason or '').strip():
        return '标记重要时必须填写原因'
    # 研判标记重要与独立"标记重要"动作同一权限要求（后端独立校验）
    if form.mark_important and not request.user.has_perms([TRIAGE_IMPORTANT_PERM]):
        return '权限拒绝'
    return None


def _parse_triage_times(form):
    """研判时间/计划处理时间解析，返回 (triaged_at, planned_handle_at, error)。"""
    triaged_at = timezone.now()
    if form.triaged_at:
        triaged_at = _parse_dt(form.triaged_at)
        if not triaged_at:
            return None, None, '研判时间格式不正确，应为 YYYY-MM-DD HH:MM'
        if triaged_at > timezone.now():
            return None, None, '研判时间不能晚于当前时间'
    planned_handle_at = None
    if form.planned_handle_at:
        planned_handle_at = _parse_dt(form.planned_handle_at)
        if not planned_handle_at:
            return None, None, '计划处理时间格式不正确，应为 YYYY-MM-DD HH:MM'
    return triaged_at, planned_handle_at, None


class RuntimeRecordTriageView(View):
    """研判：一次动作完成 影响判定 + 跟进结论 + 重要标记 + 转正式故障。

    - 对 已记录/待研判/无需跟进（重新研判纠正结论）状态开放；结论直接落地为
      目标状态：转正式故障（converted_fault）/ 跟进中（following_up）/
      无需跟进（no_follow_up）；已记录状态禁止直接 resolve/独立转故障绕过
      研判入口（可直接关闭，不要求先研判）；待研判仅历史数据持有；
    - 转正式故障时必须填写研判说明；标记重要必须填写原因（不生成重复履历）；
      普通小问题只需给出"是否需要跟进"，不强制填写复杂字段；
    - 研判把普通记录升级为影响系统运行时补写一次履历（不复写创建期事件）；
    - 内联转故障持健康重算锁 + 行锁，与第一版转换端点同一转换服务与并发约束；
    - 路由以 non_atomic_requests 装配（urls._na）：锁在事务外获取；
    - 研判操作写入审计日志。
    """

    def _parse_triage_request(self, request):
        """解析并校验研判请求：返回元组或错误消息字符串（供 post 分派）。"""
        body = _read_json_body(request)
        if body is None:
            return '请求数据格式不正确'
        form, error = _parse_triage_form(body)
        if error:
            return error
        error = _validate_triage_semantics(request, form)
        if error:
            return error
        triage_note = (form.triage_note or '').strip()
        importance_reason = (form.importance_reason or '').strip()
        times_error = None
        triaged_at, planned_handle_at, times_error = _parse_triage_times(form)
        if times_error:
            return times_error
        affects, impact_status = None, ''
        if form.affects_system_operation is not None:
            affects, impact_status, err = _validate_affects_and_impact(
                form.affects_system_operation, form.impact_status)
            if err:
                return err
        return (form, triage_note, importance_reason, triaged_at,
                planned_handle_at, affects, impact_status)

    @auth('equipment_lifecycle.runtime_record.triage')
    def post(self, request, pk):
        parsed = self._parse_triage_request(request)
        if isinstance(parsed, str):
            return json_response(error=parsed)
        (form, triage_note, importance_reason, triaged_at,
         planned_handle_at, affects, impact_status) = parsed
        if form.convert_to_fault:
            return self._triage_with_convert(
                request, pk, form, triage_note, importance_reason, triaged_at,
                planned_handle_at, affects, impact_status)
        return self._triage_plain(
            request, pk, form, triage_note, importance_reason, triaged_at,
            planned_handle_at, affects, impact_status)

    def _triage_with_convert(self, request, pk, form, triage_note, importance_reason,
                             triaged_at, planned_handle_at, affects, impact_status):
        try:
            with fault_services.health_recalc_lock():
                with transaction.atomic():
                    record = _get_record_for_user(pk, request.user, for_update=True)
                    if not record:
                        return json_response(error='运行记录不存在')
                    before_summary = _record_audit_summary(record)
                    error = self._apply_triage_fields(
                        request.user, record, form, triage_note, importance_reason,
                        triaged_at, planned_handle_at, affects, impact_status,
                        convert=True)
                    if error:
                        return json_response(error=error)
                    fault = runtime_record_services.convert_runtime_record_to_fault(
                        record=record,
                        created_by=request.user,
                        request=request,
                        re_dispose_reason=form.re_dispose_reason,
                    )
                    record_audit_event(
                        request, 'update', 'el_runtime_record', record.id,
                        record.record_no,
                        before_value=before_summary,
                        after_value={
                            **_record_audit_summary(record),
                            'action': 'triage',
                            'convert_to_fault': True,
                            'fault_no': fault.fault_no,
                            'triage_note': triage_note[:200],
                            'mark_important': bool(form.mark_important),
                        })
                    record.refresh_from_db()
        except (fault_services.HealthRecalcLockTimeout,
                fault_services.FaultNoExhausted,
                runtime_record_services.RuntimeRecordConvertError) as exc:
            return json_response(error=str(exc))
        return json_response(record.to_detail_view())

    def _triage_plain(self, request, pk, form, triage_note, importance_reason,
                      triaged_at, planned_handle_at, affects, impact_status):
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='运行记录不存在')
            before_summary = _record_audit_summary(record)
            error = self._apply_triage_fields(
                request.user, record, form, triage_note, importance_reason,
                triaged_at, planned_handle_at, affects, impact_status, convert=False)
            if error:
                return json_response(error=error)
            record_audit_event(
                request, 'update', 'el_runtime_record', record.id, record.record_no,
                before_value=before_summary,
                after_value={
                    **_record_audit_summary(record),
                    'action': 'triage',
                    'triage_note': triage_note[:200],
                    'follow_up_name': record.follow_up_name,
                    'mark_important': bool(form.mark_important),
                })
            record.refresh_from_db()
        return json_response(record.to_detail_view())

    def _apply_triage_fields(self, user, record, form, triage_note, importance_reason,
                             triaged_at, planned_handle_at, affects, impact_status,
                             convert):
        """行锁内写入研判字段与状态流转，返回错误消息或 None。

        转故障时本方法只落研判/重要/影响字段，状态由转换服务流转为 converted_fault。
        """
        if record.status not in TRIAGEABLE_RUNTIME_RECORD_STATUSES:
            return ('当前状态不能进行研判'
                    '（无需跟进的记录可重新研判纠正结论）')
        target = (
            RUNTIME_RECORD_STATUS_CONVERTED_FAULT if convert else
            (RUNTIME_RECORD_STATUS_FOLLOWING_UP if form.needs_follow_up
             else RUNTIME_RECORD_STATUS_NO_FOLLOW_UP))
        if not record.can_transition_to(target):
            return f'当前状态不能研判为「{record.STATUS_TEXT_MAP.get(target, target)}」'
        was_affecting = runtime_record_services.runtime_record_affects_system(record)

        update_fields = ['triaged_at', 'triaged_by', 'triaged_by_name', 'triage_note',
                         'updated_at', 'updated_by']
        record.triaged_at = triaged_at
        record.triaged_by = user
        # 研判人：手动输入优先，缺省取操作账号显示姓名
        record.triaged_by_name = (
            (form.triaged_by_name or '').strip()[:100]
            or fault_services.user_display_name(user))
        record.triage_note = triage_note[:1000]
        record.updated_at = timezone.now()
        record.updated_by = user

        if affects is not None:
            record.affects_system_operation = affects
            record.impact_status = impact_status
            update_fields += ['affects_system_operation', 'impact_status']

        if form.mark_important:
            if record.importance == SystemRuntimeRecord.IMPORTANCE_IMPORTANT:
                return '该运行记录已标记为重要'
            record.importance = SystemRuntimeRecord.IMPORTANCE_IMPORTANT
            record.importance_reason = importance_reason[:500]
            record.importance_marked_at = triaged_at
            record.importance_marked_by = user
            update_fields += ['importance', 'importance_reason',
                              'importance_marked_at', 'importance_marked_by']

        if not convert:
            if form.needs_follow_up:
                record.status = RUNTIME_RECORD_STATUS_FOLLOWING_UP
                record.needs_follow_up = True
                record.follow_up_name = (form.follow_up_name or '').strip()[:100]
                record.planned_handle_at = planned_handle_at
                update_fields += ['status', 'needs_follow_up',
                                  'follow_up_name', 'planned_handle_at']
            else:
                record.status = RUNTIME_RECORD_STATUS_NO_FOLLOW_UP
                record.needs_follow_up = False
                update_fields += ['status', 'needs_follow_up']
        record.save(update_fields=sorted(set(update_fields)))

        # 履历：普通记录升级为影响系统运行时补写一次；标记重要升级时写一次（不重复生成）
        runtime_record_services.maybe_record_triage_affect_event(
            record, was_affecting, created_by=user)
        if form.mark_important:
            event_services.record_runtime_record_event(
                record, 'mark_important', '运行记录标记重要',
                detail={'importance_reason': record.importance_reason,
                        'via': 'triage'},
                created_by=user)
        return None


class RuntimeRecordNoFollowUpView(RuntimeRecordActionBaseView):
    """标记无需跟进：已记录/待研判（历史）→ 无需跟进（研判结论的快捷动作）。"""

    @auth('equipment_lifecycle.runtime_record.triage')
    def post(self, request, pk):
        return super().post(request, pk)

    def handle_locked(self, request, record):
        if record.status == RUNTIME_RECORD_STATUS_NO_FOLLOW_UP:
            return '运行记录已处于无需跟进状态'
        if not record.can_transition_to(RUNTIME_RECORD_STATUS_NO_FOLLOW_UP):
            return '当前状态不能标记为无需跟进'
        record.status = RUNTIME_RECORD_STATUS_NO_FOLLOW_UP
        record.needs_follow_up = False
        record.updated_at = timezone.now()
        record.updated_by = request.user
        record.save(update_fields=['status', 'needs_follow_up', 'updated_at', 'updated_by'])
        return None


class RuntimeRecordSimilarView(View):
    """相似记录查询：同系统、发生时间窗口内、排除已关联，供人工研判关联。"""

    @auth('equipment_lifecycle.runtime_record.view')
    def get(self, request, pk):
        form, error = JsonParser(
            Argument('window_days', type=int, required=False, default=SIMILAR_DEFAULT_WINDOW_DAYS),
            Argument('keyword', type=str, required=False, default=''),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        record = _get_record_for_user(pk, request.user)
        if not record:
            return json_response(error='运行记录不存在')
        window_days = form.window_days or SIMILAR_DEFAULT_WINDOW_DAYS
        window_days = max(1, min(window_days, SIMILAR_MAX_WINDOW_DAYS))
        start = record.occurred_at - timedelta(days=window_days)
        end = record.occurred_at + timedelta(days=window_days)
        query = apply_tenant_filter(SystemRuntimeRecord.objects.all(), request.user).filter(
            system_id=record.system_id, occurred_at__gte=start, occurred_at__lt=end,
        ).exclude(pk=record.pk)
        keyword = (form.keyword or '').strip()
        if keyword:
            query = query.filter(
                Q(title__icontains=keyword) | Q(object_name__icontains=keyword))
        linked_ids = set(record.duplicate_links.values_list('duplicate_id', flat=True)) | set(
            record.inbound_duplicate_links.values_list('record_id', flat=True))
        if linked_ids:
            query = query.exclude(pk__in=linked_ids)
        records = query.order_by('-occurred_at', '-id')[:SIMILAR_LIST_LIMIT]
        return json_response({
            'data': [r.to_view() for r in records],
            'window_days': window_days,
        })


class RuntimeRecordDuplicateLinkView(View):
    """重复问题关联：查看（双向）/ 建立关联。

    - 关联只建立"相似/重复"标记，保留原始记录，不合并、不自动生成故障或履历；
    - 目标记录必须同租户可见；同一对记录不允许重复关联（含反向）；
    - 建立关联写入审计日志。
    """

    @auth('equipment_lifecycle.runtime_record.view')
    def get(self, request, pk):
        record = _get_record_for_user(pk, request.user)
        if not record:
            return json_response(error='运行记录不存在')
        outbound = record.duplicate_links.select_related(
            'duplicate', 'duplicate__created_by', 'created_by')
        inbound = record.inbound_duplicate_links.select_related(
            'record', 'record__created_by', 'created_by')
        rows = [link.to_view(record.id) for link in outbound]
        rows += [link.to_view(record.id) for link in inbound]
        rows.sort(key=lambda item: (item['created_at'] or '', item['id']), reverse=True)
        return json_response({
            'data': rows,
            'outbound_count': len(outbound),
            'inbound_count': len(inbound),
        })

    @auth('equipment_lifecycle.runtime_record.link')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        form, error = JsonParser(
            Argument('duplicate_id', type=int, required=True, help='要关联的运行记录ID'),
            Argument('note', type=str, required=False, default=''),
        ).parse(body)
        if error:
            return json_response(error=error)
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='运行记录不存在')
            duplicate = apply_tenant_filter(
                SystemRuntimeRecord.objects.all(), request.user
            ).filter(pk=form.duplicate_id).first()
            if not duplicate:
                return json_response(error='要关联的运行记录不存在或无权限访问')
            if duplicate.pk == record.pk:
                return json_response(error='不能关联记录自身')
            exists = SystemRuntimeRecordDuplicateLink.objects.filter(
                tenant_id=record.tenant_id,
            ).filter(
                Q(record=record, duplicate=duplicate) |
                Q(record=duplicate, duplicate=record)
            ).exists()
            if exists:
                return json_response(error='两条运行记录已存在关联')
            link = SystemRuntimeRecordDuplicateLink.objects.create(
                tenant_id=record.tenant_id,
                record=record,
                duplicate=duplicate,
                note=(form.note or '').strip()[:200],
                created_by=request.user,
            )
            record_audit_event(
                request, 'create', 'el_runtime_record', record.id, record.record_no,
                after_value={'action': 'link_duplicate',
                             'link_id': link.id,
                             'duplicate_id': duplicate.id,
                             'duplicate_no': duplicate.record_no,
                             'note': (form.note or '').strip()[:100]})
        return json_response(link.to_view(record.id))


class RuntimeRecordDuplicateLinkDetailView(View):
    """取消重复关联：关联两端任一侧均可解除（原始记录不受影响）。"""

    @auth('equipment_lifecycle.runtime_record.link')
    def delete(self, request, pk, lid):
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user)
            if not record:
                return json_response(error='运行记录不存在')
            link = apply_tenant_filter(
                SystemRuntimeRecordDuplicateLink.objects.all(), request.user
            ).filter(pk=lid).filter(
                Q(record=record) | Q(duplicate=record)).first()
            if not link:
                return json_response(error='关联不存在或无权限访问')
            other_id = link.duplicate_id if link.record_id == record.id else link.record_id
            link.delete()
            record_audit_event(
                request, 'delete', 'el_runtime_record', record.id, record.record_no,
                after_value={'action': 'unlink_duplicate',
                             'link_id': lid,
                             'other_record_id': other_id})
        return json_response({})


class RuntimeRecordMarkRepeatedView(View):
    """标记重复发生（幂等，可取消标记）；不自动生成故障或履历。"""

    @auth('equipment_lifecycle.runtime_record.link')
    def post(self, request, pk):
        body = _read_json_body(request) or {}
        form, error = JsonParser(
            Argument('is_repeated', type=bool, required=False, default=True,
                     help='是否重复发生（true 标记 / false 取消标记）'),
        ).parse(body)
        if error:
            return json_response(error=error)
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='运行记录不存在')
            if record.status not in EDITABLE_RUNTIME_RECORD_STATUSES:
                return json_response(error='已关闭或已转故障的运行记录不能修改重复标记')
            before = record.is_repeated
            record.is_repeated = bool(form.is_repeated)
            record.save(update_fields=['is_repeated'])
            record_audit_event(
                request, 'update', 'el_runtime_record', record.id, record.record_no,
                before_value={'is_repeated': before},
                after_value={'action': 'mark_repeated',
                             'is_repeated': record.is_repeated})
            record.refresh_from_db()
        return json_response(record.to_detail_view())


class RuntimeRecordTodoView(View):
    """运行记录待办列表：只含"跟进中"记录，关闭或转故障后自然移出。

    - 不为普通记录发送提醒，也不做周期轮询；本端点只做条件查询，
      由前端进入待办页签时触发（超期 = 计划处理时间早于当前时间）；
    - order=planned（默认）：按计划处理时间升序、未排期在后；order=recent：最近更新优先。
    """

    def _filter_todo_query(self, query, form):
        """待办筛选（超期/跟进人/计划时间范围），返回 (query, error)。"""
        now = timezone.now()
        overdue_only = (form.overdue or '').strip().lower() == 'yes'
        if overdue_only:
            query = query.filter(planned_handle_at__lt=now)
        follow_up_name = (form.follow_up_name or '').strip()
        if follow_up_name:
            query = query.filter(follow_up_name__icontains=follow_up_name)
        planned_from = _parse_dt(form.planned_from) if form.planned_from else None
        planned_to = _parse_dt(form.planned_to) if form.planned_to else None
        if form.planned_from and not planned_from:
            return None, '计划处理时间起始格式不正确'
        if form.planned_to and not planned_to:
            return None, '计划处理时间截止格式不正确'
        if planned_from:
            query = query.filter(planned_handle_at__gte=planned_from)
        if planned_to:
            query = query.filter(planned_handle_at__lt=planned_to)
        return query, None

    @auth('equipment_lifecycle.runtime_record.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('overdue', type=str, required=False, default=''),
            Argument('follow_up_name', type=str, required=False, default=''),
            Argument('planned_from', type=str, required=False, default=''),
            Argument('planned_to', type=str, required=False, default=''),
            Argument('order', type=str, required=False, default='planned'),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        query = apply_tenant_filter(
            SystemRuntimeRecord.objects.all(), request.user
        ).filter(status=RUNTIME_RECORD_STATUS_FOLLOWING_UP)
        query, error = self._filter_todo_query(query, form)
        if error:
            return json_response(error=error)
        now = timezone.now()
        rows = list(query[:TODO_LIST_LIMIT])
        if (form.order or 'planned') == 'recent':
            rows.sort(key=lambda r: (r.updated_at or r.created_at or '', r.id), reverse=True)
        else:
            # 未排期记录排在有计划时间的记录之后（None 组共用同一哨兵值即可）
            rows.sort(key=lambda r: (
                r.planned_handle_at is None, r.planned_handle_at or now, r.id))
        overdue_count = sum(
            1 for r in rows if r.planned_handle_at and r.planned_handle_at < now)
        return json_response({
            'data': [r.to_view() for r in rows],
            'total': len(rows),
            'overdue_count': overdue_count,
            'now': now,
        })


class RuntimeRecordStatisticsView(View):
    """运行记录只读统计（默认近 30 天，时间范围 __gte/__lt）。

    只使用运行记录数据；巡视/维护/配置变更/升级不进入统计。
    """

    @auth('equipment_lifecycle.runtime_record.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('occurred_from', type=str, required=False, default=''),
            Argument('occurred_to', type=str, required=False, default=''),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        now = timezone.now()
        occurred_to = now + timedelta(days=1)
        occurred_from = now - timedelta(days=30)
        if form.occurred_from:
            occurred_from = _parse_dt(form.occurred_from)
            if not occurred_from:
                return json_response(error='发生时间起始格式不正确')
        if form.occurred_to:
            occurred_to = _parse_dt(form.occurred_to)
            if not occurred_to:
                return json_response(error='发生时间截止格式不正确')
        if occurred_from >= occurred_to:
            return json_response(error='统计开始时间必须早于截止时间')
        stats = runtime_record_services.compute_runtime_statistics(
            request.user.tenant_id, occurred_from, occurred_to)
        stats['occurred_from'] = occurred_from
        stats['occurred_to'] = occurred_to
        stats['stale_days'] = runtime_record_services.RUNTIME_RECORD_STALE_DAYS
        return json_response(stats)

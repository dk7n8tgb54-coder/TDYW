# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""设备全生命周期——统一处理进展视图（2026-10-11 合并改造）。

三种记录类型共用的统一进展（SystemOperationProgress）：
- 一般记录：允许补充进展（不改变状态，恒为"已记录"）；
- 异常事件：追加首条进展即进入跟进中（recorded → following_up），
  已完成追加进展即重新跟进（completed → following_up）；
- 设备故障：仅处置中可追加/更正（已关闭/已撤销封闭）；
- 处理人 handler_name 为手动输入姓名（多人顿号分隔，缺省当前登录用户
  显示姓名），handler 外键保留操作账号审计字段；
- 更正不静默覆盖：原内容、修改内容与更正原因追加保存到 corrections；
- 工时选填（小时）；厂家送修/厂家反馈/外委处理等以进展内容记录，
  不设进展分类前置条件；
- 进展级附件已退役（2026-10-13）：材料统一挂主记录级附件
  （object_type=el_operation_record），存量进展附件经迁移 0016 重指。
"""
import json

from django.db import transaction
from django.utils import timezone
from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from libs.tenant_utils import apply_tenant_filter
from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle import operation_services
from apps.equipment_lifecycle.operation_models import SystemOperationProgress
from apps.equipment_lifecycle.operation_views import (
    AUDIT_TARGET_RECORD,
    _get_record_for_user,
    _parse_dt,
    _read_json_body,
)

# 已随字段删除下线的旧参数（原进展的处置类型/处理结果字段）：
# 出现即拒绝，不静默忽略
RETIRED_PROGRESS_PARAMS = ('progress_type', 'result', 'handler_id')


def _reject_retired_progress_params(body):
    if isinstance(body, dict):
        present = [name for name in RETIRED_PROGRESS_PARAMS if name in body]
        if present:
            return '进展已不再支持参数：' + '、'.join(present) + '，请更新后重新提交'
    return None


def _get_progress_for_user(record, rid, user, for_update=False):
    qs = apply_tenant_filter(SystemOperationProgress.objects.all(), user)
    if for_update:
        qs = qs.select_for_update()
    return qs.filter(pk=rid, record=record).first()


def _validate_progress_payload(body, for_correct=False):
    """校验进展新增/更正载荷，返回 (params, error)。

    新增：处理时间缺省当前时间（不得晚于当前时间）、处理内容必填、
    处理人缺省当前登录用户显示姓名、工时选填非负。
    更正：处理时间/处理人未提交保留原值；更正原因必填。
    """
    error = _reject_retired_progress_params(body)
    if error:
        return None, error
    form, error = JsonParser(
        Argument('handled_at', type=str, required=False, default=None,
                 help='处理时间，缺省为当前时间'),
        Argument('content', type=str, required=True, help='处理内容'),
        Argument('handler_name', type=str, required=False, default=None,
                 help='处理人姓名（手动输入，实际处理的人；缺省当前登录用户显示姓名）'),
        Argument('work_hours', type=float, required=False, default=None,
                 help='本次工时（小时，选填）'),
        Argument('correction_reason', type=str, required=False, default='',
                 help='更正原因（更正时必填）'),
    ).parse(body)
    if error:
        return None, error
    content = form.content.strip()
    if not content:
        return None, '处理内容不能为空'
    handler_name = None
    if form.handler_name is not None:
        handler_name = form.handler_name.strip()[:200]
        if not handler_name:
            return None, '处理人不能为空'
    if form.work_hours is not None and form.work_hours < 0:
        return None, '工时不能为负数'
    handled_at = None
    if form.handled_at:
        handled_at = _parse_dt(form.handled_at)
        if not handled_at:
            return None, '处理时间格式不正确，应为 YYYY-MM-DD HH:MM'
        if not for_correct and handled_at > timezone.now():
            return None, '处理时间不能晚于当前时间'
    correction_reason = ''
    if for_correct:
        correction_reason = (form.correction_reason or '').strip()
        if not correction_reason:
            return None, '更正原因不能为空'
    return {
        'form': form,
        'content': content,
        'handler_name': handler_name,
        'handled_at': handled_at,
        'work_hours': form.work_hours,
        'correction_reason': correction_reason,
    }, None


class RecordProgressView(View):
    """统一进展：按处理时间正序的时间线 / 追加进展。

    追加进展即"跟进"动作本身：异常事件已记录保存第一条进展后自动进入
    跟进中，已完成追加进展即重新跟进；一般记录允许补充进展但不改变状态；
    设备故障仅处置中可追加（已关闭/已撤销拒绝）。
    """

    @auth('equipment_lifecycle.operation_record.view')
    def get(self, request, pk):
        record = _get_record_for_user(pk, request.user)
        if not record:
            return json_response(error='记录不存在')
        query = apply_tenant_filter(
            SystemOperationProgress.objects.all(), request.user).filter(record=record)
        from libs.pagination import paginate
        page, page_size = paginate(request, default_page_size=100)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.operation_record.progress')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        params, error = _validate_progress_payload(body, for_correct=False)
        if error:
            return json_response(error=error)
        handled_at = params['handled_at'] or timezone.now()
        handler_name = params['handler_name']
        if not handler_name:
            handler_name = operation_services.user_display_name(request.user)
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='记录不存在')
            if record.status not in record.editable_statuses:
                return json_response(error='当前状态的记录不能追加进展')
            progress = SystemOperationProgress.objects.create(
                tenant_id=record.tenant_id,
                record=record,
                handled_at=handled_at,
                handler=request.user,
                handler_name=handler_name,
                content=params['content'][:2000],
                work_hours=params['work_hours'],
            )
            # 异常事件：首条进展进入跟进中 / 已完成追加进展即重新跟进；
            # 一般记录不改变状态；设备故障处置中状态不变（其余状态已被
            # 上方 editable 校验拒绝）
            if record.record_type == 'abnormal' and record.status in ('recorded', 'completed'):
                record.status = 'following_up'
                record.updated_at = timezone.now()
                record.updated_by = request.user
                record.save(update_fields=['status', 'updated_at', 'updated_by'])
            record_audit_event(request, 'create', AUDIT_TARGET_RECORD,
                               record.id, record.record_no,
                               after_value={'action': 'add_progress',
                                            'progress_id': progress.id,
                                            'handler_name': progress.handler_name,
                                            'handled_at': handled_at.isoformat(
                                                sep=' ', timespec='minutes'),
                                            'record_status': record.status})
        return json_response(progress.to_view())


class RecordProgressDetailView(View):
    """统一进展更正：保存原内容、修改内容和更正原因，不静默覆盖。"""

    @auth('equipment_lifecycle.operation_record.edit')
    def put(self, request, pk, rid):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        params, error = _validate_progress_payload(body, for_correct=True)
        if error:
            return json_response(error=error)
        form = params['form']
        with transaction.atomic():
            record = _get_record_for_user(pk, request.user, for_update=True)
            if not record:
                return json_response(error='记录不存在')
            if record.status not in record.editable_statuses:
                return json_response(error='当前状态的记录不能更正进展')
            progress = _get_progress_for_user(record, rid, request.user, for_update=True)
            if not progress:
                return json_response(error='处理进展不存在')
            corrections = progress.get_corrections()
            corrections.append({
                'old': progress.content,
                'new': params['content'][:2000],
                'reason': params['correction_reason'][:500],
                'by': request.user.username,
                'at': timezone.now().isoformat(sep=' ', timespec='minutes'),
            })
            progress.content = params['content'][:2000]
            if params['handler_name'] is not None:
                progress.handler_name = params['handler_name']
            if form.work_hours is not None:
                progress.work_hours = form.work_hours
            if params['handled_at']:
                progress.handled_at = params['handled_at']
            progress.corrections = json.dumps(corrections, ensure_ascii=False)
            progress.save()
            record_audit_event(request, 'update', AUDIT_TARGET_RECORD,
                               record.id, record.record_no,
                               after_value={'action': 'correct_progress',
                                            'progress_id': progress.id,
                                            'reason': params['correction_reason'][:200]})
        return json_response(progress.to_view())

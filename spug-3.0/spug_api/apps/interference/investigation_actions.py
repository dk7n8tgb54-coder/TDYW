# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""规律调查生命周期动作：结束调查、取消调查。

2026-10-26 三态收敛后，调查生命周期（investigating/ended/cancelled）
只能通过本模块的两个业务动作变更；通用创建/编辑路径一律拒绝携带
status/result/cancel_reason 键（fail-closed）。两个动作均在事务内以
select_for_update 锁行并复核 status=='investigating'，重复提交/并发
只能成功一次，且都记录 update 审计（含变更前后值）。
"""

import json

from django.db import transaction
from django.utils import timezone
from django.views.generic import View

from apps.interference.models import (
    INVESTIGATION_RESULT_CHOICES,
    InterferenceInvestigation,
)
from apps.interference.payloads import parse_optional_datetime
from apps.logs.audit import record_audit_event
from libs import auth, json_response
from libs.tenant_utils import apply_tenant_filter

INVESTIGATION_EDIT_PERMISSION = 'interference.investigation.edit'
INVESTIGATION_STATUS_INVESTIGATING = 'investigating'
INVESTIGATION_STATUS_ENDED = 'ended'
INVESTIGATION_STATUS_CANCELLED = 'cancelled'

# 通用 POST/PUT/PATCH 出现即拒绝的生命周期键与对应提示
LIFECYCLE_FIELD_ERRORS = (
    ('status', '调查状态不能直接修改，请通过结束调查或取消调查操作变更'),
    ('result', '调查结果不能直接填写，请通过结束调查操作提交'),
    ('cancel_reason', '取消原因不能直接填写，请通过取消调查操作提交'),
)


def reject_lifecycle_fields(data):
    """通用创建/编辑路径的生命周期字段守卫，命中返回错误文案，否则 None。"""
    if not isinstance(data, dict):
        return None
    for key, message in LIFECYCLE_FIELD_ERRORS:
        if key in data:
            return message
    return None


def _body(request):
    """解析 JSON 请求体；空请求统一返回空对象。"""
    if not request.body:
        return {}
    try:
        value = json.loads(request.body.decode('utf-8'))
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _load_for_update(user, pk):
    """租户过滤 + 行锁读取调查（必须在事务内调用）。"""
    return apply_tenant_filter(
        InterferenceInvestigation.objects.filter(is_deleted=False), user
    ).select_for_update().filter(pk=pk).first()


class InvestigationFinishView(View):
    """结束调查：提交 result + 非空 conclusion（可选 end_at，缺省当前时间）。"""

    @auth(INVESTIGATION_EDIT_PERMISSION)
    def post(self, request, pk):
        data = _body(request)
        if data is None:
            return json_response(error='请求体必须是 JSON 对象')
        result = data.get('result')
        if not result:
            return json_response(error='请选择调查结果')
        if result not in dict(INVESTIGATION_RESULT_CHOICES):
            return json_response(error='调查结果值无效')
        conclusion = str(data.get('conclusion') or '').strip()
        if not conclusion:
            return json_response(error='请填写调查结论')
        try:
            end_at = parse_optional_datetime(data.get('end_at'), '结束时间')
        except ValueError as exc:
            return json_response(error=str(exc))
        with transaction.atomic():
            investigation = _load_for_update(request.user, pk)
            if not investigation:
                return json_response(error='调查不存在或无权限编辑')
            if investigation.status != INVESTIGATION_STATUS_INVESTIGATING:
                return json_response(error='只有调查中的调查可以结束')
            before = investigation.to_view()
            investigation.status = INVESTIGATION_STATUS_ENDED
            investigation.result = result
            investigation.conclusion = conclusion
            investigation.end_at = end_at or timezone.now()
            investigation.updated_by = request.user
            investigation.updated_at = timezone.now()
            investigation.save(update_fields=[
                'status', 'result', 'conclusion', 'end_at',
                'updated_by', 'updated_at'])
            record_audit_event(
                request, 'update', 'interference_investigation',
                str(investigation.id), investigation.name,
                {'action': 'finish_investigation'},
                before_value=before, after_value=investigation.to_view(),
            )
        return json_response(investigation.to_view())


class InvestigationCancelView(View):
    """取消调查：提交非空 cancel_reason。"""

    @auth(INVESTIGATION_EDIT_PERMISSION)
    def post(self, request, pk):
        data = _body(request)
        if data is None:
            return json_response(error='请求体必须是 JSON 对象')
        cancel_reason = str(data.get('cancel_reason') or '').strip()
        if not cancel_reason:
            return json_response(error='请填写取消原因')
        with transaction.atomic():
            investigation = _load_for_update(request.user, pk)
            if not investigation:
                return json_response(error='调查不存在或无权限编辑')
            if investigation.status != INVESTIGATION_STATUS_INVESTIGATING:
                return json_response(error='只有调查中的调查可以取消')
            before = investigation.to_view()
            investigation.status = INVESTIGATION_STATUS_CANCELLED
            investigation.cancel_reason = cancel_reason
            investigation.updated_by = request.user
            investigation.updated_at = timezone.now()
            investigation.save(update_fields=[
                'status', 'cancel_reason', 'updated_by', 'updated_at'])
            record_audit_event(
                request, 'update', 'interference_investigation',
                str(investigation.id), investigation.name,
                {'action': 'cancel_investigation'},
                before_value=before, after_value=investigation.to_view(),
            )
        return json_response(investigation.to_view())

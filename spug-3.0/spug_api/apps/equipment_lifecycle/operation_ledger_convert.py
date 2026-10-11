# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""维护台账异常明细转统一记录（正式故障）视图（2026-10-11 合并改造）。

原 fault_views.LedgerItemConvertToFaultView 迁入并改目标：转换创建统一主表
正式故障记录（SystemOperationRecord，record_type=fault、处置中），
不再创建独立故障单；来源关系（source_type=ledger_item +
source_ledger_item 正式外键 + source_id 冗余）保持双向可追溯。

规则（与原口径一致）：
- 只有结果为"异常"的明细可以转故障；草稿/退回/作废台账不能转；
- 故障系统固定为明细所属系统；
- 带入台账类型、编号、检查项、异常说明、实测值与现场处理内容组装情况描述；
- 同一异常明细默认只允许生成一条有效目标；目标已撤销后重新处置须填写原因；
- 权限：ledger.handle_exception 且同时具备 operation_record.add_fault；
- 持健康重算锁 + 单事务，转换与来源关系/健康重算处于同一事务。
"""
import json
from datetime import datetime

from django.db import transaction
from django.utils import timezone
from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from libs.tenant_utils import apply_tenant_filter
from apps.logs.audit import record_audit_event

from apps.equipment_lifecycle import operation_services
from apps.equipment_lifecycle.models import (
    ITEM_RESULT_ABNORMAL,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_RETURNED,
    LEDGER_STATUS_VOID,
    LEGACY_LEDGER_TYPE_INSPECTION,
    LEDGER_TYPE_TEXT,
    OperationLedgerItem,
)
from apps.equipment_lifecycle.operation_models import (
    FAULT_IMPACT_TEXT_MAP,
    SOURCE_LEDGER_ITEM,
    SystemOperationRecord,
)
from apps.equipment_lifecycle.operation_views import (
    AUDIT_TARGET_RECORD,
    _parse_dt,
    _record_detail_response,
)

# 台账异常明细可转故障的台账状态（草稿/退回/作废不可转）
CONVERTIBLE_LEDGER_STATUSES = ('submitted', 'reviewed')


def _item_value_text(item):
    """台账明细填写值文本（转入记录的情况描述用）。"""
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
    - 已存在未撤销目标 → 一律拒绝（不能静默重复创建）；
    - 仅存在已撤销目标 → 必须填写重新处置原因；
    - 首次处置 → 直接放行。
    """
    reason = (re_dispose_reason or '').strip()
    existing = SystemOperationRecord.objects.filter(
        tenant_id=user.tenant_id, source_ledger_item=item).order_by('-id')
    active = existing.exclude(status='cancelled').first()
    latest = existing.first()
    if active:
        return f'该异常明细已转故障（{active.record_no}），不能重复转换'
    if latest and not reason:
        return '该异常明细曾转故障（目标已撤销）。如需重新处置请填写重新处置原因'
    return None


def _compose_description(item, ledger):
    """由台账明细组装默认情况描述：台账类型/编号 + 检查项 + 异常说明
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
    """台账异常明细转统一记录（正式故障）（台账详情"转故障"操作）。

    - 只有结果为"异常"的明细可以转故障；草稿/退回/作废台账不能转；
    - 目标为统一主表的正式故障记录（创建即处置中），不再创建第二张单；
    - 必须调用 operation_services.create_operation_record（统一创建服务），
      转换与来源关系保存处于同一事务，同事务重算系统健康状态。
    """

    @auth('equipment_lifecycle.ledger.handle_exception')
    def post(self, request, ledger_pk, item_pk):
        if not request.user.has_perms(
                ['equipment_lifecycle.operation_record.add_fault']):
            return json_response(error='权限拒绝')
        body = {}
        try:
            body = json.loads(request.body.decode('utf-8')) if request.body else {}
            if not isinstance(body, dict):
                body = {}
        except (ValueError, UnicodeDecodeError):
            return json_response(error='请求数据格式不正确')
        try:
            with operation_services.health_recalc_lock():
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

                    record = operation_services.create_operation_record(
                        tenant_id=request.user.tenant_id,
                        created_by=request.user,
                        system=item.system,
                        record_type='fault',
                        title=params['title'],
                        source_type=SOURCE_LEDGER_ITEM,
                        source_ledger_item=item,
                        request=request,
                        **{k: v for k, v in params.items() if k != 'title'},
                    )
                    record_audit_event(request, 'create', AUDIT_TARGET_RECORD,
                                       record.id, record.record_no,
                                       after_value={
                                           'action': 'convert_from_ledger_item',
                                           'ledger_no': ledger.ledger_no,
                                           'ledger_item_id': item.id,
                                           'item_name': item.item_name_snapshot,
                                           'status': record.status,
                                           're_dispose_reason': (
                                               body.get('re_dispose_reason') or '').strip()[:200],
                                       })
        except (operation_services.HealthRecalcLockTimeout,
                operation_services.RecordNoExhausted) as exc:
            return json_response(error=str(exc))
        record = SystemOperationRecord.objects.select_related('system').get(pk=record.id)
        return _record_detail_response(record)


def _resolve_convert_occurred_at(form, item, ledger):
    """解析转故障发生时间：显式提交 > 明细执行时间 > 台账执行日期（零点）。"""
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
    return occurred_at, None


def _validate_convert_impact(form):
    """校验影响系统运行开关与影响程度，返回 (affects, impact_status, error)。"""
    affects = bool(form.affects_system_operation)
    if affects:
        if form.impact_status not in FAULT_IMPACT_TEXT_MAP:
            return False, '', '影响系统运行时必须选择影响程度（降级/故障/中断）'
        return affects, form.impact_status, None
    return affects, '', None


def _resolve_convert_payload(body, item, ledger):
    """解析并校验台账异常转故障载荷，返回 (params, error)。

    params 包含 title/occurred_at/affects_system_operation/impact_status/description。
    """
    # 已随字段删除下线的旧参数（发现方式/级别）：出现即拒绝
    removed = [k for k in ('discovery', 'level') if k in body]
    if removed:
        return None, '记录已不再支持参数：' + '、'.join(removed) + '，请更新后重新提交'
    form, error = JsonParser(
        Argument('occurred_at', type=str, required=False, default=''),
        Argument('affects_system_operation', type=bool, required=False, default=False,
                 help='是否影响系统运行，默认不影响（部件故障）'),
        Argument('impact_status', type=str, required=False, default='',
                 help='系统影响程度：影响系统运行时必填（降级/故障/中断）'),
        Argument('title', type=str, required=False, default=''),
        Argument('description', type=str, required=False, default=''),
        Argument('re_dispose_reason', type=str, required=False, default=''),
    ).parse(body)
    if error:
        return None, error

    occurred_at, err = _resolve_convert_occurred_at(form, item, ledger)
    if err:
        return None, err
    # 默认"部件故障但不影响系统运行"；仅明确选择影响运行时才要求影响程度
    affects, impact_status, err = _validate_convert_impact(form)
    if err:
        return None, err

    description = (form.description or '').strip()
    if not description:
        description = _compose_description(item, ledger)
    # 标题缺省由台账标签 + 检查项组装（统一主表必填标题）
    title = (form.title or '').strip()
    if not title:
        ledger_label = LEDGER_TYPE_TEXT.get(ledger.ledger_type, ledger.ledger_type)
        title = f'[{ledger_label} {ledger.ledger_no}] {item.item_name_snapshot}'[:200]
    return {
        'title': title,
        'occurred_at': occurred_at,
        'affects_system_operation': affects,
        'impact_status': impact_status,
        'description': description,
    }, None

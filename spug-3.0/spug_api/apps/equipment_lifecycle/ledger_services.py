# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——巡检/周月维护/季维护台账服务（步骤 3.2）。

三类台账共用统一模型，通过 ledger_type + maintenance_cycle 区分：
- 巡检（inspection）不要求维护周期；
- 周月维护（week_month）必须为周（week）或月（month）；
- 季维护（seasonal）固定为季（season）。

核心约定：
- 系统关联一律使用系统 ID，页面显示的名称/编号/地点均保存快照；
- 模板生成台账时保存模板项目全量快照，模板后续修改不影响已生成台账；
- 表头与全部明细在同一事务内写入，任一明细校验失败整体回滚；
- 数值项目按正常范围自动建议结果，用户改判须填写修正原因；
- 本模块只记录异常：不转故障/工单、不修改系统健康状态、不做计划提醒。
"""
import json
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle.models import (
    CYCLE_MONTH,
    CYCLE_WEEK,
    ITEM_RESULT_ABNORMAL,
    ITEM_RESULT_NOT_APPLICABLE,
    ITEM_RESULT_PENDING_REVIEW,
    ITEM_RESULT_NORMAL,
    ITEM_RESULT_VALUES,
    LEDGER_FROM_MANUAL,
    LEDGER_FROM_TEMPLATE,
    LEDGER_FROM_VALUES,
    LEDGER_INPUT_TYPE_VALUES,
    LEDGER_NO_PREFIX_MAP,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_RETURNED,
    LEDGER_STATUS_REVIEWED,
    LEDGER_STATUS_SUBMITTED,
    LEDGER_STATUS_VOID,
    LEDGER_STATUS_VALUES,
    LEDGER_TYPE_INSPECTION,
    LEDGER_TYPE_SEASONAL,
    LEDGER_TYPE_VALUES,
    LEDGER_TYPE_WEEK_MONTH,
    ENTRY_CHANNEL_WEB,
    EXEC_SCOPE_VALUES,
    LifecycleSystem,
    OperationLedger,
    OperationLedgerCorrection,
    OperationLedgerItem,
    OperationLedgerTemplate,
    OperationLedgerTemplateItem,
)

# 编辑台账时允许更新的明细字段（模板快照字段生成后不可变）
ITEM_EDITABLE_FIELDS = {
    'value_text', 'value_number', 'value_bool', 'result', 'abnormal_desc',
    'na_reason', 'onsite_action', 'executor_name', 'executed_at',
    'correction_reason', 'display_order',
}
# 明细值/结果字段（快照映射展示用）
ITEM_RESULT_TEXT_MAP = {
    ITEM_RESULT_NORMAL: '正常',
    ITEM_RESULT_ABNORMAL: '异常',
    ITEM_RESULT_NOT_APPLICABLE: '不适用',
    ITEM_RESULT_PENDING_REVIEW: '待复核',
}


class LedgerValidationError(Exception):
    """台账业务校验失败（message 为可直接展示给用户的错误文案）。"""


def validate_ledger_type_cycle(ledger_type, maintenance_cycle):
    """校验台账类型与维护周期组合是否合法（三类台账统一规则）。"""
    if ledger_type not in LEDGER_TYPE_VALUES:
        raise LedgerValidationError('台账类型不合法')
    if ledger_type == LEDGER_TYPE_INSPECTION:
        if maintenance_cycle:
            raise LedgerValidationError('巡检台账不要求填写维护周期')
    elif ledger_type == LEDGER_TYPE_WEEK_MONTH:
        if maintenance_cycle not in (CYCLE_WEEK, CYCLE_MONTH):
            raise LedgerValidationError('周月维护台账必须选择"周"或"月"维护周期')
    else:  # seasonal
        if maintenance_cycle != 'season':
            raise LedgerValidationError('季维护台账维护周期固定为"季"')


def parse_datetime_value(value, field_label, allow_empty=False):
    """解析前端提交的时间字符串，格式不合法抛业务校验错误。"""
    if value in (None, ''):
        if allow_empty:
            return None
        raise LedgerValidationError('%s不能为空' % field_label)
    if isinstance(value, datetime):
        return value
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    raise LedgerValidationError('%s格式不正确' % field_label)


def generate_ledger_no(tenant_id, ledger_type, executed_date):
    """生成台账编号：{前缀}-{YYYYMMDD}-{当日序号:04d}，租户内唯一。

    并发冲突由 (tenant_id, ledger_no) 唯一约束兜底，调用方捕获
    IntegrityError 后重试。
    """
    prefix = LEDGER_NO_PREFIX_MAP[ledger_type]
    base = '%s-%s-' % (prefix, executed_date.strftime('%Y%m%d'))
    rows = OperationLedger.objects.all_with_deleted().filter(
        tenant_id=tenant_id, ledger_no__startswith=base).values_list('ledger_no', flat=True)
    seq = 0
    for no in rows:
        tail = no[len(base):]
        if tail.isdigit():
            seq = max(seq, int(tail))
    return '%s%04d' % (base, seq + 1)


def get_systems_for_user(user, system_ids):
    """按 ID 批量取当前用户可访问且未停用的系统（服务端可信查询）。"""
    ids = list({int(x) for x in system_ids if str(x).isdigit()})
    if not ids:
        raise LedgerValidationError('请选择系统')
    found = {
        s.id: s for s in
        apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(pk__in=ids)
    }
    missing = [i for i in ids if i not in found]
    if missing:
        raise LedgerValidationError('系统不存在或无权限访问')
    inactive = [found[i].name for i in ids if not found[i].is_active]
    if inactive:
        raise LedgerValidationError('系统已停用，不能用于新台账：%s' % '、'.join(inactive))
    return found


def get_template_for_entry(template_id, ledger_type, maintenance_cycle, system):
    """录入校验用模板：类型/周期匹配、启用且适用于该系统。"""
    template = OperationLedgerTemplate.objects.filter(pk=template_id).first()
    if not template:
        raise LedgerValidationError('台账模板不存在')
    if not template.is_active:
        raise LedgerValidationError('台账模板已停用，不能用于新台账：%s' % template.name)
    if template.ledger_type != ledger_type:
        raise LedgerValidationError('台账模板类型与台账类型不一致：%s' % template.name)
    if ledger_type == LEDGER_TYPE_WEEK_MONTH and template.maintenance_cycle != maintenance_cycle:
        raise LedgerValidationError('台账模板维护周期与本次维护周期不一致：%s' % template.name)
    if not template.applies_to_system(system):
        raise LedgerValidationError('台账模板不适用于系统：%s' % system.name)
    return template


def auto_judge_number_result(number_min, number_max, value_number):
    """数值范围自动判定：命中返回 'normal'/'abnormal'，无法判定返回 None。"""
    if value_number is None:
        return None
    if number_min is None and number_max is None:
        return None
    if number_min is not None and value_number < number_min:
        return ITEM_RESULT_ABNORMAL
    if number_max is not None and value_number > number_max:
        return ITEM_RESULT_ABNORMAL
    return ITEM_RESULT_NORMAL


def validate_item_value(input_type, payload):
    """按录入类型校验填写值：必填、类型、候选项。

    payload 键：value_text/value_number/value_bool/is_required/choices。
    校验通过返回规范化后的 (value_text, value_number, value_bool)。
    """
    value_text = payload.get('value_text') or ''
    value_number = payload.get('value_number')
    value_bool = payload.get('value_bool')
    is_required = bool(payload.get('is_required'))
    choices = payload.get('choices') or []

    if input_type not in LEDGER_INPUT_TYPE_VALUES:
        raise LedgerValidationError('录入类型不合法：%s' % input_type)

    if input_type == 'text':
        if is_required and not str(value_text).strip():
            raise LedgerValidationError('该项为必填项，请填写内容')
        return str(value_text), None, None
    if input_type == 'number':
        if value_number in (None, ''):
            if is_required:
                raise LedgerValidationError('该项为必填项，请填写数值')
            return '', None, None
        try:
            return '', float(value_number), None
        except (TypeError, ValueError):
            raise LedgerValidationError('填写值必须为数字')
    if input_type == 'choice':
        if not value_text:
            if is_required:
                raise LedgerValidationError('该项为必填项，请选择候选项')
            return '', None, None
        if value_text not in choices:
            raise LedgerValidationError('填写值不在候选项范围内：%s' % value_text)
        return str(value_text), None, None
    if input_type == 'multi_choice':
        values = value_text if isinstance(value_text, list) else None
        if values is None and value_text not in (None, ''):
            # 前端以 JSON 字符串提交多选值（JSON.stringify 形态），此处兼容解析
            try:
                parsed = json.loads(value_text)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, list):
                values = parsed
        if not values:
            if is_required:
                raise LedgerValidationError('该项为必填项，请选择候选项')
            return '', None, None
        bad = [v for v in values if v not in choices]
        if bad:
            raise LedgerValidationError('多选填写值不在候选项范围内：%s' % '、'.join(map(str, bad)))
        return json.dumps(values, ensure_ascii=False), None, None
    if input_type == 'boolean':
        if value_bool is None or value_bool == '':
            if is_required:
                raise LedgerValidationError('该项为必填项，请选择是/否')
            return '', None, None
        return '', None, bool(value_bool)
    # attachment：附件由附件接口管理，填写值本身不做必填校验
    return str(value_text) if value_text else '', None, None


def resolve_item_result(input_type, snapshot, payload):
    """确定明细结果：数值范围自动判定 + 用户改判校验。

    返回 (result, is_auto_judged, correction_reason)。
    """
    result = payload.get('result') or ''
    correction_reason = str(payload.get('correction_reason') or '').strip()
    if result and result not in ITEM_RESULT_VALUES:
        raise LedgerValidationError('结果不合法：%s' % result)
    auto = auto_judge_number_result(
        snapshot.get('number_min'), snapshot.get('number_max'), payload.get('value_number'))
    if auto is None:
        if not result:
            raise LedgerValidationError('请选择检查结果')
        return result, False, correction_reason
    if not result or result == auto:
        return auto, True, correction_reason
    # 用户结论与自动判定不一致：改判为 normal/abnormal 属于修正判定结论，须填写原因
    if result in (ITEM_RESULT_NORMAL, ITEM_RESULT_ABNORMAL) and not correction_reason:
        raise LedgerValidationError(
            '项目"%s"数值自动判定为%s，修改为%s须填写修正原因' % (
                snapshot.get('item_name', ''), ITEM_RESULT_TEXT_MAP[auto], ITEM_RESULT_TEXT_MAP[result]))
    return result, False, correction_reason


def validate_item_result_rules(result, payload):
    """结果配套规则：异常必填异常说明；不适用允许填写原因。"""
    if result == ITEM_RESULT_ABNORMAL and not str(payload.get('abnormal_desc') or '').strip():
        raise LedgerValidationError('异常项必须填写异常说明')
    if result == ITEM_RESULT_NORMAL and str(payload.get('abnormal_desc') or '').strip() \
            and payload.get('force_abnormal_desc'):
        raise LedgerValidationError('正常项不应填写异常说明')


def build_template_snapshot(template, tpl_item):
    """从模板项目构建明细快照字段（保存当时内容，不实时读模板）。"""
    return {
        'template_item': tpl_item,
        'template_name_snapshot': template.name,
        'item_code_snapshot': tpl_item.item_code,
        'item_name_snapshot': tpl_item.name,
        'standard_snapshot': tpl_item.standard,
        'input_type': tpl_item.input_type,
        'unit_snapshot': tpl_item.unit,
        'normal_range_snapshot': tpl_item.normal_range,
        'choices_snapshot': json.dumps(tpl_item.get_choices(), ensure_ascii=False),
        'number_min': tpl_item.number_min,
        'number_max': tpl_item.number_max,
        'is_required': tpl_item.is_required,
        'abnormal_rule_snapshot': tpl_item.abnormal_rule,
        'execution_scope': tpl_item.execution_scope,
    }


def build_manual_snapshot(payload):
    """临时直接新建/临时增加项的快照字段（内容由用户填写，后端校验）。"""
    item_name = str(payload.get('item_name') or '').strip()
    if not item_name:
        raise LedgerValidationError('请填写检查或维护项目名称')
    input_type = payload.get('input_type') or 'text'
    if input_type not in LEDGER_INPUT_TYPE_VALUES:
        raise LedgerValidationError('录入类型不合法：%s' % input_type)
    choices = payload.get('choices') or []
    if input_type in ('choice', 'multi_choice') and not isinstance(choices, list):
        raise LedgerValidationError('候选项必须为数组')
    return {
        'template_item': None,
        'template_name_snapshot': '',
        'item_code_snapshot': str(payload.get('item_code') or '').strip(),
        'item_name_snapshot': item_name,
        'standard_snapshot': str(payload.get('standard') or '').strip(),
        'input_type': input_type,
        'unit_snapshot': str(payload.get('unit') or '').strip(),
        'normal_range_snapshot': str(payload.get('normal_range') or '').strip(),
        'choices_snapshot': json.dumps(choices, ensure_ascii=False),
        'number_min': payload.get('number_min'),
        'number_max': payload.get('number_max'),
        'is_required': bool(payload.get('is_required')),
        'abnormal_rule_snapshot': str(payload.get('abnormal_rule') or '').strip(),
        'execution_scope': payload.get('execution_scope') or 'all',
    }


def validate_snapshot_execution_scope(execution_scope):
    if execution_scope not in EXEC_SCOPE_VALUES:
        raise LedgerValidationError('执行范围不合法：%s' % execution_scope)


def _parse_header_payload(user, body, for_update=False):
    """解析并校验台账表头字段，返回头部字段 dict。"""
    ledger_type = body.get('ledger_type')
    maintenance_cycle = body.get('maintenance_cycle') or ''
    validate_ledger_type_cycle(ledger_type, maintenance_cycle)
    created_from = body.get('created_from') or ''
    if created_from and created_from not in LEDGER_FROM_VALUES:
        raise LedgerValidationError('创建方式不合法')
    executed_date = body.get('executed_date')
    if not executed_date:
        raise LedgerValidationError('请填写实际执行日期')
    try:
        executed_date = datetime.strptime(str(executed_date)[:10], '%Y-%m-%d').date()
    except ValueError:
        raise LedgerValidationError('实际执行日期格式不正确')
    entry_note = str(body.get('entry_note') or '').strip()
    if created_from == LEDGER_FROM_MANUAL and not entry_note:
        raise LedgerValidationError('临时补录必须填写补录说明')
    return {
        'ledger_type': ledger_type,
        'maintenance_cycle': maintenance_cycle,
        'executed_date': executed_date,
        'shift': str(body.get('shift') or '').strip(),
        'location_scope': str(body.get('location_scope') or '').strip(),
        'executor_names': str(body.get('executor_names') or '').strip(),
        'collaborator_names': str(body.get('collaborator_names') or '').strip(),
        'summary': str(body.get('summary') or '').strip(),
        'executed_start': parse_datetime_value(body.get('executed_start'), '实际执行开始时间', allow_empty=True),
        'executed_end': parse_datetime_value(body.get('executed_end'), '实际执行结束时间', allow_empty=True),
        'entry_note': entry_note,
        'client_token': str(body.get('client_token') or '')[:64],
    }


def _build_item_instances(ledger, systems_map, entries_payload):
    """校验 entries 并构建明细实例列表（不落库）。

    entries_payload: [{system_id, template_id?, items: [{...}]}]
    任一明细校验失败抛 LedgerValidationError（调用方整体回滚）。
    """
    items = []
    seen_system_ids = set()
    for entry in entries_payload:
        if not isinstance(entry, dict):
            raise LedgerValidationError('台账系统条目格式不正确')
        system = systems_map.get(entry.get('system_id'))
        if system is None:
            raise LedgerValidationError('明细必须关联正式系统')
        seen_system_ids.add(system.id)
        template = None
        if entry.get('template_id'):
            template = get_template_for_entry(
                entry['template_id'], ledger.ledger_type, ledger.maintenance_cycle, system)
        rows = entry.get('items')
        if not isinstance(rows, list) or not rows:
            raise LedgerValidationError('系统 %s 至少需要一条台账明细' % system.name)
        order = 0
        for row in rows:
            if not isinstance(row, dict):
                raise LedgerValidationError('台账明细格式不正确')
            order += 1
            items.append(_build_item_instance(ledger, system, template, row, order))
    if not seen_system_ids:
        raise LedgerValidationError('请选择系统')
    return items


def _build_item_instance(ledger, system, template, row, order):
    """校验单条明细并构建未落库的 OperationLedgerItem。"""
    if template is not None and row.get('template_item_id'):
        tpl_item = OperationLedgerTemplateItem.objects.filter(
            pk=row['template_item_id'], template=template).first()
        if not tpl_item:
            raise LedgerValidationError('模板项目不存在或不属于所选模板')
        if not tpl_item.is_active:
            raise LedgerValidationError('模板项目已停用：%s' % tpl_item.name)
        if not tpl_item.matches_cycle(ledger.maintenance_cycle):
            raise LedgerValidationError('模板项目与本次维护周期不匹配：%s' % tpl_item.name)
        snapshot = build_template_snapshot(template, tpl_item)
        is_temporary = False
    else:
        snapshot = build_manual_snapshot(row)
        validate_snapshot_execution_scope(snapshot['execution_scope'])
        is_temporary = True
    value_text, value_number, value_bool = validate_item_value(snapshot['input_type'], row)
    result, is_auto, correction = resolve_item_result(snapshot['input_type'], snapshot, row)
    validate_item_result_rules(result, row)
    item = OperationLedgerItem(
        ledger=ledger,
        system=system,
        tenant_id=system.tenant_id,
        system_code_snapshot=system.system_code,
        system_name_snapshot=system.name,
        system_location_snapshot=system.install_location,
        value_text=value_text,
        value_number=value_number,
        value_bool=value_bool,
        result=result,
        is_auto_judged=is_auto,
        correction_reason=correction,
        abnormal_desc=str(row.get('abnormal_desc') or '').strip(),
        na_reason=str(row.get('na_reason') or '').strip(),
        onsite_action=str(row.get('onsite_action') or '').strip(),
        executor_name=str(row.get('executor_name') or '').strip(),
        executed_at=parse_datetime_value(row.get('executed_at'), '明细实际执行时间', allow_empty=True),
        is_temporary=is_temporary,
        display_order=row.get('display_order') if isinstance(row.get('display_order'), int) else order,
    )
    for key, value in snapshot.items():
        setattr(item, key, value)
    return item


def _get_ledger_for_user(pk, user, for_update=False):
    """按主键取当前用户可访问的台账（可选行锁）。"""
    qs = apply_tenant_filter(OperationLedger.objects.all(), user)
    if for_update:
        qs = qs.select_for_update()
    return qs.filter(pk=pk).first()


@transaction.atomic
def create_ledger(user, body):
    """创建台账：表头 + 全部明细 + 快照一次写入，任一明细失败整体回滚。

    幂等：client_token 命中同租户已有台账时直接返回该台账。
    创建方式未指定时按 entries 是否含模板自动推断（manual 须填补录说明）。
    返回 (ledger, None) 或 (None, error_message)。
    """
    if not body.get('created_from'):
        entries_raw = body.get('entries') or []
        body['created_from'] = LEDGER_FROM_TEMPLATE if any(
            isinstance(e, dict) and e.get('template_id') for e in entries_raw) else LEDGER_FROM_MANUAL
    try:
        header = _parse_header_payload(user, body)
    except LedgerValidationError as e:
        return None, str(e)
    client_token = header.pop('client_token', '')
    if client_token:
        exists = apply_tenant_filter(OperationLedger.objects.all(), user).filter(
            client_token=client_token).first()
        if exists:
            return exists, None

    entries = body.get('entries')
    if not isinstance(entries, list) or not entries:
        return None, '请至少录入一个系统的台账明细'
    created_from = body['created_from']

    try:
        systems_map = get_systems_for_user(user, [
            e.get('system_id') for e in entries if isinstance(e, dict)])
        ledger = OperationLedger(
            tenant_id=user.tenant_id,
            status=LEDGER_STATUS_DRAFT,
            entry_channel=ENTRY_CHANNEL_WEB,
            created_from=created_from,
            created_by=user,
            **header,
        )
        items = _build_item_instances(ledger, systems_map, entries)
        ledger.ledger_no = generate_ledger_no(user.tenant_id, ledger.ledger_type, ledger.executed_date)
        ledger.client_token = client_token
        ledger.save()
        OperationLedgerItem.objects.bulk_create(items)
        return ledger, None
    except LedgerValidationError as e:
        return None, str(e)


@transaction.atomic
def update_ledger(user, pk, body):
    """编辑可编辑状态（草稿/已退回）的台账：区分新增、修改、移除并记录变化。

    - version 不匹配视为并发冲突，拒绝静默覆盖；
    - 已有明细更新可编辑字段（模板快照不可变），新增明细按创建规则校验；
    - 请求未包含的已有明细被移除（物理删除），变化写入审计 detail；
    返回 (ledger, changed, None) 或 (None, None, error_message)。
    """
    ledger = _get_ledger_for_user(pk, user, for_update=True)
    if not ledger:
        return None, None, '台账不存在'
    if ledger.status not in OperationLedger.EDITABLE_STATUSES:
        return None, None, '当前状态不允许编辑台账'
    version = body.get('version')
    if version is not None:
        try:
            expected_version = int(version)
        except (TypeError, ValueError):
            return None, None, '版本参数不合法'
        if expected_version != ledger.version:
            return None, None, '台账已被他人修改，请刷新后重试'
    try:
        header = _parse_header_payload(user, body, for_update=True)
    except LedgerValidationError as e:
        return None, None, str(e)
    header.pop('client_token', None)
    entries = body.get('entries')
    if not isinstance(entries, list) or not entries:
        return None, None, '请至少录入一个系统的台账明细'
    changed = {'header': [], 'items_added': 0, 'items_updated': 0, 'items_removed': []}
    try:
        for field, value in header.items():
            old = getattr(ledger, field)
            if old != value:
                changed['header'].append({'field': field, 'old': str(old), 'new': str(value)})
                setattr(ledger, field, value)

        systems_map = get_systems_for_user(user, [
            e.get('system_id') for e in entries if isinstance(e, dict)])
        keep_ids = set()
        order = 0
        for entry in entries:
            system = systems_map.get(entry.get('system_id'))
            if system is None:
                raise LedgerValidationError('明细必须关联正式系统')
            template = None
            if entry.get('template_id'):
                template = get_template_for_entry(
                    entry['template_id'], ledger.ledger_type, ledger.maintenance_cycle, system)
            rows = entry.get('items')
            if not isinstance(rows, list) or not rows:
                raise LedgerValidationError('系统 %s 至少需要一条台账明细' % system.name)
            for row in rows:
                order += 1
                item_id = row.get('id')
                if item_id:
                    item = OperationLedgerItem.objects.filter(pk=item_id, ledger=ledger).first()
                    if not item:
                        raise LedgerValidationError('台账明细不存在或已移除')
                    _apply_item_edits(item, row, system)
                    keep_ids.add(item.id)
                    changed['items_updated'] += 1
                else:
                    item = _build_item_instance(ledger, system, template, row, order)
                    item.save()
                    keep_ids.add(item.id)
                    changed['items_added'] += 1
        for item in list(ledger.items.all()):
            if item.id not in keep_ids:
                changed['items_removed'].append(item.item_name_snapshot)
                item.delete()
        ledger.version += 1
        ledger.save(update_fields=[
            'ledger_type', 'maintenance_cycle', 'executed_date', 'shift', 'location_scope',
            'executor_names', 'collaborator_names', 'summary', 'executed_start', 'executed_end',
            'entry_note', 'version'])
        return ledger, changed, None
    except LedgerValidationError as e:
        return None, None, str(e)


def _apply_item_edits(item, row, system):
    """编辑已有明细：仅允许更新填写值/结果类字段，校验规则与创建一致。"""
    payload = {
        'value_text': row.get('value_text'),
        'value_number': row.get('value_number'),
        'value_bool': row.get('value_bool'),
        'is_required': item.is_required,
        'choices': item.get_choices(),
    }
    value_text, value_number, value_bool = validate_item_value(item.input_type, payload)
    item.value_text, item.value_number, item.value_bool = value_text, value_number, value_bool
    result, is_auto, correction = resolve_item_result(item.input_type, {
        'number_min': item.number_min, 'number_max': item.number_max,
        'item_name': item.item_name_snapshot,
    }, row)
    item.result, item.is_auto_judged, item.correction_reason = result, is_auto, correction
    validate_item_result_rules(result, row)
    if 'abnormal_desc' in row:
        item.abnormal_desc = str(row.get('abnormal_desc') or '').strip()
    if 'na_reason' in row:
        item.na_reason = str(row.get('na_reason') or '').strip()
    if 'onsite_action' in row:
        item.onsite_action = str(row.get('onsite_action') or '').strip()
    if 'executor_name' in row:
        item.executor_name = str(row.get('executor_name') or '').strip()
    if 'executed_at' in row:
        item.executed_at = parse_datetime_value(row.get('executed_at'), '明细实际执行时间', allow_empty=True)
    item.save()


def preview_entries(user, body):
    """按 系统+模板 生成台账明细预览骨架（不落库，值/结果由填写人补充）。"""
    ledger_type = body.get('ledger_type')
    maintenance_cycle = body.get('maintenance_cycle') or ''
    try:
        validate_ledger_type_cycle(ledger_type, maintenance_cycle)
    except LedgerValidationError as e:
        return None, str(e)
    entries = body.get('entries')
    if not isinstance(entries, list) or not entries:
        return None, '请至少选择一个系统'
    try:
        systems_map = get_systems_for_user(user, [
            e.get('system_id') for e in entries if isinstance(e, dict)])
    except LedgerValidationError as e:
        return None, str(e)
    preview = []
    for entry in entries:
        system = systems_map.get(entry.get('system_id'))
        template = None
        if entry.get('template_id'):
            try:
                template = get_template_for_entry(
                    entry['template_id'], ledger_type, maintenance_cycle, system)
            except LedgerValidationError as e:
                return None, str(e)
        items = []
        if template is not None:
            for tpl_item in template.items.filter(is_active=True):
                if not tpl_item.matches_cycle(maintenance_cycle):
                    continue
                view = tpl_item.to_view()
                view['client_key'] = '%s-%s' % (system.id, tpl_item.id)
                items.append(view)
        preview.append({
            'system': {
                'id': system.id, 'system_code': system.system_code, 'name': system.name,
                'install_location': system.install_location,
            },
            'template': {'id': template.id, 'name': template.name} if template else None,
            'items': items,
        })
    return preview, None


@transaction.atomic
def submit_ledger(user, pk):
    """提交台账：草稿/已退回 → 已提交（重复提交返回明确错误，无重复副作用）。"""
    ledger = _get_ledger_for_user(pk, user, for_update=True)
    if not ledger:
        return None, '台账不存在'
    if not ledger.can_transition_to(LEDGER_STATUS_SUBMITTED):
        return None, '当前状态不允许提交（已提交或已复核台账请勿重复操作）'
    if not ledger.items.exists():
        return None, '台账没有明细，不能提交'
    ledger.status = LEDGER_STATUS_SUBMITTED
    ledger.submitted_at = timezone.now()
    ledger.submitted_by = user
    ledger.save(update_fields=['status', 'submitted_at', 'submitted_by'])
    return ledger, None


@transaction.atomic
def return_ledger(user, pk, reason):
    """退回台账：已提交 → 已退回，必须填写原因。"""
    reason = str(reason or '').strip()
    if not reason:
        return None, '退回必须填写原因'
    ledger = _get_ledger_for_user(pk, user, for_update=True)
    if not ledger:
        return None, '台账不存在'
    if not ledger.can_transition_to(LEDGER_STATUS_RETURNED):
        return None, '当前状态不允许退回'
    ledger.status = LEDGER_STATUS_RETURNED
    ledger.returned_at = timezone.now()
    ledger.returned_by = user
    ledger.return_reason = reason
    ledger.save(update_fields=['status', 'returned_at', 'returned_by', 'return_reason'])
    return ledger, None


@transaction.atomic
def review_ledger(user, pk):
    """复核台账：已提交 → 已复核，记录复核人。"""
    ledger = _get_ledger_for_user(pk, user, for_update=True)
    if not ledger:
        return None, '台账不存在'
    if not ledger.can_transition_to(LEDGER_STATUS_REVIEWED):
        return None, '当前状态不允许复核'
    ledger.status = LEDGER_STATUS_REVIEWED
    ledger.reviewed_at = timezone.now()
    ledger.reviewed_by = user
    ledger.reviewer_name = user.username
    ledger.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'reviewer_name'])
    return ledger, None


@transaction.atomic
def void_ledger(user, pk, reason):
    """受控作废：不物理删除；已作废台账不参与正常统计。"""
    reason = str(reason or '').strip()
    if not reason:
        return None, '作废必须填写原因'
    ledger = _get_ledger_for_user(pk, user, for_update=True)
    if not ledger:
        return None, '台账不存在'
    if not ledger.can_transition_to(LEDGER_STATUS_VOID):
        return None, '当前状态不允许作废'
    ledger.status = LEDGER_STATUS_VOID
    ledger.voided_at = timezone.now()
    ledger.voided_by = user
    ledger.void_reason = reason
    ledger.save(update_fields=['status', 'voided_at', 'voided_by', 'void_reason'])
    return ledger, None


# 复核后台账允许更正的明细字段
CORRECTABLE_FIELDS = {
    'value_text': '填写值', 'value_number': '数值填写值', 'value_bool': '布尔填写值',
    'result': '结果', 'abnormal_desc': '异常说明', 'na_reason': '不适用原因',
    'onsite_action': '现场处理内容',
}


@transaction.atomic
def correct_ledger(user, pk, body):
    """复核后台账更正：必须填写原因，保存字段前后值（不静默修改）。"""
    ledger = _get_ledger_for_user(pk, user, for_update=True)
    if not ledger:
        return None, None, '台账不存在'
    if ledger.status != 'reviewed':
        return None, None, '只有已复核台账可以进行更正'
    reason = str(body.get('reason') or '').strip()
    if not reason:
        return None, None, '更正必须填写原因'
    item = None
    if body.get('item_id'):
        item = ledger.items.filter(pk=body['item_id']).first()
        if not item:
            return None, None, '台账明细不存在'
    changes = []
    try:
        if item is not None:
            payload = {
                'value_text': body.get('value_text', item.value_text),
                'value_number': body.get('value_number', item.value_number),
                'value_bool': body.get('value_bool', item.value_bool),
                'is_required': item.is_required,
                'choices': item.get_choices(),
            }
            value_text, value_number, value_bool = validate_item_value(item.input_type, payload)
            new_result = body.get('result', item.result)
            if new_result not in ITEM_RESULT_VALUES:
                raise LedgerValidationError('结果不合法：%s' % new_result)
            if new_result == ITEM_RESULT_ABNORMAL and not str(body.get('abnormal_desc', item.abnormal_desc) or '').strip():
                raise LedgerValidationError('异常项必须填写异常说明')
            updates = {
                'value_text': value_text,
                'value_number': value_number,
                'value_bool': value_bool,
                'result': new_result,
                'is_auto_judged': False,
                'correction_reason': reason,
            }
            if 'abnormal_desc' in body:
                updates['abnormal_desc'] = str(body.get('abnormal_desc') or '').strip()
            if 'na_reason' in body:
                updates['na_reason'] = str(body.get('na_reason') or '').strip()
            if 'onsite_action' in body:
                updates['onsite_action'] = str(body.get('onsite_action') or '').strip()
            for field, new_value in updates.items():
                old_value = getattr(item, field)
                if old_value != new_value:
                    changes.append({
                        'field': field, 'label': CORRECTABLE_FIELDS.get(field, field),
                        'old': old_value, 'new': new_value,
                    })
                    setattr(item, field, new_value)
            item.save()
        else:
            header_updates = {
                'summary': ('总体说明', body.get('summary')),
                'executor_names': ('执行人', body.get('executor_names')),
                'collaborator_names': ('协作人', body.get('collaborator_names')),
            }
            for field, (label, new_value) in header_updates.items():
                if new_value is None:
                    continue
                new_value = str(new_value).strip()
                old_value = getattr(ledger, field)
                if old_value != new_value:
                    changes.append({'field': field, 'label': label, 'old': old_value, 'new': new_value})
                    setattr(ledger, field, new_value)
            ledger.save(update_fields=['summary', 'executor_names', 'collaborator_names'])
        if not changes:
            return None, None, '没有需要更正的内容'
        correction = OperationLedgerCorrection.objects.create(
            ledger=ledger, item=item, reason=reason,
            changes=json.dumps(changes, ensure_ascii=False, default=str), corrected_by=user)
        return correction, changes, None
    except LedgerValidationError as e:
        return None, None, str(e)


@transaction.atomic
def confirm_normal(user, pk, item_ids):
    """批量确认正常：可编辑状态下将所选明细结果置为正常（不覆盖异常说明）。"""
    ledger = _get_ledger_for_user(pk, user, for_update=True)
    if not ledger:
        return None, '台账不存在'
    if ledger.status not in OperationLedger.EDITABLE_STATUSES:
        return None, '当前状态不允许批量确认'
    if not isinstance(item_ids, list) or not item_ids:
        return None, '请选择需要确认的明细'
    items = ledger.items.filter(pk__in=item_ids)
    if items.count() != len(set(item_ids)):
        return None, '台账明细不存在或已移除'
    for item in items:
        if item.result == ITEM_RESULT_ABNORMAL and item.abnormal_desc:
            continue  # 已确认异常的明细不通过批量确认改为正常，需逐项修改
        auto = auto_judge_number_result(item.number_min, item.number_max, item.value_number)
        if auto == ITEM_RESULT_ABNORMAL:
            continue  # 数值超限的明细不参与批量确认
        item.result = ITEM_RESULT_NORMAL
        item.is_auto_judged = auto == ITEM_RESULT_NORMAL
        item.save(update_fields=['result', 'is_auto_judged'])
    return ledger, None

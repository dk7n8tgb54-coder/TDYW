# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——周月维护/季维护台账服务（步骤 3.2）。

两类维护台账共用统一模型，通过 ledger_type 区分：
- 周月维护（week_month）：周表/月表合一，不拆分周维护/月维护（2026-09-26）；
- 季维护（seasonal）；
- 周期批量新增（2026-10-11）：按 维护类型+周期 一键生成各在用系统的草稿
  台账并按周期分组查看，周期仅作分组/去重标记（见文件尾部同名章节）；
- 旧巡检台账（ledger_type=inspection）业务分支已删除（2026-09-24），
  巡检由独立模型（InspectionTemplate/InspectionDutySheet/InspectionRecord）承担，
  旧类型请求一律显式拒绝；
- 旧可视化模板路线（template 创建/矩阵台账/预览）已于 2026-10 整体删除，
  正式台账统一走 Excel/WPS 模板路线（excel_ledger_services）；本模块保留
  手工补录台账（created_from=manual）的创建/编辑/状态机与更正能力，
  entries 携带 template_id/row_nodes 等旧参数时显式拒绝。

核心约定：
- 系统关联一律使用系统 ID，页面显示的名称/编号/地点均保存快照；
- 手工补录明细内容由用户填写、后端校验，全量快照落库；
- 表头与全部明细在同一事务内写入，任一明细校验失败整体回滚；
- 明细结果不再强制选择：未提交结果时按填写值派生默认
  （正常/不正常单选填"不正常"记 abnormal，其余一律 normal），异常说明选填；
- 本模块只记录异常：异常处置（转故障）见 operation_ledger_convert；不修改系统健康状态、
  不做计划提醒。
"""
import json
import re
from datetime import date, datetime, timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle.models import (
    ITEM_RESULT_ABNORMAL,
    ITEM_RESULT_NOT_APPLICABLE,
    ITEM_RESULT_PENDING_REVIEW,
    ITEM_RESULT_NORMAL,
    ITEM_RESULT_VALUES,
    LEGACY_LEDGER_TYPE_INSPECTION,
    LEDGER_FROM_MANUAL,
    LEDGER_FROM_EXCEL,
    LEDGER_FROM_VALUES,
    LEDGER_INPUT_TYPE_VALUES,
    LEDGER_NO_PREFIX_MAP,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_RETURNED,
    LEDGER_STATUS_REVIEWED,
    LEDGER_STATUS_SUBMITTED,
    LEDGER_STATUS_VOID,
    LEDGER_STATUS_VALUES,
    LEDGER_TYPE_SEASONAL,
    LEDGER_TYPE_VALUES,
    LEDGER_TYPE_WEEK_MONTH,
    ENTRY_CHANNEL_WEB,
    LifecycleSystem,
    OperationLedger,
    OperationLedgerCorrection,
    OperationLedgerItem,
)
from apps.equipment_lifecycle.operation_models import SystemOperationRecord

# 明细值/结果字段（快照映射展示用）
ITEM_RESULT_TEXT_MAP = {
    ITEM_RESULT_NORMAL: '正常',
    ITEM_RESULT_ABNORMAL: '异常',
    ITEM_RESULT_NOT_APPLICABLE: '不适用',
    ITEM_RESULT_PENDING_REVIEW: '待复核',
}
# 正常/不正常单选的固定候选项（与前端 constants.js NORMAL_ABNORMAL_CHOICES 对齐）
LEDGER_CHOICE_ABNORMAL = '不正常'

# 旧巡检台账类型已删除（值班巡检改造 + 旧巡检台账下线）：
# 所有针对旧类型的新建/编辑/写操作一律显式拒绝，不静默当作维护台账处理；
# 周月维护/季维护台账不受影响。
LEGACY_INSPECTION_ERROR = '旧巡检台账（历史）已删除，巡检类型不再支持该操作'

# Excel 路线台账（created_from=excel_template）无普通明细，明细编辑与
# 提交须走 /excel-ledgers/ 专用接口；复核/退回/作废沿用正式端点
EXCEL_LEDGER_EDIT_ERROR = 'Excel 模板台账请通过 Excel 台账填写接口编辑'
EXCEL_LEDGER_SUBMIT_ERROR = 'Excel 模板台账请通过 Excel 台账接口提交'


def excel_ledger_write_error(ledger):
    """Excel 路线台账误走普通明细编辑/提交接口时返回明确错误。"""
    if ledger is not None and ledger.created_from == LEDGER_FROM_EXCEL:
        return EXCEL_LEDGER_EDIT_ERROR
    return None


def legacy_inspection_error(ledger):
    """已删除的旧巡检类型统一拦截：对旧类型台账的写操作返回明确错误。"""
    if ledger is not None and ledger.ledger_type == LEGACY_LEDGER_TYPE_INSPECTION:
        return LEGACY_INSPECTION_ERROR
    return None


class LedgerValidationError(Exception):
    """台账业务校验失败（message 为可直接展示给用户的错误文案）。"""


def validate_ledger_type(ledger_type):
    """校验台账类型是否合法（旧巡检类型显式拒绝，维护台账统一规则）。"""
    if ledger_type == LEGACY_LEDGER_TYPE_INSPECTION:
        raise LedgerValidationError(LEGACY_INSPECTION_ERROR)
    if ledger_type not in LEDGER_TYPE_VALUES:
        raise LedgerValidationError('台账类型不合法')


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


# 旧可视化模板路线已删除（2026-10）：entries 携带模板引用时统一报错文案
TEMPLATE_ROUTE_REMOVED_ERROR = '可视化模板台账路线已下线，请使用 Excel/WPS 模板创建台账'


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
        # 数字/文本类型：纯数字填写值同时落 value_number，供范围自动判定与批量确认超限拦截使用
        number = None
        if value_number not in (None, ''):
            try:
                number = float(value_number)
            except (TypeError, ValueError):
                number = None
        return str(value_text), number, None
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


def resolve_item_result(payload):
    """确定明细结果：录入界面已无结果列，不强制选择。

    显式提交时校验合法性；未提交时按填写值派生默认——
    正常/不正常单选填"不正常"记 abnormal，其余一律 normal，
    避免"填写值=不正常、结果=正常"的数据矛盾。
    """
    result = payload.get('result') or ''
    if not result:
        if str(payload.get('value_text') or '').strip() == LEDGER_CHOICE_ABNORMAL:
            return ITEM_RESULT_ABNORMAL
        return ITEM_RESULT_NORMAL
    if result not in ITEM_RESULT_VALUES:
        raise LedgerValidationError('结果不合法：%s' % result)
    return result


def validate_item_result_rules(result, payload):
    """结果配套规则：异常说明选填；正常项不应填写异常说明。"""
    if result == ITEM_RESULT_NORMAL and str(payload.get('abnormal_desc') or '').strip() \
            and payload.get('force_abnormal_desc'):
        raise LedgerValidationError('正常项不应填写异常说明')


def build_manual_snapshot(payload):
    """手工补录/临时增加项的快照字段（内容由用户填写，后端校验）。"""
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
        'template_name_snapshot': '',
        'item_name_snapshot': item_name,
        'input_type': input_type,
        'unit_snapshot': str(payload.get('unit') or '').strip(),
        'choices_snapshot': json.dumps(choices, ensure_ascii=False),
        'is_required': bool(payload.get('is_required')),
        'abnormal_rule_snapshot': str(payload.get('abnormal_rule') or '').strip(),
    }


def _parse_header_payload(user, body, for_update=False):
    """解析并校验台账表头字段，返回头部字段 dict。"""
    ledger_type = body.get('ledger_type')
    validate_ledger_type(ledger_type)
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
    return {
        'ledger_type': ledger_type,
        'executed_date': executed_date,
        'executor_names': str(body.get('executor_names') or '').strip(),
        'executed_start': parse_datetime_value(body.get('executed_start'), '实际执行开始时间', allow_empty=True),
        'executed_end': parse_datetime_value(body.get('executed_end'), '实际执行结束时间', allow_empty=True),
        'client_token': str(body.get('client_token') or '')[:64],
    }


def _build_item_instances(user, ledger, systems_map, entries_payload):
    """校验 entries 并构建明细实例列表（不落库）。

    entries_payload: [{system_id, items: [{...}]}]——旧可视化模板路线已删除，
    条目携带 template_id/row_nodes 等旧参数时显式拒绝。
    任一明细校验失败抛 LedgerValidationError（调用方整体回滚）。
    """
    items = []
    seen_system_ids = set()
    for entry in entries_payload:
        if not isinstance(entry, dict):
            raise LedgerValidationError('台账系统条目格式不正确')
        if entry.get('template_id') or entry.get('row_nodes'):
            raise LedgerValidationError(TEMPLATE_ROUTE_REMOVED_ERROR)
        system = systems_map.get(entry.get('system_id'))
        if system is None:
            raise LedgerValidationError('明细必须关联正式系统')
        seen_system_ids.add(system.id)
        rows = entry.get('items')
        if not isinstance(rows, list) or not rows:
            raise LedgerValidationError('系统 %s 至少需要一条台账明细' % system.name)
        order = 0
        for row in rows:
            if not isinstance(row, dict):
                raise LedgerValidationError('台账明细格式不正确')
            order += 1
            items.append(_build_item_instance(ledger, system, row, order))
    if not seen_system_ids:
        raise LedgerValidationError('请选择系统')
    return items


def _build_item_instance(ledger, system, row, order):
    """校验单条手工补录明细并构建未落库的 OperationLedgerItem。"""
    snapshot = build_manual_snapshot(row)
    value_text, value_number, value_bool = validate_item_value(snapshot['input_type'], row)
    result = resolve_item_result(row)
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
        abnormal_desc=str(row.get('abnormal_desc') or '').strip(),
        na_reason=str(row.get('na_reason') or '').strip(),
        onsite_action=str(row.get('onsite_action') or '').strip(),
        executor_name=str(row.get('executor_name') or '').strip(),
        executed_at=parse_datetime_value(row.get('executed_at'), '明细实际执行时间', allow_empty=True),
        is_temporary=True,
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
    """创建手工补录台账：表头 + 全部明细 + 快照一次写入，任一明细失败整体回滚。

    旧可视化模板路线（矩阵台账/模板条目）已删除（2026-10）：created_from 只
    接受 manual（缺省 manual），条目携带模板引用时显式拒绝；正式新增入口
    统一走 Excel/WPS 模板路线（excel_ledger_services.create_ledger）。
    幂等：client_token 命中同租户已有台账时直接返回该台账。
    返回 (ledger, None) 或 (None, error_message)。
    """
    if not body.get('created_from'):
        body['created_from'] = LEDGER_FROM_MANUAL
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
        items = _build_item_instances(user, ledger, systems_map, entries)
        ledger.ledger_no = generate_ledger_no(user.tenant_id, ledger.ledger_type, ledger.executed_date)
        ledger.client_token = client_token
        ledger.save()
        OperationLedgerItem.objects.bulk_create(items)
        return ledger, None
    except LedgerValidationError as e:
        return None, str(e)


def _validate_expected_version(ledger, version):
    """校验编辑请求携带的并发版本；不匹配视为冲突，返回错误信息或 None。"""
    if version is None:
        return None
    try:
        expected_version = int(version)
    except (TypeError, ValueError):
        return '版本参数不合法'
    if expected_version != ledger.version:
        return '台账已被他人修改，请刷新后重试'
    return None


@transaction.atomic
def update_ledger(user, pk, body):
    """编辑可编辑状态（草稿/已退回）的手工补录台账：区分新增、修改、移除并记录变化。

    - version 不匹配视为并发冲突，拒绝静默覆盖；
    - Excel 路线台账（created_from=excel_template）拒绝走本接口；
    - 已有明细更新可编辑字段，新增明细按创建规则校验；
    - 请求未包含的已有明细被移除（物理删除），变化写入审计 detail；
    返回 (ledger, changed, None) 或 (None, None, error_message)。
    """
    ledger = _get_ledger_for_user(pk, user, for_update=True)
    if not ledger:
        return None, None, '台账不存在'
    error = legacy_inspection_error(ledger)
    if error:
        return None, None, error
    # Excel 路线台账没有普通明细，编辑须走 Excel 填写值接口（2026-10 统一入口）
    error = excel_ledger_write_error(ledger)
    if error:
        return None, None, error
    if ledger.status not in OperationLedger.EDITABLE_STATUSES:
        return None, None, '当前状态不允许编辑台账'
    error = _validate_expected_version(ledger, body.get('version'))
    if error:
        return None, None, error
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
        keep_ids = _apply_entry_edits(user, ledger, entries, systems_map, changed)
        _remove_absent_items(ledger, keep_ids, changed)
        ledger.version += 1
        ledger.save(update_fields=[
            'ledger_type', 'executed_date',
            'executor_names', 'executed_start', 'executed_end', 'version'])
        return ledger, changed, None
    except LedgerValidationError as e:
        return None, None, str(e)


def _apply_entry_edits(user, ledger, entries, systems_map, changed):
    """按条目应用明细修改/新增，返回本次请求保留的已有明细 id 集合。

    旧可视化模板路线已删除：条目携带 template_id 时显式拒绝。
    """
    keep_ids = set()
    order = 0
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('template_id') or entry.get('row_nodes'):
            raise LedgerValidationError(TEMPLATE_ROUTE_REMOVED_ERROR)
        system = systems_map.get(entry.get('system_id'))
        if system is None:
            raise LedgerValidationError('明细必须关联正式系统')
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
                item = _build_item_instance(ledger, system, row, order)
                item.save()
                keep_ids.add(item.id)
                changed['items_added'] += 1
    return keep_ids


def _remove_absent_items(ledger, keep_ids, changed):
    """物理删除请求未包含的已有明细，并记录移除清单。"""
    for item in list(ledger.items.all()):
        if item.id not in keep_ids:
            changed['items_removed'].append(item.item_name_snapshot)
            item.delete()


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
    value_changed = (item.value_text, item.value_number, item.value_bool) != (
        value_text, value_number, value_bool)
    item.value_text, item.value_number, item.value_bool = value_text, value_number, value_bool
    # 结果列已从录入界面移除：仅显式提交结果或填写值变化时重算，否则保留原结果
    if row.get('result') or value_changed:
        item.result = resolve_item_result(row)
        validate_item_result_rules(item.result, row)
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


@transaction.atomic
def submit_ledger(user, pk):
    """提交台账：草稿/已退回 → 已提交（重复提交返回明确错误，无重复副作用）。"""
    ledger = _get_ledger_for_user(pk, user, for_update=True)
    if not ledger:
        return None, '台账不存在'
    error = legacy_inspection_error(ledger)
    if error:
        return None, error
    # Excel 路线台账提交须走 /excel-ledgers/<pk>/submit/（含必填校验）
    if ledger.created_from == LEDGER_FROM_EXCEL:
        return None, EXCEL_LEDGER_SUBMIT_ERROR
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
    error = legacy_inspection_error(ledger)
    if error:
        return None, error
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
    error = legacy_inspection_error(ledger)
    if error:
        return None, error
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
    error = legacy_inspection_error(ledger)
    if error:
        return None, error
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
    error = legacy_inspection_error(ledger)
    if error:
        return None, None, error
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
            _correct_ledger_item(item, body, changes)
        else:
            _correct_ledger_header(ledger, body, changes)
        if not changes:
            return None, None, '没有需要更正的内容'
        correction = OperationLedgerCorrection.objects.create(
            ledger=ledger, item=item, reason=reason,
            changes=json.dumps(changes, ensure_ascii=False, default=str), corrected_by=user)
        return correction, changes, None
    except LedgerValidationError as e:
        return None, None, str(e)


def _correct_ledger_item(item, body, changes):
    """复核后更正单条明细：校验填写值与结果，比较前后值并应用变更。"""
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
    updates = {
        'value_text': value_text,
        'value_number': value_number,
        'value_bool': value_bool,
        'result': new_result,
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


def _correct_ledger_header(ledger, body, changes):
    """复核后更正表头允许字段（当前仅执行人），比较前后值并应用变更。"""
    header_updates = {
        'executor_names': ('执行人', body.get('executor_names')),
    }
    for field, (label, new_value) in header_updates.items():
        if new_value is None:
            continue
        new_value = str(new_value).strip()
        old_value = getattr(ledger, field)
        if old_value != new_value:
            changes.append({'field': field, 'label': label, 'old': old_value, 'new': new_value})
            setattr(ledger, field, new_value)
    ledger.save(update_fields=['executor_names'])


@transaction.atomic
def confirm_normal(user, pk, item_ids):
    """批量确认正常：可编辑状态下将所选明细结果置为正常（不覆盖异常说明）。"""
    ledger = _get_ledger_for_user(pk, user, for_update=True)
    if not ledger:
        return None, '台账不存在'
    error = legacy_inspection_error(ledger)
    if error:
        return None, error
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
        item.result = ITEM_RESULT_NORMAL
        item.save(update_fields=['result'])
    return ledger, None


# ======================================================================
# 台账异常明细处置状态（2026-09-30 自 work_order_services 迁入并去工单化：
# 仅保留"转故障"链路；由来源关系动态推导，不落库、不依赖前端）
# ----------------------------------------------------------------------
DISPOSITION_NONE = 'none'                      # 未处置
DISPOSITION_CONVERTED_FAULT = 'converted_fault'  # 已转故障
DISPOSITION_TARGET_CANCELLED = 'target_cancelled'  # 处置目标已取消或作废
DISPOSITION_STATUS_VALUES = [
    DISPOSITION_NONE, DISPOSITION_CONVERTED_FAULT, DISPOSITION_TARGET_CANCELLED,
]


def compute_item_disposition(tenant_id, item_ids):
    """计算台账异常明细的处置状态（由来源统一记录关系动态推导，事实依据）。

    返回 {item_id: {'status': ..., 'target': {...} 或 None}}：
    - status ∈ none / converted_fault / target_cancelled；
    - target 为来源统一记录摘要（id/record_no/status，正式故障单）；
    - 已撤销的来源记录仍保留关联（历史可追溯），仅体现为 target_cancelled；
    - 台账明细本身不因转故障被修改。
    """
    item_ids = [int(i) for i in item_ids]
    result = {
        i: {'status': DISPOSITION_NONE, 'target': None}
        for i in item_ids
    }
    if not item_ids or not tenant_id:
        return result

    for record in SystemOperationRecord.objects.filter(
            tenant_id=tenant_id, source_ledger_item_id__in=item_ids).order_by('-id'):
        slot = result.get(record.source_ledger_item_id)
        if slot is None:
            continue
        if slot['target'] is None:
            slot['target'] = {
                'id': record.id, 'record_no': record.record_no, 'status': record.status}
        if record.status != 'cancelled' and slot['status'] == DISPOSITION_NONE:
            slot['status'] = DISPOSITION_CONVERTED_FAULT

    # 存在历史关联但目标均已撤销
    for slot in result.values():
        if slot['status'] == DISPOSITION_NONE and slot['target']:
            slot['status'] = DISPOSITION_TARGET_CANCELLED
    return result


def append_item_disposition(tenant_id, items):
    """把处置状态批量并入台账明细序列化结果（items 为 to_view() 后的 dict 列表）。"""
    ids = [item['id'] for item in items if isinstance(item, dict) and item.get('id')]
    if not ids:
        return items
    disposition_map = compute_item_disposition(tenant_id, ids)
    for item in items:
        item['disposition'] = disposition_map.get(item.get('id'))
    return items


# ======================================================================
# 周期批量新增与周期分组（2026-10-11 最小实现）
# ----------------------------------------------------------------------
# - 维护类型只有周月维护/季维护两类：周月维护按"月"（YYYY-MM）组织，
#   不拆分周维护/月维护；季维护按民航航季组织，分"夏秋季"与"冬春季"
#   两季（YYYY-夏秋 / YYYY-冬春，YYYY 为航季开始年份）：
#   夏秋季 = 3月最后一个周日 起，至 10月最后一个周日 前；
#   冬春季 = 10月最后一个周日 起，至次年3月最后一个周日 前；
# - 一键新增范围 = 本租户在用系统（LifecycleSystem.is_active=True），
#   一系统一张草稿台账（表头 system/maintenance_period 标记），明细由
#   用户后续补录，不预填、不编造内容；
# - 幂等去重：同类型+同周期+同系统已存在有效台账（含历史台账实际执行
#   日期落在该周期内）时跳过；作废台账不占用周期名额；
# - 历史台账无周期标记，分组展示按实际执行日期推导周期。
# ======================================================================

PERIOD_MONTH_RE = re.compile(r'^(\d{4})-(0[1-9]|1[0-2])$')
PERIOD_SEASON_RE = re.compile(r'^(\d{4})-(夏秋|冬春)$')


def _last_weekday_of_month(year, month, weekday):
    """某月最后一个指定星期几（weekday: 周一=0 … 周日=6）。"""
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    return last_day - timedelta(days=(last_day.weekday() - weekday) % 7)


def parse_maintenance_period(ledger_type, period):
    """校验并解析维护周期，返回 (period, start_date, end_date_exclusive)。"""
    validate_ledger_type(ledger_type)
    period = str(period or '').strip()
    if ledger_type == LEDGER_TYPE_WEEK_MONTH:
        matched = PERIOD_MONTH_RE.match(period)
        if not matched:
            raise LedgerValidationError('周月维护周期格式应为 YYYY-MM，如 2026-10')
        year, month = int(matched.group(1)), int(matched.group(2))
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    else:
        matched = PERIOD_SEASON_RE.match(period)
        if not matched:
            raise LedgerValidationError('季维护周期应为航季：YYYY-夏秋 或 YYYY-冬春，如 2026-夏秋')
        year, season = int(matched.group(1)), matched.group(2)
        if season == '夏秋':
            start = _last_weekday_of_month(year, 3, 6)      # 夏秋航季开始（3月末周日）
            end = _last_weekday_of_month(year, 10, 6)       # 冬春航季开始（10月末周日，开区间）
        else:
            start = _last_weekday_of_month(year, 10, 6)     # 冬春航季开始（10月末周日）
            end = _last_weekday_of_month(year + 1, 3, 6)    # 次年夏秋开始（次年3月末周日，开区间）
    return period, start, end


SEASON_TEXT_MAP = {'夏秋': '夏秋季', '冬春': '冬春季'}


def maintenance_period_text(ledger_type, period):
    """周期展示文本：2026-10 → 2026年10月；2026-夏秋 → 2026年夏秋季。"""
    if ledger_type == LEDGER_TYPE_SEASONAL:
        year, season = period.split('-')
        return '%s年%s' % (year, SEASON_TEXT_MAP.get(season, season))
    year, month = period.split('-')
    return '%s年%d月' % (year, int(month))


def ledger_period_key(ledger):
    """台账归属周期：优先表头维护周期标记，历史台账按实际执行日期推导。"""
    if ledger.maintenance_period:
        return ledger.maintenance_period
    executed = ledger.executed_date
    if ledger.ledger_type == LEDGER_TYPE_SEASONAL:
        # 按航季边界推导：夏秋=3月末周日~10月末周日；冬春=10月末周日~次年3月末周日
        summer_start = _last_weekday_of_month(executed.year, 3, 6)
        winter_start = _last_weekday_of_month(executed.year, 10, 6)
        if summer_start <= executed < winter_start:
            return '%04d-夏秋' % executed.year
        if executed >= winter_start:
            return '%04d-冬春' % executed.year
        # 1~3月中属于上一年10月末开始的冬春航季
        return '%04d-冬春' % (executed.year - 1)
    return executed.strftime('%Y-%m')


def _system_has_period_ledger(user, ledger_type, system_id, period, start, end):
    """同类型同周期同系统是否已存在有效台账（作废不占名额）。

    两条命中路径：
    - 周期标记命中：表头 system + maintenance_period 完全一致（批量新增的草稿壳）；
    - 历史台账命中：表头 system 或明细 system 关联该系统，且实际执行日期
      落在周期范围内（历史台账无周期标记，按执行日期保守判定）。
    """
    query = apply_tenant_filter(OperationLedger.objects.all(), user).filter(
        ledger_type=ledger_type,
    ).exclude(status=LEDGER_STATUS_VOID)
    in_range = Q(executed_date__gte=start, executed_date__lt=end)
    linked_system = Q(system_id=system_id) | Q(items__system_id=system_id)
    return query.filter(
        Q(system_id=system_id, maintenance_period=period)
        | (Q(maintenance_period='') & in_range & linked_system)
    ).exists()


@transaction.atomic
def batch_create_period_ledgers(user, body):
    """一键新增某类型某周期的全部在用系统台账，返回 (result, None) 或 (None, error)。

    每个在用系统创建一张表头级草稿台账（无明细，补录走既有编辑入口）；
    已存在有效台账的系统跳过。created/existed 由调用方原样展示。
    """
    try:
        period, start, end = parse_maintenance_period(
            body.get('ledger_type'), body.get('period'))
    except LedgerValidationError as e:
        return None, str(e)
    ledger_type = body['ledger_type']
    systems = list(apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(
        is_active=True).order_by('system_code', 'id'))
    if not systems:
        return None, '没有在用系统，无法批量新增台账'
    executed_date = timezone.now().date()
    created, existed_systems = [], []
    for system in systems:
        if _system_has_period_ledger(user, ledger_type, system.id, period, start, end):
            existed_systems.append(system.name)
            continue
        ledger = OperationLedger(
            tenant_id=user.tenant_id,
            ledger_no=generate_ledger_no(user.tenant_id, ledger_type, executed_date),
            ledger_type=ledger_type,
            executed_date=executed_date,
            status=LEDGER_STATUS_DRAFT,
            entry_channel=ENTRY_CHANNEL_WEB,
            created_from=LEDGER_FROM_MANUAL,
            system=system,
            maintenance_period=period,
            created_by=user,
        )
        ledger.save()
        created.append(ledger)
    return {
        'ledger_type': ledger_type,
        'maintenance_period': period,
        'period_text': maintenance_period_text(ledger_type, period),
        'created': len(created),
        'existed': len(existed_systems),
        'created_ledgers': [
            {'id': item.id, 'ledger_no': item.ledger_no,
             'system_id': item.system_id, 'system_name': item.system.name}
            for item in created],
        'existed_systems': existed_systems,
    }, None


def list_period_groups(user, ledger_type, status='', system_id=None, row_serializer=None):
    """按周期分组返回台账列表（组内含各系统台账与填写状态）。

    - 分组键 = 维护类型 + 周期（周期优先取表头标记，历史台账按执行日期推导）；
    - status/system 支持筛选；system 命中表头级系统或明细系统；
    - row_serializer(ledger) 由视图层注入（来源字段等展示附加信息）；
    - 组按周期倒序，组内按系统名（空系统靠后）+ID 排序。
    """
    validate_ledger_type(ledger_type)
    query = apply_tenant_filter(OperationLedger.objects.all(), user).filter(
        ledger_type=ledger_type).select_related('system', 'excel_record__version')
    if status:
        query = query.filter(status=status)
    if system_id and str(system_id).isdigit():
        query = query.filter(
            Q(items__system_id=system_id) | Q(system_id=system_id)).distinct()
    ledgers = list(query)
    count_map = {
        row['ledger_id']: row for row in OperationLedgerItem.objects.filter(
            ledger_id__in=[item.id for item in ledgers],
        ).values('ledger_id').annotate(
            items_count=Count('id'),
            abnormal_count=Count('id', filter=Q(result=ITEM_RESULT_ABNORMAL)),
        )
    } if ledgers else {}
    grouped = {}
    for ledger in ledgers:
        view = ledger.to_view()
        count = count_map.get(ledger.id)
        view['items_count'] = count['items_count'] if count else 0
        view['abnormal_count'] = count['abnormal_count'] if count else 0
        if row_serializer is not None:
            view.update(row_serializer(ledger))
        grouped.setdefault(ledger_period_key(ledger), []).append(view)
    data = []
    for key in sorted(grouped, reverse=True):
        rows = grouped[key]
        rows.sort(key=lambda r: (not r['system_name'], r['system_name'], r['id']))
        data.append({
            'maintenance_period': key,
            'period_text': maintenance_period_text(ledger_type, key),
            'total': len(rows),
            'pending': sum(1 for r in rows if r['status'] == LEDGER_STATUS_DRAFT),
            'filled': sum(1 for r in rows if r['status'] in (LEDGER_STATUS_SUBMITTED, LEDGER_STATUS_REVIEWED)),
            'ledgers': rows,
        })
    return data

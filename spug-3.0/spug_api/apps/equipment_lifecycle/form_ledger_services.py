# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——数字表单路线台账服务（2026-10-21）。

职责与 excel_ledger_services.py 同构：按已发布数字表单版本创建正式台账
（表头 + 填写记录一次写入）、保存填写值、完成填写、详情回放。

- 台账表头复用正式 OperationLedger（created_from=form_template，
  source_form_template 指回模板），编号/状态机/作废/删除/附件/审计由
  既有通用模块承载；本模块只承载表单路线专属部分；
- 填写值协议（values JSON）：普通字段以 field_id 为键；normal_abnormal
  字段的异常说明以 `<field_id>__desc` 为键；可重复明细组以组 id 为键、
  值为行数组（每行为 {field_id: 值}，行标识 `_rid`）；矩阵组以组 id 为
  键、值为 {行id: {列id: 值}}；未知键显式拒绝，防止结构漂移；
- 创建台账固定引用模板当前在用版本（行锁复核最新 version_no，与发布
  串行化），发布新版本不回溯历史台账；
- 完成填写做必填终验（普通字段 + 明细组行内字段；矩阵单元格不做必填，
  但"异常时说明必填"覆盖矩阵行）：历史 v1 快照无 require_desc_when_abnormal
  键即不启用，终验口径随创建时版本固定不漂移；
  保存接口做结构校验，完成接口只补必填终验。

业务错误统一抛 FormLedgerError，View 层转业务错误响应。
"""
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle import form_template_manage
from apps.equipment_lifecycle.form_models import OperationLedgerFormRecord
from apps.equipment_lifecycle.form_template_manage import (
    DESC_SUFFIX,
    FIELD_CHOICE,
    FIELD_DATE,
    FIELD_NORMAL_ABNORMAL,
    FIELD_NUMBER,
    GROUP_KIND_FIELDS,
    GROUP_KIND_MATRIX,
    GROUP_KIND_REPEAT,
    NORMAL_ABNORMAL_VALUES,
)
from apps.equipment_lifecycle.ledger_services import (
    EXECUTOR_FIELD_REMOVED_ERROR,
    LedgerValidationError,
    _validate_expected_version,
    create_ledger_row_with_no_retry,
    generate_ledger_no,
)
from apps.equipment_lifecycle.models import (
    ENTRY_CHANNEL_WEB,
    LEDGER_FROM_FORM,
    LEDGER_STATUS_DRAFT,
    LEDGER_STATUS_COMPLETED,
    LEDGER_STATUS_VOID,
    OperationLedger,
    OperationLedgerCorrection,
)

EDITABLE_STATUSES = {LEDGER_STATUS_DRAFT}

# 明细组行数上限（防滥用；超出显式拒绝）
MAX_REPEAT_ROWS = 200
MAX_DESC_LENGTH = 500


class FormLedgerError(Exception):
    """数字表单台账业务校验错误（View 层转业务错误响应）。"""


def _fail(message):
    raise FormLedgerError(message)


def _canonical(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))


def get_form_ledger(pk, user, for_update=False):
    """按租户取数字表单路线台账（须存在填写记录）；其他路线按不存在处理。"""
    query = apply_tenant_filter(
        OperationLedger.objects.filter(created_from=LEDGER_FROM_FORM), user)
    if for_update:
        query = query.select_for_update()
    return query.select_related('form_record__version__template') \
        .filter(pk=pk).first()


def _type_label(ledger_type):
    return {'week_month': '周月维护', 'seasonal': '季维护'}.get(ledger_type, ledger_type)


def create_ledger(user, body):
    """按已发布数字表单模板版本创建台账（表头 + 填写记录一次写入）。

    client_token 命中同租户已有台账时直接返回该台账（创建防重复）。
    返回 (ledger, None) 或 (None, error_message)。
    """
    version = form_template_manage.get_version(body.get('version_id'), user)
    if version is None:
        return None, '模板版本不存在或未发布'
    template = version.template
    if template is None or not template.is_active:
        return None, '模板已停用，不能用于新台账'
    requested_type = body.get('ledger_type')
    if requested_type and requested_type != template.ledger_type:
        return None, '模板「%s」为%s模板，与所选台账类型不一致' % (
            template.name, _type_label(template.ledger_type))
    client_token = str(body.get('client_token') or '')[:64]
    if client_token:
        exists = apply_tenant_filter(OperationLedger.objects.all(), user) \
            .filter(client_token=client_token).first()
        if exists:
            return exists, None
    if 'executor_names' in body:
        return None, EXECUTOR_FIELD_REMOVED_ERROR
    try:
        ledger = _create_ledger_row(user, template, version, client_token)
    except (FormLedgerError, LedgerValidationError) as e:
        return None, str(e)
    return ledger, None


@transaction.atomic
def _create_ledger_row(user, template, version, client_token):
    """行锁模板并复核版本仍是当前在用版本（与 publish 串行化，同 Excel 路线）。"""
    locked = form_template_manage.get_form_template(template.pk, user, for_update=True)
    if locked is None:
        _fail('模板不存在或已删除，不能用于新台账')
    current_no = locked.versions.aggregate(max_no=Max('version_no'))['max_no'] or 0
    if version.version_no != current_no:
        _fail('模板「%s」当前在用版本为 v%s，您提交的 v%s 已不是当前版本，'
              '不能用于新台账；如需采用旧版内容，请基于旧版内容发布新版本'
              % (locked.name, current_no, version.version_no))
    def _build_row(locked=False):
        # 编号生成 + 台账/填写记录落库包保存点重试（并发同号按唯一约束
        # 冲突重算序号，见 ledger_services.create_ledger_row_with_no_retry）
        ledger = OperationLedger(
            tenant_id=user.tenant_id,
            ledger_no=generate_ledger_no(
                user.tenant_id, template.ledger_type, timezone.now().date(),
                locked=locked),
            ledger_type=template.ledger_type,
            status=LEDGER_STATUS_DRAFT,
            entry_channel=ENTRY_CHANNEL_WEB,
            created_from=LEDGER_FROM_FORM,
            source_form_template=template,
            client_token=client_token,
            created_by=user,
        )
        ledger.save()
        OperationLedgerFormRecord.objects.create(
            tenant_id=user.tenant_id,
            ledger=ledger,
            version=version,
            values=_canonical({}),
        )
        return ledger

    return create_ledger_row_with_no_retry(_build_row)


def _require_record(ledger):
    record = getattr(ledger, 'form_record', None)
    if record is None:
        _fail('台账缺少数字表单填写记录')
    return record


# ======================================================================
# 填写值校验
# ======================================================================

def _is_empty(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _normalize_text(raw, label):
    if _is_empty(raw):
        return ''
    if not isinstance(raw, (str, int, float)):
        _fail('%s填写值格式不正确' % label)
    return str(raw).strip()


def _decimal_places(raw):
    """填写值的小数位数（尾随零不计精度：1.50 与 1.5 同为 1 位）。

    经 Decimal 规范化判定，科学计数法/整数值同样适用；无法解析时返回 0
    （随后的 float 转换会给出明确错误）。
    """
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return 0
    if not value.is_finite():
        return 0
    exponent = value.normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def _normalize_number(raw, label, field=None):
    if _is_empty(raw):
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        _fail('%s填写值必须为数字' % label)
    try:
        number = float(raw)
    except (TypeError, ValueError):
        _fail('%s填写值必须为数字' % label)
    if number != number or number in (float('inf'), float('-inf')):
        _fail('%s填写值必须为有限数字' % label)
    if field is not None:
        # 协议 v2 数字属性（历史 v1 快照无这些键=不限制，语义不漂移）
        minimum = field.get('min')
        maximum = field.get('max')
        if minimum is not None and number < float(minimum):
            _fail('%s填写值不能小于 %s' % (label, minimum))
        if maximum is not None and number > float(maximum):
            _fail('%s填写值不能大于 %s' % (label, maximum))
        precision = field.get('precision')
        if precision is not None and _decimal_places(raw) > int(precision):
            _fail('%s填写值小数位不能超过 %d 位' % (label, int(precision)))
    return number


def _normalize_date(raw, label):
    if _is_empty(raw):
        return ''
    value = str(raw).strip()
    try:
        datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        _fail('%s填写值应为日期（YYYY-MM-DD）' % label)
    return value


def _normalize_choice(raw, label, options):
    if _is_empty(raw):
        return ''
    value = str(raw).strip()
    if value not in options:
        _fail('%s填写值不在候选项范围内' % label)
    return value


def _normalize_normal_abnormal(raw, label):
    if _is_empty(raw):
        return ''
    value = str(raw).strip()
    if value not in NORMAL_ABNORMAL_VALUES:
        _fail('%s填写值应为 正常 或 异常' % label)
    return value


def _normalize_field_value(field, raw, label):
    """按字段类型校验并规范化单个填写值。"""
    field_type = field.get('type')
    if field_type == FIELD_NUMBER:
        return _normalize_number(raw, label, field)
    if field_type == FIELD_DATE:
        return _normalize_date(raw, label)
    if field_type == FIELD_CHOICE:
        return _normalize_choice(raw, label, field.get('options') or [])
    if field_type == FIELD_NORMAL_ABNORMAL:
        return _normalize_normal_abnormal(raw, label)
    # text / textarea（未知类型已在结构校验拦截，此处兜底按文本）
    return _normalize_text(raw, label)


def _normalize_desc(raw, label):
    if _is_empty(raw):
        return ''
    if not isinstance(raw, (str, int, float)):
        _fail('%s异常说明格式不正确' % label)
    value = str(raw).strip()
    if len(value) > MAX_DESC_LENGTH:
        _fail('%s异常说明不能超过%d个字' % (label, MAX_DESC_LENGTH))
    return value


def _normalize_row(row, group, label):
    """校验明细组单行：只允许行内字段键、异常说明键与行标识。

    异常说明键（<field_id>__desc）仅 normal_abnormal 字段允许（协议 v2 收紧）。
    """
    if not isinstance(row, dict):
        _fail('%s格式不正确' % label)
    normalized = {}
    allowed = {field['id'] for field in group['fields']}
    for key, raw in row.items():
        if key == '_rid':
            rid = _normalize_text(raw, '%s行标识' % label)
            if rid:
                normalized['_rid'] = rid
            continue
        is_desc = str(key).endswith(DESC_SUFFIX)
        field_id = str(key)[:-len(DESC_SUFFIX)] if is_desc else str(key)
        if field_id not in allowed:
            _fail('%s包含未知字段：%s' % (label, key))
        name = '%s「%s」' % (label, _field_name_of(group, field_id))
        if is_desc:
            _check_desc_allowed(group, field_id, name)
            normalized[key] = _normalize_desc(raw, name)
        else:
            normalized[key] = _normalize_field_value(
                _field_of(group, field_id), raw, name)
    return normalized


def _check_desc_allowed(group, field_id, name):
    """异常说明键仅限 normal_abnormal 字段/矩阵行（不适用键明确拒绝）。"""
    field = _field_of(group, field_id)
    if field.get('type') != FIELD_NORMAL_ABNORMAL:
        _fail('%s不是正常/异常字段，不支持异常说明' % name)


def _field_of(group, field_id):
    for field in group['fields']:
        if field['id'] == field_id:
            return field
    return {'type': '', 'options': []}


def _field_name_of(group, field_id):
    for field in group['fields']:
        if field['id'] == field_id:
            return field['name']
    return field_id


def _normalize_matrix(matrix, group, label):
    """校验矩阵组填写值：{行id: {列id 或 列id__desc: 值}}。

    异常说明键仅允许出现在 type=normal_abnormal 的行（协议 v2 收紧，与
    明细组/普通字段同口径；单元格类型来源于所在行）。
    """
    if not isinstance(matrix, dict):
        _fail('%s格式不正确' % label)
    row_ids = {row['id'] for row in group['fields']}
    col_ids = {column['id'] for column in group.get('columns') or []}
    normalized = {}
    for row_id, cells in matrix.items():
        if row_id not in row_ids:
            _fail('%s包含未知矩阵行：%s' % (label, row_id))
        if not isinstance(cells, dict):
            _fail('%s矩阵行格式不正确' % label)
        row_name = '%s「%s」' % (label, _field_name_of(group, row_id))
        normalized_row = {}
        for key, raw in cells.items():
            is_desc = str(key).endswith(DESC_SUFFIX)
            col_id = str(key)[:-len(DESC_SUFFIX)] if is_desc else str(key)
            if col_id not in col_ids:
                _fail('%s包含未知矩阵列：%s' % (row_name, key))
            col_name = next(
                (c['name'] for c in group['columns'] if c['id'] == col_id), col_id)
            cell_label = '%s「%s」' % (row_name, col_name)
            if is_desc:
                _check_desc_allowed(group, row_id, cell_label)
                normalized_row[key] = _normalize_desc(raw, cell_label)
            else:
                normalized_row[key] = _normalize_field_value(
                    _field_of(group, row_id), raw, cell_label)
        normalized[row_id] = normalized_row
    return normalized


def _index_form_groups(form):
    """表单结构索引：明细组/矩阵组按组 id，普通组字段按字段 id。"""
    repeat_groups = {}
    matrix_groups = {}
    plain_fields = {}
    for group in form.get('groups') or []:
        if group['kind'] == GROUP_KIND_REPEAT:
            repeat_groups[group['id']] = group
        elif group['kind'] == GROUP_KIND_MATRIX:
            matrix_groups[group['id']] = group
        else:
            for field in group['fields']:
                plain_fields[field['id']] = (field, group)
    return repeat_groups, matrix_groups, plain_fields


def _normalize_repeat_values(raw, group):
    """明细组填写值：行数组，逐行校验（行数上限防滥用）。"""
    label = '分组「%s」' % group['name']
    if not isinstance(raw, list):
        _fail('%s填写值应为明细行数组' % label)
    if len(raw) > MAX_REPEAT_ROWS:
        _fail('%s明细行数不能超过%d条' % (label, MAX_REPEAT_ROWS))
    return [_normalize_row(row, group, '%s第%d条' % (label, index))
            for index, row in enumerate(raw, 1)]


def _normalize_plain_desc(raw, field, group):
    return _normalize_desc(
        raw, '分组「%s」字段「%s」' % (group['name'], field['name']))


def validate_form_values(form, values):
    """全量校验填写值并返回规范化 dict（未知键拒绝；不校验必填）。

    顶层键分派（与前端 FormLedgerStore 编辑动作写入的形态一致）：
    - 明细组组 id → 行数组；矩阵组组 id → {行id: {列id: 值}}；
    - 普通分组字段的 field_id → 字段值；`<field_id>__desc` → 异常说明
      （仅 normal_abnormal 字段允许）；
    - 未知键显式拒绝，防止结构漂移。
    必填校验只在完成填写时执行（草稿允许必填未填完），见 missing_required_labels。
    """
    if values is None:
        values = {}
    if not isinstance(values, dict):
        _fail('填写值格式不正确')
    repeat_groups, matrix_groups, plain_fields = _index_form_groups(form)
    normalized = {}
    for key, raw in values.items():
        if key in repeat_groups:
            normalized[key] = _normalize_repeat_values(raw, repeat_groups[key])
        elif key in matrix_groups:
            normalized[key] = _normalize_matrix(
                raw, matrix_groups[key], '分组「%s」' % matrix_groups[key]['name'])
        elif key.endswith(DESC_SUFFIX):
            normalized[key] = _dispatch_plain_desc(
                key, raw, plain_fields)
        elif key in plain_fields:
            field, group = plain_fields[key]
            normalized[key] = _normalize_field_value(
                field, raw, '分组「%s」字段「%s」' % (group['name'], field['name']))
        else:
            _fail('填写值包含未知字段或分组：%s' % key)
    return normalized


def _dispatch_plain_desc(key, raw, plain_fields):
    """顶层异常说明键：仅普通分组的 normal_abnormal 字段允许。"""
    field_id = key[:-len(DESC_SUFFIX)]
    if field_id not in plain_fields \
            or plain_fields[field_id][0]['type'] != FIELD_NORMAL_ABNORMAL:
        _fail('填写值包含未知字段或分组：%s' % key)
    field, group = plain_fields[field_id]
    return _normalize_plain_desc(raw, field, group)


def _desc_required_missing(field, value, desc):
    """异常时说明必填（协议 v2 require_desc_when_abnormal）：值=异常 且
    规则开启 且说明为空 → 记入缺失清单；历史 v1 快照无该键=不启用。"""
    return (field.get('type') == FIELD_NORMAL_ABNORMAL
            and field.get('require_desc_when_abnormal')
            and value == 'abnormal'
            and _is_empty(desc))


def _missing_labels_fields_group(group, values):
    """普通分组：必填值 + 异常说明必填。"""
    missing = []
    for field in group['fields']:
        if field.get('required') and _is_empty(values.get(field['id'])):
            missing.append('%s / %s' % (group['name'], field['name']))
        if _desc_required_missing(field, values.get(field['id']),
                                  values.get(field['id'] + DESC_SUFFIX)):
            missing.append('%s / %s 异常说明未填写'
                           % (group['name'], field['name']))
    return missing


def _missing_labels_repeat_group(group, values):
    """明细组：行内必填值 + 行内异常说明必填（空明细组不拦）。"""
    missing = []
    rows = values.get(group['id']) or []
    for index, row in enumerate(rows, 1):
        for field in group['fields']:
            if field.get('required') and _is_empty(row.get(field['id'])):
                missing.append('%s 第%d条 / %s'
                               % (group['name'], index, field['name']))
            if _desc_required_missing(field, row.get(field['id']),
                                      row.get(field['id'] + DESC_SUFFIX)):
                missing.append('%s 第%d条 / %s 异常说明未填写'
                               % (group['name'], index, field['name']))
    return missing


def _missing_labels_matrix_group(group, values):
    """矩阵组：单元格值不做必填（第一版口径）；异常说明必填逐格生效。"""
    missing = []
    matrix = values.get(group['id']) or {}
    for row in group['fields']:
        if not row.get('require_desc_when_abnormal'):
            continue
        cells = matrix.get(row['id']) or {}
        for column in group.get('columns') or []:
            if _desc_required_missing(
                    row, cells.get(column['id']),
                    cells.get(column['id'] + DESC_SUFFIX)):
                missing.append('%s / %s（%s）异常说明未填写'
                               % (group['name'], row['name'], column['name']))
    return missing


_MISSING_BY_KIND = {
    GROUP_KIND_FIELDS: _missing_labels_fields_group,
    GROUP_KIND_REPEAT: _missing_labels_repeat_group,
    GROUP_KIND_MATRIX: _missing_labels_matrix_group,
}


def missing_required_labels(form, values):
    """必填终验：返回未填写的必填项标签列表（空列表=全部通过）。

    - 普通分组字段：required 且值未填；
    - 明细组行内字段：行存在时行内 required 字段必须填写（空明细组不拦）；
    - 矩阵不做单元格必填终验（横向比较内容允许部分填写，第一版口径）；
    - 异常时说明必填（require_desc_when_abnormal）：值=异常 且说明未填，
      覆盖普通字段/明细行内字段/矩阵行三种载体，与前端 collectFillUnits
      同口径；历史 v1 快照无该键即不启用，终验口径随版本固定不漂移。
    """
    missing = []
    for group in form.get('groups') or []:
        handler = _MISSING_BY_KIND.get(group['kind'])
        if handler:
            missing.extend(handler(group, values))
    return missing


# ======================================================================
# 台账动作
# ======================================================================

@transaction.atomic
def update_values(user, pk, values, expected_version=None):
    """保存填写值（整体替换；仅草稿可编辑，完成后修改走更正流程）。

    行锁内重取台账并复查状态（关闭与完成填写/作废并发时"校验后、写入前"
    的 TOCTOU 窗口）；expected_version 携带时做乐观并发校验（与手工路线
    同语义），成功保存后 version+1。返回锁内最新台账对象供视图回显。
    """
    ledger = get_form_ledger(pk, user, for_update=True)
    if not ledger:
        _fail('台账不存在')
    if ledger.status not in EDITABLE_STATUSES:
        _fail('当前状态不允许修改填写值')
    error = _validate_expected_version(ledger, expected_version)
    if error:
        _fail(error)
    record = _require_record(ledger)
    form = record.version.get_form()
    try:
        normalized = validate_form_values(form, values)
    except FormLedgerError as e:
        _fail(str(e))
    record.values = _canonical(normalized)
    record.updated_at = timezone.now()
    record.save(update_fields=['values', 'updated_at'])
    ledger.version += 1
    ledger.save(update_fields=['version'])
    return ledger


@transaction.atomic
def complete_ledger(user, pk):
    """完成填写（流程终点）：草稿 → 已完成；必填终验按创建时版本执行。"""
    ledger = get_form_ledger(pk, user, for_update=True)
    if not ledger:
        return None, '台账不存在'
    record = _require_record(ledger)
    if not ledger.can_transition_to(LEDGER_STATUS_COMPLETED):
        return None, '当前状态不允许完成填写'
    missing = missing_required_labels(record.version.get_form(), record.get_values())
    if missing:
        shown = '、'.join(missing[:10])
        if len(missing) > 10:
            shown += ' 等%d项' % len(missing)
        return None, '必填项未填写：%s' % shown
    ledger.status = LEDGER_STATUS_COMPLETED
    ledger.completed_at = timezone.now()
    ledger.completed_by = user
    ledger.save(update_fields=['status', 'completed_at', 'completed_by'])
    return ledger, None


def ledger_detail(ledger):
    """台账详情：表头 + 版本快照（表单定义）+ 填写值。"""
    record = _require_record(ledger)
    version = record.version
    view = ledger.to_view()
    view['form'] = {
        'record_id': record.id,
        'values': record.get_values(),
        'editable': ledger.status in EDITABLE_STATUSES,
        'voided': ledger.status == LEDGER_STATUS_VOID,
        'version': form_template_manage.version_content_view(version),
    }
    # 更正记录：数字表单台账第一版不提供更正入口，历史数据同构透出
    view['corrections'] = [c.to_view() for c in ledger.corrections.all()]
    return view

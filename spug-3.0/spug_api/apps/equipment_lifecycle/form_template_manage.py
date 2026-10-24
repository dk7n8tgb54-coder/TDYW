# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——数字表单台账模板管理服务（2026-10-21；2026-10-23 P2 协议 v2）。

与 Excel 路线（excel_template_manage.py）平行的独立路线，职责同构：
- 创建模板（名称/类型/适用系统/生成周期）→ 编辑草稿表单 → 发布为不可变
  版本 → 台账创建固定引用发布版本；发布后版本与草稿互不影响，历史台账
  经 OperationLedgerFormRecord 引用创建时版本；
- 表单结构协议（protocol_version=2，2026-10-23 P2 起）：
  {protocol_version, groups: [{id, name, description, kind, item_name,
    columns: [{id, name}], fields: [{id, name, type, required, description,
    unit, options, rows?, min?, max?, precision?, require_desc_when_abnormal?}]}]}
  · kind=fields  普通分组（fields 为字段列表）；
  · kind=repeat  可重复明细组（fields 为单条明细的字段模板，填写值为行数组）；
  · kind=matrix  检查矩阵（fields 为行定义，columns 为列定义/对象）；
  · 字段类型：text/textarea/number/date/choice/normal_abnormal；矩阵行
    支持 text/number/choice/normal_abnormal（多行文本/日期不适合横向比较）；
  · P2 新增可选键（按类型适用，规范化输出仅保留适用键，缺省即 v1 语义）：
    textarea→rows（2~8，默认 2）；number→min/max（可空）与 precision
    （0~3 位小数，可空）；normal_abnormal→require_desc_when_abnormal
    （异常时说明必填，默认否，终验覆盖普通/明细/矩阵行三种载体）；
  · 结构校验各层未知键 fail-closed 拒绝（错误含键名与对象位置），绝不
    静默丢弃；保存接受 v1/v2 输入并统一规范化为 v2（显式保存即升级），
    直接发布存量 v1 草稿被明确拒绝；读取端（版本快照/填写值/PDF）同时
    接受 v1 与 v2 快照，历史台账语义不漂移；
  · id 由前端生成（如 g_xxxxxxxx），发布即固定：台账填写值以这些 id 为键，
    后续模板修改不得改变历史记录的字段含义；
- 发布级校验：结构合法性（validate_form_schema 全量校验）+ 行锁串行递增
  版本号（(template, version_no) 唯一约束兜底）；版本无写路径（405）；
  publish-check 为无状态预检提示（errors/warnings + anchor 定位），不落库、
  不是放行凭证——发布永远在行锁内重新执行全量校验；
- 停用/启用/物理删除语义与 Excel 模板一致（删除仅限未被任何台账引用）；
- 生成配置（适用系统 + 生成周期）直接复用 excel_template_manage 的同构
  服务与校验函数（duck-typed，同一套一模板一系统/周期枚举语义）。

业务错误统一抛 FormTemplateError，View 层转 json_response(error=...)；
FormTemplateError.anchor 为可定位对象（{type, groupId, fieldId?, columnId?}），
publish-check 结构化输出使用，普通 error 响应忽略。
"""
import json
import re

from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone

from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle.excel_models import (
    TEMPLATE_PERIOD_BY_LEDGER_TYPE,
    TEMPLATE_PERIOD_TEXT,
)
from apps.equipment_lifecycle.excel_template_manage import (
    ExcelTemplateError,
    _resolve_template_system,
    _validate_template_period,
    generation_config_options,
    save_generation_config as excel_save_generation_config,
)
from apps.equipment_lifecycle.form_models import (
    OperationLedgerFormTemplate,
    OperationLedgerFormTemplateVersion,
)
from apps.equipment_lifecycle.ledger_services import validate_ledger_type

# 协议版本（2026-10-23 P2：新增 rows/min/max/precision/require_desc_when_abnormal
# 可选键，升为 2；fixed_table 为条件性 P3，届时升 3）。保存接受 1/2 输入并统一
# 规范化为当前版本；>2 的未来版本整体拒绝；发布仅接受 v2 草稿。
PROTOCOL_VERSION = 2
# 读取端兼容的历史协议版本（版本快照按创建时版本解释，不回写）
SUPPORTED_INPUT_VERSIONS = (1, PROTOCOL_VERSION)

# 字段类型（普通字段与明细组字段）
FIELD_TEXT = 'text'
FIELD_TEXTAREA = 'textarea'
FIELD_NUMBER = 'number'
FIELD_DATE = 'date'
FIELD_CHOICE = 'choice'
FIELD_NORMAL_ABNORMAL = 'normal_abnormal'
FIELD_TYPE_VALUES = [
    FIELD_TEXT, FIELD_TEXTAREA, FIELD_NUMBER, FIELD_DATE,
    FIELD_CHOICE, FIELD_NORMAL_ABNORMAL,
]
FIELD_TYPE_TEXT = {
    FIELD_TEXT: '单行文本', FIELD_TEXTAREA: '多行文本', FIELD_NUMBER: '数字',
    FIELD_DATE: '日期', FIELD_CHOICE: '单选', FIELD_NORMAL_ABNORMAL: '正常/异常',
}
# 矩阵行支持的类型（多行文本/日期不适合横向比较，不开放）
MATRIX_ROW_TYPE_VALUES = [FIELD_TEXT, FIELD_NUMBER, FIELD_CHOICE, FIELD_NORMAL_ABNORMAL]

# —— 协议 v2 新增可选键（按字段类型适用；规范化输出仅保留适用键） ——
# 多行文本行数（2~8，缺省 2，与历史渲染一致）
TEXTAREA_ROWS_MIN = 2
TEXTAREA_ROWS_MAX = 8
TEXTAREA_ROWS_DEFAULT = 2
# 数字小数位上限（0=必须整数；None=不限）
NUMBER_PRECISION_MAX = 3

# 各层白名单（未知键 fail-closed 拒绝，防拼写错误/新增键静默丢失）
TOP_LEVEL_KEYS = {'protocol_version', 'groups'}
GROUP_KEYS = {'id', 'name', 'description', 'kind', 'item_name', 'columns', 'fields'}
FIELD_KEYS = {
    'id', 'name', 'type', 'required', 'description', 'unit', 'options',
    'rows', 'min', 'max', 'precision', 'require_desc_when_abnormal',
}
MATRIX_COLUMN_KEYS = {'id', 'name'}

GROUP_KIND_FIELDS = 'fields'
GROUP_KIND_REPEAT = 'repeat'
GROUP_KIND_MATRIX = 'matrix'
GROUP_KIND_VALUES = [GROUP_KIND_FIELDS, GROUP_KIND_REPEAT, GROUP_KIND_MATRIX]

NORMAL_ABNORMAL_VALUES = ['normal', 'abnormal']
# normal_abnormal 字段异常说明键后缀（填写值 JSON 预留分隔符，结构 id 禁含）
DESC_SUFFIX = '__desc'

# 结构规模上限（防滥用；超出显式拒绝，不静默截断）
MAX_GROUPS = 30
MAX_FIELDS_PER_GROUP = 100
MAX_MATRIX_ROWS = 50
MAX_MATRIX_COLUMNS = 20
MAX_CHOICE_OPTIONS = 50
MAX_TOTAL_FIELDS = 500
# 任一矩阵分组列数达到该值 → 整份 PDF 改用 A4 横向
# （方向规则唯一事实源在本模块，form_pdf_service 引用同一常量）
LANDSCAPE_MATRIX_COLUMNS = 6
# 字段总数接近上限的非阻断提醒阈值（publish-check warnings）
NEAR_TOTAL_FIELDS_LIMIT = 450

# 结构 id 规则：字母或数字开头，可含字母/数字/下划线/连字符，2~40 位；
# 禁止下划线开头（内部键）与双下划线（__desc 后缀保留）
_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{1,39}$')


class FormTemplateError(Exception):
    """数字表单模板业务校验错误（View 层转业务错误响应）。

    anchor 为可选的对象定位（{type, groupId, fieldId?, columnId?}，type 与
    前端编辑器 selection 同构），由结构校验在对象层级附加，供 publish-check
    结构化输出点击定位；普通 error 响应忽略该属性。
    """

    def __init__(self, message, anchor=None):
        super().__init__(message)
        self.anchor = anchor


def _fail(message):
    raise FormTemplateError(message)


def _canonical(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))


def _check_id(raw, label, used):
    value = str(raw or '').strip()
    if not _ID_RE.match(value) or '__' in value:
        _fail('%s标识符不合法（2~40位字母/数字/下划线/连字符，且不含双下划线）：%s' % (label, value or '空'))
    if value in used:
        _fail('%s标识符重复：%s' % (label, value))
    used.add(value)
    return value


def _check_text(raw, label, max_length, allow_empty=False):
    value = str(raw or '').strip()
    if not value:
        if allow_empty:
            return ''
        _fail('%s不能为空' % label)
    if len(value) > max_length:
        _fail('%s不能超过%d个字' % (label, max_length))
    return value


def _reject_unknown_keys(raw, allowed, label):
    """各层白名单校验：未知键显式拒绝（错误含键名与对象位置），不静默丢弃。"""
    if not isinstance(raw, dict):
        return
    unknown = sorted(str(key) for key in raw if key not in allowed)
    if unknown:
        _fail('%s存在未知属性：%s' % (label, '、'.join(unknown)))


def _check_int_in(raw, low, high, label, default=None):
    """可选整数值校验：None 走缺省；非法类型/越界显式拒绝。"""
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        _fail('%s必须为整数' % label)
    if raw < low or raw > high:
        _fail('%s必须在%d~%d之间' % (label, low, high))
    return raw


def _validate_field(raw, used_ids, matrix_row=False, group_anchor=None):
    """校验并规范化单个字段（矩阵组内为行定义）。

    协议 v2：textarea→rows；number→min/max/precision；
    normal_abnormal→require_desc_when_abnormal。不适用键出现在输入中即
    拒绝（None/False 视为无值放行），规范化输出仅保留适用键——切换字段
    类型时的属性清理由前端执行、后端同样约束。
    """
    if not isinstance(raw, dict):
        _fail('字段定义格式不正确')
    field_name = str(raw.get('name') or '').strip() or '未命名'
    scope = '检查项' if matrix_row else '字段'
    label = '%s「%s」' % (scope, field_name)
    _reject_unknown_keys(raw, FIELD_KEYS, label)
    try:
        field = {
            'id': _check_id(raw.get('id'), scope, used_ids),
            'name': _check_text(raw.get('name'), '%s名称' % scope, 100),
            'type': str(raw.get('type') or '').strip(),
            'required': bool(raw.get('required')),
            'description': _check_text(
                raw.get('description'), '%s说明' % scope, 200, allow_empty=True),
            'unit': _check_text(raw.get('unit'), '单位', 20, allow_empty=True),
            'options': [],
        }
        allowed = MATRIX_ROW_TYPE_VALUES if matrix_row else FIELD_TYPE_VALUES
        if field['type'] not in allowed:
            _fail('%s类型不合法：%s' % (label, field['type'] or '空'))
        if field['type'] == FIELD_CHOICE:
            field['options'] = _validate_field_options(raw, field, scope)
        _validate_field_type_attrs(field, raw, label)
        return field
    except FormTemplateError as e:
        if e.anchor is None and group_anchor and raw.get('id'):
            e.anchor = dict(group_anchor,
                            type='matrixRow' if matrix_row else 'field',
                            fieldId=str(raw['id']))
        raise


def _validate_field_options(raw, field, scope):
    """单选字段候选项校验（非空、去重、数量上限）。"""
    options = raw.get('options')
    if not isinstance(options, list) or not options:
        _fail('单选%s「%s」至少配置一个选项' % (scope, field['name']))
    if len(options) > MAX_CHOICE_OPTIONS:
        _fail('单选%s「%s」选项不能超过%d个'
              % (scope, field['name'], MAX_CHOICE_OPTIONS))
    normalized = []
    for option in options:
        text = _check_text(option, '候选项', 100)
        if text in normalized:
            _fail('单选%s「%s」存在重复选项：%s' % (scope, field['name'], text))
        normalized.append(text)
    return normalized


def _validate_field_type_attrs(field, raw, label):
    """协议 v2 类型化属性校验（适用键校验取值，不适用键出现即拒绝）。"""
    field_type = field['type']
    if field_type == FIELD_TEXTAREA:
        field['rows'] = _check_int_in(
            raw.get('rows'), TEXTAREA_ROWS_MIN, TEXTAREA_ROWS_MAX,
            '%s多行文本行数（rows）' % label, default=TEXTAREA_ROWS_DEFAULT)
    elif raw.get('rows') is not None:
        _fail('%s类型不支持多行文本行数（rows）配置' % label)
    if field_type == FIELD_NUMBER:
        _validate_number_attrs(field, raw, label)
    elif any(raw.get(key) is not None for key in ('min', 'max', 'precision')):
        _fail('%s类型不支持数值范围/小数位（min/max/precision）配置' % label)
    _validate_abnormal_attrs(field, raw, label)


def _validate_number_attrs(field, raw, label):
    """number 字段的 min/max/precision 校验（None=不限）。"""
    field['min'] = _check_number_bound(raw.get('min'), '%s最小值（min）' % label)
    field['max'] = _check_number_bound(raw.get('max'), '%s最大值（max）' % label)
    if field['min'] is not None and field['max'] is not None \
            and field['min'] > field['max']:
        _fail('%s最小值不能大于最大值' % label)
    field['precision'] = _check_int_in(
        raw.get('precision'), 0, NUMBER_PRECISION_MAX,
        '%s小数位（precision）' % label)


def _validate_abnormal_attrs(field, raw, label):
    """normal_abnormal 字段的 require_desc_when_abnormal 校验（默认否）。"""
    require_desc = raw.get('require_desc_when_abnormal')
    if field['type'] == FIELD_NORMAL_ABNORMAL:
        if require_desc not in (None, False, True):
            _fail('%s异常时说明必填（require_desc_when_abnormal）应为布尔值' % label)
        field['require_desc_when_abnormal'] = bool(require_desc)
    elif require_desc not in (None, False):
        _fail('%s类型不支持异常时说明必填（require_desc_when_abnormal）配置' % label)


def _check_number_bound(raw, label):
    """数字范围边界值校验：None=不限；仅接受有限数值。"""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        _fail('%s必须为数字' % label)
    value = float(raw)
    if value != value or value in (float('inf'), float('-inf')):
        _fail('%s必须为有限数字' % label)
    return value


def _validate_group(raw_group, used_ids):
    """校验并规范化单个分组（fields/repeat/matrix 三类各自的子结构）。"""
    if not isinstance(raw_group, dict):
        _fail('分组定义格式不正确')
    group_name = str(raw_group.get('name') or '').strip() or '未命名'
    _reject_unknown_keys(
        raw_group, GROUP_KEYS, '分组「%s」' % group_name)
    kind = str(raw_group.get('kind') or '').strip()
    if kind not in GROUP_KIND_VALUES:
        _fail('分组「%s」类型不合法：%s' % (group_name, kind or '空'))
    try:
        normalized = {
            'id': _check_id(raw_group.get('id'), '分组', used_ids),
            'name': _check_text(raw_group.get('name'), '分组名称', 60),
            'description': _check_text(
                raw_group.get('description'), '分组说明', 200, allow_empty=True),
            'kind': kind,
            'item_name': '',
            'columns': [],
            'fields': [],
        }
        group_anchor = {'type': 'group', 'groupId': normalized['id']}
        if kind == GROUP_KIND_REPEAT:
            normalized['item_name'] = _check_text(
                raw_group.get('item_name') or '明细条目', '明细条目名称', 30)
        if kind == GROUP_KIND_MATRIX:
            normalized['columns'] = _validate_matrix_columns(
                raw_group, normalized, group_anchor, used_ids)
        normalized['fields'] = _validate_group_fields(
            raw_group, normalized, kind, group_anchor, used_ids)
        return normalized
    except FormTemplateError as e:
        if e.anchor is None and raw_group.get('id'):
            e.anchor = {'type': 'group', 'groupId': str(raw_group['id'])}
        raise


def _validate_matrix_columns(raw_group, normalized_group, group_anchor, used_ids):
    """矩阵组的列（对比对象）校验。"""
    group_name = normalized_group['name']
    columns = raw_group.get('columns')
    if not isinstance(columns, list) or not columns:
        _fail('矩阵分组「%s」至少配置一个列（对比对象）' % group_name)
    if len(columns) > MAX_MATRIX_COLUMNS:
        _fail('矩阵分组「%s」列数不能超过%d' % (group_name, MAX_MATRIX_COLUMNS))
    normalized = []
    for column in columns:
        if not isinstance(column, dict):
            _fail('矩阵列定义格式不正确')
        try:
            _reject_unknown_keys(
                column, MATRIX_COLUMN_KEYS,
                '矩阵列「%s」（分组「%s」）'
                % (str(column.get('name') or '').strip() or '未命名', group_name))
            normalized.append({
                'id': _check_id(column.get('id'), '矩阵列', used_ids),
                'name': _check_text(column.get('name'), '矩阵列名称', 30),
            })
        except FormTemplateError as e:
            if e.anchor is None and column.get('id'):
                e.anchor = dict(group_anchor, type='matrixColumn',
                                columnId=str(column['id']))
            raise
    return normalized


def _validate_group_fields(raw_group, normalized_group, kind, group_anchor, used_ids):
    """组内字段（矩阵组即行定义）校验。"""
    name = normalized_group['name']
    rows = raw_group.get('fields')
    if not isinstance(rows, list) or not rows:
        _fail('分组「%s」至少配置一个字段' % name)
    if len(rows) > MAX_FIELDS_PER_GROUP:
        _fail('分组「%s」字段数量不能超过%d个' % (name, MAX_FIELDS_PER_GROUP))
    return [_validate_field(row, used_ids, matrix_row=(kind == GROUP_KIND_MATRIX),
                            group_anchor=group_anchor)
            for row in rows]


def validate_form_schema(data):
    """全量校验表单定义，返回规范化后的 dict（不合法抛 FormTemplateError）。

    校验覆盖：协议版本、各层未知键白名单（fail-closed）、分组数量与类型、
    结构 id 全局唯一、字段类型/选项/长度上限、v2 类型化属性、矩阵行列规模；
    规范化的 dict 即发布快照内容。保存端接受 v1/v2 输入并统一规范化为
    当前版本（显式保存即升级）；未来版本整体拒绝，绝不静默丢键。
    """
    if not isinstance(data, dict):
        _fail('表单定义格式不正确')
    _reject_unknown_keys(data, TOP_LEVEL_KEYS, '表单定义')
    if data.get('protocol_version') not in SUPPORTED_INPUT_VERSIONS:
        _fail('表单协议版本不支持（应为 %s）' % PROTOCOL_VERSION)
    groups = data.get('groups')
    if not isinstance(groups, list) or not groups:
        _fail('请至少配置一个分组')
    if len(groups) > MAX_GROUPS:
        _fail('分组数量不能超过%d个' % MAX_GROUPS)
    used_ids = set()
    normalized_groups = [_validate_group(group, used_ids) for group in groups]
    total_fields = sum(
        len(group['fields']) for group in normalized_groups)
    if total_fields > MAX_TOTAL_FIELDS:
        _fail('字段总数不能超过%d个（当前%d个）' % (MAX_TOTAL_FIELDS, total_fields))
    return {'protocol_version': PROTOCOL_VERSION, 'groups': normalized_groups}


def collect_publish_issues(form):
    """发布检查（无状态，不落库、不是放行凭证）：errors=阻断项，warnings=提醒。

    errors 与草稿/发布校验同源（validate_form_schema，含 anchor 对象定位）；
    warnings 为非阻断提醒（normal_abnormal 无检查说明、矩阵列数将触发整份
    横向、字段总数接近上限、明细条目名仍为默认）。发布前必须以行锁内
    重新校验为准，本函数结果仅供编辑器展示与定位。
    """
    if isinstance(form, dict) and form.get('protocol_version') == 1:
        return {'errors': [{
            'code': 'protocol_v1',
            'message': '草稿仍为旧版协议（v1），请重新编辑并保存后再发布'
                       '（保存草稿时自动升级为 v2）',
            'anchor': None,
        }], 'warnings': []}
    try:
        normalized = validate_form_schema(form)
    except FormTemplateError as e:
        return {'errors': [{
            'code': 'schema_invalid',
            'message': str(e),
            'anchor': getattr(e, 'anchor', None),
        }], 'warnings': []}
    warnings = _collect_publish_warnings(normalized)
    return {'errors': [], 'warnings': warnings}


def _collect_publish_warnings(form):
    """非阻断提醒（结构已合法）：逐项携带 anchor 供编辑器点击定位。"""
    warnings = []
    total_fields = 0
    for group in form.get('groups') or []:
        anchor = {'type': 'group', 'groupId': group['id']}
        warnings.extend(_group_kind_warnings(group, anchor))
        total_fields += len(group.get('fields') or [])
        warnings.extend(_abnormal_no_desc_warnings(group, anchor))
    if total_fields >= NEAR_TOTAL_FIELDS_LIMIT:
        warnings.append({
            'code': 'fields_near_limit',
            'message': '字段总数 %d 个，已接近上限 %d 个'
                       % (total_fields, MAX_TOTAL_FIELDS),
            'anchor': None,
        })
    return warnings


def _group_kind_warnings(group, anchor):
    """分组级提醒：明细条目名仍为默认、宽矩阵将整份横向。"""
    items = []
    if group['kind'] == GROUP_KIND_REPEAT \
            and group.get('item_name') == '明细条目':
        items.append({
            'code': 'default_item_name',
            'message': '分组「%s」的明细条目名仍为默认的"明细条目"，'
                       '建议改为业务名称' % group['name'],
            'anchor': anchor,
        })
    columns = group.get('columns') or []
    if group['kind'] == GROUP_KIND_MATRIX and len(columns) >= LANDSCAPE_MATRIX_COLUMNS:
        items.append({
            'code': 'matrix_landscape',
            'message': '分组「%s」矩阵列数达 %d 列，PDF 将整份使用横向纸张'
                       % (group['name'], len(columns)),
            'anchor': anchor,
        })
    return items


def _abnormal_no_desc_warnings(group, anchor):
    """normal_abnormal 项未填写检查说明的提醒（填写人缺少判断依据）。"""
    items = []
    scope = '检查项' if group['kind'] == GROUP_KIND_MATRIX else '字段'
    for field in group.get('fields') or []:
        if field.get('type') != FIELD_NORMAL_ABNORMAL \
                or (field.get('description') or '').strip():
            continue
        items.append({
            'code': 'abnormal_no_desc',
            'message': '%s「%s」（分组「%s」）为正常/异常项但未填写'
                       '检查说明，填写人缺少判断依据'
                       % (scope, field['name'], group['name']),
            'anchor': dict(anchor,
                           type='matrixRow'
                           if group['kind'] == GROUP_KIND_MATRIX else 'field',
                           fieldId=field['id']),
        })
    return items


def count_form_fields(form):
    """可填写字段总数（展示口径）：普通/明细组按字段数，矩阵按 行×列 单元格。"""
    total = 0
    for group in form.get('groups') or []:
        if group.get('kind') == GROUP_KIND_MATRIX:
            total += len(group.get('fields') or []) * len(group.get('columns') or [])
        else:
            total += len(group.get('fields') or [])
    return total


def get_form_template(pk, user, for_update=False):
    """按租户取模板；不存在返回 None（跨租户与不存在不区分，避免探测）。"""
    query = apply_tenant_filter(OperationLedgerFormTemplate.objects.all(), user)
    if for_update:
        query = query.select_for_update()
    return query.select_related('system').filter(pk=pk).first()


def get_version(version_id, user):
    """按租户取已发布版本；不存在返回 None。"""
    query = apply_tenant_filter(OperationLedgerFormTemplateVersion.objects.all(), user)
    return query.select_related('template').filter(pk=version_id).first()


def _template_summary(template, latest_version_no, versions_count, ledgers_count):
    view = template.to_view(latest_version_no=latest_version_no,
                            versions_count=versions_count,
                            ledgers_count=ledgers_count)
    view['template_kind'] = 'form'
    view['generation_period_text'] = TEMPLATE_PERIOD_TEXT.get(
        template.generation_period, template.generation_period or '待配置')
    return view


def list_templates(user):
    query = apply_tenant_filter(OperationLedgerFormTemplate.objects.all(), user)
    query = query.annotate(
        latest_version_no=Max('versions__version_no'),
        versions_count=Count('versions', distinct=True),
        ledgers_count=Count('versions__form_ledger_records', distinct=True))
    return [_template_summary(t, t.latest_version_no or 0, t.versions_count or 0,
                              t.ledgers_count or 0)
            for t in query]


def available_templates(user, ledger_type=None):
    """台账创建用：启用且有已发布版本的模板（可按类型过滤）。

    versions 只含当前在用版本（模板内最大 version_no），与 Excel 路线
    同口径：新增台账固定使用当前版本，旧版本仅供历史追溯。
    """
    query = apply_tenant_filter(
        OperationLedgerFormTemplate.objects.filter(is_active=True), user)
    if ledger_type:
        query = query.filter(ledger_type=ledger_type)
    query = query.annotate(versions_count=Count('versions')).filter(versions_count__gt=0)
    items = []
    for template in query.order_by('id'):
        current = template.versions.first()
        items.append({
            'id': template.id,
            'name': template.name,
            'template_kind': 'form',
            'ledger_type': template.ledger_type,
            'description': template.description,
            'versions': [current.to_view()] if current else [],
        })
    return items


def create_template(user, body):
    """创建数字表单模板容器（不含表单内容，草稿随后编辑）。

    name/ledger_type/description/system/generation_period 校验口径与
    Excel 模板一致（复用同构校验函数）；创建后进入草稿编辑。
    """
    name = _check_text(body.get('name'), '模板名称', 100)
    ledger_type = body.get('ledger_type')
    try:
        validate_ledger_type(ledger_type)
    except Exception as e:
        _fail(str(e))
    description = _check_text(body.get('description'), '模板说明', 500, allow_empty=True)
    # 复用 Excel 同构校验（抛 ExcelTemplateError），统一转为本模块业务错误
    try:
        system = _resolve_template_system(user, body.get('system'))
        generation_period = _validate_template_period(ledger_type, body.get('generation_period'))
    except ExcelTemplateError as e:
        _fail(str(e))
    template = OperationLedgerFormTemplate.objects.create(
        tenant_id=user.tenant_id,
        name=name,
        ledger_type=ledger_type,
        description=description,
        system=system,
        generation_period=generation_period,
        created_by=user,
    )
    return template


def save_draft_form(user, template, form):
    """保存草稿表单定义（全量校验后整体替换；仅启用模板可编辑）。"""
    if not template.is_active:
        _fail('模板已停用，不能编辑表单')
    normalized = validate_form_schema(form)
    template.draft_form = _canonical(normalized)
    template.draft_updated_at = timezone.now()
    template.draft_updated_by = user
    template.updated_at = timezone.now()
    template.updated_by = user
    template.save(update_fields=[
        'draft_form', 'draft_updated_at', 'draft_updated_by',
        'updated_at', 'updated_by'])
    return template


def save_generation_config(user, template, body):
    """保存生成配置（适用系统 + 生成周期）：直接复用 Excel 同构服务
    （模板对象同名字段 duck-typed，校验语义完全一致；ExcelTemplateError
    统一转为本模块业务错误）。"""
    try:
        return excel_save_generation_config(user, template, body)
    except ExcelTemplateError as e:
        _fail(str(e))


@transaction.atomic
def publish_version(user, template):
    """发布：草稿表单快照为不可变版本（发布级校验 + 行锁串行递增版本号）。

    - 必须已有草稿表单；
    - 行锁内重新校验结构与租户归属，版本号 = 模板内最大 version_no + 1
      （同锁串行化，与台账创建的版本复核互斥；(template, version_no)
      唯一约束兜底）；
    - 发布后草稿保留（继续编辑可再发布新版本），历史台账不受影响。
    """
    locked = get_form_template(template.pk, user, for_update=True)
    if locked is None:
        _fail('模板不存在或无权限访问')
    if not locked.is_active:
        _fail('模板已停用，不能发布')
    if not locked.draft_form:
        _fail('请先编辑并保存表单草稿再发布')
    try:
        form = json.loads(locked.draft_form)
    except (ValueError, TypeError):
        _fail('草稿表单内容已损坏，请重新编辑保存后再发布')
    if isinstance(form, dict) and form.get('protocol_version') == 1:
        # 存量 v1 草稿不做发布时静默升级：显式保存一次即转为 v2
        _fail('草稿仍为旧版协议（v1），请重新编辑并保存后再发布')
    # 行锁内重新执行全量校验（publish-check 只是无状态提示，不是放行凭证）
    form = validate_form_schema(form)
    latest_no = locked.versions.aggregate(max_no=Max('version_no'))['max_no'] or 0
    version = OperationLedgerFormTemplateVersion.objects.create(
        tenant_id=locked.tenant_id,
        template=locked,
        version_no=latest_no + 1,
        template_name_snapshot=locked.name,
        form=_canonical(form),
        field_count=count_form_fields(form),
        published_by=user,
    )
    return version


def version_content_view(version):
    """版本内容视图（表单定义快照；台账详情与版本详情接口共用）。"""
    return version.to_view(with_content=True)


def template_detail(template):
    """模板详情：汇总 + 草稿表单 + 草稿与版本内容关系（不做时间推断）。"""
    latest_no = template.versions.aggregate(max_no=Max('version_no'))['max_no'] or 0
    total = template.versions.count()
    ledgers = template.versions.aggregate(
        total=Count('form_ledger_records', distinct=True))['total'] or 0
    view = _template_summary(template, latest_no, total, ledgers)
    view['draft'] = draft_meta_view(template)
    view['draft_state'] = draft_version_state(template)
    return view


def draft_meta_view(template):
    if not template.draft_form:
        return None
    try:
        form = json.loads(template.draft_form)
    except (ValueError, TypeError):
        return None
    updated_by = template.draft_updated_by
    return {
        'form': form if isinstance(form, dict) else {},
        'updated_at': template.draft_updated_at,
        'updated_by': updated_by.nickname if updated_by else '',
        'updated_by_username': updated_by.username if updated_by else '',
    }


def draft_version_state(template):
    """草稿与发布版本的内容关系：identical/modified/no_draft/no_versions。"""
    versions = list(template.versions.all().order_by('-version_no'))
    latest_no = max([v.version_no for v in versions], default=0)
    updated_by = template.draft_updated_by
    state = {
        'latest_version_no': latest_no,
        'versions_count': len(versions),
        'updated_at': template.draft_updated_at,
        'updated_by': updated_by.nickname if updated_by else '',
        'updated_by_username': updated_by.username if updated_by else '',
        'field_count': 0,
        'relation': 'no_draft',
        'based_on_version_no': None,
    }
    if not template.draft_form:
        return state
    try:
        draft = json.loads(template.draft_form)
    except (ValueError, TypeError):
        draft = None
    if not isinstance(draft, dict):
        state['relation'] = 'unknown'
        return state
    state['field_count'] = count_form_fields(draft)
    if not versions:
        state['relation'] = 'no_versions'
        return state
    identical = [v.version_no for v in versions
                 if _canonical(v.get_form()) == _canonical(draft)]
    if identical:
        state['relation'] = 'identical'
        state['based_on_version_no'] = max(identical)
    else:
        state['relation'] = 'modified'
    return state


def deactivate_template(user, template):
    """停用（逻辑停用，幂等）：不能用于新台账，历史版本与台账保留。"""
    if not template.is_active:
        return template
    template.is_active = False
    template.updated_at = timezone.now()
    template.updated_by = user
    template.save(update_fields=['is_active', 'updated_at', 'updated_by'])
    return template


def activate_template(user, template):
    """重新启用（停用逆操作，幂等）。"""
    if template.is_active:
        return template
    template.is_active = True
    template.updated_at = timezone.now()
    template.updated_by = user
    template.save(update_fields=['is_active', 'updated_at', 'updated_by'])
    return template


@transaction.atomic
def destroy_template(user, template):
    """物理删除：仅限未被任何台账引用（含已作废台账）的模板。

    行锁内重新检查引用关系（generated_form_ledgers 台账直接引用 +
    各版本被填写记录引用）；被引用模板只能停用，不提供删除。
    """
    locked = get_form_template(template.pk, user, for_update=True)
    if locked is None:
        _fail('模板不存在或无权限访问')
    if locked.generated_form_ledgers.exists():
        _fail('模板已被台账引用，不能删除，只能停用')
    for version in locked.versions.all():
        if version.form_ledger_records.exists():
            _fail('模板已被台账引用，不能删除，只能停用')
    info = {'id': locked.id, 'name': locked.name,
            'latest_version_no': locked.versions.aggregate(
                max_no=Max('version_no'))['max_no'] or 0}
    locked.delete()
    return info


def sample_form():
    """内置示例表单（"载入示例"数据源）：覆盖全部分组种类与常用字段类型，
    并演示协议 v2 类型化属性（rows/数值范围/小数位/异常说明必填），
    供真实维护场景验证闭环；返回深拷贝，调用方可自由修改。"""
    return {
        'protocol_version': PROTOCOL_VERSION,
        'groups': [
            {
                'id': 'g_baseinfo01',
                'name': '基本信息',
                'description': '本次维护的登记信息',
                'kind': 'fields',
                'fields': [
                    {'id': 'f_maintdate1', 'name': '维护日期', 'type': 'date',
                     'required': True, 'description': '', 'unit': '', 'options': []},
                    {'id': 'f_maintuser1', 'name': '维护人员', 'type': 'text',
                     'required': True, 'description': '多人以顿号分隔', 'unit': '', 'options': []},
                    {'id': 'f_remark001', 'name': '备注', 'type': 'textarea',
                     'required': False, 'description': '', 'unit': '', 'options': [],
                     'rows': 3},
                ],
            },
            {
                'id': 'g_statusche1',
                'name': '设备状态检查',
                'description': '',
                'kind': 'fields',
                'fields': [
                    {'id': 'f_casing0001', 'name': '机壳外观', 'type': 'normal_abnormal',
                     'required': True, 'description': '有无变形、锈蚀、破损',
                     'unit': '', 'options': [], 'require_desc_when_abnormal': True},
                    {'id': 'f_lampstat01', 'name': '指示灯状态', 'type': 'normal_abnormal',
                     'required': True, 'description': '', 'unit': '', 'options': []},
                    {'id': 'f_coolingfan', 'name': '散热风扇', 'type': 'normal_abnormal',
                     'required': False, 'description': '', 'unit': '', 'options': []},
                ],
            },
            {
                'id': 'g_measuremt1',
                'name': '电气参数测量',
                'description': '测量项目数量不固定，按实际增减',
                'kind': 'repeat',
                'item_name': '测量项目',
                'fields': [
                    {'id': 'f_itemname01', 'name': '项目名称', 'type': 'text',
                     'required': True, 'description': '', 'unit': '', 'options': []},
                    {'id': 'f_measvalue1', 'name': '测量值', 'type': 'number',
                     'required': True, 'description': '', 'unit': '', 'options': [],
                     'precision': 2},
                    {'id': 'f_unittext01', 'name': '单位', 'type': 'text',
                     'required': False, 'description': '如 V、A、℃', 'unit': '', 'options': []},
                    {'id': 'f_judgement', 'name': '判断结果', 'type': 'normal_abnormal',
                     'required': True, 'description': '', 'unit': '', 'options': [],
                     'require_desc_when_abnormal': True},
                ],
            },
            {
                'id': 'g_multidev01',
                'name': '多机运行对比',
                'description': 'A 机与 B 机横向比较',
                'kind': 'matrix',
                'columns': [
                    {'id': 'c_devicema', 'name': 'A 机'},
                    {'id': 'c_devicemb', 'name': 'B 机'},
                ],
                'fields': [
                    {'id': 'r_voltage001', 'name': '输出电压', 'type': 'number',
                     'required': False, 'description': '', 'unit': 'V', 'options': [],
                     'min': 0, 'max': 400, 'precision': 1},
                    {'id': 'r_current001', 'name': '输出电流', 'type': 'number',
                     'required': False, 'description': '', 'unit': 'A', 'options': []},
                    {'id': 'r_linkstate', 'name': '通讯状态', 'type': 'normal_abnormal',
                     'required': False, 'description': '', 'unit': '', 'options': [],
                     'require_desc_when_abnormal': True},
                ],
            },
        ],
    }

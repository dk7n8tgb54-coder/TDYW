# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统配置变更服务层（2026-10）。

职责：
- generate_config_change_no：变更编号生成（PZ+日期+当日序号，口径同故障/运行记录）；
- normalize_param_value / canonical_value_text：按参数定义校验并规范化输入值、
  生成类型无关的规范文本（当前值对比与快照的唯一口径）；
- create_config_change / update_draft_change：草稿创建与编辑（后端重新查询
  参数定义与数据库当前值生成快照，不信任前端传入的参数名称/类型/旧值）；
- apply_config_change：应用变更（锁系统行+当前值行 → 校验变更前值未被并发
  覆盖 → upsert 当前配置值 → 主表状态流转 → 重要变更写履历 → 审计由视图层
  同事务写入）；
- verify_config_change / cancel_config_change：验证与取消；
- rollback_config_change：回退（须在编号锁+事务内调用，生成一条新的反向
  变更，不修改/删除原记录内容）；
- validate_param_definition：参数定义维护校验（编码格式、枚举选项、敏感
  配置拒绝）。

约定：
- 配置值只经「创建草稿 → 应用生效」流程写入 SystemParamValue，不提供
  散改接口，也不直接修改系统主数据固定字段（呼号/工作频率等由系统编辑
  接口管理，走系统主数据公开 Service，与本服务无关）；
- 敏感配置（密码/令牌/密钥/私钥）在参数定义层拒绝保存，必要时以外部密钥
  系统的引用编号作为普通文本参数保存；
  须填原因，应用时写入一次履历，回退生成的反向变更继承该标记再写一次
  （回退本身也是一次重要配置变更）；重复动作被状态机拦截，事件不重复；
- 行锁约定：应用/回退对 LifecycleSystem 行 select_for_update 串行化同一
  系统的配置写入，并对涉及的 SystemParamValue 行 select_for_update。
"""
import json
import re
from contextlib import contextmanager
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from django.db import connection
from django.utils import timezone

from apps.equipment_lifecycle.config_models import (
    CONFIG_CHANGE_APPLIED,
    CONFIG_CHANGE_CANCELLED,
    CONFIG_CHANGE_DRAFT,
    CONFIG_CHANGE_NO_PREFIX,
    CONFIG_CHANGE_NO_SEQ_LIMIT,
    CONFIG_CHANGE_ROLLED_BACK,
    CONFIG_CHANGE_VERIFIED,
    CONFIG_VERIFY_FAILED,
    CONFIG_VERIFY_PASSED,
    PARAM_CATEGORY_CHOICES,
    PARAM_CATEGORY_RUNTIME,
    PARAM_CATEGORY_VALUES,
    PARAM_SCOPE_ALL,
    PARAM_SCOPE_SPECIFIC,
    PARAM_TYPE_BOOL,
    PARAM_TYPE_CHOICE,
    PARAM_TYPE_CHOICES,
    PARAM_TYPE_DATE,
    PARAM_TYPE_NUMBER,
    PARAM_TYPE_TEXT,
    ConfigChangeItem,
    ConfigChangeRecord,
    ConfigParamDefinition,
    SystemConfigBaseline,
    SystemParamValue,
)

# 数字值存储精度（与 SystemParamValue.value_number 一致）
NUMBER_MAX_DIGITS = 14
NUMBER_MAX_PLACES = 6

# 敏感配置关键词：参数编码（英文明文）与参数名称（中文）出现即拒绝保存
SENSITIVE_CODE_KEYWORDS = [
    'password', 'passwd', 'pwd', 'token', 'secret', 'private', 'credential',
    'apikey', 'api_key', 'access_key', 'secretkey', 'sign_key',
]
SENSITIVE_NAME_KEYWORDS = ['密码', '口令', '令牌', '密钥', '秘钥', '私钥', '凭证']

PARAM_CODE_PATTERN = re.compile(r'^[a-z][a-z0-9_]{1,49}$')


class ConfigValueError(Exception):
    """参数值/参数定义业务校验失败（由调用方转为业务错误提示）。"""


class ConfigChangeError(Exception):
    """配置变更状态机/并发校验失败（由调用方转为业务错误提示）。"""


class ConfigChangeNoExhausted(Exception):
    """当日变更编号序号已用尽（PZyyyymmdd-9999 已占用）：fail-closed。"""


class ConfigChangeLockTimeout(Exception):
    """变更编号锁获取超时：并发过高时 fail-closed。"""


CONFIG_CHANGE_NO_LOCK_NAME = 'el_config_change_no'
CONFIG_CHANGE_NO_LOCK_TIMEOUT = 10


@contextmanager
def config_change_no_lock():
    """变更编号生成全局串行锁（GET_LOCK，防并发创建/回退撞号）。

    用法（视图层）：事务外取锁 → 事务内完成编号生成 + 写库 → 提交 → 放锁。
    ATOMIC_REQUESTS 下持锁视图以 non_atomic_requests 装配并显式开启事务
    （与故障/运行记录视图的锁提交顺序约定一致）。
    """
    cursor = connection.cursor()
    try:
        cursor.execute('SELECT GET_LOCK(%s, %s)',
                       [CONFIG_CHANGE_NO_LOCK_NAME, CONFIG_CHANGE_NO_LOCK_TIMEOUT])
        got = cursor.fetchone()[0]
        if got != 1:
            raise ConfigChangeLockTimeout('系统繁忙，请稍后重试')
        try:
            yield
        finally:
            try:
                cursor.execute('SELECT RELEASE_LOCK(%s)', [CONFIG_CHANGE_NO_LOCK_NAME])
            except Exception:
                connection.close()
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def generate_config_change_no():
    """生成变更编号 PZ{yyyymmdd}-{seq:04d}（须在创建事务内调用）。

    日期取创建当天；当日序号跨租户共享（有效四位后缀最大值 +1，缺口不回填）；
    序号达上限抛 ConfigChangeNoExhausted，整个创建事务回滚。
    """
    prefix = CONFIG_CHANGE_NO_PREFIX + timezone.now().date().strftime('%Y%m%d') + '-'
    max_seq = 0
    existing = ConfigChangeRecord.objects.filter(change_no__startswith=prefix).values_list(
        'change_no', flat=True)
    for change_no in existing:
        suffix = change_no[len(prefix):]
        if len(suffix) == 4 and suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    if max_seq >= CONFIG_CHANGE_NO_SEQ_LIMIT:
        raise ConfigChangeNoExhausted(
            f'当日配置变更编号已达上限（{prefix}9999），请明日再创建')
    return f'{prefix}{max_seq + 1:04d}'


def _clean(value, limit):
    return (value or '').strip()[:limit]


SENSITIVE_HINT = ('禁止保存密码/令牌/密钥等敏感配置；'
                  '如需关联请保存外部密钥系统的引用编号')


def _match_sensitive_words(code, name):
    lowered = code.lower()
    if any(word in lowered for word in SENSITIVE_CODE_KEYWORDS):
        return '参数编码包含敏感配置关键词，' + SENSITIVE_HINT
    if any(word in name for word in SENSITIVE_NAME_KEYWORDS):
        return '参数名称包含敏感配置关键词，' + SENSITIVE_HINT
    return None


def _validate_choice_options(options):
    clean_options = [str(x).strip() for x in (options or []) if str(x).strip()]
    if len(clean_options) < 2:
        return '枚举类型参数必须提供至少 2 个选项'
    if len(set(clean_options)) != len(clean_options):
        return '枚举选项不能重复'
    return None


def _validate_code_name_category(code, name, category):
    """编码/名称/分类基础校验，返回错误文案或 None。"""
    if not code:
        return '参数编码不能为空'
    if not PARAM_CODE_PATTERN.match(code):
        return '参数编码须为小写字母开头，仅含小写字母/数字/下划线，长度 2-50'
    if not name:
        return '参数名称不能为空'
    if category is not None and category not in PARAM_CATEGORY_VALUES:
        return '参数分类不正确'
    return _match_sensitive_words(code, name)


def validate_param_definition(*, param_code, param_name, data_type, scope_type,
                              options, validation_regex, category=None):
    """参数定义维护校验，返回错误文案或 None。

    - 编码格式固定（小写字母开头，字母/数字/下划线），防止把值塞进编码；
    - 分类必须为 硬件规格/运行参数 之一（未提交时由调用方回落默认值）；
    - 敏感配置（密码/令牌/密钥/私钥等）直接拒绝保存：不允许在配置参数里
      存任何明文凭据，必要时以外部密钥系统的引用编号作为普通文本参数；
    - 枚举类型必须提供 ≥2 个不重复选项；正则仅文本类型可填且必须可编译。
    """
    code = (param_code or '').strip()
    name = (param_name or '').strip()
    basic_error = _validate_code_name_category(code, name, category)
    if basic_error:
        return basic_error
    if data_type == PARAM_TYPE_CHOICE:
        options_error = _validate_choice_options(options)
        if options_error:
            return options_error
    if (validation_regex or '').strip() and data_type != PARAM_TYPE_TEXT:
        return '校验正则仅对文本类型参数生效'
    if scope_type == PARAM_SCOPE_SPECIFIC and not options:
        return '指定系统范围时必须选择至少一个适用系统'
    return None


def _validate_regex_compilable(pattern):
    try:
        re.compile(pattern)
    except re.error:
        raise ConfigValueError('参数校验正则不合法')


def _empty_fields():
    return {'value_text': '', 'value_number': None, 'value_bool': None,
            'value_date': None, 'value_choice': ''}


def _normalize_text(param, raw_value):
    text = _clean(raw_value, 500)
    if len(str(raw_value or '').strip()) > 500:
        raise ConfigValueError(f'参数「{param.param_name}」的值超长（最多 500 字符）')
    pattern = (param.validation_regex or '').strip()
    if pattern:
        _validate_regex_compilable(pattern)
        if text and not re.fullmatch(pattern, text):
            raise ConfigValueError(f'参数「{param.param_name}」的值不符合校验规则')
    fields = _empty_fields()
    fields['value_text'] = text
    return fields


def _normalize_number(param, raw_value):
    if raw_value is None or str(raw_value).strip() == '':
        return _empty_fields()
    try:
        number = Decimal(str(raw_value).strip())
    except (InvalidOperation, ValueError):
        raise ConfigValueError(f'参数「{param.param_name}」必须是数字')
    if not number.is_finite():
        raise ConfigValueError(f'参数「{param.param_name}」必须是有效数字')
    exponent = -number.as_tuple().exponent
    if exponent > NUMBER_MAX_PLACES:
        raise ConfigValueError(
            f'参数「{param.param_name}」最多支持 {NUMBER_MAX_PLACES} 位小数')
    if number.copy_abs() >= Decimal(10) ** NUMBER_MAX_DIGITS:
        raise ConfigValueError(f'参数「{param.param_name}」的数值超出允许范围')
    fields = _empty_fields()
    fields['value_number'] = number
    return fields


def _normalize_bool(param, raw_value):
    if raw_value in (True, False):
        boolean = raw_value
    elif str(raw_value).strip().lower() in ('true', '1', '是'):
        boolean = True
    elif str(raw_value).strip().lower() in ('false', '0', '否'):
        boolean = False
    elif str(raw_value).strip() == '':
        boolean = None
    else:
        raise ConfigValueError(f'参数「{param.param_name}」必须是布尔值（是/否）')
    fields = _empty_fields()
    fields['value_bool'] = boolean
    return fields


def _normalize_date(param, raw_value):
    raw = str(raw_value or '').strip()
    if not raw:
        return _empty_fields()
    try:
        parsed = datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        raise ConfigValueError(f'参数「{param.param_name}」的日期格式应为 YYYY-MM-DD')
    fields = _empty_fields()
    fields['value_date'] = parsed
    return fields


def _normalize_choice(param, raw_value):
    text = _clean(raw_value, 200)
    options = param.get_options()
    if text and options and text not in options:
        raise ConfigValueError(
            f'参数「{param.param_name}」只能提交允许的选项：{"、".join(options)}')
    fields = _empty_fields()
    fields['value_choice'] = text
    return fields

# 各类型的规范化器（normalize_param_value 的分发表）
_NORMALIZERS = {
    PARAM_TYPE_TEXT: _normalize_text,
    PARAM_TYPE_NUMBER: _normalize_number,
    PARAM_TYPE_BOOL: _normalize_bool,
    PARAM_TYPE_DATE: _normalize_date,
    PARAM_TYPE_CHOICE: _normalize_choice,
}


def normalize_param_value(param, raw_value):
    """按参数定义校验并规范化输入值，返回类型化字段 dict。

    失败抛 ConfigValueError（文案可直接提示）。bool 的 False 是合法值，
    空值判定按类型区分：text/choice 空串、number/date 为 None、bool 为 None。
    """
    normalizer = _NORMALIZERS.get(param.data_type)
    if not normalizer:
        raise ConfigValueError(f'参数「{param.param_name}」的数据类型不支持')
    return normalizer(param, raw_value)


def canonical_value_text(data_type, fields):
    """由类型化字段生成规范文本（当前值对比与明细快照的唯一口径）。"""
    if data_type == PARAM_TYPE_TEXT:
        return fields.get('value_text') or ''
    if data_type == PARAM_TYPE_NUMBER:
        number = fields.get('value_number')
        if number is None:
            return ''
        text = format(Decimal(number), 'f')
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        return text or '0'
    if data_type == PARAM_TYPE_BOOL:
        boolean = fields.get('value_bool')
        if boolean is None:
            return ''
        return 'true' if boolean else 'false'
    if data_type == PARAM_TYPE_DATE:
        value = fields.get('value_date')
        if isinstance(value, datetime):
            value = value.date()
        return value.strftime('%Y-%m-%d') if isinstance(value, date) else ''
    if data_type == PARAM_TYPE_CHOICE:
        return fields.get('value_choice') or ''
    return ''


def get_current_value_fields(value_row):
    """SystemParamValue 行 → 类型化字段 dict（canonical_value_text 入参）。"""
    return {
        'value_text': value_row.value_text,
        'value_number': value_row.value_number,
        'value_bool': value_row.value_bool,
        'value_date': value_row.value_date,
        'value_choice': value_row.value_choice,
    }


def get_current_value_text(system, param):
    """数据库中该系统该参数的当前值规范文本（未设置返回空串）。"""
    row = SystemParamValue.objects.filter(
        tenant_id=system.tenant_id, system=system, param=param).first()
    if not row:
        return ''
    return canonical_value_text(param.data_type, get_current_value_fields(row))


def build_change_items(system, raw_items):
    """从原始明细构建配置变更明细实例（未保存）。

    - 后端重新查询参数定义与数据库当前值，不信任前端传入的参数名称/类型/
      旧值（前端只提交参数 ID、变更后值与备注）；
    - 参数必须启用且适用当前系统；同一参数不允许重复提交；
    - 必填参数不允许提交空值；新旧值相同的参数拒绝提交（无变化不产生变更）。
    """
    if not isinstance(raw_items, list) or not raw_items:
        raise ConfigValueError('至少选择一个配置参数')
    seen_param_ids = set()
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ConfigValueError('配置参数明细格式不正确')
        param_id = raw.get('param')
        if not param_id or str(param_id).isdigit() is False:
            raise ConfigValueError('配置参数明细缺少参数')
        param_id = int(param_id)
        if param_id in seen_param_ids:
            raise ConfigValueError('同一参数在一条变更中不能重复提交')
        seen_param_ids.add(param_id)
        param = ConfigParamDefinition.objects.filter(
            pk=param_id, tenant_id=system.tenant_id).first()
        if not param:
            raise ConfigValueError('配置参数不存在或无权限访问')
        if not param.is_enabled:
            raise ConfigValueError(f'参数「{param.param_name}」已停用，不能提交变更')
        if not param.applies_to_system(system.id):
            raise ConfigValueError(f'参数「{param.param_name}」不适用于当前系统')
        fields = normalize_param_value(param, raw.get('new_value'))
        new_text = canonical_value_text(param.data_type, fields)
        old_text = get_current_value_text(system, param)
        if param.is_required and not new_text:
            raise ConfigValueError(f'参数「{param.param_name}」为必填项，不能提交空值')
        if old_text == new_text:
            raise ConfigValueError(
                f'参数「{param.param_name}」的变更后值与当前值相同，无需变更')
        items.append(ConfigChangeItem(
            tenant_id=system.tenant_id,
            param=param,
            param_code=param.param_code,
            param_name=param.param_name,
            param_data_type=param.data_type,
            unit=param.unit,
            old_value=old_text,
            new_value=new_text,
            remark=_clean(raw.get('remark'), 200),
        ))
    return items


def create_config_change(*, tenant_id, created_by, system, reason, items,
                         verify_note='', client_token=''):
    """创建草稿配置变更（须在编号锁 + 事务内调用）。

    明细由 build_change_items 以后端数据为准构建；只落变更记录，不写当前
    配置值（应用时才生效）。
    """
    change_items = build_change_items(system, items)
    change = ConfigChangeRecord.objects.create(
        tenant_id=tenant_id,
        change_no=generate_config_change_no(),
        system=system,
        system_code=system.system_code,
        system_name=system.name,
        reason=_clean(reason, 500),
        status=CONFIG_CHANGE_DRAFT,
        verify_note=_clean(verify_note, 500),
        client_token=_clean(client_token, 64),
        created_by=created_by,
    )
    for item in change_items:
        item.change = change
    ConfigChangeItem.objects.bulk_create(change_items)
    return change


def update_draft_change(*, change, updated_by, reason, items, verify_note=None):
    """编辑草稿变更（仅 draft 可编辑；明细全量替换并按当前库值重算快照）。

    已生效/已验证/已回退/已取消的变更拒绝普通编辑（不静默覆盖）。
    """
    if change.status != CONFIG_CHANGE_DRAFT:
        raise ConfigChangeError('只有草稿状态的配置变更可以编辑')
    change_items = build_change_items(change.system, items)
    change.reason = _clean(reason, 500)
    if verify_note is not None:
        change.verify_note = _clean(verify_note, 500)
    change.updated_at = timezone.now()
    change.updated_by = updated_by
    change.save(update_fields=['reason', 'verify_note', 'updated_at', 'updated_by'])
    change.items.all().delete()
    for item in change_items:
        item.change = change
        item.tenant_id = change.tenant_id
    ConfigChangeItem.objects.bulk_create(change_items)
    change.refresh_from_db()
    return change


def _upsert_current_value(*, system, param, fields, change, applied_by, applied_at,
                          created_by=None):
    """更新或创建当前配置值行（调用方已持行锁/系统锁）。"""
    row = SystemParamValue.objects.select_for_update().filter(
        system=system, param=param).first()
    if row:
        row.value_text = fields['value_text']
        row.value_number = fields['value_number']
        row.value_bool = fields['value_bool']
        row.value_date = fields['value_date']
        row.value_choice = fields['value_choice']
        row.effective_at = applied_at
        row.last_change = change
        row.last_changed_by = applied_by
        row.updated_at = applied_at
        row.save(update_fields=['value_text', 'value_number', 'value_bool',
                                'value_date', 'value_choice', 'effective_at',
                                'last_change', 'last_changed_by', 'updated_at'])
    else:
        SystemParamValue.objects.create(
            tenant_id=system.tenant_id,
            system=system,
            param=param,
            effective_at=applied_at,
            last_change=change,
            last_changed_by=applied_by,
            created_by=created_by or applied_by,
            **fields,
        )


def apply_config_change(*, change, applied_by, request=None):
    """应用配置变更（视图层在 transaction.atomic 内调用）。

    事务内完成：锁变更行 → 锁系统行（串行化同系统配置写入）→ 逐参数锁定
    当前值行并校验变更前值未被并发覆盖 → upsert 当前配置值 → 主表流转为
    applied → 重要变更同事务写履历。
    """
    change = ConfigChangeRecord.objects.select_for_update().get(pk=change.pk)
    if change.status != CONFIG_CHANGE_DRAFT:
        raise ConfigChangeError('只有草稿状态的配置变更可以应用')
    system = type(change.system).objects.select_for_update().get(pk=change.system_id)
    items = list(change.items.select_related('param').order_by('id'))
    if not items:
        raise ConfigChangeError('该变更没有配置参数明细，不能应用')
    applied_at = timezone.now()
    for item in items:
        param = item.param
        if not param.is_enabled:
            raise ConfigValueError(
                f'参数「{item.param_name}」已停用，不能应用变更；请取消本变更并重新登记')
        current_text = SystemParamValue.objects.filter(
            system=system, param=param).select_for_update().first()
        current_canonical = (
            canonical_value_text(param.data_type, get_current_value_fields(current_text))
            if current_text else '')
        if current_canonical != item.old_value:
            raise ConfigChangeError(
                f'参数「{item.param_name}」的当前值已被其他变更修改'
                f'（当前为「{current_canonical or "未设置"}」），请取消本变更后重新登记')
        fields = normalize_param_value(param, item.new_value)
        if canonical_value_text(param.data_type, fields) != item.new_value:
            raise ConfigValueError(
                f'参数「{item.param_name}」的变更后值不符合参数定义（参数定义可能已修改）')
        _upsert_current_value(system=system, param=param, fields=fields,
                              change=change, applied_by=applied_by,
                              applied_at=applied_at, created_by=change.created_by)
    change.status = CONFIG_CHANGE_APPLIED
    change.applied_at = applied_at
    change.applied_by = applied_by
    change.save(update_fields=['status', 'applied_at', 'applied_by'])
    return change


def verify_config_change(*, change, verify_status, verify_note, verified_by, request=None):
    """验证配置变更：passed 时主状态转为 verified（终态），failed 保持 applied
    可补验；verified 状态不接受再次验证。"""
    verify_status = (verify_status or '').strip()
    if verify_status not in (CONFIG_VERIFY_PASSED, CONFIG_VERIFY_FAILED):
        raise ConfigValueError('验证结论只能是验证通过或验证不通过')
    if change.status == CONFIG_CHANGE_VERIFIED:
        raise ConfigChangeError('该变更已验证通过，不能重复验证')
    if change.status != CONFIG_CHANGE_APPLIED:
        raise ConfigChangeError('只有已生效的配置变更可以验证')
    change.verify_status = verify_status
    if verify_note is not None:
        change.verify_note = _clean(verify_note, 500)
    change.items.all().update(verify_status=verify_status)
    if verify_status == CONFIG_VERIFY_PASSED:
        change.status = CONFIG_CHANGE_VERIFIED
        change.verified_by = verified_by
        change.verified_at = timezone.now()
        change.save(update_fields=['status', 'verify_status', 'verify_note',
                                   'verified_by', 'verified_at'])
    else:
        change.save(update_fields=['verify_status', 'verify_note'])
    return change


def rollback_config_change(*, change, created_by):
    """回退配置变更（须在编号锁 + 事务内调用）。

    - 校验当前数据库值仍等于原变更的"变更后值"（否则说明已被其他变更
      覆盖，拒绝直接回退）；
    - 生成一条新的反向变更（status=applied，rollback_of 指向原变更），
      继承原变更的履历标记与原因；
    - 原变更只流转状态为 rolled_back，内容与历史不改写、不删除。
    """
    if change.status not in (CONFIG_CHANGE_APPLIED, CONFIG_CHANGE_VERIFIED):
        raise ConfigChangeError('只有已生效或已验证的配置变更可以回退')
    if change.rollback_changes.exists():
        raise ConfigChangeError('该变更已回退，不能重复回退')
    system = type(change.system).objects.select_for_update().get(pk=change.system_id)
    items = list(change.items.select_related('param').order_by('id'))
    if not items:
        raise ConfigChangeError('该变更没有配置参数明细，无法回退')
    rolled_at = timezone.now()
    rollback_items = []
    for item in items:
        param = item.param
        current_row = SystemParamValue.objects.filter(
            system=system, param=param).select_for_update().first()
        current_canonical = (
            canonical_value_text(item.param_data_type, get_current_value_fields(current_row))
            if current_row else '')
        if current_canonical != item.new_value:
            raise ConfigChangeError(
                f'参数「{item.param_name}」的当前值已被其他变更修改，'
                f'不能基于本变更直接回退；请登记一条新的配置变更')
        fields = normalize_param_value(param, item.old_value)
        if canonical_value_text(item.param_data_type, fields) != item.old_value:
            raise ConfigValueError(
                f'参数「{item.param_name}」的原值不符合当前参数定义，无法自动回退；'
                f'请登记一条新的配置变更')
        rollback_items.append((param, fields, item))
    rollback_change = ConfigChangeRecord.objects.create(
        tenant_id=change.tenant_id,
        change_no=generate_config_change_no(),
        system=change.system,
        system_code=change.system_code,
        system_name=change.system_name,
        reason=f'回退变更 {change.change_no}：{_clean(change.reason, 400)}',
        status=CONFIG_CHANGE_APPLIED,
        applied_at=rolled_at,
        applied_by=created_by,
        rollback_of=change,
        created_by=created_by,
    )
    for param, fields, item in rollback_items:
        _upsert_current_value(system=system, param=param, fields=fields,
                              change=rollback_change, applied_by=created_by,
                              applied_at=rolled_at, created_by=created_by)
        ConfigChangeItem.objects.create(
            tenant_id=change.tenant_id,
            change=rollback_change,
            param=param,
            param_code=item.param_code,
            param_name=item.param_name,
            param_data_type=item.param_data_type,
            unit=item.unit,
            old_value=item.new_value,
            new_value=item.old_value,
            remark=item.remark,
        )
    change.status = CONFIG_CHANGE_ROLLED_BACK
    change.save(update_fields=['status'])
    return rollback_change


def cancel_config_change(*, change, cancelled_by, request=None):
    """取消草稿变更（仅 draft；已生效变更只能走回退流程）。"""
    if change.status != CONFIG_CHANGE_DRAFT:
        raise ConfigChangeError('只有草稿状态的配置变更可以取消；已生效变更请使用回退')
    change.status = CONFIG_CHANGE_CANCELLED
    change.cancelled_at = timezone.now()
    change.cancelled_by = cancelled_by
    change.save(update_fields=['status', 'cancelled_at', 'cancelled_by'])
    return change


def get_system_config_view(system):
    """系统当前配置视图：适用且启用的参数 + 当前值（未设置的参数也给出行）。

    参数定义按系统租户过滤（TenantModelManager 不做租户过滤，必须显式限定）。
    """
    from django.db.models import Q
    params = ConfigParamDefinition.objects.filter(
        tenant_id=system.tenant_id, is_enabled=True,
    ).filter(
        Q(scope_type=PARAM_SCOPE_ALL)
        | Q(scope_type=PARAM_SCOPE_SPECIFIC, system_scopes__system_id=system.id),
    ).distinct().order_by('param_code')
    value_rows = {
        row.param_id: row
        for row in SystemParamValue.objects.filter(
            tenant_id=system.tenant_id, system=system,
        ).select_related('param', 'last_change')
    }
    type_text_map = dict(PARAM_TYPE_CHOICES)
    category_text_map = dict(PARAM_CATEGORY_CHOICES)
    baseline = SystemConfigBaseline.objects.filter(
        tenant_id=system.tenant_id, system=system,
    ).select_related('established_by').first()
    items = []
    for param in params:
        row = value_rows.get(param.id)
        if row:
            fields = get_current_value_fields(row)
            if row.last_change_id:
                source_text = f'配置变更 {row.last_change.change_no}'
            elif row.baseline_id:
                source_text = '初始建档'
            else:
                source_text = ''
            items.append({
                'param': param.id,
                'param_code': param.param_code,
                'param_name': param.param_name,
                'category': param.category,
                'category_text': category_text_map.get(param.category, param.category),
                'data_type': param.data_type,
                'data_type_text': type_text_map.get(param.data_type, param.data_type),
                'unit': param.unit,
                'is_required': param.is_required,
                'options': param.get_options(),
                'value_text': fields['value_text'],
                'value_number': fields['value_number'],
                'value_bool': fields['value_bool'],
                'value_date': fields['value_date'],
                'value_choice': fields['value_choice'],
                'display_value': canonical_value_text(param.data_type, fields) or '未设置',
                'effective_at': row.effective_at,
                'last_change_id': row.last_change_id,
                'last_change_no': row.last_change.change_no if row.last_change_id else '',
                'last_changed_by_name': row.last_changed_by.username if row.last_changed_by_id else '',
                'source_text': source_text,
            })
        else:
            items.append({
                'param': param.id,
                'param_code': param.param_code,
                'param_name': param.param_name,
                'category': param.category,
                'category_text': category_text_map.get(param.category, param.category),
                'data_type': param.data_type,
                'data_type_text': type_text_map.get(param.data_type, param.data_type),
                'unit': param.unit,
                'is_required': param.is_required,
                'options': param.get_options(),
                'value_text': '', 'value_number': None, 'value_bool': None,
                'value_date': None, 'value_choice': '',
                'display_value': '未设置',
                'effective_at': None,
                'last_change_id': None,
                'last_change_no': '',
                'last_changed_by_name': '',
                'source_text': '',
            })
    return {
        'system': {'id': system.id, 'name': system.name, 'system_code': system.system_code},
        'baseline': {
            'id': baseline.id,
            'source': baseline.source,
            'established_by_name': baseline.established_by.username if baseline.established_by_id else '',
            'established_at': baseline.established_at,
        } if baseline else None,
        'items': items,
    }


def get_param_candidates_for_system(system):
    """记录配置变更时可选择的参数候选（适用且启用；按系统租户过滤）。"""
    from django.db.models import Q
    return ConfigParamDefinition.objects.filter(
        tenant_id=system.tenant_id, is_enabled=True,
    ).filter(
        Q(scope_type=PARAM_SCOPE_ALL)
        | Q(scope_type=PARAM_SCOPE_SPECIFIC, system_scopes__system_id=system.id),
    ).distinct().order_by('param_code')


def load_json_options(raw_options):
    """枚举选项入参清洗：接受数组或 JSON 数组字符串。"""
    if raw_options is None:
        return []
    if isinstance(raw_options, list):
        return [str(x).strip() for x in raw_options if str(x).strip()]
    try:
        data = json.loads(raw_options)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [str(x).strip() for x in data if str(x).strip()]

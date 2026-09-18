# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统配置档案服务层：字段值校验、变更历史、快照与差异比较。

视图层负责参数收集与权限校验；本模块负责：
- 动态字段值的类型/必填/候选项/范围/正则校验（可校验、可查询的结构化存储）；
- 敏感字段关键词拦截（密码/令牌/私钥不得作为字段定义或普通值保存）；
- 配置值保存与 SystemConfigChange 前后值记录；
- 快照内容构建与差异比较。
"""
import datetime
import json
import re

from django.utils import timezone

from apps.equipment_lifecycle.models import (
    ConfigFieldDefinition,
    LifecycleSystem,
    SystemConfigChange,
    SystemConfigValue,
)

# 字段定义中禁止出现的秘密类关键词（密码/令牌/私钥不得保存为普通字段）
FORBIDDEN_SECRET_KEYWORDS = (
    'password', 'passwd', 'token', 'secret', 'private_key', 'privatekey',
    'access_key', 'apikey', 'api_key', 'credential',
    '密码', '令牌', '私钥', '密钥',
)

TEXT_MAX_LENGTH = 500
LONGTEXT_MAX_LENGTH = 10000
DETAIL_TABLE_MAX_ROWS = 100
ATTACHMENT_MAX_COUNT = 20


def contains_secret_keyword(text):
    """判断文本是否包含秘密类关键词，用于字段定义创建校验。"""
    if not text:
        return False
    lowered = str(text).lower()
    return any(k in lowered for k in FORBIDDEN_SECRET_KEYWORDS)


def find_secret_keyword(text):
    """返回文本中命中的第一个秘密类关键词，未命中返回 None。"""
    if not text:
        return None
    lowered = str(text).lower()
    for k in FORBIDDEN_SECRET_KEYWORDS:
        if k in lowered:
            return k
    return None


def _parse_json_list(raw):
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def normalize_field_value(field, value):
    """校验并归一化单个字段值，返回 (storage, display, error)。

    storage 为按 field_type 分列的存储字典（value_text/value_number/value_date/value_bool）；
    display 为用于变更历史与快照展示的字符串。
    """
    if value is None:
        value = ''
    ftype = field.field_type

    if ftype == ConfigFieldDefinition.TYPE_BOOLEAN:
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ('true', '1', '是'):
                value = True
            elif low in ('false', '0', '否'):
                value = False
            elif low == '':
                value = None
            else:
                return {}, '', '布尔值只能是 是/否'
        if value is None:
            return {'value_bool': None}, '', None
        if not isinstance(value, bool):
            return {}, '', '布尔值只能是 是/否'
        display = '是' if value else '否'
        return {'value_bool': value}, display, None

    # 以下类型均以"非空字符串"视角处理空值
    if isinstance(value, bool):
        return {}, '', '值类型不正确'
    if not isinstance(value, (str, int, float, list, dict)):
        return {}, '', '值类型不正确'

    if ftype == ConfigFieldDefinition.TYPE_NUMBER:
        if value == '' or value is None:
            return {'value_number': None}, '', None
        try:
            num = float(value)
        except (TypeError, ValueError):
            return {}, '', '必须为数字'
        if field.number_min is not None and num < field.number_min:
            return {}, '', f'不能小于 {field.number_min}'
        if field.number_max is not None and num > field.number_max:
            return {}, '', f'不能大于 {field.number_max}'
        display = ('%g' % num)
        return {'value_number': num}, display, None

    if ftype == ConfigFieldDefinition.TYPE_DATE:
        if value == '' or value is None:
            return {'value_date': None}, '', None
        text = str(value).strip()
        try:
            date_val = datetime.date.fromisoformat(text[:10])
        except (TypeError, ValueError):
            return {}, '', '日期格式必须为 YYYY-MM-DD'
        return {'value_date': date_val}, text[:10], None

    # 文本类类型：统一转字符串
    if ftype in (ConfigFieldDefinition.TYPE_TEXT, ConfigFieldDefinition.TYPE_LONGTEXT,
                 ConfigFieldDefinition.TYPE_CHOICE):
        text = '' if value is None else str(value)
        max_len = TEXT_MAX_LENGTH if ftype == ConfigFieldDefinition.TYPE_TEXT else LONGTEXT_MAX_LENGTH
        if ftype == ConfigFieldDefinition.TYPE_TEXT and len(text) > max_len:
            return {}, '', f'长度不能超过 {max_len} 字'
        if ftype == ConfigFieldDefinition.TYPE_LONGTEXT and len(text) > max_len:
            return {}, '', f'长度不能超过 {max_len} 字'
        if ftype == ConfigFieldDefinition.TYPE_CHOICE:
            option_list = field.get_choices()
            if text and option_list and text not in option_list:
                return {}, '', '值不在候选项内'
        if ftype == ConfigFieldDefinition.TYPE_TEXT and field.text_regex:
            try:
                if text and not re.match(field.text_regex, text):
                    return {}, '', '格式不符合要求'
            except re.error:
                pass
        return {'value_text': text}, text, None

    if ftype == ConfigFieldDefinition.TYPE_MULTI_CHOICE:
        items = value if isinstance(value, list) else _parse_json_list(str(value))
        if not isinstance(items, list):
            return {}, '', '多选值必须为数组'
        cleaned = []
        for item in items:
            if not isinstance(item, (str, int, float)):
                return {}, '', '多选候选项类型不正确'
            cleaned.append(str(item))
        option_list = field.get_choices()
        if option_list:
            for item in cleaned:
                if item not in option_list:
                    return {}, '', f'候选项 {item} 不在可选项内'
        display = '、'.join(cleaned)
        return {'value_text': json.dumps(cleaned, ensure_ascii=False)}, display, None

    if ftype == ConfigFieldDefinition.TYPE_ATTACHMENT:
        ids = value if isinstance(value, list) else _parse_json_list(str(value))
        if not isinstance(ids, list):
            return {}, '', '附件值必须为附件ID数组'
        cleaned = []
        for item in ids:
            try:
                cleaned.append(int(item))
            except (TypeError, ValueError):
                return {}, '', '附件ID必须为整数'
        if len(cleaned) > ATTACHMENT_MAX_COUNT:
            return {}, '', f'附件数量不能超过 {ATTACHMENT_MAX_COUNT}'
        display = f'{len(cleaned)} 个附件' if cleaned else ''
        return {'value_text': json.dumps(cleaned)}, display, None

    if ftype == ConfigFieldDefinition.TYPE_DETAIL_TABLE:
        rows = value if isinstance(value, list) else _parse_json_list(str(value))
        if not isinstance(rows, list):
            return {}, '', '明细表必须为行数组'
        if len(rows) > DETAIL_TABLE_MAX_ROWS:
            return {}, '', f'明细行数不能超过 {DETAIL_TABLE_MAX_ROWS}'
        columns = field.get_detail_columns()
        column_codes = {c.get('code') for c in columns if isinstance(c, dict) and c.get('code')}
        cleaned_rows = []
        for row in rows:
            if not isinstance(row, dict):
                return {}, '', '明细行必须为对象'
            clean_row = {}
            for key, val in row.items():
                if val is None:
                    val = ''
                if not isinstance(val, (str, int, float)):
                    return {}, '', '明细单元格必须为文本或数字'
                if column_codes and key not in column_codes:
                    return {}, '', f'明细列 {key} 不在字段定义的列内'
                clean_row[key] = str(val)
            cleaned_rows.append(clean_row)
        display = f'{len(cleaned_rows)} 行' if cleaned_rows else ''
        return {'value_text': json.dumps(cleaned_rows, ensure_ascii=False)}, display, None

    return {}, '', '不支持的字段类型'


def value_to_display(field, record):
    """把存储的 SystemConfigValue 转成展示字符串。"""
    if record is None:
        return ''
    ftype = field.field_type
    if ftype == ConfigFieldDefinition.TYPE_BOOLEAN:
        return '' if record.value_bool is None else ('是' if record.value_bool else '否')
    if ftype == ConfigFieldDefinition.TYPE_NUMBER:
        return '' if record.value_number is None else ('%g' % record.value_number)
    if ftype == ConfigFieldDefinition.TYPE_DATE:
        return '' if record.value_date is None else record.value_date.isoformat()
    if ftype == ConfigFieldDefinition.TYPE_MULTI_CHOICE:
        items = _parse_json_list(record.value_text)
        return '、'.join(str(x) for x in items)
    if ftype == ConfigFieldDefinition.TYPE_ATTACHMENT:
        items = _parse_json_list(record.value_text)
        return f'{len(items)} 个附件' if items else ''
    if ftype == ConfigFieldDefinition.TYPE_DETAIL_TABLE:
        rows = _parse_json_list(record.value_text)
        return f'{len(rows)} 行' if rows else ''
    return record.value_text or ''


def value_to_payload(field, record):
    """把存储值转成前端编辑回填所需的原始值。"""
    if record is None:
        return ''
    ftype = field.field_type
    if ftype == ConfigFieldDefinition.TYPE_BOOLEAN:
        if record.value_bool is None:
            return ''
        return record.value_bool
    if ftype == ConfigFieldDefinition.TYPE_NUMBER:
        return '' if record.value_number is None else record.value_number
    if ftype == ConfigFieldDefinition.TYPE_DATE:
        return '' if record.value_date is None else record.value_date.isoformat()
    if ftype in (ConfigFieldDefinition.TYPE_MULTI_CHOICE,
                 ConfigFieldDefinition.TYPE_ATTACHMENT,
                 ConfigFieldDefinition.TYPE_DETAIL_TABLE):
        return _parse_json_list(record.value_text)
    return record.value_text or ''


def field_applies_to_system(field, system):
    """判断字段对具体系统是否适用（applies_to=new_only 时仅适用于其后新建的系统）。"""
    if field.applies_to != ConfigFieldDefinition.APPLIES_NEW_ONLY:
        return True
    if field.created_at is None or system.created_at is None:
        return True
    return system.created_at >= field.created_at


def collect_applicable_fields(system, include_inactive=False):
    """收集系统适用的全部配置字段：类型模板字段 + 本系统自定义字段。"""
    qs = ConfigFieldDefinition.objects.filter(
        tenant_id=system.tenant_id,
        scope_type=ConfigFieldDefinition.SCOPE_TEMPLATE,
        scope_owner_id=str(system.system_type_id),
    ) | ConfigFieldDefinition.objects.filter(
        tenant_id=system.tenant_id,
        scope_type=ConfigFieldDefinition.SCOPE_CUSTOM,
        scope_owner_id=str(system.id),
    )
    if not include_inactive:
        qs = qs.filter(is_active=True)
    fields = list(qs)
    fields.sort(key=lambda f: (f.display_order, f.id))
    return fields


def validate_field_value_map(fields, submitted, user):
    """按字段集合校验提交值映射（不含必填检查与附件归属检查），返回 (cleaned, errors)。

    - submitted: {field_id: value}，键可为 int 或数字字符串；
    - 提交中出现的 field_id 必须属于给定字段集合（不适用/已停用即拒绝）；
    - 逐字段做角色编辑权限与类型/候选项/范围/正则校验。
    """
    field_map = {f.id: f for f in fields}
    cleaned = {}
    errors = []

    if not isinstance(submitted, dict):
        return {}, ['配置值格式不正确']

    for key, value in submitted.items():
        try:
            field_id = int(key)
        except (TypeError, ValueError):
            errors.append(f'无效的字段标识 {key}')
            continue
        field = field_map.get(field_id)
        if field is None:
            errors.append(f'字段 {key} 不适用于当前系统或已停用')
            continue
        role_ids = set(user.roles.values_list('id', flat=True)) if user is not None else set()
        editable_roles = field.get_role_ids('editable_roles')
        if editable_roles and user is not None and not role_ids.intersection(editable_roles) \
                and not getattr(user, 'is_supper', False):
            errors.append(f'字段 {field.display_name} 不允许当前角色编辑')
            continue
        storage, display, err = normalize_field_value(field, value)
        if err:
            errors.append(f'{field.display_name}: {err}')
            continue
        cleaned[field_id] = (storage, display)
    return cleaned, errors


def validate_config_submission(system, fields, submitted, user):
    """校验整个配置提交，返回 (cleaned: {field_id: (storage, display)}, errors: [str])。

    规则：
    - 提交中出现的 field_id 必须属于本系统适用的启用字段；
    - 逐字段类型/候选项/范围/正则校验；
    - 适用且启用的必填字段必须有值（历史系统逐步补录在下一次保存时强制完成）。
    """
    from libs.tenant_utils import apply_tenant_filter
    from apps.evidence.models import EvidenceAttachment

    cleaned, errors = validate_field_value_map(fields, submitted, user)

    for field in fields:
        if not field.is_required or not field_applies_to_system(field, system):
            continue
        entry = cleaned.get(field.id)
        if entry is None:
            existing = SystemConfigValue.objects.filter(system=system, field=field).first()
            if existing is None or value_to_display(field, existing) == '':
                errors.append(f'{field.display_name} 为必填项')

    attachment_field_ids = [
        f.id for f in fields if f.field_type == ConfigFieldDefinition.TYPE_ATTACHMENT
    ]
    if attachment_field_ids:
        checked_ids = []
        for field_id in attachment_field_ids:
            entry = cleaned.get(field_id)
            if entry:
                raw = entry[0].get('value_text', '')
                if raw:
                    checked_ids.extend(json.loads(raw))
        if checked_ids:
            valid_ids = set(apply_tenant_filter(
                EvidenceAttachment.objects.filter(is_deleted=False), user
            ).filter(
                module='equipment_lifecycle', object_type='el_system_config',
                object_id=str(system.id), pk__in=checked_ids,
            ).values_list('id', flat=True))
            for field_id in attachment_field_ids:
                entry = cleaned.get(field_id)
                if not entry:
                    continue
                raw = entry[0].get('value_text', '')
                ids = json.loads(raw) if raw else []
                bad = [i for i in ids if i not in valid_ids]
                if bad:
                    field = next(f for f in fields if f.id == field_id)
                    errors.append(f'{field.display_name}: 附件不存在或无权限访问')

    return cleaned, errors


def diff_changes(old_display_map, new_display_map, fields):
    """比较新旧展示值，生成 SystemConfigChange.changes JSON 数组。"""
    changes = []
    field_map = {f.id: f for f in fields}
    for field_id, new_display in new_display_map.items():
        field = field_map.get(field_id)
        if field is None:
            continue
        old_display = old_display_map.get(field_id, '')
        if old_display != new_display:
            changes.append({
                'scope': field.scope_type,
                'code': field.field_code,
                'label': field.display_name,
                'old': old_display,
                'new': new_display,
            })
    return changes


def record_config_change(system, source, action, changes, user):
    SystemConfigChange.objects.create(
        tenant_id=system.tenant_id,
        system=system,
        source=source,
        action=action,
        changes=json.dumps(changes, ensure_ascii=False),
        changed_by=user,
    )


def build_snapshot_content(system):
    """构建系统当前完整配置快照内容（固定字段 + 动态字段值 + 组成项）。"""
    fixed = {
        'system_code': system.system_code,
        'name': system.name,
        'system_type': system.system_type.name,
        'system_model': system.system_model,
        'install_location': system.install_location,
        'geo_coordinate': system.geo_coordinate,
        'system_purpose': system.system_purpose,
        'manufacturer': system.manufacturer,
        'install_unit': system.install_unit,
        'use_unit': system.use_unit,
        'install_time': system.install_time.isoformat(sep=' ', timespec='minutes') if system.install_time else '',
        'enable_time': system.enable_time.isoformat(sep=' ', timespec='minutes') if system.enable_time else '',
        'responsible_user_name': system.responsible_user_name,
        'health_status': system.get_health_status_display(),
        'is_active': system.is_active,
        'remark': system.remark,
    }
    fields = collect_applicable_fields(system, include_inactive=True)
    value_map = {
        v.field_id: v for v in SystemConfigValue.objects.filter(system=system)
    }
    values = []
    for field in fields:
        record = value_map.get(field.id)
        values.append({
            'scope': field.scope_type,
            'code': field.field_code,
            'label': field.display_name,
            'type': field.field_type,
            'is_active': field.is_active,
            'value': value_to_display(field, record),
        })
    components = []
    for comp in system.components.all():
        components.append({
            'name': comp.name,
            'category': comp.category,
            'model_version': comp.model_version,
            'quantity': comp.quantity,
            'purpose': comp.purpose,
            'asset_sn': comp.asset_sn,
            'external_ref': comp.external_ref,
            'remark': comp.remark,
        })
    return {'fixed': fixed, 'values': values, 'components': components}


def diff_content(base_content, target_content):
    """比较两份快照内容，返回差异条目数组 [{group, label, old, new}]。"""
    diffs = []
    base_fixed = base_content.get('fixed') or {}
    target_fixed = target_content.get('fixed') or {}
    for key in base_fixed.keys() | target_fixed.keys():
        old = str(base_fixed.get(key, '') if base_fixed.get(key, '') is not None else '')
        new = str(target_fixed.get(key, '') if target_fixed.get(key, '') is not None else '')
        if old != new:
            diffs.append({'group': '固定字段', 'label': key, 'old': old, 'new': new})

    def _value_map(content):
        return {item.get('code'): item for item in (content.get('values') or []) if isinstance(item, dict)}

    base_values = _value_map(base_content)
    target_values = _value_map(target_content)
    for code in base_values.keys() | target_values.keys():
        base_item = base_values.get(code) or {}
        target_item = target_values.get(code) or {}
        label = target_item.get('label') or base_item.get('label') or code
        old = str(base_item.get('value') or '')
        new = str(target_item.get('value') or '')
        if old != new:
            diffs.append({'group': '配置字段', 'label': label, 'old': old, 'new': new})

    def _component_map(content):
        result = {}
        for item in (content.get('components') or []):
            if not isinstance(item, dict):
                continue
            key = (item.get('name'), item.get('category'), item.get('model_version'))
            result[key] = item
        return result

    base_comps = _component_map(base_content)
    target_comps = _component_map(target_content)
    for key in base_comps.keys() | target_comps.keys():
        base_item = base_comps.get(key) or {}
        target_item = target_comps.get(key) or {}
        label = target_item.get('name') or base_item.get('name') or str(key)
        old = _component_brief(base_item)
        new = _component_brief(target_item)
        if old != new:
            diffs.append({'group': '配置组成项', 'label': label, 'old': old, 'new': new})
    return diffs


def _component_brief(item):
    parts = []
    for key, label in (('model_version', '型号'), ('quantity', '数量'), ('purpose', '用途')):
        value = item.get(key)
        if value not in (None, ''):
            parts.append(f'{label}:{value}')
    return '，'.join(parts)


def now():
    return timezone.now()

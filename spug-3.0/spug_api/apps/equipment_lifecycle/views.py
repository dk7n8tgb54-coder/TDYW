# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——系统主数据与配置字段视图（步骤二）。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.system.view|add|edit|del|deactivate|export
- equipment_lifecycle.system_config.view|edit|field|snapshot|export

系统新增（POST /systems/）与编辑（PUT /systems/<pk>/）支持结构化聚合提交：
{"system": {...}, "custom_fields": [...], "components": [...]}
（编辑为 config_values / custom_fields / components）。固定字段、字段定义、
字段值与组成项在同一事务内写入，任一步失败整体回滚；旧平铺载荷仍兼容。
系统编号（system_code）为后端内部标识：新增时由后端自动生成（租户内唯一、
创建后不可修改），客户端传入的取值一律忽略，前端不展示。
内联自定义字段的 client_key 仅用于关联本次请求的定义与值，正式字段编码
由后端生成。配置字段定义集中维护接口（自定义字段）保留。

所有写操作记录业务审计（record_audit_event）与配置变更历史；
所有查询经租户过滤（apply_tenant_filter / TenantModelManager.for_user）。
"""
import csv
import hashlib
import io
import json
import re
from datetime import datetime
from secrets import token_hex
from types import SimpleNamespace

from django.db import IntegrityError, models, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import View

from libs import JsonParser, Argument, json_response, auth
from libs.tenant_utils import apply_tenant_filter
from apps.logs.audit import record_audit_event
from apps.evidence.attachment_service import (
    AttachmentService, DefaultAttachmentConfig, ATTACHMENT_ACCESS_DENIED_ERROR,
    ATTACHMENT_DELETE_DENIED_ERROR,
)
from apps.evidence.models import EvidenceAttachment

from apps.equipment_lifecycle.models import (
    ConfigFieldDefinition,
    LifecycleSystem,
    SystemConfigChange,
    SystemConfigComponent,
    SystemConfigSnapshot,
    SystemConfigValue,
)
from apps.equipment_lifecycle import services

AUDIT_TARGET_SYSTEM = 'el_system'
AUDIT_TARGET_CONFIG = 'el_system_config'

# 配置档案附件归属标识（动态字段 attachment 类型的物理存储归属）
EL_ATTACHMENT_MODULE = 'equipment_lifecycle'
EL_ATTACHMENT_OBJECT_TYPE = 'el_system_config'

FIELD_CODE_PATTERN = re.compile(r'^[a-z][a-z0-9_]{0,49}$')

# 固定核心字段：动态字段不得与其重名（编码与显示名称双向占用）
RESERVED_FIELD_CODES = {
    'system_code', 'name', 'system_model', 'install_location',
    'geo_coordinate', 'system_purpose', 'manufacturer', 'install_unit',
    'use_unit', 'install_time', 'enable_time', 'responsible_user_name',
    'health_status', 'is_active', 'remark', 'id', 'created_at', 'updated_at',
}
RESERVED_FIELD_LABELS = {
    '系统编号', '系统名称', '系统型号', '安装地点', '安装经纬度',
    '系统用途', '生产厂家', '安装单位', '使用单位', '安装时间', '启用时间',
    '系统负责人', '运行健康状态', '是否可用', '备注',
}

DATETIME_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d')

# 系统固定字段的变更历史展示名（与模型 help_text 口径一致）
# 注意：health_status 由故障/工单驱动统一计算（fault_services），不属于可编辑固定字段
FIXED_CHANGE_LABELS = {
    'name': '系统名称', 'system_model': '系统型号', 'install_location': '安装地点',
    'geo_coordinate': '安装经纬度', 'system_purpose': '系统用途',
    'manufacturer': '生产厂家', 'install_unit': '安装单位', 'use_unit': '使用单位',
    'install_time': '安装时间', 'enable_time': '启用时间',
    'responsible_user_name': '系统负责人', 'remark': '备注',
}


def _read_json_body(request):
    """读取 JSON 请求体为 dict；格式不合法返回 None。"""
    try:
        body = json.loads(request.body.decode('utf-8')) if request.body else {}
    except (ValueError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _parse_system_fields(data):
    """解析系统固定字段（data 为已解析的 dict）。

    system_code 为后端内部标识，不接收客户端取值，新增时自动生成。
    """
    parser = JsonParser(
        Argument('name', type=str, required=True, help='系统名称'),
        Argument('system_model', type=str, required=True, help='系统型号'),
        Argument('install_location', type=str, required=True, help='安装地点'),
        Argument('geo_coordinate', type=str, required=False, default=''),
        Argument('system_purpose', type=str, required=False, default=''),
        Argument('manufacturer', type=str, required=True, help='生产厂家'),
        Argument('install_unit', type=str, required=True, help='安装单位'),
        Argument('use_unit', type=str, required=True, help='使用单位'),
        Argument('install_time', type=str, required=True, help='安装时间'),
        Argument('enable_time', type=str, required=True, help='启用时间'),
        Argument('responsible_user_name', type=str, required=True, help='系统负责人'),
        Argument('remark', type=str, required=False, default=''),
    )
    return parser.parse(data or {})


def _fixed_field_snapshot(item):
    """提取参与变更历史比对的系统固定字段快照。

    health_status 不参与比对：它由故障/工单驱动统一计算（fault_services），
    不是用户可编辑字段，其变化通过健康状态审计与系统履历记录。
    """
    return {
        'name': item.name, 'system_model': item.system_model,
        'install_location': item.install_location, 'geo_coordinate': item.geo_coordinate,
        'system_purpose': item.system_purpose, 'manufacturer': item.manufacturer,
        'install_unit': item.install_unit, 'use_unit': item.use_unit,
        'install_time': item.install_time.isoformat(sep=' ', timespec='minutes') if item.install_time else '',
        'enable_time': item.enable_time.isoformat(sep=' ', timespec='minutes') if item.enable_time else '',
        'responsible_user_name': item.responsible_user_name, 'remark': item.remark,
    }


def _diff_fixed_changes(before, after):
    """比较固定字段前后快照，生成 SystemConfigChange.changes 条目。"""
    return [
        {'scope': 'fixed', 'code': key, 'label': FIXED_CHANGE_LABELS[key],
         'old': before[key], 'new': after[key]}
        for key in before if before[key] != after[key]
    ]


def _apply_fixed_fields(item, form, install_time, enable_time, user):
    """把校验通过的固定字段写入系统实例（不落库）。

    health_status 不在此写入：普通系统编辑不能覆盖由故障和工单计算的健康状态
    （步骤 3.5 收口，新建系统初始化为 normal，后续变化只由重算服务写入）。
    """
    item.name = form.name.strip()
    item.system_model = form.system_model.strip()
    item.install_location = form.install_location.strip()
    item.geo_coordinate = (form.geo_coordinate or '').strip()
    item.system_purpose = (form.system_purpose or '').strip()[:500]
    item.manufacturer = form.manufacturer.strip()
    item.install_unit = form.install_unit.strip()
    item.use_unit = form.use_unit.strip()
    item.install_time = install_time
    item.enable_time = enable_time
    item.responsible_user_name = form.responsible_user_name.strip()
    item.remark = (form.remark or '').strip()[:1000]
    item.updated_at = timezone.now()
    item.updated_by = user


def _validate_system_fixed_payload(request, form):
    """校验系统固定字段公共部分，返回 (install_time, enable_time, error)。

    system_code 不来自客户端：新增由 _generate_system_code 生成，编辑保持原值。
    """
    err = SystemView._check_geo(form.geo_coordinate)
    if err:
        return None, None, err
    install_time = _parse_datetime(form.install_time)
    enable_time = _parse_datetime(form.enable_time)
    if not install_time or not enable_time:
        return None, None, '安装时间/启用时间格式不正确，应为 YYYY-MM-DD HH:MM'
    return install_time, enable_time, None


def _generate_system_code(user):
    """生成租户内唯一的系统编号：SYS-日期-6位随机十六进制。

    编号仅作后端标识（快照/审计/导出命名），不向前端展示。预检查避开已有
    编号，极小概率的并发碰撞由 (tenant_id, system_code) 唯一约束兜底。
    """
    # USE_TZ=False 下 timezone.now() 即本地 naive 时间，直接取日期（localdate 会抛错）
    prefix = 'SYS-%s-' % timezone.now().strftime('%Y%m%d')
    for _ in range(5):
        code = prefix + token_hex(3).upper()
        if not apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(
                system_code=code).exists():
            return code
    return prefix + token_hex(8).upper()


def _generate_field_code(display_name, tenant_id, custom_system_id=None):
    """按显示名称生成稳定字段编码：ASCII 可读优先，中文等回退 custom_field_N。

    编码在系统自定义字段作用范围内不重复。
    """
    slug = re.sub(r'[^a-z0-9]+', '_', str(display_name).strip().lower()).strip('_')
    if slug and slug[0].isdigit():
        slug = 'f_' + slug
    if not slug or slug in RESERVED_FIELD_CODES:
        slug = 'custom_field'
    slug = slug[:50]
    existing = set()
    if custom_system_id:
        existing = set(ConfigFieldDefinition.objects.filter(
            tenant_id=tenant_id, scope_type=ConfigFieldDefinition.SCOPE_CUSTOM,
            scope_owner_id=str(custom_system_id),
        ).values_list('field_code', flat=True))
    if slug not in existing:
        return slug
    index = 1
    while f'{slug}_{index}' in existing:
        index += 1
    return f'{slug}_{index}'[:50]


def _build_inline_field_form(item):
    """把一次提交中的内联自定义字段条目转成字段定义校验表单，返回 (form, error)。"""
    if not isinstance(item, dict):
        return None, '自定义字段定义格式不正确'
    name = str(item.get('name') or '').strip()
    if not name:
        return None, '自定义字段名称不能为空'
    field_type = str(item.get('field_type') or 'text').strip()
    choices = item.get('choices')
    if isinstance(choices, list):
        choices = json.dumps([str(x) for x in choices], ensure_ascii=False)
    elif not choices:
        choices = ''
    form = SimpleNamespace(
        pk=None,
        field_code='',
        display_name=name,
        field_type=field_type,
        help_text=str(item.get('help_text') or '')[:200],
        default_value='',
        choices=choices,
        detail_columns='',
        number_min=item.get('number_min') if item.get('number_min') is not None else None,
        number_max=item.get('number_max') if item.get('number_max') is not None else None,
        text_regex=str(item.get('text_regex') or '')[:200],
        visible_roles='',
        editable_roles='',
    )
    for key in ('number_min', 'number_max'):
        value = getattr(form, key)
        if value is not None:
            try:
                setattr(form, key, float(value))
            except (TypeError, ValueError):
                return None, f'自定义字段「{name}」数值范围不合法'
    return form, None


def _validate_component_entry(entry):
    """校验一次提交中的单个配置组成项条目，返回 (params, error)。"""
    if not isinstance(entry, dict):
        return None, '配置组成项格式不正确'
    name = str(entry.get('name') or '').strip()
    if not name:
        return None, '配置组成项名称不能为空'
    quantity = entry.get('quantity')
    if quantity is not None and quantity != '':
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return None, f'组成项「{name}」数量必须为整数'
        if quantity < 0:
            return None, '数量不能为负数'
    else:
        quantity = None
    params = {
        'name': name[:100],
        'category': str(entry.get('category') or '').strip()[:50],
        'model_version': str(entry.get('model_version') or '').strip()[:100],
        'quantity': quantity,
        'purpose': str(entry.get('purpose') or '').strip()[:200],
        'asset_sn': str(entry.get('asset_sn') or '').strip()[:100],
        'external_ref': str(entry.get('external_ref') or '').strip()[:200],
        'remark': str(entry.get('remark') or '').strip()[:500],
        'display_order': entry.get('display_order') if isinstance(entry.get('display_order'), int) else 0,
    }
    return params, None


def _parse_datetime(value):
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    return None


def _get_system_for_user(pk, user):
    return apply_tenant_filter(LifecycleSystem.objects.all(), user).filter(pk=pk).first()


def _get_field_for_user(pk, user):
    return apply_tenant_filter(ConfigFieldDefinition.objects.all(), user).filter(pk=pk).first()


def _collect_system_references(system):
    """删除保护：返回引用该系统的业务对象描述列表，非空则禁止物理删除。

    步骤 3.1 起故障、步骤 3.2 起台账明细、步骤 3.3 起工单、步骤 3.4 起
    履历事件均以系统 ID 建立业务关联（PROTECT）；升级管理挂接系统档案后，
    升级记录同样以系统 ID 关联。历史记录必须继续可查，
    存在关联的系统不得物理删除。fail-closed 语义。
    """
    from apps.equipment_lifecycle.models import (
        OperationLedgerItem,
        SystemEvent,
        SystemFault,
        SystemWorkOrder,
    )
    from apps.upgrade.models import UpgradeRecord
    refs = []
    if SystemFault.objects.filter(
            tenant_id=system.tenant_id, system_id=system.id).exists():
        refs.append('故障记录')
    if OperationLedgerItem.objects.filter(
            tenant_id=system.tenant_id, system_id=system.id).exists():
        refs.append('运维台账明细')
    if SystemWorkOrder.objects.filter(
            tenant_id=system.tenant_id, system_id=system.id).exists():
        refs.append('工单')
    if SystemEvent.objects.filter(
            tenant_id=system.tenant_id, system_id=system.id).exists():
        refs.append('系统履历事件')
    if UpgradeRecord.objects.filter(
            tenant_id=system.tenant_id, system_id=system.id,
            is_deleted=False).exists():
        refs.append('升级记录')
    return refs


def _get_user_role_ids(user):
    if user is None:
        return set()
    return set(user.roles.values_list('id', flat=True))


def _field_visible(field, user):
    role_ids = _get_user_role_ids(user)
    visible_roles = field.get_role_ids('visible_roles')
    if not visible_roles:
        return True
    if getattr(user, 'is_supper', False):
        return True
    return bool(role_ids.intersection(visible_roles))


def _component_brief(comp):
    parts = []
    if comp.model_version:
        parts.append(f'型号:{comp.model_version}')
    if comp.quantity is not None:
        parts.append(f'数量:{comp.quantity}')
    if comp.category:
        parts.append(f'类别:{comp.category}')
    return f'{comp.name}（' + '，'.join(parts) + '）' if parts else comp.name


def _serialize_field(field):
    data = field.to_view()
    data['choices_parsed'] = field.get_choices()
    data['detail_columns_parsed'] = field.get_detail_columns()
    default = field.default_value or ''
    if field.field_type in (ConfigFieldDefinition.TYPE_MULTI_CHOICE,
                            ConfigFieldDefinition.TYPE_ATTACHMENT,
                            ConfigFieldDefinition.TYPE_DETAIL_TABLE):
        try:
            data['default_parsed'] = json.loads(default) if default else []
        except (ValueError, TypeError):
            data['default_parsed'] = []
    else:
        data['default_parsed'] = default
    return data


def _validate_field_definition_payload(form, scope_type, owner_obj):
    """字段定义公共校验，返回错误字符串或 None。"""
    code = (form.field_code or '').strip()
    if not FIELD_CODE_PATTERN.match(code):
        return '字段编码必须以小写字母开头，仅含小写字母、数字和下划线，长度不超过 50'
    if code in RESERVED_FIELD_CODES:
        return f'字段编码 {code} 与固定核心字段冲突'
    label = (form.display_name or '').strip()
    if not label:
        return '显示名称不能为空'
    if label in RESERVED_FIELD_LABELS:
        return f'显示名称 {label} 与固定核心字段冲突'
    if form.field_type not in ConfigFieldDefinition.FIELD_TYPE_VALUES:
        return '不支持的字段类型'

    for text, name in ((code, '字段编码'), (label, '显示名称'),
                       (form.help_text or '', '帮助文字'), (form.default_value or '', '默认值')):
        keyword = services.find_secret_keyword(text)
        if keyword:
            return f'{name}不能包含密码/令牌/私钥类关键词（命中 {keyword}），敏感信息只能保存引用标识'

    if form.field_type in (ConfigFieldDefinition.TYPE_CHOICE, ConfigFieldDefinition.TYPE_MULTI_CHOICE):
        options = []
        try:
            raw = json.loads(form.choices) if form.choices else []
            if not isinstance(raw, list) or not raw:
                return '单选/多选字段必须提供非空候选项数组'
            for item in raw:
                if not isinstance(item, (str, int, float)):
                    return '候选项必须为文本或数字'
                options.append(str(item))
        except (ValueError, TypeError):
            return '候选项必须为 JSON 字符串数组'
        if len(set(options)) != len(options):
            return '候选项不能重复'
    elif form.choices:
        return '仅单选/多选字段需要候选项'

    if form.field_type == ConfigFieldDefinition.TYPE_DETAIL_TABLE and form.detail_columns:
        try:
            raw = json.loads(form.detail_columns)
            if not isinstance(raw, list):
                return '明细表列定义必须为 JSON 数组'
            for item in raw:
                if not isinstance(item, dict) or not item.get('code') or not item.get('name'):
                    return '明细表列定义必须包含 code 和 name'
        except (ValueError, TypeError):
            return '明细表列定义必须为 JSON 数组'
    elif form.detail_columns and form.field_type != ConfigFieldDefinition.TYPE_DETAIL_TABLE:
        return '仅明细表字段需要列定义'

    if form.number_min is not None and form.number_max is not None and form.number_min > form.number_max:
        return '数字最小值不能大于最大值'

    if form.text_regex:
        try:
            re.compile(form.text_regex)
        except re.error:
            return '文本格式校验正则不合法'

    for attr in ('visible_roles', 'editable_roles'):
        raw = getattr(form, attr) or ''
        if not raw:
            continue
        try:
            data = json.loads(raw)
            ids = [int(x) for x in data]
        except (ValueError, TypeError):
            return f'{attr} 必须为角色ID JSON 数组'
        from apps.account.models import Role
        exist_count = Role.objects.filter(id__in=ids).count()
        if exist_count != len(set(ids)):
            return f'{attr} 包含不存在的角色'

    default = form.default_value or ''
    if default and form.field_type == ConfigFieldDefinition.TYPE_CHOICE:
        if default not in [str(x) for x in (json.loads(form.choices) if form.choices else [])]:
            return '默认值必须为候选项之一'
    if default and form.field_type == ConfigFieldDefinition.TYPE_MULTI_CHOICE:
        try:
            defaults = json.loads(default)
        except (ValueError, TypeError):
            return '多选默认值必须为 JSON 数组'
        options = [str(x) for x in (json.loads(form.choices) if form.choices else [])]
        for item in defaults:
            if str(item) not in options:
                return '默认值必须为候选项之一'
    if default and form.field_type == ConfigFieldDefinition.TYPE_BOOLEAN and default not in ('true', 'false'):
        return '布尔默认值必须为 true 或 false'

    # 重名校验：同一作用范围内字段编码与显示名称均不得重复（不得与固定字段重名）
    dup_query = ConfigFieldDefinition.objects.filter(
        tenant_id=owner_obj.tenant_id,
        scope_type=scope_type,
        scope_owner_id=str(owner_obj.id),
    ).filter(Q(field_code=code) | Q(display_name=label))
    if getattr(form, 'pk', None):
        dup_query = dup_query.exclude(pk=form.pk)
    if dup_query.exists():
        return '字段编码或显示名称与现有字段重复'
    return None


def _parse_field_definition(request, code_required=True):
    """字段定义新增/编辑公共参数解析（自定义字段定义与内联字段共用）。"""
    return JsonParser(
        Argument('field_code', type=str, required=code_required,
                 default='' if not code_required else None, help='字段编码'),
        Argument('display_name', type=str, required=True, help='显示名称'),
        Argument('field_type', type=str, required=True, help='字段类型'),
        Argument('help_text', type=str, required=False, default=''),
        Argument('display_order', type=int, required=False, default=0),
        Argument('is_required', type=bool, required=False, default=False),
        Argument('default_value', type=str, required=False, default=''),
        Argument('choices', type=str, required=False, default=''),
        Argument('detail_columns', type=str, required=False, default=''),
        Argument('number_min', type=float, required=False),
        Argument('number_max', type=float, required=False),
        Argument('text_regex', type=str, required=False, default=''),
        Argument('is_searchable', type=bool, required=False, default=False),
        Argument('is_filterable', type=bool, required=False, default=False),
        Argument('is_exportable', type=bool, required=False, default=False),
        Argument('visible_roles', type=str, required=False, default=''),
        Argument('editable_roles', type=str, required=False, default=''),
        Argument('is_sensitive', type=bool, required=False, default=False),
        Argument('applies_to', type=str, required=False, default=ConfigFieldDefinition.APPLIES_ALL),
        Argument('is_active', type=bool, required=False, default=True),
    ).parse(request.body)


def _check_existing_field_values(field, form):
    """字段类型或候选项变更时必须校验已有值，禁止静默破坏数据。"""
    existing = SystemConfigValue.objects.filter(field=field)
    if not existing.exists():
        return None
    if form.field_type != field.field_type:
        return '该字段已有历史值，不能变更字段类型；请先确认历史值处理方案'
    if form.field_type in (ConfigFieldDefinition.TYPE_CHOICE, ConfigFieldDefinition.TYPE_MULTI_CHOICE):
        options = set(str(x) for x in (json.loads(form.choices) if form.choices else []))
        for record in existing:
            if field.field_type == ConfigFieldDefinition.TYPE_MULTI_CHOICE:
                try:
                    items = json.loads(record.value_text) if record.value_text else []
                except (ValueError, TypeError):
                    items = []
            else:
                items = [record.value_text] if record.value_text else []
            for item in items:
                if str(item) not in options:
                    return f'已有值「{item}」不在新候选项内，请先处理历史值'
    return None


def _parse_health_status_filter(raw):
    """解析健康状态筛选参数，兼容三种提交形态，非法返回 None。

    - 前端单选以标量字符串提交（axios 不做 JSON 编码）：normal；
    - 多值以逗号分隔提交：normal,fault；
    - 历史调用以 JSON 数组字符串提交（json.dumps 形态）：["fault"]。
    """
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith('['):
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, list):
            return None
        return [str(x).strip() for x in data if str(x).strip()]
    return [part.strip() for part in text.split(',') if part.strip()]


class SystemView(View):
    @auth('equipment_lifecycle.system.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('keyword', type=str, required=False),
            # 前端单选以标量字符串提交，声明为 list 会使 JsonParser 对普通
            # 字符串执行 json.loads 而报错（见 _parse_health_status_filter）
            Argument('health_status', type=str, required=False),
            Argument('is_active', type=bool, required=False),
            Argument('use_unit', type=str, required=False),
            Argument('install_location', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        query = apply_tenant_filter(LifecycleSystem.objects.all(), request.user)
        if form.keyword:
            query = query.filter(
                Q(system_code__icontains=form.keyword) | Q(name__icontains=form.keyword))
        if form.health_status:
            statuses = _parse_health_status_filter(form.health_status)
            if statuses is None:
                return json_response(error='运行健康状态筛选值不合法')
            if statuses:
                query = query.filter(health_status__in=statuses)
        if form.is_active is not None:
            query = query.filter(is_active=form.is_active)
        if form.use_unit:
            query = query.filter(use_unit__icontains=form.use_unit)
        if form.install_location:
            query = query.filter(install_location__icontains=form.install_location)

        query = self._apply_dynamic_filters(request, query)

        from libs.pagination import paginate
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [r.to_view() for r in records],
            'total': total,
            'page': page,
            'page_size': page_size,
        })

    @staticmethod
    def _apply_dynamic_filters(request, query):
        """动态字段筛选：cf_<field_id>=value，仅支持启用且可筛选的自定义字段。"""
        for key, value in request.GET.items():
            if not key.startswith('cf_') or value in ('', None):
                continue
            try:
                field_id = int(key[3:])
            except ValueError:
                continue
            field = apply_tenant_filter(ConfigFieldDefinition.objects.all(), request.user).filter(
                pk=field_id,
                scope_type=ConfigFieldDefinition.SCOPE_CUSTOM,
                is_filterable=True,
                is_active=True,
            ).first()
            if not field:
                continue
            condition = Q(config_values__field=field)
            if field.field_type == ConfigFieldDefinition.TYPE_NUMBER:
                try:
                    condition &= Q(config_values__value_number=float(value))
                except ValueError:
                    continue
            elif field.field_type == ConfigFieldDefinition.TYPE_BOOLEAN:
                if str(value).lower() in ('true', '1'):
                    condition &= Q(config_values__value_bool=True)
                elif str(value).lower() in ('false', '0'):
                    condition &= Q(config_values__value_bool=False)
                else:
                    continue
            elif field.field_type == ConfigFieldDefinition.TYPE_CHOICE:
                condition &= Q(config_values__value_text=value)
            else:
                condition &= Q(config_values__value_text__icontains=value)
            query = query.filter(condition).distinct()
        return query

    @auth('equipment_lifecycle.system.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        if isinstance(body.get('system'), dict):
            return self._create_aggregate(request, body)
        form, error = _parse_system_fields(body)
        if error:
            return json_response(error=error)
        return self._create_flat(request, form)

    def _create_flat(self, request, form):
        """旧平铺载荷：仅创建系统固定字段。"""
        install_time, enable_time, error = _validate_system_fixed_payload(request, form)
        if error:
            return json_response(error=error)
        system_code = _generate_system_code(request.user)

        with transaction.atomic():
            item = LifecycleSystem.objects.create(
                tenant_id=request.user.tenant_id,
                system_code=system_code,
                name=form.name.strip(),
                system_model=form.system_model.strip(),
                install_location=form.install_location.strip(),
                geo_coordinate=(form.geo_coordinate or '').strip(),
                system_purpose=(form.system_purpose or '').strip()[:500],
                manufacturer=form.manufacturer.strip(),
                install_unit=form.install_unit.strip(),
                use_unit=form.use_unit.strip(),
                install_time=install_time,
                enable_time=enable_time,
                responsible_user_name=form.responsible_user_name.strip(),
                health_status=LifecycleSystem.HEALTH_NORMAL,
                is_active=True,
                remark=(form.remark or '').strip()[:1000],
                created_by=request.user,
            )
            services.record_config_change(item, SystemConfigChange.SOURCE_SYSTEM,
                                          SystemConfigChange.ACTION_CREATE, [], request.user)
            record_audit_event(request, 'create', AUDIT_TARGET_SYSTEM, item.id, item.name,
                               after_value={'system_code': item.system_code, 'name': item.name})
        return json_response(item.to_view())

    def _create_aggregate(self, request, body):
        """结构化聚合创建：系统固定字段 + 内联自定义字段 + 组成项一次提交。

        所有校验在写入前完成；写操作在单事务内执行，任何一步失败整体回滚，
        不会留下只有系统、没有字段值，或只有字段定义、没有系统的半成品数据。
        """
        form, error = _parse_system_fields(body.get('system'))
        if error:
            return json_response(error=error)
        install_time, enable_time, error = _validate_system_fixed_payload(request, form)
        if error:
            return json_response(error=error)
        system_code = _generate_system_code(request.user)

        custom_fields_payload = body.get('custom_fields')
        components_payload = body.get('components')
        if custom_fields_payload is not None and not isinstance(custom_fields_payload, list):
            return json_response(error='custom_fields 必须为数组')
        if components_payload is not None and not isinstance(components_payload, list):
            return json_response(error='components 必须为数组')
        custom_fields_payload = custom_fields_payload or []
        components_payload = components_payload or []

        if custom_fields_payload and not request.user.has_perms(
                ['equipment_lifecycle.system_config.field']):
            return json_response(error='无自定义字段管理权限，不能在新增系统时创建字段定义')

        # ---- 校验内联自定义字段定义与值（field_code 由后端生成） ----
        custom_specs = []
        seen_keys, seen_names = set(), set()
        for item in custom_fields_payload:
            if not isinstance(item, dict):
                return json_response(error='custom_fields 条目格式不正确')
            client_key = str(item.get('client_key') or '').strip()
            if not client_key:
                return json_response(error='自定义字段缺少 client_key')
            if client_key in seen_keys:
                return json_response(error=f'client_key 重复：{client_key}')
            seen_keys.add(client_key)
            form_obj, error = _build_inline_field_form(item)
            if error:
                return json_response(error=error)
            name = form_obj.display_name
            if name in seen_names:
                return json_response(error=f'自定义字段名称重复：{name}')
            seen_names.add(name)
            form_obj.field_code = _generate_field_code(name, request.user.tenant_id,
                                                       custom_system_id=0)
            # 伪归属对象：id=0 时自定义作用域查询必为空（新建系统尚无已有字段）
            pseudo_owner = SimpleNamespace(
                tenant_id=request.user.tenant_id, id=0)
            error = _validate_field_definition_payload(
                form_obj, ConfigFieldDefinition.SCOPE_CUSTOM, pseudo_owner)
            if error:
                return json_response(error=f'自定义字段「{name}」：{error}')
            transient = ConfigFieldDefinition(
                field_type=form_obj.field_type, choices=form_obj.choices,
                number_min=form_obj.number_min, number_max=form_obj.number_max,
                text_regex=form_obj.text_regex)
            value = item.get('value')
            storage, display, error = services.normalize_field_value(transient, value)
            if error:
                return json_response(error=f'自定义字段「{name}」：{error}')
            if item.get('required') and display == '':
                return json_response(error=f'自定义字段「{name}」为必填项，请同时填写字段值')
            custom_specs.append({
                'client_key': client_key,
                'field_code': form_obj.field_code,
                'display_name': name,
                'field_type': form_obj.field_type,
                'help_text': form_obj.help_text,
                'display_order': item.get('display_order') if isinstance(item.get('display_order'), int) else 1000,
                'is_required': bool(item.get('required')),
                'choices': form_obj.choices,
                'number_min': form_obj.number_min,
                'number_max': form_obj.number_max,
                'text_regex': form_obj.text_regex,
                'is_sensitive': bool(item.get('is_sensitive')),
                'is_exportable': bool(item.get('is_exportable')),
                'storage': storage,
                'display': display,
            })

        # ---- 校验配置组成项 ----
        component_specs = []
        for entry in components_payload:
            params, error = _validate_component_entry(entry)
            if error:
                return json_response(error=error)
            component_specs.append(params)

        # ---- 单事务写入 ----
        try:
            with transaction.atomic():
                item = LifecycleSystem.objects.create(
                    tenant_id=request.user.tenant_id,
                    system_code=system_code,
                    name=form.name.strip(),
                    system_model=form.system_model.strip(),
                    install_location=form.install_location.strip(),
                    geo_coordinate=(form.geo_coordinate or '').strip(),
                    system_purpose=(form.system_purpose or '').strip()[:500],
                    manufacturer=form.manufacturer.strip(),
                    install_unit=form.install_unit.strip(),
                    use_unit=form.use_unit.strip(),
                    install_time=install_time,
                    enable_time=enable_time,
                    responsible_user_name=form.responsible_user_name.strip(),
                    health_status=LifecycleSystem.HEALTH_NORMAL,
                    is_active=True,
                    remark=(form.remark or '').strip()[:1000],
                    created_by=request.user,
                )
                services.record_config_change(item, SystemConfigChange.SOURCE_SYSTEM,
                                              SystemConfigChange.ACTION_CREATE, [], request.user)
                value_changes = []
                field_codes = []
                for spec in custom_specs:
                    field = ConfigFieldDefinition.objects.create(
                        tenant_id=request.user.tenant_id,
                        scope_type=ConfigFieldDefinition.SCOPE_CUSTOM,
                        scope_owner_id=str(item.id),
                        system=item,
                        field_code=spec['field_code'],
                        display_name=spec['display_name'],
                        field_type=spec['field_type'],
                        help_text=spec['help_text'],
                        display_order=spec['display_order'],
                        is_required=spec['is_required'],
                        default_value='',
                        choices=spec['choices'],
                        detail_columns='',
                        number_min=spec['number_min'],
                        number_max=spec['number_max'],
                        text_regex=spec['text_regex'],
                        is_sensitive=spec['is_sensitive'],
                        is_exportable=spec['is_exportable'],
                        applies_to=ConfigFieldDefinition.APPLIES_ALL,
                        is_active=True,
                        created_by=request.user,
                    )
                    field_codes.append(field.field_code)
                    services.record_config_change(
                        item, SystemConfigChange.SOURCE_FIELD_DEF, SystemConfigChange.ACTION_CREATE,
                        [{'scope': ConfigFieldDefinition.SCOPE_CUSTOM, 'code': field.field_code,
                          'label': field.display_name, 'old': '', 'new': '新增自定义字段'}],
                        request.user)
                    if spec['display'] != '':
                        SystemConfigValue.objects.create(
                            tenant_id=item.tenant_id, system=item, field=field,
                            value_text=spec['storage'].get('value_text', ''),
                            value_number=spec['storage'].get('value_number'),
                            value_date=spec['storage'].get('value_date'),
                            value_bool=spec['storage'].get('value_bool'),
                            updated_by=request.user,
                        )
                        value_changes.append({
                            'scope': ConfigFieldDefinition.SCOPE_CUSTOM,
                            'code': field.field_code, 'label': field.display_name,
                            'old': '', 'new': spec['display']})
                if value_changes:
                    services.record_config_change(
                        item, SystemConfigChange.SOURCE_CONFIG, SystemConfigChange.ACTION_CREATE,
                        value_changes, request.user)
                component_briefs = []
                for params in component_specs:
                    comp = SystemConfigComponent.objects.create(
                        tenant_id=item.tenant_id, system=item,
                        created_by=request.user, **params)
                    component_briefs.append(_component_brief(comp))
                if component_briefs:
                    services.record_config_change(
                        item, SystemConfigChange.SOURCE_COMPONENT, SystemConfigChange.ACTION_CREATE,
                        [{'scope': 'component', 'code': '', 'label': '配置组成项',
                          'old': '', 'new': '；'.join(component_briefs)}], request.user)
                record_audit_event(request, 'create', AUDIT_TARGET_SYSTEM, item.id, item.name,
                                   after_value={'system_code': item.system_code, 'name': item.name,
                                                'custom_fields': field_codes,
                                                'components': len(component_briefs)})
        except IntegrityError:
            return json_response(error='保存失败：系统编号或字段编码冲突，请检查后重试')
        return json_response(item.to_view())

    @staticmethod
    def _check_geo(value):
        if not value:
            return None
        parts = str(value).split(',')
        if len(parts) != 2:
            return '安装经纬度格式应为: 经度,纬度'
        try:
            lng, lat = float(parts[0]), float(parts[1])
        except ValueError:
            return '安装经纬度格式应为: 经度,纬度'
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            return '安装经纬度超出有效范围'
        return None


class SystemDetailView(View):
    @auth('equipment_lifecycle.system.view')
    def get(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        data = item.to_view()
        data['created_by_name'] = item.created_by.username if item.created_by_id else ''
        data['config_components_count'] = item.components.count()
        # 基本信息统一展示：固定字段 + 系统自定义字段值（含停用字段历史值）
        fields = [f for f in services.collect_applicable_fields(item, include_inactive=True)
                  if _field_visible(f, request.user)]
        value_map = {v.field_id: v for v in SystemConfigValue.objects.filter(system=item)}
        config_fields = []
        sensitive_names = []
        for field in fields:
            record = value_map.get(field.id)
            display = services.value_to_display(field, record)
            config_fields.append({
                'id': field.id,
                'field_code': field.field_code,
                'display_name': field.display_name,
                'field_type': field.field_type,
                'field_type_text': field.FIELD_TYPE_TEXT_MAP.get(field.field_type, field.field_type),
                'scope_type': field.scope_type,
                'help_text': field.help_text,
                'display_order': field.display_order,
                'is_required': field.is_required,
                'is_sensitive': field.is_sensitive,
                'is_active': field.is_active,
                # 定义属性：供「配置字段」页签编辑定义时回填
                'choices': field.choices,
                'detail_columns': field.detail_columns,
                'default_value': field.default_value,
                'number_min': field.number_min,
                'number_max': field.number_max,
                'text_regex': field.text_regex,
                'is_searchable': field.is_searchable,
                'is_filterable': field.is_filterable,
                'is_exportable': field.is_exportable,
                'visible_roles': field.visible_roles,
                'editable_roles': field.editable_roles,
                'applies_to': field.applies_to,
                'value': services.value_to_payload(field, record),
                'display': display,
                'updated_at': record.updated_at if record else None,
                'updated_by': record.updated_by.username if record and record.updated_by_id else '',
            })
            if field.is_sensitive and field.is_active and display:
                sensitive_names.append(field.display_name)
        if sensitive_names:
            record_audit_event(request, 'other', AUDIT_TARGET_CONFIG, item.id, item.name,
                               detail={'sensitive_view': sensitive_names})
        data['config_fields'] = config_fields
        return json_response(data)

    @auth('equipment_lifecycle.system.edit')
    def put(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求数据格式不正确')
        if isinstance(body.get('system'), dict):
            return self._update_aggregate(request, item, body)
        form, error = _parse_system_fields(body)
        if error:
            return json_response(error=error)
        return self._update_flat(request, item, form)

    def _update_flat(self, request, item, form):
        """旧平铺载荷：仅更新系统固定字段。"""
        install_time, enable_time, error = _validate_system_fixed_payload(request, form)
        if error:
            return json_response(error=error)
        before = _fixed_field_snapshot(item)
        _apply_fixed_fields(item, form, install_time, enable_time, request.user)
        changes = _diff_fixed_changes(before, _fixed_field_snapshot(item))
        with transaction.atomic():
            item.save()
            if changes:
                services.record_config_change(item, SystemConfigChange.SOURCE_SYSTEM,
                                              SystemConfigChange.ACTION_UPDATE, changes, request.user)
            record_audit_event(request, 'update', AUDIT_TARGET_SYSTEM, item.id, item.name,
                               before_value={'changed': [c['label'] for c in changes]},
                               after_value={'system_code': item.system_code})
        return json_response(item.to_view())

    def _update_aggregate(self, request, item, body):
        """结构化聚合编辑：固定字段 + 已有动态字段值 + 新增自定义字段 + 组成项一次提交。

        所有校验在写入前完成；写操作在单事务内执行，任何一步失败整体回滚。
        config_values / custom_fields / components 任一键缺省时对应部分保持不变。
        """
        form, error = _parse_system_fields(body.get('system'))
        if error:
            return json_response(error=error)
        install_time, enable_time, error = _validate_system_fixed_payload(request, form)
        if error:
            return json_response(error=error)

        config_values_payload = body.get('config_values')
        custom_fields_payload = body.get('custom_fields')
        components_payload = body.get('components')
        if config_values_payload is not None and not isinstance(config_values_payload, dict):
            return json_response(error='config_values 必须为对象')
        if custom_fields_payload is not None and not isinstance(custom_fields_payload, list):
            return json_response(error='custom_fields 必须为数组')
        if components_payload is not None and not isinstance(components_payload, list):
            return json_response(error='components 必须为数组')
        custom_fields_payload = custom_fields_payload or []

        active_fields = services.collect_applicable_fields(item, include_inactive=False)
        cleaned = None
        if config_values_payload is not None:
            cleaned, errors = services.validate_config_submission(
                item, active_fields, config_values_payload, request.user)
            if errors:
                return json_response(error='；'.join(errors))

        custom_specs = []
        if custom_fields_payload:
            if not request.user.has_perms(['equipment_lifecycle.system_config.field']):
                return json_response(error='无自定义字段管理权限，不能在编辑系统时创建字段定义')
            seen_keys, seen_names = set(), set()
            for entry in custom_fields_payload:
                if not isinstance(entry, dict):
                    return json_response(error='custom_fields 条目格式不正确')
                client_key = str(entry.get('client_key') or '').strip()
                if not client_key:
                    return json_response(error='自定义字段缺少 client_key')
                if client_key in seen_keys:
                    return json_response(error=f'client_key 重复：{client_key}')
                seen_keys.add(client_key)
                form_obj, error = _build_inline_field_form(entry)
                if error:
                    return json_response(error=error)
                name = form_obj.display_name
                if name in seen_names:
                    return json_response(error=f'自定义字段名称重复：{name}')
                seen_names.add(name)
                form_obj.field_code = _generate_field_code(
                    name, item.tenant_id, custom_system_id=item.id)
                error = _validate_field_definition_payload(
                    form_obj, ConfigFieldDefinition.SCOPE_CUSTOM, item)
                if error:
                    return json_response(error=f'自定义字段「{name}」：{error}')
                transient = ConfigFieldDefinition(
                    field_type=form_obj.field_type, choices=form_obj.choices,
                    number_min=form_obj.number_min, number_max=form_obj.number_max,
                    text_regex=form_obj.text_regex)
                storage, display, error = services.normalize_field_value(
                    transient, entry.get('value'))
                if error:
                    return json_response(error=f'自定义字段「{name}」：{error}')
                if entry.get('required') and display == '':
                    return json_response(error=f'自定义字段「{name}」为必填项，请同时填写字段值')
                custom_specs.append({
                    'client_key': client_key,
                    'field_code': form_obj.field_code,
                    'display_name': name,
                    'field_type': form_obj.field_type,
                    'help_text': form_obj.help_text,
                    'display_order': entry.get('display_order')
                    if isinstance(entry.get('display_order'), int) else 1000,
                    'is_required': bool(entry.get('required')),
                    'choices': form_obj.choices,
                    'number_min': form_obj.number_min,
                    'number_max': form_obj.number_max,
                    'text_regex': form_obj.text_regex,
                    'is_sensitive': bool(entry.get('is_sensitive')),
                    'is_exportable': bool(entry.get('is_exportable')),
                    'storage': storage,
                    'display': display,
                })

        component_specs = []
        existing_comps = {}
        if components_payload is not None:
            existing_comps = {c.id: c for c in item.components.all()}
            seen_ids = set()
            for entry in components_payload:
                params, error = _validate_component_entry(entry)
                if error:
                    return json_response(error=error)
                entry_id = entry.get('id')
                if entry_id in (None, ''):
                    component_specs.append((None, params))
                    continue
                if not isinstance(entry_id, int):
                    return json_response(error='配置组成项标识不合法')
                comp = existing_comps.get(entry_id)
                if not comp:
                    return json_response(error='配置组成项不存在')
                if entry_id in seen_ids:
                    return json_response(error='配置组成项重复提交')
                seen_ids.add(entry_id)
                component_specs.append((comp, params))

        before = _fixed_field_snapshot(item)
        _apply_fixed_fields(item, form, install_time, enable_time, request.user)
        changes = _diff_fixed_changes(before, _fixed_field_snapshot(item))

        try:
            with transaction.atomic():
                item.save()
                if changes:
                    services.record_config_change(item, SystemConfigChange.SOURCE_SYSTEM,
                                                  SystemConfigChange.ACTION_UPDATE, changes,
                                                  request.user)
                # 已有动态字段值：新建/更新/清空删除，历史由变更记录保留
                config_changes = []
                if cleaned is not None:
                    existing_map = {
                        v.field_id: v for v in SystemConfigValue.objects.filter(system=item)}
                    old_display_map = {
                        fid: services.value_to_display(field, existing_map.get(fid))
                        for fid, field in ((f.id, f) for f in active_fields)
                    }
                    now = timezone.now()
                    for field in active_fields:
                        entry = cleaned.get(field.id)
                        if entry is None:
                            continue
                        storage, display = entry
                        record = existing_map.get(field.id)
                        if display == '':
                            if record is not None:
                                record.delete()
                            continue
                        if record is None:
                            SystemConfigValue.objects.create(
                                tenant_id=item.tenant_id, system=item, field=field,
                                value_text=storage.get('value_text', ''),
                                value_number=storage.get('value_number'),
                                value_date=storage.get('value_date'),
                                value_bool=storage.get('value_bool'),
                                updated_by=request.user,
                            )
                        else:
                            record.value_text = storage.get('value_text', '')
                            record.value_number = storage.get('value_number')
                            record.value_date = storage.get('value_date')
                            record.value_bool = storage.get('value_bool')
                            record.updated_at = now
                            record.updated_by = request.user
                            record.save()
                    final_map = dict(old_display_map)
                    final_map.update({fid: entry[1] for fid, entry in cleaned.items()})
                    config_changes = services.diff_changes(old_display_map, final_map, active_fields)
                    if config_changes:
                        services.record_config_change(item, SystemConfigChange.SOURCE_CONFIG,
                                                      SystemConfigChange.ACTION_UPDATE,
                                                      config_changes, request.user)
                # 本次新增的自定义字段及其值
                field_codes = []
                new_value_changes = []
                for spec in custom_specs:
                    field = ConfigFieldDefinition.objects.create(
                        tenant_id=request.user.tenant_id,
                        scope_type=ConfigFieldDefinition.SCOPE_CUSTOM,
                        scope_owner_id=str(item.id),
                        system=item,
                        field_code=spec['field_code'],
                        display_name=spec['display_name'],
                        field_type=spec['field_type'],
                        help_text=spec['help_text'],
                        display_order=spec['display_order'],
                        is_required=spec['is_required'],
                        default_value='',
                        choices=spec['choices'],
                        detail_columns='',
                        number_min=spec['number_min'],
                        number_max=spec['number_max'],
                        text_regex=spec['text_regex'],
                        is_sensitive=spec['is_sensitive'],
                        is_exportable=spec['is_exportable'],
                        applies_to=ConfigFieldDefinition.APPLIES_ALL,
                        is_active=True,
                        created_by=request.user,
                    )
                    field_codes.append(field.field_code)
                    services.record_config_change(
                        item, SystemConfigChange.SOURCE_FIELD_DEF, SystemConfigChange.ACTION_CREATE,
                        [{'scope': ConfigFieldDefinition.SCOPE_CUSTOM, 'code': field.field_code,
                          'label': field.display_name, 'old': '', 'new': '新增自定义字段'}],
                        request.user)
                    if spec['display'] != '':
                        SystemConfigValue.objects.create(
                            tenant_id=item.tenant_id, system=item, field=field,
                            value_text=spec['storage'].get('value_text', ''),
                            value_number=spec['storage'].get('value_number'),
                            value_date=spec['storage'].get('value_date'),
                            value_bool=spec['storage'].get('value_bool'),
                            updated_by=request.user,
                        )
                        new_value_changes.append({
                            'scope': ConfigFieldDefinition.SCOPE_CUSTOM,
                            'code': field.field_code, 'label': field.display_name,
                            'old': '', 'new': spec['display']})
                if new_value_changes:
                    services.record_config_change(
                        item, SystemConfigChange.SOURCE_CONFIG, SystemConfigChange.ACTION_CREATE,
                        new_value_changes, request.user)
                # 组成项全量同步：仅当请求携带 components 键时处理
                if components_payload is not None:
                    created_entries, updated_entries, deleted_entries = [], [], []
                    keep_ids = set()
                    for comp, params in component_specs:
                        if comp is not None:
                            keep_ids.add(comp.id)
                            old_brief = _component_brief(comp)
                            for attr, value in params.items():
                                setattr(comp, attr, value)
                            comp.updated_at = timezone.now()
                            comp.updated_by = request.user
                            comp.save()
                            new_brief = _component_brief(comp)
                            if old_brief != new_brief:
                                updated_entries.append({
                                    'scope': 'component', 'code': str(comp.id),
                                    'label': comp.name, 'old': old_brief, 'new': new_brief})
                        else:
                            new_comp = SystemConfigComponent.objects.create(
                                tenant_id=item.tenant_id, system=item,
                                created_by=request.user, **params)
                            created_entries.append({
                                'scope': 'component', 'code': str(new_comp.id),
                                'label': new_comp.name, 'old': '',
                                'new': _component_brief(new_comp)})
                    for cid, comp in existing_comps.items():
                        if cid not in keep_ids:
                            deleted_entries.append({
                                'scope': 'component', 'code': str(cid), 'label': comp.name,
                                'old': _component_brief(comp), 'new': ''})
                            comp.delete()
                    if created_entries:
                        services.record_config_change(
                            item, SystemConfigChange.SOURCE_COMPONENT,
                            SystemConfigChange.ACTION_CREATE, created_entries, request.user)
                    if updated_entries:
                        services.record_config_change(
                            item, SystemConfigChange.SOURCE_COMPONENT,
                            SystemConfigChange.ACTION_UPDATE, updated_entries, request.user)
                    if deleted_entries:
                        services.record_config_change(
                            item, SystemConfigChange.SOURCE_COMPONENT,
                            SystemConfigChange.ACTION_DELETE, deleted_entries, request.user)
                record_audit_event(request, 'update', AUDIT_TARGET_SYSTEM, item.id, item.name,
                                   before_value={'changed': [c['label'] for c in changes]},
                                   after_value={'system_code': item.system_code,
                                                'config_changed': len(config_changes),
                                                'custom_fields_added': field_codes,
                                                'components_synced': components_payload is not None})
        except IntegrityError:
            return json_response(error='保存失败：字段编码冲突，请检查后重试')
        return json_response(item.to_view())

    @auth('equipment_lifecycle.system.del')
    def delete(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        blockers = _collect_system_references(item)
        if blockers:
            return json_response(error='系统已被以下业务引用，不能删除：' + '、'.join(blockers))
        audit_snapshot = {
            'system_code': item.system_code, 'name': item.name,
            'config_values': item.config_values.count(),
            'components': item.components.count(),
            'changes': item.config_changes.count(),
            'snapshots': item.config_snapshots.count(),
        }
        with transaction.atomic():
            item.delete()
            record_audit_event(request, 'delete', AUDIT_TARGET_SYSTEM, item.system_code,
                               audit_snapshot['name'], before_value=audit_snapshot)
        return json_response({})


class SystemActiveView(View):
    @auth('equipment_lifecycle.system.deactivate')
    def post(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        form, error = JsonParser(
            Argument('is_active', type=bool, required=True, help='是否可用'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        if item.is_active == form.is_active:
            return json_response(error='系统状态未发生变化')
        item.is_active = form.is_active
        item.updated_at = timezone.now()
        item.updated_by = request.user
        action = SystemConfigChange.ACTION_ACTIVATE if form.is_active else SystemConfigChange.ACTION_DEACTIVATE
        with transaction.atomic():
            item.save(update_fields=['is_active', 'updated_at', 'updated_by'])
            services.record_config_change(
                item, SystemConfigChange.SOURCE_SYSTEM, action,
                [{'scope': 'fixed', 'code': 'is_active', 'label': '是否可用',
                  'old': str(not form.is_active), 'new': str(form.is_active)}],
                request.user)
            record_audit_event(request, 'update', AUDIT_TARGET_SYSTEM, item.id, item.name,
                               before_value={'is_active': not form.is_active},
                               after_value={'is_active': form.is_active})
        return json_response(item.to_view())


class SystemExportView(View):
    @auth('equipment_lifecycle.system.export')
    def get(self, request):
        query = apply_tenant_filter(LifecycleSystem.objects.all(), request.user)
        headers = ['系统编号', '系统名称', '系统型号', '安装地点', '安装经纬度',
                   '系统用途', '生产厂家', '安装单位', '使用单位', '安装时间', '启用时间',
                   '系统负责人', '运行健康状态', '是否可用', '备注', '创建时间']
        rows = []
        for item in query:
            rows.append([
                item.system_code, item.name, item.system_model,
                item.install_location, item.geo_coordinate, item.system_purpose,
                item.manufacturer, item.install_unit, item.use_unit,
                item.install_time.strftime('%Y-%m-%d %H:%M') if item.install_time else '',
                item.enable_time.strftime('%Y-%m-%d %H:%M') if item.enable_time else '',
                item.responsible_user_name,
                item.HEALTH_STATUS_TEXT_MAP.get(item.health_status, item.health_status),
                '是' if item.is_active else '否', item.remark,
                item.created_at.strftime('%Y-%m-%d %H:%M'),
            ])
        record_audit_event(request, 'export', AUDIT_TARGET_SYSTEM, '', '',
                           detail={'count': len(rows)})
        return _csv_response('el_systems', headers, rows)


class SystemStatusSummaryView(View):
    """当前运行状态汇总（只读聚合，供"履历与状态→当前运行状态"页面）。

    - 按健康状态统计本租户系统数量（含停用系统单独计数）；
    - 健康状态唯一来源为 fault_services 计算（步骤 3.5 收口），本视图只读。
    """

    @auth('equipment_lifecycle.system.view')
    def get(self, request):
        query = apply_tenant_filter(LifecycleSystem.objects.all(), request.user)
        summary = {status: 0 for status, _ in LifecycleSystem.HEALTH_STATUS_CHOICES}
        for row in query.values('health_status').annotate(n=models.Count('id')):
            summary[row['health_status']] = row['n']
        return json_response({
            'summary': summary,
            'total': sum(summary.values()),
            'active_total': query.filter(is_active=True).count(),
            'inactive_total': query.filter(is_active=False).count(),
        })


class SystemFormFieldsView(View):
    """编辑系统表单的动态字段与组成项加载。

    ?system=<id>：返回适用字段（自定义字段，含停用字段历史值）、
    当前值与已有配置组成项，供一次提交聚合编辑。
    """

    @auth('equipment_lifecycle.system.view')
    def get(self, request):
        system_param = request.GET.get('system')
        values = {}
        components = []
        system_info = None
        if not system_param:
            return json_response(error='缺少 system 参数')
        try:
            system_id = int(system_param)
        except (TypeError, ValueError):
            return json_response(error='system 参数不合法')
        item = _get_system_for_user(system_id, request.user)
        if not item:
            return json_response(error='系统不存在')
        fields = [f for f in services.collect_applicable_fields(item, include_inactive=True)
                  if _field_visible(f, request.user)]
        value_map = {v.field_id: v for v in SystemConfigValue.objects.filter(system=item)}
        sensitive_names = []
        for field in fields:
            record = value_map.get(field.id)
            display = services.value_to_display(field, record)
            values[str(field.id)] = {
                'value': services.value_to_payload(field, record),
                'display': display,
            }
            if field.is_sensitive and field.is_active and display:
                sensitive_names.append(field.display_name)
        if sensitive_names:
            record_audit_event(request, 'other', AUDIT_TARGET_CONFIG, item.id, item.name,
                               detail={'sensitive_view': sensitive_names})
        components = [c.to_view() for c in item.components.all()]
        system_info = {'id': item.id, 'system_code': item.system_code, 'name': item.name}
        return json_response({
            'data': [_serialize_field(f) for f in fields],
            'values': values,
            'components': components,
            'system': system_info,
        })


class SystemConfigView(View):
    @auth('equipment_lifecycle.system_config.view')
    def get(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        fields = services.collect_applicable_fields(item, include_inactive=True)
        visible_fields = [f for f in fields if _field_visible(f, request.user)]
        value_map = {
            v.field_id: v for v in SystemConfigValue.objects.filter(system=item)
        }
        values = {}
        for field in visible_fields:
            record = value_map.get(field.id)
            values[str(field.id)] = {
                'value': services.value_to_payload(field, record),
                'display': services.value_to_display(field, record),
                'updated_at': record.updated_at if record else None,
                'updated_by': record.updated_by.username if record and record.updated_by_id else '',
            }
        sensitive_codes = [
            f.display_name for f in visible_fields
            if f.is_sensitive and f.is_active and values[str(f.id)]['display']
        ]
        if sensitive_codes:
            record_audit_event(request, 'other', AUDIT_TARGET_CONFIG, item.id, item.name,
                               detail={'sensitive_view': sensitive_codes})
        return json_response({
            'system': {'id': item.id, 'system_code': item.system_code, 'name': item.name,
                       'system_created_at': item.created_at},
            'fields': [_serialize_field(f) for f in visible_fields],
            'values': values,
        })

    @auth('equipment_lifecycle.system_config.edit')
    def put(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        form, error = JsonParser(
            # 键名避开 dict.values 等内建方法（AttrDict 属性访问优先命中内建方法）
            Argument('config_values', type=dict, required=True, help='配置值'),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        active_fields = services.collect_applicable_fields(item, include_inactive=False)
        cleaned, errors = services.validate_config_submission(item, active_fields, form.config_values, request.user)
        if errors:
            return json_response(error='；'.join(errors))

        existing_map = {
            v.field_id: v for v in SystemConfigValue.objects.filter(system=item)
        }
        old_display_map = {
            fid: services.value_to_display(field, existing_map.get(fid))
            for fid, field in ((f.id, f) for f in active_fields)
        }

        now = timezone.now()
        with transaction.atomic():
            for field in active_fields:
                entry = cleaned.get(field.id)
                if entry is None:
                    continue
                storage, display = entry
                record = existing_map.get(field.id)
                if display == '':
                    # 清空提交：删除值行；历史由 SystemConfigChange 前后值保留
                    if record is not None:
                        record.delete()
                    continue
                if record is None:
                    SystemConfigValue.objects.create(
                        tenant_id=item.tenant_id,
                        system=item,
                        field=field,
                        value_text=storage.get('value_text', ''),
                        value_number=storage.get('value_number'),
                        value_date=storage.get('value_date'),
                        value_bool=storage.get('value_bool'),
                        updated_by=request.user,
                    )
                else:
                    record.value_text = storage.get('value_text', '')
                    record.value_number = storage.get('value_number')
                    record.value_date = storage.get('value_date')
                    record.value_bool = storage.get('value_bool')
                    record.updated_at = now
                    record.updated_by = request.user
                    record.save()
            new_display_map = {fid: entry[1] for fid, entry in cleaned.items()}
            # 组装保存后的完整展示值（含本次未提交字段的现状）
            final_map = dict(old_display_map)
            final_map.update(new_display_map)
            changes = services.diff_changes(old_display_map, final_map, active_fields)
            if changes:
                services.record_config_change(item, SystemConfigChange.SOURCE_CONFIG,
                                              SystemConfigChange.ACTION_UPDATE, changes, request.user)
            record_audit_event(request, 'update', AUDIT_TARGET_CONFIG, item.id, item.name,
                               before_value={'changed_fields': [c['label'] for c in changes]})
        return json_response({'saved': True, 'changed': len(changes)})


class SystemConfigExportView(View):
    @auth('equipment_lifecycle.system_config.export')
    def get(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        fields = [f for f in services.collect_applicable_fields(item, include_inactive=True)
                  if _field_visible(f, request.user)]
        value_map = {v.field_id: v for v in SystemConfigValue.objects.filter(system=item)}
        headers = ['字段编码', '显示名称', '来源', '类型', '值']
        rows = []
        for field in fields:
            if not field.is_exportable:
                continue
            record = value_map.get(field.id)
            rows.append([
                field.field_code, field.display_name,
                '系统自定义',
                field.FIELD_TYPE_TEXT_MAP.get(field.field_type, field.field_type),
                services.value_to_display(field, record),
            ])
        record_audit_event(request, 'export', AUDIT_TARGET_CONFIG, item.id, item.name,
                           detail={'count': len(rows)})
        return _csv_response(f'el_system_config_{item.system_code}', headers, rows)


class SystemComponentView(View):
    @auth('equipment_lifecycle.system_config.view')
    def get(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        return json_response({'data': [c.to_view() for c in item.components.all()]})

    @auth('equipment_lifecycle.system_config.edit')
    def post(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        form, error = JsonParser(
            Argument('name', type=str, required=True, help='组成项名称'),
            Argument('category', type=str, required=False, default=''),
            Argument('model_version', type=str, required=False, default=''),
            Argument('quantity', type=int, required=False),
            Argument('purpose', type=str, required=False, default=''),
            Argument('asset_sn', type=str, required=False, default=''),
            Argument('external_ref', type=str, required=False, default=''),
            Argument('remark', type=str, required=False, default=''),
            Argument('display_order', type=int, required=False, default=0),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        if not form.name.strip():
            return json_response(error='组成项名称不能为空')
        if form.quantity is not None and form.quantity < 0:
            return json_response(error='数量不能为负数')
        with transaction.atomic():
            comp = SystemConfigComponent.objects.create(
                tenant_id=item.tenant_id,
                system=item,
                name=form.name.strip()[:100],
                category=(form.category or '').strip()[:50],
                model_version=(form.model_version or '').strip()[:100],
                quantity=form.quantity,
                purpose=(form.purpose or '').strip()[:200],
                asset_sn=(form.asset_sn or '').strip()[:100],
                external_ref=(form.external_ref or '').strip()[:200],
                remark=(form.remark or '').strip()[:500],
                display_order=form.display_order,
                created_by=request.user,
            )
            services.record_config_change(
                item, SystemConfigChange.SOURCE_COMPONENT, SystemConfigChange.ACTION_CREATE,
                [{'scope': 'component', 'code': str(comp.id), 'label': '配置组成项',
                  'old': '', 'new': _component_brief(comp)}],
                request.user)
            record_audit_event(request, 'create', AUDIT_TARGET_CONFIG, item.id, item.name,
                               after_value={'action': 'add_component', 'name': comp.name})
        return json_response(comp.to_view())


class SystemComponentDetailView(View):
    @auth('equipment_lifecycle.system_config.edit')
    def put(self, request, pk, cid):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        comp = apply_tenant_filter(SystemConfigComponent.objects.all(), request.user).filter(
            pk=cid, system=item).first()
        if not comp:
            return json_response(error='配置组成项不存在')
        form, error = JsonParser(
            Argument('name', type=str, required=True, help='组成项名称'),
            Argument('category', type=str, required=False, default=''),
            Argument('model_version', type=str, required=False, default=''),
            Argument('quantity', type=int, required=False),
            Argument('purpose', type=str, required=False, default=''),
            Argument('asset_sn', type=str, required=False, default=''),
            Argument('external_ref', type=str, required=False, default=''),
            Argument('remark', type=str, required=False, default=''),
            Argument('display_order', type=int, required=False, default=0),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        if not form.name.strip():
            return json_response(error='组成项名称不能为空')
        if form.quantity is not None and form.quantity < 0:
            return json_response(error='数量不能为负数')
        old_brief = _component_brief(comp)
        comp.name = form.name.strip()[:100]
        comp.category = (form.category or '').strip()[:50]
        comp.model_version = (form.model_version or '').strip()[:100]
        comp.quantity = form.quantity
        comp.purpose = (form.purpose or '').strip()[:200]
        comp.asset_sn = (form.asset_sn or '').strip()[:100]
        comp.external_ref = (form.external_ref or '').strip()[:200]
        comp.remark = (form.remark or '').strip()[:500]
        comp.display_order = form.display_order
        comp.updated_at = timezone.now()
        comp.updated_by = request.user
        with transaction.atomic():
            comp.save()
            new_brief = _component_brief(comp)
            if old_brief != new_brief:
                services.record_config_change(
                    item, SystemConfigChange.SOURCE_COMPONENT, SystemConfigChange.ACTION_UPDATE,
                    [{'scope': 'component', 'code': str(comp.id), 'label': comp.name,
                      'old': old_brief, 'new': new_brief}],
                    request.user)
            record_audit_event(request, 'update', AUDIT_TARGET_CONFIG, item.id, item.name,
                               after_value={'action': 'edit_component', 'name': comp.name})
        return json_response(comp.to_view())

    @auth('equipment_lifecycle.system_config.edit')
    def delete(self, request, pk, cid):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        comp = apply_tenant_filter(SystemConfigComponent.objects.all(), request.user).filter(
            pk=cid, system=item).first()
        if not comp:
            return json_response(error='配置组成项不存在')
        brief = _component_brief(comp)
        with transaction.atomic():
            comp.delete()
            services.record_config_change(
                item, SystemConfigChange.SOURCE_COMPONENT, SystemConfigChange.ACTION_DELETE,
                [{'scope': 'component', 'code': str(comp.id), 'label': comp.name,
                  'old': brief, 'new': ''}],
                request.user)
            record_audit_event(request, 'delete', AUDIT_TARGET_CONFIG, item.id, item.name,
                               before_value={'action': 'delete_component', 'name': comp.name})
        return json_response({})


class CustomFieldView(View):
    @auth('equipment_lifecycle.system_config.view')
    def get(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        fields = item.custom_fields.all()
        return json_response({'data': [_serialize_field(f) for f in fields]})

    @auth('equipment_lifecycle.system_config.field')
    def post(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        form, error = _parse_field_definition(request, code_required=False)
        if error:
            return json_response(error=error)
        if not (form.field_code or '').strip():
            # 字段编码留空时由后端按显示名称生成稳定编码
            form.field_code = _generate_field_code(
                form.display_name, request.user.tenant_id, custom_system_id=item.id)
        err = _validate_field_definition_payload(form, ConfigFieldDefinition.SCOPE_CUSTOM, item)
        if err:
            return json_response(error=err)
        with transaction.atomic():
            field = ConfigFieldDefinition.objects.create(
                tenant_id=request.user.tenant_id,
                scope_type=ConfigFieldDefinition.SCOPE_CUSTOM,
                scope_owner_id=str(item.id),
                system=item,
                field_code=(form.field_code or '').strip(),
                display_name=(form.display_name or '').strip(),
                field_type=form.field_type,
                help_text=(form.help_text or '').strip()[:200],
                display_order=form.display_order,
                is_required=form.is_required,
                default_value=(form.default_value or '').strip(),
                choices=(form.choices or '').strip(),
                detail_columns=(form.detail_columns or '').strip(),
                number_min=form.number_min,
                number_max=form.number_max,
                text_regex=(form.text_regex or '').strip()[:200],
                is_searchable=form.is_searchable,
                is_filterable=form.is_filterable,
                is_exportable=form.is_exportable,
                visible_roles=(form.visible_roles or '').strip(),
                editable_roles=(form.editable_roles or '').strip(),
                is_sensitive=form.is_sensitive,
                applies_to=ConfigFieldDefinition.APPLIES_ALL,
                is_active=True,
                created_by=request.user,
            )
            services.record_config_change(
                item, SystemConfigChange.SOURCE_FIELD_DEF, SystemConfigChange.ACTION_CREATE,
                [{'scope': ConfigFieldDefinition.SCOPE_CUSTOM, 'code': field.field_code,
                  'label': field.display_name, 'old': '', 'new': '新增自定义字段'}],
                request.user)
            record_audit_event(request, 'create', AUDIT_TARGET_CONFIG, item.id, item.name,
                               after_value={'action': 'add_custom_field',
                                            'field_code': field.field_code,
                                            'display_name': field.display_name})
        return json_response(_serialize_field(field))


class CustomFieldDetailView(View):
    @auth('equipment_lifecycle.system_config.field')
    def put(self, request, pk, fid):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        field = _get_field_for_user(fid, request.user)
        if not field or field.scope_type != ConfigFieldDefinition.SCOPE_CUSTOM \
                or field.scope_owner_id != str(item.id):
            return json_response(error='自定义字段不存在')
        form, error = _parse_field_definition(request)
        if error:
            return json_response(error=error)
        form.pk = field.pk
        err = _validate_field_definition_payload(form, ConfigFieldDefinition.SCOPE_CUSTOM, item)
        if err:
            return json_response(error=err)
        err = _check_existing_field_values(field, form)
        if err:
            return json_response(error=err)
        before_active = field.is_active
        field.display_name = (form.display_name or '').strip()
        field.help_text = (form.help_text or '').strip()[:200]
        field.display_order = form.display_order
        field.is_required = form.is_required
        field.default_value = (form.default_value or '').strip()
        field.choices = (form.choices or '').strip()
        field.detail_columns = (form.detail_columns or '').strip()
        field.number_min = form.number_min
        field.number_max = form.number_max
        field.text_regex = (form.text_regex or '').strip()[:200]
        field.is_searchable = form.is_searchable
        field.is_filterable = form.is_filterable
        field.is_exportable = form.is_exportable
        field.visible_roles = (form.visible_roles or '').strip()
        field.editable_roles = (form.editable_roles or '').strip()
        field.is_sensitive = form.is_sensitive
        field.is_active = form.is_active
        field.updated_at = timezone.now()
        field.updated_by = request.user
        with transaction.atomic():
            field.save()
            if before_active and not field.is_active:
                services.record_config_change(
                    item, SystemConfigChange.SOURCE_FIELD_DEF, SystemConfigChange.ACTION_DEACTIVATE,
                    [{'scope': ConfigFieldDefinition.SCOPE_CUSTOM, 'code': field.field_code,
                      'label': field.display_name, 'old': '启用', 'new': '停用'}],
                    request.user)
            elif not before_active and field.is_active:
                services.record_config_change(
                    item, SystemConfigChange.SOURCE_FIELD_DEF, SystemConfigChange.ACTION_ACTIVATE,
                    [{'scope': ConfigFieldDefinition.SCOPE_CUSTOM, 'code': field.field_code,
                      'label': field.display_name, 'old': '停用', 'new': '启用'}],
                    request.user)
            record_audit_event(request, 'update', AUDIT_TARGET_CONFIG, item.id, item.name,
                               after_value={'action': 'edit_custom_field',
                                            'field_code': field.field_code,
                                            'is_active': field.is_active})
        return json_response(_serialize_field(field))

    @auth('equipment_lifecycle.system_config.field')
    def delete(self, request, pk, fid):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        field = _get_field_for_user(fid, request.user)
        if not field or field.scope_type != ConfigFieldDefinition.SCOPE_CUSTOM \
                or field.scope_owner_id != str(item.id):
            return json_response(error='自定义字段不存在')
        if SystemConfigValue.objects.filter(field=field).exists():
            return json_response(error='该字段已有历史值，不能删除；请停用以保留历史值')
        with transaction.atomic():
            field.delete()
            services.record_config_change(
                item, SystemConfigChange.SOURCE_FIELD_DEF, SystemConfigChange.ACTION_DELETE,
                [{'scope': ConfigFieldDefinition.SCOPE_CUSTOM, 'code': field.field_code,
                  'label': field.display_name, 'old': '存在', 'new': '已删除（无历史值）'}],
                request.user)
            record_audit_event(request, 'delete', AUDIT_TARGET_CONFIG, item.id, item.name,
                               before_value={'action': 'delete_custom_field',
                                             'field_code': field.field_code})
        return json_response({})


class SystemChangeView(View):
    @auth('equipment_lifecycle.system_config.view')
    def get(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        query = item.config_changes.all()
        source = request.GET.get('source')
        if source:
            query = query.filter(source=source)
        from libs.pagination import paginate
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [c.to_view() for c in records],
            'total': total, 'page': page, 'page_size': page_size,
        })


class SystemSnapshotView(View):
    @auth('equipment_lifecycle.system_config.view')
    def get(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        from libs.pagination import paginate
        page, page_size = paginate(request)
        query = item.config_snapshots.all()
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size]
        return json_response({
            'data': [s.to_view() for s in records],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.system_config.snapshot')
    def post(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        form, error = JsonParser(
            Argument('name', type=str, required=True, help='快照名称'),
            Argument('remark', type=str, required=False, default=''),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        name = form.name.strip()
        if not name:
            return json_response(error='快照名称不能为空')
        content = services.build_snapshot_content(item)
        content_text = json.dumps(content, ensure_ascii=False, sort_keys=True)
        with transaction.atomic():
            snapshot = SystemConfigSnapshot.objects.create(
                tenant_id=item.tenant_id,
                system=item,
                name=name[:100],
                remark=(form.remark or '').strip()[:500],
                content=content_text,
                content_hash=hashlib.sha256(content_text.encode('utf-8')).hexdigest(),
                created_by=request.user,
            )
            # 步骤 3.4：配置快照生成进入系统履历（同一事务）
            from apps.equipment_lifecycle import event_services
            event_services.record_snapshot_event(item, snapshot, created_by=request.user)
            record_audit_event(request, 'create', AUDIT_TARGET_CONFIG, item.id, item.name,
                               after_value={'action': 'create_snapshot', 'name': snapshot.name,
                                            'content_hash': snapshot.content_hash})
        return json_response(snapshot.to_view())


class SystemSnapshotDetailView(View):
    @auth('equipment_lifecycle.system_config.view')
    def get(self, request, pk, sid):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        snapshot = apply_tenant_filter(SystemConfigSnapshot.objects.all(), request.user).filter(
            pk=sid, system=item).first()
        if not snapshot:
            return json_response(error='配置快照不存在')
        try:
            base_content = json.loads(snapshot.content)
        except (ValueError, TypeError):
            return json_response(error='快照内容已损坏')

        target_param = request.GET.get('target', 'current')
        if target_param == 'current':
            target_content = services.build_snapshot_content(item)
            target_label = '当前配置'
        else:
            try:
                other_id = int(target_param)
            except ValueError:
                return json_response(error='比较目标不合法')
            other = apply_tenant_filter(SystemConfigSnapshot.objects.all(), request.user).filter(
                pk=other_id, system=item).exclude(pk=snapshot.pk).first()
            if not other:
                return json_response(error='比较目标快照不存在')
            try:
                target_content = json.loads(other.content)
            except (ValueError, TypeError):
                return json_response(error='比较目标快照内容已损坏')
            target_label = other.name
        return json_response({
            'snapshot': snapshot.to_view(),
            'target': {'label': target_label},
            'diffs': services.diff_content(base_content, target_content),
        })


def _csv_response(filename_prefix, headers, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    response = HttpResponse('\ufeff' + buf.getvalue(), content_type='text/csv; charset=utf-8')
    stamp = timezone.now().strftime('%Y%m%d%H%M%S')
    response['Content-Disposition'] = f"attachment; filename={filename_prefix}_{stamp}.csv"
    return response


class SystemConfigAttachmentView(View):
    """配置档案附件（attachment 类型动态字段）列表与上传。

    归属校验遵循项目附件范式：module/object_type 固定为本模块常量，
    附件归属租户取系统记录的租户（服务端可信值，不采信 HTTP 参数）。
    """

    @auth('equipment_lifecycle.system_config.view')
    def get(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        attachments = AttachmentService.list(
            request.user, EL_ATTACHMENT_MODULE, EL_ATTACHMENT_OBJECT_TYPE, item.id)
        return json_response({'data': attachments})

    @auth('equipment_lifecycle.system_config.edit')
    def post(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        file = request.FILES.get('file')
        if not file:
            return json_response(error='缺少上传文件')
        att, error = AttachmentService.upload(
            file, request.user, EL_ATTACHMENT_MODULE, EL_ATTACHMENT_OBJECT_TYPE,
            item.id, config=DefaultAttachmentConfig, owner_tenant_id=item.tenant_id)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'create', AUDIT_TARGET_CONFIG, item.id, item.name,
                           after_value={'action': 'upload_config_attachment',
                                        'file_name': att.file_name})
        return json_response(att.to_view())


class SystemConfigAttachmentDetailView(View):
    @auth('equipment_lifecycle.system_config.edit')
    def delete(self, request, pk, aid):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        # 先做本系统归属校验（object_id），再走服务统一软删除留痕
        att = apply_tenant_filter(
            EvidenceAttachment.objects.filter(is_deleted=False), request.user
        ).filter(pk=aid, module=EL_ATTACHMENT_MODULE,
                 object_type=EL_ATTACHMENT_OBJECT_TYPE,
                 object_id=str(item.id)).first()
        if not att:
            return json_response(error=ATTACHMENT_DELETE_DENIED_ERROR)
        error = AttachmentService.soft_delete(
            request.user, aid, EL_ATTACHMENT_MODULE, EL_ATTACHMENT_OBJECT_TYPE,
            reason='系统配置档案附件删除')
        if error:
            return json_response(error=error)
        record_audit_event(request, 'delete', AUDIT_TARGET_CONFIG, item.id, item.name,
                           before_value={'action': 'delete_config_attachment',
                                         'file_name': att.file_name})
        return json_response({})


class SystemConfigAttachmentDownloadView(View):
    @auth('equipment_lifecycle.system_config.view')
    def get(self, request, pk, aid):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        response, error = AttachmentService.download_response(
            request.user, aid, EL_ATTACHMENT_MODULE, EL_ATTACHMENT_OBJECT_TYPE)
        if error:
            return json_response(error=error)
        return response

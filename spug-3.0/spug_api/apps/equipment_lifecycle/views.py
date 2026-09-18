# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——系统主数据与配置档案视图（步骤二）。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.system.view|add|edit|del|deactivate|export
- equipment_lifecycle.system_type.view|add|edit|del
- equipment_lifecycle.system_config.view|edit|field|snapshot|export

所有写操作记录业务审计（record_audit_event）与配置变更历史；
所有查询经租户过滤（apply_tenant_filter / TenantModelManager.for_user）。
"""
import csv
import hashlib
import io
import json
import re
from datetime import datetime

from django.db import transaction
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
    SystemType,
)
from apps.equipment_lifecycle import services

AUDIT_TARGET_SYSTEM = 'el_system'
AUDIT_TARGET_TYPE = 'el_system_type'
AUDIT_TARGET_CONFIG = 'el_system_config'

# 配置档案附件归属标识（动态字段 attachment 类型的物理存储归属）
EL_ATTACHMENT_MODULE = 'equipment_lifecycle'
EL_ATTACHMENT_OBJECT_TYPE = 'el_system_config'

FIELD_CODE_PATTERN = re.compile(r'^[a-z][a-z0-9_]{0,49}$')

# 固定核心字段：动态字段不得与其重名（编码与显示名称双向占用）
RESERVED_FIELD_CODES = {
    'system_code', 'name', 'system_type', 'system_model', 'install_location',
    'geo_coordinate', 'system_purpose', 'manufacturer', 'install_unit',
    'use_unit', 'install_time', 'enable_time', 'responsible_user_name',
    'health_status', 'is_active', 'remark', 'id', 'created_at', 'updated_at',
}
RESERVED_FIELD_LABELS = {
    '系统编号', '系统名称', '系统类型', '系统型号', '安装地点', '安装经纬度',
    '系统用途', '生产厂家', '安装单位', '使用单位', '安装时间', '启用时间',
    '系统负责人', '运行健康状态', '是否可用', '备注',
}

DATETIME_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d')


def _parse_datetime(value):
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    return None


def _get_system_for_user(pk, user):
    return apply_tenant_filter(
        LifecycleSystem.objects.all().select_related('system_type'), user
    ).filter(pk=pk).first()


def _get_type_for_user(pk, user):
    return apply_tenant_filter(SystemType.objects.all(), user).filter(pk=pk).first()


def _get_field_for_user(pk, user):
    return apply_tenant_filter(ConfigFieldDefinition.objects.all(), user).filter(pk=pk).first()


def _collect_system_references(system):
    """删除保护：返回引用该系统的业务对象描述列表，非空则禁止物理删除。

    步骤二暂无外部业务引用（故障/工单/台账/履历在步骤三接入）；
    步骤三实现时在此追加对应查询，保持 fail-closed 语义。
    """
    return []


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

    # 重名校验：同一作用范围内字段编码与显示名称均不得重复（不得与固定字段或模板字段重名）
    dup_query = ConfigFieldDefinition.objects.filter(
        tenant_id=owner_obj.tenant_id,
        scope_type=scope_type,
        scope_owner_id=str(owner_obj.id),
    ).filter(Q(field_code=code) | Q(display_name=label))
    if getattr(form, 'pk', None):
        dup_query = dup_query.exclude(pk=form.pk)
    if dup_query.exists():
        return '字段编码或显示名称与现有字段重复'
    # 自定义字段还不得与所属系统类型的模板字段重名
    if scope_type == ConfigFieldDefinition.SCOPE_CUSTOM and getattr(owner_obj, 'system_type_id', None):
        template_dup = ConfigFieldDefinition.objects.filter(
            tenant_id=owner_obj.tenant_id,
            scope_type=ConfigFieldDefinition.SCOPE_TEMPLATE,
            scope_owner_id=str(owner_obj.system_type_id),
        ).filter(Q(field_code=code) | Q(display_name=label)).exists()
        if template_dup:
            return '字段编码或显示名称与该类型的模板字段重复'
    return None


class SystemTypeView(View):
    @auth('equipment_lifecycle.system_type.view')
    def get(self, request):
        types = apply_tenant_filter(SystemType.objects.all(), request.user)
        if request.GET.get('active_only'):
            types = types.filter(is_active=True)
        data = []
        for item in types:
            row = item.to_view()
            row['systems_count'] = item.systems.count()
            row['template_fields_count'] = item.template_fields.filter(is_active=True).count()
            data.append(row)
        return json_response({'data': data})

    @auth('equipment_lifecycle.system_type.add')
    def post(self, request):
        form, error = JsonParser(
            Argument('name', type=str, required=True, help='系统类型名称'),
            Argument('description', type=str, required=False, default=''),
            Argument('display_order', type=int, required=False, default=0),
            Argument('is_active', type=bool, required=False, default=True),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        name = form.name.strip()
        if not name:
            return json_response(error='系统类型名称不能为空')
        dup = apply_tenant_filter(SystemType.objects.all(), request.user).filter(name=name).exists()
        if dup:
            return json_response(error='已存在同名系统类型')
        with transaction.atomic():
            item = SystemType.objects.create(
                tenant_id=request.user.tenant_id,
                name=name,
                description=(form.description or '').strip()[:500],
                display_order=form.display_order,
                is_active=form.is_active,
                created_by=request.user,
            )
            record_audit_event(request, 'create', AUDIT_TARGET_TYPE, item.id, item.name,
                               after_value={'name': item.name, 'is_active': item.is_active})
        return json_response(item.to_view())


class SystemTypeDetailView(View):
    @auth('equipment_lifecycle.system_type.edit')
    def put(self, request, pk):
        item = _get_type_for_user(pk, request.user)
        if not item:
            return json_response(error='系统类型不存在')
        form, error = JsonParser(
            Argument('name', type=str, required=True, help='系统类型名称'),
            Argument('description', type=str, required=False, default=''),
            Argument('display_order', type=int, required=False, default=0),
            Argument('is_active', type=bool, required=False, default=True),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        name = form.name.strip()
        if not name:
            return json_response(error='系统类型名称不能为空')
        dup = apply_tenant_filter(SystemType.objects.all(), request.user).filter(name=name).exclude(pk=item.pk).exists()
        if dup:
            return json_response(error='已存在同名系统类型')
        before = {'name': item.name, 'description': item.description,
                  'display_order': item.display_order, 'is_active': item.is_active}
        item.name = name
        item.description = (form.description or '').strip()[:500]
        item.display_order = form.display_order
        item.is_active = form.is_active
        item.updated_at = timezone.now()
        item.updated_by = request.user
        with transaction.atomic():
            item.save(update_fields=['name', 'description', 'display_order', 'is_active',
                                     'updated_at', 'updated_by'])
            record_audit_event(request, 'update', AUDIT_TARGET_TYPE, item.id, item.name,
                               before_value=before,
                               after_value={'name': item.name, 'description': item.description,
                                            'display_order': item.display_order, 'is_active': item.is_active})
        return json_response(item.to_view())

    @auth('equipment_lifecycle.system_type.del')
    def delete(self, request, pk):
        item = _get_type_for_user(pk, request.user)
        if not item:
            return json_response(error='系统类型不存在')
        if item.systems.exists():
            return json_response(error='该类型下已存在系统，不能删除')
        if item.template_fields.exists():
            return json_response(error='该类型下存在字段模板，请先删除或停用全部模板字段')
        with transaction.atomic():
            item.delete()
            record_audit_event(request, 'delete', AUDIT_TARGET_TYPE, item.id, item.name,
                               before_value={'name': item.name})
        return json_response({})


class TypeFieldView(View):
    @auth('equipment_lifecycle.system_type.view')
    def get(self, request, pk):
        item = _get_type_for_user(pk, request.user)
        if not item:
            return json_response(error='系统类型不存在')
        fields = item.template_fields.all()
        return json_response({'data': [_serialize_field(f) for f in fields]})

    @auth('equipment_lifecycle.system_type.add')
    def post(self, request, pk):
        item = _get_type_for_user(pk, request.user)
        if not item:
            return json_response(error='系统类型不存在')
        form, error = self._parse(request)
        if error:
            return json_response(error=error)
        err = _validate_field_definition_payload(form, ConfigFieldDefinition.SCOPE_TEMPLATE, item)
        if err:
            return json_response(error=err)
        with transaction.atomic():
            field = ConfigFieldDefinition.objects.create(
                tenant_id=request.user.tenant_id,
                scope_type=ConfigFieldDefinition.SCOPE_TEMPLATE,
                scope_owner_id=str(item.id),
                system_type=item,
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
                applies_to=form.applies_to,
                is_active=True,
                created_by=request.user,
            )
            record_audit_event(request, 'create', AUDIT_TARGET_TYPE, item.id, item.name,
                               after_value={'action': 'add_template_field',
                                            'field_code': field.field_code,
                                            'display_name': field.display_name,
                                            'field_type': field.field_type})
        return json_response(_serialize_field(field))

    @staticmethod
    def _parse(request):
        return JsonParser(
            Argument('field_code', type=str, required=True, help='字段编码'),
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


class TypeFieldDetailView(View):
    @auth('equipment_lifecycle.system_type.edit')
    def put(self, request, pk, fid):
        item = _get_type_for_user(pk, request.user)
        if not item:
            return json_response(error='系统类型不存在')
        field = _get_field_for_user(fid, request.user)
        if not field or field.scope_type != ConfigFieldDefinition.SCOPE_TEMPLATE \
                or field.scope_owner_id != str(item.id):
            return json_response(error='模板字段不存在')
        form, error = TypeFieldView._parse(request)
        if error:
            return json_response(error=error)
        form.pk = field.pk
        err = _validate_field_definition_payload(form, ConfigFieldDefinition.SCOPE_TEMPLATE, item)
        if err:
            return json_response(error=err)
        err = self._check_existing_values(field, form)
        if err:
            return json_response(error=err)
        before = {'field_code': field.field_code, 'display_name': field.display_name,
                  'is_required': field.is_required, 'is_active': field.is_active}
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
        field.applies_to = form.applies_to
        field.is_active = form.is_active
        field.updated_at = timezone.now()
        field.updated_by = request.user
        with transaction.atomic():
            field.save()
            record_audit_event(request, 'update', AUDIT_TARGET_TYPE, item.id, item.name,
                               before_value=before,
                               after_value={'action': 'edit_template_field',
                                            'field_code': field.field_code,
                                            'display_name': field.display_name,
                                            'is_active': field.is_active})
        return json_response(_serialize_field(field))

    @staticmethod
    def _check_existing_values(field, form):
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

    @auth('equipment_lifecycle.system_type.del')
    def delete(self, request, pk, fid):
        item = _get_type_for_user(pk, request.user)
        if not item:
            return json_response(error='系统类型不存在')
        field = _get_field_for_user(fid, request.user)
        if not field or field.scope_type != ConfigFieldDefinition.SCOPE_TEMPLATE \
                or field.scope_owner_id != str(item.id):
            return json_response(error='模板字段不存在')
        if SystemConfigValue.objects.filter(field=field).exists():
            return json_response(error='该字段已有历史值，不能删除；请停用以保留历史值')
        with transaction.atomic():
            field.delete()
            record_audit_event(request, 'delete', AUDIT_TARGET_TYPE, item.id, item.name,
                               before_value={'action': 'delete_template_field',
                                             'field_code': field.field_code,
                                             'display_name': field.display_name})
        return json_response({})


class SystemView(View):
    @auth('equipment_lifecycle.system.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('keyword', type=str, required=False),
            Argument('system_type', type=int, required=False),
            Argument('health_status', type=list, required=False),
            Argument('is_active', type=bool, required=False),
            Argument('use_unit', type=str, required=False),
            Argument('install_location', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        query = apply_tenant_filter(
            LifecycleSystem.objects.all().select_related('system_type'), request.user)
        if form.keyword:
            query = query.filter(
                Q(system_code__icontains=form.keyword) | Q(name__icontains=form.keyword))
        if form.system_type:
            query = query.filter(system_type_id=form.system_type)
        if form.health_status:
            query = query.filter(health_status__in=form.health_status)
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
        """动态字段筛选：cf_<field_id>=value，仅支持启用且可筛选的类型模板字段。"""
        for key, value in request.GET.items():
            if not key.startswith('cf_') or value in ('', None):
                continue
            try:
                field_id = int(key[3:])
            except ValueError:
                continue
            field = apply_tenant_filter(ConfigFieldDefinition.objects.all(), request.user).filter(
                pk=field_id,
                scope_type=ConfigFieldDefinition.SCOPE_TEMPLATE,
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
        form, error = self._parse_system_payload(request)
        if error:
            return json_response(error=error)
        system_type = apply_tenant_filter(SystemType.objects.all(), request.user).filter(
            pk=form.system_type, is_active=True).first()
        if not system_type:
            return json_response(error='系统类型不存在或已停用')
        system_code = (form.system_code or '').strip()
        if not system_code:
            return json_response(error='系统编号不能为空')
        if apply_tenant_filter(LifecycleSystem.objects.all(), request.user).filter(
                system_code=system_code).exists():
            return json_response(error='系统编号已存在')

        err = self._check_geo(form.geo_coordinate)
        if err:
            return json_response(error=err)
        if form.health_status not in LifecycleSystem.HEALTH_STATUS_TEXT_MAP:
            return json_response(error='运行健康状态不合法')
        install_time = _parse_datetime(form.install_time)
        enable_time = _parse_datetime(form.enable_time)
        if not install_time or not enable_time:
            return json_response(error='安装时间/启用时间格式不正确，应为 YYYY-MM-DD HH:MM')

        with transaction.atomic():
            item = LifecycleSystem.objects.create(
                tenant_id=request.user.tenant_id,
                system_code=system_code,
                name=form.name.strip(),
                system_type=system_type,
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
                health_status=form.health_status,
                is_active=True,
                remark=(form.remark or '').strip()[:1000],
                created_by=request.user,
            )
            services.record_config_change(item, SystemConfigChange.SOURCE_SYSTEM,
                                          SystemConfigChange.ACTION_CREATE, [], request.user)
            record_audit_event(request, 'create', AUDIT_TARGET_SYSTEM, item.id, item.name,
                               after_value={'system_code': item.system_code, 'name': item.name,
                                            'system_type': system_type.name})
        return json_response(item.to_view())

    @staticmethod
    def _parse_system_payload(request, for_update=False):
        parser = JsonParser(
            Argument('system_code', type=str, required=not for_update, help='系统编号'),
            Argument('name', type=str, required=True, help='系统名称'),
            Argument('system_type', type=int, required=not for_update, help='系统类型'),
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
            Argument('health_status', type=str, required=True, help='运行健康状态'),
            Argument('remark', type=str, required=False, default=''),
        )
        return parser.parse(request.body)

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
        return json_response(data)

    @auth('equipment_lifecycle.system.edit')
    def put(self, request, pk):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        form, error = SystemView._parse_system_payload(request, for_update=True)
        if error:
            return json_response(error=error)
        system_code = (form.system_code or '').strip()
        if system_code and system_code != item.system_code:
            return json_response(error='系统编号创建后不可修改')
        system_type = item.system_type
        if form.health_status not in LifecycleSystem.HEALTH_STATUS_TEXT_MAP:
            return json_response(error='运行健康状态不合法')
        err = SystemView._check_geo(form.geo_coordinate)
        if err:
            return json_response(error=err)
        install_time = _parse_datetime(form.install_time)
        enable_time = _parse_datetime(form.enable_time)
        if not install_time or not enable_time:
            return json_response(error='安装时间/启用时间格式不正确，应为 YYYY-MM-DD HH:MM')

        before = {
            'name': item.name, 'system_model': item.system_model,
            'install_location': item.install_location, 'geo_coordinate': item.geo_coordinate,
            'system_purpose': item.system_purpose, 'manufacturer': item.manufacturer,
            'install_unit': item.install_unit, 'use_unit': item.use_unit,
            'install_time': item.install_time.isoformat(sep=' ', timespec='minutes') if item.install_time else '',
            'enable_time': item.enable_time.isoformat(sep=' ', timespec='minutes') if item.enable_time else '',
            'responsible_user_name': item.responsible_user_name,
            'health_status': item.health_status, 'remark': item.remark,
        }
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
        item.health_status = form.health_status
        item.remark = (form.remark or '').strip()[:1000]
        item.updated_at = timezone.now()
        item.updated_by = request.user

        changes = []
        after = {
            'name': item.name, 'system_model': item.system_model,
            'install_location': item.install_location, 'geo_coordinate': item.geo_coordinate,
            'system_purpose': item.system_purpose, 'manufacturer': item.manufacturer,
            'install_unit': item.install_unit, 'use_unit': item.use_unit,
            'install_time': item.install_time.isoformat(sep=' ', timespec='minutes') if item.install_time else '',
            'enable_time': item.enable_time.isoformat(sep=' ', timespec='minutes') if item.enable_time else '',
            'responsible_user_name': item.responsible_user_name,
            'health_status': item.health_status, 'remark': item.remark,
        }
        label_map = {
            'name': '系统名称', 'system_model': '系统型号', 'install_location': '安装地点',
            'geo_coordinate': '安装经纬度', 'system_purpose': '系统用途',
            'manufacturer': '生产厂家', 'install_unit': '安装单位', 'use_unit': '使用单位',
            'install_time': '安装时间', 'enable_time': '启用时间',
            'responsible_user_name': '系统负责人', 'health_status': '运行健康状态', 'remark': '备注',
        }
        for key, old in before.items():
            new = after[key]
            if old != new:
                changes.append({'scope': 'fixed', 'code': key, 'label': label_map[key],
                                'old': old, 'new': new})

        with transaction.atomic():
            item.save()
            if changes:
                services.record_config_change(item, SystemConfigChange.SOURCE_SYSTEM,
                                              SystemConfigChange.ACTION_UPDATE, changes, request.user)
            record_audit_event(request, 'update', AUDIT_TARGET_SYSTEM, item.id, item.name,
                               before_value={'changed': [c['label'] for c in changes]},
                               after_value={'system_code': item.system_code})
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
        query = apply_tenant_filter(
            LifecycleSystem.objects.all().select_related('system_type'), request.user)
        headers = ['系统编号', '系统名称', '系统类型', '系统型号', '安装地点', '安装经纬度',
                   '系统用途', '生产厂家', '安装单位', '使用单位', '安装时间', '启用时间',
                   '系统负责人', '运行健康状态', '是否可用', '备注', '创建时间']
        rows = []
        for item in query:
            rows.append([
                item.system_code, item.name, item.system_type.name, item.system_model,
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
                       'system_type': item.system_type_id, 'system_type_name': item.system_type.name,
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
                '类型模板' if field.scope_type == ConfigFieldDefinition.SCOPE_TEMPLATE else '系统自定义',
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
        form, error = TypeFieldView._parse(request)
        if error:
            return json_response(error=error)
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
        form, error = TypeFieldView._parse(request)
        if error:
            return json_response(error=error)
        form.pk = field.pk
        err = _validate_field_definition_payload(form, ConfigFieldDefinition.SCOPE_CUSTOM, item)
        if err:
            return json_response(error=err)
        err = TypeFieldDetailView._check_existing_values(field, form)
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


class CustomFieldPromoteView(View):
    """把具体系统自定义字段提升为系统类型模板字段，历史值跟随迁移。"""

    @auth('equipment_lifecycle.system_config.field')
    def post(self, request, pk, fid):
        item = _get_system_for_user(pk, request.user)
        if not item:
            return json_response(error='系统不存在')
        field = _get_field_for_user(fid, request.user)
        if not field or field.scope_type != ConfigFieldDefinition.SCOPE_CUSTOM \
                or field.scope_owner_id != str(item.id):
            return json_response(error='自定义字段不存在')
        dup = ConfigFieldDefinition.objects.filter(
            tenant_id=item.tenant_id,
            scope_type=ConfigFieldDefinition.SCOPE_TEMPLATE,
            scope_owner_id=str(item.system_type_id),
        ).filter(Q(field_code=field.field_code) | Q(display_name=field.display_name)).exists()
        if dup:
            return json_response(error='该系统类型模板下已存在同编码或同名的字段')
        with transaction.atomic():
            promoted = ConfigFieldDefinition.objects.create(
                tenant_id=item.tenant_id,
                scope_type=ConfigFieldDefinition.SCOPE_TEMPLATE,
                scope_owner_id=str(item.system_type_id),
                system_type=item.system_type,
                field_code=field.field_code,
                display_name=field.display_name,
                field_type=field.field_type,
                help_text=field.help_text,
                display_order=field.display_order,
                is_required=field.is_required,
                default_value=field.default_value,
                choices=field.choices,
                detail_columns=field.detail_columns,
                number_min=field.number_min,
                number_max=field.number_max,
                text_regex=field.text_regex,
                is_searchable=field.is_searchable,
                is_filterable=field.is_filterable,
                is_exportable=field.is_exportable,
                visible_roles=field.visible_roles,
                editable_roles=field.editable_roles,
                is_sensitive=field.is_sensitive,
                applies_to=ConfigFieldDefinition.APPLIES_ALL,
                is_active=True,
                created_by=request.user,
            )
            moved = SystemConfigValue.objects.filter(field=field).update(field=promoted)
            field.delete()
            services.record_config_change(
                item, SystemConfigChange.SOURCE_FIELD_DEF, SystemConfigChange.ACTION_PROMOTE,
                [{'scope': ConfigFieldDefinition.SCOPE_CUSTOM, 'code': field.field_code,
                  'label': field.display_name,
                  'old': '系统自定义字段',
                  'new': f'已提升为类型「{item.system_type.name}」模板字段'}],
                request.user)
            record_audit_event(request, 'update', AUDIT_TARGET_CONFIG, item.id, item.name,
                               after_value={'action': 'promote_custom_field',
                                            'field_code': field.field_code,
                                            'moved_values': moved})
        return json_response(_serialize_field(promoted))


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

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——系统主数据与配置档案模型（步骤二）。

按《设备与系统全生命周期管理总体方案 v2.0》步骤二建设：

- LifecycleSystem          系统主数据（平级、无父子层级、无系统—设备关系）
- SystemType               系统类型（模板归属）
- ConfigFieldDefinition    配置字段定义（类型模板字段 / 具体系统自定义字段）
- SystemConfigValue        系统在某个字段下的当前值（类型化存储，可查询）
- SystemConfigComponent    配置组成项（按类型汇总，不做单台设备资产）
- SystemConfigChange       配置变更历史（字段前后值、来源、人员、时间）
- SystemConfigSnapshot     配置快照（按需生成，支持差异比较）

约束：
- 全部继承 TenantModelMixin，租户隔离；
- CharField/TextField 一律禁止 null=True；
- 字段定义删除不得级联删除历史值（SystemConfigValue.field 使用 PROTECT）；
- 新表均不复用步骤一删除的旧表名（tdyw_el_system 等）。
"""
import json

from django.db import models

from apps.account.models import User
from libs.tenant_base_model import TenantModelManager, TenantModelMixin, make_tenant_id

# Meta/CheckConstraint 内无法访问类体常量（类作用域不形成闭包），枚举值提为模块级
HEALTH_STATUS_VALUES = ['normal', 'degraded', 'fault', 'repairing', 'interrupted', 'unknown']
FIELD_TYPE_VALUES_LIST = ['text', 'longtext', 'number', 'date', 'choice',
                          'multi_choice', 'boolean', 'attachment', 'detail_table']


class SystemType(TenantModelMixin, models.Model):
    """系统类型：系统分类与模板字段归属，租户内名称唯一。"""

    name = models.CharField(max_length=50, help_text='系统类型名称，租户内唯一')
    description = models.CharField(max_length=500, default='', blank=True, help_text='类型说明')
    display_order = models.IntegerField(default=0, help_text='显示顺序，小者靠前')
    is_active = models.BooleanField(default=True, help_text='是否启用（停用后不可用于新建系统）')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_system_type'
        verbose_name = '系统类型'
        verbose_name_plural = '系统类型'
        ordering = ('display_order', 'id')
        constraints = [
            models.UniqueConstraint(fields=['tenant_id', 'name'], name='uniq_el_system_type_tenant_name'),
        ]

    def __repr__(self):
        return '<SystemType %r>' % self.name

    def to_view(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'display_order': self.display_order,
            'is_active': self.is_active,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


class LifecycleSystem(TenantModelMixin, models.Model):
    """系统主数据：一个对象代表某地点实际运行的一套系统实例。

    - 所有系统平级，不设父系统/子系统/树形层级（无 parent 字段，测试固化）；
    - system_code 租户内唯一，创建后不可修改；
    - is_active 只控制系统能否继续被业务选择，不表达运行状态；
    - health_status 为运行健康状态，步骤二仅初始化，不做故障/工单驱动计算。
    """

    HEALTH_NORMAL = 'normal'
    HEALTH_DEGRADED = 'degraded'
    HEALTH_FAULT = 'fault'
    HEALTH_REPAIRING = 'repairing'
    HEALTH_INTERRUPTED = 'interrupted'
    HEALTH_UNKNOWN = 'unknown'
    HEALTH_STATUS_CHOICES = (
        (HEALTH_NORMAL, '正常'),
        (HEALTH_DEGRADED, '降级'),
        (HEALTH_FAULT, '故障'),
        (HEALTH_REPAIRING, '维修中'),
        (HEALTH_INTERRUPTED, '中断'),
        (HEALTH_UNKNOWN, '未知'),
    )
    HEALTH_STATUS_TEXT_MAP = dict(HEALTH_STATUS_CHOICES)

    system_code = models.CharField(max_length=50, help_text='系统编号，租户内唯一，创建后不可修改')
    name = models.CharField(max_length=100, help_text='系统正式名称')
    system_type = models.ForeignKey(SystemType, models.PROTECT, related_name='systems', help_text='系统类型')
    system_model = models.CharField(max_length=100, help_text='系统型号')
    install_location = models.CharField(max_length=200, help_text='安装地点')
    geo_coordinate = models.CharField(max_length=100, default='', blank=True, help_text='安装经纬度，格式: 经度,纬度')
    system_purpose = models.TextField(max_length=500, default='', blank=True, help_text='系统用途')
    manufacturer = models.CharField(max_length=100, help_text='生产厂家')
    install_unit = models.CharField(max_length=100, help_text='安装单位')
    use_unit = models.CharField(max_length=100, help_text='使用单位')
    install_time = models.DateTimeField(null=True, blank=True, help_text='安装时间（仅档案信息）')
    enable_time = models.DateTimeField(null=True, blank=True, help_text='启用时间（仅档案信息）')
    responsible_user_name = models.CharField(max_length=100, help_text='系统负责人姓名')
    health_status = models.CharField(max_length=20, choices=HEALTH_STATUS_CHOICES, help_text='运行健康状态')
    is_active = models.BooleanField(default=True, help_text='是否可用（仅控制业务候选资格）')
    remark = models.TextField(max_length=1000, default='', blank=True, help_text='备注')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_systems'
        verbose_name = '系统'
        verbose_name_plural = '系统'
        ordering = ('-created_at', '-id')
        constraints = [
            models.UniqueConstraint(fields=['tenant_id', 'system_code'], name='uniq_el_systems_tenant_code'),
            models.CheckConstraint(
                check=models.Q(health_status__in=HEALTH_STATUS_VALUES),
                name='el_systems_health_status_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'system_type']),
            models.Index(fields=['tenant_id', 'health_status']),
            models.Index(fields=['tenant_id', '-created_at', '-id']),
        ]

    def __repr__(self):
        return '<LifecycleSystem %r>' % self.system_code

    def to_view(self):
        return {
            'id': self.id,
            'system_code': self.system_code,
            'name': self.name,
            'system_type': self.system_type_id,
            'system_type_name': self.system_type.name,
            'system_model': self.system_model,
            'install_location': self.install_location,
            'geo_coordinate': self.geo_coordinate,
            'system_purpose': self.system_purpose,
            'manufacturer': self.manufacturer,
            'install_unit': self.install_unit,
            'use_unit': self.use_unit,
            'install_time': self.install_time,
            'enable_time': self.enable_time,
            'responsible_user_name': self.responsible_user_name,
            'health_status': self.health_status,
            'health_status_text': self.HEALTH_STATUS_TEXT_MAP.get(self.health_status, self.health_status),
            'is_active': self.is_active,
            'remark': self.remark,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


class ConfigFieldDefinition(TenantModelMixin, models.Model):
    """配置字段定义：类型模板字段（scope=template）与具体系统自定义字段（scope=custom）。

    - scope_owner_id 为 scope_type 归属对象的字符串主键，保证租户内
      (scope_type, scope_owner_id, field_code) 三元组唯一且各列非空
      （MariaDB 唯一索引对 NULL 不去重，不能依赖可空外键做唯一约束）；
    - field_type 支持文本、长文本、数字、日期、单选、多选、布尔、附件、明细表；
    - is_active=False 停用后不再用于新录入，历史值保留可查；
    - 字段定义删除不得级联删除历史值（由 SystemConfigValue.field PROTECT 保证）。
    """

    SCOPE_TEMPLATE = 'template'
    SCOPE_CUSTOM = 'custom'
    SCOPE_CHOICES = (
        (SCOPE_TEMPLATE, '系统类型模板字段'),
        (SCOPE_CUSTOM, '系统自定义字段'),
    )

    TYPE_TEXT = 'text'
    TYPE_LONGTEXT = 'longtext'
    TYPE_NUMBER = 'number'
    TYPE_DATE = 'date'
    TYPE_CHOICE = 'choice'
    TYPE_MULTI_CHOICE = 'multi_choice'
    TYPE_BOOLEAN = 'boolean'
    TYPE_ATTACHMENT = 'attachment'
    TYPE_DETAIL_TABLE = 'detail_table'
    FIELD_TYPE_CHOICES = (
        (TYPE_TEXT, '文本'),
        (TYPE_LONGTEXT, '长文本'),
        (TYPE_NUMBER, '数字'),
        (TYPE_DATE, '日期'),
        (TYPE_CHOICE, '单选'),
        (TYPE_MULTI_CHOICE, '多选'),
        (TYPE_BOOLEAN, '布尔值'),
        (TYPE_ATTACHMENT, '附件'),
        (TYPE_DETAIL_TABLE, '明细表'),
    )
    FIELD_TYPE_TEXT_MAP = dict(FIELD_TYPE_CHOICES)
    FIELD_TYPE_VALUES = {item[0] for item in FIELD_TYPE_CHOICES}

    APPLIES_ALL = 'all'
    APPLIES_NEW_ONLY = 'new_only'
    APPLIES_CHOICES = (
        (APPLIES_ALL, '全部系统'),
        (APPLIES_NEW_ONLY, '仅新建系统'),
    )

    scope_type = models.CharField(max_length=20, choices=SCOPE_CHOICES, help_text='字段作用范围')
    scope_owner_id = models.CharField(max_length=20, help_text='归属对象ID（模板=系统类型ID，自定义=系统ID）')
    system_type = models.ForeignKey(SystemType, models.PROTECT, related_name='template_fields', null=True, blank=True, help_text='模板字段所属系统类型')
    system = models.ForeignKey(LifecycleSystem, models.PROTECT, related_name='custom_fields', null=True, blank=True, help_text='自定义字段所属系统')
    field_code = models.CharField(max_length=50, help_text='稳定字段编码，作用范围内唯一')
    display_name = models.CharField(max_length=100, help_text='显示名称')
    field_type = models.CharField(max_length=20, choices=FIELD_TYPE_CHOICES, help_text='字段类型')
    help_text = models.CharField(max_length=200, default='', blank=True, help_text='帮助文字')
    display_order = models.IntegerField(default=0, help_text='显示顺序，小者靠前')
    is_required = models.BooleanField(default=False, help_text='是否必填')
    default_value = models.TextField(default='', blank=True, help_text='默认值（多选为 JSON 数组）')
    choices = models.TextField(default='', blank=True, help_text='候选项，JSON 字符串数组（单选/多选）')
    detail_columns = models.TextField(default='', blank=True, help_text='明细表列定义，JSON 数组 [{"code","name"}]')
    number_min = models.FloatField(null=True, blank=True, help_text='数字最小值（含）')
    number_max = models.FloatField(null=True, blank=True, help_text='数字最大值（含）')
    text_regex = models.CharField(max_length=200, default='', blank=True, help_text='文本格式正则校验')
    is_searchable = models.BooleanField(default=False, help_text='是否可搜索')
    is_filterable = models.BooleanField(default=False, help_text='是否可筛选')
    is_exportable = models.BooleanField(default=False, help_text='是否可导出')
    visible_roles = models.TextField(default='', blank=True, help_text='可见角色ID JSON 数组，空为不限')
    editable_roles = models.TextField(default='', blank=True, help_text='可编辑角色ID JSON 数组，空为不限')
    is_sensitive = models.BooleanField(default=False, help_text='是否属于敏感配置（查看记录审计）')
    applies_to = models.CharField(max_length=20, choices=APPLIES_CHOICES, default=APPLIES_ALL, help_text='适用系统范围')
    is_active = models.BooleanField(default=True, help_text='是否启用（停用后不再用于新录入）')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_config_field'
        verbose_name = '配置字段定义'
        verbose_name_plural = '配置字段定义'
        ordering = ('display_order', 'id')
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'scope_type', 'scope_owner_id', 'field_code'],
                name='uniq_el_config_field_scope_code',
            ),
            models.CheckConstraint(
                check=models.Q(field_type__in=FIELD_TYPE_VALUES_LIST),
                name='el_config_field_type_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'scope_type', 'scope_owner_id']),
        ]

    def __repr__(self):
        return '<ConfigFieldDefinition %r>' % self.field_code

    def to_view(self):
        return {
            'id': self.id,
            'scope_type': self.scope_type,
            'scope_owner_id': self.scope_owner_id,
            'system_type': self.system_type_id,
            'system': self.system_id,
            'field_code': self.field_code,
            'display_name': self.display_name,
            'field_type': self.field_type,
            'field_type_text': self.FIELD_TYPE_TEXT_MAP.get(self.field_type, self.field_type),
            'help_text': self.help_text,
            'display_order': self.display_order,
            'is_required': self.is_required,
            'default_value': self.default_value,
            'choices': self.choices,
            'detail_columns': self.detail_columns,
            'number_min': self.number_min,
            'number_max': self.number_max,
            'text_regex': self.text_regex,
            'is_searchable': self.is_searchable,
            'is_filterable': self.is_filterable,
            'is_exportable': self.is_exportable,
            'visible_roles': self.visible_roles,
            'editable_roles': self.editable_roles,
            'is_sensitive': self.is_sensitive,
            'applies_to': self.applies_to,
            'is_active': self.is_active,
            'created_at': self.created_at,
        }

    def get_choices(self):
        if not self.choices:
            return []
        try:
            data = json.loads(self.choices)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    def get_detail_columns(self):
        if not self.detail_columns:
            return []
        try:
            data = json.loads(self.detail_columns)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    def get_role_ids(self, attr):
        raw = getattr(self, attr) or ''
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return [int(x) for x in data] if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []


class SystemConfigValue(TenantModelMixin, models.Model):
    """系统在某配置字段下的当前值：按字段类型分列存储，保证可校验、可查询。

    - value_text 承载文本/长文本/单选/多选(JSON)/附件(JSON ID 数组)/明细表(JSON 行数组)；
    - value_number / value_date / value_bool 承载类型化值；
    - field 使用 PROTECT：字段定义删除前必须先确认无历史值，历史值不得级联删除。
    """

    system = models.ForeignKey(LifecycleSystem, models.CASCADE, related_name='config_values', help_text='所属系统')
    field = models.ForeignKey(ConfigFieldDefinition, models.PROTECT, related_name='config_values', help_text='配置字段定义')
    value_text = models.TextField(default='', blank=True, help_text='文本类值（多选/附件/明细表为 JSON）')
    value_number = models.FloatField(null=True, blank=True, help_text='数字值')
    value_date = models.DateField(null=True, blank=True, help_text='日期值')
    value_bool = models.BooleanField(null=True, blank=True, help_text='布尔值')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_config_value'
        verbose_name = '系统配置值'
        verbose_name_plural = '系统配置值'
        ordering = ('field_id', 'id')
        constraints = [
            models.UniqueConstraint(fields=['system', 'field'], name='uniq_el_config_value_system_field'),
        ]

    def __repr__(self):
        return '<SystemConfigValue system=%s field=%s>' % (self.system_id, self.field_id)


class SystemConfigComponent(TenantModelMixin, models.Model):
    """配置组成项：描述系统组成（设备/软件/模块/链路），按类型汇总即可，不做单台设备资产。

    不建立与设备台账（DeviceResume）的任何关联，也无调拨/流转语义。
    """

    system = models.ForeignKey(LifecycleSystem, models.CASCADE, related_name='components', help_text='所属系统')
    name = models.CharField(max_length=100, help_text='组成项名称')
    category = models.CharField(max_length=50, default='', blank=True, help_text='类别，如接入交换机')
    model_version = models.CharField(max_length=100, default='', blank=True, help_text='型号或版本')
    quantity = models.IntegerField(null=True, blank=True, help_text='数量，允许按类型汇总如 4 台')
    purpose = models.CharField(max_length=200, default='', blank=True, help_text='用途')
    asset_sn = models.CharField(max_length=100, default='', blank=True, help_text='可选资产编号或序列号')
    external_ref = models.CharField(max_length=200, default='', blank=True, help_text='外部系统引用标识')
    remark = models.CharField(max_length=500, default='', blank=True, help_text='备注')
    display_order = models.IntegerField(default=0, help_text='显示顺序，小者靠前')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_config_component'
        verbose_name = '配置组成项'
        verbose_name_plural = '配置组成项'
        ordering = ('display_order', 'id')
        indexes = [
            models.Index(fields=['tenant_id', 'system']),
        ]

    def __repr__(self):
        return '<SystemConfigComponent %r>' % self.name

    def to_view(self):
        return {
            'id': self.id,
            'system': self.system_id,
            'name': self.name,
            'category': self.category,
            'model_version': self.model_version,
            'quantity': self.quantity,
            'purpose': self.purpose,
            'asset_sn': self.asset_sn,
            'external_ref': self.external_ref,
            'remark': self.remark,
            'display_order': self.display_order,
        }


class SystemConfigChange(TenantModelMixin, models.Model):
    """配置变更历史：每次保存记录变更人、时间、来源及字段前后值。

    - source 区分固定字段（system）、动态字段值（config）、组成项（component）、
      字段定义（field_definition）；
    - changes 为 JSON 数组：[{scope, code, label, old, new}]；
    - 字段/组成项停用或删除后，本表记录不受影响（纯 JSON 快照，无外键依赖）。
    """

    SOURCE_SYSTEM = 'system'
    SOURCE_CONFIG = 'config'
    SOURCE_COMPONENT = 'component'
    SOURCE_FIELD_DEF = 'field_definition'
    SOURCE_CHOICES = (
        (SOURCE_SYSTEM, '系统固定字段'),
        (SOURCE_CONFIG, '配置字段值'),
        (SOURCE_COMPONENT, '配置组成项'),
        (SOURCE_FIELD_DEF, '字段定义'),
    )

    ACTION_CREATE = 'create'
    ACTION_UPDATE = 'update'
    ACTION_DELETE = 'delete'
    ACTION_ACTIVATE = 'activate'
    ACTION_DEACTIVATE = 'deactivate'
    ACTION_PROMOTE = 'promote'
    ACTION_CHOICES = (
        (ACTION_CREATE, '新建'),
        (ACTION_UPDATE, '修改'),
        (ACTION_DELETE, '删除'),
        (ACTION_ACTIVATE, '启用'),
        (ACTION_DEACTIVATE, '停用'),
        (ACTION_PROMOTE, '提升为模板字段'),
    )

    system = models.ForeignKey(LifecycleSystem, models.CASCADE, related_name='config_changes', help_text='所属系统')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, help_text='变更来源')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, help_text='变更动作')
    changes = models.TextField(default='', blank=True, help_text='字段前后值 JSON 数组')
    changed_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    changed_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_config_change'
        verbose_name = '配置变更历史'
        verbose_name_plural = '配置变更历史'
        ordering = ('-changed_at', '-id')
        indexes = [
            models.Index(fields=['tenant_id', 'system', '-changed_at', '-id']),
        ]

    def __repr__(self):
        return '<SystemConfigChange system=%s %s/%s>' % (self.system_id, self.source, self.action)

    def to_view(self):
        changes = []
        if self.changes:
            try:
                data = json.loads(self.changes)
                if isinstance(data, list):
                    changes = data
            except (ValueError, TypeError):
                changes = []
        return {
            'id': self.id,
            'system': self.system_id,
            'source': self.source,
            'source_text': self.get_source_display(),
            'action': self.action,
            'action_text': self.get_action_display(),
            'changes': changes,
            'changed_by': self.changed_by_id,
            'changed_by_name': self.changed_by.username if self.changed_by_id else '',
            'changed_at': self.changed_at,
        }


class SystemConfigSnapshot(TenantModelMixin, models.Model):
    """配置快照：重要配置变更或技术改造后按需生成，保存当时完整配置。

    - content 为 JSON：{fixed: {...}, values: [{code,label,type,value}], components: [...]}；
    - 支持与当前配置或另一份快照做服务端差异比较；
    - 普通修改只记变更历史，不要求手工发布快照。
    """

    system = models.ForeignKey(LifecycleSystem, models.CASCADE, related_name='config_snapshots', help_text='所属系统')
    name = models.CharField(max_length=100, help_text='快照名称')
    remark = models.CharField(max_length=500, default='', blank=True, help_text='快照说明')
    content = models.TextField(help_text='快照内容 JSON')
    content_hash = models.CharField(max_length=64, default='', help_text='快照内容 SHA256')
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_config_snapshot'
        verbose_name = '配置快照'
        verbose_name_plural = '配置快照'
        ordering = ('-created_at', '-id')
        indexes = [
            models.Index(fields=['tenant_id', 'system']),
        ]

    def __repr__(self):
        return '<SystemConfigSnapshot %r>' % self.name

    def to_view(self):
        return {
            'id': self.id,
            'system': self.system_id,
            'name': self.name,
            'remark': self.remark,
            'content_hash': self.content_hash,
            'created_by': self.created_by_id,
            'created_by_name': self.created_by.username if self.created_by_id else '',
            'created_at': self.created_at,
        }

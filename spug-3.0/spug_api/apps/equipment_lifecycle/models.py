# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——系统主数据与配置档案模型（步骤二）。

按《设备与系统全生命周期管理总体方案 v2.0》步骤二建设：

- LifecycleSystem          系统主数据（平级、无父子层级、无系统—设备关系）
- ConfigFieldDefinition    配置字段定义（具体系统自定义字段）
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
FAULT_IMPACT_VALUES = ['degraded', 'fault', 'interrupted']
FAULT_STATUS_VALUES = ['pending', 'handling', 'recovered', 'closed', 'cancelled']
FIELD_TYPE_VALUES_LIST = ['text', 'longtext', 'number', 'date', 'choice',
                          'multi_choice', 'boolean', 'attachment', 'detail_table']


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

    SCOPE_CUSTOM = 'custom'
    SCOPE_CHOICES = (
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
    scope_owner_id = models.CharField(max_length=20, help_text='归属对象ID（=系统ID）')
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


class SystemFault(TenantModelMixin, models.Model):
    """系统故障主表（步骤 3.1，单系统简化）。

    与步骤一删除的旧故障表（tdyw_fault_records/tdyw_fault_parts）无关，不复用旧表名。

    关联规则（一个故障单只关联一个故障系统，不建设跨系统影响关系）：
    - 故障系统必须通过外键关联系统主数据（请求与存储一律用系统 ID，页面只显示名称）；
    - 故障发生时保存系统快照（编号/名称/安装地点），系统改名后历史详情仍显示当时名称；
      快照仅用于历史展示，不替代正式外键；
    - 具体故障对象可选引用配置组成项（SET_NULL，组成项删除不影响历史快照文本），
      不建立单台设备外键、不关联 DeviceResume。
    一次实际工作涉及多个独立系统时分别建立故障，不允许一单关联多系统。

    状态流转（后端校验，动作接口触发）：
    pending →(start)→ handling →(recover)→ recovered →(close)→ closed；
    pending/handling/recovered 可 →(cancel)→ cancelled（受控作废，del 权限）。
    已关闭/已作废不参与健康状态计算。
    """

    STATUS_PENDING = 'pending'
    STATUS_HANDLING = 'handling'
    STATUS_RECOVERED = 'recovered'
    STATUS_CLOSED = 'closed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = (
        (STATUS_PENDING, '待处置'),
        (STATUS_HANDLING, '处置中'),
        (STATUS_RECOVERED, '已恢复'),
        (STATUS_CLOSED, '已关闭'),
        (STATUS_CANCELLED, '已作废'),
    )
    STATUS_TEXT_MAP = dict(STATUS_CHOICES)

    LEVEL_MINOR = 'minor'
    LEVEL_MAJOR = 'major'
    LEVEL_CRITICAL = 'critical'
    LEVEL_CHOICES = (
        (LEVEL_MINOR, '一般'),
        (LEVEL_MAJOR, '严重'),
        (LEVEL_CRITICAL, '重大'),
    )
    LEVEL_TEXT_MAP = dict(LEVEL_CHOICES)

    IMPACT_DEGRADED = 'degraded'
    IMPACT_FAULT = 'fault'
    IMPACT_INTERRUPTED = 'interrupted'
    IMPACT_CHOICES = (
        (IMPACT_DEGRADED, '降级'),
        (IMPACT_FAULT, '故障'),
        (IMPACT_INTERRUPTED, '中断'),
    )
    IMPACT_TEXT_MAP = dict(IMPACT_CHOICES)

    DISCOVERY_PATROL = 'patrol'
    DISCOVERY_ALARM = 'alarm'
    DISCOVERY_REPORT = 'report'
    DISCOVERY_OTHER = 'other'
    DISCOVERY_CHOICES = (
        (DISCOVERY_PATROL, '巡检发现'),
        (DISCOVERY_ALARM, '告警发现'),
        (DISCOVERY_REPORT, '人工报告'),
        (DISCOVERY_OTHER, '其他'),
    )
    DISCOVERY_TEXT_MAP = dict(DISCOVERY_CHOICES)

    SOURCE_MANUAL = 'manual'

    fault_no = models.CharField(max_length=50, help_text='故障编号，租户内唯一，自动生成')
    system = models.ForeignKey(
        LifecycleSystem, models.PROTECT, related_name='faults',
        help_text='故障系统（外键关联系统主数据，一个故障单只关联一个系统）')
    impact_status = models.CharField(
        max_length=20, choices=IMPACT_CHOICES, help_text='故障系统影响状态')
    # 故障系统故障发生时快照
    system_code = models.CharField(max_length=50, help_text='故障系统编号快照')
    system_name = models.CharField(max_length=100, help_text='故障系统名称快照')
    system_location = models.CharField(max_length=200, help_text='故障系统安装地点快照')

    occurred_at = models.DateTimeField(help_text='故障发生时间')
    discovery = models.CharField(max_length=20, choices=DISCOVERY_CHOICES, help_text='故障发现方式')
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, help_text='故障级别')
    phenomenon = models.TextField(max_length=2000, help_text='故障现象')
    impact_scope = models.TextField(max_length=1000, default='', blank=True, help_text='影响范围')
    fault_location = models.CharField(max_length=200, default='', blank=True,
                                      help_text='故障位置描述')
    fault_object_name = models.CharField(max_length=100, default='', blank=True,
                                         help_text='具体故障对象名称快照')
    fault_object_model = models.CharField(max_length=100, default='', blank=True,
                                          help_text='具体故障对象型号快照')
    fault_object_sn = models.CharField(max_length=100, default='', blank=True,
                                       help_text='具体故障对象编号/序列号快照')
    fault_component = models.ForeignKey(
        SystemConfigComponent, models.SET_NULL, related_name='faults', null=True, blank=True,
        help_text='可选配置组成项引用（非必填，不建单台设备外键）')

    reason_analysis = models.TextField(max_length=2000, default='', blank=True, help_text='原因分析')
    recovered_at = models.DateTimeField(null=True, blank=True, help_text='恢复时间')
    recover_confirm = models.TextField(max_length=1000, default='', blank=True, help_text='恢复确认信息')
    recovered_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                     help_text='恢复确认人')
    recovered_confirmed_at = models.DateTimeField(null=True, blank=True, help_text='恢复确认时间')
    final_result = models.TextField(max_length=2000, default='', blank=True, help_text='最终结果')
    cancel_reason = models.CharField(max_length=200, default='', blank=True,
                                     help_text='作废原因（受控作废时填写，审计与履历留痕）')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING,
                              help_text='当前状态')
    source_type = models.CharField(max_length=20, default=SOURCE_MANUAL, help_text='来源类型：manual 人工 / ledger_item 台账异常明细（步骤 3.3）')
    source_id = models.CharField(max_length=50, default='', blank=True, help_text='来源对象 ID 冗余（与来源外键一致，便于追溯查询）')
    source_ledger_item = models.ForeignKey(
        'equipment_lifecycle.OperationLedgerItem', models.PROTECT,
        related_name='generated_faults', null=True, blank=True,
        help_text='来源台账异常明细（台账异常转故障时写入，真实外键保证可追溯）')

    created_by = models.ForeignKey(User, models.PROTECT, related_name='+', help_text='创建人')
    handler = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                help_text='当前处置负责人')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_fault'
        verbose_name = '系统故障'
        verbose_name_plural = '系统故障'
        ordering = ('-occurred_at', '-id')
        constraints = [
            models.UniqueConstraint(fields=['tenant_id', 'fault_no'], name='uniq_el_fault_tenant_no'),
            models.CheckConstraint(
                check=models.Q(status__in=FAULT_STATUS_VALUES),
                name='el_fault_status_valid',
            ),
            models.CheckConstraint(
                check=models.Q(impact_status__in=FAULT_IMPACT_VALUES),
                name='el_fault_impact_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'status']),
            models.Index(fields=['tenant_id', 'system', '-occurred_at', '-id']),
            models.Index(fields=['tenant_id', '-occurred_at', '-id']),
        ]

    def __repr__(self):
        return '<SystemFault %r>' % self.fault_no

    def to_view(self):
        """列表行摘要。"""
        return {
            'id': self.id,
            'fault_no': self.fault_no,
            'system': self.system_id,
            'system_name': self.system_name,
            'system_code': self.system_code,
            'system_location': self.system_location,
            'impact_status': self.impact_status,
            'impact_status_text': self.IMPACT_TEXT_MAP.get(self.impact_status, ''),
            'occurred_at': self.occurred_at,
            'level': self.level,
            'level_text': self.LEVEL_TEXT_MAP.get(self.level, self.level),
            'phenomenon': self.phenomenon,
            'status': self.status,
            'status_text': self.STATUS_TEXT_MAP.get(self.status, self.status),
            'handler': self.handler_id,
            'handler_name': self.handler.username if self.handler_id else '',
            'created_by_name': self.created_by.username if self.created_by_id else '',
            'created_at': self.created_at,
        }

    def to_detail_view(self):
        """详情：全字段（单系统简化，无受影响系统）。"""
        data = self.to_view()
        data.update({
            'discovery': self.discovery,
            'discovery_text': self.DISCOVERY_TEXT_MAP.get(self.discovery, self.discovery),
            'impact_scope': self.impact_scope,
            'fault_location': self.fault_location,
            'fault_object_name': self.fault_object_name,
            'fault_object_model': self.fault_object_model,
            'fault_object_sn': self.fault_object_sn,
            'fault_component': self.fault_component_id,
            'fault_component_name': self.fault_component.name if self.fault_component_id else '',
            'reason_analysis': self.reason_analysis,
            'recovered_at': self.recovered_at,
            'recover_confirm': self.recover_confirm,
            'recovered_by': self.recovered_by_id,
            'recovered_by_name': self.recovered_by.username if self.recovered_by_id else '',
            'recovered_confirmed_at': self.recovered_confirmed_at,
            'final_result': self.final_result,
            'source_type': self.source_type,
            'source_id': self.source_id,
            # 台账来源追溯：跳回来源台账明细所需定位信息
            'source_ledger_item': self.source_ledger_item_id,
            'source_ledger': (
                self.source_ledger_item.ledger_id if self.source_ledger_item_id else None),
            'source_ledger_no': (
                self.source_ledger_item.ledger.ledger_no if self.source_ledger_item_id else ''),
            'source_ledger_type': (
                self.source_ledger_item.ledger.ledger_type if self.source_ledger_item_id else ''),
            'updated_at': self.updated_at,
        })
        return data


class SystemFaultHandlingRecord(TenantModelMixin, models.Model):
    """故障处置过程记录：追加式时间线，不把过程反复覆盖在一个文本字段中。

    - 已保存记录不得被普通用户静默覆盖：更正时把原内容、修改内容、更正原因
      追加保存到 corrections JSON 数组（[{old, new, reason, by, at}]）；
    - 附件使用项目现有 EvidenceAttachment 能力
      （module=equipment_lifecycle, object_type=el_fault_handling, object_id=记录ID）。
    """

    fault = models.ForeignKey(SystemFault, models.CASCADE, related_name='handling_records',
                              help_text='所属故障')
    handled_at = models.DateTimeField(help_text='处置时间')
    handler = models.ForeignKey(User, models.PROTECT, related_name='+', help_text='处置人')
    content = models.TextField(max_length=2000, help_text='处置内容')
    result = models.CharField(max_length=200, default='', blank=True, help_text='处置结果')
    corrections = models.TextField(default='', blank=True, help_text='更正历史 JSON 数组')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_fault_handling_record'
        verbose_name = '故障处置记录'
        verbose_name_plural = '故障处置记录'
        ordering = ('handled_at', 'id')
        indexes = [
            models.Index(fields=['tenant_id', 'fault', 'handled_at', 'id']),
        ]

    def __repr__(self):
        return '<SystemFaultHandlingRecord fault=%s at=%s>' % (self.fault_id, self.handled_at)

    def get_corrections(self):
        if not self.corrections:
            return []
        try:
            data = json.loads(self.corrections)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    def to_view(self):
        return {
            'id': self.id,
            'fault': self.fault_id,
            'handled_at': self.handled_at,
            'handler': self.handler_id,
            'handler_name': self.handler.username if self.handler_id else '',
            'content': self.content,
            'result': self.result,
            'corrections': self.get_corrections(),
            'created_at': self.created_at,
        }


# ======================================================================
# 步骤 3.2：巡检 / 周月维护 / 季维护台账
# ----------------------------------------------------------------------
# 结构：系统 → 检查项或维护项 → 台账明细 → 台账汇总表。
# 三类台账共用统一模型（OperationLedger/OperationLedgerItem），
# 通过 ledger_type + maintenance_cycle 区分，不为三类台账复制三套表。
# 本步骤只记录异常，不转故障/工单，不修改系统健康状态（步骤 3.1 逻辑），
# 不建设计划提醒、系统履历与现场采集能力。
# ======================================================================

# 台账类型
LEDGER_TYPE_INSPECTION = 'inspection'    # 巡检
LEDGER_TYPE_WEEK_MONTH = 'week_month'    # 周月维护（周期字段区分周/月）
LEDGER_TYPE_SEASONAL = 'seasonal'        # 季维护（正式名称，不用"季度维护"）
LEDGER_TYPE_VALUES = ['inspection', 'week_month', 'seasonal']

# 维护周期
CYCLE_WEEK = 'week'
CYCLE_MONTH = 'month'
CYCLE_SEASON = 'season'
CYCLE_VALUES = ['week', 'month', 'season']

# 周月维护模板项目的执行范围
EXEC_SCOPE_ALL = 'all'              # 周月均执行
EXEC_SCOPE_WEEK_ONLY = 'week_only'  # 仅每周执行
EXEC_SCOPE_MONTH_ONLY = 'month_only'
EXEC_SCOPE_VALUES = ['all', 'week_only', 'month_only']

# 台账状态
LEDGER_STATUS_DRAFT = 'draft'
LEDGER_STATUS_SUBMITTED = 'submitted'
LEDGER_STATUS_RETURNED = 'returned'
LEDGER_STATUS_REVIEWED = 'reviewed'
LEDGER_STATUS_VOID = 'void'
LEDGER_STATUS_VALUES = ['draft', 'submitted', 'returned', 'reviewed', 'void']

# 台账明细结果
ITEM_RESULT_NORMAL = 'normal'
ITEM_RESULT_ABNORMAL = 'abnormal'
ITEM_RESULT_NOT_APPLICABLE = 'not_applicable'
ITEM_RESULT_PENDING_REVIEW = 'pending_review'
ITEM_RESULT_VALUES = ['normal', 'abnormal', 'not_applicable', 'pending_review']

# 台账明细录入类型（模板项目与明细快照共用）
LEDGER_INPUT_TYPE_VALUES = ['text', 'number', 'choice', 'multi_choice', 'boolean', 'attachment']

# 台账创建来源
LEDGER_FROM_TEMPLATE = 'template'
LEDGER_FROM_MANUAL = 'manual'
LEDGER_FROM_VALUES = ['template', 'manual']

# 录入渠道：当前固定 web（平台电脑端事后录入），保留字段作未来扩展边界
ENTRY_CHANNEL_WEB = 'web'
ENTRY_CHANNEL_VALUES = ['web']

# 台账类型 → 编号前缀
LEDGER_NO_PREFIX_MAP = {
    LEDGER_TYPE_INSPECTION: 'EL-INS',
    LEDGER_TYPE_WEEK_MONTH: 'EL-WM',
    LEDGER_TYPE_SEASONAL: 'EL-SE',
}

# 展示文本映射
LEDGER_TYPE_TEXT = {
    LEDGER_TYPE_INSPECTION: '巡检',
    LEDGER_TYPE_WEEK_MONTH: '周月维护',
    LEDGER_TYPE_SEASONAL: '季维护',
}
LEDGER_CYCLE_TEXT = {CYCLE_WEEK: '周', CYCLE_MONTH: '月', CYCLE_SEASON: '季'}


def ledger_cycle_combo_q(ledger_type_field, cycle_field):
    """台账类型与维护周期的合法组合（台账表头与模板共用 DB 校验）：

    - 巡检：不要求维护周期（固定空串）；
    - 周月维护：必须为周或月；
    - 季维护：固定为季。
    """
    return (
        models.Q(**{ledger_type_field: LEDGER_TYPE_INSPECTION, cycle_field: ''}) |
        models.Q(**{ledger_type_field: LEDGER_TYPE_WEEK_MONTH, cycle_field + '__in': [CYCLE_WEEK, CYCLE_MONTH]}) |
        models.Q(**{ledger_type_field: LEDGER_TYPE_SEASONAL, cycle_field: CYCLE_SEASON})
    )


class OperationLedgerTemplate(TenantModelMixin, models.Model):
    """运维台账模板：巡检/周月维护/季维护共用，ledger_type 决定用途。

    - 模板只决定以后生成的台账内容，修改不影响已生成台账（明细保存快照）；
    - 适用范围：可选系统类型 + 可选具体系统（多选），不得自由填写系统名称；
    - 停用后不能用于新台账，历史记录继续可查；
    - 周期组合校验：巡检空 / 周月维护 week|month / 季维护 season。
    """

    name = models.CharField(max_length=100, help_text='模板名称')
    template_code = models.CharField(max_length=50, help_text='模板编号，租户内唯一')
    ledger_type = models.CharField(max_length=20, help_text='台账类型')
    maintenance_cycle = models.CharField(
        max_length=20, default='', blank=True, help_text='周月维护周期（week/month/season；巡检为空）')
    applicable_systems = models.ManyToManyField(
        LifecycleSystem, blank=True, related_name='ledger_templates',
        db_table='tdyw_el_ledger_template_systems', help_text='适用具体系统（可多选）')
    description = models.CharField(max_length=500, default='', blank=True, help_text='说明')
    is_active = models.BooleanField(default=True, help_text='是否启用（停用后不能用于新台账）')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_ledger_template'
        verbose_name = '运维台账模板'
        verbose_name_plural = '运维台账模板'
        ordering = ('-created_at', '-id')
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'template_code'], name='uniq_el_ledger_template_code'),
            models.CheckConstraint(
                check=models.Q(ledger_type__in=LEDGER_TYPE_VALUES),
                name='el_ledger_template_type_valid',
            ),
            models.CheckConstraint(
                check=ledger_cycle_combo_q('ledger_type', 'maintenance_cycle'),
                name='el_ledger_template_cycle_combo',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'ledger_type']),
        ]

    def __repr__(self):
        return '<OperationLedgerTemplate %r>' % self.template_code

    def applies_to_system(self, system):
        """模板是否适用于指定系统（按具体系统匹配）。"""
        return self.applicable_systems.all().filter(pk=system.pk).exists()

    def to_view(self, with_counts=False):
        data = {
            'id': self.id,
            'name': self.name,
            'template_code': self.template_code,
            'ledger_type': self.ledger_type,
            'maintenance_cycle': self.maintenance_cycle,
            'description': self.description,
            'is_active': self.is_active,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        if with_counts:
            data['items_count'] = self.items.filter(is_active=True).count()
        return data


class OperationLedgerTemplateItem(TenantModelMixin, models.Model):
    """台账模板项目：模板中的检查或维护项目。

    - 录入类型支持文本/数值/单选/多选/布尔/附件；
    - 周月维护模板项目通过 execution_scope 区分 仅每周/仅每月/周月均执行，
      生成台账时只加载与本次维护周期匹配的项目；
    - 停用或删除项目不影响历史台账明细（明细保存全量快照）。
    """

    template = models.ForeignKey(
        OperationLedgerTemplate, models.CASCADE, related_name='items', help_text='所属模板')
    item_code = models.CharField(max_length=50, help_text='项目编码，模板内唯一')
    name = models.CharField(max_length=100, help_text='项目名称')
    standard = models.CharField(max_length=500, default='', blank=True, help_text='检查或维护标准')
    input_type = models.CharField(max_length=20, help_text='录入类型')
    unit = models.CharField(max_length=20, default='', blank=True, help_text='单位')
    normal_range = models.CharField(max_length=100, default='', blank=True, help_text='正常范围（展示文本）')
    number_min = models.FloatField(null=True, blank=True, help_text='数值正常下限（含，自动判定用）')
    number_max = models.FloatField(null=True, blank=True, help_text='数值正常上限（含，自动判定用）')
    choices = models.TextField(default='', blank=True, help_text='候选项 JSON 数组（单选/多选）')
    default_value = models.CharField(max_length=200, default='', blank=True, help_text='默认值')
    is_required = models.BooleanField(default=False, help_text='是否必填')
    execution_scope = models.CharField(
        max_length=20, default=EXEC_SCOPE_ALL, help_text='执行范围（周月维护模板：all/week_only/month_only）')
    abnormal_rule = models.CharField(max_length=200, default='', blank=True, help_text='异常判定规则')
    operation_guide = models.CharField(max_length=500, default='', blank=True, help_text='操作说明')
    display_order = models.IntegerField(default=0, help_text='显示顺序，小者靠前')
    is_active = models.BooleanField(default=True, help_text='是否启用')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_ledger_template_item'
        verbose_name = '台账模板项目'
        verbose_name_plural = '台账模板项目'
        ordering = ('display_order', 'id')
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'template', 'item_code'],
                name='uniq_el_ledger_template_item_code'),
            models.CheckConstraint(
                check=models.Q(input_type__in=LEDGER_INPUT_TYPE_VALUES),
                name='el_ledger_template_item_input_type_valid',
            ),
            models.CheckConstraint(
                check=models.Q(execution_scope__in=EXEC_SCOPE_VALUES),
                name='el_ledger_template_item_scope_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'template']),
        ]

    def __repr__(self):
        return '<OperationLedgerTemplateItem %r>' % self.item_code

    def get_choices(self):
        if not self.choices:
            return []
        try:
            data = json.loads(self.choices)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    def matches_cycle(self, cycle):
        """项目是否匹配本次维护周期：周月维护模板按 scope 过滤，其余全匹配。"""
        if self.template.ledger_type != LEDGER_TYPE_WEEK_MONTH:
            return True
        if self.execution_scope == EXEC_SCOPE_ALL:
            return True
        if self.execution_scope == EXEC_SCOPE_WEEK_ONLY:
            return cycle == CYCLE_WEEK
        return cycle == CYCLE_MONTH

    def to_view(self):
        return {
            'id': self.id,
            'template': self.template_id,
            'item_code': self.item_code,
            'name': self.name,
            'standard': self.standard,
            'input_type': self.input_type,
            'unit': self.unit,
            'normal_range': self.normal_range,
            'number_min': self.number_min,
            'number_max': self.number_max,
            'choices': self.get_choices(),
            'default_value': self.default_value,
            'is_required': self.is_required,
            'execution_scope': self.execution_scope,
            'abnormal_rule': self.abnormal_rule,
            'operation_guide': self.operation_guide,
            'display_order': self.display_order,
            'is_active': self.is_active,
        }


class OperationLedger(TenantModelMixin, models.Model):
    """运维台账表头：巡检/周月维护/季维护共用，一张台账可汇总多个系统的明细。

    - 系统不是整张台账的边界，而是每条明细（OperationLedgerItem）的归属；
    - 实际执行时间（executed_date/executed_start/executed_end）与平台录入
      时间（created_at）分别保存，录入时间不冒充实际执行时间；
    - entry_channel 当前固定 web；状态流转由后端校验（STATE_TRANSITIONS）；
    - version 用于可编辑状态下的并发控制；作废为受控终态，不物理删除；
    - 台账异常不修改系统健康状态（步骤 3.1 逻辑独立）。
    """

    ledger_no = models.CharField(max_length=50, help_text='台账编号，租户内唯一，自动生成')
    ledger_type = models.CharField(max_length=20, help_text='台账类型')
    maintenance_cycle = models.CharField(
        max_length=20, default='', blank=True, help_text='维护周期（week/month/season；巡检为空）')
    executed_date = models.DateField(help_text='实际执行日期')
    shift = models.CharField(max_length=50, default='', blank=True, help_text='班次')
    location_scope = models.CharField(max_length=200, default='', blank=True, help_text='机房、区域或维护范围')
    executor_names = models.CharField(max_length=200, default='', blank=True, help_text='执行人（多人以顿号或逗号分隔）')
    collaborator_names = models.CharField(max_length=200, default='', blank=True, help_text='协作人')
    summary = models.TextField(max_length=2000, default='', blank=True, help_text='总体说明')
    status = models.CharField(max_length=20, default=LEDGER_STATUS_DRAFT, help_text='台账状态')
    executed_start = models.DateTimeField(null=True, blank=True, help_text='实际执行开始时间')
    executed_end = models.DateTimeField(null=True, blank=True, help_text='实际执行结束时间')
    entry_channel = models.CharField(max_length=20, default=ENTRY_CHANNEL_WEB, help_text='录入渠道（当前固定 web）')
    entry_note = models.CharField(max_length=500, default='', blank=True, help_text='补录说明')
    created_from = models.CharField(max_length=20, default=LEDGER_FROM_TEMPLATE, help_text='创建方式（template 模板生成 / manual 临时补录）')
    client_token = models.CharField(max_length=64, default='', blank=True, help_text='客户端幂等令牌（创建防重复）')
    version = models.IntegerField(default=1, help_text='并发编辑版本号')
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)
    reviewer_name = models.CharField(max_length=100, default='', blank=True, help_text='复核人姓名快照')
    returned_at = models.DateTimeField(null=True, blank=True)
    returned_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)
    return_reason = models.CharField(max_length=500, default='', blank=True, help_text='最近一次退回原因')
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)
    void_reason = models.CharField(max_length=500, default='', blank=True, help_text='作废原因')
    created_at = models.DateTimeField(auto_now_add=True, help_text='平台录入时间')
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    # 状态机：允许的流转（后端强制校验）
    STATE_TRANSITIONS = {
        LEDGER_STATUS_DRAFT: {LEDGER_STATUS_SUBMITTED, LEDGER_STATUS_VOID},
        LEDGER_STATUS_SUBMITTED: {LEDGER_STATUS_REVIEWED, LEDGER_STATUS_RETURNED, LEDGER_STATUS_VOID},
        LEDGER_STATUS_RETURNED: {LEDGER_STATUS_SUBMITTED, LEDGER_STATUS_VOID},
        LEDGER_STATUS_REVIEWED: {LEDGER_STATUS_VOID},
        LEDGER_STATUS_VOID: set(),
    }
    # 允许编辑明细的状态（草稿与被退回）
    EDITABLE_STATUSES = {LEDGER_STATUS_DRAFT, LEDGER_STATUS_RETURNED}

    class Meta:
        db_table = 'tdyw_el_operation_ledger'
        verbose_name = '运维台账'
        verbose_name_plural = '运维台账'
        ordering = ('-created_at', '-id')
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'ledger_no'], name='uniq_el_operation_ledger_no'),
            models.CheckConstraint(
                check=models.Q(ledger_type__in=LEDGER_TYPE_VALUES),
                name='el_operation_ledger_type_valid',
            ),
            models.CheckConstraint(
                check=ledger_cycle_combo_q('ledger_type', 'maintenance_cycle'),
                name='el_operation_ledger_cycle_combo',
            ),
            models.CheckConstraint(
                check=models.Q(status__in=LEDGER_STATUS_VALUES),
                name='el_operation_ledger_status_valid',
            ),
            models.CheckConstraint(
                check=models.Q(entry_channel__in=ENTRY_CHANNEL_VALUES),
                name='el_operation_ledger_entry_channel_web',
            ),
            models.CheckConstraint(
                check=models.Q(created_from__in=LEDGER_FROM_VALUES),
                name='el_operation_ledger_created_from_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'ledger_type', 'status']),
            models.Index(fields=['tenant_id', 'executed_date']),
            models.Index(fields=['tenant_id', 'client_token']),
        ]

    def __repr__(self):
        return '<OperationLedger %r>' % self.ledger_no

    def can_transition_to(self, new_status):
        return new_status in self.STATE_TRANSITIONS.get(self.status, set())

    def to_view(self, with_counts=False):
        data = {
            'id': self.id,
            'ledger_no': self.ledger_no,
            'ledger_type': self.ledger_type,
            'maintenance_cycle': self.maintenance_cycle,
            'executed_date': self.executed_date,
            'shift': self.shift,
            'location_scope': self.location_scope,
            'executor_names': self.executor_names,
            'collaborator_names': self.collaborator_names,
            'summary': self.summary,
            'status': self.status,
            'executed_start': self.executed_start,
            'executed_end': self.executed_end,
            'entry_channel': self.entry_channel,
            'entry_note': self.entry_note,
            'created_from': self.created_from,
            'version': self.version,
            'submitted_at': self.submitted_at,
            'reviewed_at': self.reviewed_at,
            'reviewer_name': self.reviewer_name,
            'returned_at': self.returned_at,
            'return_reason': self.return_reason,
            'voided_at': self.voided_at,
            'void_reason': self.void_reason,
            'created_at': self.created_at,
            'created_by': self.created_by_id,
            'created_by_name': self.created_by.username if self.created_by_id else '',
        }
        if with_counts:
            data['items_count'] = self.items.count()
            data['abnormal_count'] = self.items.filter(result=ITEM_RESULT_ABNORMAL).count()
        return data


class OperationLedgerItem(TenantModelMixin, models.Model):
    """运维台账明细：一次检查/维护的最小记录，归属某张台账与某个正式系统。

    - 每条明细必须关联正式系统 ID（LifecycleSystem PROTECT），并保存
      系统编号/名称/地点快照——系统改名后外键仍有效，历史显示快照；
    - 模板来源明细保存当时模板项目全量快照，不得只存 template_item_id
      后实时读取模板内容（template_item 仅溯源，SET_NULL）；
    - 填写值按录入类型分列（value_text/value_number/value_bool），可校验；
    - 结果支持 正常/异常/不适用/待复核；异常明细具稳定主键（本表 id），
      为步骤 3.3 异常转故障/工单预留来源关联；本模块不修改系统健康状态。
    """

    ledger = models.ForeignKey(
        OperationLedger, models.CASCADE, related_name='items', help_text='所属台账')
    system = models.ForeignKey(
        LifecycleSystem, models.PROTECT, related_name='ledger_items', help_text='所属系统（正式系统 ID）')
    # —— 系统快照 ——
    system_code_snapshot = models.CharField(max_length=50, default='', blank=True, help_text='系统编号快照')
    system_name_snapshot = models.CharField(max_length=100, default='', blank=True, help_text='系统名称快照')
    system_location_snapshot = models.CharField(max_length=200, default='', blank=True, help_text='系统安装地点快照')
    # —— 模板项目快照 ——
    template_item = models.ForeignKey(
        OperationLedgerTemplateItem, models.SET_NULL, related_name='ledger_items', null=True, blank=True,
        help_text='来源模板项目（仅溯源；历史明细不依赖其当前内容）')
    template_name_snapshot = models.CharField(max_length=100, default='', blank=True, help_text='模板名称快照')
    item_code_snapshot = models.CharField(max_length=50, default='', blank=True, help_text='项目编码快照')
    item_name_snapshot = models.CharField(max_length=100, help_text='检查或维护项目名称快照')
    standard_snapshot = models.CharField(max_length=500, default='', blank=True, help_text='标准要求快照')
    input_type = models.CharField(max_length=20, help_text='录入类型快照')
    unit_snapshot = models.CharField(max_length=20, default='', blank=True, help_text='单位快照')
    normal_range_snapshot = models.CharField(max_length=100, default='', blank=True, help_text='正常范围快照')
    choices_snapshot = models.TextField(default='', blank=True, help_text='候选项快照 JSON 数组')
    number_min = models.FloatField(null=True, blank=True, help_text='数值正常下限快照（自动判定用）')
    number_max = models.FloatField(null=True, blank=True, help_text='数值正常上限快照（自动判定用）')
    is_required = models.BooleanField(default=False, help_text='必填规则快照')
    abnormal_rule_snapshot = models.CharField(max_length=200, default='', blank=True, help_text='异常判定规则快照')
    execution_scope = models.CharField(max_length=20, default=EXEC_SCOPE_ALL, help_text='执行范围快照')
    # —— 填写值（按录入类型分列，可校验） ——
    value_text = models.TextField(default='', blank=True, help_text='文本类值（多选为 JSON 选项数组）')
    value_number = models.FloatField(null=True, blank=True, help_text='数值填写值')
    value_bool = models.BooleanField(null=True, blank=True, help_text='布尔填写值')
    # —— 结果与异常 ——
    result = models.CharField(max_length=20, help_text='结果：normal/abnormal/not_applicable/pending_review')
    is_auto_judged = models.BooleanField(default=False, help_text='结果是否由数值范围自动判定')
    correction_reason = models.CharField(max_length=200, default='', blank=True, help_text='修正自动判定结果的原因')
    abnormal_desc = models.CharField(max_length=500, default='', blank=True, help_text='异常说明（异常项必填）')
    na_reason = models.CharField(max_length=200, default='', blank=True, help_text='不适用原因')
    onsite_action = models.CharField(max_length=500, default='', blank=True, help_text='现场处理内容')
    executor_name = models.CharField(max_length=100, default='', blank=True, help_text='明细执行人')
    executed_at = models.DateTimeField(null=True, blank=True, help_text='明细实际执行时间')
    is_temporary = models.BooleanField(default=False, help_text='是否临时增加项（只属于当前台账，不写回模板）')
    display_order = models.IntegerField(default=0, help_text='显示顺序，小者靠前')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_operation_ledger_item'
        verbose_name = '运维台账明细'
        verbose_name_plural = '运维台账明细'
        ordering = ('system_id', 'display_order', 'id')
        constraints = [
            models.CheckConstraint(
                check=models.Q(input_type__in=LEDGER_INPUT_TYPE_VALUES),
                name='el_ledger_item_input_type_valid',
            ),
            models.CheckConstraint(
                check=models.Q(result__in=ITEM_RESULT_VALUES),
                name='el_ledger_item_result_valid',
            ),
            models.CheckConstraint(
                check=models.Q(execution_scope__in=EXEC_SCOPE_VALUES),
                name='el_ledger_item_scope_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['ledger', 'system']),
            models.Index(fields=['tenant_id', 'system', 'result']),
            models.Index(fields=['tenant_id', 'result']),
        ]

    def __repr__(self):
        return '<OperationLedgerItem ledger=%s system=%s %r>' % (
            self.ledger_id, self.system_id, self.item_name_snapshot)

    def get_choices(self):
        if not self.choices_snapshot:
            return []
        try:
            data = json.loads(self.choices_snapshot)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    def get_value_list(self):
        """value_text 的 JSON 数组形态（多选候选项）。"""
        if not self.value_text:
            return []
        try:
            data = json.loads(self.value_text)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    def to_view(self):
        return {
            'id': self.id,
            'ledger': self.ledger_id,
            'system': self.system_id,
            'system_code': self.system_code_snapshot,
            'system_name': self.system_name_snapshot,
            'system_location': self.system_location_snapshot,
            'template_item': self.template_item_id,
            'template_name': self.template_name_snapshot,
            'item_code': self.item_code_snapshot,
            'item_name': self.item_name_snapshot,
            'standard': self.standard_snapshot,
            'input_type': self.input_type,
            'unit': self.unit_snapshot,
            'normal_range': self.normal_range_snapshot,
            'number_min': self.number_min,
            'number_max': self.number_max,
            'choices': self.get_choices(),
            'is_required': self.is_required,
            'abnormal_rule': self.abnormal_rule_snapshot,
            'execution_scope': self.execution_scope,
            'value_text': self.value_text,
            'value_number': self.value_number,
            'value_bool': self.value_bool,
            'result': self.result,
            'is_auto_judged': self.is_auto_judged,
            'correction_reason': self.correction_reason,
            'abnormal_desc': self.abnormal_desc,
            'na_reason': self.na_reason,
            'onsite_action': self.onsite_action,
            'executor_name': self.executor_name,
            'executed_at': self.executed_at,
            'is_temporary': self.is_temporary,
            'display_order': self.display_order,
        }


# ======================================================================
# 步骤 3.3：工单管理与异常转单
# ----------------------------------------------------------------------
# 结构：工单主表（一张工单只关联一个作业系统）→ 参与人 / 处理记录，
# 来源关联故障或台账明细。
# 状态流转由后端状态机校验（SystemWorkOrder.STATE_TRANSITIONS）；
# 执行中且 affects_system_operation=True 的"故障维修"工单参与统一
# 健康状态计算（fault_services，"维修中"），其余工单不影响系统健康状态。
# 本步骤不建统一系统履历、计划提醒、库存/调拨与系统升级嫁接。
# ======================================================================

# 工单类型（稳定编码，页面中文名称不得作为关联条件）
WORK_TYPE_REPAIR = 'repair'                    # 故障维修
WORK_TYPE_SPECIAL_MAINTENANCE = 'special_maintenance'  # 专项维护
WORK_TYPE_TECH_REFORM = 'tech_reform'          # 技术改造
WORK_TYPE_CONFIG_CHANGE = 'config_change'      # 配置变更
WORK_TYPE_FIELD_TEST = 'field_test'            # 现场测试
WORK_TYPE_CALIBRATION = 'calibration'          # 校准
WORK_ORDER_TYPE_VALUES = [
    WORK_TYPE_REPAIR, WORK_TYPE_SPECIAL_MAINTENANCE, WORK_TYPE_TECH_REFORM,
    WORK_TYPE_CONFIG_CHANGE, WORK_TYPE_FIELD_TEST, WORK_TYPE_CALIBRATION,
]

# 工单状态（后端状态机：STATE_TRANSITIONS）
WORK_ORDER_STATUS_PENDING_DISPATCH = 'pending_dispatch'  # 待派发
WORK_ORDER_STATUS_PENDING_ACCEPT = 'pending_accept'      # 待接单
WORK_ORDER_STATUS_EXECUTING = 'executing'                # 执行中
WORK_ORDER_STATUS_PENDING_REVIEW = 'pending_review'      # 待复核
WORK_ORDER_STATUS_COMPLETED = 'completed'                # 已完成
WORK_ORDER_STATUS_CLOSED = 'closed'                      # 已关闭
WORK_ORDER_STATUS_CANCELLED = 'cancelled'                # 已取消
WORK_ORDER_STATUS_VALUES = [
    WORK_ORDER_STATUS_PENDING_DISPATCH, WORK_ORDER_STATUS_PENDING_ACCEPT,
    WORK_ORDER_STATUS_EXECUTING, WORK_ORDER_STATUS_PENDING_REVIEW,
    WORK_ORDER_STATUS_COMPLETED, WORK_ORDER_STATUS_CLOSED, WORK_ORDER_STATUS_CANCELLED,
]

# 工单来源类型
WORK_ORDER_SOURCE_MANUAL = 'manual'
WORK_ORDER_SOURCE_FAULT = 'fault'
WORK_ORDER_SOURCE_LEDGER_ITEM = 'ledger_item'
WORK_ORDER_SOURCE_VALUES = [WORK_ORDER_SOURCE_MANUAL, WORK_ORDER_SOURCE_FAULT, WORK_ORDER_SOURCE_LEDGER_ITEM]

# 优先级
WORK_ORDER_PRIORITY_VALUES = ['low', 'normal', 'high', 'urgent']

# 参与人角色
WORK_ORDER_ROLE_OWNER = 'owner'
WORK_ORDER_ROLE_PARTICIPANT = 'participant'
WORK_ORDER_ROLE_VALUES = [WORK_ORDER_ROLE_OWNER, WORK_ORDER_ROLE_PARTICIPANT]

# 工单编号前缀
WORK_ORDER_NO_PREFIX = 'WO'

# 台账异常明细处置状态（由来源关系动态计算，不落库、不依赖前端）
DISPOSITION_NONE = 'none'                      # 未处置
DISPOSITION_CONVERTED_FAULT = 'converted_fault'          # 已转故障
DISPOSITION_CONVERTED_WORK_ORDER = 'converted_work_order'  # 已转工单
DISPOSITION_TARGET_CANCELLED = 'target_cancelled'        # 处置目标已取消或作废
DISPOSITION_STATUS_VALUES = [
    DISPOSITION_NONE, DISPOSITION_CONVERTED_FAULT,
    DISPOSITION_CONVERTED_WORK_ORDER, DISPOSITION_TARGET_CANCELLED,
]


class SystemWorkOrder(TenantModelMixin, models.Model):
    """系统工单主表（步骤 3.3，单系统简化）。

    关联规则（一张工单只关联一个作业系统，不建设跨系统影响关系）：
    - 作业系统必须通过正式系统 ID 外键关联（PROTECT），页面只显示名称；
    - 工单创建时保存作业系统快照（编号/名称/安装地点），系统改名后
      历史工单显示快照但外键仍然有效；
    - affects_system_operation 记录"作业期间是否影响系统运行"：
      只有执行中且影响运行的工单才使系统进入"维修中"状态；
    - 可选引用配置组成项（SET_NULL + 名称快照），组成项修改/删除不影响历史；
    - 来源：manual 人工创建 / fault 来源故障 / ledger_item 来源台账异常明细，
      来源一律用真实外键（PROTECT），不保存自由文本冒充来源。
    一次实际工作涉及多个独立系统时分别建立工单，不允许一单关联多系统。

    状态流转（后端校验，动作接口触发）：
    待派发 →(dispatch)→ 待接单 →(start)→ 执行中 →(submit)→ 待复核
      →(review pass)→ 已完成 →(close)→ 已关闭；
    待复核 →(review return)→ 执行中；
    待派发/待接单/执行中/待复核 →(cancel, del 权限)→ 已取消。
    接单（accept）为待接单状态内的确认动作（记录接单人），不改变状态；
    已关闭/已取消为终态，不参与健康状态计算。
    """

    STATUS_PENDING_DISPATCH = WORK_ORDER_STATUS_PENDING_DISPATCH
    STATUS_PENDING_ACCEPT = WORK_ORDER_STATUS_PENDING_ACCEPT
    STATUS_EXECUTING = WORK_ORDER_STATUS_EXECUTING
    STATUS_PENDING_REVIEW = WORK_ORDER_STATUS_PENDING_REVIEW
    STATUS_COMPLETED = WORK_ORDER_STATUS_COMPLETED
    STATUS_CLOSED = WORK_ORDER_STATUS_CLOSED
    STATUS_CANCELLED = WORK_ORDER_STATUS_CANCELLED
    STATUS_CHOICES = (
        (STATUS_PENDING_DISPATCH, '待派发'),
        (STATUS_PENDING_ACCEPT, '待接单'),
        (STATUS_EXECUTING, '执行中'),
        (STATUS_PENDING_REVIEW, '待复核'),
        (STATUS_COMPLETED, '已完成'),
        (STATUS_CLOSED, '已关闭'),
        (STATUS_CANCELLED, '已取消'),
    )
    STATUS_TEXT_MAP = dict(STATUS_CHOICES)

    # 允许的状态流转（后端强制校验）
    STATE_TRANSITIONS = {
        STATUS_PENDING_DISPATCH: {STATUS_PENDING_ACCEPT, STATUS_CANCELLED},
        STATUS_PENDING_ACCEPT: {STATUS_EXECUTING, STATUS_CANCELLED},
        STATUS_EXECUTING: {STATUS_PENDING_REVIEW, STATUS_CANCELLED},
        STATUS_PENDING_REVIEW: {STATUS_COMPLETED, STATUS_EXECUTING, STATUS_CANCELLED},
        STATUS_COMPLETED: {STATUS_CLOSED},
        STATUS_CLOSED: set(),
        STATUS_CANCELLED: set(),
    }
    # 允许普通编辑的状态（仅待派发）
    EDITABLE_STATUSES = {STATUS_PENDING_DISPATCH}
    # 允许受控取消的状态
    CANCELLABLE_STATUSES = {
        STATUS_PENDING_DISPATCH, STATUS_PENDING_ACCEPT,
        STATUS_EXECUTING, STATUS_PENDING_REVIEW,
    }

    TYPE_REPAIR = WORK_TYPE_REPAIR
    TYPE_SPECIAL_MAINTENANCE = WORK_TYPE_SPECIAL_MAINTENANCE
    TYPE_TECH_REFORM = WORK_TYPE_TECH_REFORM
    TYPE_CONFIG_CHANGE = WORK_TYPE_CONFIG_CHANGE
    TYPE_FIELD_TEST = WORK_TYPE_FIELD_TEST
    TYPE_CALIBRATION = WORK_TYPE_CALIBRATION
    TYPE_CHOICES = (
        (TYPE_REPAIR, '故障维修'),
        (TYPE_SPECIAL_MAINTENANCE, '专项维护'),
        (TYPE_TECH_REFORM, '技术改造'),
        (TYPE_CONFIG_CHANGE, '配置变更'),
        (TYPE_FIELD_TEST, '现场测试'),
        (TYPE_CALIBRATION, '校准'),
    )
    TYPE_TEXT_MAP = dict(TYPE_CHOICES)

    SOURCE_MANUAL = WORK_ORDER_SOURCE_MANUAL
    SOURCE_FAULT = WORK_ORDER_SOURCE_FAULT
    SOURCE_LEDGER_ITEM = WORK_ORDER_SOURCE_LEDGER_ITEM
    SOURCE_CHOICES = (
        (SOURCE_MANUAL, '人工创建'),
        (SOURCE_FAULT, '来源故障'),
        (SOURCE_LEDGER_ITEM, '来源台账异常'),
    )
    SOURCE_TEXT_MAP = dict(SOURCE_CHOICES)

    PRIORITY_LOW = 'low'
    PRIORITY_NORMAL = 'normal'
    PRIORITY_HIGH = 'high'
    PRIORITY_URGENT = 'urgent'
    PRIORITY_CHOICES = (
        (PRIORITY_LOW, '较低'),
        (PRIORITY_NORMAL, '一般'),
        (PRIORITY_HIGH, '高'),
        (PRIORITY_URGENT, '紧急'),
    )
    PRIORITY_TEXT_MAP = dict(PRIORITY_CHOICES)

    work_no = models.CharField(max_length=50, help_text='工单编号，租户内唯一，自动生成')
    title = models.CharField(max_length=100, help_text='工单标题')
    work_type = models.CharField(max_length=30, choices=TYPE_CHOICES, help_text='工单类型（稳定编码）')
    priority = models.CharField(
        max_length=20, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL, help_text='优先级')

    # —— 来源（真实外键 + 编号快照；人工工单两者必须为空） ——
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_MANUAL,
                                   help_text='来源类型')
    source_fault = models.ForeignKey(
        SystemFault, models.PROTECT, related_name='generated_work_orders', null=True, blank=True,
        help_text='来源故障（source_type=fault 时必填）')
    source_ledger_item = models.ForeignKey(
        OperationLedgerItem, models.PROTECT, related_name='generated_work_orders', null=True, blank=True,
        help_text='来源台账异常明细（source_type=ledger_item 时必填）')
    source_no = models.CharField(max_length=50, default='', blank=True,
                                 help_text='来源单据编号快照（故障编号或台账编号，列表显示与追溯）')

    # —— 作业系统（正式外键 + 创建时快照） ——
    system = models.ForeignKey(
        LifecycleSystem, models.PROTECT, related_name='work_orders',
        help_text='作业系统（本次作业对象系统，外键关联系统主数据，一张工单只关联一个系统）')
    system_code = models.CharField(max_length=50, help_text='作业系统编号快照')
    system_name = models.CharField(max_length=100, help_text='作业系统名称快照')
    system_location = models.CharField(max_length=200, help_text='作业系统安装地点快照')
    affects_system_operation = models.BooleanField(
        default=False, help_text='作业期间是否影响系统运行（执行中且为真才参与"维修中"计算）')

    work_location = models.CharField(max_length=200, default='', blank=True, help_text='作业位置')
    work_object_desc = models.TextField(max_length=1000, default='', blank=True,
                                        help_text='具体作业对象描述')
    work_component = models.ForeignKey(
        SystemConfigComponent, models.SET_NULL, related_name='work_orders', null=True, blank=True,
        help_text='可选配置组成项引用（非必填，非创建前置条件）')
    work_component_name = models.CharField(max_length=100, default='', blank=True,
                                           help_text='配置组成项名称快照（组成项修改后不变）')

    owner = models.ForeignKey(User, models.PROTECT, related_name='owned_work_orders',
                              null=True, blank=True, help_text='当前负责人（派发时指定）')
    dispatched_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                      help_text='派发人')
    dispatched_at = models.DateTimeField(null=True, blank=True, help_text='派发时间')
    accepted_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                    help_text='接单人')
    accepted_at = models.DateTimeField(null=True, blank=True, help_text='接单时间')

    planned_start = models.DateTimeField(null=True, blank=True, help_text='计划开始时间')
    planned_end = models.DateTimeField(null=True, blank=True, help_text='计划结束时间')
    actual_start = models.DateTimeField(null=True, blank=True, help_text='实际开始时间（开始执行时记录）')
    actual_end = models.DateTimeField(null=True, blank=True, help_text='实际完成时间（复核通过时记录）')

    work_requirement = models.TextField(max_length=2000, default='', blank=True, help_text='作业要求')
    work_steps = models.TextField(max_length=2000, default='', blank=True, help_text='作业步骤')
    process_result = models.TextField(max_length=2000, default='', blank=True,
                                      help_text='处理结果（提交复核前必填）')
    work_hours = models.FloatField(null=True, blank=True, help_text='工时（小时）')
    interrupt_hours = models.FloatField(null=True, blank=True, help_text='系统中断时间（小时）')
    material_note = models.TextField(max_length=500, default='', blank=True,
                                     help_text='材料说明（名称/型号/数量/单位/说明/可选外部库存编号）')

    reviewer = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                 help_text='复核人')
    reviewed_at = models.DateTimeField(null=True, blank=True, help_text='复核时间')
    review_result = models.TextField(max_length=1000, default='', blank=True, help_text='复核结果')
    return_reason = models.CharField(max_length=500, default='', blank=True,
                                     help_text='最近一次复核退回原因')
    closed_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                  help_text='关闭人')
    closed_at = models.DateTimeField(null=True, blank=True, help_text='关闭时间')
    cancelled_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                     help_text='取消人')
    cancelled_at = models.DateTimeField(null=True, blank=True, help_text='取消时间')
    cancel_reason = models.CharField(max_length=500, default='', blank=True, help_text='取消原因')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_PENDING_DISPATCH, help_text='当前状态')
    client_token = models.CharField(max_length=64, default='', blank=True,
                                    help_text='客户端幂等令牌（创建/转单防重复）')
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+', help_text='创建人')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_work_order'
        verbose_name = '系统工单'
        verbose_name_plural = '系统工单'
        ordering = ('-created_at', '-id')
        constraints = [
            models.UniqueConstraint(fields=['tenant_id', 'work_no'], name='uniq_el_work_order_tenant_no'),
            models.CheckConstraint(
                check=models.Q(work_type__in=WORK_ORDER_TYPE_VALUES),
                name='el_work_order_type_valid',
            ),
            models.CheckConstraint(
                check=models.Q(status__in=WORK_ORDER_STATUS_VALUES),
                name='el_work_order_status_valid',
            ),
            models.CheckConstraint(
                check=models.Q(priority__in=WORK_ORDER_PRIORITY_VALUES),
                name='el_work_order_priority_valid',
            ),
            models.CheckConstraint(
                check=models.Q(source_type__in=WORK_ORDER_SOURCE_VALUES),
                name='el_work_order_source_valid',
            ),
            # 来源类型与来源对象必须匹配：manual 两者皆空，fault/ledger_item 只允许对应外键
            models.CheckConstraint(
                check=(
                    (models.Q(source_type=WORK_ORDER_SOURCE_MANUAL)
                     & models.Q(source_fault__isnull=True)
                     & models.Q(source_ledger_item__isnull=True))
                    | (models.Q(source_type=WORK_ORDER_SOURCE_FAULT)
                       & models.Q(source_fault__isnull=False)
                       & models.Q(source_ledger_item__isnull=True))
                    | (models.Q(source_type=WORK_ORDER_SOURCE_LEDGER_ITEM)
                       & models.Q(source_fault__isnull=True)
                       & models.Q(source_ledger_item__isnull=False))
                ),
                name='el_work_order_source_consistent',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'status']),
            models.Index(fields=['tenant_id', 'work_type', 'status']),
            models.Index(fields=['tenant_id', 'system', '-created_at', '-id']),
            models.Index(fields=['tenant_id', 'client_token']),
            models.Index(fields=['tenant_id', 'source_fault']),
            models.Index(fields=['tenant_id', 'source_ledger_item']),
        ]

    def __repr__(self):
        return '<SystemWorkOrder %r>' % self.work_no

    def can_transition_to(self, new_status):
        return new_status in self.STATE_TRANSITIONS.get(self.status, set())

    def to_view(self):
        """列表行摘要。"""
        return {
            'id': self.id,
            'work_no': self.work_no,
            'title': self.title,
            'work_type': self.work_type,
            'work_type_text': self.TYPE_TEXT_MAP.get(self.work_type, self.work_type),
            'priority': self.priority,
            'priority_text': self.PRIORITY_TEXT_MAP.get(self.priority, self.priority),
            'status': self.status,
            'status_text': self.STATUS_TEXT_MAP.get(self.status, self.status),
            'source_type': self.source_type,
            'source_type_text': self.SOURCE_TEXT_MAP.get(self.source_type, self.source_type),
            'source_no': self.source_no,
            'system': self.system_id,
            'system_name': self.system_name,
            'system_code': self.system_code,
            'affects_system_operation': self.affects_system_operation,
            'owner': self.owner_id,
            'owner_name': self.owner.username if self.owner_id else '',
            'planned_start': self.planned_start,
            'planned_end': self.planned_end,
            'actual_start': self.actual_start,
            'actual_end': self.actual_end,
            'created_by_name': self.created_by.username if self.created_by_id else '',
            'created_at': self.created_at,
        }

    def to_detail_view(self):
        """详情：全字段 + 参与人 + 来源追溯信息（单系统简化，无受影响系统）。"""
        data = self.to_view()
        data.update({
            'system_location': self.system_location,
            'work_location': self.work_location,
            'work_object_desc': self.work_object_desc,
            'work_component': self.work_component_id,
            'work_component_name': self.work_component_name,
            'dispatched_by': self.dispatched_by_id,
            'dispatched_by_name': self.dispatched_by.username if self.dispatched_by_id else '',
            'dispatched_at': self.dispatched_at,
            'accepted_by': self.accepted_by_id,
            'accepted_by_name': self.accepted_by.username if self.accepted_by_id else '',
            'accepted_at': self.accepted_at,
            'work_requirement': self.work_requirement,
            'work_steps': self.work_steps,
            'process_result': self.process_result,
            'work_hours': self.work_hours,
            'interrupt_hours': self.interrupt_hours,
            'material_note': self.material_note,
            'reviewer': self.reviewer_id,
            'reviewer_name': self.reviewer.username if self.reviewer_id else '',
            'reviewed_at': self.reviewed_at,
            'review_result': self.review_result,
            'return_reason': self.return_reason,
            'closed_by': self.closed_by_id,
            'closed_by_name': self.closed_by.username if self.closed_by_id else '',
            'closed_at': self.closed_at,
            'cancelled_by': self.cancelled_by_id,
            'cancelled_by_name': self.cancelled_by.username if self.cancelled_by_id else '',
            'cancelled_at': self.cancelled_at,
            'cancel_reason': self.cancel_reason,
            'client_token': self.client_token,
            'updated_at': self.updated_at,
            'participants': [row.to_view() for row in self.participants.all()],
            # 来源追溯：故障来源给出故障主键；台账来源给出台账与明细定位信息
            'source_fault': self.source_fault_id,
            'source_ledger_item': self.source_ledger_item_id,
            'source_ledger': self.source_ledger_item.ledger_id if self.source_ledger_item_id else None,
            'source_ledger_type': (
                self.source_ledger_item.ledger.ledger_type if self.source_ledger_item_id else ''),
        })
        return data


class SystemWorkOrderParticipant(TenantModelMixin, models.Model):
    """工单参与人员：负责人与参与人记录（业务角色，不等于系统权限）。

    - 用户必须是当前租户内有效账户（视图层校验）；
    - 同一工单同一人员唯一（负责人兼参与人时只保留一行 role=owner）；
    - 参与人不因此自动获得任何系统权限（权限与业务角色分别判断）。
    """

    work_order = models.ForeignKey(SystemWorkOrder, models.CASCADE, related_name='participants',
                                   help_text='所属工单')
    user = models.ForeignKey(User, models.PROTECT, related_name='+', help_text='参与人员')
    role = models.CharField(max_length=20, help_text='参与角色：owner 负责人 / participant 参与人')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_work_order_participant'
        verbose_name = '工单参与人员'
        verbose_name_plural = '工单参与人员'
        ordering = ('id',)
        constraints = [
            models.UniqueConstraint(fields=['work_order', 'user'],
                                    name='uniq_el_work_order_participant'),
            models.CheckConstraint(
                check=models.Q(role__in=WORK_ORDER_ROLE_VALUES),
                name='el_work_order_participant_role_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'work_order']),
        ]

    def __repr__(self):
        return '<SystemWorkOrderParticipant work_order=%s user=%s role=%s>' % (
            self.work_order_id, self.user_id, self.role)

    def to_view(self):
        return {
            'id': self.id,
            'user': self.user_id,
            'username': self.user.username if self.user_id else '',
            'nickname': self.user.nickname if self.user_id else '',
            'role': self.role,
            'role_text': '负责人' if self.role == WORK_ORDER_ROLE_OWNER else '参与人',
            'created_at': self.created_at,
        }


class SystemWorkOrderHandlingRecord(TenantModelMixin, models.Model):
    """工单处理过程记录：追加式时间线，不把过程反复覆盖在一个文本字段中。

    - 已保存记录不得被普通用户静默覆盖：更正时把原内容、新内容、更正原因
      追加保存到 corrections JSON 数组（与故障处置记录同一模式）；
    - 附件复用 EvidenceAttachment 体系
      （module=equipment_lifecycle, object_type=el_work_order_handling, object_id=记录ID）。
    """

    work_order = models.ForeignKey(SystemWorkOrder, models.CASCADE, related_name='handling_records',
                                   help_text='所属工单')
    handled_at = models.DateTimeField(help_text='处理时间')
    handler = models.ForeignKey(User, models.PROTECT, related_name='+', help_text='处理人')
    content = models.TextField(max_length=2000, help_text='处理内容')
    result = models.CharField(max_length=200, default='', blank=True, help_text='处理结果')
    work_hours = models.FloatField(null=True, blank=True, help_text='本次工时（小时）')
    corrections = models.TextField(default='', blank=True, help_text='更正历史 JSON 数组')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_work_order_handling_record'
        verbose_name = '工单处理记录'
        verbose_name_plural = '工单处理记录'
        ordering = ('handled_at', 'id')
        indexes = [
            models.Index(fields=['tenant_id', 'work_order', 'handled_at', 'id']),
        ]

    def __repr__(self):
        return '<SystemWorkOrderHandlingRecord work_order=%s at=%s>' % (
            self.work_order_id, self.handled_at)

    def get_corrections(self):
        if not self.corrections:
            return []
        try:
            data = json.loads(self.corrections)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    def to_view(self):
        return {
            'id': self.id,
            'work_order': self.work_order_id,
            'handled_at': self.handled_at,
            'handler': self.handler_id,
            'handler_name': self.handler.username if self.handler_id else '',
            'content': self.content,
            'result': self.result,
            'work_hours': self.work_hours,
            'corrections': self.get_corrections(),
            'created_at': self.created_at,
        }


class OperationLedgerCorrection(TenantModelMixin, models.Model):
    """复核后台账更正记录：保存更正原因与字段前后值（不静默修改）。"""

    ledger = models.ForeignKey(
        OperationLedger, models.PROTECT, related_name='corrections', help_text='所属台账')
    item = models.ForeignKey(
        OperationLedgerItem, models.PROTECT, related_name='corrections', null=True, blank=True,
        help_text='被更正的明细（表头级更正为空）')
    reason = models.CharField(max_length=500, help_text='更正原因（必填）')
    changes = models.TextField(default='', blank=True, help_text='字段前后值 JSON 数组 [{field,label,old,new}]')
    corrected_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    corrected_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_ledger_correction'
        verbose_name = '台账更正记录'
        verbose_name_plural = '台账更正记录'
        ordering = ('-corrected_at', '-id')
        indexes = [
            models.Index(fields=['tenant_id', 'ledger']),
        ]

    def __repr__(self):
        return '<OperationLedgerCorrection ledger=%s>' % self.ledger_id

    def get_corrections(self):
        if not self.changes:
            return []
        try:
            data = json.loads(self.changes)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

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
            'ledger': self.ledger_id,
            'item': self.item_id,
            'reason': self.reason,
            'changes': changes,
            'corrected_by': self.corrected_by_id,
            'corrected_by_name': self.corrected_by.username if self.corrected_by_id else '',
            'corrected_at': self.corrected_at,
        }


# 统一系统履历事件枚举（步骤 3.4；Meta 约束访问不到类作用域，提为模块级）
# 单系统简化：一条事件只关联一个系统，不再有跨系统角色（primary/affected/related 已删）
EVENT_TYPE_VALUES = ['fault', 'work_order', 'ledger', 'health', 'config_snapshot']
EVENT_SOURCE_TYPE_VALUES = ['fault', 'work_order', 'ledger_item', 'health', 'config_snapshot']
EVENT_ACTION_VALUES = [
    'create', 'recover', 'close', 'cancel',
    'convert_to_fault', 'convert_to_work_order',
    'complete', 'status_change', 'snapshot',
]


class SystemEvent(TenantModelMixin, models.Model):
    """统一系统履历事件（步骤 3.4，单系统简化）。

    - 由业务动作经 event_services.record_system_event 自动生成，与业务保存
      处于同一事务；普通用户不能手工新增，不提供普通修改与物理删除接口；
    - 故障、台账异常、工单、健康状态与配置快照共用同一事件模型，
      每条事件有明确主要来源（source_type + source_id）；
    - 一条事件只通过正式系统 ID 外键关联一个系统（PROTECT），保存系统
      编号/名称快照，系统改名后历史事件仍显示保存时的名称；
      不再建立跨系统事件角色（primary/affected/related 已随受影响系统
      结构一并移除），系统名称只用于事件快照，不替代正式外键；
    - 更正与受控撤销以追加新事件表达（如故障作废、工单取消），
      已生成事件原样保留；来源对象作废后事件与关联继续保留；
    - 事件纯插入，不递归触发健康状态重算；重复业务请求由业务层
      状态机与幂等键拦截，不产生重复事件。
    """

    EVENT_FAULT = 'fault'
    EVENT_WORK_ORDER = 'work_order'
    EVENT_LEDGER = 'ledger'
    EVENT_HEALTH = 'health'
    EVENT_CONFIG_SNAPSHOT = 'config_snapshot'
    EVENT_TYPE_CHOICES = (
        (EVENT_FAULT, '故障'),
        (EVENT_WORK_ORDER, '工单'),
        (EVENT_LEDGER, '台账异常'),
        (EVENT_HEALTH, '健康状态'),
        (EVENT_CONFIG_SNAPSHOT, '配置快照'),
    )
    EVENT_TYPE_TEXT_MAP = dict(EVENT_TYPE_CHOICES)

    system = models.ForeignKey(
        LifecycleSystem, models.PROTECT, related_name='system_events',
        help_text='关联系统（正式系统 ID，一条事件只关联一个系统）')
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES, help_text='事件类型')
    action = models.CharField(max_length=30, help_text='事件动作')
    source_type = models.CharField(max_length=20, help_text='主要来源类型')
    source_id = models.CharField(
        max_length=32, default='', blank=True, help_text='来源对象ID（健康状态事件为空）')
    source_no = models.CharField(
        max_length=50, default='', blank=True, help_text='来源编号快照（故障号/工单号/台账号/快照名）')
    title = models.CharField(max_length=200, help_text='事件摘要（保存时点快照）')
    detail = models.TextField(default='', blank=True, help_text='受控结构化详情 JSON')
    system_code = models.CharField(max_length=50, help_text='系统编号快照')
    system_name = models.CharField(max_length=100, help_text='系统名称快照')
    occurred_at = models.DateTimeField(help_text='业务事实时间')
    created_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True,
        help_text='触发业务动作的用户（服务内部触发可为空）')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_system_event'
        verbose_name = '系统履历事件'
        verbose_name_plural = '系统履历事件'
        ordering = ('-occurred_at', '-id')
        constraints = [
            models.CheckConstraint(
                check=models.Q(event_type__in=EVENT_TYPE_VALUES),
                name='el_system_event_type_valid',
            ),
            models.CheckConstraint(
                check=models.Q(source_type__in=EVENT_SOURCE_TYPE_VALUES),
                name='el_system_event_source_type_valid',
            ),
            models.CheckConstraint(
                check=models.Q(action__in=EVENT_ACTION_VALUES),
                name='el_system_event_action_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'system', '-occurred_at', '-id']),
            models.Index(fields=['tenant_id', 'event_type']),
            models.Index(fields=['tenant_id', 'source_type', 'source_id']),
        ]

    def __repr__(self):
        return '<SystemEvent %s %s>' % (self.event_type, self.title[:30])

    def get_detail(self):
        if not self.detail:
            return {}
        try:
            data = json.loads(self.detail)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    def to_view(self):
        return {
            'id': self.id,
            'system': self.system_id,
            'system_code': self.system_code,
            'system_name': self.system_name,
            'event_type': self.event_type,
            'event_type_text': self.EVENT_TYPE_TEXT_MAP.get(self.event_type, self.event_type),
            'action': self.action,
            'source_type': self.source_type,
            'source_id': self.source_id,
            'source_no': self.source_no,
            'title': self.title,
            'detail': self.get_detail(),
            'occurred_at': self.occurred_at,
            'created_by_name': self.created_by.username if self.created_by_id else '',
            'created_at': self.created_at,
        }

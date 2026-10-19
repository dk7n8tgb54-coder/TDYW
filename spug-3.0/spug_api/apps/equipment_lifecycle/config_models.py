# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——系统配置参数与配置变更模型（2026-10）。

产品定位（2026-10-19 起）：配置的写操作集中在「设备管理 → 系统配置」独立
维护入口（选择系统、初始建档、维护参数定义、处理配置变更）；「系统详情 →
配置」页签改为只读展示（当前配置 + 建档信息 + 变更历史），可跳转维护入口。
本组模型与已删除的旧"配置三表/自定义字段"路线（0021/0023）无关：
- ConfigParamDefinition    配置参数定义（编码/名称/分类/适用范围/类型/单位/必填/枚举/校验/启用）
- ConfigParamSystemScope   参数适用系统范围（scope_type=specific 时的显式系统清单）
- SystemParamValue         系统当前配置值（类型化字段，同系统同参数唯一生效值）
- SystemConfigBaseline     系统初始配置建档（基线：建档人/时间/来源，每系统至多一份）
- SystemConfigBaselineItem 初始建档明细（参数快照 + 基线值快照）
- ConfigChangeRecord       配置变更主表（草稿/已生效/已验证/已回退/已取消）
- ConfigChangeItem         配置变更明细（参数快照 + 变更前后值快照）

参数分类（2026-10-19）：hardware_spec=硬件规格（能明确描述整套系统的规格，
如系统额定功率、容量；仅属于某台设备的规格不得登记为系统规格）；
runtime_param=运行参数（可调整的设定值，如设定功率、工作模式）。
实测值不属于配置，仍记录在运行处置记录中。

初始建档原则：建档是独立于配置变更的明确身份（建档人/建档时间/来源），
不是一条伪装的普通变更；建档后参数修改一律走配置变更流程。只有"干净"
系统（无建档、无当前配置值、无已生效变更）允许建档——已有配置数据的
老系统保留原有记录，不补建、不凭空推断历史基线。

历史快照原则：明细保存参数编码/名称/类型/单位与变更前后值的规范化文本
快照，参数定义后续修改/停用不改变历史含义；参数定义不提供删除接口
（只有启用/停用），停用后当前值与历史记录全部保留。
配置值只经「初始建档」或「配置变更」（创建草稿 → 应用生效）流程写入，
不提供散改接口。
（系统履历已于 2026-10-11 整体退役：配置变更不再写履历事件，变更历史与
审计留痕承载追溯需求。）
"""
import json

from django.db import models

from apps.account.models import User
from libs.tenant_base_model import TenantModelManager, TenantModelMixin, make_tenant_id

from apps.equipment_lifecycle.models import LifecycleSystem

# 参数适用范围：all=全部系统通用参数；specific=显式关联的系统清单（不新建系统分类体系）
PARAM_SCOPE_ALL = 'all'
PARAM_SCOPE_SPECIFIC = 'specific'
PARAM_SCOPE_VALUES = [PARAM_SCOPE_ALL, PARAM_SCOPE_SPECIFIC]
PARAM_SCOPE_CHOICES = (
    (PARAM_SCOPE_ALL, '全部系统'),
    (PARAM_SCOPE_SPECIFIC, '指定系统'),
)

# 参数数据类型（枚举类型校验依赖 enum_options，见 config_services）
PARAM_TYPE_TEXT = 'text'
PARAM_TYPE_NUMBER = 'number'
PARAM_TYPE_BOOL = 'bool'
PARAM_TYPE_DATE = 'date'
PARAM_TYPE_CHOICE = 'choice'
PARAM_TYPE_VALUES = [PARAM_TYPE_TEXT, PARAM_TYPE_NUMBER, PARAM_TYPE_BOOL,
                     PARAM_TYPE_DATE, PARAM_TYPE_CHOICE]
PARAM_TYPE_CHOICES = (
    (PARAM_TYPE_TEXT, '文本'),
    (PARAM_TYPE_NUMBER, '数字'),
    (PARAM_TYPE_BOOL, '布尔'),
    (PARAM_TYPE_DATE, '日期'),
    (PARAM_TYPE_CHOICE, '枚举'),
)
PARAM_TYPE_TEXT_MAP = dict(PARAM_TYPE_CHOICES)

# 参数分类（2026-10-19）：硬件规格=整套系统的静态规格（额定功率/容量等，
# 引用系统档案视角，不得登记单台设备规格）；运行参数=可调整的设定值
# （设定功率/工作模式等）。存量参数默认归入运行参数，不凭空推断历史分类。
PARAM_CATEGORY_HARDWARE = 'hardware_spec'
PARAM_CATEGORY_RUNTIME = 'runtime_param'
PARAM_CATEGORY_VALUES = [PARAM_CATEGORY_HARDWARE, PARAM_CATEGORY_RUNTIME]
PARAM_CATEGORY_CHOICES = (
    (PARAM_CATEGORY_HARDWARE, '硬件规格'),
    (PARAM_CATEGORY_RUNTIME, '运行参数'),
)
PARAM_CATEGORY_TEXT_MAP = dict(PARAM_CATEGORY_CHOICES)

# 配置变更状态：draft(草稿) → applied(已生效) → verified(已验证)；
# applied/verified → rolled_back(已回退，生成一条新的反向变更)；
# draft → cancelled(已取消)。终态不可再变更（已生效内容不可被普通编辑覆盖）。
CONFIG_CHANGE_DRAFT = 'draft'
CONFIG_CHANGE_APPLIED = 'applied'
CONFIG_CHANGE_VERIFIED = 'verified'
CONFIG_CHANGE_ROLLED_BACK = 'rolled_back'
CONFIG_CHANGE_CANCELLED = 'cancelled'
CONFIG_CHANGE_STATUS_VALUES = [
    CONFIG_CHANGE_DRAFT, CONFIG_CHANGE_APPLIED, CONFIG_CHANGE_VERIFIED,
    CONFIG_CHANGE_ROLLED_BACK, CONFIG_CHANGE_CANCELLED,
]
CONFIG_CHANGE_STATUS_CHOICES = (
    (CONFIG_CHANGE_DRAFT, '草稿'),
    (CONFIG_CHANGE_APPLIED, '已生效'),
    (CONFIG_CHANGE_VERIFIED, '已验证'),
    (CONFIG_CHANGE_ROLLED_BACK, '已回退'),
    (CONFIG_CHANGE_CANCELLED, '已取消'),
)
CONFIG_CHANGE_STATUS_TEXT_MAP = dict(CONFIG_CHANGE_STATUS_CHOICES)

# 验证状态：空串=未验证；passed=验证通过（主状态转为 verified）；failed=验证不通过
CONFIG_VERIFY_PASSED = 'passed'
CONFIG_VERIFY_FAILED = 'failed'
CONFIG_VERIFY_STATUS_DB_VALUES = ['', CONFIG_VERIFY_PASSED, CONFIG_VERIFY_FAILED]

# 变更编号前缀：PZ{yyyymmdd}-{seq:04d}，当日序号全租户共享（口径同故障/运行记录）
CONFIG_CHANGE_NO_PREFIX = 'PZ'
CONFIG_CHANGE_NO_SEQ_LIMIT = 9999


class ConfigParamDefinition(TenantModelMixin, models.Model):
    """配置参数定义：不同系统可拥有不同配置参数，不为参数硬编码数据库列。

    - 适用范围 scope_type：all 通用参数对全部系统生效；specific 通过
      ConfigParamSystemScope 显式关联系统清单（复用系统主数据本身做范围，
      不新建第二套系统分类体系）；
    - 枚举类型必须提供选项清单（JSON 数组，存中文选项文本）；
    - validation_regex 仅对文本类型生效（可选）；number/bool/date 的格式
      校验由类型本身决定，不开放自由正则；
    - 参数不提供物理删除：停用（is_enabled=False）后当前值与历史变更记录
      全部保留，历史含义由明细快照保证。
    """

    param_code = models.CharField(max_length=100, help_text='参数编码（小写字母开头的字母/数字/下划线，租户内唯一，创建后不可修改）')
    param_name = models.CharField(max_length=100, help_text='参数名称')
    category = models.CharField(
        max_length=20, choices=PARAM_CATEGORY_CHOICES, default=PARAM_CATEGORY_RUNTIME,
        help_text='参数分类：hardware_spec 硬件规格（系统级规格，如额定功率/容量）/'
                  'runtime_param 运行参数（可调整设定值，如设定功率/工作模式）')
    scope_type = models.CharField(
        max_length=20, choices=PARAM_SCOPE_CHOICES, default=PARAM_SCOPE_ALL,
        help_text='适用范围：all 全部系统 / specific 指定系统清单')
    data_type = models.CharField(
        max_length=20, choices=PARAM_TYPE_CHOICES, default=PARAM_TYPE_TEXT,
        help_text='数据类型：text/number/bool/date/choice')
    unit = models.CharField(max_length=20, default='', blank=True, help_text='单位（选填，如 dB、MHz、%）')
    is_required = models.BooleanField(default=False, help_text='是否必填（应用变更时该参数不允许提交空值）')
    enum_options = models.TextField(default='', blank=True, help_text='枚举选项清单 JSON 数组（仅 choice 类型使用，如 ["主用","备用"]）')
    validation_regex = models.CharField(max_length=200, default='', blank=True, help_text='文本类型可选校验正则（仅 text 类型生效）')
    is_enabled = models.BooleanField(default=True, help_text='是否启用（停用后不再出现在当前配置与变更参数候选中，历史保留）')
    remark = models.CharField(max_length=200, default='', blank=True, help_text='备注（选填）')
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_config_params'
        verbose_name = '配置参数定义'
        verbose_name_plural = '配置参数定义'
        ordering = ('param_code',)
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'param_code'], name='uniq_el_config_params_tenant_code'),
            models.CheckConstraint(
                check=models.Q(scope_type__in=PARAM_SCOPE_VALUES),
                name='el_config_params_scope_valid',
            ),
            models.CheckConstraint(
                check=models.Q(data_type__in=PARAM_TYPE_VALUES),
                name='el_config_params_type_valid',
            ),
            models.CheckConstraint(
                check=models.Q(category__in=PARAM_CATEGORY_VALUES),
                name='el_config_params_category_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'is_enabled', 'param_code']),
        ]

    def __repr__(self):
        return '<ConfigParamDefinition %r>' % self.param_code

    def get_options(self):
        """解析枚举选项清单（空/非法时返回空列表）。"""
        if not self.enum_options:
            return []
        try:
            data = json.loads(self.enum_options)
        except (ValueError, TypeError):
            return []
        if not isinstance(data, list):
            return []
        return [str(x) for x in data if str(x).strip()]

    def applies_to_system(self, system_id):
        """参数是否适用于指定系统（定义层判定；查询侧见 config_services）。"""
        if self.scope_type == PARAM_SCOPE_ALL:
            return True
        return self.system_scopes.filter(system_id=system_id).exists()

    def to_view(self):
        return {
            'id': self.id,
            'param_code': self.param_code,
            'param_name': self.param_name,
            'category': self.category,
            'category_text': PARAM_CATEGORY_TEXT_MAP.get(self.category, self.category),
            'scope_type': self.scope_type,
            'scope_type_text': dict(PARAM_SCOPE_CHOICES).get(self.scope_type, self.scope_type),
            'system_ids': list(self.system_scopes.values_list('system_id', flat=True)),
            'data_type': self.data_type,
            'data_type_text': PARAM_TYPE_TEXT_MAP.get(self.data_type, self.data_type),
            'unit': self.unit,
            'is_required': self.is_required,
            'options': self.get_options(),
            'validation_regex': self.validation_regex,
            'is_enabled': self.is_enabled,
            'remark': self.remark,
            'created_by_name': self.created_by.username if self.created_by_id else '',
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


class ConfigParamSystemScope(TenantModelMixin, models.Model):
    """参数适用系统清单（scope_type=specific 时生效）。"""

    param = models.ForeignKey(
        ConfigParamDefinition, models.CASCADE, related_name='system_scopes',
        help_text='所属参数定义')
    system = models.ForeignKey(
        LifecycleSystem, models.PROTECT, related_name='config_param_scopes',
        help_text='适用系统')

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_config_param_systems'
        verbose_name = '参数适用系统'
        verbose_name_plural = '参数适用系统'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'param', 'system'],
                name='uniq_el_config_param_systems'),
        ]


class SystemParamValue(TenantModelMixin, models.Model):
    """系统当前配置值：同一系统同一参数只有一条当前生效值（租户内唯一约束）。

    - 不同数据类型使用类型化字段（value_text/value_number/value_bool/
      value_date/value_choice），规范文本（展示与快照对比口径）由服务层
      canonical_value_text 统一派生；
    - 只经配置变更流程写入（应用变更 upsert），参数停用后行保留不删除；
    - 模型名 SystemParamValue 与已删除的旧自定义字段值表 SystemConfigValue
      （迁移 0023）刻意区分，避免同名歧义；
    - effective_at/last_change/last_changed_by 记录当前值的生效来源。
    """

    system = models.ForeignKey(
        LifecycleSystem, models.PROTECT, related_name='config_values',
        help_text='所属系统')
    param = models.ForeignKey(
        ConfigParamDefinition, models.PROTECT, related_name='current_values',
        help_text='参数定义（停用不删除，PROTECT）')
    value_text = models.CharField(max_length=500, default='', blank=True, help_text='文本值（text 类型）')
    value_number = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True, help_text='数字值（number 类型）')
    value_bool = models.BooleanField(null=True, blank=True, help_text='布尔值（bool 类型）')
    value_date = models.DateField(null=True, blank=True, help_text='日期值（date 类型）')
    value_choice = models.CharField(max_length=200, default='', blank=True, help_text='枚举值（choice 类型，必须是参数选项之一）')
    effective_at = models.DateTimeField(help_text='当前值生效时间（应用变更时间或建档时间）')
    last_change = models.ForeignKey(
        'ConfigChangeRecord', models.PROTECT, related_name='applied_config_values',
        null=True, blank=True,
        help_text='最后变更记录（应用该值的配置变更；初始建档写入的值为空）')
    baseline = models.ForeignKey(
        'SystemConfigBaseline', models.PROTECT, related_name='baseline_config_values',
        null=True, blank=True,
        help_text='初始建档来源（建档建立该值时填写；后续配置变更不改写本标记）')
    last_changed_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True,
        help_text='最后变更操作账号')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_system_param_values'
        verbose_name = '系统参数当前值'
        verbose_name_plural = '系统参数当前值'
        ordering = ('param__param_code',)
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'system', 'param'],
                name='uniq_el_config_values_system_param'),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'system']),
        ]

    def __repr__(self):
        return '<SystemParamValue system=%s param=%s>' % (self.system_id, self.param_id)

    def to_view(self):
        return {
            'id': self.id,
            'system': self.system_id,
            'param': self.param_id,
            'param_code': self.param.param_code,
            'param_name': self.param.param_name,
            'data_type': self.param.data_type,
            'data_type_text': PARAM_TYPE_TEXT_MAP.get(self.param.data_type, self.param.data_type),
            'unit': self.param.unit,
            'value_text': self.value_text,
            'value_number': self.value_number,
            'value_bool': self.value_bool,
            'value_date': self.value_date,
            'value_choice': self.value_choice,
            'effective_at': self.effective_at,
            'last_change': self.last_change_id,
            'last_changed_by_name': self.last_changed_by.username if self.last_changed_by_id else '',
        }


class ConfigChangeRecord(TenantModelMixin, models.Model):
    """配置变更主表：一条变更可包含多个参数（明细见 ConfigChangeItem）。

    - 状态机：draft → applied → verified；applied/verified → rolled_back
      （回退生成一条新的反向变更，原记录内容不改写只改状态）；
      draft → cancelled；终态不可再操作；
    - 已生效（applied 及之后）变更不允许普通编辑（PUT 仅 draft 放行）；
    - rollback_of 指向被回退的原变更（"回退记录关联"双向可查）。
    """

    change_no = models.CharField(max_length=50, help_text='变更编号（PZ+创建日期+当日四位序号，自动生成；当日序号全租户共享）')
    system = models.ForeignKey(
        LifecycleSystem, models.PROTECT, related_name='config_changes',
        help_text='所属系统')
    system_code = models.CharField(max_length=50, help_text='系统编号快照')
    system_name = models.CharField(max_length=100, help_text='系统名称快照')
    reason = models.TextField(max_length=500, help_text='变更原因')
    status = models.CharField(
        max_length=20, choices=CONFIG_CHANGE_STATUS_CHOICES, default=CONFIG_CHANGE_DRAFT,
        help_text='变更状态')
    applied_at = models.DateTimeField(null=True, blank=True, help_text='生效时间')
    applied_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True,
        help_text='应用生效操作账号')
    verify_status = models.CharField(
        max_length=20, default='', blank=True,
        help_text='验证状态：空串未验证/passed 通过/failed 不通过')
    verify_note = models.CharField(max_length=500, default='', blank=True, help_text='验证说明（创建时可填预期；验证时写入结论）')
    verified_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True,
        help_text='验证操作账号')
    verified_at = models.DateTimeField(null=True, blank=True, help_text='验证时间')
    rollback_of = models.ForeignKey(
        'self', models.PROTECT, related_name='rollback_changes', null=True, blank=True,
        help_text='被回退的原变更（回退生成的反向变更填写）')
    cancelled_at = models.DateTimeField(null=True, blank=True, help_text='取消时间')
    cancelled_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True,
        help_text='取消操作账号')
    client_token = models.CharField(max_length=64, default='', blank=True, help_text='客户端幂等令牌（创建防重复）')
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+', help_text='操作人（变更登记人）')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_config_changes'
        verbose_name = '配置变更'
        verbose_name_plural = '配置变更'
        ordering = ('-created_at', '-id')
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'change_no'], name='uniq_el_config_changes_tenant_no'),
            models.CheckConstraint(
                check=models.Q(status__in=CONFIG_CHANGE_STATUS_VALUES),
                name='el_config_changes_status_valid',
            ),
            models.CheckConstraint(
                check=models.Q(verify_status__in=CONFIG_VERIFY_STATUS_DB_VALUES),
                name='el_config_changes_verify_status_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'system', '-created_at', '-id']),
            models.Index(fields=['tenant_id', 'status']),
            models.Index(fields=['tenant_id', 'client_token']),
        ]

    def __repr__(self):
        return '<ConfigChangeRecord %r>' % self.change_no

    def to_view(self):
        return {
            'id': self.id,
            'change_no': self.change_no,
            'system': self.system_id,
            'system_code': self.system_code,
            'system_name': self.system_name,
            'reason': self.reason,
            'status': self.status,
            'status_text': CONFIG_CHANGE_STATUS_TEXT_MAP.get(self.status, self.status),
            'applied_at': self.applied_at,
            'verify_status': self.verify_status,
            'verify_status_text': {'passed': '验证通过', 'failed': '验证不通过'}.get(self.verify_status, '未验证'),
            'verify_note': self.verify_note,
            'verified_at': self.verified_at,
            'verified_by_name': self.verified_by.username if self.verified_by_id else '',
            'rollback_of': self.rollback_of_id,
            'rollback_of_no': self.rollback_of.change_no if self.rollback_of_id else '',
            'created_by_name': self.created_by.username if self.created_by_id else '',
            'created_at': self.created_at,
        }

    def to_detail_view(self):
        data = self.to_view()
        data.update({
            'applied_by_name': self.applied_by.username if self.applied_by_id else '',
            'cancelled_at': self.cancelled_at,
            'cancelled_by_name': self.cancelled_by.username if self.cancelled_by_id else '',
            'client_token': self.client_token,
            'updated_at': self.updated_at,
        })
        return data


class ConfigChangeItem(TenantModelMixin, models.Model):
    """配置变更明细：参数定义快照 + 变更前后值快照。

    - 前后值保存规范化文本快照（canonical text）：bool 存 true/false、
      date 存 YYYY-MM-DD、number 存去尾零数字串、choice 存选项文本——
      参数定义后续修改/停用不改变历史含义；
    - old_value 在创建/编辑变更时由后端从数据库当前值重新生成（不信任
      前端传入），应用变更时与数据库当前值再次比对防并发覆盖；
    - verify_status 单项验证结果由验证动作统一回填（与主表验证结论一致）。
    """

    change = models.ForeignKey(
        ConfigChangeRecord, models.CASCADE, related_name='items',
        help_text='所属配置变更')
    param = models.ForeignKey(
        ConfigParamDefinition, models.PROTECT, related_name='change_items',
        help_text='参数定义（快照外键，定义修改不影响历史展示）')
    param_code = models.CharField(max_length=100, help_text='参数编码快照')
    param_name = models.CharField(max_length=100, help_text='参数名称快照')
    param_data_type = models.CharField(max_length=20, help_text='参数类型快照')
    unit = models.CharField(max_length=20, default='', blank=True, help_text='单位快照')
    old_value = models.CharField(max_length=500, default='', blank=True, help_text='变更前值规范化文本快照（空串=此前未设置）')
    new_value = models.CharField(max_length=500, help_text='变更后值规范化文本快照')
    verify_status = models.CharField(max_length=20, default='', blank=True, help_text='单项验证结果（验证动作回填：passed/failed）')
    remark = models.CharField(max_length=200, default='', blank=True, help_text='备注（选填）')

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_config_change_items'
        verbose_name = '配置变更明细'
        verbose_name_plural = '配置变更明细'
        ordering = ('id',)
        constraints = [
            models.CheckConstraint(
                check=models.Q(param_data_type__in=PARAM_TYPE_VALUES),
                name='el_config_change_items_type_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'param']),
        ]

    def __repr__(self):
        return '<ConfigChangeItem %s %s>' % (self.change_id, self.param_code)

    def to_view(self):
        return {
            'id': self.id,
            'param': self.param_id,
            'param_code': self.param_code,
            'param_name': self.param_name,
            'data_type': self.param_data_type,
            'data_type_text': PARAM_TYPE_TEXT_MAP.get(self.param_data_type, self.param_data_type),
            'unit': self.unit,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'verify_status': self.verify_status,
            'verify_status_text': {'passed': '验证通过', 'failed': '验证不通过'}.get(self.verify_status, ''),
            'remark': self.remark,
        }


class SystemConfigBaseline(TenantModelMixin, models.Model):
    """系统初始配置建档（基线）：每系统至多一份，独立于配置变更的明确身份。

    - 记录基线值（明细见 SystemConfigBaselineItem）、建档人、建档时间与
      来源（source，如验收文档/出厂技术资料/人工核定）；
    - 建档后参数修改一律走配置变更流程；建档写入的当前值 last_change 为空、
      baseline 指向本行，当前值展示据此区分"初始建档"与"配置变更"；
    - 只有"干净"系统允许建档（无建档、无当前配置值、无非草稿配置变更），
      校验在 config_baseline_services；已有配置数据的老系统保留原记录，
      不补建、不凭空推断历史基线；
    - 建档不提供删除/修改接口（基线是档案性记录）。
    """

    system = models.ForeignKey(
        LifecycleSystem, models.PROTECT, related_name='config_baseline',
        help_text='所属系统（每系统至多一份建档，租户内唯一）')
    system_code = models.CharField(max_length=50, help_text='系统编号快照')
    system_name = models.CharField(max_length=100, help_text='系统名称快照')
    source = models.CharField(max_length=200, help_text='建档来源（如验收文档、出厂技术资料、人工核定）')
    remark = models.CharField(max_length=200, default='', blank=True, help_text='备注（选填）')
    established_at = models.DateTimeField(help_text='建档时间')
    established_by = models.ForeignKey(User, models.PROTECT, related_name='+', help_text='建档人')

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_config_baselines'
        verbose_name = '系统初始配置建档'
        verbose_name_plural = '系统初始配置建档'
        ordering = ('-established_at', '-id')
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'system'], name='uniq_el_config_baselines_system'),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'system']),
        ]

    def __repr__(self):
        return '<SystemConfigBaseline system=%s>' % self.system_id

    def to_view(self):
        return {
            'id': self.id,
            'system': self.system_id,
            'system_code': self.system_code,
            'system_name': self.system_name,
            'source': self.source,
            'remark': self.remark,
            'established_at': self.established_at,
            'established_by_name': self.established_by.username if self.established_by_id else '',
        }


class SystemConfigBaselineItem(TenantModelMixin, models.Model):
    """初始建档明细：参数定义快照 + 基线值（类型化字段）。

    - 快照原则与 ConfigChangeItem 一致：参数定义后续修改/停用不改变建档
      的历史含义；展示值由 canonical_value_text 按类型派生；
    - 建档值不允许为空（空值参数不纳入建档，保持"未设置"）。
    """

    baseline = models.ForeignKey(
        SystemConfigBaseline, models.CASCADE, related_name='items',
        help_text='所属建档')
    param = models.ForeignKey(
        ConfigParamDefinition, models.PROTECT, related_name='baseline_items',
        help_text='参数定义（快照外键）')
    param_code = models.CharField(max_length=100, help_text='参数编码快照')
    param_name = models.CharField(max_length=100, help_text='参数名称快照')
    param_data_type = models.CharField(max_length=20, help_text='参数类型快照')
    unit = models.CharField(max_length=20, default='', blank=True, help_text='单位快照')
    value_text = models.CharField(max_length=500, default='', blank=True, help_text='文本基线值（text 类型）')
    value_number = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True, help_text='数字基线值（number 类型）')
    value_bool = models.BooleanField(null=True, blank=True, help_text='布尔基线值（bool 类型）')
    value_date = models.DateField(null=True, blank=True, help_text='日期基线值（date 类型）')
    value_choice = models.CharField(max_length=200, default='', blank=True, help_text='枚举基线值（choice 类型）')

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_config_baseline_items'
        verbose_name = '初始建档明细'
        verbose_name_plural = '初始建档明细'
        ordering = ('id',)
        constraints = [
            models.CheckConstraint(
                check=models.Q(param_data_type__in=PARAM_TYPE_VALUES),
                name='el_config_baseline_items_type_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'param']),
        ]

    def __repr__(self):
        return '<SystemConfigBaselineItem baseline=%s %s>' % (self.baseline_id, self.param_code)

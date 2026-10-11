# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——系统主数据模型（步骤二）与维护台账/巡检历史模型。

2026-10-11 合并改造：原"故障处置"与"运行记录"合并为"运行与故障记录"
（SystemOperationRecord/SystemOperationProgress，见 operation_models.py），
"系统履历"（SystemEvent）整体下线；本文件不再包含这五个旧模型。

按《设备与系统全生命周期管理总体方案 v2.0》步骤二建设：

- LifecycleSystem          系统主数据（平级、无父子层级、无系统—设备关系）

已下线功能（2026-09 功能下线，迁移 0021/0023 删除）：
- SystemConfigComponent（配置组成项）、SystemConfigChange（配置变更历史）、
  SystemConfigSnapshot（配置快照）三表及故障上的组成项外键已删除；
  故障历史组成项名称以 fault_component_name 文本快照保留，
  config_snapshot 类型履历事件仅存量兼容、不再新增；
- ConfigFieldDefinition（自定义配置字段定义）、SystemConfigValue（配置值）
  两表已删除（迁移 0023），扩展信息由固定字段承载
  （callsign 呼号 / geo_coordinate 安装经纬度 / work_frequency 工作频率，
  均选填），迁移时已将同名自定义字段的历史文本值回填到新列。

约束：
- 全部继承 TenantModelMixin，租户隔离；
- CharField/TextField 一律禁止 null=True；
- 新表均不复用步骤一删除的旧表名（tdyw_el_system 等）。
"""
import json

from django.db import models

from apps.account.models import User
from libs.tenant_base_model import TenantModelManager, TenantModelMixin, make_tenant_id

# Meta/CheckConstraint 内无法访问类体常量（类作用域不形成闭包），枚举值提为模块级
# repairing（维修中）已随"故障维修工单"功能整体删除（2026-09-30）：维修过程统一由
# 运行与故障记录承载，健康状态只由有效正式故障的影响程度驱动（operation_services）。
# 2026-10-11 合并改造：SystemFault/SystemFaultHandlingRecord/SystemRuntimeRecord/
# SystemRuntimeRecordProgress/SystemEvent 五个模型已整体退役（迁移 0013 删表），
# 统一主表/进展表见 operation_models.py（运行与故障记录），系统履历功能整体下线。
HEALTH_STATUS_VALUES = ['normal', 'degraded', 'fault', 'interrupted', 'unknown']


class LifecycleSystem(TenantModelMixin, models.Model):
    """系统主数据：一个对象代表某地点实际运行的一套系统实例。

    - 所有系统平级，不设父系统/子系统/树形层级（无 parent 字段，测试固化）；
    - system_code 为后端内部标识：新增时自动生成（SYS-日期-随机），租户内唯一，
      创建后不可修改，不向前端展示；
    - is_active 只控制系统能否继续被业务选择，不表达运行状态；
    - health_status 为运行健康状态，只由 fault_services 依据有效故障统一计算写入。
    """

    HEALTH_NORMAL = 'normal'
    HEALTH_DEGRADED = 'degraded'
    HEALTH_FAULT = 'fault'
    HEALTH_INTERRUPTED = 'interrupted'
    HEALTH_UNKNOWN = 'unknown'
    HEALTH_STATUS_CHOICES = (
        (HEALTH_NORMAL, '正常'),
        (HEALTH_DEGRADED, '降级'),
        (HEALTH_FAULT, '故障'),
        (HEALTH_INTERRUPTED, '中断'),
        (HEALTH_UNKNOWN, '未知'),
    )
    HEALTH_STATUS_TEXT_MAP = dict(HEALTH_STATUS_CHOICES)

    system_code = models.CharField(max_length=50, help_text='系统编号，租户内唯一，创建后不可修改')
    name = models.CharField(max_length=100, help_text='系统正式名称')
    system_model = models.CharField(max_length=100, help_text='系统型号')
    install_location = models.CharField(max_length=200, help_text='安装地点')
    geo_coordinate = models.CharField(max_length=100, default='', blank=True, help_text='安装经纬度，格式: 经度,纬度')
    callsign = models.CharField(max_length=50, default='', blank=True, help_text='呼号，选填')
    work_frequency = models.CharField(max_length=100, default='', blank=True, help_text='工作频率，选填，如 438.500MHz 或频段范围')
    system_purpose = models.TextField(max_length=500, default='', blank=True, help_text='系统用途')
    manufacturer = models.CharField(max_length=100, help_text='生产厂家')
    install_unit = models.CharField(max_length=100, help_text='安装单位')
    use_unit = models.CharField(max_length=100, help_text='使用单位')
    install_time = models.DateField(null=True, blank=True, help_text='安装时间（仅档案信息，只需日期）')
    enable_time = models.DateField(null=True, blank=True, help_text='启用时间（仅档案信息，只需日期）')
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
            'callsign': self.callsign,
            'work_frequency': self.work_frequency,
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


# ======================================================================
# 步骤 3.2：周月维护 / 季维护台账
# ----------------------------------------------------------------------
# 结构：系统 → 检查项或维护项 → 台账明细 → 台账汇总表。
# 两类维护台账共用统一模型（OperationLedger/OperationLedgerItem），
# 通过 ledger_type 区分，不为两类台账复制两套表。
# 周月维护不再拆分周表/月表（2026-09-26）：维护周期与项目执行范围已删除，
# 一张周月维护台账即一次完整维护记录。
# 旧巡检台账（ledger_type=inspection）业务分支已删除（2026-09-24）：
# 巡检由独立模型（InspectionTemplate/InspectionDutySheet/InspectionRecord）承担，
# 历史数据由 purge_legacy_inspection_ledgers 管理命令受控清理。
# 本步骤只记录异常，不转故障、不修改系统健康状态（异常处置见 fault_views），
# 不建设计划提醒、系统履历与现场采集能力。
# ======================================================================

# 台账类型（旧巡检类型 inspection 已删除，仅保留常量供显式拒绝与历史数据清理识别）
LEGACY_LEDGER_TYPE_INSPECTION = 'inspection'  # 旧巡检（已下线，不再支持）
LEDGER_TYPE_WEEK_MONTH = 'week_month'    # 周月维护（周表/月表合一）
LEDGER_TYPE_SEASONAL = 'seasonal'        # 季维护（正式名称，不用"季度维护"）
LEDGER_TYPE_VALUES = ['week_month', 'seasonal']

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
# 未填写：矩阵台账单元格生成后的初始态（空串），不参与结果统计；
# 未填写不能被自动转换为正常（一键正常仅显式作用于未填写单元格）
ITEM_RESULT_UNSET = ''
# DB CHECK 约束值域 = 四种显式结果 + 未填写（空串）
ITEM_RESULT_DB_VALUES = [ITEM_RESULT_UNSET] + ITEM_RESULT_VALUES
ITEM_RESULT_TEXT_MAP_FULL = {
    ITEM_RESULT_UNSET: '未填写',
    ITEM_RESULT_NORMAL: '正常',
    ITEM_RESULT_ABNORMAL: '异常',
    ITEM_RESULT_NOT_APPLICABLE: '不适用',
    ITEM_RESULT_PENDING_REVIEW: '待复核',
}

# 台账明细录入类型（模板项目与明细快照共用）
LEDGER_INPUT_TYPE_VALUES = ['text', 'number', 'choice', 'multi_choice', 'boolean', 'attachment']

# ======================================================================
# 行对象树（旧可视化模板路线）已于 2026-10 整体删除：正式维护台账统一
# 使用 Excel/WPS 模板路线（OperationLedgerExcelTemplate 体系），手工补录
# 台账保留 entries 明细能力。ROW_NODE_* / LEDGER_ROW_MAX_LEVEL /
# ROW_PATH_SEPARATOR / OperationLedgerRowTemplateNode /
# OperationLedgerRowInstance 及模板两表一并移除（数据清理与删表见
# 迁移 0045）。
# ======================================================================

# 台账创建来源（旧可视化模板来源 template 已随路线删除，迁移 0045 收窄约束）
LEDGER_FROM_MANUAL = 'manual'
# Excel 上传版模板（固定版式 .xlsx，2026-09-28 试点）：台账明细为模板版本
# 填写值（OperationLedgerExcelRecord），无 OperationLedgerItem
LEDGER_FROM_EXCEL = 'excel_template'
LEDGER_FROM_VALUES = ['manual', 'excel_template']

# 录入渠道：当前固定 web（平台电脑端事后录入），保留字段作未来扩展边界
ENTRY_CHANNEL_WEB = 'web'
ENTRY_CHANNEL_VALUES = ['web']

# 台账类型 → 编号前缀（旧巡检前缀 EL-INS 随类型一并下线）
LEDGER_NO_PREFIX_MAP = {
    LEDGER_TYPE_WEEK_MONTH: 'EL-WM',
    LEDGER_TYPE_SEASONAL: 'EL-SE',
}

# 展示文本映射（旧巡检文本已随类型删除；历史履历/审计中的巡检文本为快照）
LEDGER_TYPE_TEXT = {
    LEDGER_TYPE_WEEK_MONTH: '周月维护',
    LEDGER_TYPE_SEASONAL: '季维护',
}


class OperationLedger(TenantModelMixin, models.Model):
    """运维台账表头：周月维护/季维护共用，一张台账可汇总多个系统的明细。

    - 系统不是整张台账的边界，而是每条明细（OperationLedgerItem）的归属；
      例外：周期批量新增的台账（2026-10-11）为"一系统一台账"草稿壳，
      表头 system/maintenance_period 标记归属，明细由用户后续补录；
    - 实际执行时间（executed_date/executed_start/executed_end）与平台录入
      时间（created_at）分别保存，录入时间不冒充实际执行时间；
    - entry_channel 当前固定 web；状态流转由后端校验（STATE_TRANSITIONS）；
    - version 用于可编辑状态下的并发控制；作废为受控终态，不物理删除；
    - 台账异常不修改系统健康状态（步骤 3.1 逻辑独立）。
    """

    ledger_no = models.CharField(max_length=50, help_text='台账编号，租户内唯一，自动生成')
    ledger_type = models.CharField(max_length=20, help_text='台账类型')
    executed_date = models.DateField(help_text='实际执行日期')
    executor_names = models.CharField(max_length=200, default='', blank=True, help_text='执行人（多人以顿号或逗号分隔）')
    status = models.CharField(max_length=20, default=LEDGER_STATUS_DRAFT, help_text='台账状态')
    executed_start = models.DateTimeField(null=True, blank=True, help_text='实际执行开始时间')
    executed_end = models.DateTimeField(null=True, blank=True, help_text='实际执行结束时间')
    system = models.ForeignKey(
        LifecycleSystem, models.PROTECT, related_name='operation_ledgers', null=True, blank=True,
        help_text='表头级系统（周期批量新增的按系统台账；历史聚合台账与Excel路线为空）')
    entry_channel = models.CharField(max_length=20, default=ENTRY_CHANNEL_WEB, help_text='录入渠道（当前固定 web）')
    maintenance_period = models.CharField(
        max_length=10, default='', blank=True,
        help_text='维护周期标记（week_month: YYYY-MM；seasonal: YYYY-夏秋/YYYY-冬春；'
                  '历史台账为空），仅用于周期分组与批量新增去重，不表达周/月维护拆分')
    created_from = models.CharField(max_length=20, default=LEDGER_FROM_MANUAL, help_text='创建方式（manual 临时补录 / excel_template Excel模板）')
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
            models.Index(fields=['tenant_id', 'ledger_type', 'maintenance_period'],
                         name='el_ledger_type_period_idx'),
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
            'executed_date': self.executed_date,
            'executor_names': self.executor_names,
            'status': self.status,
            'executed_start': self.executed_start,
            'executed_end': self.executed_end,
            'system': self.system_id,
            'system_name': self.system.name if self.system_id else '',
            'maintenance_period': self.maintenance_period,
            'entry_channel': self.entry_channel,
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
    - 项目内容全量快照保存（template_name_snapshot 仅溯源文本），不回读
      任何模板表（旧可视化模板路线已于 2026-10 删除，字段见迁移 0045）；
    - 填写值按录入类型分列（value_text/value_number/value_bool），可校验；
    - 结果支持 正常/异常/不适用/待复核；异常明细具稳定主键（本表 id），
      为异常转故障预留来源关联；本模块不修改系统健康状态。
    """

    ledger = models.ForeignKey(
        OperationLedger, models.CASCADE, related_name='items', help_text='所属台账')
    system = models.ForeignKey(
        LifecycleSystem, models.PROTECT, related_name='ledger_items', help_text='所属系统（正式系统 ID）')
    # —— 系统快照 ——
    system_code_snapshot = models.CharField(max_length=50, default='', blank=True, help_text='系统编号快照')
    system_name_snapshot = models.CharField(max_length=100, default='', blank=True, help_text='系统名称快照')
    system_location_snapshot = models.CharField(max_length=200, default='', blank=True, help_text='系统安装地点快照')
    # —— 项目快照（手工补录/历史模板项目内容，全量快照不回读模板） ——
    template_name_snapshot = models.CharField(max_length=100, default='', blank=True, help_text='模板名称快照')
    item_name_snapshot = models.CharField(max_length=100, help_text='检查或维护项目名称快照')
    input_type = models.CharField(max_length=20, help_text='录入类型快照')
    unit_snapshot = models.CharField(max_length=20, default='', blank=True, help_text='单位快照')
    choices_snapshot = models.TextField(default='', blank=True, help_text='候选项快照 JSON 数组')
    is_required = models.BooleanField(default=False, help_text='必填规则快照')
    abnormal_rule_snapshot = models.CharField(max_length=200, default='', blank=True, help_text='异常判定规则快照')
    # —— 填写值（按录入类型分列，可校验） ——
    value_text = models.TextField(default='', blank=True, help_text='文本类值（多选为 JSON 选项数组）')
    value_number = models.FloatField(null=True, blank=True, help_text='数值填写值')
    value_bool = models.BooleanField(null=True, blank=True, help_text='布尔填写值')
    # —— 结果与异常 ——
    result = models.CharField(max_length=20, help_text='结果：normal/abnormal/not_applicable/pending_review')
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
                check=models.Q(result__in=ITEM_RESULT_DB_VALUES),
                name='el_ledger_item_result_valid',
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
            'template_name': self.template_name_snapshot,
            'item_name': self.item_name_snapshot,
            'input_type': self.input_type,
            'unit': self.unit_snapshot,
            'choices': self.get_choices(),
            'is_required': self.is_required,
            'abnormal_rule': self.abnormal_rule_snapshot,
            'value_text': self.value_text,
            'value_number': self.value_number,
            'value_bool': self.value_bool,
            'result': self.result,
            'abnormal_desc': self.abnormal_desc,
            'na_reason': self.na_reason,
            'onsite_action': self.onsite_action,
            'executor_name': self.executor_name,
            'executed_at': self.executed_at,
            'is_temporary': self.is_temporary,
            'display_order': self.display_order,
        }


# ======================================================================
# 步骤 3.3（工单管理与异常转单）已于 2026-09-30 整体删除：故障维修工单下线，
# SystemWorkOrder / SystemWorkOrderParticipant / SystemWorkOrderHandlingRecord
# 三表及工单类型/状态/来源等常量一并移除（删除迁移见 migrations 0043）。
# 故障处理统一走追加式"处置记录"（SystemFaultHandlingRecord，含 work_hours），
# 非故障的计划性维护、校准、现场测试等统一由运维台账承载；
# 台账异常明细处置状态常量与计算见 ledger_services.py
# （仅保留 未处置/已转故障/目标已取消，工单处置枚举一并删除）。
# ======================================================================


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


# ======================================================================
# 值班巡检（今日巡检改造，2026-09）：独立的巡检模板与值班巡检单模型
# ----------------------------------------------------------------------
# 今日巡检不再按系统拆分、不关联 LifecycleSystem：
# - 巡检单唯一范围 = 值班日 + 巡检模板（值班人员登记在单上，支持多人+姓名快照）；
# - 每个值班日固定四轮：11:00-11:20 / 16:00-16:20 / 22:00-22:20、次日 6:30-6:50
#   （第四轮发生在下一自然日，仍归属前一天的值班日）；
# - 不记录实际填写时间作为巡检业务字段（created_at/updated_at 仅为系统审计，
#   不作巡检执行时间展示、不参与业务判断、不判断迟填）；
# - 模板结构 = 巡检模板 → 设备名称 → 检查内容（设备名称不关联任何系统）；
# - 巡检明细保存全量快照，模板后续修改/停用不影响历史巡检记录；
# - 异常明细转故障时才由用户选择系统（不允许由设备名称推断系统）；
# - 周维护/月维护/季维护仍走 OperationLedger 体系，与本组模型互不影响。
# ======================================================================

# 固定巡检轮次（稳定编码，页面中文名称不得作为关联条件）
INSPECTION_ROUND_1 = 'r1'
INSPECTION_ROUND_2 = 'r2'
INSPECTION_ROUND_3 = 'r3'
INSPECTION_ROUND_4 = 'r4'
INSPECTION_ROUND_VALUES = [
    INSPECTION_ROUND_1, INSPECTION_ROUND_2, INSPECTION_ROUND_3, INSPECTION_ROUND_4,
]
INSPECTION_ROUND_CHOICES = (
    (INSPECTION_ROUND_1, '11:00-11:20'),
    (INSPECTION_ROUND_2, '16:00-16:20'),
    (INSPECTION_ROUND_3, '22:00-22:20'),
    (INSPECTION_ROUND_4, '6:30-6:50'),
)
INSPECTION_ROUND_TEXT_MAP = dict(INSPECTION_ROUND_CHOICES)

# 巡检录入类型（与台账录入收敛一致：正常/不正常单选 + 数字/文本）
INSPECTION_INPUT_TYPE_CHOICE = 'choice'
INSPECTION_INPUT_TYPE_TEXT = 'text'
INSPECTION_INPUT_TYPE_VALUES = [INSPECTION_INPUT_TYPE_CHOICE, INSPECTION_INPUT_TYPE_TEXT]

# 巡检结果（由填写值派生，不由前端提交：choice 填"不正常"→ abnormal）
INSPECTION_RESULT_NORMAL = 'normal'
INSPECTION_RESULT_ABNORMAL = 'abnormal'
INSPECTION_RESULT_VALUES = [INSPECTION_RESULT_NORMAL, INSPECTION_RESULT_ABNORMAL]

# 巡检单状态：记录/提交分离；已退回（超级管理员退回整改）可再编辑重提；
# 作废为受控作废（留档可查，释放当日唯一占用）
INSPECTION_SHEET_DRAFT = 'draft'
INSPECTION_SHEET_SUBMITTED = 'submitted'
INSPECTION_SHEET_RETURNED = 'returned'
INSPECTION_SHEET_VOID = 'void'
INSPECTION_SHEET_STATUS_VALUES = [
    INSPECTION_SHEET_DRAFT, INSPECTION_SHEET_SUBMITTED,
    INSPECTION_SHEET_RETURNED, INSPECTION_SHEET_VOID,
]
# 允许编辑明细/值班人员的状态（草稿与已退回整改）
INSPECTION_SHEET_EDITABLE_STATUSES = [
    INSPECTION_SHEET_DRAFT, INSPECTION_SHEET_RETURNED,
]

# 巡检单编号前缀：XJ{yyyymmdd}-{seq:04d}，租户内唯一
INSPECTION_SHEET_NO_PREFIX = 'XJ'

# choice 录入类型的固定候选项（与前端 NORMAL_ABNORMAL_CHOICES 对齐）
INSPECTION_CHOICE_NORMAL = '正常'
INSPECTION_CHOICE_ABNORMAL = '不正常'
INSPECTION_DEFAULT_CHOICES = [INSPECTION_CHOICE_NORMAL, INSPECTION_CHOICE_ABNORMAL]


class InspectionTemplate(TenantModelMixin, models.Model):
    """值班巡检模板：模板 → 设备名称 → 检查内容 两级结构。

    - 设备名称只是巡检展示与填写的分组维度，不关联 LifecycleSystem；
    - 模板停用后不可再用于新建巡检单，历史巡检单不受影响（明细保存全量快照）。
    """

    name = models.CharField(max_length=100, help_text='模板名称')
    description = models.CharField(max_length=500, default='', blank=True, help_text='模板说明')
    is_active = models.BooleanField(default=True, help_text='是否启用')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_inspection_template'
        verbose_name = '巡检模板'
        verbose_name_plural = '巡检模板'
        ordering = ('-created_at', '-id')
        indexes = [
            models.Index(fields=['tenant_id', 'is_active']),
        ]

    def __repr__(self):
        return '<InspectionTemplate %r>' % self.name

    def to_view(self, with_counts=False):
        data = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        if with_counts:
            data['devices_count'] = self.devices.filter(is_active=True).count()
        return data


class InspectionTemplateDevice(TenantModelMixin, models.Model):
    """巡检模板设备名称层：一个模板包含多个设备名称。

    设备名称不关联系统档案，也不能用于推断系统；
    巡检异常转故障时由用户显式选择系统。
    """

    template = models.ForeignKey(
        InspectionTemplate, models.CASCADE, related_name='devices', help_text='所属模板')
    device_name = models.CharField(max_length=100, help_text='设备名称（巡检分组维度，不关联系统）')
    display_order = models.IntegerField(default=0, help_text='显示顺序，小者靠前')
    is_active = models.BooleanField(default=True, help_text='是否启用')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_inspection_template_device'
        verbose_name = '巡检模板设备'
        verbose_name_plural = '巡检模板设备'
        ordering = ('display_order', 'id')
        constraints = [
            models.UniqueConstraint(
                fields=['template', 'device_name'], name='uniq_el_ins_tpl_device_name'),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'template']),
        ]

    def __repr__(self):
        return '<InspectionTemplateDevice %r>' % self.device_name

    def to_view(self):
        return {
            'id': self.id,
            'template': self.template_id,
            'device_name': self.device_name,
            'display_order': self.display_order,
            'is_active': self.is_active,
        }


class InspectionTemplateItem(TenantModelMixin, models.Model):
    """巡检模板检查内容层：一个设备名称可配置一个或多个检查内容。

    - 录入类型两种：正常/不正常单选（choice，候选项固定）与数字/文本（text）；
    - 停用或删除检查内容不影响历史巡检明细（明细保存全量快照）。
    """

    device = models.ForeignKey(
        InspectionTemplateDevice, models.CASCADE, related_name='items',
        help_text='所属设备名称')
    name = models.CharField(max_length=200, help_text='检查内容')
    input_type = models.CharField(max_length=20, help_text='录入类型：choice 正常/不正常单选；text 数字/文本')
    choices = models.TextField(default='', blank=True, help_text='候选项 JSON 数组（choice 类型，固定 正常/不正常）')
    is_required = models.BooleanField(default=True, help_text='是否必填')
    display_order = models.IntegerField(default=0, help_text='显示顺序，小者靠前')
    is_active = models.BooleanField(default=True, help_text='是否启用')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_inspection_template_item'
        verbose_name = '巡检模板检查内容'
        verbose_name_plural = '巡检模板检查内容'
        ordering = ('display_order', 'id')
        constraints = [
            models.CheckConstraint(
                check=models.Q(input_type__in=INSPECTION_INPUT_TYPE_VALUES),
                name='el_ins_tpl_item_input_type_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'device']),
        ]

    def __repr__(self):
        return '<InspectionTemplateItem %r>' % self.name

    def get_choices(self):
        if not self.choices:
            return []
        try:
            data = json.loads(self.choices)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    def to_view(self):
        return {
            'id': self.id,
            'device': self.device_id,
            'name': self.name,
            'input_type': self.input_type,
            'choices': self.get_choices(),
            'is_required': self.is_required,
            'display_order': self.display_order,
            'is_active': self.is_active,
        }


class InspectionDutySheet(TenantModelMixin, models.Model):
    """值班巡检单：唯一范围 = 值班日 + 巡检模板（值班人员登记在单上，支持多人）。

    - 每个值班日固定四轮，第四轮发生在次日凌晨仍归属本单 duty_date；
    - 一张单 = 一个值班日 + 一个模板：同一值班日同一模板只有一张有效单
      （作废单通过 uniq_key 后缀释放唯一占用，沿用项目 __deleted_{id} 惯例）；
    - 记录/提交分离：草稿可多次累积四轮记录，提交后不可再修改；
    - 已提交单仅超级管理员可"退回整改"（submitted → returned，原因留痕），
      已退回单可再编辑并重新提交（returned → submitted，更新提交人/时间）；
    - 不关联 LifecycleSystem：异常转故障时才由用户选择系统。
    """

    sheet_no = models.CharField(max_length=50, help_text='巡检单编号，租户内唯一，自动生成')
    duty_date = models.DateField(help_text='值班日（第四轮次发生在次日凌晨仍归属本日）')
    template = models.ForeignKey(
        InspectionTemplate, models.PROTECT, related_name='sheets',
        help_text='巡检模板（值班巡检单范围维度之一，历史单据不受模板停用影响）')
    status = models.CharField(
        max_length=20,
        choices=(
            (INSPECTION_SHEET_DRAFT, '草稿'),
            (INSPECTION_SHEET_SUBMITTED, '已提交'),
            (INSPECTION_SHEET_RETURNED, '已退回'),
            (INSPECTION_SHEET_VOID, '已作废'),
        ),
        default=INSPECTION_SHEET_DRAFT, help_text='当前状态')
    uniq_key = models.CharField(
        max_length=80,
        help_text='租户内唯一键 "{duty_date}|{template_id}"，作废后追加 "|voided_{id}" 后缀释放占用')
    client_token = models.CharField(max_length=64, default='', blank=True,
                                    help_text='客户端幂等键（防重复建单）')
    version = models.IntegerField(default=1, help_text='并发编辑版本号（乐观锁）')
    recorded_rounds = models.TextField(
        default='', blank=True,
        help_text='已记录轮次 JSON 数组（如 ["r1","r2"]）：记录本轮成功后写入，'
                  '已记录轮次只读、不能被再次修改')
    submitted_at = models.DateTimeField(null=True, blank=True, help_text='提交时间')
    submitted_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                     help_text='提交人')
    voided_at = models.DateTimeField(null=True, blank=True, help_text='作废时间')
    voided_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                  help_text='作废人')
    void_reason = models.CharField(max_length=200, default='', blank=True,
                                   help_text='作废原因（受控作废留痕）')
    returned_at = models.DateTimeField(null=True, blank=True, help_text='退回时间')
    returned_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                    help_text='退回人（超级管理员）')
    return_reason = models.CharField(max_length=200, default='', blank=True,
                                     help_text='退回原因（超级管理员退回整改留痕）')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+', help_text='创建人')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_inspection_sheet'
        verbose_name = '值班巡检单'
        verbose_name_plural = '值班巡检单'
        ordering = ('-duty_date', '-id')
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'uniq_key'], name='uniq_el_ins_sheet_key'),
            models.UniqueConstraint(
                fields=['tenant_id', 'sheet_no'], name='uniq_el_ins_sheet_no'),
            models.CheckConstraint(
                check=models.Q(status__in=INSPECTION_SHEET_STATUS_VALUES),
                name='el_ins_sheet_status_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'duty_date']),
            models.Index(fields=['tenant_id', 'status']),
        ]

    def __repr__(self):
        return '<InspectionDutySheet %r>' % self.sheet_no

    def build_uniq_key(self):
        return f'{self.duty_date}|{self.template_id}'

    def get_recorded_rounds(self):
        """已记录轮次列表（容错解析，仅保留合法轮次值）。"""
        if not self.recorded_rounds:
            return []
        try:
            data = json.loads(self.recorded_rounds)
        except (ValueError, TypeError):
            return []
        if not isinstance(data, list):
            return []
        return [r for r in INSPECTION_ROUND_VALUES if r in data]

    def set_recorded_rounds(self, rounds):
        """按固定轮次顺序写入已记录轮次（去重、忽略非法值）。"""
        valid = [r for r in INSPECTION_ROUND_VALUES if r in (rounds or [])]
        self.recorded_rounds = json.dumps(valid, ensure_ascii=False)

    def to_view(self):
        return {
            'id': self.id,
            'sheet_no': self.sheet_no,
            'duty_date': str(self.duty_date),
            'template': self.template_id,
            'template_name': self.template.name,
            'status': self.status,
            'status_text': self.get_status_display(),
            'version': self.version,
            'abnormal_count': self.records.filter(result=INSPECTION_RESULT_ABNORMAL).count(),
            'submitted_at': self.submitted_at,
            'submitted_by_name': self.submitted_by.username if self.submitted_by_id else '',
            'created_by_name': self.created_by.username if self.created_by_id else '',
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

    def to_detail_view(self):
        data = self.to_view()
        data.update({
            'void_reason': self.void_reason,
            'voided_at': self.voided_at,
            'voided_by_name': self.voided_by.username if self.voided_by_id else '',
            'return_reason': self.return_reason,
            'returned_at': self.returned_at,
            'returned_by_name': self.returned_by.username if self.returned_by_id else '',
            'recorded_rounds': self.get_recorded_rounds(),
            'persons': [p.to_view() for p in self.persons.all()],
            'records': [r.to_view() for r in self.records.all()],
        })
        return data


class InspectionDutyPerson(TenantModelMixin, models.Model):
    """值班人员（多人，姓名快照）。

    - 优先选择账号（稳定 ID），同时允许手工补录无账号人员（user 为空）；
    - person_name 为姓名快照，账号改名/删除不影响历史巡检单展示。
    """

    sheet = models.ForeignKey(
        InspectionDutySheet, models.CASCADE, related_name='persons', help_text='所属巡检单')
    user = models.ForeignKey(
        User, models.SET_NULL, related_name='+', null=True, blank=True,
        help_text='账号（可空：手工补录人员无账号）')
    person_name = models.CharField(max_length=100, help_text='值班人员姓名快照')

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_ins_sheet_person'
        verbose_name = '值班巡检人员'
        verbose_name_plural = '值班巡检人员'
        ordering = ('id',)
        constraints = [
            models.UniqueConstraint(
                fields=['sheet', 'user'], name='uniq_el_ins_sheet_person'),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'sheet']),
        ]

    def __repr__(self):
        return '<InspectionDutyPerson %r>' % self.person_name

    def to_view(self):
        return {
            'id': self.id,
            'user': self.user_id,
            'user_name': self.user.username if self.user_id else '',
            'person_name': self.person_name,
        }


class InspectionRecord(TenantModelMixin, models.Model):
    """巡检明细：一行 = 检查内容 × 轮次，保存全量快照。

    - round_no 为固定四轮之一；不记录实际填写时间（created_at/updated_at
      仅为系统审计，不作巡检执行时间展示、不参与业务判断）；
    - 快照字段：设备名称/检查内容/录入类型/候选项/必填规则/排序——
      模板后续修改或停用不影响历史巡检记录；
    - 结果由后端按填写值派生（choice 填"不正常"→ abnormal），不由前端提交；
    - template_item 为空 = 手工临时加项（不依赖模板，同样保存快照）。
    """

    ROUND_TEXT_MAP = INSPECTION_ROUND_TEXT_MAP

    sheet = models.ForeignKey(
        InspectionDutySheet, models.CASCADE, related_name='records', help_text='所属巡检单')
    round_no = models.CharField(
        max_length=8, choices=INSPECTION_ROUND_CHOICES,
        help_text='固定巡检轮次（第四轮归属前一值班日）')
    template_item = models.ForeignKey(
        InspectionTemplateItem, models.SET_NULL, related_name='inspection_records',
        null=True, blank=True,
        help_text='模板检查内容引用（手工加项为空；删除模板项不影响历史快照）')
    is_temporary = models.BooleanField(default=False, help_text='是否手工临时加项')
    client_key = models.CharField(max_length=64, default='', blank=True,
                                  help_text='客户端行键（手工加项幂等更新）')
    # —— 全量快照（模板修改不影响历史记录） ——
    device_name_snapshot = models.CharField(max_length=100, help_text='设备名称快照')
    item_name_snapshot = models.CharField(max_length=200, help_text='检查内容快照')
    input_type_snapshot = models.CharField(max_length=20, help_text='录入类型快照')
    choices_snapshot = models.TextField(default='', blank=True, help_text='候选项 JSON 数组快照')
    is_required_snapshot = models.BooleanField(default=True, help_text='必填规则快照')
    display_order = models.IntegerField(default=0, help_text='显示顺序，小者靠前')
    # —— 填写值（choice 存文本；text 纯数字同时落 value_number） ——
    value_text = models.TextField(default='', blank=True, help_text='填写值文本')
    value_number = models.FloatField(null=True, blank=True, help_text='填写值数字（text 纯数字时落值）')
    result = models.CharField(
        max_length=20,
        choices=(
            (INSPECTION_RESULT_NORMAL, '正常'),
            (INSPECTION_RESULT_ABNORMAL, '异常'),
        ),
        default=INSPECTION_RESULT_NORMAL, help_text='巡检结果（后端按填写值派生）')
    abnormal_desc = models.TextField(default='', blank=True, help_text='异常说明（选填）')
    onsite_action = models.TextField(default='', blank=True, help_text='现场处理内容')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_inspection_record'
        verbose_name = '巡检明细'
        verbose_name_plural = '巡检明细'
        ordering = ('round_no', 'device_name_snapshot', 'display_order', 'id')
        constraints = [
            # 模板行按（单, 轮次, 模板项）唯一；手工加项 template_item 为 NULL 不受约束
            models.UniqueConstraint(
                fields=['sheet', 'round_no', 'template_item'],
                name='uniq_el_ins_record_item_round'),
            models.CheckConstraint(
                check=models.Q(round_no__in=INSPECTION_ROUND_VALUES),
                name='el_ins_record_round_valid',
            ),
            models.CheckConstraint(
                check=models.Q(result__in=INSPECTION_RESULT_VALUES),
                name='el_ins_record_result_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'sheet', 'round_no']),
            models.Index(fields=['tenant_id', 'result']),
        ]

    def __repr__(self):
        return '<InspectionRecord sheet=%s round=%s item=%s>' % (
            self.sheet_id, self.round_no, self.item_name_snapshot)

    def get_choices(self):
        if not self.choices_snapshot:
            return []
        try:
            data = json.loads(self.choices_snapshot)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    def to_view(self):
        return {
            'id': self.id,
            'sheet': self.sheet_id,
            'round_no': self.round_no,
            'round_text': self.ROUND_TEXT_MAP.get(self.round_no, self.round_no),
            'template_item': self.template_item_id,
            'is_temporary': self.is_temporary,
            'client_key': self.client_key,
            'device_name': self.device_name_snapshot,
            'item_name': self.item_name_snapshot,
            'input_type': self.input_type_snapshot,
            'choices': self.get_choices(),
            'is_required': self.is_required_snapshot,
            'display_order': self.display_order,
            'value_text': self.value_text,
            'value_number': self.value_number,
            'result': self.result,
            'abnormal_desc': self.abnormal_desc,
            'onsite_action': self.onsite_action,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

# 设计器维护台账模板（已下线，休眠保留）：模型主体在 layout_models.py，
# 其视图/服务/路由均已删除，业务代码不访问；保持注册仅使模型状态与 0039
# 迁移一致（注销会触发 DeleteModel 删历史表），LongTextField 供 0039
# 序列化引用解析；Excel 模板模型同在文件底部导入完成注册。
from apps.equipment_lifecycle.layout_models import (  # noqa: E402
    OperationLedgerLayoutTemplate,
    OperationLedgerLayoutVersion,
)
from apps.equipment_lifecycle.excel_models import (  # noqa: E402
    OperationLedgerExcelRecord,
    OperationLedgerExcelTemplate,
    OperationLedgerExcelTemplateVersion,
)
# 系统配置参数与配置变更（2026-10）：模型主体在 config_models.py（文件行数治理），
# 底部导入完成模型注册，使 makemigrations/迁移状态一致。
from apps.equipment_lifecycle.config_models import (  # noqa: E402
    ConfigChangeItem,
    ConfigChangeRecord,
    ConfigParamDefinition,
    ConfigParamSystemScope,
    SystemParamValue,
)
# 运行与故障记录（2026-10-11 合并改造）：统一主表/进展表模型主体在
# operation_models.py（文件行数治理），底部导入完成模型注册，
# 使 makemigrations/迁移状态一致；旧 SystemFault/SystemFaultHandlingRecord/
# SystemRuntimeRecord/SystemRuntimeRecordProgress/SystemEvent 五模型已退役。
from apps.equipment_lifecycle.operation_models import (  # noqa: E402
    SystemOperationProgress,
    SystemOperationRecord,
)

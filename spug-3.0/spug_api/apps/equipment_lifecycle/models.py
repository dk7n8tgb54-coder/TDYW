# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——系统主数据模型（步骤二）。

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
# 故障处置记录承载，健康状态只由有效故障的影响程度驱动（fault_services）。
HEALTH_STATUS_VALUES = ['normal', 'degraded', 'fault', 'interrupted', 'unknown']
FAULT_IMPACT_VALUES = ['degraded', 'fault', 'interrupted']
# 影响系统运行时的合法影响程度即 FAULT_IMPACT_VALUES；
# 不影响系统运行（部件故障/离线维修）时 impact_status 统一存空串
FAULT_IMPACT_DB_VALUES = [''] + FAULT_IMPACT_VALUES
FAULT_STATUS_VALUES = ['handling', 'closed', 'cancelled']


def load_legacy_source_snapshot(raw):
    """解析旧巡检台账来源快照 JSON（字段为空或非法时返回空 dict）。"""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


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


class SystemFault(TenantModelMixin, models.Model):
    """系统故障主表（步骤 3.1，单系统简化）。

    与步骤一删除的旧故障表（tdyw_fault_records/tdyw_fault_parts）无关，不复用旧表名。

    关联规则（一个故障单只关联一个故障系统，不建设跨系统影响关系）：
    - 故障系统必须通过外键关联系统主数据（请求与存储一律用系统 ID，页面只显示名称）；
    - 故障发生时保存系统快照（编号/名称/安装地点），系统改名后历史详情仍显示当时名称；
      快照仅用于历史展示，不替代正式外键；
    - 具体故障对象以快照文本（名称/型号/编号）记录，不建立单台设备外键、
      不关联 DeviceResume；历史故障的组成项名称以 fault_component_name 文本
      快照保留（配置组成项功能已下线）。
    一次实际工作涉及多个独立系统时分别建立故障，不允许一单关联多系统。

    状态流转（2026-10 流程简化，模块未上线无历史包袱）：
    新建 → handling →(确认恢复并结案 recover，单次事务)→ closed；
    handling 可 →(cancel)→ cancelled（受控撤销登记，del 权限）。
    已关闭不可撤销；已撤销为终态，不可重复撤销或继续处理。

    cancelled 状态语义（2026-10）：撤销错误/重复/误报的故障登记——
    登记本身不再作为有效故障，但历史记录保留可追溯（不物理删除），
    不参与有效故障统计与健康状态计算。历史数据沿用 cancelled 值保证兼容，
    前端展示文案为"已撤销"。

    旧流程的 pending（待处置）与 recovered（已恢复）过渡态已整体删除，
    由迁移 0051 清理存量并收紧 CHECK 约束，数据库层拒绝旧状态值。
    """

    STATUS_HANDLING = 'handling'
    STATUS_CLOSED = 'closed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = (
        (STATUS_HANDLING, '处置中'),
        (STATUS_CLOSED, '已关闭'),
        (STATUS_CANCELLED, '已撤销'),
    )
    STATUS_TEXT_MAP = dict(STATUS_CHOICES)

    IMPACT_DEGRADED = 'degraded'
    IMPACT_FAULT = 'fault'
    IMPACT_INTERRUPTED = 'interrupted'
    IMPACT_CHOICES = (
        (IMPACT_DEGRADED, '降级'),
        (IMPACT_FAULT, '故障'),
        (IMPACT_INTERRUPTED, '中断'),
    )
    IMPACT_TEXT_MAP = dict(IMPACT_CHOICES)

    SOURCE_MANUAL = 'manual'
    # 运行异常记录转故障来源类型（2026-10 运行异常记录第一版）
    SOURCE_RUNTIME_RECORD = 'runtime_record'

    fault_no = models.CharField(max_length=50, help_text='故障编号（GZ+创建日期+当日四位序号，自动生成；当日序号全租户共享，存量数据仅保证租户内唯一）')
    system = models.ForeignKey(
        LifecycleSystem, models.PROTECT, related_name='faults',
        help_text='故障系统（外键关联系统主数据，一个故障单只关联一个系统）')
    impact_status = models.CharField(
        max_length=20, choices=IMPACT_CHOICES, default='', blank=True,
        help_text='系统影响程度：影响系统运行时必填（degraded降级/fault故障/interrupted中断）；'
                  '不影响系统运行时后端强制存空串')
    affects_system_operation = models.BooleanField(
        default=False,
        help_text='是否影响系统运行（False=部件故障/离线维修，默认不影响，不参与健康状态计算；'
                  'True=影响运行，按 impact_status 参与健康状态计算）')
    # 故障系统故障发生时快照
    system_code = models.CharField(max_length=50, help_text='故障系统编号快照')
    system_name = models.CharField(max_length=100, help_text='故障系统名称快照')
    system_location = models.CharField(max_length=200, help_text='故障系统安装地点快照')

    occurred_at = models.DateTimeField(help_text='故障发生时间')
    phenomenon = models.TextField(max_length=2000, help_text='故障现象')
    fault_object_name = models.CharField(max_length=100, default='', blank=True,
                                         help_text='具体故障对象名称快照')
    fault_object_model = models.CharField(max_length=100, default='', blank=True,
                                          help_text='具体故障对象型号快照')
    fault_object_sn = models.CharField(max_length=100, default='', blank=True,
                                       help_text='具体故障对象编号/序列号快照')
    fault_component_name = models.CharField(max_length=100, default='', blank=True,
                                            help_text='配置组成项名称快照（组成项功能下线前历史数据，仅展示）')

    # 原因分析是单一字段，不同阶段只是展示口径不同：新增=初步原因分析、
    # 处置中=初步判断、结案=最终原因；"原因未明"不是第二个原因字段，
    # 勾选后 reason_analysis 保存的是未明说明（不强迫用户填写虚假原因）。
    reason_analysis = models.TextField(max_length=2000, default='', blank=True, help_text='原因分析（新增=初步原因分析；处置中展示为初步判断；结案时保存为最终原因；原因未明时保存未明说明）')
    reason_unknown = models.BooleanField(
        default=False,
        help_text='原因未明标记（确实无法确定原因时为 True，reason_analysis 保存未明说明；'
                  '历史数据为 False）')
    recovered_at = models.DateTimeField(null=True, blank=True, help_text='恢复时间')
    # 结案说明（2026-10 字段合并）：唯一读写来源，结案时一次性填写
    # 采取的处理措施、恢复验证依据与最终处理结果；原 recover_confirm（恢复确认
    # 信息）与 final_result（最终结果）语义重复，已删除，历史数据由迁移 0054
    # 合并回填（两者都有时按"恢复确认信息：…；最终结果：…"格式拼接，不丢内容）
    recovery_close_note = models.TextField(
        max_length=3000, default='', blank=True,
        help_text='结案说明（采取的处理措施、恢复验证依据及最终处理结果）')
    # 恢复确认人（2026-09）：手动输入的确认人姓名（多人顿号分隔），参照故障登记人
    # registrar_name 口径——实际执行恢复确认的人，不关联 User（可能无系统账号）；
    # 原外键 recovered_by 已删除，历史数据迁移时回填为登录账号用户名文本
    recovered_by_name = models.CharField(
        max_length=200, default='', blank=True,
        help_text='恢复确认人（手动输入的确认人姓名，多人以顿号分隔；'
                  '历史数据回填为确认操作账号用户名）')
    recovered_confirmed_at = models.DateTimeField(null=True, blank=True, help_text='恢复确认时间')
    cancel_reason = models.CharField(max_length=200, default='', blank=True,
                                     help_text='撤销原因（撤销错误/重复的故障登记时必填，审计与履历留痕）')
    # 撤销人与撤销时间（2026-10）：撤销登记操作留痕（与 updated_at/updated_by
    # 独立，语义明确）；历史已撤销数据由迁移 0053 从 updated 字段回填
    cancelled_at = models.DateTimeField(null=True, blank=True,
                                        help_text='撤销时间（撤销登记操作写入）')
    cancelled_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True,
        help_text='撤销人（执行撤销登记的登录账号，仅用于审计与展示）')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_HANDLING,
                              help_text='当前状态（新建即处置中，恢复确认并结案后进入已关闭终态）')
    source_type = models.CharField(max_length=20, default=SOURCE_MANUAL, help_text='来源类型：manual 人工 / ledger_item 台账异常明细 / inspection_record 值班巡检明细 / runtime_record 运行记录（步骤 3.3；运行记录 2026-10）')
    source_id = models.CharField(max_length=50, default='', blank=True, help_text='来源对象 ID 冗余（与来源外键一致，便于追溯查询）')
    source_ledger_item = models.ForeignKey(
        'equipment_lifecycle.OperationLedgerItem', models.PROTECT,
        related_name='generated_faults', null=True, blank=True,
        help_text='来源台账异常明细（台账异常转故障时写入，真实外键保证可追溯）')
    source_inspection_record = models.ForeignKey(
        'equipment_lifecycle.InspectionRecord', models.PROTECT,
        related_name='generated_faults', null=True, blank=True,
        help_text='来源巡检异常明细（巡检异常转故障时写入，双向追溯）')
    source_runtime_record = models.ForeignKey(
        'equipment_lifecycle.SystemRuntimeRecord', models.PROTECT,
        related_name='generated_faults', null=True, blank=True,
        help_text='来源运行记录（运行记录转故障时写入，正式外键双向追溯；'
                  '一条运行记录同一时间最多一张有效故障，防重复转换）')
    # 旧巡检台账来源快照：来源明细物理删除后保留历史语义（来源类型仍为 ledger_item）
    source_ledger_legacy = models.TextField(
        default='', blank=True,
        help_text='旧巡检台账来源快照 JSON（台账号/类型/项目名/系统快照等；'
                  '来源明细随旧巡检台账受控删除后，据此展示历史来源，不做跳转）')

    created_by = models.ForeignKey(
        User, models.PROTECT, related_name='+',
        help_text='创建人（实际登录账号，仅用于审计）')
    # 故障登记人（2026-09）：手动输入的登记人姓名，只表示"谁登记"，
    # 不代表其负责后续跟进、不承担维修责任（处置负责人字段已于 2026-09 删除）；
    # 不关联 User——实际登记人可能没有系统账号（共用登录账号场景），
    # 参照系统档案 responsible_user_name 的姓名快照口径。
    # 历史故障登记人为空（可空文本），新增时由视图层写入（缺省当前登录用户姓名）。
    registrar_name = models.CharField(
        max_length=200, default='', blank=True,
        help_text='故障登记人（手动输入的登记人姓名，多人以顿号分隔；'
                  '实际添加本条故障记录的人，不代表后续跟进与维修责任；'
                  '与登录账号 created_by 独立，历史数据可为空）')

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
                check=models.Q(impact_status__in=FAULT_IMPACT_DB_VALUES),
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
            'affects_system_operation': self.affects_system_operation,
            'occurred_at': self.occurred_at,
            'phenomenon': self.phenomenon,
            'status': self.status,
            'status_text': self.STATUS_TEXT_MAP.get(self.status, self.status),
            'registrar_name': self.registrar_name or '',
            'created_by_name': self.created_by.username if self.created_by_id else '',
            'created_at': self.created_at,
        }

    def _source_ledger_field(self, key):
        """台账来源定位字段：真实外键在位时实时读取，否则回落 legacy 快照。"""
        if self.source_ledger_item_id:
            if key == 'ledger_no':
                return self.source_ledger_item.ledger.ledger_no
            if key == 'ledger_type':
                return self.source_ledger_item.ledger.ledger_type
            if key == 'item_name':
                return self.source_ledger_item.item_name_snapshot
            return ''
        return load_legacy_source_snapshot(self.source_ledger_legacy).get(key, '')

    def to_detail_view(self):
        """详情：全字段（单系统简化，无受影响系统）。"""
        data = self.to_view()
        data.update({
            'fault_object_name': self.fault_object_name,
            'fault_object_model': self.fault_object_model,
            'fault_object_sn': self.fault_object_sn,
            'fault_component_name': self.fault_component_name or '',
            'reason_analysis': self.reason_analysis,
            'reason_unknown': self.reason_unknown,
            'recovered_at': self.recovered_at,
            'recovery_close_note': self.recovery_close_note,
            'recovered_by_name': self.recovered_by_name or '',
            'recovered_confirmed_at': self.recovered_confirmed_at,
            # 撤销登记留痕（2026-10）：已撤销详情回显撤销原因/时间/人，仅供历史追溯
            'cancel_reason': self.cancel_reason or '',
            'cancelled_at': self.cancelled_at,
            'cancelled_by_name': self.cancelled_by.username if self.cancelled_by_id else '',
            'source_type': self.source_type,
            'source_id': self.source_id,
            # 台账来源追溯：跳回来源台账明细所需定位信息
            # （旧巡检台账明细已删除时回落到 legacy 快照，仅展示不做跳转）
            'source_ledger_item': self.source_ledger_item_id,
            'source_ledger': (
                self.source_ledger_item.ledger_id if self.source_ledger_item_id else None),
            'source_ledger_no': self._source_ledger_field('ledger_no'),
            'source_ledger_type': self._source_ledger_field('ledger_type'),
            'source_ledger_item_name': self._source_ledger_field('item_name'),
            'source_ledger_legacy': bool(
                not self.source_ledger_item_id and self.source_ledger_legacy),
            # 巡检来源追溯：值班巡检单与轮次定位信息（转单后双向可查）
            'source_inspection_record': self.source_inspection_record_id,
            'source_inspection_sheet': (
                self.source_inspection_record.sheet_id
                if self.source_inspection_record_id else None),
            'source_inspection_sheet_no': (
                self.source_inspection_record.sheet.sheet_no
                if self.source_inspection_record_id else ''),
            'source_inspection_duty_date': (
                str(self.source_inspection_record.sheet.duty_date)
                if self.source_inspection_record_id else ''),
            'source_inspection_round_text': (
                self.source_inspection_record.ROUND_TEXT_MAP.get(self.source_inspection_record.round_no, '')
                if self.source_inspection_record_id else ''),
            'source_inspection_item_name': (
                self.source_inspection_record.item_name_snapshot
                if self.source_inspection_record_id else ''),
            # 运行异常记录来源追溯（2026-10 第二版）：正式外键双向可查，跳回运行异常记录详情
            'source_runtime_record': self.source_runtime_record_id,
            'source_runtime_record_no': (
                self.source_runtime_record.record_no
                if self.source_runtime_record_id else ''),
            'updated_at': self.updated_at,
        })
        return data


class SystemFaultHandlingRecord(TenantModelMixin, models.Model):
    """故障处置记录（2026-10 用户文案定名"处置记录"；2026-09 曾统一改名
    "处理进展"，内部字段与 API 保持兼容不改名）：追加式时间线，
    记录检查、临时措施、送厂、厂家反馈、返还、本方测试、持续观察等整体跟进，
    不把过程反复覆盖在一个文本字段中。

    - 已保存记录不得被普通用户静默覆盖：更正时把原内容、修改内容、更正原因
      追加保存到 corrections JSON 数组（[{old, new, reason, by, at}]）；
    - 处置类型（progress_type）与处置结果（result）字段已删除（2026-10-05），
      仅保留处置时间/处置人/处置措施；旧参数出现即拒绝，不静默忽略；
    - 附件使用项目现有 EvidenceAttachment 能力
      （module=equipment_lifecycle, object_type=el_fault_handling, object_id=记录ID）。
    """

    fault = models.ForeignKey(SystemFault, models.CASCADE, related_name='handling_records',
                              help_text='所属故障')
    handled_at = models.DateTimeField(help_text='处置时间')
    # handler 保留为审计字段（记录操作登录账号，历史数据不变）；
    # 处置人为手动输入姓名（recorder_name，2026-09），不关联 User，
    # 历史记录无 recorder_name 时展示回落到 handler 的用户名
    handler = models.ForeignKey(
        User, models.PROTECT, related_name='+',
        help_text='记录操作账号（审计字段；处置人姓名见 recorder_name）')
    recorder_name = models.CharField(
        max_length=200, default='', blank=True,
        help_text='处置人（手动输入的姓名，多人以顿号分隔；'
                  '实际添加本条处置记录的人，不代表负责整个故障；'
                  '空串=历史记录，展示回落 handler 用户名）')
    content = models.TextField(max_length=2000, help_text='处置措施')
    # 工时（2026-09-30 工单下线后由处置记录统一承接，选填，小时）
    work_hours = models.FloatField(null=True, blank=True, help_text='本次工时（小时，选填）')
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
            'recorder_name': self.recorder_name or '',
            'content': self.content,
            'work_hours': self.work_hours,
            'corrections': self.get_corrections(),
            'created_at': self.created_at,
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
    entry_channel = models.CharField(max_length=20, default=ENTRY_CHANNEL_WEB, help_text='录入渠道（当前固定 web）')
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


# 统一系统履历事件枚举（步骤 3.4；Meta 约束访问不到类作用域，提为模块级）
# 单系统简化：一条事件只关联一个系统，不再有跨系统角色（primary/affected/related 已删）
# upgrade：系统升级管理挂接系统档案（2026-09），升级登记/完成/回退写入履历
# work_order 事件类型已随工单功能删除（2026-09-30），存量工单事件由迁移 0043 清理
# inspection：值班巡检异常转故障（2026-09），转换动作落目标系统履历
# runtime：运行异常记录（2026-10）——2026-10-05 第四版起运行异常记录不再写入履历，
# 该类型仅为历史已生成事件保留（回溯展示，不产生新数据）
# config：配置变更（2026-10）——仅重要配置变更（include_in_history）应用/回退
# 时写入履历，普通配置变更不进履历；事件携带变更编号与来源链接
EVENT_TYPE_VALUES = ['fault', 'ledger', 'health', 'config_snapshot', 'upgrade', 'inspection', 'runtime', 'config']
EVENT_SOURCE_TYPE_VALUES = [
    'fault', 'ledger_item', 'health', 'config_snapshot', 'upgrade',
    'inspection_record', 'runtime_record', 'config_change',
]
EVENT_ACTION_VALUES = [
    'create', 'recover', 'close', 'cancel',
    'convert_to_fault',
    'complete', 'status_change', 'snapshot',
    'rollback', 'mark_important', 'apply',
]


class SystemEvent(TenantModelMixin, models.Model):
    """统一系统履历事件（步骤 3.4，单系统简化）。

    - 由业务动作经 event_services.record_system_event 自动生成，与业务保存
      处于同一事务；普通用户不能手工新增，不提供普通修改与物理删除接口；
    - 故障、台账异常、健康状态与配置快照共用同一事件模型，
      每条事件有明确主要来源（source_type + source_id）；
    - 一条事件只通过正式系统 ID 外键关联一个系统（PROTECT），保存系统
      编号/名称快照，系统改名后历史事件仍显示保存时的名称；
      不再建立跨系统事件角色（primary/affected/related 已随受影响系统
      结构一并移除），系统名称只用于事件快照，不替代正式外键；
    - 更正与受控撤销以追加新事件表达（如故障作废），
      已生成事件原样保留；来源对象作废后事件与关联继续保留；
    - 事件纯插入，不递归触发健康状态重算；重复业务请求由业务层
      状态机与幂等键拦截，不产生重复事件。
    """

    EVENT_FAULT = 'fault'
    EVENT_LEDGER = 'ledger'
    EVENT_HEALTH = 'health'
    EVENT_CONFIG_SNAPSHOT = 'config_snapshot'
    EVENT_UPGRADE = 'upgrade'
    EVENT_INSPECTION = 'inspection'
    EVENT_RUNTIME = 'runtime'
    # 配置变更（2026-10）：仅重要配置变更应用/回退时写入（普通变更只留变更历史与审计）
    EVENT_CONFIG = 'config'
    EVENT_TYPE_CHOICES = (
        (EVENT_FAULT, '故障'),
        (EVENT_LEDGER, '台账异常'),
        (EVENT_HEALTH, '健康状态'),
        (EVENT_CONFIG_SNAPSHOT, '配置快照'),
        (EVENT_UPGRADE, '系统升级'),
        (EVENT_INSPECTION, '值班巡检'),
        (EVENT_CONFIG, '配置变更'),
        (EVENT_RUNTIME, '运行记录'),
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
        max_length=50, default='', blank=True, help_text='来源编号快照（故障号/台账号/快照名）')
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

# ======================================================================
# 运行异常记录（2026-10，第一版）：面向用户的统一运行情况录入入口
# ----------------------------------------------------------------------
# 定位：异常与运行情况的统一录入，用户不必先判断"故障/事件/其他类型"；
# 适用于用户反馈、值班发现的运行异常、短暂中断或恢复、已处理的小问题、
# 需要后续跟进的运行情况。
# 边界（明确不纳入）：周期巡视与维护（巡检单/运维台账）、临时维护保养校准、
# 系统升级（upgrade 模块）、单项配置变更、系统事件手工录入——各自模块负责。
# 履历规则（2026-10-05 第四版）：运行异常记录不再生成 SystemEvent（历史已写入
# 的事件保留供回溯）；正式故障进入系统履历，由故障服务层控制。
# ======================================================================

# 编号前缀 YX{yyyymmdd}-{seq:04d}（当日序号口径与故障编号一致：全租户共享）
RUNTIME_RECORD_NO_PREFIX = 'YX'
RUNTIME_RECORD_NO_SEQ_LIMIT = 9999

RUNTIME_RECORD_STATUS_RECORDED = 'recorded'
# 2026-10-06 旧状态归一（迁移 0007）：历史 pending_triage/no_follow_up 已按
# "已记录"、resolved/closed 已按"已完成"归一为正式状态，枚举与 CHECK 约束
# 同步收紧为四状态，旧值不再可写入。
RUNTIME_RECORD_STATUS_FOLLOWING_UP = 'following_up'
RUNTIME_RECORD_STATUS_COMPLETED = 'completed'
RUNTIME_RECORD_STATUS_CONVERTED_FAULT = 'converted_fault'
RUNTIME_RECORD_STATUS_VALUES = [
    RUNTIME_RECORD_STATUS_RECORDED,
    RUNTIME_RECORD_STATUS_FOLLOWING_UP,
    RUNTIME_RECORD_STATUS_COMPLETED,
    RUNTIME_RECORD_STATUS_CONVERTED_FAULT,
]

# 状态机（后端动作接口校验）：
# recorded（已记录，登记已完成的合法稳定状态，可长期保留，不进待办）→
#   following_up（追加首条处理进展）/converted_fault（独立转故障）；
# following_up → completed（完成跟进）/converted_fault；
# completed（已完成）→ following_up（重新跟进）；不提供普通关闭动作；
# converted_fault 为终态：正式处置以 SystemFault 为准，不再双向同步状态。
RUNTIME_RECORD_TRANSITIONS = {
    RUNTIME_RECORD_STATUS_RECORDED: {
        RUNTIME_RECORD_STATUS_FOLLOWING_UP, RUNTIME_RECORD_STATUS_CONVERTED_FAULT,
    },
    RUNTIME_RECORD_STATUS_FOLLOWING_UP: {
        RUNTIME_RECORD_STATUS_COMPLETED, RUNTIME_RECORD_STATUS_CONVERTED_FAULT,
    },
    RUNTIME_RECORD_STATUS_COMPLETED: {
        RUNTIME_RECORD_STATUS_FOLLOWING_UP,
    },
    RUNTIME_RECORD_STATUS_CONVERTED_FAULT: set(),
}

# 允许普通编辑与追加处理进展的状态（已完成仍可补录；已转故障为终态）
EDITABLE_RUNTIME_RECORD_STATUSES = (
    RUNTIME_RECORD_STATUS_RECORDED,
    RUNTIME_RECORD_STATUS_FOLLOWING_UP,
    RUNTIME_RECORD_STATUS_COMPLETED,
)

# 异常类别（2026-10 第二版，结构化补充字段）：固定枚举，新建选填（空串=未选择）；
# 仅用于筛选与统计归类，不参与任何状态机与履历判定
RUNTIME_CATEGORY_DEVICE = 'device'
RUNTIME_CATEGORY_SIGNAL = 'signal'
RUNTIME_CATEGORY_LINK = 'link'
RUNTIME_CATEGORY_POWER = 'power'
RUNTIME_CATEGORY_ENVIRONMENT = 'environment'
RUNTIME_CATEGORY_SOFTWARE = 'software'
RUNTIME_CATEGORY_OTHER = 'other'
RUNTIME_CATEGORY_VALUES = [
    RUNTIME_CATEGORY_DEVICE, RUNTIME_CATEGORY_SIGNAL, RUNTIME_CATEGORY_LINK,
    RUNTIME_CATEGORY_POWER, RUNTIME_CATEGORY_ENVIRONMENT,
    RUNTIME_CATEGORY_SOFTWARE, RUNTIME_CATEGORY_OTHER,
]
RUNTIME_CATEGORY_DB_VALUES = [''] + RUNTIME_CATEGORY_VALUES
RUNTIME_CATEGORY_CHOICES = (
    (RUNTIME_CATEGORY_DEVICE, '设备异常'),
    (RUNTIME_CATEGORY_SIGNAL, '信号异常'),
    (RUNTIME_CATEGORY_LINK, '链路传输'),
    (RUNTIME_CATEGORY_POWER, '供电异常'),
    (RUNTIME_CATEGORY_ENVIRONMENT, '机房环境'),
    (RUNTIME_CATEGORY_SOFTWARE, '软件/数据'),
    (RUNTIME_CATEGORY_OTHER, '其他'),
)
RUNTIME_CATEGORY_TEXT_MAP = dict(RUNTIME_CATEGORY_CHOICES)


class SystemRuntimeRecord(TenantModelMixin, models.Model):
    """运行异常记录：异常与运行情况的统一录入入口（第一版）。

    - 新建只要求 系统/发生时间/标题/情况描述，其余字段选填或默认值；
    - 新建成功即 recorded（已记录，登记已完成、暂不需要后续处理的合法稳定
      状态，可长期保留，不作为待办）；研判不再是必经步骤（第四版
      2026-10-05，旧 triage/close 兼容端点已随 2026-10-06 状态归一整体删除）：
      追加首条处理进展即进入跟进中，转正式故障为独立动作（recorded/
      following_up 均可直接转换），前端不提供业务"关闭"入口；
    - 用户可见状态即全部状态：已记录/跟进中/已完成/已转故障；完成跟进入
      completed（已完成，可重新跟进）；历史 pending_triage/no_follow_up/
      resolved/closed 已由迁移 0007 按语义归一（→recorded / →completed）；
    - 运行异常记录不纳入系统履历（2026-10-05 第四版起，创建/研判升级影响/转为故障
      均不再生成 SystemEvent；历史已写入的事件保留仅供回溯）；
      具体对象名称/对象型号/影响系统运行（含影响程度）/标记重要四组字段已于
      2026-10-06 整体删除（迁移 0006），历史数据随列删除不再保留；正式故障
      进入系统履历（"发生故障"履历由 create_fault_record 生成）；
    - 转为故障后记录状态为 converted_fault（终态），后续处理/恢复确认/关闭
      以 SystemFault 为准，运行异常记录不维护第二套处理状态；
    - 系统快照仅用于历史展示，正式关联一律用 system 外键（PROTECT）。
    """

    STATUS_RECORDED = RUNTIME_RECORD_STATUS_RECORDED
    STATUS_FOLLOWING_UP = RUNTIME_RECORD_STATUS_FOLLOWING_UP
    STATUS_COMPLETED = RUNTIME_RECORD_STATUS_COMPLETED
    STATUS_CONVERTED_FAULT = RUNTIME_RECORD_STATUS_CONVERTED_FAULT
    STATUS_CHOICES = (
        (STATUS_RECORDED, '已记录'),
        (STATUS_FOLLOWING_UP, '跟进中'),
        (STATUS_COMPLETED, '已完成'),
        (STATUS_CONVERTED_FAULT, '已转故障'),
    )
    STATUS_TEXT_MAP = dict(STATUS_CHOICES)

    CATEGORY_TEXT_MAP = RUNTIME_CATEGORY_TEXT_MAP

    record_no = models.CharField(max_length=50, help_text='运行记录编号（YX+创建日期+当日四位序号，自动生成；当日序号全租户共享）')
    system = models.ForeignKey(
        LifecycleSystem, models.PROTECT, related_name='runtime_records',
        help_text='所属系统（正式系统 ID 外键）')
    # —— 系统快照（创建时点，仅历史展示） ——
    system_code = models.CharField(max_length=50, help_text='系统编号快照')
    system_name = models.CharField(max_length=100, help_text='系统名称快照')
    system_location = models.CharField(max_length=200, help_text='系统安装地点快照')

    occurred_at = models.DateTimeField(help_text='发生时间')
    title = models.CharField(max_length=200, help_text='标题')
    description = models.TextField(max_length=2000, help_text='情况描述')
    # 登记人（2026-10）：手动输入的登记人姓名，只表示"谁登记这条运行异常记录"，
    # 与登录账号 created_by 独立（共用登录账号场景下实际登记人可能没有账号），
    # 参照故障登记人 registrar_name 口径；历史数据为空（可空文本）
    registrar_name = models.CharField(
        max_length=200, default='', blank=True,
        help_text='登记人（手动输入的登记人姓名，多人以顿号分隔；'
                  '实际添加本条运行记录的人，与登录账号 created_by 独立，'
                  '历史数据可为空）')

    needs_follow_up = models.BooleanField(
        default=False, help_text='是否需要跟进（标记跟进中状态时置 True）')
    measures_taken = models.TextField(
        max_length=1000, default='', blank=True, help_text='已采取措施（选填）')
    handling_result = models.TextField(
        max_length=1000, default='', blank=True, help_text='处理结果（选填，完成跟随时可补填）')

    # —— 研判（2026-10 第二版）：研判动作写入，一次研判一组快照字段 ——
    triaged_at = models.DateTimeField(
        null=True, blank=True, help_text='研判时间（缺省研判动作当时）')
    triaged_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True,
        help_text='研判操作账号（审计字段；研判人姓名见 triaged_by_name）')
    triaged_by_name = models.CharField(
        max_length=100, default='', blank=True,
        help_text='研判人（手动输入姓名快照，缺省取研判操作账号显示姓名）')
    triage_note = models.TextField(
        max_length=1000, default='', blank=True,
        help_text='研判说明（转正式故障的研判必须填写）')

    # —— 跟进与待办（2026-10 第二版）：仅"跟进中"记录参与待办视图 ——
    follow_up_name = models.CharField(
        max_length=100, default='', blank=True,
        help_text='跟进人（手动输入姓名快照，可多人顿号分隔；待办视图按此筛选）')
    planned_handle_at = models.DateTimeField(
        null=True, blank=True, help_text='计划处理时间（待办超期判定依据）')
    resolved_at = models.DateTimeField(
        null=True, blank=True, help_text='首次完成跟进时间（原"标记已处理"；统计平均处理时长用，不随重新跟进/再次完成覆盖）')

    # —— 结构化补充字段（2026-10 第二版）：全部选填，不增加录入负担 ——
    # 具体对象名称/对象型号两列已删除（2026-10-06 迁移 0006），历史数据随列删除
    category = models.CharField(
        max_length=20, choices=RUNTIME_CATEGORY_CHOICES, default='', blank=True,
        help_text='异常类别（选填：device设备异常/signal信号异常/link链路传输/'
                  'power供电异常/environment机房环境/software软件数据/other其他；空串=未选择）')
    initial_reason = models.CharField(
        max_length=500, default='', blank=True, help_text='初步原因（选填）')
    impact_scope = models.CharField(
        max_length=200, default='', blank=True, help_text='影响范围（选填，文本描述）')
    # is_repeated 与重复问题关联表已随功能下线删除（2026-10-06 迁移 0008）

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_RECORDED,
        help_text='当前状态')
    client_token = models.CharField(
        max_length=64, default='', blank=True, help_text='客户端幂等令牌（创建防重复）')

    created_by = models.ForeignKey(User, models.PROTECT, related_name='+', help_text='创建人')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_runtime_record'
        verbose_name = '运行记录'
        verbose_name_plural = '运行记录'
        ordering = ('-occurred_at', '-id')
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'record_no'], name='uniq_el_runtime_record_tenant_no'),
            models.CheckConstraint(
                check=models.Q(status__in=RUNTIME_RECORD_STATUS_VALUES),
                name='el_runtime_record_status_valid',
            ),
            models.CheckConstraint(
                check=models.Q(category__in=RUNTIME_CATEGORY_DB_VALUES),
                name='el_runtime_record_category_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'status']),
            models.Index(fields=['tenant_id', 'system', '-occurred_at', '-id']),
            models.Index(fields=['tenant_id', '-occurred_at', '-id']),
            models.Index(fields=['tenant_id', 'client_token']),
        ]

    def __repr__(self):
        return '<SystemRuntimeRecord %r>' % self.record_no

    def can_transition_to(self, new_status):
        return new_status in RUNTIME_RECORD_TRANSITIONS.get(self.status, set())

    def to_view(self):
        converted_fault = self.generated_faults.exclude(
            status=SystemFault.STATUS_CANCELLED).order_by('-id').first()
        data = {
            'id': self.id,
            'record_no': self.record_no,
            'system': self.system_id,
            'system_name': self.system_name,
            'system_code': self.system_code,
            'system_location': self.system_location,
            'occurred_at': self.occurred_at,
            'title': self.title,
            'registrar_name': self.registrar_name or '',
            'status': self.status,
            'status_text': self.STATUS_TEXT_MAP.get(self.status, self.status),
            'needs_follow_up': self.needs_follow_up,
            # —— 第二版：列表即可见的跟进信息 ——
            'category': self.category,
            'category_text': self.CATEGORY_TEXT_MAP.get(self.category, '') if self.category else '',
            'follow_up_name': self.follow_up_name,
            'planned_handle_at': self.planned_handle_at,
            'converted_fault': converted_fault.id if converted_fault else None,
            'converted_fault_no': converted_fault.fault_no if converted_fault else '',
            'created_by_name': self.created_by.username if self.created_by_id else '',
            'created_at': self.created_at,
        }
        return data

    def to_detail_view(self):
        data = self.to_view()
        data.update({
            'description': self.description,
            'measures_taken': self.measures_taken,
            'handling_result': self.handling_result,
            # —— 研判（第二版）——
            'triaged_at': self.triaged_at,
            'triaged_by_name': self.triaged_by_name,
            'triage_note': self.triage_note,
            # —— 跟进与待办（第二版）——
            'resolved_at': self.resolved_at,
            # —— 结构化补充字段（第二版）——
            'initial_reason': self.initial_reason,
            'impact_scope': self.impact_scope,
            'client_token': self.client_token,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        })
        return data


class SystemRuntimeRecordProgress(TenantModelMixin, models.Model):
    """运行异常记录处理进展：追加式时间线（第一版轻量模型）。

    - 追加式记录，普通用户不能静默覆盖：更正把原内容、新内容与更正原因
      追加保存到 corrections JSON 数组（[{old, new, reason, by, at}]），
      与故障处理进展（SystemFaultHandlingRecord）同一约定；
    - 处理人 handler_name 为手动输入姓名快照（实际处理的人可能无系统账号），
      handler 保留操作账号审计字段；历史/缺省展示回落 handler 用户名；
    - 已转故障的运行异常记录不允许继续追加普通处理进展（视图层校验）。
    """

    record = models.ForeignKey(
        SystemRuntimeRecord, models.CASCADE, related_name='progress_records',
        help_text='所属运行记录')
    handled_at = models.DateTimeField(help_text='处理时间')
    handler = models.ForeignKey(
        User, models.PROTECT, related_name='+',
        help_text='记录操作账号（审计字段；处理人姓名见 handler_name）')
    handler_name = models.CharField(
        max_length=200, default='', blank=True,
        help_text='处理人（手动输入的姓名，多人以顿号分隔；空串展示回落 handler 用户名）')
    content = models.TextField(max_length=2000, help_text='处理内容')
    result = models.CharField(max_length=200, default='', blank=True, help_text='处理结果（选填）')
    work_hours = models.FloatField(null=True, blank=True, help_text='本次工时（小时，选填）')
    corrections = models.TextField(default='', blank=True, help_text='更正历史 JSON 数组')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_runtime_record_progress'
        verbose_name = '运行记录处理进展'
        verbose_name_plural = '运行记录处理进展'
        ordering = ('handled_at', 'id')
        indexes = [
            models.Index(fields=['tenant_id', 'record', 'handled_at', 'id']),
        ]

    def __repr__(self):
        return '<SystemRuntimeRecordProgress record=%s at=%s>' % (
            self.record_id, self.handled_at)

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
            'record': self.record_id,
            'handled_at': self.handled_at,
            'handler': self.handler_id,
            'handler_name': self.handler_name or (
                self.handler.username if self.handler_id else ''),
            'content': self.content,
            'result': self.result,
            'work_hours': self.work_hours,
            'corrections': self.get_corrections(),
            'created_at': self.created_at,
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

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——系统主数据模型（步骤二）。

按《设备与系统全生命周期管理总体方案 v2.0》步骤二建设：

- LifecycleSystem          系统主数据（平级、无父子层级、无系统—设备关系）

已下线功能（2026-09 功能下线，迁移 0021/0023 删除）：
- SystemConfigComponent（配置组成项）、SystemConfigChange（配置变更历史）、
  SystemConfigSnapshot（配置快照）三表及故障/工单上的组成项外键已删除；
  故障/工单历史组成项名称以 fault_component_name / work_component_name
  文本快照保留，config_snapshot 类型履历事件仅存量兼容、不再新增；
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
HEALTH_STATUS_VALUES = ['normal', 'degraded', 'fault', 'repairing', 'interrupted', 'unknown']
FAULT_IMPACT_VALUES = ['degraded', 'fault', 'interrupted']
# 影响系统运行时的合法影响程度即 FAULT_IMPACT_VALUES；
# 不影响系统运行（部件故障/离线维修）时 impact_status 统一存空串
FAULT_IMPACT_DB_VALUES = [''] + FAULT_IMPACT_VALUES
FAULT_STATUS_VALUES = ['pending', 'handling', 'recovered', 'closed', 'cancelled']


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
    fault_component_name = models.CharField(max_length=100, default='', blank=True,
                                            help_text='配置组成项名称快照（组成项功能下线前历史数据，仅展示）')

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
    source_type = models.CharField(max_length=20, default=SOURCE_MANUAL, help_text='来源类型：manual 人工 / ledger_item 台账异常明细 / inspection_record 值班巡检明细（步骤 3.3）')
    source_id = models.CharField(max_length=50, default='', blank=True, help_text='来源对象 ID 冗余（与来源外键一致，便于追溯查询）')
    source_ledger_item = models.ForeignKey(
        'equipment_lifecycle.OperationLedgerItem', models.PROTECT,
        related_name='generated_faults', null=True, blank=True,
        help_text='来源台账异常明细（台账异常转故障时写入，真实外键保证可追溯）')
    source_inspection_record = models.ForeignKey(
        'equipment_lifecycle.InspectionRecord', models.PROTECT,
        related_name='generated_faults', null=True, blank=True,
        help_text='来源巡检异常明细（巡检异常转故障时写入，双向追溯）')
    # 旧巡检台账来源快照：来源明细物理删除后保留历史语义（来源类型仍为 ledger_item）
    source_ledger_legacy = models.TextField(
        default='', blank=True,
        help_text='旧巡检台账来源快照 JSON（台账号/类型/项目名/系统快照等；'
                  '来源明细随旧巡检台账受控删除后，据此展示历史来源，不做跳转）')

    created_by = models.ForeignKey(
        User, models.PROTECT, related_name='+',
        help_text='创建人（实际登录账号，仅用于审计）')
    # 故障登记人（2026-09）：手动输入的登记人姓名，只表示"谁登记"，
    # 不代表其负责后续跟进、不承担维修责任（跟进人/处置人仍是 handler）；
    # 不关联 User——实际登记人可能没有系统账号（共用登录账号场景），
    # 参照系统档案 responsible_user_name 的姓名快照口径。
    # 历史故障登记人为空（可空文本），新增时由视图层写入（缺省当前登录用户姓名）。
    registrar_name = models.CharField(
        max_length=200, default='', blank=True,
        help_text='故障登记人（手动输入的登记人姓名，多人以顿号分隔；'
                  '实际添加本条故障记录的人，不代表后续跟进与维修责任；'
                  '与登录账号 created_by 独立，历史数据可为空）')
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
            'level': self.level,
            'level_text': self.LEVEL_TEXT_MAP.get(self.level, self.level),
            'phenomenon': self.phenomenon,
            'status': self.status,
            'status_text': self.STATUS_TEXT_MAP.get(self.status, self.status),
            'handler': self.handler_id,
            'handler_name': self.handler.username if self.handler_id else '',
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
            'discovery': self.discovery,
            'discovery_text': self.DISCOVERY_TEXT_MAP.get(self.discovery, self.discovery),
            'impact_scope': self.impact_scope,
            'fault_location': self.fault_location,
            'fault_object_name': self.fault_object_name,
            'fault_object_model': self.fault_object_model,
            'fault_object_sn': self.fault_object_sn,
            'fault_component_name': self.fault_component_name or '',
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
            'updated_at': self.updated_at,
        })
        return data


class SystemFaultHandlingRecord(TenantModelMixin, models.Model):
    """故障处理进展记录（原"处置记录"，2026-09 统一改名）：追加式时间线，
    记录检查、临时措施、送厂、厂家反馈、返还、本方测试、持续观察等整体跟进，
    不把过程反复覆盖在一个文本字段中。

    - 已保存记录不得被普通用户静默覆盖：更正时把原内容、修改内容、更正原因
      追加保存到 corrections JSON 数组（[{old, new, reason, by, at}]）；
    - progress_type 为选填的结构化进展类型（空串=未选择，历史记录为空），
      故障恢复/关闭仍走原有状态流转，不依赖进展类型推断；
    - 附件使用项目现有 EvidenceAttachment 能力
      （module=equipment_lifecycle, object_type=el_fault_handling, object_id=记录ID）。
    """

    # 进展类型（2026-09：本方维修/送厂/仅测试/暂未修复等真实跟进阶段，
    # 结构化存储，选填；空串=未选择。历史记录类型为空，不通过文本解析反推类型）
    PROGRESS_CHECK = 'check'
    PROGRESS_SELF_FIX = 'self_fix'
    PROGRESS_TO_VENDOR = 'to_vendor'
    PROGRESS_VENDOR_FEEDBACK = 'vendor_feedback'
    PROGRESS_RETURN = 'return'
    PROGRESS_TEST = 'test'
    PROGRESS_WATCH = 'watch'
    PROGRESS_OTHER = 'other'
    PROGRESS_TYPE_CHOICES = (
        (PROGRESS_CHECK, '检查'),
        (PROGRESS_SELF_FIX, '本方处理'),
        (PROGRESS_TO_VENDOR, '送厂'),
        (PROGRESS_VENDOR_FEEDBACK, '厂家反馈'),
        (PROGRESS_RETURN, '返还'),
        (PROGRESS_TEST, '测试'),
        (PROGRESS_WATCH, '持续观察'),
        (PROGRESS_OTHER, '其他'),
    )
    PROGRESS_TYPE_TEXT_MAP = dict(PROGRESS_TYPE_CHOICES)

    fault = models.ForeignKey(SystemFault, models.CASCADE, related_name='handling_records',
                              help_text='所属故障')
    handled_at = models.DateTimeField(help_text='进展时间')
    # handler 保留为审计字段（记录操作登录账号，历史数据不变）；
    # 进展记录人为手动输入姓名（recorder_name，2026-09），不关联 User，
    # 历史记录无 recorder_name 时展示回落到 handler 的用户名
    handler = models.ForeignKey(
        User, models.PROTECT, related_name='+',
        help_text='记录操作账号（审计字段；进展记录人姓名见 recorder_name）')
    recorder_name = models.CharField(
        max_length=200, default='', blank=True,
        help_text='进展记录人（手动输入的记录人姓名，多人以顿号分隔；'
                  '实际添加本条进展的人，不代表负责整个故障；'
                  '空串=历史记录，展示回落 handler 用户名）')
    content = models.TextField(max_length=2000, help_text='进展内容')
    progress_type = models.CharField(
        max_length=20, choices=PROGRESS_TYPE_CHOICES, default='', blank=True,
        help_text='进展类型（选填：check检查/self_fix本方处理/to_vendor送厂/'
                  'vendor_feedback厂家反馈/return返还/test测试/watch持续观察/other其他；'
                  '空串=未选择，历史记录为空）')
    result = models.CharField(max_length=200, default='', blank=True, help_text='处理结果（选填）')
    corrections = models.TextField(default='', blank=True, help_text='更正历史 JSON 数组')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_fault_handling_record'
        verbose_name = '故障处理进展'
        verbose_name_plural = '故障处理进展'
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
            'progress_type': self.progress_type,
            'progress_type_text': self.PROGRESS_TYPE_TEXT_MAP.get(self.progress_type, ''),
            'content': self.content,
            'result': self.result,
            'corrections': self.get_corrections(),
            'created_at': self.created_at,
        }


# ======================================================================
# 步骤 3.2：周月维护 / 季维护台账
# ----------------------------------------------------------------------
# 结构：系统 → 检查项或维护项 → 台账明细 → 台账汇总表。
# 两类维护台账共用统一模型（OperationLedger/OperationLedgerItem），
# 通过 ledger_type + maintenance_cycle 区分，不为两类台账复制两套表。
# 旧巡检台账（ledger_type=inspection）业务分支已删除（2026-09-24）：
# 巡检由独立模型（InspectionTemplate/InspectionDutySheet/InspectionRecord）承担，
# 历史数据由 purge_legacy_inspection_ledgers 管理命令受控清理。
# 本步骤只记录异常，不转故障/工单，不修改系统健康状态（步骤 3.1 逻辑），
# 不建设计划提醒、系统履历与现场采集能力。
# ======================================================================

# 台账类型（旧巡检类型 inspection 已删除，仅保留常量供显式拒绝与历史数据清理识别）
LEGACY_LEDGER_TYPE_INSPECTION = 'inspection'  # 旧巡检（已下线，不再支持）
LEDGER_TYPE_WEEK_MONTH = 'week_month'    # 周月维护（周期字段区分周/月）
LEDGER_TYPE_SEASONAL = 'seasonal'        # 季维护（正式名称，不用"季度维护"）
LEDGER_TYPE_VALUES = ['week_month', 'seasonal']

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
LEDGER_CYCLE_TEXT = {CYCLE_WEEK: '周', CYCLE_MONTH: '月', CYCLE_SEASON: '季'}


def ledger_cycle_combo_q(ledger_type_field, cycle_field):
    """台账类型与维护周期的合法组合（台账表头与模板共用 DB 校验）：

    - 周月维护：必须为周或月；
    - 季维护：固定为季；
    - 旧巡检类型已删除，任何组合均不合法（迁移收窄 CHECK 前须先清理历史数据）。
    """
    return (
        models.Q(**{ledger_type_field: LEDGER_TYPE_WEEK_MONTH, cycle_field + '__in': [CYCLE_WEEK, CYCLE_MONTH]}) |
        models.Q(**{ledger_type_field: LEDGER_TYPE_SEASONAL, cycle_field: CYCLE_SEASON})
    )


class OperationLedgerTemplate(TenantModelMixin, models.Model):
    """运维台账模板：周月维护/季维护共用，ledger_type 决定用途。

    - 模板只决定以后生成的台账内容，修改不影响已生成台账（明细保存快照）；
    - 模板不绑定系统，适用于任何系统（录入时逐条目显式选择系统）；
    - 停用后不能用于新台账，历史记录继续可查；
    - 周期组合校验：周月维护 week|month / 季维护 season
      （旧巡检类型已删除，DB CHECK 收窄前须先清理历史数据）。
    """

    name = models.CharField(max_length=100, help_text='模板名称')
    ledger_type = models.CharField(max_length=20, help_text='台账类型')
    maintenance_cycle = models.CharField(
        max_length=20, default='', blank=True, help_text='周月维护周期（week/month/season；巡检为空）')
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
        return '<OperationLedgerTemplate %r>' % self.name

    def to_view(self, with_counts=False):
        data = {
            'id': self.id,
            'name': self.name,
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

    - 录入类型收敛为两种：正常/不正常(choice，候选项固定)与数字/文本(text，
      纯数字填写值同时落 value_number)；枚举中其余类型仅为历史数据兼容保留，
      新建项目不可再选；
    - 周月维护模板项目通过 execution_scope 区分 仅每周/仅每月/周月均执行，
      生成台账时只加载与本次维护周期匹配的项目；
    - 停用或删除项目不影响历史台账明细（明细保存全量快照）。
    """

    template = models.ForeignKey(
        OperationLedgerTemplate, models.CASCADE, related_name='items', help_text='所属模板')
    name = models.CharField(max_length=100, help_text='项目名称')
    input_type = models.CharField(max_length=20, help_text='录入类型')
    unit = models.CharField(max_length=20, default='', blank=True, help_text='单位')
    choices = models.TextField(default='', blank=True, help_text='候选项 JSON 数组（单选/多选）')
    default_value = models.CharField(max_length=200, default='', blank=True, help_text='默认值')
    is_required = models.BooleanField(default=True, help_text='是否必填')
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
        return '<OperationLedgerTemplateItem %r>' % self.name

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
            'name': self.name,
            'input_type': self.input_type,
            'unit': self.unit,
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
    maintenance_cycle = models.CharField(
        max_length=20, default='', blank=True, help_text='维护周期（week/month/season；巡检为空）')
    executed_date = models.DateField(help_text='实际执行日期')
    executor_names = models.CharField(max_length=200, default='', blank=True, help_text='执行人（多人以顿号或逗号分隔）')
    status = models.CharField(max_length=20, default=LEDGER_STATUS_DRAFT, help_text='台账状态')
    executed_start = models.DateTimeField(null=True, blank=True, help_text='实际执行开始时间')
    executed_end = models.DateTimeField(null=True, blank=True, help_text='实际执行结束时间')
    entry_channel = models.CharField(max_length=20, default=ENTRY_CHANNEL_WEB, help_text='录入渠道（当前固定 web）')
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
    item_name_snapshot = models.CharField(max_length=100, help_text='检查或维护项目名称快照')
    input_type = models.CharField(max_length=20, help_text='录入类型快照')
    unit_snapshot = models.CharField(max_length=20, default='', blank=True, help_text='单位快照')
    choices_snapshot = models.TextField(default='', blank=True, help_text='候选项快照 JSON 数组')
    is_required = models.BooleanField(default=False, help_text='必填规则快照')
    abnormal_rule_snapshot = models.CharField(max_length=200, default='', blank=True, help_text='异常判定规则快照')
    execution_scope = models.CharField(max_length=20, default=EXEC_SCOPE_ALL, help_text='执行范围快照')
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
            'item_name': self.item_name_snapshot,
            'input_type': self.input_type,
            'unit': self.unit_snapshot,
            'choices': self.get_choices(),
            'is_required': self.is_required,
            'abnormal_rule': self.abnormal_rule_snapshot,
            'execution_scope': self.execution_scope,
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
# 单账号协同流程（2026-09）：新工单创建即执行中，不再有派发/接单/复核环节；
# pending_dispatch / pending_accept / pending_review 仅为历史数据兼容保留
# （迁移 0033 已将 pending_dispatch/pending_accept 归入 executing，
# pending_review 由人工迁移命令处理，不自动完成）。
WORK_ORDER_STATUS_PENDING_DISPATCH = 'pending_dispatch'  # 待派发（历史）
WORK_ORDER_STATUS_PENDING_ACCEPT = 'pending_accept'      # 待接单（历史）
WORK_ORDER_STATUS_EXECUTING = 'executing'                # 执行中
WORK_ORDER_STATUS_PENDING_REVIEW = 'pending_review'      # 待复核（历史）
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
WORK_ORDER_SOURCE_INSPECTION_RECORD = 'inspection_record'
WORK_ORDER_SOURCE_VALUES = [
    WORK_ORDER_SOURCE_MANUAL, WORK_ORDER_SOURCE_FAULT, WORK_ORDER_SOURCE_LEDGER_ITEM,
    WORK_ORDER_SOURCE_INSPECTION_RECORD,
]

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
    - 历史作业组成项名称以 work_component_name 文本快照保留
      （配置组成项功能已下线，新工单不再写入）；
    - 来源：manual 人工创建 / fault 来源故障 / ledger_item 来源台账异常明细，
      来源一律用真实外键（PROTECT），不保存自由文本冒充来源。
    一次实际工作涉及多个独立系统时分别建立工单，不允许一单关联多系统。

    状态流转（后端校验，动作接口触发，单账号协同流程）：
    创建即执行中（创建时自动记录实际开始时间）→(complete)→ 已完成
      →(close)→ 已关闭；
    执行中 →(cancel, del 权限)→ 已取消；
    已关闭/已取消为终态，不参与健康状态计算；
    pending_dispatch / pending_accept / pending_review 为历史兼容状态，
    仅供历史数据展示与受控取消，不再产生新工单。
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

    # 允许的状态流转（后端强制校验；历史状态仅保留受控取消出口）
    STATE_TRANSITIONS = {
        STATUS_PENDING_DISPATCH: {STATUS_CANCELLED},
        STATUS_PENDING_ACCEPT: {STATUS_CANCELLED},
        STATUS_EXECUTING: {STATUS_COMPLETED, STATUS_CANCELLED},
        STATUS_PENDING_REVIEW: {STATUS_CANCELLED},
        STATUS_COMPLETED: {STATUS_CLOSED},
        STATUS_CLOSED: set(),
        STATUS_CANCELLED: set(),
    }
    # 允许普通编辑的状态（执行中可修正基础信息；待派发为历史兼容）
    EDITABLE_STATUSES = {STATUS_PENDING_DISPATCH, STATUS_EXECUTING}
    # 允许受控取消的状态（含历史兼容状态）
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
    SOURCE_INSPECTION_RECORD = WORK_ORDER_SOURCE_INSPECTION_RECORD
    SOURCE_CHOICES = (
        (SOURCE_MANUAL, '人工创建'),
        (SOURCE_FAULT, '来源故障'),
        (SOURCE_LEDGER_ITEM, '来源台账异常'),
        (SOURCE_INSPECTION_RECORD, '来源值班巡检'),
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
    source_inspection_record = models.ForeignKey(
        'equipment_lifecycle.InspectionRecord', models.PROTECT,
        related_name='generated_work_orders', null=True, blank=True,
        help_text='来源巡检异常明细（source_type=inspection_record 时必填，双向追溯）')
    # 旧巡检台账来源快照：来源明细物理删除后保留历史语义（来源类型仍为 ledger_item）
    source_ledger_legacy = models.TextField(
        default='', blank=True,
        help_text='旧巡检台账来源快照 JSON（台账号/类型/项目名/系统快照等；'
                  '来源明细随旧巡检台账受控删除后，据此展示历史来源，不做跳转）')
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
    work_component_name = models.CharField(max_length=100, default='', blank=True,
                                           help_text='配置组成项名称快照（组成项功能下线前历史数据，仅展示）')

    owner = models.ForeignKey(User, models.PROTECT, related_name='owned_work_orders',
                              null=True, blank=True,
                              help_text='负责人（历史流程字段，新流程不再写入；历史工单保留展示）')
    dispatched_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                      help_text='派发人（历史流程字段，新流程不再写入）')
    dispatched_at = models.DateTimeField(null=True, blank=True,
                                         help_text='派发时间（历史流程字段，新流程不再写入）')
    accepted_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                    help_text='接单人（历史流程字段，新流程不再写入）')
    accepted_at = models.DateTimeField(null=True, blank=True,
                                       help_text='接单时间（历史流程字段，新流程不再写入）')

    planned_start = models.DateTimeField(null=True, blank=True, help_text='计划开始时间')
    planned_end = models.DateTimeField(null=True, blank=True, help_text='计划结束时间')
    actual_start = models.DateTimeField(null=True, blank=True,
                                        help_text='实际开始时间（创建工单时自动记录；历史工单为开始执行时间）')
    actual_end = models.DateTimeField(null=True, blank=True,
                                      help_text='实际完成时间（完成工单时记录）')

    work_requirement = models.TextField(max_length=2000, default='', blank=True, help_text='作业要求')
    work_steps = models.TextField(max_length=2000, default='', blank=True, help_text='作业步骤')
    process_result = models.TextField(max_length=2000, default='', blank=True,
                                      help_text='处理结果（提交复核前必填）')
    work_hours = models.FloatField(null=True, blank=True, help_text='工时（小时）')
    interrupt_hours = models.FloatField(null=True, blank=True, help_text='系统中断时间（小时）')
    material_note = models.TextField(max_length=500, default='', blank=True,
                                     help_text='材料说明（名称/型号/数量/单位/说明/可选外部库存编号）')

    completed_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                     help_text='完成操作账号（完成工单动作的实际登录账号，历史工单可为空）')
    completed_at = models.DateTimeField(null=True, blank=True,
                                        help_text='完成操作时间（完成工单动作发生时间）')
    reviewer = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                 help_text='复核人（历史流程字段，新流程不再写入）')
    reviewed_at = models.DateTimeField(null=True, blank=True,
                                       help_text='复核时间（历史流程字段，新流程不再写入）')
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
                              default=STATUS_EXECUTING, help_text='当前状态（新工单创建即执行中）')
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
            # 来源类型与来源对象必须匹配：manual 两者皆空，fault/ledger_item/inspection_record
            # 只允许对应外键；ledger_item 来源在外键已解除且 legacy 快照在位时仍合法
            # （旧巡检台账明细受控删除后的迁移态，2026-09-24）
            models.CheckConstraint(
                check=(
                    (models.Q(source_type=WORK_ORDER_SOURCE_MANUAL)
                     & models.Q(source_fault__isnull=True)
                     & models.Q(source_ledger_item__isnull=True)
                     & models.Q(source_inspection_record__isnull=True))
                    | (models.Q(source_type=WORK_ORDER_SOURCE_FAULT)
                       & models.Q(source_fault__isnull=False)
                       & models.Q(source_ledger_item__isnull=True)
                       & models.Q(source_inspection_record__isnull=True))
                    | (models.Q(source_type=WORK_ORDER_SOURCE_LEDGER_ITEM)
                       & models.Q(source_fault__isnull=True)
                       & models.Q(source_inspection_record__isnull=True)
                       & (models.Q(source_ledger_item__isnull=False)
                          | (models.Q(source_ledger_item__isnull=True)
                             & ~models.Q(source_ledger_legacy=''))))
                    | (models.Q(source_type=WORK_ORDER_SOURCE_INSPECTION_RECORD)
                       & models.Q(source_fault__isnull=True)
                       & models.Q(source_ledger_item__isnull=True)
                       & models.Q(source_inspection_record__isnull=False))
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
            models.Index(fields=['tenant_id', 'source_inspection_record']),
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
        """详情：全字段 + 参与人 + 来源追溯信息（单系统简化，无受影响系统）。"""
        data = self.to_view()
        data.update({
            'system_location': self.system_location,
            'work_location': self.work_location,
            'work_object_desc': self.work_object_desc,
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
            'completed_by': self.completed_by_id,
            'completed_by_name': self.completed_by.username if self.completed_by_id else '',
            'completed_at': self.completed_at,
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
            # 台账来源追溯：旧巡检明细删除后回落 legacy 快照（仅展示不做跳转）
            'source_ledger_item': self.source_ledger_item_id,
            'source_ledger': self.source_ledger_item.ledger_id if self.source_ledger_item_id else None,
            'source_ledger_type': self._source_ledger_field('ledger_type'),
            'source_ledger_no': self._source_ledger_field('ledger_no'),
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
      追加保存到 corrections JSON 数组（与故障处理进展同一模式）；
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
# upgrade：系统升级管理挂接系统档案（2026-09），升级登记/完成/回退写入履历
# inspection：值班巡检异常转故障/工单（2026-09），转换动作落目标系统履历
EVENT_TYPE_VALUES = ['fault', 'work_order', 'ledger', 'health', 'config_snapshot', 'upgrade', 'inspection']
EVENT_SOURCE_TYPE_VALUES = [
    'fault', 'work_order', 'ledger_item', 'health', 'config_snapshot', 'upgrade',
    'inspection_record',
]
EVENT_ACTION_VALUES = [
    'create', 'recover', 'close', 'cancel',
    'convert_to_fault', 'convert_to_work_order',
    'complete', 'status_change', 'snapshot',
    'rollback',
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
    EVENT_UPGRADE = 'upgrade'
    EVENT_INSPECTION = 'inspection'
    EVENT_TYPE_CHOICES = (
        (EVENT_FAULT, '故障'),
        (EVENT_WORK_ORDER, '工单'),
        (EVENT_LEDGER, '台账异常'),
        (EVENT_HEALTH, '健康状态'),
        (EVENT_CONFIG_SNAPSHOT, '配置快照'),
        (EVENT_UPGRADE, '系统升级'),
        (EVENT_INSPECTION, '值班巡检'),
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


# ======================================================================
# 值班巡检（今日巡检改造，2026-09）：独立的巡检模板与值班巡检单模型
# ----------------------------------------------------------------------
# 今日巡检不再按系统拆分、不关联 LifecycleSystem：
# - 巡检单唯一范围 = 值班日 + 巡检模板（值班人员登记在单上，支持多人+姓名快照）；
# - 每个值班日固定四轮：当日 11:00 / 16:00 / 22:00、次日 06:30
#   （第四轮发生在下一自然日，仍归属前一天的值班日）；
# - 不记录实际填写时间作为巡检业务字段（created_at/updated_at 仅为系统审计，
#   不作巡检执行时间展示、不参与业务判断、不判断迟填）；
# - 模板结构 = 巡检模板 → 设备名称 → 检查内容（设备名称不关联任何系统）；
# - 巡检明细保存全量快照，模板后续修改/停用不影响历史巡检记录；
# - 异常明细转故障/工单时才由用户选择系统（不允许由设备名称推断系统）；
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
    (INSPECTION_ROUND_1, '当日 11:00'),
    (INSPECTION_ROUND_2, '当日 16:00'),
    (INSPECTION_ROUND_3, '当日 22:00'),
    (INSPECTION_ROUND_4, '次日 06:30'),
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
    巡检异常转故障/工单时由用户显式选择系统。
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
    - 不关联 LifecycleSystem：异常转故障/工单时才由用户选择系统。
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

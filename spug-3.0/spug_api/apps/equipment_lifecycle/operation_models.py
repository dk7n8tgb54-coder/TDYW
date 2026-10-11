# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——运行与故障记录统一模型（2026-10-11 合并改造）。

将原"故障处置"（SystemFault/SystemFaultHandlingRecord）与"运行记录"
（SystemRuntimeRecord/SystemRuntimeRecordProgress）合并为一张统一主表 +
一张统一进展表；原"系统履历"（SystemEvent）同步退役（模型、写入与查询
整体删除，系统档案直接查询各业务表）。

统一记录类型（record_type，创建后除"异常事件认定故障"外不可修改）：
- routine   日常运行：常规作业留痕，创建后恒为"已记录"，允许补充进展，
  不进入故障状态机，不影响系统健康状态；
- abnormal  异常事件：临时异常或尚未认定为正式故障的问题，
  已记录 → 跟进中 → 已完成；允许在原记录上认定为正式故障；
- fault     正式故障：直接登记或由异常事件认定，处置中 →（确认恢复并结案）
  已关闭，错误/重复登记可填写原因受控撤销（已撤销）。

健康状态：只有 正式故障 + 处置中（有效未关闭）+ 明确影响系统运行 的记录
参与系统健康状态计算（operation_services 统一重算）。

约束：
- 继承 TenantModelMixin，租户隔离；CharField/TextField 禁止 null=True；
- 统一编号 record_no（JL+日期+当日四位序号）不可变，不再分别维护
  运行记录号（YX）与故障号（GZ）；
- 旧四表（tdyw_el_fault/tdyw_el_fault_handling_record/
  tdyw_el_runtime_record/tdyw_el_runtime_record_progress）与
  tdyw_el_system_event 由迁移 0013 受控删除，历史数据不保留、不建兼容层。
"""
import json

from django.db import models

from apps.account.models import User
from libs.tenant_base_model import TenantModelManager, TenantModelMixin, make_tenant_id

from apps.equipment_lifecycle.models import LifecycleSystem

# 复用系统档案模块的影响程度枚举（健康状态计算口径不变）：
# 影响系统运行时必填（degraded降级/fault故障/interrupted中断）；
# 不影响系统运行时 impact_status 强制存空串
FAULT_IMPACT_VALUES = ['degraded', 'fault', 'interrupted']
FAULT_IMPACT_DB_VALUES = [''] + FAULT_IMPACT_VALUES
FAULT_IMPACT_TEXT_MAP = {
    'degraded': '降级',
    'fault': '故障',
    'interrupted': '中断',
}

# 统一记录类型
RECORD_TYPE_ROUTINE = 'routine'
RECORD_TYPE_ABNORMAL = 'abnormal'
RECORD_TYPE_FAULT = 'fault'
RECORD_TYPE_VALUES = [RECORD_TYPE_ROUTINE, RECORD_TYPE_ABNORMAL, RECORD_TYPE_FAULT]
RECORD_TYPE_CHOICES = (
    (RECORD_TYPE_ROUTINE, '日常运行'),
    (RECORD_TYPE_ABNORMAL, '异常事件'),
    (RECORD_TYPE_FAULT, '正式故障'),
)
RECORD_TYPE_TEXT_MAP = dict(RECORD_TYPE_CHOICES)

# 统一状态（三类型各有合法子集，DB CHECK 强制 record_type 与 status 匹配）
RECORD_STATUS_RECORDED = 'recorded'            # 已记录（日常运行/异常事件）
RECORD_STATUS_FOLLOWING_UP = 'following_up'    # 跟进中（异常事件）
RECORD_STATUS_COMPLETED = 'completed'          # 已完成（异常事件）
RECORD_STATUS_HANDLING = 'handling'            # 处置中（正式故障）
RECORD_STATUS_CLOSED = 'closed'                # 已关闭（正式故障终态）
RECORD_STATUS_CANCELLED = 'cancelled'          # 已撤销（正式故障终态，登记不再有效）
RECORD_STATUS_VALUES = [
    RECORD_STATUS_RECORDED, RECORD_STATUS_FOLLOWING_UP, RECORD_STATUS_COMPLETED,
    RECORD_STATUS_HANDLING, RECORD_STATUS_CLOSED, RECORD_STATUS_CANCELLED,
]
RECORD_STATUS_CHOICES = (
    (RECORD_STATUS_RECORDED, '已记录'),
    (RECORD_STATUS_FOLLOWING_UP, '跟进中'),
    (RECORD_STATUS_COMPLETED, '已完成'),
    (RECORD_STATUS_HANDLING, '处置中'),
    (RECORD_STATUS_CLOSED, '已关闭'),
    (RECORD_STATUS_CANCELLED, '已撤销'),
)
RECORD_STATUS_TEXT_MAP = dict(RECORD_STATUS_CHOICES)

# 状态机（服务层动作接口校验；普通编辑不允许改状态）：
# - routine：恒为 recorded，不发生流转；
# - abnormal：recorded →(首条进展) following_up →(完成跟进) completed，
#   completed 追加进展即重新跟进（→ following_up）；
#   recorded/following_up 可认定故障（类型变更为 fault，状态进入 handling）；
# - fault：handling →(确认恢复并结案) closed；handling →(撤销登记) cancelled。
RECORD_STATUS_TRANSITIONS = {
    RECORD_STATUS_RECORDED: {RECORD_STATUS_FOLLOWING_UP, RECORD_STATUS_HANDLING},
    RECORD_STATUS_FOLLOWING_UP: {RECORD_STATUS_COMPLETED, RECORD_STATUS_HANDLING},
    RECORD_STATUS_COMPLETED: {RECORD_STATUS_FOLLOWING_UP},
    RECORD_STATUS_HANDLING: {RECORD_STATUS_CLOSED, RECORD_STATUS_CANCELLED},
    RECORD_STATUS_CLOSED: set(),
    RECORD_STATUS_CANCELLED: set(),
}

# 各类型允许普通编辑/追加进展/上传附件的状态
# - routine/abnormal 没有终态（已记录/已完成均可补充）；
# - fault 仅处置中可编辑与追加进展（已关闭/已撤销封闭）。
ROUTINE_EDITABLE_STATUSES = (RECORD_STATUS_RECORDED,)
ABNORMAL_EDITABLE_STATUSES = (
    RECORD_STATUS_RECORDED, RECORD_STATUS_FOLLOWING_UP, RECORD_STATUS_COMPLETED,
)
FAULT_EDITABLE_STATUSES = (RECORD_STATUS_HANDLING,)

# 来源类型：manual 人工登记；ledger_item 维护台账异常明细转故障。
# 已退役来源不保留：runtime_record（原"运行记录转故障"已改为原记录认定，
# 不再产生第二张单）、inspection_record（日巡视已下线且故障旧表删除）。
SOURCE_MANUAL = 'manual'
SOURCE_LEDGER_ITEM = 'ledger_item'
SOURCE_TYPE_VALUES = [SOURCE_MANUAL, SOURCE_LEDGER_ITEM]

# 异常类别（选填，空串=未选择；仅用于筛选与统计归类）
RECORD_CATEGORY_DEVICE = 'device'
RECORD_CATEGORY_SIGNAL = 'signal'
RECORD_CATEGORY_LINK = 'link'
RECORD_CATEGORY_POWER = 'power'
RECORD_CATEGORY_ENVIRONMENT = 'environment'
RECORD_CATEGORY_SOFTWARE = 'software'
RECORD_CATEGORY_OTHER = 'other'
RECORD_CATEGORY_VALUES = [
    RECORD_CATEGORY_DEVICE, RECORD_CATEGORY_SIGNAL, RECORD_CATEGORY_LINK,
    RECORD_CATEGORY_POWER, RECORD_CATEGORY_ENVIRONMENT,
    RECORD_CATEGORY_SOFTWARE, RECORD_CATEGORY_OTHER,
]
RECORD_CATEGORY_DB_VALUES = [''] + RECORD_CATEGORY_VALUES
RECORD_CATEGORY_CHOICES = (
    (RECORD_CATEGORY_DEVICE, '设备异常'),
    (RECORD_CATEGORY_SIGNAL, '信号异常'),
    (RECORD_CATEGORY_LINK, '链路传输'),
    (RECORD_CATEGORY_POWER, '供电异常'),
    (RECORD_CATEGORY_ENVIRONMENT, '机房环境'),
    (RECORD_CATEGORY_SOFTWARE, '软件/数据'),
    (RECORD_CATEGORY_OTHER, '其他'),
)
RECORD_CATEGORY_TEXT_MAP = dict(RECORD_CATEGORY_CHOICES)

# 编号前缀 JL{yyyymmdd}-{seq:04d}（当日序号全租户共享，口径沿用原故障/运行记录编号）
RECORD_NO_PREFIX = 'JL'
RECORD_NO_SEQ_LIMIT = 9999

# 附件归属标识（复用 EvidenceAttachment 体系，不新建文件存储）：
# 主记录级 el_operation_record / 统一进展级 el_operation_progress
OPERATION_ATTACHMENT_OBJECT_TYPE = 'el_operation_record'
PROGRESS_ATTACHMENT_OBJECT_TYPE = 'el_operation_progress'


class SystemOperationRecord(TenantModelMixin, models.Model):
    """运行与故障记录统一主表（2026-10-11 合并故障处置与运行记录）。

    - 新建只要求 系统/发生时间/标题/情况描述/登记人，其余选填或默认值；
      正式故障可径直创建（add_fault 权限），异常事件可在原记录上认定为
      正式故障（identify-fault 动作：更新同一条主记录的类型与状态，
      保留原描述、登记人、附件与全部进展，不创建第二张单）；
    - 系统快照（编号/名称/安装地点）仅用于历史展示，正式关联一律用
      system 外键（PROTECT）；切换系统由编辑动作完成并重算健康状态；
    - 故障专用字段（影响系统运行/影响程度/原因分析/原因未明/恢复信息/
      结案说明）仅正式故障使用，日常运行与异常事件恒为默认值；
    - 取消语义：cancel_reason/cancelled_at/cancelled_by 为撤销留痕，
      仅正式故障可撤销，历史记录保留可追溯（不物理删除）；
    - 来源信息：台账异常转故障写入 source_ledger_item 正式外键 +
      source_type/source_id 冗余，双向可追溯；
    - resolved_at 为异常事件首次完成跟进时间（统计平均处理时长用，
      重新跟进后再次完成不覆盖）；
    - 状态与影响设置的合法性由 DB CHECK 强制（类型-状态匹配、
      影响开关-影响程度匹配），业务流转由服务层状态机校验。
    """

    record_no = models.CharField(max_length=50, help_text='统一记录编号（JL+创建日期+当日四位序号，自动生成、不可变；当日序号全租户共享）')
    record_type = models.CharField(
        max_length=20, choices=RECORD_TYPE_CHOICES,
        help_text='记录类型（routine日常运行/abnormal异常事件/fault正式故障；'
                  '异常事件认定故障后原地变更为 fault，其余场景创建后不可修改）')
    system = models.ForeignKey(
        LifecycleSystem, models.PROTECT, related_name='operation_records',
        help_text='所属系统（正式系统 ID 外键，一条记录只关联一个系统）')
    # —— 系统快照（创建时点，仅历史展示） ——
    system_code = models.CharField(max_length=50, help_text='系统编号快照')
    system_name = models.CharField(max_length=100, help_text='系统名称快照')
    system_location = models.CharField(max_length=200, help_text='系统安装地点快照')

    occurred_at = models.DateTimeField(help_text='发生时间')
    title = models.CharField(max_length=200, help_text='标题')
    description = models.TextField(max_length=2000, help_text='情况描述（正式故障时即故障现象）')
    registrar_name = models.CharField(
        max_length=200, default='', blank=True,
        help_text='登记人（手动输入的登记人姓名，多人以顿号分隔；'
                  '实际添加本条记录的人，与登录账号 created_by 独立）')

    status = models.CharField(max_length=20, choices=RECORD_STATUS_CHOICES,
                              help_text='当前状态（类型与状态的合法组合由 DB CHECK 强制）')

    # —— 异常事件补充字段（选填） ——
    category = models.CharField(
        max_length=20, choices=RECORD_CATEGORY_CHOICES, default='', blank=True,
        help_text='异常类别（选填：device设备异常/signal信号异常/link链路传输/'
                  'power供电异常/environment机房环境/software软件数据/other其他；空串=未选择）')

    # —— 正式故障专用字段 ——
    fault_object_name = models.CharField(max_length=100, default='', blank=True,
                                         help_text='具体故障对象名称快照（正式故障）')
    fault_object_model = models.CharField(max_length=100, default='', blank=True,
                                          help_text='具体故障对象型号快照（正式故障）')
    fault_object_sn = models.CharField(max_length=100, default='', blank=True,
                                       help_text='具体故障对象编号/序列号快照（正式故障）')
    affects_system_operation = models.BooleanField(
        default=False,
        help_text='是否影响系统运行（False=部件故障/离线维修，默认不影响，不参与健康状态计算；'
                  'True=影响运行，按 impact_status 参与健康状态计算）')
    impact_status = models.CharField(
        max_length=20, default='', blank=True,
        help_text='系统影响程度：影响系统运行时必填（degraded降级/fault故障/interrupted中断）；'
                  '不影响系统运行时强制存空串')
    # 原因分析是单一字段，不同阶段只是展示口径不同：登记=初步原因分析、
    # 处置中=初步判断、结案=最终原因；"原因未明"不是第二个原因字段，
    # 勾选后 reason_analysis 保存的是未明说明（不强迫用户填写虚假原因）
    reason_analysis = models.TextField(
        max_length=2000, default='', blank=True,
        help_text='原因分析（正式故障；新增=初步原因分析，处置中=初步判断，结案=最终原因；'
                  '原因未明时保存未明说明）')
    reason_unknown = models.BooleanField(
        default=False,
        help_text='原因未明标记（确实无法确定原因时为 True，reason_analysis 保存未明说明）')
    recovered_at = models.DateTimeField(null=True, blank=True, help_text='恢复时间（正式故障结案时写入）')
    recovered_confirmed_at = models.DateTimeField(null=True, blank=True, help_text='恢复确认时间（结案操作写入）')
    recovered_by_name = models.CharField(
        max_length=200, default='', blank=True,
        help_text='恢复确认人（手动输入的确认人姓名，多人以顿号分隔；不关联 User）')
    recovery_close_note = models.TextField(
        max_length=3000, default='', blank=True,
        help_text='结案说明（采取的处理措施、恢复验证依据及最终处理结果）')
    cancel_reason = models.CharField(
        max_length=200, default='', blank=True,
        help_text='撤销原因（撤销错误/重复的故障登记时必填）')
    cancelled_at = models.DateTimeField(null=True, blank=True, help_text='撤销时间（撤销登记操作写入）')
    cancelled_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True,
        help_text='撤销人（执行撤销登记的登录账号，仅用于审计与展示）')

    # —— 来源信息 ——
    source_type = models.CharField(
        max_length=20, default=SOURCE_MANUAL,
        help_text='来源类型：manual 人工 / ledger_item 维护台账异常明细转故障')
    source_id = models.CharField(
        max_length=50, default='', blank=True,
        help_text='来源对象 ID 冗余（与来源外键一致，便于追溯查询）')
    source_ledger_item = models.ForeignKey(
        'equipment_lifecycle.OperationLedgerItem', models.PROTECT,
        related_name='generated_records', null=True, blank=True,
        help_text='来源台账异常明细（台账异常转故障时写入，真实外键保证可追溯）')

    # —— 跟进与统计 ——
    resolved_at = models.DateTimeField(
        null=True, blank=True,
        help_text='首次完成跟进时间（异常事件；统计平均处理时长用，不随重新跟进/再次完成覆盖）')
    client_token = models.CharField(
        max_length=64, default='', blank=True, help_text='客户端幂等令牌（创建防重复）')

    created_by = models.ForeignKey(User, models.PROTECT, related_name='+', help_text='创建人（实际登录账号，仅用于审计）')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_operation_record'
        verbose_name = '运行与故障记录'
        verbose_name_plural = '运行与故障记录'
        ordering = ('-occurred_at', '-id')
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'record_no'], name='uniq_el_operation_record_tenant_no'),
            models.CheckConstraint(
                check=models.Q(record_type__in=RECORD_TYPE_VALUES),
                name='el_operation_record_type_valid'),
            models.CheckConstraint(
                check=models.Q(status__in=RECORD_STATUS_VALUES),
                name='el_operation_record_status_valid'),
            models.CheckConstraint(
                check=models.Q(category__in=RECORD_CATEGORY_DB_VALUES),
                name='el_operation_record_category_valid'),
            models.CheckConstraint(
                check=models.Q(source_type__in=SOURCE_TYPE_VALUES),
                name='el_operation_record_source_valid'),
            models.CheckConstraint(
                check=models.Q(impact_status__in=FAULT_IMPACT_DB_VALUES),
                name='el_operation_record_impact_valid'),
            # 记录类型与状态匹配（服务层状态机之外的数据库兜底）
            models.CheckConstraint(
                check=(
                    models.Q(record_type=RECORD_TYPE_ROUTINE, status=RECORD_STATUS_RECORDED) |
                    models.Q(record_type=RECORD_TYPE_ABNORMAL,
                             status__in=[RECORD_STATUS_RECORDED, RECORD_STATUS_FOLLOWING_UP,
                                         RECORD_STATUS_COMPLETED]) |
                    models.Q(record_type=RECORD_TYPE_FAULT,
                             status__in=[RECORD_STATUS_HANDLING, RECORD_STATUS_CLOSED,
                                         RECORD_STATUS_CANCELLED])
                ),
                name='el_operation_record_type_status_match'),
            # 影响开关与影响程度匹配：不影响运行 ⇒ 程度为空；影响运行 ⇒ 程度必填
            models.CheckConstraint(
                check=(
                    models.Q(affects_system_operation=False, impact_status='') |
                    models.Q(affects_system_operation=True,
                             impact_status__in=FAULT_IMPACT_VALUES)
                ),
                name='el_operation_record_affect_impact_match'),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'status']),
            models.Index(fields=['tenant_id', 'record_type', '-occurred_at', '-id'],
                         name='el_operation_type_occ_idx'),
            models.Index(fields=['tenant_id', 'system', '-occurred_at', '-id']),
            models.Index(fields=['tenant_id', '-occurred_at', '-id']),
            models.Index(fields=['tenant_id', 'client_token']),
        ]

    def __repr__(self):
        return '<SystemOperationRecord %r>' % self.record_no

    @property
    def editable_statuses(self):
        """当前记录类型允许普通编辑/追加进展/上传附件的状态集合。"""
        if self.record_type == RECORD_TYPE_ROUTINE:
            return ROUTINE_EDITABLE_STATUSES
        if self.record_type == RECORD_TYPE_ABNORMAL:
            return ABNORMAL_EDITABLE_STATUSES
        return FAULT_EDITABLE_STATUSES

    @property
    def is_fault(self):
        return self.record_type == RECORD_TYPE_FAULT

    def can_transition_to(self, new_status):
        return new_status in RECORD_STATUS_TRANSITIONS.get(self.status, set())

    def to_view(self):
        """列表行摘要。"""
        return {
            'id': self.id,
            'record_no': self.record_no,
            'record_type': self.record_type,
            'record_type_text': RECORD_TYPE_TEXT_MAP.get(self.record_type, self.record_type),
            'system': self.system_id,
            'system_name': self.system_name,
            'system_code': self.system_code,
            'system_location': self.system_location,
            'occurred_at': self.occurred_at,
            'title': self.title,
            'description': self.description,
            'category': self.category,
            'category_text': RECORD_CATEGORY_TEXT_MAP.get(self.category, '') if self.category else '',
            'status': self.status,
            'status_text': RECORD_STATUS_TEXT_MAP.get(self.status, self.status),
            'affects_system_operation': self.affects_system_operation,
            'impact_status': self.impact_status,
            'impact_status_text': FAULT_IMPACT_TEXT_MAP.get(self.impact_status, '') if self.impact_status else '',
            'registrar_name': self.registrar_name or '',
            'created_by_name': self.created_by.username if self.created_by_id else '',
            'created_at': self.created_at,
        }

    def to_detail_view(self):
        """详情：全字段。"""
        data = self.to_view()
        data.update({
            'fault_object_name': self.fault_object_name,
            'fault_object_model': self.fault_object_model,
            'fault_object_sn': self.fault_object_sn,
            'reason_analysis': self.reason_analysis,
            'reason_unknown': self.reason_unknown,
            'recovered_at': self.recovered_at,
            'recovered_confirmed_at': self.recovered_confirmed_at,
            'recovered_by_name': self.recovered_by_name or '',
            'recovery_close_note': self.recovery_close_note,
            'cancel_reason': self.cancel_reason or '',
            'cancelled_at': self.cancelled_at,
            'cancelled_by_name': self.cancelled_by.username if self.cancelled_by_id else '',
            'resolved_at': self.resolved_at,
            'source_type': self.source_type,
            'source_id': self.source_id,
            # 台账来源追溯：跳回来源台账明细所需定位信息
            'source_ledger_item': self.source_ledger_item_id,
            'source_ledger': (
                self.source_ledger_item.ledger_id if self.source_ledger_item_id else None),
            'source_ledger_no': (
                self.source_ledger_item.ledger.ledger_no
                if self.source_ledger_item_id else ''),
            'source_ledger_type': (
                self.source_ledger_item.ledger.ledger_type
                if self.source_ledger_item_id else ''),
            'source_ledger_item_name': (
                self.source_ledger_item.item_name_snapshot
                if self.source_ledger_item_id else ''),
            'client_token': self.client_token,
            'updated_at': self.updated_at,
        })
        return data


class SystemOperationProgress(TenantModelMixin, models.Model):
    """统一处理进展：追加式时间线（合并原故障处置记录与运行记录处理进展）。

    - 三种记录类型共用本表：日常运行允许补充进展（不改变状态），
      异常事件首条进展即进入跟进中、已完成追加进展即重新跟进，
      正式故障仅处置中可追加（已关闭/已撤销封闭，视图层校验）；
    - 处理人 handler_name 为手动输入姓名快照（实际处理的人可能无系统账号），
      handler 保留操作账号审计字段；历史/缺省展示回落 handler 用户名；
    - 工时选填（小时）；厂家送修、厂家反馈、外委处理等暂以进展内容记录，
      不设进展分类前置，也不建设厂家维修模块；
    - 已保存进展不得被普通用户静默覆盖：更正时把原内容、修改内容、更正原因
      追加保存到 corrections JSON 数组（[{old, new, reason, by, at}]）；
    - 附件使用 EvidenceAttachment（module=equipment_lifecycle,
      object_type=el_operation_progress, object_id=进展ID）。
    """

    record = models.ForeignKey(
        SystemOperationRecord, models.CASCADE, related_name='progress_records',
        help_text='所属统一记录')
    handled_at = models.DateTimeField(help_text='处理时间')
    handler = models.ForeignKey(
        User, models.PROTECT, related_name='+',
        help_text='记录操作账号（审计字段；处理人姓名见 handler_name）')
    handler_name = models.CharField(
        max_length=200, default='', blank=True,
        help_text='处理人（手动输入的姓名，多人以顿号分隔；空串展示回落 handler 用户名）')
    content = models.TextField(max_length=2000, help_text='处理内容')
    work_hours = models.FloatField(null=True, blank=True, help_text='本次工时（小时，选填）')
    corrections = models.TextField(default='', blank=True, help_text='更正历史 JSON 数组')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    class Meta:
        db_table = 'tdyw_el_operation_progress'
        verbose_name = '统一处理进展'
        verbose_name_plural = '统一处理进展'
        ordering = ('handled_at', 'id')
        indexes = [
            models.Index(fields=['tenant_id', 'record', 'handled_at', 'id']),
        ]

    def __repr__(self):
        return '<SystemOperationProgress record=%s at=%s>' % (self.record_id, self.handled_at)

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
            'work_hours': self.work_hours,
            'corrections': self.get_corrections(),
            'created_at': self.created_at,
        }

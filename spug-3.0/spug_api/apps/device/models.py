# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
from apps.account.models import User


class SoftDeleteTenantManager(TenantModelManager):
    """默认管理器：业务查询自动排除软删除记录（is_deleted=False），保留租户感知能力。

    与 document 模块的 SoftDeletedManager 模式一致。
    审计/证据场景如需查看已删除记录，请使用 all_objects。
    """
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class DeviceResume(models.Model, TenantModelMixin):
    """设备档案主表"""
    # 设备状态枚举
    STATUS_NORMAL = '1'
    STATUS_FAULT = '2'
    STATUS_REPAIRING = '3'
    STATUS_DISABLED = '4'
    STATUS_SCRAPPED = '5'
    STATUS_CHOICES = (
        (STATUS_NORMAL, '正常'),
        (STATUS_FAULT, '故障'),
        (STATUS_REPAIRING, '维修中'),
        (STATUS_DISABLED, '停用'),
        (STATUS_SCRAPPED, '报废'),
    )
    STATUS_TEXT_MAP = dict(STATUS_CHOICES)

    objects = SoftDeleteTenantManager()       # 默认：业务查询自动排除软删除
    all_objects = TenantModelManager()        # 全量：审计/证据场景使用（含已删除）
    tenant_id = make_tenant_id()
    device_sn = models.CharField(max_length=50, help_text='设备资产编号，租户内唯一')
    device_name = models.CharField(max_length=50, help_text='设备名称')
    device_model = models.CharField(max_length=50, help_text='设备型号')
    frequency = models.CharField(max_length=30, null=True, blank=True, help_text='工作频率')
    call_sign = models.CharField(max_length=30, null=True, blank=True, help_text='设备呼号')
    install_location = models.CharField(max_length=200, help_text='安装地点')
    geo_coordinate = models.CharField(max_length=100, null=True, blank=True, help_text='安装经纬度，格式: 经度,纬度')
    device_purpose = models.TextField(null=True, blank=True, max_length=500, help_text='设备用途')
    manufacturer = models.CharField(max_length=100, help_text='生产厂家')
    install_unit = models.CharField(max_length=100, help_text='安装单位')
    use_unit = models.CharField(max_length=100, help_text='使用单位')
    install_time = models.DateTimeField(null=True, blank=True, help_text='安装时间')
    enable_time = models.DateTimeField(null=True, blank=True, help_text='启用时间')
    current_status = models.CharField(max_length=20, choices=STATUS_CHOICES, help_text='当前设备状况：1=正常，2=故障，3=维修中，4=停用，5=报废')
    responsible_user_id = models.IntegerField(null=True, blank=True, help_text='设备负责人ID（已废弃，保留以兼容旧数据，新建/编辑请使用 responsible_user_name）')
    responsible_user_name = models.CharField(max_length=100, help_text='设备负责人姓名')
    remark = models.TextField(null=True, blank=True, max_length=1000, help_text='备注')
    # 软删除标记：证据闭环第三阶段启用软删除，避免硬删除断链
    is_deleted = models.BooleanField(default=False, help_text='是否已删除（软删除）')
    deleted_at = models.DateTimeField(null=True, blank=True, help_text='删除时间')
    deleted_by_id = models.IntegerField(null=True, blank=True, help_text='删除人账号ID')
    delete_reason = models.CharField(max_length=500, default='', blank=True, help_text='删除原因')
    # 证据闭环：归档快照哈希
    snapshot_hash = models.CharField(max_length=64, default='', help_text='设备快照哈希(SHA256)')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<DeviceResume %r>' % self.device_sn

    def to_view(self):
        tmp = self.to_dict(excludes=('is_deleted',))
        # 添加状态显示文本（使用 STATUS_TEXT_MAP 保证与 choices 一致）
        tmp['current_status_text'] = self.STATUS_TEXT_MAP.get(self.current_status, self.current_status)
        return tmp

    class Meta:
        db_table = 'tdyw_device_resume'
        verbose_name = '设备档案'
        verbose_name_plural = '设备档案'
        ordering = ('-created_at', '-id')
        constraints = [
            # 设备编号租户内唯一（不同租户可创建相同编号）
            models.UniqueConstraint(fields=['tenant_id', 'device_sn'], name='uniq_device_resume_tenant_sn'),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'current_status']),
            models.Index(fields=['tenant_id', '-created_at', '-id']),
        ]


class DeviceEvent(models.Model, TenantModelMixin):
    """设备事件记录表"""
    # 事件类型枚举
    EVENT_TYPE_FAULT = 1
    EVENT_TYPE_UPDATE = 2
    EVENT_TYPE_INSPECTION = 3
    EVENT_TYPE_CHOICES = (
        (EVENT_TYPE_FAULT, '重大故障维修'),
        (EVENT_TYPE_UPDATE, '设备更新'),
        (EVENT_TYPE_INSPECTION, '设备检修'),
    )
    EVENT_TYPE_TEXT_MAP = dict(EVENT_TYPE_CHOICES)
    # 合法事件类型集合（供 validators 复用）
    EVENT_TYPE_VALUES = {EVENT_TYPE_FAULT, EVENT_TYPE_UPDATE, EVENT_TYPE_INSPECTION}

    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    # 注意：当前以 IntegerField 保存设备档案ID，未使用数据库外键约束。
    # 原因：项目已上线，外键改造需清理孤儿数据并执行表结构变更，风险较高。
    # 缓解措施：
    #   1. 事件创建统一走 DeviceEventBuilder，调用前在 views 层按租户查询设备是否存在；
    #   2. 删除设备时在 views 层事务内级联删除事件（见 DeviceResumeView.delete）。
    # 后续若需更强一致性，可新增迁移：先清理孤儿事件，再 AlterField 为 ForeignKey。
    device_resume_id = models.IntegerField(help_text='关联设备档案ID（逻辑外键，未使用DB外键约束）')
    device_name = models.CharField(max_length=100, help_text='设备名称（冗余字段，便于查询）')
    device_sn = models.CharField(max_length=50, help_text='设备编号（冗余字段，便于查询）')
    event_type = models.IntegerField(choices=EVENT_TYPE_CHOICES, help_text='事件类型：1=重大故障维修，2=设备更新，3=设备检修')
    event_time = models.DateTimeField(null=True, blank=True, help_text='事件时间')
    event_title = models.CharField(max_length=100, help_text='事件标题')
    fault_part = models.CharField(max_length=100, null=True, blank=True, help_text='故障件（仅检修类型）')
    fault_phenomenon_cause = models.TextField(null=True, blank=True, max_length=1000, help_text='故障现象及原因（仅检修类型）')
    maintenance_measures = models.TextField(null=True, blank=True, max_length=2000, help_text='检修措施（仅检修类型）')
    related_user_id = models.IntegerField(null=True, blank=True, help_text='记录人ID（已废弃，保留以兼容旧数据，新建/编辑请使用 related_user_name）')
    related_user_name = models.CharField(max_length=100, help_text='记录人姓名')
    repair_time = models.DateTimeField(null=True, blank=True, help_text='修复时间（仅检修类型）')
    remark = models.TextField(null=True, blank=True, max_length=500, help_text='备注')
    # 软删除标记：当前业务采用硬删除，该字段仅保留以兼容历史数据
    is_deleted = models.BooleanField(default=False, help_text='是否已删除（当前为硬删除，字段预留）')
    # ==== 证据闭环：更正机制 ====
    correction_event_id = models.IntegerField(null=True, blank=True, help_text='更正指向的原事件ID')
    correction_reason = models.CharField(max_length=500, default='', blank=True, help_text='更正原因')
    corrected_by_id = models.IntegerField(null=True, blank=True, help_text='更正人账号ID')
    corrected_at = models.DateTimeField(null=True, blank=True, help_text='更正时间')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')

    def __repr__(self):
        return '<DeviceEvent %r>' % self.event_title

    def to_view(self):
        tmp = self.to_dict(excludes=('is_deleted',))
        # 添加事件类型显示文本（使用 EVENT_TYPE_TEXT_MAP 保证与 choices 一致）
        tmp['event_type_text'] = self.EVENT_TYPE_TEXT_MAP.get(self.event_type, str(self.event_type))
        return tmp

    class Meta:
        db_table = 'tdyw_device_event'
        verbose_name = '设备事件'
        verbose_name_plural = '设备事件'
        ordering = ('-event_time', '-id')
        indexes = [
            models.Index(fields=['tenant_id', 'device_resume_id']),
            models.Index(fields=['tenant_id', '-event_time', '-id']),
        ]

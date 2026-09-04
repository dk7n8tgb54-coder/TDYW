# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备生命周期模型：设备档案（独立）+ 位置历史 + 系统主数据 + 系统—设备关系。

边界约束：
- 设备档案为本应用独立主数据（不读写 apps.device 的 DeviceResume），
  与旧设备管理模块数据互不穿透；
- 位置历史只进不出：变更仅封存旧时段（ended_at）并新建记录，不删除、
  不修改已保存的历史快照；
- 关系中的设备以 DB 级外键引用本应用模型（删除由应用层守卫 + PROTECT
  双重防护），并保留编号/名称快照便于历史展示；
- 所有模型继承 TenantModelMixin，遵守现有租户隔离规范；
- 关系历史只进不出：退出仅置状态，不删除记录。
"""
from django.db import models

from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
from apps.account.models import User


class LifecycleDevice(models.Model, TenantModelMixin):
    """设备生命周期 - 设备档案（独立主数据，与旧 device 模块无关）"""
    # 设备状态枚举（语义与旧模块一致，便于后续数据迁移）
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

    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    device_sn = models.CharField(max_length=50, help_text='设备资产编号，租户内唯一')
    device_name = models.CharField(max_length=50, help_text='设备名称')
    device_model = models.CharField(max_length=50, help_text='设备型号')
    install_time = models.DateField(null=True, blank=True, help_text='安装时间')
    enable_time = models.DateField(null=True, blank=True, help_text='启用时间')
    current_status = models.CharField(max_length=20, choices=STATUS_CHOICES, help_text='当前设备状况：1=正常，2=故障，3=维修中，4=停用，5=报废')
    current_location = models.CharField(max_length=200, blank=True, default='', help_text='当前所在位置')
    remark = models.CharField(max_length=500, blank=True, help_text='备注', default='')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<LifecycleDevice %r>' % self.device_sn

    def to_view(self):
        tmp = self.to_dict()
        tmp['current_status_text'] = self.STATUS_TEXT_MAP.get(self.current_status, self.current_status)
        return tmp

    class Meta:
        db_table = 'tdyw_el_device'
        verbose_name = '生命周期设备档案'
        verbose_name_plural = '生命周期设备档案'
        ordering = ('-created_at', '-id')
        constraints = [
            models.UniqueConstraint(fields=['tenant_id', 'device_sn'], name='uniq_el_device_tenant_sn'),
            models.CheckConstraint(
                check=models.Q(current_status__in=['1', '2', '3', '4', '5']),
                name='el_device_status_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant_id', '-created_at', '-id'], name='el_dev_tenant_idx'),
        ]


class LifecycleDeviceLocation(models.Model, TenantModelMixin):
    """设备位置历史（只进不出）

    位置时段语义：[effective_at, ended_at)，ended_at 为空表示当前位置；
    同一设备同一时间至多一条有效位置记录——MariaDB 不支持部分唯一索引，
    由 GET_LOCK 命名锁（el_loc:{tenant}:{device}）串行化写入 + 事务内
    select_for_update + 应用层校验共同保证。
    历史记录保留变更前位置快照，后续变更不修改已保存记录。
    """
    # 变更类型：initial 仅由建档流程服务端写入，变更接口不接受
    CHANGE_INITIAL = 'initial'
    CHANGE_RELOCATION = 'relocation'
    CHANGE_CORRECTION = 'correction'
    CHANGE_TYPE_CHOICES = (
        (CHANGE_INITIAL, '初始登记'),
        (CHANGE_RELOCATION, '位置搬迁'),
        (CHANGE_CORRECTION, '位置更正'),
    )
    CHANGE_TYPE_TEXT_MAP = dict(CHANGE_TYPE_CHOICES)
    # 位置变更接口允许的变更类型
    CHANGE_TYPE_VALUES = {CHANGE_RELOCATION, CHANGE_CORRECTION}

    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    # 设备为本应用自有模型，DB 级外键（设备删除由应用层守卫 + PROTECT 双重防护）
    device = models.ForeignKey(LifecycleDevice, models.PROTECT, related_name='location_history',
                               help_text='所属设备档案')
    old_location = models.CharField(max_length=200, blank=True, default='',
                                    help_text='变更前位置快照（初始登记为空）')
    new_location = models.CharField(max_length=200, help_text='变更后位置')
    effective_at = models.DateTimeField(help_text='生效时间')
    ended_at = models.DateTimeField(null=True, blank=True, help_text='失效时间（空=当前位置）')
    change_type = models.CharField(max_length=20, choices=CHANGE_TYPE_CHOICES, help_text='变更类型')
    reason = models.CharField(max_length=500, blank=True, default='', help_text='变更原因')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')

    def __repr__(self):
        return '<LifecycleDeviceLocation %r/%r>' % (self.device_id, self.new_location)

    def to_view(self):
        tmp = self.to_dict()
        tmp['change_type_text'] = self.CHANGE_TYPE_TEXT_MAP.get(self.change_type, self.change_type)
        return tmp

    class Meta:
        db_table = 'tdyw_el_device_location'
        verbose_name = '生命周期设备位置历史'
        verbose_name_plural = '生命周期设备位置历史'
        ordering = ('-effective_at', '-id')
        constraints = [
            models.CheckConstraint(
                check=models.Q(change_type__in=['initial', 'relocation', 'correction']),
                name='el_loc_change_type_valid',
            ),
        ]
        indexes = [
            # 当前有效记录定位（device_id + ended_at）与同设备历史检索
            models.Index(fields=['device_id', 'ended_at'], name='el_loc_dev_end_idx'),
            models.Index(fields=['tenant_id', 'device_id', '-effective_at', '-id'], name='el_loc_tenant_idx'),
        ]


class LifecycleSystem(models.Model, TenantModelMixin):
    """系统主数据"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    code = models.CharField(max_length=50, default='', blank=True, help_text='系统编码，租户内选填唯一')
    name = models.CharField(max_length=100, help_text='系统名称，租户内唯一')
    description = models.CharField(max_length=500, default='', blank=True, help_text='系统描述')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<LifecycleSystem %r>' % self.name

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_el_system'
        verbose_name = '生命周期系统'
        verbose_name_plural = '生命周期系统'
        ordering = ('-created_at', '-id')
        constraints = [
            # 系统名称租户内唯一（不同租户可创建同名系统）
            models.UniqueConstraint(fields=['tenant_id', 'name'], name='uniq_el_system_tenant_name'),
        ]
        indexes = [
            models.Index(fields=['tenant_id', '-created_at', '-id']),
        ]


class SystemDeviceRelation(models.Model, TenantModelMixin):
    """系统—设备关系

    时间段语义：半开区间 [valid_from, valid_to)，valid_to 当天已不隶属，
    端点相接不算重叠；valid_to 为空表示长期有效。
    历史只进不出：退出（status=ended）仅封存时间段，不删除记录；
    重新加入必须建立新的关系时间段。
    """
    # 关系角色
    ROLE_PRIMARY = 'primary'
    ROLE_BACKUP = 'backup'
    ROLE_MEMBER = 'member'
    ROLE_CHOICES = (
        (ROLE_PRIMARY, '主用'),
        (ROLE_BACKUP, '备用'),
        (ROLE_MEMBER, '组成单元'),
    )
    ROLE_TEXT_MAP = dict(ROLE_CHOICES)
    ROLE_VALUES = {ROLE_PRIMARY, ROLE_BACKUP, ROLE_MEMBER}

    # 关系状态
    STATUS_ACTIVE = 'active'
    STATUS_ENDED = 'ended'
    STATUS_CHOICES = (
        (STATUS_ACTIVE, '生效中'),
        (STATUS_ENDED, '已退出'),
    )
    STATUS_TEXT_MAP = dict(STATUS_CHOICES)

    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    # 系统与设备均为本应用自有模型，使用 DB 级外键（删除由应用层守卫 + PROTECT 双重防护）
    system = models.ForeignKey(LifecycleSystem, models.PROTECT, related_name='device_relations',
                               help_text='所属系统')
    device = models.ForeignKey(LifecycleDevice, models.PROTECT, related_name='system_relations',
                               help_text='关联设备档案')
    device_sn = models.CharField(max_length=50, help_text='设备编号（创建时快照，便于展示）')
    device_name = models.CharField(max_length=50, help_text='设备名称（创建时快照，便于展示）')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, help_text='关系角色：主用/备用/组成单元')
    is_primary = models.BooleanField(default=False, help_text='是否为主要归属')
    valid_from = models.DateField(help_text='生效日期（含）')
    valid_to = models.DateField(null=True, blank=True, help_text='失效日期（不含，空=长期有效）')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
                              help_text='关系状态：active=生效中，ended=已退出')
    remark = models.CharField(max_length=500, default='', blank=True, help_text='备注')
    ended_at = models.DateTimeField(null=True, blank=True, help_text='退出时间')
    ended_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True,
                                 help_text='退出操作人')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<SystemDeviceRelation %r/%r>' % (self.system_id, self.device_id)

    def to_view(self):
        tmp = self.to_dict()
        tmp['role_text'] = self.ROLE_TEXT_MAP.get(self.role, self.role)
        tmp['status_text'] = self.STATUS_TEXT_MAP.get(self.status, self.status)
        return tmp

    @staticmethod
    def find_overlap(rows, valid_from, valid_to, exclude_id=None):
        """在已锁定的关系行中查找与新时间段重叠的记录（半开区间语义）。

        返回第一条重叠记录，无重叠返回 None。
        overlap := existing.valid_from < new.valid_to 且 new.valid_from < existing.valid_to
        （valid_to 为 None 视为无穷远）
        """
        for row in rows:
            if exclude_id and row.id == exclude_id:
                continue
            if row.valid_to is not None and row.valid_to <= valid_from:
                continue
            if valid_to is not None and row.valid_from >= valid_to:
                continue
            return row
        return None

    class Meta:
        db_table = 'tdyw_el_system_device_relation'
        verbose_name = '系统设备关系'
        verbose_name_plural = '系统设备关系'
        ordering = ('-valid_from', '-id')
        indexes = [
            # 重叠检查与并发锁定的定位索引（同系统+设备+角色的锁定读走此索引）
            models.Index(fields=['system_id', 'device_id', 'role'], name='el_rel_trio_idx'),
            models.Index(fields=['tenant_id', 'system_id', 'status'], name='el_rel_tenant_sys_idx'),
            models.Index(fields=['device_id'], name='el_rel_device_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(role__in=['primary', 'backup', 'member']),
                name='el_rel_role_valid',
            ),
            models.CheckConstraint(
                check=models.Q(status__in=['active', 'ended']),
                name='el_rel_status_valid',
            ),
            models.CheckConstraint(
                check=models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=models.F('valid_from')),
                name='el_rel_period_valid',
            ),
        ]

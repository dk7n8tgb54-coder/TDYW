# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from libs import human_datetime
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
from apps.account.models import User


class DeviceResume(models.Model, TenantModelMixin):
    """设备档案主表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    device_sn = models.CharField(max_length=50, unique=True, help_text='设备资产编号，全局唯一')
    device_sn = models.CharField(max_length=50, unique=True, help_text='设备资产编号，全局唯一')
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
    install_time = models.CharField(max_length=20, help_text='安装时间')
    enable_time = models.CharField(max_length=20, help_text='启用时间')
    current_status = models.CharField(max_length=20, help_text='当前设备状况：1=正常，2=故障，3=维修中，4=停用，5=报废')
    responsible_user_id = models.IntegerField(null=True, blank=True, help_text='设备负责人ID（已废弃，使用负责人姓名字段）')
    responsible_user_name = models.CharField(max_length=100, help_text='设备负责人姓名')
    remark = models.TextField(null=True, blank=True, max_length=1000, help_text='备注')
    is_deleted = models.BooleanField(default=False, help_text='是否已删除')
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<DeviceResume %r>' % self.device_sn

    def to_view(self):
        tmp = self.to_dict(excludes=('is_deleted',))
        # 添加状态显示文本
        status_map = {
            '1': '正常',
            '2': '故障',
            '3': '维修中',
            '4': '停用',
            '5': '报废'
        }
        tmp['current_status_text'] = status_map.get(self.current_status, self.current_status)
        return tmp

    class Meta:
        db_table = 'tdyw_device_resume'
        verbose_name = '设备档案'
        verbose_name_plural = '设备档案'
        ordering = ('-created_at', '-id')
        # device_sn已全局唯一，无需unique_together
        indexes = [
            models.Index(fields=['tenant_id', 'current_status']),
            models.Index(fields=['tenant_id', '-created_at', '-id']),
        ]


class DeviceEvent(models.Model, TenantModelMixin):
    """设备事件记录表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    device_resume_id = models.IntegerField(help_text='关联设备档案ID')
    device_name = models.CharField(max_length=100, help_text='设备名称（冗余字段，便于查询）')
    device_sn = models.CharField(max_length=50, help_text='设备编号（冗余字段，便于查询）')
    event_type = models.IntegerField(help_text='事件类型：1=重大故障维修，2=设备更新，3=设备检修')
    event_time = models.CharField(max_length=20, help_text='事件时间')
    event_title = models.CharField(max_length=100, help_text='事件标题')
    fault_part = models.CharField(max_length=100, null=True, blank=True, help_text='故障件（仅检修类型）')
    fault_phenomenon_cause = models.TextField(null=True, blank=True, max_length=1000, help_text='故障现象及原因（仅检修类型）')
    maintenance_measures = models.TextField(null=True, blank=True, max_length=2000, help_text='检修措施（仅检修类型）')
    related_user_id = models.IntegerField(null=True, blank=True, help_text='记录人ID（已废弃，使用记录人姓名字段）')
    related_user_name = models.CharField(max_length=100, help_text='记录人姓名')
    repair_time = models.CharField(max_length=20, null=True, blank=True, help_text='修复时间（仅检修类型）')
    remark = models.TextField(null=True, blank=True, max_length=500, help_text='备注')
    is_deleted = models.BooleanField(default=False, help_text='是否已删除')
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')

    def __repr__(self):
        return '<DeviceEvent %r>' % self.event_title

    def to_view(self):
        tmp = self.to_dict(excludes=('is_deleted',))
        # 添加事件类型显示文本
        event_type_map = {
            1: '重大故障维修',
            2: '设备更新',
            3: '设备检修'
        }
        tmp['event_type_text'] = event_type_map.get(self.event_type, str(self.event_type))
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

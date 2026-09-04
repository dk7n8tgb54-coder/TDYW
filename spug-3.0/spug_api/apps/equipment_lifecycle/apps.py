# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.apps import AppConfig


class EquipmentLifecycleConfig(AppConfig):
    """设备生命周期应用配置类

    第一阶段第 1 步：与 device 模块并行的独立只读视图模块。
    本应用不定义任何模型，直接租户隔离地只读展示 apps.device 的 DeviceResume，
    后续阶段（系统主数据、设备关系、部件、履历、巡检、工单、报废、迁移）在本应用内扩展。
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.equipment_lifecycle'
    verbose_name = '设备生命周期'

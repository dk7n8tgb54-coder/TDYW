# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.apps import AppConfig


class EquipmentLifecycleConfig(AppConfig):
    """设备全生命周期应用配置类

    步骤一（旧结构清理）已删除旧的设备档案、位置历史、系统主数据、
    系统—设备关系模型及对应四张表（见 migrations/0005），应用外壳保留，
    后续按《设备全生命周期管理总体方案》在本应用内重建。
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.equipment_lifecycle'
    verbose_name = '设备生命周期'

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

from django.apps import AppConfig


class DeviceConfig(AppConfig):
    """Device应用配置类"""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.device'
    verbose_name = '设备管理'

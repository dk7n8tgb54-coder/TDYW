# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

from django.apps import AppConfig


class InterferenceConfig(AppConfig):
    """Interference应用配置类"""
    default_auto_field = 'django.db.models.AutoField'
    name = 'apps.interference'
    verbose_name = '干扰管理'

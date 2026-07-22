# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

from django.apps import AppConfig


class RegulationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.regulation'
    verbose_name = '规章管理'

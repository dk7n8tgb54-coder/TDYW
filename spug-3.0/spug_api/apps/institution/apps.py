# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.

from django.apps import AppConfig


class InstitutionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.institution'
    verbose_name = '制度管理'

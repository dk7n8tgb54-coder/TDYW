# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

from django.apps import AppConfig


class IndustryRuleConfig(AppConfig):
    default_auto_field = 'django.db.models.AutoField'
    name = 'apps.industry_rule'
    verbose_name = '行业规章'

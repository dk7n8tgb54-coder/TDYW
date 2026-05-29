# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
系统升级模板模型

用于快速创建升级表单，预设常用字段值。
"""
from django.db import models
from libs import ModelMixin
from apps.account.models import User


class UpgradeTemplate(models.Model, ModelMixin):
    """升级模板"""
    tenant_id = models.CharField(max_length=50, default='', db_index=True, help_text='租户标识')
    name = models.CharField(max_length=100, verbose_name='模板名称')
    system = models.CharField(max_length=100, default='', blank=True, verbose_name='系统')
    upgrade_type = models.CharField(max_length=50, default='', blank=True, verbose_name='升级类型')
    version = models.CharField(max_length=100, default='', blank=True, verbose_name='默认版本')
    owner = models.CharField(max_length=100, default='', blank=True, verbose_name='负责人')
    status = models.CharField(max_length=20, default='处理中', verbose_name='默认状态')
    detail_content = models.TextField(default='', blank=True, verbose_name='默认记录内容')
    is_default = models.BooleanField(default=False, verbose_name='是否为默认模板')

    created_at = models.CharField(max_length=20, verbose_name='创建时间')
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True, blank=True, verbose_name='更新时间')

    def __repr__(self):
        return f'<UpgradeTemplate {self.name}>'

    class Meta:
        db_table = 'exec_upgrade_templates'
        ordering = ('-is_default', 'name', '-id')
        indexes = [
            models.Index(fields=['tenant_id']),
        ]

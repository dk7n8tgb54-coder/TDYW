# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
系统升级模块模型

注意：当前模型与数据库 schema 完全匹配（Django 2.2 + MySQL）。
数据库 schema 变更（DateTimeField/ForeignKey/去除冗余字段）需通过迁移 0004 执行，
迁移完成后需同步更新本文件和 serializers/services 层。
"""
from django.db import models
from django.utils import timezone
from libs import ModelMixin
from apps.account.models import User
import logging

logger = logging.getLogger(__name__)

# 租户类型常量
TENANT_TYPE_PRIVATE = 'PRIVATE'


class UpgradeRecord(models.Model, ModelMixin):
    """升级表单主表"""
    TENANT_TYPE = TENANT_TYPE_PRIVATE
    tenant_id = models.CharField(max_length=50, default='', db_index=True, help_text='租户标识')
    upgrade_no = models.CharField(max_length=50)
    system = models.CharField(max_length=100)
    upgrade_type = models.CharField(max_length=50)
    version = models.CharField(max_length=100)
    upgrade_time = models.CharField(max_length=20, verbose_name='升级时间')
    status = models.CharField(max_length=20, default='处理中')
    owner = models.CharField(max_length=100)

    created_at = models.CharField(max_length=20, verbose_name='创建时间')
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True, blank=True, verbose_name='更新时间')
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True)

    def __repr__(self):
        return '<UpgradeRecord %r>' % self.upgrade_no

    class Meta:
        db_table = 'exec_upgrade_records'
        ordering = ('-upgrade_time', '-id',)
        unique_together = [['tenant_id', 'upgrade_no']]
        indexes = [
            models.Index(fields=['tenant_id', 'status']),
        ]







# 导入模板模型，确保 Django 发现
from .models_template import UpgradeTemplate  # noqa: E402, F401
# 导入步骤清单模型，确保 Django 发现
from .models_checklist import UpgradeChecklist, UpgradeChecklistStep, UpgradeRecordStep  # noqa: E402, F401

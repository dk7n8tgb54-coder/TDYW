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
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
from apps.account.models import User
import logging

logger = logging.getLogger(__name__)


class UpgradeRecord(models.Model, TenantModelMixin):
    """升级表单主表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    upgrade_no = models.CharField(max_length=50)
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
        db_table = 'tdyw_upgrade_records'
        verbose_name = '升级记录'
        verbose_name_plural = '升级记录'
        ordering = ('-upgrade_time', '-id',)
        unique_together = [['tenant_id', 'upgrade_no']]
        indexes = [
            models.Index(fields=['tenant_id', 'status']),
        ]







# 导入升级方案模型（原升级模板+步骤清单合并），确保 Django 发现
from .models_template import UpgradeTemplate, UpgradePlanStep  # noqa: E402, F401
# 导入升级记录步骤模型，确保 Django 发现
from .models_checklist import UpgradeRecordStep  # noqa: E402, F401
# 导入升级状态日志模型，确保 Django 发现
from .models_status_log import UpgradeStatusLog  # noqa: E402, F401

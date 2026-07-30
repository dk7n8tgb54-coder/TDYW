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
    title = models.CharField(max_length=200, default='', verbose_name='标题')
    system = models.CharField(max_length=100)
    upgrade_type = models.CharField(max_length=50)
    upgrade_time = models.DateTimeField(null=True, blank=True, verbose_name='计划升级时间')
    status = models.CharField(max_length=20, default='处理中')
    owner = models.CharField(max_length=100)
    upgrade_content = models.TextField(default='', blank=True, verbose_name='升级内容')
    impact_scope = models.TextField(default='', blank=True, verbose_name='影响范围')
    risk_desc = models.TextField(default='', blank=True, verbose_name='风险说明')
    rollback_plan = models.TextField(default='', blank=True, verbose_name='回退方案摘要')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True, verbose_name='更新时间')
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True)
    is_deleted = models.BooleanField(default=False, help_text='软删除标识')
    deleted_at = models.DateTimeField(null=True, blank=True, help_text='删除时间')

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
            # 默认列表分页：tenant_id + 计划升级时间倒序 + id
            models.Index(fields=['tenant_id', 'upgrade_time', 'id'], name='upg_rec_time_idx'),
            # 状态精确筛选 + 时间排序（status 为列表高频筛选字段）
            models.Index(fields=['tenant_id', 'status', 'upgrade_time', 'id'], name='upg_rec_status_time_idx'),
            # 升级类型精确筛选 + 时间排序（upgrade_type 为列表高频筛选字段）
            models.Index(fields=['tenant_id', 'upgrade_type', 'upgrade_time', 'id'], name='upg_rec_type_time_idx'),
        ]







class UpgradeSystem(models.Model, TenantModelMixin):
    """升级系统候选项字典

    用于"升级系统"字段的候选列表维护。新建升级申请时可搜索/选择/新增。
    历史升级记录的 system 字段是纯文本，不受本表删除/停用影响。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    name = models.CharField(max_length=100, verbose_name='系统名称')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    sort_order = models.IntegerField(default=0, verbose_name='排序')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True, verbose_name='更新时间')
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True, blank=True)
    is_deleted = models.BooleanField(default=False, help_text='软删除标识')
    deleted_at = models.DateTimeField(null=True, blank=True, help_text='删除时间')

    def __repr__(self):
        return '<UpgradeSystem %r>' % self.name

    class Meta:
        db_table = 'tdyw_upgrade_systems'
        verbose_name = '升级系统候选项'
        verbose_name_plural = '升级系统候选项'
        ordering = ('sort_order', 'name',)
        unique_together = [['tenant_id', 'name']]
        indexes = [
            # 启用系统下拉/系统管理列表：tenant_id + is_active + sort_order + name
            models.Index(fields=['tenant_id', 'is_active', 'sort_order', 'name'], name='upg_sys_active_idx'),
        ]


# 导入升级方案模型（原升级模板+步骤清单合并），确保 Django 发现
from .models_template import UpgradeTemplate, UpgradePlanStep  # noqa: E402, F401
# 导入升级记录步骤模型，确保 Django 发现
from .models_checklist import UpgradeRecordStep  # noqa: E402, F401
# 导入升级状态日志模型，确保 Django 发现
from .models_status_log import UpgradeStatusLog  # noqa: E402, F401

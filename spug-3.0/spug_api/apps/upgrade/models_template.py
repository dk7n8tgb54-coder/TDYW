# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
升级方案模型

由原「升级模板」与「步骤清单」合并而来：
- UpgradeTemplate 扩展 description 字段，承载方案基本信息（系统/类型/版本/负责人/默认状态等）。
- UpgradePlanStep 关联 template_id，存放方案的预设步骤。

注意：
- 原 UpgradeChecklist / UpgradeChecklistStep 已于迁移 0004 移除，数据已合并至本表。
- UpgradeRecordStep.checklist_id 字段保留，合并后语义为「来源方案ID（template_id）」，
  历史数据指向已删除的旧 checklist，新数据指向 UpgradeTemplate.id。
"""
from django.db import models
from libs import ModelMixin
from apps.account.models import User


class UpgradeTemplate(models.Model, ModelMixin):
    """升级方案（原升级模板，扩展为模板+步骤的合集）"""
    tenant_id = models.CharField(max_length=50, default='', db_index=True, help_text='租户标识')
    name = models.CharField(max_length=100, verbose_name='方案名称')
    description = models.TextField(default='', blank=True, verbose_name='方案描述')
    system = models.CharField(max_length=100, default='', blank=True, verbose_name='系统')
    upgrade_type = models.CharField(max_length=50, default='', blank=True, verbose_name='升级类型')
    version = models.CharField(max_length=100, default='', blank=True, verbose_name='默认版本')
    owner = models.CharField(max_length=100, default='', blank=True, verbose_name='负责人')
    status = models.CharField(max_length=20, default='处理中', verbose_name='默认状态')
    detail_content = models.TextField(default='', blank=True, verbose_name='默认记录内容')
    is_default = models.BooleanField(default=False, verbose_name='是否为默认方案')

    created_at = models.CharField(max_length=20, verbose_name='创建时间')
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True, blank=True, verbose_name='更新时间')

    def __repr__(self):
        return f'<UpgradeTemplate {self.name}>'

    class Meta:
        db_table = 'tdyw_upgrade_templates'
        verbose_name = '升级方案'
        verbose_name_plural = '升级方案'
        ordering = ('-is_default', 'name', '-id')
        indexes = [
            models.Index(fields=['tenant_id']),
            # 模板列表默认排序：tenant_id + is_default + name + id
            models.Index(fields=['tenant_id', 'is_default', 'name', 'id'], name='upg_tpl_default_idx'),
        ]


class UpgradePlanStep(models.Model, ModelMixin):
    """方案预设步骤项 - 关联到某个升级方案（UpgradeTemplate）"""
    tenant_id = models.CharField(max_length=50, default='', db_index=True, help_text='租户标识')
    template_id = models.IntegerField(verbose_name='关联方案ID')

    # 所属阶段（对应标准升级流程），空字符串为未分组
    phase = models.CharField(max_length=20, default='', blank=True, verbose_name='所属阶段')

    title = models.CharField(max_length=200, verbose_name='步骤标题')
    description = models.TextField(default='', blank=True, verbose_name='步骤描述')
    sequence = models.IntegerField(default=0, verbose_name='排序序号')
    is_required = models.BooleanField(default=True, verbose_name='是否必执行')

    created_at = models.CharField(max_length=20, verbose_name='创建时间')

    @property
    def template(self):
        """获取关联的方案（延迟查询）"""
        if not hasattr(self, '_template_cache'):
            self._template_cache = UpgradeTemplate.objects.filter(pk=self.template_id).first()
        return self._template_cache

    def __repr__(self):
        return f'<UpgradePlanStep {self.title}>'

    class Meta:
        db_table = 'tdyw_upgrade_plan_steps'
        verbose_name = '方案预设步骤'
        verbose_name_plural = '方案预设步骤'
        ordering = ('template_id', 'sequence', 'id')
        indexes = [
            models.Index(fields=['template_id']),
            models.Index(fields=['tenant_id', 'template_id']),
            # 方案步骤展示顺序：tenant_id + template_id + sequence + id
            models.Index(fields=['tenant_id', 'template_id', 'sequence', 'id'], name='upg_plan_tenant_seq_idx'),
        ]

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
升级步骤清单模型

用于预设升级步骤，每次升级时直接调用，生成步骤执行跟踪记录。
"""
from django.db import models
from django.utils import timezone
from libs import ModelMixin
from apps.account.models import User
import json
import logging

logger = logging.getLogger(__name__)

# 步骤状态常量
STEP_STATUS_PENDING = 'pending'
STEP_STATUS_COMPLETED = 'completed'
STEP_STATUS_SKIPPED = 'skipped'

STEP_STATUS_CHOICES = [
    (STEP_STATUS_PENDING, '待执行'),
    (STEP_STATUS_COMPLETED, '已完成'),
    (STEP_STATUS_SKIPPED, '已跳过'),
]


class UpgradeChecklist(models.Model, ModelMixin):
    """升级步骤清单模板 - 预设升级步骤集合"""
    tenant_id = models.CharField(max_length=50, default='', db_index=True, help_text='租户标识')
    name = models.CharField(max_length=100, verbose_name='清单名称')
    description = models.TextField(default='', blank=True, verbose_name='清单描述')
    is_default = models.BooleanField(default=False, verbose_name='是否为默认清单')

    created_at = models.CharField(max_length=20, verbose_name='创建时间')
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True, blank=True, verbose_name='更新时间')

    def __repr__(self):
        return f'<UpgradeChecklist {self.name}>'

    class Meta:
        db_table = 'exec_upgrade_checklists'
        ordering = ('-is_default', 'name', '-id')
        indexes = [
            models.Index(fields=['tenant_id']),
        ]


class UpgradeChecklistStep(models.Model, ModelMixin):
    """清单步骤项 - 预设的单个步骤"""
    tenant_id = models.CharField(max_length=50, default='', db_index=True, help_text='租户标识')
    checklist_id = models.IntegerField(verbose_name='关联清单ID')
    title = models.CharField(max_length=200, verbose_name='步骤标题')
    description = models.TextField(default='', blank=True, verbose_name='步骤描述')
    sequence = models.IntegerField(default=0, verbose_name='排序序号')
    is_required = models.BooleanField(default=True, verbose_name='是否必执行')

    created_at = models.CharField(max_length=20, verbose_name='创建时间')

    @property
    def checklist(self):
        """获取关联的清单（延迟查询）"""
        if not hasattr(self, '_checklist_cache'):
            self._checklist_cache = UpgradeChecklist.objects.filter(pk=self.checklist_id).first()
        return self._checklist_cache

    def __repr__(self):
        return f'<UpgradeChecklistStep {self.title}>'

    class Meta:
        db_table = 'exec_upgrade_checklist_steps'
        ordering = ('checklist_id', 'sequence', 'id')
        indexes = [
            models.Index(fields=['checklist_id']),
            models.Index(fields=['tenant_id', 'checklist_id']),
        ]


class UpgradeRecordStep(models.Model, ModelMixin):
    """升级记录步骤执行状态 - 实例化到具体升级表单"""
    tenant_id = models.CharField(max_length=50, default='', db_index=True, help_text='租户标识')
    upgrade_id = models.IntegerField(verbose_name='关联升级表单ID')
    checklist_id = models.IntegerField(default=0, verbose_name='来源清单ID（0为手动添加）')

    title = models.CharField(max_length=200, verbose_name='步骤标题')
    description = models.TextField(default='', blank=True, verbose_name='步骤描述')
    sequence = models.IntegerField(default=0, verbose_name='排序序号')
    is_required = models.BooleanField(default=True, verbose_name='是否必执行')

    status = models.CharField(
        max_length=20, default=STEP_STATUS_PENDING,
        choices=STEP_STATUS_CHOICES,
        verbose_name='执行状态'
    )
    completed_by = models.CharField(max_length=100, default='', blank=True, verbose_name='完成人')
    completed_at = models.CharField(max_length=20, default='', blank=True, verbose_name='完成时间')
    remark = models.TextField(default='', blank=True, verbose_name='备注')

    created_at = models.CharField(max_length=20, verbose_name='创建时间')

    @property
    def upgrade(self):
        """获取关联的升级表单（延迟查询）"""
        if not hasattr(self, '_upgrade_cache'):
            from .models import UpgradeRecord
            self._upgrade_cache = UpgradeRecord.objects.filter(pk=self.upgrade_id).first()
        return self._upgrade_cache

    def mark_completed(self, user, remark=''):
        """标记步骤为已完成"""
        now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        self.status = STEP_STATUS_COMPLETED
        self.completed_by = user.nickname or user.username
        self.completed_at = now_str
        if remark:
            self.remark = remark
        self.save(update_fields=['status', 'completed_by', 'completed_at', 'remark'])

    def mark_skipped(self, user, remark=''):
        """标记步骤为已跳过"""
        now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        self.status = STEP_STATUS_SKIPPED
        self.completed_by = user.nickname or user.username
        self.completed_at = now_str
        if remark:
            self.remark = remark
        self.save(update_fields=['status', 'completed_by', 'completed_at', 'remark'])

    def reset_status(self):
        """重置步骤为待执行"""
        self.status = STEP_STATUS_PENDING
        self.completed_by = ''
        self.completed_at = ''
        self.remark = ''
        self.save(update_fields=['status', 'completed_by', 'completed_at', 'remark'])

    class Meta:
        db_table = 'exec_upgrade_record_steps'
        ordering = ('upgrade_id', 'sequence', 'id')
        indexes = [
            models.Index(fields=['upgrade_id']),
            models.Index(fields=['tenant_id', 'upgrade_id']),
        ]

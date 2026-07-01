# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
升级记录步骤模型

注意：
- 原 UpgradeChecklist / UpgradeChecklistStep 已于迁移 0004 合并至 UpgradeTemplate / UpgradePlanStep 并移除。
- 本文件仅保留 UpgradeRecordStep（升级记录实际执行步骤，方案明确不变）。
- checklist_id 字段保留，合并后语义为「来源方案ID（template_id）」，0 表示手动添加；
  历史数据可能指向已删除的旧 checklist，不影响功能读取。
"""
from django.db import models
from django.utils import timezone
from libs import ModelMixin
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


class UpgradeRecordStep(models.Model, ModelMixin):
    """升级记录步骤执行状态 - 实例化到具体升级表单"""
    tenant_id = models.CharField(max_length=50, default='', db_index=True, help_text='租户标识')
    upgrade_id = models.IntegerField(verbose_name='关联升级表单ID')
    # 合并后语义：来源方案ID（template_id），0 为手动添加；历史数据可能指向已删除的旧 checklist
    checklist_id = models.IntegerField(default=0, verbose_name='来源方案ID（0为手动添加）')

    # 所属阶段（对应标准升级流程：start/backup/gray_release/test/test_pass/full_release/observe/complete）
    # 空字符串表示未分组（兼容历史数据），前端归入"未分组"
    phase = models.CharField(max_length=20, default='', blank=True, verbose_name='所属阶段')

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
        db_table = 'tdyw_upgrade_record_steps'
        verbose_name = '升级记录步骤'
        verbose_name_plural = '升级记录步骤'
        ordering = ('upgrade_id', 'sequence', 'id')
        indexes = [
            models.Index(fields=['upgrade_id']),
            models.Index(fields=['tenant_id', 'upgrade_id']),
        ]

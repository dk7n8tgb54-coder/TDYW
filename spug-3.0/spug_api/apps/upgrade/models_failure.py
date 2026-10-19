# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
升级失败处理单

阶段标记失败（test_fail）后生成一条失败处理单，承载"处理失败"闭环：
- pending   失败待处理：阻塞该阶段普通完成/跳过与整体自动完成，保留失败现场（不清步骤）
- redoing   重做中：已选定重做范围（部分步骤/整个阶段），解除阻塞，直至该阶段重新完成
- resolved  已解决：重做后该阶段重新完成（check_phase_completion）或被"从某阶段重新执行"覆盖
- corrected 已更正：误标失败，人工填写原因更正（原失败事件保留，追加更正事件）

设计约束：
- 标记失败不修改过去的完成事件（phase_done outcome 不再联动），失败以独立单据+事件表达；
- 同一升级同一阶段同时最多一条未结（pending/redoing）失败单；
- 状态迁移与事件写入必须在同一事务（调用方负责）。
"""
from django.db import models
from libs import ModelMixin
from libs.tenant_base_model import TenantModelManager
import logging

logger = logging.getLogger(__name__)

# 失败处理单状态
FAILURE_PENDING = 'pending'        # 失败待处理（阻塞该阶段普通执行与自动完成）
FAILURE_REDOING = 'redoing'        # 重做中（已选重做范围，解除阻塞）
FAILURE_RESOLVED = 'resolved'      # 已解决（重做完成/重新执行覆盖）
FAILURE_CORRECTED = 'corrected'    # 已更正（误标失败）

FAILURE_STATUS_CHOICES = [
    (FAILURE_PENDING, '失败待处理'),
    (FAILURE_REDOING, '重做中'),
    (FAILURE_RESOLVED, '已解决'),
    (FAILURE_CORRECTED, '已更正'),
]

# 未结状态：阻塞普通执行流程
FAILURE_UNRESOLVED_STATUSES = (FAILURE_PENDING, FAILURE_REDOING)


class UpgradeFailureHandling(models.Model, ModelMixin):
    """升级失败处理单 - 阶段失败的处理闭环"""
    objects = TenantModelManager()
    tenant_id = models.CharField(max_length=50, default='', db_index=True, help_text='租户标识')
    upgrade_id = models.IntegerField(verbose_name='关联升级表单ID')
    phase = models.CharField(max_length=50, verbose_name='失败阶段名')

    reason = models.TextField(default='', blank=True, verbose_name='失败原因')

    status = models.CharField(
        max_length=20, default=FAILURE_PENDING, choices=FAILURE_STATUS_CHOICES,
        verbose_name='处理状态'
    )

    failed_by_name = models.CharField(max_length=100, default='', blank=True, verbose_name='标记失败人')
    failed_at = models.DateTimeField(null=True, blank=True, verbose_name='标记失败时间')

    # 开始重做：选择范围与实际重置数量分开记录（避免数量混淆）
    redo_selected_count = models.IntegerField(default=0, verbose_name='选择重做步骤数')
    redo_reset_count = models.IntegerField(default=0, verbose_name='实际重置步骤数（完成/跳过→待执行）')
    redo_by_name = models.CharField(max_length=100, default='', blank=True, verbose_name='开始重做人')
    redo_at = models.DateTimeField(null=True, blank=True, verbose_name='开始重做时间')

    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name='解决时间')
    resolved_note = models.TextField(default='', blank=True, verbose_name='解决说明')

    correct_reason = models.TextField(default='', blank=True, verbose_name='更正原因')
    correct_by_name = models.CharField(max_length=100, default='', blank=True, verbose_name='更正人')
    correct_at = models.DateTimeField(null=True, blank=True, verbose_name='更正时间')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'tdyw_upgrade_failure_handlings'
        verbose_name = '升级失败处理单'
        verbose_name_plural = '升级失败处理单'
        ordering = ('-id',)
        indexes = [
            models.Index(fields=['tenant_id', 'upgrade_id', 'status']),
            models.Index(fields=['upgrade_id', 'phase', 'status']),
        ]

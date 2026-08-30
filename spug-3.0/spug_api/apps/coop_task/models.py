# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""协作任务模块数据模型

业务流程：发起科室创建任务并派发给若干科室 -> 各科室按材料清单上传交付 -> 发起方逐材料验收/退回 -> 全部材料验收通过后任务自动完成。

租户语义（跨科室可见性由视图层显式校验，不依赖 tenant_id 自动过滤）：
- CoopTask.tenant_id          = 发起科室
- CoopTaskAssignment.tenant_id = 创建人（发起方）租户，target_tenant_id 才是交付科室
- CoopTaskDelivery.tenant_id  = 预生成行记发起方租户；交付状态以下挂附件（上传方租户）为准
"""
import logging

from django.db import models
from django.utils import timezone

from libs.mixins import ModelMixin
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id

logger = logging.getLogger(__name__)

# ==================== 任务状态 ====================
TASK_STATUS_IN_PROGRESS = 'in_progress'
TASK_STATUS_COMPLETED = 'completed'
TASK_STATUS_VOIDED = 'voided'

TASK_STATUS_CHOICES = (
    (TASK_STATUS_IN_PROGRESS, '进行中'),
    (TASK_STATUS_COMPLETED, '已完成'),
    (TASK_STATUS_VOIDED, '已作废'),
)

TASK_STATUS_TEXT = dict(TASK_STATUS_CHOICES)

# ==================== 交付明细状态 ====================
DELIVERY_PENDING = 'pending'
DELIVERY_SUBMITTED = 'submitted'
DELIVERY_ACCEPTED = 'accepted'
DELIVERY_REJECTED = 'rejected'

DELIVERY_STATUS_CHOICES = (
    (DELIVERY_PENDING, '待交付'),
    (DELIVERY_SUBMITTED, '待验收'),
    (DELIVERY_ACCEPTED, '已验收'),
    (DELIVERY_REJECTED, '已退回'),
)

DELIVERY_STATUS_TEXT = dict(DELIVERY_STATUS_CHOICES)

# ==================== 分派聚合状态（由交付明细实时聚合，不落库） ====================
ASSIGNMENT_PENDING = 'pending'
ASSIGNMENT_PARTIAL = 'partial'
ASSIGNMENT_SUBMITTED = 'submitted'
ASSIGNMENT_REJECTED = 'rejected'
ASSIGNMENT_ACCEPTED = 'accepted'

ASSIGNMENT_STATUS_TEXT = {
    ASSIGNMENT_PENDING: '待交付',
    ASSIGNMENT_PARTIAL: '部分交付',
    ASSIGNMENT_SUBMITTED: '待验收',
    ASSIGNMENT_REJECTED: '待重新交付',
    ASSIGNMENT_ACCEPTED: '已完成',
}

TITLE_MAX_LEN = 200
REJECT_REASON_MAX_LEN = 500


def compute_assignment_status(total, accepted, rejected, pending):
    """按交付明细计数聚合分派状态

    优先级：全待交付 > 有退回 > 全部验收 > 无待交付 > 部分交付
    """
    if not total or pending == total:
        return ASSIGNMENT_PENDING
    if rejected:
        return ASSIGNMENT_REJECTED
    if accepted == total:
        return ASSIGNMENT_ACCEPTED
    if pending == 0:
        return ASSIGNMENT_SUBMITTED
    return ASSIGNMENT_PARTIAL


class CoopTask(models.Model, TenantModelMixin):
    """协作任务主表（tdyw_coop_tasks）

    tenant_id 为发起科室；deadline 为交付截止时间（仅展示与逾期标记，不拦截交付）。
    completed 在全部交付明细验收通过后自动置位；voided 由发起方手动作废。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    title = models.CharField(max_length=TITLE_MAX_LEN, help_text='任务标题')
    description = models.TextField(blank=True, default='', help_text='任务说明与要求')
    deadline = models.DateTimeField(help_text='交付截止时间')
    status = models.CharField(
        max_length=20, choices=TASK_STATUS_CHOICES, default=TASK_STATUS_IN_PROGRESS, help_text='任务状态')
    completed_at = models.DateTimeField(null=True, blank=True, help_text='完成时间')

    # 操作人快照（姓名只展示，身份以账号ID为准；不使用FK避免跨库删除约束）
    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')
    created_by_id = models.IntegerField(null=True, blank=True, help_text='创建人ID')
    created_by_name = models.CharField(max_length=100, default='', help_text='创建人姓名快照')
    updated_at = models.DateTimeField(null=True, blank=True, help_text='更新时间')
    updated_by_id = models.IntegerField(null=True, blank=True, help_text='更新人ID')
    updated_by_name = models.CharField(max_length=100, default='', help_text='更新人姓名快照')

    # 软删除
    is_deleted = models.BooleanField(default=False, help_text='软删除标识')
    deleted_at = models.DateTimeField(null=True, blank=True, help_text='删除时间')
    deleted_by_id = models.IntegerField(null=True, blank=True, help_text='删除人ID')
    deleted_by_name = models.CharField(max_length=100, default='', help_text='删除人姓名快照')

    def is_overdue(self, now=None):
        if self.status != TASK_STATUS_IN_PROGRESS or not self.deadline:
            return False
        now = now or timezone.now()
        return now > self.deadline

    def to_view(self, now=None):
        now = now or timezone.now()
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'deadline': self.deadline.strftime('%Y-%m-%d %H:%M') if self.deadline else '',
            'status': self.status,
            'status_text': TASK_STATUS_TEXT.get(self.status, self.status),
            'is_overdue': self.is_overdue(now),
            'completed_at': self.completed_at.strftime('%Y-%m-%d %H:%M') if self.completed_at else '',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '',
            'created_by_name': self.created_by_name,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M') if self.updated_at else '',
            'updated_by_name': self.updated_by_name,
        }

    def __repr__(self):
        return '<CoopTask %s %s>' % (self.id, self.title)

    class Meta:
        db_table = 'tdyw_coop_tasks'
        verbose_name = '协作任务'
        verbose_name_plural = '协作任务'
        ordering = ('-id',)
        indexes = [
            models.Index(fields=['tenant_id', 'is_deleted', 'status'], name='coop_task_scope_idx'),
            models.Index(fields=['status', 'deadline'], name='coop_task_status_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(status__in=['in_progress', 'completed', 'voided']),
                name='coop_task_status_valid',
            ),
        ]


class CoopTaskItem(models.Model, TenantModelMixin):
    """材料清单子表（tdyw_coop_task_items）

    一次任务可要求多份材料；只交一份时即一行。随任务级联，不做独立软删除。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    task = models.ForeignKey(CoopTask, models.CASCADE, related_name='items', help_text='所属任务')
    name = models.CharField(max_length=TITLE_MAX_LEN, help_text='材料名称')
    remark = models.CharField(max_length=500, blank=True, default='', help_text='材料要求说明')
    sort_order = models.IntegerField(default=0, help_text='排序号')
    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')

    def to_view(self):
        return {
            'id': self.id,
            'task_id': self.task_id,
            'name': self.name,
            'remark': self.remark,
            'sort_order': self.sort_order,
        }

    def __repr__(self):
        return '<CoopTaskItem %s %s>' % (self.id, self.name)

    class Meta:
        db_table = 'tdyw_coop_task_items'
        verbose_name = '协作任务材料'
        verbose_name_plural = '协作任务材料'
        ordering = ('sort_order', 'id')
        indexes = [
            models.Index(fields=['task_id', 'sort_order', 'id'], name='coop_item_task_idx'),
        ]


class CoopTaskAssignment(models.Model, TenantModelMixin):
    """任务分派表（tdyw_coop_task_assignments）

    一行 = 任务 × 交付科室。tenant_id 记录创建人（发起方）租户，
    target_tenant_id 才是交付科室（交付方按此字段查询自己的待办）。
    科室级进度状态由 deliveries 实时聚合，不落库，避免状态同步问题。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    task = models.ForeignKey(CoopTask, models.CASCADE, related_name='assignments', help_text='所属任务')
    target_tenant_id = models.CharField(max_length=50, help_text='交付科室ID')
    target_tenant_name = models.CharField(max_length=100, default='', help_text='交付科室名称快照')
    contact_user_id = models.IntegerField(null=True, blank=True, help_text='交付科室账号ID（按账号分发的任务记录选定账号，旧数据为空）')
    contact_user_name = models.CharField(max_length=100, default='', help_text='交付科室账号人名快照（旧数据可能记录经办人备注）')

    # 催办记录
    urge_count = models.IntegerField(default=0, help_text='催办次数')
    last_urged_at = models.DateTimeField(null=True, blank=True, help_text='最近催办时间')
    urge_read_at = models.DateTimeField(null=True, blank=True, help_text='交付方最近查看时间（用于催办未读标记）')

    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')

    def has_unread_urge(self):
        if not self.last_urged_at:
            return False
        return not self.urge_read_at or self.urge_read_at < self.last_urged_at

    def __repr__(self):
        return '<CoopTaskAssignment %s task=%s tenant=%s>' % (self.id, self.task_id, self.target_tenant_id)

    class Meta:
        db_table = 'tdyw_coop_task_assignments'
        verbose_name = '协作任务分派'
        verbose_name_plural = '协作任务分派'
        ordering = ('id',)
        constraints = [
            models.UniqueConstraint(
                fields=['task', 'target_tenant_id'],
                name='uniq_coop_assignment_task_tenant',
            ),
        ]
        indexes = [
            models.Index(fields=['target_tenant_id'], name='coop_assign_target_idx'),
            models.Index(fields=['task_id', 'target_tenant_id'], name='coop_assign_task_idx'),
        ]


class CoopTaskDelivery(models.Model, TenantModelMixin):
    """交付明细表（tdyw_coop_task_deliveries）

    一行 = 分派 × 材料，即进度矩阵中的一个格子。附件挂在交付明细上
    （EvidenceAttachment module='coop_task', object_type='delivery'）。
    行由发起方创建任务时预生成；附件的 tenant_id 才是上传方（交付科室）租户。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    assignment = models.ForeignKey(CoopTaskAssignment, models.CASCADE, related_name='deliveries', help_text='所属分派')
    item = models.ForeignKey(CoopTaskItem, models.CASCADE, related_name='deliveries', help_text='对应材料')

    status = models.CharField(
        max_length=20, choices=DELIVERY_STATUS_CHOICES, default=DELIVERY_PENDING, help_text='交付状态')
    submitted_at = models.DateTimeField(null=True, blank=True, help_text='最近提交时间')
    submitter_id = models.IntegerField(null=True, blank=True, help_text='提交人账号ID')
    submitter_name = models.CharField(max_length=100, default='', help_text='提交人姓名快照')

    accepted_at = models.DateTimeField(null=True, blank=True, help_text='验收时间')
    accepted_by_id = models.IntegerField(null=True, blank=True, help_text='验收人账号ID')
    accepted_by_name = models.CharField(max_length=100, default='', help_text='验收人姓名快照')
    reject_reason = models.CharField(max_length=REJECT_REASON_MAX_LEN, blank=True, default='', help_text='退回原因')

    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')
    updated_at = models.DateTimeField(auto_now=True, help_text='更新时间')

    def to_view(self):
        return {
            'id': self.id,
            'assignment_id': self.assignment_id,
            'item_id': self.item_id,
            'status': self.status,
            'status_text': DELIVERY_STATUS_TEXT.get(self.status, self.status),
            'submitted_at': self.submitted_at.strftime('%Y-%m-%d %H:%M') if self.submitted_at else '',
            'submitter_name': self.submitter_name,
            'accepted_at': self.accepted_at.strftime('%Y-%m-%d %H:%M') if self.accepted_at else '',
            'accepted_by_name': self.accepted_by_name,
            'reject_reason': self.reject_reason,
        }

    def __repr__(self):
        return '<CoopTaskDelivery %s assignment=%s item=%s>' % (self.id, self.assignment_id, self.item_id)

    class Meta:
        db_table = 'tdyw_coop_task_deliveries'
        verbose_name = '协作任务交付明细'
        verbose_name_plural = '协作任务交付明细'
        ordering = ('id',)
        constraints = [
            models.UniqueConstraint(
                fields=['assignment', 'item'],
                name='uniq_coop_delivery_assignment_item',
            ),
            models.CheckConstraint(
                check=models.Q(status__in=['pending', 'submitted', 'accepted', 'rejected']),
                name='coop_delivery_status_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['assignment_id', 'status'], name='coop_dlvy_assign_idx'),
            models.Index(fields=['status'], name='coop_dlvy_status_idx'),
        ]

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""部门值班日志 - 数据模型

全局共享业务表，不设置 tenant_id，不做租户隔离。
值班人员固定为当前登录用户，不支持代填/代签。
生命周期：draft -> signed（管理员可退回已签记录到草稿）
"""
from django.db import models

from libs import ModelMixin
from django.utils import timezone


# ==================== 状态常量 ====================
STATUS_DRAFT = 'draft'
STATUS_SIGNED = 'signed'

STATUS_CHOICES = (
    (STATUS_DRAFT, '草稿'),
    (STATUS_SIGNED, '已签署'),
)


class DepartmentDutyLog(models.Model, ModelMixin):
    """部门值班日志（全局共享，不按租户隔离）"""

    # ---- 填报基本信息 ----
    duty_date = models.DateField(help_text='值班日期 YYYY-MM-DD')
    duty_person = models.ForeignKey(
        'account.User', on_delete=models.PROTECT, related_name='+',
        help_text='值班人员，固定为创建时的当前登录用户')
    duty_person_name = models.CharField(max_length=100, help_text='值班人员姓名快照')

    # ---- 环境参数（文本原文保存，不解析数值）----
    weather = models.CharField(max_length=50, blank=True, help_text='天气情况简述', default='')

    # ---- 值班记录 ----
    duty_record = models.TextField(help_text='当班情况，必填')
    remark = models.TextField(blank=True, help_text='上级工作要求', default='')

    # ---- 状态与版本 ----
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, help_text='签署状态')
    version = models.PositiveIntegerField(default=1, help_text='乐观锁版本号，每次编辑/签署加 1')

    # ---- 同日唯一签署约束的辅助字段 ----
    # signed 时由服务层写入 duty_date，draft 时必须为 NULL。
    # 唯一索引（MariaDB 允许唯一索引中存在多个 NULL）保证：全局最多只有一条
    # signed 记录占用同一日期；退回草稿时置 NULL 即释放该日期。
    # 只能由服务层维护，客户端提交该字段一律拒绝（PROTECTED_FIELDS）。
    signed_date = models.DateField(
        null=True, blank=True, unique=True,
        help_text='签署占用日期：signed 时等于 duty_date，draft 时为 NULL；同日唯一约束的载体')

    # ---- 签署快照（签署后锁定，不可覆盖）----
    signature_usage_id = models.BigIntegerField(
        null=True, blank=True, unique=True, help_text='关联不可变 SignatureUsage.id')
    signed_by = models.ForeignKey(
        'account.User', on_delete=models.PROTECT, related_name='+',
        null=True, blank=True, help_text='签署人，必须与值班人员一致')
    signed_by_name = models.CharField(max_length=100, blank=True, help_text='签署人姓名快照', default='')
    signed_at = models.DateTimeField(null=True, blank=True, help_text='服务器签署时间')
    signature_version = models.PositiveIntegerField(null=True, blank=True, help_text='签署时签名版本')
    signature_sha256 = models.CharField(max_length=64, blank=True, help_text='签名图片 SHA256 快照', default='')
    business_snapshot_hash = models.CharField(max_length=64, blank=True, help_text='业务快照哈希', default='')

    # ---- 更正关系（预留，当前未使用） ----
    supersedes = models.ForeignKey(
        'self', on_delete=models.PROTECT, related_name='corrections',
        null=True, blank=True, help_text='更正时指向被更正的记录')

    # ---- 审计字段 ----
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'account.User', on_delete=models.PROTECT, related_name='+', help_text='创建人')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        'account.User', on_delete=models.PROTECT, related_name='+',
        null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True, help_text='非空表示已软删除')
    deleted_by = models.ForeignKey(
        'account.User', on_delete=models.PROTECT, related_name='+',
        null=True, blank=True)

    def __repr__(self):
        return '<DepartmentDutyLog id=%r date=%r status=%r>' % (self.id, self.duty_date, self.status)

    class Meta:
        db_table = 'tdyw_department_duty_log'
        verbose_name = '部门值班日志'
        verbose_name_plural = '部门值班日志'
        ordering = ('-duty_date', '-id')
        indexes = [
            models.Index(
                fields=['status', 'deleted_at', 'duty_date'],
                name='department_duty_status_date_ix',
            ),
            models.Index(
                fields=['duty_person', 'duty_date'],
                name='department_duty_person_date_ix',
            ),
            # P0(R11): 独立 duty_date 索引，解决复合索引最左前缀违反
            # 大多数查询直接按 duty_date 过滤（不按 status），需独立索引
            models.Index(
                fields=['-duty_date', '-id'],
                name='duty_log_date_idx',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(status__in=[item[0] for item in STATUS_CHOICES]),
                name='duty_log_status_valid',
            ),
            models.CheckConstraint(
                check=models.Q(version__gte=1),
                name='duty_log_version_valid',
            ),
            # 签署状态不变量：
            # DRAFT -> 签署字段全部为空（可空字段 NULL + CharField 空串）
            # SIGNED -> 签署字段全部完整 且 signed_by_id == duty_person_id
            models.CheckConstraint(
                check=(
                    (
                        models.Q(status=STATUS_DRAFT) &
                        models.Q(signature_usage_id__isnull=True) &
                        models.Q(signed_by_id__isnull=True) &
                        models.Q(signed_at__isnull=True) &
                        models.Q(signature_version__isnull=True) &
                        (models.Q(signed_by_name='') | models.Q(signed_by_name__isnull=True)) &
                        (models.Q(signature_sha256='') | models.Q(signature_sha256__isnull=True)) &
                        (models.Q(business_snapshot_hash='') | models.Q(business_snapshot_hash__isnull=True))
                    ) | (
                        models.Q(status=STATUS_SIGNED) &
                        models.Q(signature_usage_id__isnull=False) &
                        models.Q(signed_by_id__isnull=False) &
                        models.Q(signed_at__isnull=False) &
                        models.Q(signature_version__isnull=False) &
                        ~models.Q(signed_by_name='') &
                        ~models.Q(signature_sha256='') &
                        ~models.Q(business_snapshot_hash='') &
                        models.Q(signed_by_id=models.F('duty_person_id'))
                    )
                ),
                name='duty_log_signature_fields',
            ),
            # signed_date 与 status/duty_date 的一致性约束（防静默漂移）：
            # draft -> signed_date 必须为 NULL（草稿不占用日期）
            # signed -> signed_date 必须非空且等于 duty_date（由唯一索引保证同日唯一）
            # 注意 MariaDB CHECK 三值逻辑：signed_date 与 duty_date 的等值比较
            # 在 signed_date 为 NULL 时结果是 UNKNOWN 而非 FALSE，CHECK 对
            # UNKNOWN 放行，因此必须显式加 signed_date IS NOT NULL 前置条件
            # （IS NOT NULL 判定永不返回 UNKNOWN）。
            models.CheckConstraint(
                check=(
                    (
                        models.Q(status=STATUS_DRAFT) &
                        models.Q(signed_date__isnull=True)
                    ) | (
                        models.Q(status=STATUS_SIGNED) &
                        models.Q(signed_date__isnull=False) &
                        models.Q(signed_date=models.F('duty_date'))
                    )
                ),
                name='duty_log_signed_date_valid',
            ),
        ]

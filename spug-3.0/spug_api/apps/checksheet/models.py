# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from libs import human_datetime
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
import json


class CheckSheetTemplate(models.Model):
    """检查表模板"""
    # P0-3 修复：project 增加唯一约束，避免同名模板导致
    # CheckSheetTemplate.objects.get(project=...) 抛 MultipleObjectsReturned (500)
    project = models.CharField('项目名称', max_length=100, unique=True)
    check_items = models.TextField('检查项目列表', default='[]')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'tdyw_checksheet_template'
        verbose_name = '检查表模板'
        verbose_name_plural = verbose_name
        ordering = ['created_at']

    def __str__(self):
        items = json.loads(self.check_items) if isinstance(self.check_items, str) else self.check_items
        return f'{self.project} ({len(items)}项)'

    def get_check_items(self):
        """获取检查项目列表"""
        if isinstance(self.check_items, str):
            return json.loads(self.check_items)
        return self.check_items

    def set_check_items(self, items):
        """设置检查项目列表"""
        self.check_items = json.dumps(items, ensure_ascii=False)


# ==================== 证据闭环：提交批次状态 ====================
SUBMISSION_STATUS_CHOICES = (
    ('draft', '草稿'),
    ('submitted', '已提交'),
    ('reviewed', '已复核'),
    ('closed', '已归档'),
    ('voided', '已作废'),
)
# 可编辑状态集合（draft 可自由保存；其他状态核心字段锁定）
EDITABLE_STATUSES = {'draft'}
# 状态流转合法路径
SUBMISSION_TRANSITIONS = {
    'draft': {'submitted', 'voided'},
    'submitted': {'reviewed', 'draft'},  # 驳回回 draft
    'reviewed': {'closed', 'draft'},     # 驳回回 draft
    'closed': {'voided'},                # 归档后只能作废
    'voided': set(),                     # 终态
}


class CheckSheetSubmission(models.Model, TenantModelMixin):
    """检查单提交批次表（证据闭环第三阶段）

    以"项目+年+月"为一个提交批次，状态流转：
    draft → submitted → reviewed → closed
                                 ↘ voided（作废）

    状态规则：
    - draft：可自由保存检查记录
    - submitted：核心字段锁定，等待复核
    - reviewed：复核通过，可归档
    - closed：归档锁定，只能发起更正或作废
    - voided：终态，不物理删除
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    # ---- 业务定位 ----
    project = models.CharField('项目名称', max_length=100)
    year = models.CharField('年份', max_length=4)
    month = models.CharField('月份', max_length=2)
    status = models.CharField('状态', max_length=20, choices=SUBMISSION_STATUS_CHOICES, default='draft')

    # ---- 提交人身份快照 ----
    submitted_by_id = models.IntegerField('提交人ID', null=True, blank=True)
    submitted_by_name = models.CharField('提交人姓名快照', max_length=100, default='')
    submitted_at = models.CharField('提交时间', max_length=20, null=True, blank=True)

    # ---- 复核人身份快照 ----
    reviewed_by_id = models.IntegerField('复核人ID', null=True, blank=True)
    reviewed_by_name = models.CharField('复核人姓名快照', max_length=100, default='')
    reviewed_at = models.CharField('复核时间', max_length=20, null=True, blank=True)
    review_comment = models.TextField('复核意见', blank=True, null=True)

    # ---- 作废 ----
    voided_by_id = models.IntegerField('作废人ID', null=True, blank=True)
    voided_by_name = models.CharField('作废人姓名快照', max_length=100, default='')
    voided_at = models.CharField('作废时间', max_length=20, null=True, blank=True)
    void_reason = models.CharField('作废原因', max_length=500, default='')

    # ---- 快照哈希（提交时计算，证明提交后未被篡改）----
    snapshot_hash = models.CharField('提交快照哈希', max_length=64, default='')

    # ---- 时间 ----
    created_at = models.CharField('创建时间', max_length=20, default=human_datetime)
    updated_at = models.CharField('更新时间', max_length=20, null=True, blank=True)

    class Meta:
        db_table = 'tdyw_checksheet_submission'
        verbose_name = '检查单提交批次'
        verbose_name_plural = verbose_name
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['tenant_id', 'project', 'year', 'month'], name='cs_sub_obj_idx'),
            models.Index(fields=['tenant_id', 'status'], name='cs_sub_status_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'project', 'year', 'month'],
                name='uniq_cs_submission_period',
            ),
            models.CheckConstraint(
                check=models.Q(status__in=[item[0] for item in SUBMISSION_STATUS_CHOICES]),
                name='cs_submission_status_valid',
            ),
            models.CheckConstraint(
                check=models.Q(month__in=[f'{month:02d}' for month in range(1, 13)]),
                name='cs_submission_month_valid',
            ),
            # 一旦进入提交后的状态，提交身份、时间和快照必须同时存在。
            models.CheckConstraint(
                check=(
                    models.Q(status__in=['draft', 'voided']) |
                    (
                        models.Q(submitted_by_id__isnull=False) &
                        models.Q(submitted_at__isnull=False) &
                        ~models.Q(submitted_by_name='') &
                        ~models.Q(snapshot_hash='')
                    )
                ),
                name='cs_submission_submit_fields',
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(status__in=['reviewed', 'closed']) |
                    (
                        models.Q(reviewed_by_id__isnull=False) &
                        models.Q(reviewed_at__isnull=False) &
                        ~models.Q(reviewed_by_name='')
                    )
                ),
                name='cs_submission_review_fields',
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(status='voided') |
                    (
                        models.Q(voided_by_id__isnull=False) &
                        models.Q(voided_at__isnull=False) &
                        ~models.Q(voided_by_name='') &
                        ~models.Q(void_reason='')
                    )
                ),
                name='cs_submission_void_fields',
            ),
        ]

    def __str__(self):
        return f'{self.project} {self.year}-{self.month} [{self.status}]'

    def can_edit(self):
        """是否可编辑检查记录（仅 draft 状态可编辑）"""
        return self.status in EDITABLE_STATUSES

    def can_transition_to(self, new_status):
        """状态流转是否合法"""
        return new_status in SUBMISSION_TRANSITIONS.get(self.status, set())


class CheckSheetRecord(models.Model):
    """检查记录"""
    template = models.ForeignKey(CheckSheetTemplate, on_delete=models.CASCADE, verbose_name='检查模板')
    year = models.CharField('年份', max_length=4)
    month = models.CharField('月份', max_length=2)
    day = models.IntegerField('日期')
    item_index = models.IntegerField('检查项索引')
    status = models.CharField('状态', max_length=10,
                            choices=[('NORMAL', '正常'), ('ABNORMAL', '异常'), ('UNCHECKED', '未检查')],
                            default='UNCHECKED')
    remark = models.TextField('备注', blank=True, null=True)
    rectification = models.TextField('发现问题及整改情况', blank=True, null=True)
    operator = models.CharField('操作人', max_length=50, blank=True, null=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    # ==== 证据闭环：身份快照（保留 operator 文本字段兼容旧数据）====
    operator_user_id = models.IntegerField('操作人账号ID', null=True, blank=True)
    operator_name_snapshot = models.CharField('操作人姓名快照', max_length=100, default='')
    operator_department_snapshot = models.CharField('操作人部门快照', max_length=100, default='')
    submitted_at = models.CharField('提交时间快照', max_length=20, null=True, blank=True)

    class Meta:
        db_table = 'tdyw_checksheet_record'
        verbose_name = '检查记录'
        verbose_name_plural = verbose_name
        ordering = ['year', 'month', 'day', 'item_index']
        unique_together = ['template', 'year', 'month', 'day', 'item_index']
        constraints = [
            models.CheckConstraint(
                check=models.Q(month__in=[f'{month:02d}' for month in range(1, 13)]),
                name='cs_record_month_valid',
            ),
            models.CheckConstraint(
                check=models.Q(day__gte=1, day__lte=31),
                name='cs_record_day_valid',
            ),
            models.CheckConstraint(
                check=models.Q(item_index__gte=0),
                name='cs_record_item_index_valid',
            ),
            models.CheckConstraint(
                check=models.Q(status__in=['NORMAL', 'ABNORMAL', 'UNCHECKED']),
                name='cs_record_status_valid',
            ),
        ]

    def __str__(self):
        return f'{self.template.project} {self.year}-{self.month}-{self.day} 第{self.item_index + 1}项'


class CheckSheetDailySummary(models.Model):
    """每日检查汇总 - 存储每天的备注、整改情况和值班人员"""
    year = models.CharField('年份', max_length=4)
    month = models.CharField('月份', max_length=2)
    day = models.IntegerField('日期')
    operator = models.CharField('值班人员', max_length=50, blank=True, null=True)
    remark = models.TextField('备注', blank=True, null=True)
    rectification = models.TextField('发现问题及整改情况', blank=True, null=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    # ==== 证据闭环：身份快照 ====
    operator_user_id = models.IntegerField('值班人员账号ID', null=True, blank=True)
    operator_name_snapshot = models.CharField('值班人员姓名快照', max_length=100, default='')

    class Meta:
        db_table = 'tdyw_checksheet_daily_summary'
        verbose_name = '每日检查汇总'
        verbose_name_plural = verbose_name
        unique_together = ['year', 'month', 'day']
        constraints = [
            models.CheckConstraint(
                check=models.Q(month__in=[f'{month:02d}' for month in range(1, 13)]),
                name='cs_summary_month_valid',
            ),
            models.CheckConstraint(
                check=models.Q(day__gte=1, day__lte=31),
                name='cs_summary_day_valid',
            ),
        ]

    def __str__(self):
        return f'{self.year}-{self.month}-{self.day} 汇总'

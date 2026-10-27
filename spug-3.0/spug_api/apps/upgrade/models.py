# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
系统升级模块模型

升级记录/升级方案通过正式外键关联系统档案（equipment_lifecycle.LifecycleSystem），
并保存系统编号/名称/安装地点快照；请求与存储一律用系统 ID，页面只显示名称，
快照仅用于历史展示，不替代正式外键（对齐故障处置/运维台账的挂接模式）。
历史未匹配到系统档案的记录允许 system 外键为空，仅保留 system_name 文本。
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
    upgrade_no = models.CharField(
        max_length=50,
        help_text='升级编号（SJ+创建日期+当日四位序号，自动生成；当日序号跨租户共享，'
                  '由 RecordService.create_record 等创建入口在 upgrade_record_no '
                  '全局锁内分配，存量历史数据由迁移 0023 按创建日期回填）')
    title = models.CharField(max_length=200, default='', verbose_name='标题')
    system = models.ForeignKey(
        'equipment_lifecycle.LifecycleSystem', models.PROTECT, related_name='upgrade_records',
        null=True, blank=True,
        help_text='升级系统（正式系统 ID；历史未匹配记录允许为空）')
    system_code = models.CharField(
        max_length=50, default='', blank=True, verbose_name='系统编号快照')
    system_name = models.CharField(
        max_length=100, default='', blank=True, verbose_name='系统名称快照')
    system_location = models.CharField(
        max_length=200, default='', blank=True, verbose_name='系统安装地点快照')
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
        return '<UpgradeRecord %r>' % self.title

    class Meta:
        db_table = 'tdyw_upgrade_records'
        verbose_name = '升级记录'
        verbose_name_plural = '升级记录'
        ordering = ('-upgrade_time', '-id',)
        constraints = [
            # 编号为创建入口自动分配；唯一约束仅作并发兜底（正常路径由
            # upgrade_record_no 全局锁 + 跨租户当日序号保证唯一）
            models.UniqueConstraint(fields=['tenant_id', 'upgrade_no'],
                                    name='uniq_upgrade_tenant_no'),
        ]
        indexes = [
            models.Index(fields=['tenant_id', 'status']),
            # 默认列表分页：tenant_id + 计划升级时间倒序 + id
            models.Index(fields=['tenant_id', 'upgrade_time', 'id'], name='upg_rec_time_idx'),
            # 状态精确筛选 + 时间排序（status 为列表高频筛选字段）
            models.Index(fields=['tenant_id', 'status', 'upgrade_time', 'id'], name='upg_rec_status_time_idx'),
            # 升级类型精确筛选 + 时间排序（upgrade_type 为列表高频筛选字段）
            models.Index(fields=['tenant_id', 'upgrade_type', 'upgrade_time', 'id'], name='upg_rec_type_time_idx'),
            # 按系统查询（系统详情"升级记录"页签）
            models.Index(fields=['tenant_id', 'system'], name='upg_rec_system_idx'),
        ]







# 导入升级方案模型（原升级模板+步骤清单合并），确保 Django 发现
from .models_template import UpgradeTemplate, UpgradePlanStep  # noqa: E402, F401
# 导入升级记录步骤模型，确保 Django 发现
from .models_checklist import UpgradeRecordStep  # noqa: E402, F401
# 导入升级状态日志模型，确保 Django 发现
from .models_status_log import UpgradeStatusLog  # noqa: E402, F401
# 导入升级失败处理单模型，确保 Django 发现
from .models_failure import UpgradeFailureHandling  # noqa: E402, F401

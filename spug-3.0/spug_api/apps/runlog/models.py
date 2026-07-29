# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import json
from django.db import models
from django.utils import timezone
from libs.mixins import ModelMixin
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
from apps.account.models import User


class RunLog(models.Model, TenantModelMixin):
    """运行日志事件表（闭环管理）"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    SEVERITY_CHOICES = ('P0', 'P1', 'P2')
    STATUS_CHOICES = ('in_progress', 'resolved', 'verified', 'closed', 'voided')
    
    # === 事件基本信息 ===
    event_title = models.CharField(max_length=200, help_text='事件标题')
    event_type = models.CharField(max_length=50, help_text='事件类型：运行异常/设备故障/安全事件/其他')
    system_name = models.CharField(max_length=100, help_text='关联系统名称')
    
    # === 事件级别与状态 ===
    severity = models.CharField(max_length=10, default='P2',
                                 help_text='事件级别：P0紧急/P1重要/P2一般')
    status = models.CharField(max_length=20, default='in_progress',
                             help_text='事件状态：in_progress处理中/resolved已解决/verified已验证/closed已归档/voided已作废')
    
    # === 责任与时效 ===
    responsible_user_id = models.IntegerField(null=True, blank=True)
    responsible_user_name = models.CharField(max_length=100, blank=True, default='')
    
    # === 处理结果 ===
    resolution = models.TextField(blank=True, help_text='处理措施总结（事件解决后的最终方案总结，与动态记录不同，此处填写结案报告）', default='')
    verifier_id = models.IntegerField(null=True, blank=True)
    verifier_name = models.CharField(max_length=100, blank=True, default='')
    verified_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # ==== 证据闭环：快照哈希 + 验证人身份快照 ====
    # 关闭/验证时计算快照哈希，证明归档时内容未被篡改
    snapshot_hash = models.CharField(max_length=64, default='', help_text='归档快照哈希(SHA256)')
    verified_by_id = models.IntegerField(null=True, blank=True, help_text='验证人账号ID（已废弃 verifier_id 仍保留）')
    
    # === 统计字段 ===
    update_count = models.IntegerField(default=0, help_text='动态数量')
    first_update_date = models.DateField(null=True, blank=True, help_text='首次动态日期')
    last_update_date = models.DateField(null=True, blank=True, help_text='最后动态日期')
    
    # === 时间戳 ===
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<RunLog %r>' % self.event_title

    def to_view(self):
        tmp = self.to_dict()
        # 添加状态和级别文本
        status_map = {
            'in_progress': '处理中',
            'resolved': '已解决',
            'verified': '已验证',
            'closed': '已归档',
            'voided': '已作废',
        }
        severity_map = {
            'P0': '紧急',
            'P1': '重要',
            'P2': '一般'
        }
        tmp['status_text'] = status_map.get(self.status, self.status)
        tmp['severity_text'] = severity_map.get(self.severity, self.severity)
        return tmp

    class Meta:
        managed = True  # 由 Django 管理表结构
        db_table = 'tdyw_run_logs'
        verbose_name = '运行日志'
        verbose_name_plural = '运行日志'
        ordering = ('-created_at', '-id')
        indexes = [
            models.Index(fields=['tenant_id', 'status']),
            models.Index(fields=['tenant_id', 'severity']),
            models.Index(fields=['tenant_id', '-created_at', '-id'], name='runlog_t_ctime_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(severity__in=['P0', 'P1', 'P2']),
                name='runlog_severity_valid',
            ),
            models.CheckConstraint(
                check=models.Q(status__in=['in_progress', 'resolved', 'verified', 'closed', 'voided']),
                name='runlog_status_valid',
            ),
            models.CheckConstraint(
                check=models.Q(update_count__gte=0),
                name='runlog_update_count_valid',
            ),
            models.CheckConstraint(
                check=models.Q(last_update_date__isnull=True) |
                      models.Q(first_update_date__isnull=True) |
                      models.Q(last_update_date__gte=models.F('first_update_date')),
                name='runlog_update_date_order',
            ),
        ]


class RunLogUpdate(models.Model, TenantModelMixin):
    """运行日志动态表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    
    # 关联事件
    runlog_id = models.IntegerField(help_text='关联事件ID')
    event_title = models.CharField(max_length=200, help_text='事件标题（冗余）')
    
    # 动态内容
    update_date = models.DateField(help_text='动态日期（精确到日）')
    sequence = models.IntegerField(default=0, help_text='同一天内的序号')
    recorder = models.CharField(max_length=100, help_text='记录人')
    detail_content = models.TextField(help_text='详细记录')
    duty_person = models.CharField(max_length=128, blank=True, help_text='值班人', default='')

    # 附件（图片）
    attachments = models.TextField(blank=True, help_text='附件JSON，存储图片路径列表', default='')

    # 修改权限控制
    editable_until = models.DateTimeField(help_text='可修改截止时间（创建后24小时内）')

    # ==== 证据闭环：动态类型 + 更正 + 作废 ====
    UPDATE_TYPE_CHOICES = (
        ('normal', '普通动态'),
        ('correction', '更正说明'),
        ('supplement', '补充说明'),
        ('system', '系统记录'),
    )
    update_type = models.CharField(max_length=20, default='normal', choices=UPDATE_TYPE_CHOICES,
                                   help_text='动态类型：normal/correction/supplement/system')
    corrected_update_id = models.IntegerField(null=True, blank=True, help_text='更正指向的原动态ID')
    is_voided = models.BooleanField(default=False, help_text='是否已作废')
    void_reason = models.CharField(max_length=500, default='', blank=True, help_text='作废原因')
    
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')

    def can_edit(self, user):
        """判断动态是否可修改

        规则：创建者或超级管理员在 24 小时内可编辑。
        """
        # 创建者或超级管理员可修改（需在 24 小时内）
        if self.created_by_id == user.id or user.is_supper:
            from django.utils import timezone
            return timezone.now() < self.editable_until
        return False

    def to_view(self, user=None):
        tmp = self.to_dict()
        # 将 attachments 从 JSON 字符串解析为数组
        if isinstance(tmp.get('attachments'), str):
            try:
                parsed = json.loads(tmp['attachments'])
                tmp['attachments'] = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                tmp['attachments'] = []
        elif tmp.get('attachments') is None:
            tmp['attachments'] = []
        # 添加是否可编辑标识
        if user is not None:
            # 完整校验：创建者/超级管理员 + 24小时内
            tmp['can_edit'] = self.can_edit(user)
        else:
            # 兜底：仅按时间判断（向后兼容无 user 参数的调用方，如 PDF 导出）
            from django.utils import timezone
            tmp['can_edit'] = timezone.now() < self.editable_until
        return tmp

    class Meta:
        db_table = 'tdyw_run_log_updates'
        verbose_name = '运行日志动态'
        verbose_name_plural = '运行日志动态'
        ordering = ('update_date', 'sequence', 'id')
        indexes = [
            models.Index(fields=['tenant_id', 'runlog_id']),
            models.Index(fields=['update_date']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(sequence__gte=0),
                name='runlog_update_sequence_valid',
            ),
            models.CheckConstraint(
                check=models.Q(update_type__in=['normal', 'correction', 'supplement', 'system']),
                name='runlog_update_type_valid',
            ),
            models.CheckConstraint(
                check=models.Q(is_voided=False) | ~models.Q(void_reason=''),
                name='runlog_update_void_reason',
            ),
        ]


class EventTypeConfig(models.Model, ModelMixin):
    """事件类型配置表（全局配置，所有租户共享）"""

    name = models.CharField(max_length=50, unique=True, help_text='类型名称')
    is_active = models.BooleanField(default=True, help_text='是否启用')
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')

    def __repr__(self):
        return f'<EventTypeConfig {self.name}>'

    def to_view(self):
        return self.to_dict()

    class Meta:
        db_table = 'tdyw_run_log_event_types'
        verbose_name = '事件类型配置'
        verbose_name_plural = '事件类型配置'
        ordering = ('id',)
        indexes = [
            models.Index(fields=['is_active']),
        ]

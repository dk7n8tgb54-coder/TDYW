# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import json
from django.db import models
from libs import human_datetime
from libs.mixins import ModelMixin
from libs.tenant_base_model import TenantModelMixin, TenantModelManager, make_tenant_id
from apps.account.models import User


class RunLog(models.Model, TenantModelMixin):
    """运行日志事件表（闭环管理）"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    
    # === 事件基本信息 ===
    event_title = models.CharField(max_length=200, help_text='事件标题')
    event_type = models.CharField(max_length=50, help_text='事件类型：运行异常/设备故障/安全事件/其他')
    system_name = models.CharField(max_length=100, help_text='关联系统名称')
    
    # === 事件级别与状态 ===
    severity = models.CharField(max_length=10, default='P2',
                                 help_text='事件级别：P0紧急/P1重要/P2一般')
    status = models.CharField(max_length=20, default='in_progress',
                             help_text='事件状态：in_progress处理中/resolved已解决')
    
    # === 责任与时效 ===
    responsible_user_id = models.IntegerField(null=True, blank=True)
    responsible_user_name = models.CharField(max_length=100, null=True, blank=True)
    
    # === 处理结果 ===
    resolution = models.TextField(null=True, blank=True, help_text='处理措施总结（事件解决后的最终方案总结，与动态记录不同，此处填写结案报告）')
    verifier_id = models.IntegerField(null=True, blank=True)
    verifier_name = models.CharField(max_length=100, null=True, blank=True)
    verified_at = models.CharField(max_length=20, null=True, blank=True)
    closed_at = models.CharField(max_length=20, null=True, blank=True)
    
    # === 统计字段 ===
    update_count = models.IntegerField(default=0, help_text='动态数量')
    first_update_date = models.CharField(max_length=20, null=True, blank=True, help_text='首次动态日期')
    last_update_date = models.CharField(max_length=20, null=True, blank=True, help_text='最后动态日期')
    
    # === 时间戳 ===
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def __repr__(self):
        return '<RunLog %r>' % self.event_title

    def to_view(self):
        tmp = self.to_dict()
        # 添加状态和级别文本
        status_map = {
            'in_progress': '处理中',
            'resolved': '已解决',
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
        ]


class RunLogUpdate(models.Model, TenantModelMixin):
    """运行日志动态表"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    
    # 关联事件
    runlog_id = models.IntegerField(help_text='关联事件ID')
    event_title = models.CharField(max_length=200, help_text='事件标题（冗余）')
    
    # 动态内容
    update_date = models.CharField(max_length=20, help_text='动态日期（精确到日）')
    sequence = models.IntegerField(default=0, help_text='同一天内的序号')
    recorder = models.CharField(max_length=100, help_text='记录人')
    detail_content = models.TextField(help_text='详细记录')

    # 附件（图片）
    attachments = models.TextField(null=True, blank=True, help_text='附件JSON，存储图片路径列表')

    # 修改权限控制
    editable_until = models.CharField(max_length=20, help_text='可修改截止时间（创建后24小时内）')
    
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')

    def can_edit(self, user):
        """判断动态是否可修改"""
        # 创建者和管理员始终可修改
        if self.created_by_id == user.id or user.is_superuser:
            from datetime import datetime
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            return now < self.editable_until
        return False

    def to_view(self):
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
        # 添加是否可编辑标识 - 比较时间戳字符串
        from datetime import datetime
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        tmp['can_edit'] = now < self.editable_until
        return tmp

    class Meta:
        db_table = 'tdyw_run_log_updates'
        verbose_name = '运行日志动态'
        verbose_name_plural = '运行日志动态'
        ordering = ('update_date', 'sequence', 'id')
        indexes = [
            models.Index(fields=['runlog_id']),
            models.Index(fields=['tenant_id', 'runlog_id']),
            models.Index(fields=['update_date']),
        ]


class EventTypeConfig(models.Model, ModelMixin):
    """事件类型配置表（全局配置，所有租户共享）"""

    name = models.CharField(max_length=50, unique=True, help_text='类型名称')
    is_active = models.BooleanField(default=True, help_text='是否启用')
    created_at = models.CharField(max_length=20, default=human_datetime)
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

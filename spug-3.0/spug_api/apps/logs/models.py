# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

from django.db import models
from libs.mixins import ModelMixin
from libs.utils import human_datetime


class AuditLog(models.Model, ModelMixin):
    """操作审计日志模型"""
    ACTION_CHOICES = [
        ('create', '创建'),
        ('update', '更新'),
        ('delete', '删除'),
        ('login', '登录'),
        ('logout', '登出'),
        ('export', '导出'),
        ('import', '导入'),
        ('approve', '审批'),
        ('other', '其他'),
    ]

    user_id = models.IntegerField()
    username = models.CharField(max_length=100)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    target_type = models.CharField(max_length=50)
    target_id = models.CharField(max_length=50, null=True)
    target_name = models.CharField(max_length=255, null=True)
    detail = models.TextField(null=True)
    ip = models.CharField(max_length=50)
    is_success = models.BooleanField(default=True)
    tenant_id = models.CharField(max_length=50, null=True, default='default')
    created_at = models.CharField(max_length=20, default=human_datetime)

    class Meta:
        db_table = 'audit_logs'
        ordering = ('-id',)

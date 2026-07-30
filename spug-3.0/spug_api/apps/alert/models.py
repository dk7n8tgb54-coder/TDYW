# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License
from django.db import models
from libs.mixins import ModelMixin


class Alert(models.Model, ModelMixin):
    LEVEL_ERROR = 'error'
    LEVEL_WARNING = 'warning'
    LEVEL_INFO = 'info'
    LEVEL_CHOICES = (
        (LEVEL_ERROR, '严重'),
        (LEVEL_WARNING, '警告'),
        (LEVEL_INFO, '提示'),
    )

    STATUS_ACTIVE = 'active'
    STATUS_RESOLVED = 'resolved'
    STATUS_CHOICES = (
        (STATUS_ACTIVE, '待处理'),
        (STATUS_RESOLVED, '已处理'),
    )

    title = models.CharField(max_length=200)
    message = models.TextField(default='', blank=True)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    source = models.CharField(max_length=50, default='', blank=True, db_index=True)
    alert_key = models.CharField(max_length=255, default='', blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        'account.User', models.PROTECT, related_name='+', null=True, blank=True
    )

    class Meta:
        db_table = 'alerts'
        ordering = ('-created_at', '-id')
        indexes = [
            models.Index(fields=['status', 'created_at'], name='alert_status_time_idx'),
            models.Index(fields=['level', 'status'], name='alert_level_status_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(level__in=['error', 'warning', 'info']),
                name='alert_level_valid',
            ),
            models.CheckConstraint(
                check=models.Q(status__in=['active', 'resolved']),
                name='alert_status_valid',
            ),
        ]


class AlertRead(models.Model):
    alert = models.ForeignKey(Alert, models.CASCADE, related_name='reads')
    user_id = models.IntegerField(db_index=True)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'alert_reads'
        ordering = ('-read_at', '-id')
        constraints = [
            models.UniqueConstraint(
                fields=['alert_id', 'user_id'],
                name='uniq_alert_read_user',
            ),
        ]

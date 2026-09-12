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


class HealthProbeSample(models.Model):
    """外部探活原始样本；写入者应位于应用容器之外。"""
    timestamp = models.DateTimeField(unique=True)
    success = models.BooleanField(default=False)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    error_type = models.CharField(max_length=80, default='', blank=True)

    class Meta:
        db_table = 'health_probe_samples'
        ordering = ('-timestamp', '-id')
        indexes = [models.Index(fields=['timestamp', 'success'], name='probe_time_success_idx')]


class DbMetricSnapshot(models.Model):
    """数据库巡检的带时间快照，供窗口聚合读取。"""
    captured_at = models.DateTimeField(db_index=True)
    threads_connected = models.IntegerField(null=True, blank=True)
    slow_queries = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = 'db_metric_snapshots'
        ordering = ('-captured_at', '-id')
        indexes = [models.Index(fields=['captured_at'], name='db_snapshot_time_idx')]


class RunMetric(models.Model):
    """每个完整五分钟窗口一行的运行指标。"""
    bucket_start = models.DateTimeField(unique=True)
    request_count = models.IntegerField(default=0)
    api_request_count = models.IntegerField(default=0)
    transfer_request_count = models.IntegerField(default=0)
    health_check_count = models.IntegerField(default=0)
    websocket_handshake_count = models.IntegerField(default=0)
    client_error_count = models.IntegerField(default=0)
    app_server_error_count = models.IntegerField(default=0)
    gateway_error_count = models.IntegerField(default=0)
    business_error_count = models.IntegerField(default=0)
    slow_count = models.IntegerField(default=0)
    total_ms = models.BigIntegerField(default=0)
    max_ms = models.IntegerField(default=0)
    latency_le_200 = models.IntegerField(default=0)
    latency_le_500 = models.IntegerField(default=0)
    latency_le_1000 = models.IntegerField(default=0)
    latency_le_3000 = models.IntegerField(default=0)
    latency_gt_3000 = models.IntegerField(default=0)
    celery_fail_count = models.IntegerField(default=0)
    probe_count = models.IntegerField(default=0)
    probe_success_count = models.IntegerField(default=0)
    probe_total_ms = models.BigIntegerField(default=0)
    probe_max_ms = models.IntegerField(default=0)
    db_threads_connected = models.IntegerField(null=True, blank=True)
    db_slow_queries = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'run_metrics'
        ordering = ('-bucket_start',)
        indexes = [models.Index(fields=['bucket_start'], name='run_metric_bucket_idx')]

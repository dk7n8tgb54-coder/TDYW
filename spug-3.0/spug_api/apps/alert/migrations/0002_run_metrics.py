from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('alert', '0001_initial')]
    operations = [
        migrations.CreateModel(
            name='HealthProbeSample',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(unique=True)),
                ('success', models.BooleanField(default=False)),
                ('http_status', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('duration_ms', models.PositiveIntegerField(default=0)),
                ('error_type', models.CharField(blank=True, default='', max_length=80)),
            ],
            options={'db_table': 'health_probe_samples', 'ordering': ('-timestamp', '-id')},
        ),
        migrations.CreateModel(
            name='DbMetricSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('captured_at', models.DateTimeField(db_index=True)),
                ('threads_connected', models.IntegerField(blank=True, null=True)),
                ('slow_queries', models.BigIntegerField(blank=True, null=True)),
            ],
            options={'db_table': 'db_metric_snapshots', 'ordering': ('-captured_at', '-id')},
        ),
        migrations.CreateModel(
            name='RunMetric',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('bucket_start', models.DateTimeField(unique=True)),
                ('request_count', models.IntegerField(default=0)),
                ('api_request_count', models.IntegerField(default=0)),
                ('transfer_request_count', models.IntegerField(default=0)),
                ('health_check_count', models.IntegerField(default=0)),
                ('websocket_handshake_count', models.IntegerField(default=0)),
                ('client_error_count', models.IntegerField(default=0)),
                ('app_server_error_count', models.IntegerField(default=0)),
                ('gateway_error_count', models.IntegerField(default=0)),
                ('business_error_count', models.IntegerField(default=0)),
                ('slow_count', models.IntegerField(default=0)),
                ('total_ms', models.BigIntegerField(default=0)),
                ('max_ms', models.IntegerField(default=0)),
                ('latency_le_200', models.IntegerField(default=0)),
                ('latency_le_500', models.IntegerField(default=0)),
                ('latency_le_1000', models.IntegerField(default=0)),
                ('latency_le_3000', models.IntegerField(default=0)),
                ('latency_gt_3000', models.IntegerField(default=0)),
                ('celery_fail_count', models.IntegerField(default=0)),
                ('probe_count', models.IntegerField(default=0)),
                ('probe_success_count', models.IntegerField(default=0)),
                ('probe_total_ms', models.BigIntegerField(default=0)),
                ('probe_max_ms', models.IntegerField(default=0)),
                ('db_threads_connected', models.IntegerField(blank=True, null=True)),
                ('db_slow_queries', models.BigIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'db_table': 'run_metrics', 'ordering': ('-bucket_start',)},
        ),
        migrations.AddIndex(model_name='healthprobesample', index=models.Index(fields=['timestamp', 'success'], name='probe_time_success_idx')),
        migrations.AddIndex(model_name='dbmetricsnapshot', index=models.Index(fields=['captured_at'], name='db_snapshot_time_idx')),
        migrations.AddIndex(model_name='runmetric', index=models.Index(fields=['bucket_start'], name='run_metric_bucket_idx')),
    ]

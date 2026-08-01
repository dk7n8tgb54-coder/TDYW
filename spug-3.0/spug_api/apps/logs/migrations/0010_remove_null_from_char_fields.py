"""移除 tenant_id/request_id/user_agent 的 null=True

Migration 0008 已修复 detail/target_id/target_name，但遗漏了这三个字段。
CharField 不应有 null=True（项目规范），改用 default='' + blank=True。

先更新已有 NULL 值为默认值，再 ALTER 字段去除 null=True。
"""

from django.db import migrations, models


def fill_null_values(apps, schema_editor):
    """将 NULL 值更新为默认值，避免 ALTER 时违反 NOT NULL 约束"""
    AuditLog = apps.get_model('logs', 'AuditLog')
    AuditLog.objects.filter(tenant_id__isnull=True).update(tenant_id='default')
    AuditLog.objects.filter(request_id__isnull=True).update(request_id='')
    AuditLog.objects.filter(user_agent__isnull=True).update(user_agent='')


class Migration(migrations.Migration):

    dependencies = [
        ('logs', '0009_auditlog_audit_action_valid'),
    ]

    operations = [
        # 先填充 NULL 值
        migrations.RunPython(fill_null_values, migrations.RunPython.noop),

        # 再 ALTER 字段去除 null=True
        migrations.AlterField(
            model_name='auditlog',
            name='tenant_id',
            field=models.CharField(default='default', max_length=50),
        ),
        migrations.AlterField(
            model_name='auditlog',
            name='request_id',
            field=models.CharField(
                blank=True, db_index=True, default='',
                help_text='请求唯一标识(uuid4)，关联同请求多条记录',
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name='auditlog',
            name='user_agent',
            field=models.CharField(
                blank=True, default='', help_text='客户端 User-Agent',
                max_length=500,
            ),
        ),
    ]

# Data migration + CheckConstraint: fix non-standard audit action values, then add constraint

from django.db import migrations, models


def fix_nonstandard_actions(apps, schema_editor):
    """将非标准 action 值更新为标准 code"""
    AuditLog = apps.get_model('logs', 'AuditLog')
    # '新建批复' -> 'create'
    AuditLog.objects.filter(action='新建批复').update(action='create')
    # '编辑批复' -> 'update'
    AuditLog.objects.filter(action='编辑批复').update(action='update')
    # '删除批复' -> 'delete'
    AuditLog.objects.filter(action='删除批复').update(action='delete')
    # '确认批复提醒' -> 'update'
    AuditLog.objects.filter(action='确认批复提醒').update(action='update')


class Migration(migrations.Migration):

    dependencies = [
        ('logs', '0008_remove_null_from_string_fields'),
    ]

    operations = [
        migrations.RunPython(fix_nonstandard_actions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='auditlog',
            constraint=models.CheckConstraint(
                check=models.Q(('action__in', ['create', 'update', 'delete', 'login', 'logout', 'export', 'import', 'approve', 'other'])),
                name='audit_action_valid',
            ),
        ),
    ]

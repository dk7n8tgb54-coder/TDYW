"""移除 RadioLicense.is_deleted 字段，改为全硬删除策略。

执行步骤：
1. 删除所有 is_deleted=True 的执照记录（CASCADE 自动级联删除频率/附件/提醒子表）
2. 移除 is_deleted 字段
"""
from django.db import migrations


def delete_soft_deleted_licenses(apps, schema_editor):
    """删除已软删除的执照记录（Django CASCADE 会自动级联删除子表）"""
    RadioLicense = apps.get_model('radio_license', 'RadioLicense')
    deleted_count, _ = RadioLicense.objects.filter(is_deleted=True).delete()
    if deleted_count:
        # delete() 返回 {'model': count} 字典，取总计数
        total = sum(deleted_count.values()) if isinstance(deleted_count, dict) else deleted_count
        print(f'[radio_license] 清理已软删除执照记录: {total} 条')


class Migration(migrations.Migration):

    dependencies = [
        ('radio_license', '0003_add_reminder_model'),
    ]

    operations = [
        migrations.RunPython(delete_soft_deleted_licenses, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='radiolicense',
            name='is_deleted',
        ),
    ]

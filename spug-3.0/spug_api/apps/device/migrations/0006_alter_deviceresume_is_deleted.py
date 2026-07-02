"""Alter DeviceResume.is_deleted help_text to reflect soft-delete semantics.

证据闭环第三阶段：DeviceResume 启用软删除，更新 help_text 文案以与 0004 的
"当前为硬删除，字段预留" 区分。DeviceEvent 仍为硬删除，保持 0004 文案不变。
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('device', '0005_evidence_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='deviceresume',
            name='is_deleted',
            field=models.BooleanField(default=False, help_text='是否已删除（软删除）'),
        ),
    ]

# Generated for evidence-closure stage 3: runlog evidence fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('runlog', '0006_add_duty_person_to_runlogupdate'),
    ]

    operations = [
        # ---- RunLog 新增快照哈希 + 验证人ID ----
        migrations.AddField(
            model_name='runlog',
            name='snapshot_hash',
            field=models.CharField(default='', max_length=64, help_text='归档快照哈希(SHA256)'),
        ),
        migrations.AddField(
            model_name='runlog',
            name='verified_by_id',
            field=models.IntegerField(blank=True, help_text='验证人账号ID（已废弃 verifier_id 仍保留）', null=True),
        ),
        # ---- RunLogUpdate 新增证据闭环字段 ----
        migrations.AddField(
            model_name='runlogupdate',
            name='update_type',
            field=models.CharField(choices=[('normal', '普通动态'), ('correction', '更正说明'), ('supplement', '补充说明'), ('system', '系统记录')], default='normal', help_text='动态类型：normal/correction/supplement/system', max_length=20),
        ),
        migrations.AddField(
            model_name='runlogupdate',
            name='corrected_update_id',
            field=models.IntegerField(blank=True, help_text='更正指向的原动态ID', null=True),
        ),
        migrations.AddField(
            model_name='runlogupdate',
            name='is_voided',
            field=models.BooleanField(default=False, help_text='是否已作废'),
        ),
        migrations.AddField(
            model_name='runlogupdate',
            name='void_reason',
            field=models.CharField(blank=True, default='', help_text='作废原因', max_length=500),
        ),
    ]

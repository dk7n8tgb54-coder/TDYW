# Generated for evidence-closure stage 3: device evidence fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('device', '0004_device_sn_tenant_unique_and_choices'),
    ]

    operations = [
        # ---- DeviceResume 软删除 + 快照哈希 ----
        migrations.AddField(
            model_name='deviceresume',
            name='deleted_at',
            field=models.CharField(blank=True, help_text='删除时间', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='deviceresume',
            name='deleted_by_id',
            field=models.IntegerField(blank=True, help_text='删除人账号ID', null=True),
        ),
        migrations.AddField(
            model_name='deviceresume',
            name='delete_reason',
            field=models.CharField(blank=True, default='', help_text='删除原因', max_length=500),
        ),
        migrations.AddField(
            model_name='deviceresume',
            name='snapshot_hash',
            field=models.CharField(default='', help_text='设备快照哈希(SHA256)', max_length=64),
        ),
        # ---- DeviceEvent 更正机制 ----
        migrations.AddField(
            model_name='deviceevent',
            name='correction_event_id',
            field=models.IntegerField(blank=True, help_text='更正指向的原事件ID', null=True),
        ),
        migrations.AddField(
            model_name='deviceevent',
            name='correction_reason',
            field=models.CharField(blank=True, default='', help_text='更正原因', max_length=500),
        ),
        migrations.AddField(
            model_name='deviceevent',
            name='corrected_by_id',
            field=models.IntegerField(blank=True, help_text='更正人账号ID', null=True),
        ),
        migrations.AddField(
            model_name='deviceevent',
            name='corrected_at',
            field=models.CharField(blank=True, help_text='更正时间', max_length=20, null=True),
        ),
    ]

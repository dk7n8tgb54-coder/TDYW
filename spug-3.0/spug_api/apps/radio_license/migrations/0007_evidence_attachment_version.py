# Generated for evidence-closure stage 3: radio_license attachment hash + version history

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('radio_license', '0006_auto_20260627_0807'),
    ]

    operations = [
        # ---- RadioLicenseAttachment 增加哈希 + 软删除字段 ----
        migrations.AddField(
            model_name='radiolicenseattachment',
            name='file_hash_sha256',
            field=models.CharField(db_index=True, default='', help_text='文件 SHA256', max_length=64),
        ),
        migrations.AddField(
            model_name='radiolicenseattachment',
            name='file_hash_md5',
            field=models.CharField(default='', help_text='文件 MD5（兼容旧系统）', max_length=32),
        ),
        migrations.AddField(
            model_name='radiolicenseattachment',
            name='uploaded_by_name',
            field=models.CharField(default='', help_text='上传人姓名快照', max_length=100),
        ),
        migrations.AddField(
            model_name='radiolicenseattachment',
            name='is_deleted',
            field=models.BooleanField(default=False, help_text='是否已删除（软删除）'),
        ),
        migrations.AddField(
            model_name='radiolicenseattachment',
            name='deleted_by_id',
            field=models.IntegerField(blank=True, help_text='删除人账号 ID', null=True),
        ),
        migrations.AddField(
            model_name='radiolicenseattachment',
            name='deleted_by_name',
            field=models.CharField(default='', help_text='删除人姓名快照', max_length=100),
        ),
        migrations.AddField(
            model_name='radiolicenseattachment',
            name='deleted_at',
            field=models.CharField(blank=True, help_text='删除时间', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='radiolicenseattachment',
            name='delete_reason',
            field=models.CharField(blank=True, default='', help_text='删除原因', max_length=500),
        ),
        migrations.AddIndex(
            model_name='radiolicenseattachment',
            index=models.Index(fields=['file_hash_sha256'], name='rl_att_sha256_idx'),
        ),
        # ---- 新增 RadioLicenseVersion 版本历史表 ----
        migrations.CreateModel(
            name='RadioLicenseVersion',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(default='', help_text='租户标识', max_length=50)),
                ('version_no', models.IntegerField(help_text='版本号（按执照递增）')),
                ('snapshot_json', models.TextField(help_text='修改前完整字段快照 JSON')),
                ('changed_fields', models.TextField(default='', help_text='本次变更字段列表（逗号分隔）')),
                ('change_reason', models.CharField(blank=True, default='', help_text='变更原因', max_length=500)),
                ('changed_by_id', models.IntegerField(blank=True, help_text='修改人账号 ID', null=True)),
                ('changed_by_name', models.CharField(default='', help_text='修改人姓名快照', max_length=100)),
                ('changed_at', models.CharField(help_text='修改时间', max_length=20)),
                ('snapshot_hash', models.CharField(default='', help_text='快照哈希(SHA256)', max_length=64)),
                ('license', models.ForeignKey(help_text='执照', on_delete=models.deletion.CASCADE, related_name='versions', to='radio_license.radiolicense')),
            ],
            options={
                'db_table': 'tdyw_radio_license_version',
                'verbose_name': '执照版本',
                'verbose_name_plural': '执照版本',
                'ordering': ('-version_no', '-id'),
            },
        ),
        migrations.AddIndex(
            model_name='radiolicenseversion',
            index=models.Index(fields=['tenant_id', 'license'], name='rl_ver_license_idx'),
        ),
    ]

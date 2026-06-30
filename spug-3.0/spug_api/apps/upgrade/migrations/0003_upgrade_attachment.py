# Generated for upgrade attachment table

from django.db import migrations, models
import django.db.models.deletion
import libs.utils


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0003_add_tenant_id_index'),
        ('upgrade', '0002_auto_20260627_0807'),
    ]

    operations = [
        migrations.CreateModel(
            name='UpgradeAttachment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(db_index=True, default='', help_text='租户标识', max_length=50)),
                ('file_name', models.CharField(help_text='原始文件名（用户上传时的名字）', max_length=255)),
                ('file_path', models.CharField(help_text='磁盘存储相对路径（含重命名后的文件名）', max_length=500)),
                ('file_size', models.BigIntegerField(default=0, help_text='文件大小(字节)')),
                ('file_ext', models.CharField(default='', help_text='文件扩展名（含点，小写）', max_length=20)),
                ('file_hash_sha256', models.CharField(db_index=True, default='', help_text='文件 SHA256', max_length=64)),
                ('uploaded_by_name', models.CharField(default='', help_text='上传人姓名快照', max_length=100)),
                ('is_deleted', models.BooleanField(default=False, help_text='是否已删除（软删除）')),
                ('deleted_by_id', models.IntegerField(blank=True, help_text='删除人账号 ID', null=True)),
                ('deleted_by_name', models.CharField(default='', help_text='删除人姓名快照', max_length=100)),
                ('deleted_at', models.CharField(blank=True, help_text='删除时间', max_length=20, null=True)),
                ('delete_reason', models.CharField(blank=True, default='', help_text='删除原因', max_length=500)),
                ('remark', models.CharField(blank=True, default='', help_text='附件备注（如版本说明）', max_length=500)),
                ('created_at', models.CharField(default=libs.utils.human_datetime, help_text='上传时间', max_length=20)),
                ('record', models.ForeignKey(help_text='关联的升级表单', on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='upgrade.UpgradeRecord')),
                ('uploaded_by', models.ForeignKey(help_text='上传人', on_delete=django.db.models.deletion.PROTECT, related_name='+', to='account.User')),
            ],
            options={
                'db_table': 'tdyw_upgrade_attachments',
                'verbose_name': '升级附件',
                'verbose_name_plural': '升级附件',
                'ordering': ('-created_at',),
            },
        ),
        migrations.AddIndex(
            model_name='upgradeattachment',
            index=models.Index(fields=['tenant_id', 'record'], name='upg_att_record_idx'),
        ),
        migrations.AddIndex(
            model_name='upgradeattachment',
            index=models.Index(fields=['file_hash_sha256'], name='upg_att_sha256_idx'),
        ),
        migrations.AddIndex(
            model_name='upgradeattachment',
            index=models.Index(fields=['tenant_id', 'is_deleted'], name='upg_att_del_idx'),
        ),
    ]

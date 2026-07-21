# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""新增台站频率批复主表和提醒确认表。"""

from django.db import migrations, models
import django.db.models.deletion
import libs.utils


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0001_initial'),
        ('radio_license', '0009_remove_radiolicensereminder'),
    ]

    operations = [
        migrations.CreateModel(
            name='StationFrequencyApproval',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(default='', help_text='租户标识', max_length=50)),
                ('name', models.CharField(help_text='文件名称', max_length=200)),
                ('doc_no', models.CharField(help_text='文件编号', max_length=100)),
                ('frequency_text', models.CharField(help_text='批复频率', max_length=200)),
                ('valid_from', models.DateField(help_text='起始日期')),
                ('valid_to', models.DateField(help_text='截止日期')),
                ('responsible_user_id', models.IntegerField(help_text='责任人ID')),
                ('responsible_user_name', models.CharField(
                    default='', help_text='责任人姓名快照（服务端回填）', max_length=100)),
                ('status', models.CharField(
                    choices=[('normal', '正常'), ('expiring', '即将到期'), ('expired', '已过期')],
                    default='normal', help_text='缓存状态，由定时任务维护；接口一律实时计算',
                    max_length=20)),
                ('remark', models.TextField(blank=True, default='', help_text='备注')),
                ('created_at', models.CharField(default=libs.utils.human_datetime, max_length=20)),
                ('updated_at', models.CharField(max_length=20, null=True)),
                ('created_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name='+',
                    to='account.user')),
                ('updated_by', models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+',
                    to='account.user')),
            ],
            options={
                'db_table': 'tdyw_station_frequency_approval',
                'verbose_name': '台站频率批复',
                'verbose_name_plural': '台站频率批复',
                'ordering': ('-created_at', '-id'),
            },
        ),
        migrations.CreateModel(
            name='StationFrequencyApprovalReminderAck',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(default='', help_text='租户标识', max_length=50)),
                ('user_id', models.IntegerField(help_text='确认用户ID')),
                ('user_name', models.CharField(default='', help_text='确认用户姓名快照', max_length=100)),
                ('ack_valid_to', models.DateField(help_text='确认时的截止日期（用于续期后自动失效）')),
                ('created_at', models.CharField(default=libs.utils.human_datetime, max_length=20)),
                ('approval', models.ForeignKey(
                    help_text='批复', on_delete=django.db.models.deletion.CASCADE,
                    related_name='reminder_acks', to='radio_license.stationfrequencyapproval')),
            ],
            options={
                'db_table': 'tdyw_station_frequency_approval_reminder_ack',
                'verbose_name': '频率批复提醒确认',
                'verbose_name_plural': '频率批复提醒确认',
                'ordering': ('-created_at', '-id'),
            },
        ),
        migrations.AddConstraint(
            model_name='stationfrequencyapproval',
            constraint=models.UniqueConstraint(
                fields=['tenant_id', 'doc_no'],
                name='uniq_sfa_tenant_doc_no',
            ),
        ),
        migrations.AddConstraint(
            model_name='stationfrequencyapprovalreminderack',
            constraint=models.UniqueConstraint(
                fields=['tenant_id', 'approval', 'user_id', 'ack_valid_to'],
                name='uniq_sfa_ack_cycle',
            ),
        ),
        migrations.AddIndex(
            model_name='stationfrequencyapproval',
            index=models.Index(
                fields=['tenant_id', '-created_at', '-id'],
                name='sfa_tenant_created_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='stationfrequencyapproval',
            index=models.Index(
                fields=['tenant_id', 'responsible_user_id', 'valid_to'],
                name='sfa_owner_expiry_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='stationfrequencyapproval',
            index=models.Index(
                fields=['tenant_id', 'valid_to'],
                name='sfa_tenant_expiry_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='stationfrequencyapprovalreminderack',
            index=models.Index(
                fields=['tenant_id', 'user_id', 'approval'],
                name='sfa_ack_user_approval_idx',
            ),
        ),
    ]

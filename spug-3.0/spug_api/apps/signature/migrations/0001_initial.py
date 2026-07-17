# Generated for signature stage 1: account signature binding

from django.db import migrations, models

import libs.utils


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='AccountSignature',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(db_index=True, default='', help_text='目标账号所属租户快照', max_length=50)),
                ('user_id', models.BigIntegerField(help_text='目标账号 ID，一账号一条绑定记录', unique=True)),
                ('current_attachment_id', models.BigIntegerField(blank=True, help_text='当前签名对应的 EvidenceAttachment.id', null=True)),
                ('version', models.PositiveIntegerField(default=1, help_text='当前版本号，从 1 递增')),
                ('status', models.CharField(choices=[('active', '生效'), ('disabled', '已停用')], default='active', help_text='签名状态', max_length=20)),
                ('assigned_by_id', models.BigIntegerField(blank=True, help_text='最近一次赋予/替换的超级管理员 ID', null=True)),
                ('assigned_by_name', models.CharField(default='', help_text='管理员姓名快照', max_length=100)),
                ('assigned_at', models.CharField(default=libs.utils.human_datetime, help_text='最近一次赋予/替换时间', max_length=20)),
                ('disabled_by_id', models.BigIntegerField(blank=True, help_text='停用操作人 ID', null=True)),
                ('disabled_by_name', models.CharField(blank=True, help_text='停用操作人姓名快照', max_length=100, null=True)),
                ('disabled_at', models.CharField(blank=True, help_text='停用时间', max_length=20, null=True)),
                ('remark', models.CharField(blank=True, default='', help_text='管理备注，不返回给普通业务页面', max_length=255)),
                ('created_at', models.CharField(default=libs.utils.human_datetime, help_text='创建时间', max_length=20)),
                ('updated_at', models.CharField(default=libs.utils.human_datetime, help_text='更新时间', max_length=20)),
            ],
            options={
                'db_table': 'tdyw_account_signatures',
                'verbose_name': '账号签名',
                'verbose_name_plural': '账号签名',
                'ordering': ('-id',),
            },
        ),
        migrations.AddIndex(
            model_name='accountsignature',
            index=models.Index(fields=['tenant_id', 'status'], name='sig_tenant_status_idx'),
        ),
    ]

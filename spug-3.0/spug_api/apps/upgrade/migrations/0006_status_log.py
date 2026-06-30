# Generated for upgrade status log table + record status add '已回退' choice

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('upgrade', '0005_drop_upgrade_attachment'),
    ]

    operations = [
        # 1. 新建状态日志表
        migrations.CreateModel(
            name='UpgradeStatusLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(db_index=True, default='', help_text='租户标识', max_length=50)),
                ('upgrade_id', models.IntegerField(verbose_name='关联升级表单ID')),
                ('action', models.CharField(choices=[
                    ('start', '开始升级'),
                    ('backup', '备份'),
                    ('gray_release', '灰度发布'),
                    ('full_release', '全量发布'),
                    ('test', '升级测试'),
                    ('test_pass', '测试通过'),
                    ('test_fail', '测试失败'),
                    ('rollback', '回退'),
                    ('pause', '暂停'),
                    ('resume', '继续'),
                    ('observe', '上线观察期'),
                    ('complete', '完成'),
                ], max_length=20, verbose_name='动作类型')),
                ('from_status', models.CharField(blank=True, default='', max_length=20, verbose_name='变更前主表状态')),
                ('to_status', models.CharField(blank=True, default='', max_length=20, verbose_name='变更后主表状态')),
                ('operator_id', models.IntegerField(default=0, verbose_name='操作人ID')),
                ('operator_name', models.CharField(blank=True, default='', max_length=100, verbose_name='操作人姓名')),
                ('remark', models.TextField(blank=True, default='', verbose_name='备注')),
                ('created_at', models.CharField(max_length=20, verbose_name='操作时间')),
            ],
            options={
                'verbose_name': '升级状态日志',
                'verbose_name_plural': '升级状态日志',
                'db_table': 'tdyw_upgrade_status_logs',
                'ordering': ('-created_at', '-id'),
            },
        ),
        migrations.AddIndex(
            model_name='upgradestatuslog',
            index=models.Index(fields=['upgrade_id'], name='tdyw_upgrad_upgrade_fab64e_idx'),
        ),
        migrations.AddIndex(
            model_name='upgradestatuslog',
            index=models.Index(fields=['tenant_id', 'upgrade_id'], name='tdyw_upgrad_tenant__b4cd1a_idx'),
        ),
        # 2. UpgradeRecord.status 保持 CharField(max_length=20)，"已回退" 只是新增可选值，无需改字段定义
        #    （原 default='处理中' 不变，max_length=20 足够容纳"已回退"）
    ]

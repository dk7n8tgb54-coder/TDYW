# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""为升级记录新增建单字段：标题/升级内容/影响范围/风险说明/回退方案摘要，并将版本改为可选。"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('upgrade', '0010_alter_upgradestatuslog_action'),
    ]

    operations = [
        migrations.AddField(
            model_name='upgraderecord',
            name='title',
            field=models.CharField(default='', max_length=200, verbose_name='标题'),
        ),
        migrations.AddField(
            model_name='upgraderecord',
            name='upgrade_content',
            field=models.TextField(blank=True, default='', verbose_name='升级内容'),
        ),
        migrations.AddField(
            model_name='upgraderecord',
            name='impact_scope',
            field=models.TextField(blank=True, default='', verbose_name='影响范围'),
        ),
        migrations.AddField(
            model_name='upgraderecord',
            name='risk_desc',
            field=models.TextField(blank=True, default='', verbose_name='风险说明'),
        ),
        migrations.AddField(
            model_name='upgraderecord',
            name='rollback_plan',
            field=models.TextField(blank=True, default='', verbose_name='回退方案摘要'),
        ),
        migrations.AlterField(
            model_name='upgraderecord',
            name='version',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AlterField(
            model_name='upgraderecord',
            name='upgrade_time',
            field=models.CharField(max_length=20, verbose_name='计划升级时间'),
        ),
    ]

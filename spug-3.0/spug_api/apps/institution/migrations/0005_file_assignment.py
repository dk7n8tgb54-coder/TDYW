# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""文件分工：分工单位从"章节"改为"整份制度文件"（2026-10-29）

结构变更（全部为可空/默认值新增列，历史数据零改写）：
- ManualFile 新增 文件分工与提交编制字段。分工就存放在文件条目自身，
  每份文件至多一名负责人，结构上不存在"同一文件多条互相冲突的当前
  分工"；负责人/提交人账号删除后 owner_name 等快照仍可读（SET_NULL）。
- ManualChapter（旧章节分工）表与记录一律不动：旧记录只关联制度、
  无法按章节名称猜测所属文件，在人工核对完成前保留供查阅，写接口
  由视图层关闭（视图返回明确业务错误，非数据删除）。

提交状态失效为计算式：提交时记录草稿修订号（submission_revision），
草稿再次保存/重建/回退/恢复都会推进 revision，提交状态随之失效，
不迁移任何旧状态、无需回填。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('institution', '0004_file_lifecycle_retention'),
    ]

    operations = [
        migrations.AddField(
            model_name='manualfile',
            name='owner',
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=models.SET_NULL, related_name='+',
                                    to='account.user',
                                    verbose_name='文件负责人'),
        ),
        migrations.AddField(
            model_name='manualfile',
            name='owner_name',
            field=models.CharField(blank=True, default='', max_length=100,
                                   verbose_name='负责人账号名'),
        ),
        migrations.AddField(
            model_name='manualfile',
            name='assign_note',
            field=models.CharField(blank=True, default='', max_length=500,
                                   verbose_name='分工说明'),
        ),
        migrations.AddField(
            model_name='manualfile',
            name='assigned_at',
            field=models.DateTimeField(blank=True, null=True,
                                       verbose_name='最近分工时间'),
        ),
        migrations.AddField(
            model_name='manualfile',
            name='assigned_by',
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=models.SET_NULL, related_name='+',
                                    to='account.user',
                                    verbose_name='最近分工操作人'),
        ),
        migrations.AddField(
            model_name='manualfile',
            name='submission_revision',
            field=models.PositiveIntegerField(blank=True, null=True,
                                              verbose_name='提交时修订号'),
        ),
        migrations.AddField(
            model_name='manualfile',
            name='submitted_at',
            field=models.DateTimeField(blank=True, null=True,
                                       verbose_name='提交编制时间'),
        ),
        migrations.AddField(
            model_name='manualfile',
            name='submitted_by',
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=models.SET_NULL, related_name='+',
                                    to='account.user',
                                    verbose_name='提交编制人'),
        ),
    ]

"""故障"处置记录"改名"处理进展"，并新增选填的进展类型结构化字段。

内容：
- SystemFaultHandlingRecord 新增 progress_type 列（选填，default=''）：
  检查/本方处理/送厂/厂家反馈/返还/测试/持续观察/其他，空串=未选择；
- handled_at / content / handler / result 的 help_text 同步改为"进展"口径
  （仅元数据）；
- Meta verbose_name 由"故障处置记录"改为"故障处理进展"（仅元数据）。

兼容性说明：
- 新列带 default=''，历史记录 progress_type 为空串（未选择），无需回填；
- 空串语义为"未选择"，不通过拼接文本解析或反推历史记录的类型；
- AlterField 仅涉及 help_text、AlterModelOptions 仅涉及 verbose_name，
  均不改变数据库结构（无破坏性 DDL）；
- 可回滚：反向删除 progress_type 列并恢复原元数据。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0030_inspection_sheet_returned'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemfaulthandlingrecord',
            name='progress_type',
            field=models.CharField(
                blank=True, choices=[
                    ('check', '检查'), ('self_fix', '本方处理'), ('to_vendor', '送厂'),
                    ('vendor_feedback', '厂家反馈'), ('return', '返还'), ('test', '测试'),
                    ('watch', '持续观察'), ('other', '其他'),
                ],
                default='', help_text='进展类型（选填：check检查/self_fix本方处理/to_vendor送厂/'
                                      'vendor_feedback厂家反馈/return返还/test测试/watch持续观察/'
                                      'other其他；空串=未选择，历史记录为空）',
                max_length=20),
        ),
        migrations.AlterField(
            model_name='systemfaulthandlingrecord',
            name='content',
            field=models.TextField(help_text='进展内容', max_length=2000),
        ),
        migrations.AlterField(
            model_name='systemfaulthandlingrecord',
            name='handled_at',
            field=models.DateTimeField(help_text='进展时间'),
        ),
        migrations.AlterField(
            model_name='systemfaulthandlingrecord',
            name='handler',
            field=models.ForeignKey(help_text='记录人',
                                    on_delete=models.PROTECT, related_name='+',
                                    to='account.user'),
        ),
        migrations.AlterField(
            model_name='systemfaulthandlingrecord',
            name='result',
            field=models.CharField(blank=True, default='', help_text='处理结果（选填）',
                                   max_length=200),
        ),
        migrations.AlterModelOptions(
            name='systemfaulthandlingrecord',
            options={'ordering': ('handled_at', 'id'),
                     'verbose_name': '故障处理进展',
                     'verbose_name_plural': '故障处理进展'},
        ),
    ]

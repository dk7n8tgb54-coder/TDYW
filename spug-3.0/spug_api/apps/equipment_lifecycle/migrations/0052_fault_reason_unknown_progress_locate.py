# -*- coding: utf-8 -*-
"""原因分析流程优化（2026-10）：
- SystemFault 新增 reason_unknown（原因未明标记，默认 False）：确实无法确定
  原因时勾选，未明说明仍存入单一字段 reason_analysis，不新增第二原因字段；
  历史数据全部为 False，展示口径回落"初步判断/尚未分析"，完全兼容；
- SystemFaultHandlingRecord.progress_type 新增"故障定位"（fault_locate）选项：
  记录原因判断的依据与过程（choices 变更不改变数据库结构，仅元数据同步）；
- reason_analysis help_text 同步为阶段口径说明（仅元数据）。

兼容性说明：
- reason_unknown 带 default=False，历史故障无需回填；
- progress_type 无数据库 CHECK 约束，新增枚举值对历史记录零影响；
- 可回滚：反向删除 reason_unknown 列并恢复原 choices。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0051_remove_fault_pending_recovered'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemfault',
            name='reason_unknown',
            field=models.BooleanField(
                default=False,
                help_text='原因未明标记（确实无法确定原因时为 True，reason_analysis '
                          '保存未明说明；历史数据为 False）'),
        ),
        migrations.AlterField(
            model_name='systemfault',
            name='reason_analysis',
            field=models.TextField(
                blank=True, default='',
                help_text='原因分析（新增=初步原因分析；处置中展示为初步判断；'
                          '结案时保存为最终原因；原因未明时保存未明说明）',
                max_length=2000),
        ),
        migrations.AlterField(
            model_name='systemfaulthandlingrecord',
            name='progress_type',
            field=models.CharField(
                blank=True, choices=[
                    ('check', '检查'), ('fault_locate', '故障定位'),
                    ('self_fix', '本方处理'), ('to_vendor', '送厂'),
                    ('vendor_feedback', '厂家反馈'), ('return', '返还'),
                    ('test', '测试'), ('watch', '持续观察'), ('other', '其他'),
                ],
                default='',
                help_text='进展类型（选填：check检查/fault_locate故障定位/self_fix本方处理/'
                          'to_vendor送厂/vendor_feedback厂家反馈/return返还/test测试/'
                          'watch持续观察/other其他；空串=未选择，历史记录为空）',
                max_length=20),
        ),
    ]

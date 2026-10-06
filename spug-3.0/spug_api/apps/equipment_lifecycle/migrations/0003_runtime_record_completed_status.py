# 2026-10-04 运行记录四状态收敛（第三版）：新增 completed（已完成）状态。
#
# 用户可见状态收敛为 已记录/跟进中/已完成/已转故障：
# - completed 为新写入状态（完成跟进 resolved 端点落地）；
# - 历史值 pending_triage/no_follow_up/resolved/closed 全部保留在枚举与
#   CHECK 约束中（历史数据不迁改，仅展示文案统一）；
# - 同迁移更新 status/resolved_at/handling_result 的 choices 与 help_text
#   文案（库结构无变化，仅 Django 状态对齐）。
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0002_constraints_and_indexes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='systemruntimerecord',
            name='status',
            field=models.CharField(
                choices=[
                    ('recorded', '已记录'),
                    ('pending_triage', '已记录'),
                    ('no_follow_up', '已记录'),
                    ('following_up', '跟进中'),
                    ('resolved', '已完成'),
                    ('completed', '已完成'),
                    ('converted_fault', '已转故障'),
                    ('closed', '已完成'),
                ],
                default='recorded', help_text='当前状态', max_length=20),
        ),
        migrations.AlterField(
            model_name='systemruntimerecord',
            name='resolved_at',
            field=models.DateTimeField(
                blank=True,
                help_text='首次完成跟进时间（原"标记已处理"；统计平均处理时长用，不随重新跟进/再次完成覆盖）',
                null=True),
        ),
        migrations.AlterField(
            model_name='systemruntimerecord',
            name='handling_result',
            field=models.TextField(
                blank=True, default='',
                help_text='处理结果（选填，完成跟进/关闭时可补填）', max_length=1000),
        ),
        migrations.RemoveConstraint(
            model_name='systemruntimerecord',
            name='el_runtime_record_status_valid',
        ),
        migrations.AddConstraint(
            model_name='systemruntimerecord',
            constraint=models.CheckConstraint(
                check=models.Q(('status__in', [
                    'recorded', 'pending_triage', 'no_follow_up',
                    'following_up', 'resolved', 'completed',
                    'converted_fault', 'closed',
                ])),
                name='el_runtime_record_status_valid',
            ),
        ),
    ]

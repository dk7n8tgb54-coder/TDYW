# 2026-10-06 跟进计划功能退役：删除运行异常记录的跟进人/计划处理时间
# （跟进计划）两列，以及处理进展的处理结果/本次工时两列。
#
# 功能收敛（同日删除 follow-up 端点与前端跟进计划弹窗）：
# - 跟进动作统一为"追加处理进展"（首条进展进入跟进中；已完成记录追加
#   进展即重新跟进），不再维护独立的跟进人/计划处理时间，待办不再有
#   超期/跟进人/计划时间维度；
# - 处理进展只记录 处理时间/处理人/处理内容，结果性描述写入处理内容。
#
# 回滚（Reverse）：
# - RemoveField 反向补建四列：follow_up_name/planned_handle_at（历史值不
#   恢复，删除前即无业务写入入口）、result（空串）、work_hours（NULL）。
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0008_runtime_record_duplicate_retirement'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='systemruntimerecord',
            name='follow_up_name',
        ),
        migrations.RemoveField(
            model_name='systemruntimerecord',
            name='planned_handle_at',
        ),
        migrations.RemoveField(
            model_name='systemruntimerecordprogress',
            name='result',
        ),
        migrations.RemoveField(
            model_name='systemruntimerecordprogress',
            name='work_hours',
        ),
    ]

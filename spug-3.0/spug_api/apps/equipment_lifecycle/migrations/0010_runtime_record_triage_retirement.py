# 2026-10-07 研判快照字段彻底退役：删除运行异常记录的研判时间/研判操作
# 账号/研判人/研判说明四列。
#
# 背景：研判不再是必经步骤（2026-10-05 第四版，triage/close 端点与
# TriageModal 已于 2026-10-06 随状态归一整体删除），新记录不产生研判数据；
# 本迁移删除历史快照列，存量历史值随列删除不再保留（dev 库存量 3 条，
# 均为 2026-10-04 之前的录入）。
#
# 回滚（Reverse）：
# - RemoveField 反向补建四空列（triaged_at/triaged_by 可空、其余空串），
#   历史值不恢复。
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0009_runtime_record_follow_up_plan_retirement'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='systemruntimerecord',
            name='triaged_at',
        ),
        migrations.RemoveField(
            model_name='systemruntimerecord',
            name='triaged_by',
        ),
        migrations.RemoveField(
            model_name='systemruntimerecord',
            name='triaged_by_name',
        ),
        migrations.RemoveField(
            model_name='systemruntimerecord',
            name='triage_note',
        ),
    ]

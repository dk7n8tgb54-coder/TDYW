# 2026-10-06 运行异常记录旧状态归一（状态清理收尾）。
#
# 第三/四/五版流程收敛后，旧枚举 pending_triage（待研判）/no_follow_up（无需跟进）/
# resolved（已处理）/closed（已关闭）不再产生新数据，仅存量历史行仍持有旧值。
# 本迁移按既有展示语义把旧值一次性归一到正式状态：
# - pending_triage / no_follow_up → recorded（已记录：留痕稳定态）；
# - resolved / closed → completed（已完成：完成跟进合并语义）。
# 仅改写 status 单列，记录本身、研判快照（triaged_at 等）、跟进与审计信息
# 全部保留不动。
#
# 可回滚设计：
# - 正向执行前先把待归一行 (id, status) 备份到
#   tdyw_el_runtime_record_status_backfill；
# - 反向（unapply）按 operations 逆序执行：先回退 CHECK 约束与 choices 到
#   迁移 0003 的八状态口径，再从备份表恢复旧值（仅限仍处于 recorded/
#   completed 的行——已合法流转到 following_up/converted_fault 的行不回写，
#   避免把已推进的业务状态拉回旧值）；备份表保留，可重复正向/反向；
# - 确认新流程稳定后可手工删除备份表。
from django.db import migrations, models

BACKUP_TABLE = 'tdyw_el_runtime_record_status_backfill'

REVERSE_SQL = f"""
UPDATE tdyw_el_runtime_record r
    JOIN {BACKUP_TABLE} b ON b.record_id = r.id
    SET r.status = b.old_status
    WHERE r.status IN ('recorded', 'completed');
"""

FORWARD_STATEMENTS = [
    f"""CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} (
    record_id bigint NOT NULL PRIMARY KEY,
    old_status varchar(20) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",
    f"DELETE FROM {BACKUP_TABLE};",
    f"""INSERT INTO {BACKUP_TABLE} (record_id, old_status)
    SELECT id, status FROM tdyw_el_runtime_record
    WHERE status IN ('pending_triage', 'no_follow_up', 'resolved', 'closed');""",
    """UPDATE tdyw_el_runtime_record SET status = 'recorded'
    WHERE status IN ('pending_triage', 'no_follow_up');""",
    """UPDATE tdyw_el_runtime_record SET status = 'completed'
    WHERE status IN ('resolved', 'closed');""",
]


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0006_runtime_record_field_retirement'),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_STATEMENTS, reverse_sql=REVERSE_SQL),
        migrations.AlterField(
            model_name='systemruntimerecord',
            name='status',
            field=models.CharField(
                choices=[
                    ('recorded', '已记录'),
                    ('following_up', '跟进中'),
                    ('completed', '已完成'),
                    ('converted_fault', '已转故障'),
                ],
                default='recorded', help_text='当前状态', max_length=20),
        ),
        migrations.RemoveConstraint(
            model_name='systemruntimerecord',
            name='el_runtime_record_status_valid',
        ),
        migrations.AddConstraint(
            model_name='systemruntimerecord',
            constraint=models.CheckConstraint(
                check=models.Q(('status__in', [
                    'recorded', 'following_up', 'completed', 'converted_fault',
                ])),
                name='el_runtime_record_status_valid',
            ),
        ),
    ]

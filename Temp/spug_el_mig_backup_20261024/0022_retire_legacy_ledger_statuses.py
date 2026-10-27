"""维护台账旧状态退役（2026-10-17）：submitted/returned/reviewed 移出值域。

- 存量洗数：submitted/reviewed → completed（旧流程已提交/已复核即业务
  终态，对齐新流程"已完成"；completed_at/completed_by 保持空缺，如实
  反映并非经新流程完成填写）；returned → draft（退回即待整改重填，
  回到可编辑草稿）；
- 收紧状态值域 CHECK（Remove + Add，Django 4.2 无 AlterConstraint）：
  仅 draft/completed/void，代码与库约束一致，旧状态不再可写入；
- 反向不可逆（洗数后的行无法与原生 completed/draft 区分）。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0021_ledger_completed_status_and_slot_rebuild'),
    ]

    operations = [
        # 先洗数据再加约束（旧状态行不清洗会直接违反收紧后的 CHECK）
        migrations.RunSQL(
            sql=[
                "UPDATE tdyw_el_operation_ledger SET status = 'completed' "
                "WHERE status IN ('submitted', 'reviewed')",
                "UPDATE tdyw_el_operation_ledger SET status = 'draft' "
                "WHERE status = 'returned'",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RemoveConstraint(
            model_name='operationledger',
            name='el_operation_ledger_status_valid',
        ),
        migrations.AddConstraint(
            model_name='operationledger',
            constraint=models.CheckConstraint(
                check=models.Q(status__in=['draft', 'completed', 'void']),
                name='el_operation_ledger_status_valid',
            ),
        ),
    ]

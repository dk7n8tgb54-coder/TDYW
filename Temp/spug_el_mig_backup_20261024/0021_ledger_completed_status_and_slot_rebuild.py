"""维护台账流程简化（2026-10-16）：三状态收敛 + 作废补建支持。

- 新增 completed（已完成）状态：完成填写为流程终点；CHECK 值域在保留
  submitted/returned/reviewed（历史存量可查看/删除）基础上加入 completed；
- 新增 completed_at/completed_by：完成填写时间与人（旧流程 reviewed_at 等
  字段保留供历史数据展示）；
- 新增 slot_active 并改写期次唯一约束：非作废=True、作废=NULL（MariaDB
  无部分唯一索引，以 NULL 行豁免实现"作废不占槽位"），支持作废后明确补建；
  自动生成仍由分类判定拦截（作废槽位不自动重建）。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0020_remove_executor_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='operationledger',
            name='completed_at',
            field=models.DateTimeField(blank=True, null=True,
                                       help_text='完成填写时间（2026-10-16 新流程终点）'),
        ),
        migrations.AddField(
            model_name='operationledger',
            name='completed_by',
            field=models.ForeignKey(blank=True, null=True,
                                    help_text='完成填写人',
                                    on_delete=models.PROTECT, related_name='+',
                                    to='account.user'),
        ),
        migrations.AddField(
            model_name='operationledger',
            name='slot_active',
            field=models.BooleanField(default=True, blank=True, null=True,
                                      help_text='期次槽位占用标记（作废置 NULL 以支持补建）'),
        ),
        # AddField(default=True) 回填后，把存量作废行置 NULL（不占生成槽位）
        migrations.RunSQL(
            sql="UPDATE tdyw_el_operation_ledger SET slot_active = NULL WHERE status = 'void'",
            reverse_sql=(
                "UPDATE tdyw_el_operation_ledger SET slot_active = 1 "
                "WHERE status = 'void' AND slot_active IS NULL"),
        ),
        migrations.RemoveConstraint(
            model_name='operationledger',
            name='uniq_el_ledger_tpl_period',
        ),
        migrations.AddConstraint(
            model_name='operationledger',
            constraint=models.UniqueConstraint(
                fields=('tenant_id', 'source_template', 'system',
                        'maintenance_period', 'slot_active'),
                name='uniq_el_ledger_tpl_period'),
        ),
        # Django 4.2 无 AlterConstraint：状态值域 CHECK 用 Remove + Add 重放
        migrations.RemoveConstraint(
            model_name='operationledger',
            name='el_operation_ledger_status_valid',
        ),
        migrations.AddConstraint(
            model_name='operationledger',
            constraint=models.CheckConstraint(
                check=models.Q(status__in=[
                    'draft', 'completed', 'submitted', 'returned', 'reviewed', 'void']),
                name='el_operation_ledger_status_valid'),
        ),
    ]

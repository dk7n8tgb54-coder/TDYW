# 周月维护不再拆分周表/月表（2026-09-26）：
# 删除维护周期字段（模板/台账表头 maintenance_cycle）与项目执行范围字段
# （模板项目/明细快照 execution_scope）及其 CHECK 约束。
# 周月维护与季维护仅靠 ledger_type 区分；历史台账/模板中的周期与执行范围
# 数据随列删除，历史明细自身快照内容不受影响。
# 回滚说明：反向迁移可恢复列与约束（列为可空默认值，历史值不可恢复）。
# 部署顺序：重建镜像 → migrate。

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0034_operationledgerrowinstance_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='operationledger',
            name='el_operation_ledger_cycle_combo',
        ),
        migrations.RemoveConstraint(
            model_name='operationledgeritem',
            name='el_ledger_item_scope_valid',
        ),
        migrations.RemoveConstraint(
            model_name='operationledgertemplate',
            name='el_ledger_template_cycle_combo',
        ),
        migrations.RemoveConstraint(
            model_name='operationledgertemplateitem',
            name='el_ledger_template_item_scope_valid',
        ),
        migrations.RemoveField(
            model_name='operationledger',
            name='maintenance_cycle',
        ),
        migrations.RemoveField(
            model_name='operationledgeritem',
            name='execution_scope',
        ),
        migrations.RemoveField(
            model_name='operationledgertemplate',
            name='maintenance_cycle',
        ),
        migrations.RemoveField(
            model_name='operationledgertemplateitem',
            name='execution_scope',
        ),
    ]

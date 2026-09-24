# 旧巡检台账（历史）下线改造（2026-09-24）
# 第一步（本迁移）：为 SystemFault / SystemWorkOrder 增加 source_ledger_legacy
# legacy 来源快照字段——须在执行 purge_legacy_inspection_ledgers --confirm 之前
# 应用（清理命令要向该字段写入旧巡检来源快照后再解除来源外键）。
# 第二步（0029）：待清理命令删除全部 ledger_type='inspection' 历史数据后，
# 再收窄台账类型与周期组合 CHECK 约束（0029 带历史数据前置防护）。

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0027_remove_inspectionrecord_unit_snapshot_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemfault',
            name='source_ledger_legacy',
            field=models.TextField(blank=True, default='', help_text='旧巡检台账来源快照 JSON（台账号/类型/项目名/系统快照等；来源明细随旧巡检台账受控删除后，据此展示历史来源，不做跳转）'),
        ),
        migrations.AddField(
            model_name='systemworkorder',
            name='source_ledger_legacy',
            field=models.TextField(blank=True, default='', help_text='旧巡检台账来源快照 JSON（台账号/类型/项目名/系统快照等；来源明细随旧巡检台账受控删除后，据此展示历史来源，不做跳转）'),
        ),
    ]

# 旧巡检台账（历史）下线改造（2026-09-24）
# 第一步（本迁移，须在执行 purge_legacy_inspection_ledgers --confirm 之前应用）：
# 1. SystemFault / SystemWorkOrder 增加 source_ledger_legacy legacy 来源快照字段
#    （清理命令向该字段写入旧巡检来源快照后，再解除 source_ledger_item 外键）；
# 2. 放宽工单来源一致性 CHECK：ledger_item 来源在"外键已解除 + legacy 快照在位"
#    的迁移态仍合法（否则解除外键会违反 el_work_order_source_consistent）。
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
        migrations.RemoveConstraint(
            model_name='systemworkorder',
            name='el_work_order_source_consistent',
        ),
        migrations.AddConstraint(
            model_name='systemworkorder',
            constraint=models.CheckConstraint(check=(
                (models.Q(source_type='manual')
                 & models.Q(source_fault__isnull=True)
                 & models.Q(source_ledger_item__isnull=True)
                 & models.Q(source_inspection_record__isnull=True))
                | (models.Q(source_type='fault')
                   & models.Q(source_fault__isnull=False)
                   & models.Q(source_ledger_item__isnull=True)
                   & models.Q(source_inspection_record__isnull=True))
                | (models.Q(source_type='ledger_item')
                   & models.Q(source_fault__isnull=True)
                   & models.Q(source_inspection_record__isnull=True)
                   & (models.Q(source_ledger_item__isnull=False)
                      | (models.Q(source_ledger_item__isnull=True)
                         & ~models.Q(source_ledger_legacy=''))))
                | (models.Q(source_type='inspection_record')
                   & models.Q(source_fault__isnull=True)
                   & models.Q(source_ledger_item__isnull=True)
                   & models.Q(source_inspection_record__isnull=False))
            ), name='el_work_order_source_consistent'),
        ),
    ]

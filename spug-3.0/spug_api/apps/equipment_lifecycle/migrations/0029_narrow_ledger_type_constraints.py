# 旧巡检台账（历史）下线改造（2026-09-24）
# 第二步（本迁移）：收窄台账类型与周期组合 CHECK 约束——
# 台账类型只允许 week_month / seasonal，周期组合只保留周、月、季。
#
# 前置防护（fail-closed）：迁移开头的 RunPython 检查是否仍存在
# ledger_type='inspection' 历史数据；存在即抛错中止，提示先执行
#     python manage.py purge_legacy_inspection_ledgers --confirm
# 因为 MariaDB ALTER TABLE ... ADD CONSTRAINT 会校验存量行，
# 未清理历史数据时收窄约束会直接失败（且可能留下半程 DDL）。
#
# 生产部署顺序：重建镜像 → migrate（仅 0028 及之前生效）→
# purge_legacy_inspection_ledgers --confirm → migrate（应用本迁移）。
#
# 回滚说明：反向迁移恢复旧 CHECK（允许 inspection），不会恢复已删除的
# 历史数据；source_ledger_legacy 快照字段保留（历史来源语义仍在）。

from django.db import migrations, models


def ensure_legacy_data_purged(apps, schema_editor):
    """历史数据前置防护：仍存在旧巡检数据时中止迁移并给出操作指引。"""
    OperationLedger = apps.get_model('equipment_lifecycle', 'OperationLedger')
    OperationLedgerTemplate = apps.get_model('equipment_lifecycle', 'OperationLedgerTemplate')
    ledger_count = OperationLedger.objects.filter(ledger_type='inspection').count()
    template_count = OperationLedgerTemplate.objects.filter(ledger_type='inspection').count()
    if ledger_count or template_count:
        raise RuntimeError(
            '检测到旧巡检台账历史数据尚未清理（台账 %d 条、模板 %d 个），'
            '不能收窄台账类型 CHECK 约束。请先执行：'
            'python manage.py purge_legacy_inspection_ledgers --confirm ，'
            '然后重新运行 migrate。' % (ledger_count, template_count))


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0028_systemfault_source_ledger_legacy_and_more'),
    ]

    operations = [
        migrations.RunPython(ensure_legacy_data_purged, noop),
        migrations.RemoveConstraint(
            model_name='operationledger',
            name='el_operation_ledger_type_valid',
        ),
        migrations.RemoveConstraint(
            model_name='operationledger',
            name='el_operation_ledger_cycle_combo',
        ),
        migrations.RemoveConstraint(
            model_name='operationledgertemplate',
            name='el_ledger_template_type_valid',
        ),
        migrations.RemoveConstraint(
            model_name='operationledgertemplate',
            name='el_ledger_template_cycle_combo',
        ),
        migrations.AddConstraint(
            model_name='operationledger',
            constraint=models.CheckConstraint(check=models.Q(('ledger_type__in', ['week_month', 'seasonal'])), name='el_operation_ledger_type_valid'),
        ),
        migrations.AddConstraint(
            model_name='operationledger',
            constraint=models.CheckConstraint(check=models.Q(models.Q(('ledger_type', 'week_month'), ('maintenance_cycle__in', ['week', 'month'])), models.Q(('ledger_type', 'seasonal'), ('maintenance_cycle', 'season')), _connector='OR'), name='el_operation_ledger_cycle_combo'),
        ),
        migrations.AddConstraint(
            model_name='operationledgertemplate',
            constraint=models.CheckConstraint(check=models.Q(('ledger_type__in', ['week_month', 'seasonal'])), name='el_ledger_template_type_valid'),
        ),
        migrations.AddConstraint(
            model_name='operationledgertemplate',
            constraint=models.CheckConstraint(check=models.Q(models.Q(('ledger_type', 'week_month'), ('maintenance_cycle__in', ['week', 'month'])), models.Q(('ledger_type', 'seasonal'), ('maintenance_cycle', 'season')), _connector='OR'), name='el_ledger_template_cycle_combo'),
        ),
    ]

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""阶段字段语义调整：枚举 value → 显示名，并放宽 max_length。

- UpgradePlanStep.phase / UpgradeRecordStep.phase：max_length 20→50
- 回填历史数据：phase 存的 value（start/backup/...）替换为中文显示名
- 回退 SQL 不可逆（值已映射），用 noop
"""
from django.db import migrations, models


# 历史枚举 value → 显示名映射（与 constants.UPGRADE_PHASES 的 label 一致）
_PHASE_BACKFILL_SQL = """
UPDATE {table} SET phase = CASE phase
    WHEN 'start' THEN '升级启动'
    WHEN 'backup' THEN '备份'
    WHEN 'gray_release' THEN '灰度发布'
    WHEN 'test' THEN '升级测试'
    WHEN 'full_release' THEN '全量发布'
    WHEN 'observe' THEN '上线观察期'
    ELSE phase
END
WHERE phase IN ('start','backup','gray_release','test','full_release','observe');
"""


class Migration(migrations.Migration):

    dependencies = [
        ('upgrade', '0016_alter_upgradeplanstep_created_at_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='upgradeplanstep',
            name='phase',
            field=models.CharField(blank=True, default='', max_length=50, verbose_name='所属阶段'),
        ),
        migrations.AlterField(
            model_name='upgraderecordstep',
            name='phase',
            field=models.CharField(blank=True, default='', max_length=50, verbose_name='所属阶段'),
        ),
        migrations.RunSQL(
            sql=[
                _PHASE_BACKFILL_SQL.format(table='tdyw_upgrade_plan_steps'),
                _PHASE_BACKFILL_SQL.format(table='tdyw_upgrade_record_steps'),
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

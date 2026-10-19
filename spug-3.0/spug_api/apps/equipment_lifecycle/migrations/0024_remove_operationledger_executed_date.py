# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""删除台账表头"实际执行日期"（executed_date，2026-10-19）。

执行日期由台账表格内容（模板填写值）承载，不再单列表头维护。删除前把
"无期次标记但有执行日期"的历史台账按原读时推导口径（与
ledger_period_services.ledger_period_key 一致）物化到 maintenance_period：

- 周月维护（week_month）→ 执行日期所在自然月键 YYYY-MM；
- 季维护（seasonal）→ 执行日期所在航季键 YYYY-夏秋 / YYYY-冬春
  （夏秋=3月末周日~10月末周日，冬春=10月末周日~次年3月末周日）；

回填后周期分组/翻阅/概览统计的归属与删除前完全一致；两者皆缺的行保持
无标记（展示"未标注期次"），与删除前行为一致。回填只涉及 source_template
为 NULL 的历史行（模板生成台账创建即带标记、不在回填范围），不触碰
期次槽位唯一约束 uniq_el_ledger_tpl_period 的参与数据。

回滚路径：RemoveField 反向自动加回空列；回填的期次标记保留（推导口径是
确定性纯函数，重放迁移可得相同结果，原 executed_date 数值不可从标记逆推）。
"""
from datetime import date, timedelta

from django.db import migrations


def _last_weekday_of_month(year, month, weekday):
    """某月最后一个指定星期几（weekday: 周一=0 … 周日=6），与期次服务同口径。"""
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    return last_day - timedelta(days=(last_day.weekday() - weekday) % 7)


def _season_key(day):
    """日期所属航季期次键（与 ledger_period_services.season_key_of 同口径）。"""
    summer_start = _last_weekday_of_month(day.year, 3, 6)
    winter_start = _last_weekday_of_month(day.year, 10, 6)
    if summer_start <= day < winter_start:
        return '%04d-夏秋' % day.year
    if day >= winter_start:
        return '%04d-冬春' % day.year
    # 1~3月中属于上一年10月末开始的冬春航季
    return '%04d-冬春' % (day.year - 1)


def backfill_maintenance_period(apps, schema_editor):
    OperationLedger = apps.get_model('equipment_lifecycle', 'OperationLedger')
    rows = OperationLedger.objects.exclude(executed_date=None).filter(
        maintenance_period='')
    for ledger in rows:
        if ledger.ledger_type == 'seasonal':
            key = _season_key(ledger.executed_date)
        else:
            # 周月维护历史推导口径为自然月键（推导不产生每周键）
            key = ledger.executed_date.strftime('%Y-%m')
        ledger.maintenance_period = key
        ledger.save(update_fields=['maintenance_period'])


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0023_native_ledger_templates'),
    ]

    operations = [
        migrations.RunPython(backfill_maintenance_period, migrations.RunPython.noop),
        migrations.RemoveField(model_name='operationledger', name='executed_date'),
    ]

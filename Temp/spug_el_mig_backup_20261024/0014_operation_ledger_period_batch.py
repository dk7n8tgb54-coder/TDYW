# -*- coding: utf-8 -*-
"""周期批量新增台账：OperationLedger 增加表头级 system 外键与 maintenance_period 周期标记。

2026-10-11 维护台账周期批量新增（最小实现）：
- system：表头级系统外键，仅由"一键新增周期台账"写入（一系统一台账草稿壳）；
  历史聚合台账与 Excel 路线台账保持 NULL，不影响既有语义；
- maintenance_period：维护周期标记（week_month: YYYY-MM；seasonal: YYYY-夏秋/
  YYYY-冬春，夏秋季/冬春季为航季口径，YYYY 为航季开始年份），仅用于列表分组
  与批量新增去重，不代表恢复 0035 删除的周表/月表拆分；
- 历史数据无需回填（NULL/空串即"未参与周期批量"）。
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0013_systemoperationprogress_systemoperationrecord_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='operationledger',
            name='system',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='operation_ledgers',
                to='equipment_lifecycle.lifecyclesystem',
                help_text='表头级系统（周期批量新增的按系统台账；历史聚合台账与Excel路线为空）'),
        ),
        migrations.AddField(
            model_name='operationledger',
            name='maintenance_period',
            field=models.CharField(
                blank=True, default='', max_length=10,
                help_text='维护周期标记（week_month: YYYY-MM；seasonal: YYYY-夏秋/YYYY-冬春；'
                          '历史台账为空），仅用于周期分组与批量新增去重，不表达周/月维护拆分'),
        ),
        migrations.AddIndex(
            model_name='operationledger',
            index=models.Index(
                fields=['tenant_id', 'ledger_type', 'maintenance_period'],
                name='el_ledger_type_period_idx'),
        ),
    ]

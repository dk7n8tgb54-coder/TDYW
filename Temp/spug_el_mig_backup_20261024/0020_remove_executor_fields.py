"""删除维护台账执行人字段（2026-10-16）：

- OperationLedger.executor_names（表头执行人）与
  OperationLedgerItem.executor_name（明细执行人）一并退役；
- 列表/详情不再展示执行人，录入人（created_by）保留；
- 正向删列，历史执行人数据随列删除；反向仅恢复列结构（默认空串），
  不回填历史数据。
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0019_operationledger_source_template_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='operationledger',
            name='executor_names',
        ),
        migrations.RemoveField(
            model_name='operationledgeritem',
            name='executor_name',
        ),
    ]

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统履历事件枚举扩展：支持系统升级（upgrade）事件。

升级管理挂接系统档案后，升级登记/完成/回退写入统一履历：
- event_type 新增 'upgrade'；
- source_type 新增 'upgrade'；
- action 新增 'rollback'（升级回退）。
仅替换三个 CHECK 约束，无数据变更。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0014_remove_operationledger_collaborator_names_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='systemevent',
            name='event_type',
            field=models.CharField(
                choices=[
                    ('fault', '故障'),
                    ('work_order', '工单'),
                    ('ledger', '台账异常'),
                    ('health', '健康状态'),
                    ('config_snapshot', '配置快照'),
                    ('upgrade', '系统升级'),
                ],
                help_text='事件类型', max_length=20),
        ),
        migrations.RemoveConstraint(
            model_name='systemevent',
            name='el_system_event_type_valid',
        ),
        migrations.RemoveConstraint(
            model_name='systemevent',
            name='el_system_event_source_type_valid',
        ),
        migrations.RemoveConstraint(
            model_name='systemevent',
            name='el_system_event_action_valid',
        ),
        migrations.AddConstraint(
            model_name='systemevent',
            constraint=models.CheckConstraint(
                check=models.Q(('event_type__in', ['fault', 'work_order', 'ledger', 'health', 'config_snapshot', 'upgrade'])),
                name='el_system_event_type_valid',
            ),
        ),
        migrations.AddConstraint(
            model_name='systemevent',
            constraint=models.CheckConstraint(
                check=models.Q(('source_type__in', ['fault', 'work_order', 'ledger_item', 'health', 'config_snapshot', 'upgrade'])),
                name='el_system_event_source_type_valid',
            ),
        ),
        migrations.AddConstraint(
            model_name='systemevent',
            constraint=models.CheckConstraint(
                check=models.Q(('action__in', ['create', 'recover', 'close', 'cancel', 'convert_to_fault', 'convert_to_work_order', 'complete', 'status_change', 'snapshot', 'rollback'])),
                name='el_system_event_action_valid',
            ),
        ),
    ]

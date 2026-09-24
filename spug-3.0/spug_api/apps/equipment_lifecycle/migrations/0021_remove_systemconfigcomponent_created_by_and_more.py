# 功能下线迁移（2026-09）：配置组成项 / 配置变更历史 / 配置快照
#
# 内容：
# - SystemFault.fault_component 外键转为 fault_component_name 文本快照列，
#   RunPython 回填历史引用的组成项名称（历史故障展示不受影响）；
# - SystemWorkOrder.work_component 外键删除（work_component_name 快照列本就存在，历史保留）；
# - 删除 SystemConfigChange / SystemConfigComponent / SystemConfigSnapshot 三表。
#
# 可回滚性说明：
# - reverse 会重建三张表结构与两个外键列（空表），并删除 fault_component_name 列；
# - 已删除的三表数据与外键指向关系无法由 reverse 恢复（属功能下线的既定清理），
#   回滚前如需保留请先做好数据库备份。
from django.db import migrations, models


def backfill_fault_component_name(apps, schema_editor):
    """把历史故障的组成项名称回填到 fault_component_name 文本快照列。"""
    SystemFault = apps.get_model('equipment_lifecycle', 'SystemFault')
    SystemConfigComponent = apps.get_model('equipment_lifecycle', 'SystemConfigComponent')
    name_map = dict(
        SystemConfigComponent.objects.values_list('id', 'name')
    )
    for fault in SystemFault.objects.exclude(fault_component=None).iterator():
        name = name_map.get(fault.fault_component_id, '')
        if name:
            # 单列 update，避免触发全字段 save；分批由 iterator 控制内存
            SystemFault.objects.filter(pk=fault.pk).update(fault_component_name=name[:100])


def rollback_fault_component_name(apps, schema_editor):
    # 名称快照无法还原为外键指向关系；回滚仅恢复结构
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0020_inspectiondutyperson_inspectiondutysheet_and_more'),
    ]

    operations = [
        # 1. 先加名称快照列并回填历史数据（保证列先于外键删除存在）
        migrations.AddField(
            model_name='systemfault',
            name='fault_component_name',
            field=models.CharField(blank=True, default='', help_text='配置组成项名称快照（组成项功能下线前历史数据，仅展示）', max_length=100),
        ),
        migrations.RunPython(backfill_fault_component_name, rollback_fault_component_name),
        # 2. 删除故障/工单上指向配置组成项的外键列
        migrations.RemoveField(
            model_name='systemfault',
            name='fault_component',
        ),
        migrations.RemoveField(
            model_name='systemworkorder',
            name='work_component',
        ),
        # 3. help_text 同步（work_component_name 语义调整为历史快照）
        migrations.AlterField(
            model_name='systemworkorder',
            name='work_component_name',
            field=models.CharField(blank=True, default='', help_text='配置组成项名称快照（组成项功能下线前历史数据，仅展示）', max_length=100),
        ),
        # 4. 删除三张已下线功能的表
        migrations.DeleteModel(
            name='SystemConfigChange',
        ),
        migrations.DeleteModel(
            name='SystemConfigComponent',
        ),
        migrations.DeleteModel(
            name='SystemConfigSnapshot',
        ),
    ]

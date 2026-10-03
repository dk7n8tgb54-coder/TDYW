# -*- coding: utf-8 -*-
"""故障处置流程简化（2026-10）：新建即处置中 + 存量待处置转换。

- AlterField：SystemFault.status 默认值 pending → handling（新建故障
  不再有待处置过渡态；choices 与 DB CHECK 约束不变，pending 仍为
  合法历史状态）；
- RunPython：将存量 pending（待处置）故障一次性转换为 handling
  （处置中），避免删除"开始处置"步骤后历史待处置故障无法恢复或结案。
  反向无操作：转换不保留原状态清单，旧流程语义由恢复确认并结案接口的
  pending 兼容路径承接（从旧备份恢复的 pending 数据仍可直接结案）。
"""
from django.db import migrations, models


def convert_pending_to_handling(apps, schema_editor):
    """存量待处置故障 → 处置中（幂等：无 pending 行时零更新）。"""
    fault_model = apps.get_model('equipment_lifecycle', 'SystemFault')
    fault_model.objects.filter(status='pending').update(status='handling')


def restore_nothing(apps, schema_editor):
    """反向无操作：pending → handling 为单向收敛（见模块 docstring）。"""
    return None


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0049_runtime_record_registrar'),
    ]

    operations = [
        migrations.AlterField(
            model_name='systemfault',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', '待处置'),
                    ('handling', '处置中'),
                    ('recovered', '已恢复'),
                    ('closed', '已关闭'),
                    ('cancelled', '已作废'),
                ],
                default='handling',
                help_text='当前状态（新建即处置中；pending 为历史兼容状态，'
                          '存量由迁移转换为处置中，恢复确认并结案接口继续接受）',
                max_length=20),
        ),
        migrations.RunPython(convert_pending_to_handling, restore_nothing),
    ]

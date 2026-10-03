# -*- coding: utf-8 -*-
"""故障状态机收敛（2026-10，模块未上线无历史包袱）：
删除旧流程的 pending（待处置）/recovered（已恢复）过渡态。

- RunPython：防御性清理存量（仅开发/测试库可能出现）——pending → handling、
  recovered → handling（recovered 行的恢复确认字段保留，结案时经合并操作
  重新确认）；模块未上线，生产库无历史数据；
- RemoveConstraint + AddConstraint：CHECK 约束 el_fault_status_valid 收紧为
  ['handling', 'closed', 'cancelled']，数据库层拒绝旧状态值（先删旧约束再
  转换数据再建新约束，转换窗口内不受旧约束限制）；
- AlterField：choices 与 help_text 同步收敛为三状态。

反向：恢复旧约束与旧字段定义；数据转换为单向收敛（反向无操作）。
"""
from django.db import migrations, models


def convert_legacy_statuses(apps, schema_editor):
    """存量 pending/recovered → handling（幂等：无该类行时零更新）。"""
    fault_model = apps.get_model('equipment_lifecycle', 'SystemFault')
    fault_model.objects.filter(
        status__in=['pending', 'recovered']).update(status='handling')


def restore_nothing(apps, schema_editor):
    """反向无操作：旧状态已删除，数据单向收敛到 handling。"""
    return None


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0050_fault_create_as_handling'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='systemfault',
            name='el_fault_status_valid',
        ),
        migrations.RunPython(convert_legacy_statuses, restore_nothing),
        migrations.AddConstraint(
            model_name='systemfault',
            constraint=models.CheckConstraint(
                check=models.Q(status__in=['handling', 'closed', 'cancelled']),
                name='el_fault_status_valid',
            ),
        ),
        migrations.AlterField(
            model_name='systemfault',
            name='status',
            field=models.CharField(
                choices=[
                    ('handling', '处置中'),
                    ('closed', '已关闭'),
                    ('cancelled', '已作废'),
                ],
                default='handling',
                help_text='当前状态（新建即处置中，恢复确认并结案后进入已关闭终态）',
                max_length=20),
        ),
    ]

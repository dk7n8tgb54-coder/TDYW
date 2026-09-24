"""系统运行状态与部件维修状态分离（第一步）：故障增加"影响系统运行"开关。

- SystemFault 新增 affects_system_operation（默认 False = 部件故障/离线维修，
  不参与系统健康状态计算）；
- 存量故障全部回填 True：历史故障均是在"故障即影响系统运行"的旧语义下创建，
  回填 True 保持现有健康状态与历史语义不变，仅新记录按默认 False 处理；
- impact_status 语义收窄为"影响系统运行时的影响程度"：默认改空串，
  CHECK 约束 el_fault_impact_valid 扩展允许空串（不影响运行时后端强制存空串），
  原有三值（降级/故障/中断）保持不变。
"""
from django.db import migrations, models


def backfill_affects_true(apps, schema_editor):
    SystemFault = apps.get_model('equipment_lifecycle', 'SystemFault')
    SystemFault.objects.all().update(affects_system_operation=True)


def reverse_backfill_affects(apps, schema_editor):
    SystemFault = apps.get_model('equipment_lifecycle', 'SystemFault')
    SystemFault.objects.all().update(affects_system_operation=False)


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0018_remove_template_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemfault',
            name='affects_system_operation',
            field=models.BooleanField(
                default=False,
                help_text='是否影响系统运行（False=部件故障/离线维修，默认不影响，不参与健康状态计算；'
                          'True=影响运行，按 impact_status 参与健康状态计算）'),
        ),
        migrations.RunPython(backfill_affects_true, reverse_backfill_affects),
        migrations.AlterField(
            model_name='systemfault',
            name='impact_status',
            field=models.CharField(
                blank=True, default='', max_length=20,
                choices=[
                    ('degraded', '降级'),
                    ('fault', '故障'),
                    ('interrupted', '中断'),
                ],
                help_text='系统影响程度：影响系统运行时必填（degraded降级/fault故障/interrupted中断）；'
                          '不影响系统运行时后端强制存空串'),
        ),
        migrations.RemoveConstraint(
            model_name='systemfault',
            name='el_fault_impact_valid',
        ),
        migrations.AddConstraint(
            model_name='systemfault',
            constraint=models.CheckConstraint(
                check=models.Q(impact_status__in=['', 'degraded', 'fault', 'interrupted']),
                name='el_fault_impact_valid',
            ),
        ),
    ]

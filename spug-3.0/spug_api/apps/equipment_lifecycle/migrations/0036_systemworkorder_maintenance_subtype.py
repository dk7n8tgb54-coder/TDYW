# 工单类型收敛（2026-09-27）：SystemWorkOrder 新增维护二级分类
# maintenance_subtype（默认 general），并加 CHECK 约束 el_work_order_subtype_valid。
# 历史兼容：AddField 携带 default，历史工单迁移后统一落"一般维护"，
# 历史顶层类型（tech_reform 等）不改动，仍可查询/查看/导出。
# 回滚说明：反向迁移删除该列与约束，历史二级分类信息随之丢失。
# 部署顺序：重建镜像 → migrate。

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0035_remove_ledger_maintenance_cycle_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemworkorder',
            name='maintenance_subtype',
            field=models.CharField(choices=[('general', '一般维护'), ('config_change', '配置变更'), ('field_test', '现场测试'), ('calibration', '校准'), ('temporary_maintenance', '临时维护')], default='general', help_text='维护二级分类（仅专项维护有业务含义：一般维护/配置变更/现场测试/校准/临时维护；其他顶层类型统一落默认值且前端不展示）', max_length=30),
        ),
        migrations.AddConstraint(
            model_name='systemworkorder',
            constraint=models.CheckConstraint(check=models.Q(('maintenance_subtype__in', ['general', 'config_change', 'field_test', 'calibration', 'temporary_maintenance'])), name='el_work_order_subtype_valid'),
        ),
    ]

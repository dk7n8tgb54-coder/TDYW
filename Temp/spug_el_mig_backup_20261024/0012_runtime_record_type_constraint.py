# 2026-10-07 运行记录模块扩展（第二步）：record_type 约束与索引。
#
# - CHECK 约束 el_runtime_record_record_type_valid：record_type 仅允许
#   routine/abnormal（此时全部存量行已由迁移 0011 回填为 abnormal，约束
#   不会因历史数据失败）；
# - 索引 (tenant_id, record_type, -occurred_at, -id)：支撑列表按记录类型
#   筛选 + 发生时间排序。
# Reverse：RemoveConstraint + RemoveIndex，均幂等可回滚。
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0011_runtime_record_type'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='systemruntimerecord',
            constraint=models.CheckConstraint(
                check=models.Q(record_type__in=['routine', 'abnormal']),
                name='el_runtime_record_record_type_valid',
            ),
        ),
        migrations.AddIndex(
            model_name='systemruntimerecord',
            index=models.Index(
                fields=['tenant_id', 'record_type', '-occurred_at', '-id'],
                name='el_runtime_record_type_occ_idx',
            ),
        ),
    ]

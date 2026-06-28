# P0-2: 为审计日志增加 tenant_id + (-created_at) + (-id) 组合索引。
# 服务于时间范围筛选（start_time/end_time）+ 时间倒序分页的真实查询路径，
# 避免数据量增长后列表查询出现 Using filesort。
#
# 说明：
# - 保留 0002 中的 audit_tenant_time_idx（tenant_id + created_at）以兼容旧迁移，
#   不在此迁移中删除；是否删除待慢查询观测后决定。
# - 不改动 Meta.ordering（仍为 -id），保持现有列表排序行为向后兼容。

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('logs', '0004_remove_dup_indexes'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(
                fields=['tenant_id', '-created_at', '-id'],
                name='audit_tenant_ctime_id_idx',
            ),
        ),
    ]

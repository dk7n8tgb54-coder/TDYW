# 「系统当前配置」简化版功能：配置字段增加展示分组。
#
# 内容：
# - ConfigFieldDefinition 新增 config_group 字段（tech_param 技术参数 /
#   software 软件版本 / composition 系统构成 / other 其他配置），
#   供系统详情「系统当前配置」页签分组展示；
# - 历史字段行统一落默认值 other（其他配置），可在字段定义中重新归属分组；
# - 同步增加 DB CHECK 约束（与 field_type 约束风格一致）。
#
# 可回滚性说明：
# - reverse 删除 CHECK 约束与 config_group 列，完全可回滚；
# - 回滚会丢失字段上的分组归属信息（属功能回退的既定清理）。
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0021_remove_systemconfigcomponent_created_by_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='configfielddefinition',
            name='config_group',
            field=models.CharField(
                choices=[
                    ('tech_param', '技术参数'),
                    ('software', '软件版本'),
                    ('composition', '系统构成'),
                    ('other', '其他配置'),
                ],
                default='other',
                help_text='「系统当前配置」展示分组',
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name='configfielddefinition',
            constraint=models.CheckConstraint(
                check=models.Q(config_group__in=[
                    'tech_param', 'software', 'composition', 'other',
                ]),
                name='el_config_field_group_valid',
            ),
        ),
    ]

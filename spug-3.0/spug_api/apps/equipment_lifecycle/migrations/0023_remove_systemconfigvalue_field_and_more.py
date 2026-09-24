# 自定义字段功能下线：扩展信息转固定字段。
#
# 内容：
# - LifecycleSystem 新增 callsign（呼号）/ work_frequency（工作频率）两个
#   选填固定列（geo_coordinate 安装经纬度列此前已存在，一并构成扩展信息）；
# - 删除 ConfigFieldDefinition（自定义配置字段定义）与
#   SystemConfigValue（配置值）两表及对应 CHECK 约束、索引、唯一约束；
# - 回填：显示名称恰为「呼号」「工作频率」的自定义字段历史值，按文本表示
#   回填到同名新列（目标列已有值不覆盖，超长截断），其余自定义字段数据随
#   两表删除（历史数据以数据库备份留档）。
#
# 可回滚性说明：
# - reverse 重建两表并删除新列，结构可回滚；
# - 回滚不把新列值还原为自定义字段（属功能回退的既定清理），已回填数据保留在列上直到列被删除。
from django.db import migrations, models


def backfill_extended_fields(apps, schema_editor):
    """把「呼号」「工作频率」自定义字段的历史值回填到系统新列。"""
    system_model = apps.get_model('equipment_lifecycle', 'LifecycleSystem')
    field_model = apps.get_model('equipment_lifecycle', 'ConfigFieldDefinition')
    value_model = apps.get_model('equipment_lifecycle', 'SystemConfigValue')
    targets = {'呼号': 'callsign', '工作频率': 'work_frequency'}
    max_lengths = {'callsign': 50, 'work_frequency': 100}
    fields = field_model.objects.filter(display_name__in=list(targets.keys()))
    for field in fields:
        attr = targets[field.display_name]
        for record in value_model.objects.filter(field_id=field.pk):
            if record.value_number is not None:
                text = '%g' % record.value_number
            elif record.value_date is not None:
                text = record.value_date.isoformat()
            elif record.value_bool is not None:
                text = '是' if record.value_bool else '否'
            else:
                text = record.value_text or ''
            if not text:
                continue
            system_model.objects.filter(pk=record.system_id, **{attr: ''}).update(
                **{attr: text[:max_lengths[attr]]})


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0022_configfield_group'),
    ]

    operations = [
        migrations.AddField(
            model_name='lifecyclesystem',
            name='callsign',
            field=models.CharField(blank=True, default='', help_text='呼号，选填', max_length=50),
        ),
        migrations.AddField(
            model_name='lifecyclesystem',
            name='work_frequency',
            field=models.CharField(blank=True, default='', help_text='工作频率，选填，如 438.500MHz 或频段范围', max_length=100),
        ),
        migrations.RunPython(backfill_extended_fields, noop_reverse),
        # 注意：MariaDB 下先 RemoveField(field) 会因复合唯一索引
        # uniq_el_config_value_system_field 依赖列而报 1072；
        # 两表整体删除（先删值表再删定义表）不受影响。
        migrations.DeleteModel(
            name='SystemConfigValue',
        ),
        migrations.DeleteModel(
            name='ConfigFieldDefinition',
        ),
    ]

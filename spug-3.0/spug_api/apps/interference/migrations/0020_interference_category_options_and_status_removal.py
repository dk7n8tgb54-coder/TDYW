"""干扰分类选项表与分类状态下线。

- 新建 InterferenceCategoryOption 全平台字典表，并按既有固定枚举导入
  内置选项（受影响系统补充「未知/待查」编码 unknown）；
- 事件表下线 classification_status（删除列、索引与 CHECK），
  「待分类/已确认」概念整体退役；
- 三个分类字段的固定枚举 CHECK 一并移除，改由选项表在写入层校验；
  affected_system_code 缺省值 other → unknown，历史数据一律不改写。

2026-10-26 部署前按用户在开发环境已验证的裁剪口径精简（21→13，生产库无干扰事件历史数据），
生产首次应用即得该清单。
"""

from django.db import migrations, models
import django.db.models.deletion

# 迁移时点的固定选项快照：(分组, 编码, 名称, 排序)
# 编码一经使用不得删除或复用；后续增删改一律走维护接口，不改本快照。
# 2026-10-26 部署前按用户在开发环境已验证的裁剪口径精简（21→13，生产库无干扰事件历史数据），
# 生产首次应用即得该清单。
SEED_OPTIONS = [
    ('interference_kind', 'noise', '杂音', 10),
    ('interference_kind', 'intermittent', '间歇中断', 20),
    ('interference_kind', 'communication_loss', '完全失联', 30),
    ('interference_kind', 'unknown', '未知/待查', 80),
    ('affected_system', 'communication', '通信', 10),
    ('affected_system', 'navigation', '导航', 20),
    ('affected_system', 'surveillance', '监视', 30),
    ('affected_system', 'datalink', '数据链', 40),
    ('affected_system', 'equipment', '设备电磁兼容', 50),
    ('affected_system', 'other', '其他', 60),
    ('affected_system', 'unknown', '未知/待查', 70),
    ('source_type', 'ground_equipment', '地面设备', 10),
    ('source_type', 'unknown', '未知/待查', 60),
]


def seed_category_options(apps, schema_editor):
    Option = apps.get_model('interference', 'InterferenceCategoryOption')
    for group, code, name, sort_id in SEED_OPTIONS:
        Option.objects.get_or_create(
            group=group, code=code,
            defaults={'name': name, 'sort_id': sort_id, 'is_active': True},
        )


def remove_category_options(apps, schema_editor):
    Option = apps.get_model('interference', 'InterferenceCategoryOption')
    Option.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('interference', '0019_remove_airinterferencedetail_alert_altitude_unit_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='InterferenceCategoryOption',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('group', models.CharField(choices=[('interference_kind', '具体干扰类型'), ('affected_system', '受影响系统'), ('source_type', '疑似干扰源')], max_length=32, verbose_name='分组')),
                ('code', models.CharField(max_length=40, verbose_name='稳定编码')),
                ('name', models.CharField(max_length=100, verbose_name='名称')),
                ('sort_id', models.IntegerField(default=0, verbose_name='排序')),
                ('is_active', models.BooleanField(default=True, verbose_name='启用')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='account.user')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='account.user')),
            ],
            options={
                'verbose_name': '干扰分类选项',
                'verbose_name_plural': '干扰分类选项',
                'db_table': 'tdyw_interference_category_options',
                'ordering': ('group', 'sort_id', 'id'),
                'constraints': [
                    models.UniqueConstraint(fields=('group', 'code'), name='inter_cat_group_code_unique'),
                ],
            },
        ),
        migrations.RunPython(seed_category_options, remove_category_options),
        migrations.RemoveConstraint(
            model_name='interferenceevent', name='inter_event_class_valid'),
        migrations.RemoveIndex(
            model_name='interferenceevent', name='inter_event_class_idx'),
        migrations.RemoveConstraint(
            model_name='interferenceevent', name='inter_event_kind_valid'),
        migrations.RemoveConstraint(
            model_name='interferenceevent', name='inter_event_system_valid'),
        migrations.RemoveConstraint(
            model_name='interferenceevent', name='inter_event_source_valid'),
        migrations.RemoveField(
            model_name='interferenceevent', name='classification_status'),
        migrations.AlterField(
            model_name='interferenceevent',
            name='interference_kind_code',
            field=models.CharField(default='unknown', max_length=40, verbose_name='具体干扰类型'),
        ),
        migrations.AlterField(
            model_name='interferenceevent',
            name='affected_system_code',
            field=models.CharField(default='unknown', max_length=40, verbose_name='受影响系统'),
        ),
        migrations.AlterField(
            model_name='interferenceevent',
            name='source_type_code',
            field=models.CharField(default='unknown', max_length=40, verbose_name='疑似干扰源'),
        ),
    ]

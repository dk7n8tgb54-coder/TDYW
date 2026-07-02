# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""创建升级系统候选项字典表，并回填预设系统与历史系统。

字典表设计为全局共享（tenant_id='' 表示公共），所有租户共用同一套系统候选列表。
历史升级记录的 system 字段是纯文本，不受本表删除/停用影响。
"""
from django.db import migrations, models
from django.utils import timezone


def _now_str():
    return timezone.now().strftime('%Y-%m-%d %H:%M:%S')


def forward_add_systems(apps, schema_editor):
    """回填：预设系统 + 历史升级记录中出现过的系统。

    字典表为全局共享（tenant_id=''），回填后所有租户可见。
    预设系统 sort_order 1..N 排在前面，历史系统 sort_order=100+ 排在后面。
    """
    UpgradeSystem = apps.get_model('upgrade', 'UpgradeSystem')
    UpgradeRecord = apps.get_model('upgrade', 'UpgradeRecord')
    db_alias = schema_editor.connection.alias

    preset = [
        '运维管理平台', '数据库系统', '网络设备', '安全设备', '中间件',
        '监控系统', '备份系统', '邮件系统', 'OA系统', '其他',
    ]

    now = _now_str()
    for idx, name in enumerate(preset, start=1):
        UpgradeSystem.objects.using(db_alias).get_or_create(
            tenant_id='',
            name=name,
            defaults={'is_active': True, 'sort_order': idx, 'created_at': now},
        )

    try:
        history = UpgradeRecord.objects.using(db_alias).values_list('system', flat=True).distinct()
    except Exception:
        history = []

    for idx, name in enumerate(history, start=100):
        if not name:
            continue
        UpgradeSystem.objects.using(db_alias).get_or_create(
            tenant_id='',
            name=name,
            defaults={'is_active': True, 'sort_order': idx, 'created_at': now},
        )


def reverse_remove_systems(apps, schema_editor):
    UpgradeSystem = apps.get_model('upgrade', 'UpgradeSystem')
    db_alias = schema_editor.connection.alias
    UpgradeSystem.objects.using(db_alias).all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('upgrade', '0011_record_create_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='UpgradeSystem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(default='', max_length=50, help_text='租户标识')),
                ('name', models.CharField(max_length=100, verbose_name='系统名称')),
                ('is_active', models.BooleanField(default=True, verbose_name='是否启用')),
                ('sort_order', models.IntegerField(default=0, verbose_name='排序')),
                ('created_at', models.CharField(max_length=20, verbose_name='创建时间')),
                ('updated_at', models.CharField(blank=True, null=True, max_length=20, verbose_name='更新时间')),
                ('created_by', models.ForeignKey(related_name='+', blank=True, null=True, on_delete=models.PROTECT, to='account.user')),
                ('updated_by', models.ForeignKey(related_name='+', blank=True, null=True, on_delete=models.PROTECT, to='account.user')),
            ],
            options={
                'db_table': 'tdyw_upgrade_systems',
                'verbose_name': '升级系统候选项',
                'verbose_name_plural': '升级系统候选项',
                'ordering': ('sort_order', 'name'),
                'unique_together': {('tenant_id', 'name')},
            },
        ),
        migrations.RunPython(forward_add_systems, reverse_remove_systems),
    ]

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""移除系统类型（SystemType）机制（custom-fields-only 收口）。

- 数据操作在 DDL 之前执行：
  1) 台账模板按"适用系统类型"定义的，把该类型下全部系统写入 applicable_systems
     M2M（语义等价转换，模板不丢）；
  2) scope=template 的字段定义及其配置值删除（PROTECT 要求先删值）。
     若库中已有需要保留的模板字段值，应在应用本迁移前先行导出。
- 之后再移除各表 system_type 外键、相关索引并删除 SystemType 表。
- 反向为 no-op：已删除的数据无法自动恢复，回滚只恢复表结构不恢复数据。
"""

from django.db import migrations, models


def convert_template_type_to_systems(apps, schema_editor):
    """按类型适用的台账模板 → 显式适用该类型下全部系统。"""
    OperationLedgerTemplate = apps.get_model('equipment_lifecycle', 'OperationLedgerTemplate')
    LifecycleSystem = apps.get_model('equipment_lifecycle', 'LifecycleSystem')
    for template in OperationLedgerTemplate.objects.exclude(applicable_system_type_id=None):
        system_ids = LifecycleSystem.objects.filter(
            system_type_id=template.applicable_system_type_id,
        ).values_list('id', flat=True)
        template.applicable_systems.add(*system_ids)


def delete_template_scope_fields(apps, schema_editor):
    """删除类型模板字段定义及其配置值（先删值再删定义，满足 PROTECT）。"""
    ConfigFieldDefinition = apps.get_model('equipment_lifecycle', 'ConfigFieldDefinition')
    SystemConfigValue = apps.get_model('equipment_lifecycle', 'SystemConfigValue')
    template_fields = ConfigFieldDefinition.objects.filter(scope_type='template')
    SystemConfigValue.objects.filter(
        field_id__in=template_fields.values_list('id', flat=True)).delete()
    template_fields.delete()


def noop_reverse(apps, schema_editor):
    """数据不可自动恢复，反向仅保留表结构回滚能力。"""


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0010_systemfault_cancel_reason_systemevent_and_more'),
    ]

    operations = [
        migrations.RunPython(convert_template_type_to_systems, noop_reverse),
        migrations.RunPython(delete_template_scope_fields, noop_reverse),
        migrations.RemoveField(
            model_name='systemtype',
            name='created_by',
        ),
        migrations.RemoveField(
            model_name='systemtype',
            name='updated_by',
        ),
        migrations.RemoveIndex(
            model_name='lifecyclesystem',
            name='tdyw_el_sys_tenant__b932dd_idx',
        ),
        migrations.RemoveField(
            model_name='configfielddefinition',
            name='system_type',
        ),
        migrations.RemoveField(
            model_name='lifecyclesystem',
            name='system_type',
        ),
        migrations.RemoveField(
            model_name='operationledgertemplate',
            name='applicable_system_type',
        ),
        migrations.AlterField(
            model_name='configfielddefinition',
            name='scope_owner_id',
            field=models.CharField(help_text='归属对象ID（=系统ID）', max_length=20),
        ),
        migrations.AlterField(
            model_name='configfielddefinition',
            name='scope_type',
            field=models.CharField(choices=[('custom', '系统自定义字段')], help_text='字段作用范围', max_length=20),
        ),
        migrations.DeleteModel(
            name='SystemType',
        ),
    ]

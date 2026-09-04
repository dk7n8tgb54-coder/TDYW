# -*- coding: utf-8 -*-
"""设备档案独立化：新增 LifecycleDevice，关系改引用本应用设备档案。

设备生命周期模块的设备档案不再读取旧 device 模块（apps.device.DeviceResume），
改为本应用独立主数据；系统设备关系同步改为 DB 级外键引用新档案表。

数据策略：关系表既有行仅存在于开发/测试库（功能未上线），其 device_resume_id
指向旧模块数据、无法映射到新档案表，迁移中先洗掉这些孤儿行再加非空约束
（反向回滚为 noop，不重建历史数据）。
"""
import django.db.models.deletion
from django.db import migrations, models
import libs.tenant_base_model


def remove_orphan_relations(apps, schema_editor):
    """清除 device 引用为空的孤儿关系行（仅存在于未上线的开发/测试数据）"""
    SystemDeviceRelation = apps.get_model('equipment_lifecycle', 'SystemDeviceRelation')
    SystemDeviceRelation.objects.filter(device__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='LifecycleDevice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(default='', help_text='租户标识', max_length=50)),
                ('device_sn', models.CharField(help_text='设备资产编号，租户内唯一', max_length=50)),
                ('device_name', models.CharField(help_text='设备名称', max_length=50)),
                ('device_model', models.CharField(help_text='设备型号', max_length=50)),
                ('frequency', models.CharField(blank=True, default='', help_text='工作频率', max_length=30)),
                ('call_sign', models.CharField(blank=True, default='', help_text='设备呼号', max_length=30)),
                ('install_location', models.CharField(help_text='安装地点', max_length=200)),
                ('geo_coordinate', models.CharField(blank=True, default='', help_text='安装经纬度，格式: 经度,纬度', max_length=100)),
                ('device_purpose', models.CharField(blank=True, default='', help_text='设备用途', max_length=500)),
                ('manufacturer', models.CharField(blank=True, default='', help_text='生产厂家', max_length=100)),
                ('install_unit', models.CharField(blank=True, default='', help_text='安装单位', max_length=100)),
                ('use_unit', models.CharField(blank=True, default='', help_text='使用单位', max_length=100)),
                ('install_time', models.DateField(blank=True, help_text='安装时间', null=True)),
                ('enable_time', models.DateField(blank=True, help_text='启用时间', null=True)),
                ('current_status', models.CharField(choices=[('1', '正常'), ('2', '故障'), ('3', '维修中'), ('4', '停用'), ('5', '报废')], help_text='当前设备状况：1=正常，2=故障，3=维修中，4=停用，5=报废', max_length=20)),
                ('responsible_user_name', models.CharField(blank=True, default='', help_text='设备负责人姓名', max_length=100)),
                ('remark', models.CharField(blank=True, default='', help_text='备注', max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='account.user')),
                ('updated_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='account.user')),
            ],
            options={
                'verbose_name': '生命周期设备档案',
                'verbose_name_plural': '生命周期设备档案',
                'db_table': 'tdyw_el_device',
                'ordering': ('-created_at', '-id'),
            },
            bases=(models.Model, libs.tenant_base_model.TenantModelMixin),
        ),
        migrations.AddConstraint(
            model_name='lifecycledevice',
            constraint=models.CheckConstraint(check=models.Q(('current_status__in', ['1', '2', '3', '4', '5'])), name='el_device_status_valid'),
        ),
        migrations.AddConstraint(
            model_name='lifecycledevice',
            constraint=models.UniqueConstraint(fields=('tenant_id', 'device_sn'), name='uniq_el_device_tenant_sn'),
        ),
        migrations.AddIndex(
            model_name='lifecycledevice',
            index=models.Index(fields=['tenant_id', '-created_at', '-id'], name='el_dev_tenant_idx'),
        ),
        migrations.RemoveIndex(
            model_name='systemdevicerelation',
            name='el_rel_trio_idx',
        ),
        migrations.RemoveIndex(
            model_name='systemdevicerelation',
            name='el_rel_device_idx',
        ),
        migrations.RemoveField(
            model_name='systemdevicerelation',
            name='device_resume_id',
        ),
        migrations.AddField(
            model_name='systemdevicerelation',
            name='device',
            field=django.db.models.ForeignKey(blank=True, help_text='关联设备档案', null=True, on_delete=django.db.models.deletion.PROTECT,
                                              related_name='system_relations', to='equipment_lifecycle.lifecycledevice'),
        ),
        migrations.RunPython(remove_orphan_relations, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='systemdevicerelation',
            name='device',
            field=django.db.models.ForeignKey(help_text='关联设备档案', on_delete=django.db.models.deletion.PROTECT,
                                              related_name='system_relations', to='equipment_lifecycle.lifecycledevice'),
        ),
        migrations.AddIndex(
            model_name='systemdevicerelation',
            index=models.Index(fields=['system_id', 'device_id', 'role'], name='el_rel_trio_idx'),
        ),
        migrations.AddIndex(
            model_name='systemdevicerelation',
            index=models.Index(fields=['device_id'], name='el_rel_device_idx'),
        ),
    ]

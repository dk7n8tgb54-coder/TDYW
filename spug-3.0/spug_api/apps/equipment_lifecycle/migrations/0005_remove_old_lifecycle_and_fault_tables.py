# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""步骤一（旧结构清理）：删除旧设备生命周期四张表和旧故障两张表。

- 四张旧设备生命周期表通过 DeleteModel 删除：
  tdyw_el_device、tdyw_el_device_location、tdyw_el_system、
  tdyw_el_system_device_relation；
- 旧故障应用 apps.fault 已整体移除（其 models/migrations 不再存在），
  已执行过 fault 0001-0006 的环境中 tdyw_fault_records、tdyw_fault_parts
  两张表通过本迁移的 RunSQL 删除；全新环境中表从未创建，IF EXISTS 直接跳过；
- 旧功能尚未启用，六张表无需要保留的业务数据，不做数据迁移或备份；
- 回滚路径：反向仅能重建空表结构（RunSQL 反向为 no-op），数据级回滚
  依赖镜像回滚 + 备份恢复流程。
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0004_lifecycledevice_current_location_and_more'),
    ]

    # MariaDB 不支持事务性 DDL，DROP TABLE 会隐式提交，禁用整体事务。
    atomic = False

    operations = [
        migrations.RemoveField(
            model_name='lifecycledevicelocation',
            name='created_by',
        ),
        migrations.RemoveField(
            model_name='lifecycledevicelocation',
            name='device',
        ),
        migrations.RemoveField(
            model_name='lifecyclesystem',
            name='created_by',
        ),
        migrations.RemoveField(
            model_name='lifecyclesystem',
            name='updated_by',
        ),
        migrations.RemoveField(
            model_name='systemdevicerelation',
            name='created_by',
        ),
        migrations.RemoveField(
            model_name='systemdevicerelation',
            name='device',
        ),
        migrations.RemoveField(
            model_name='systemdevicerelation',
            name='ended_by',
        ),
        migrations.RemoveField(
            model_name='systemdevicerelation',
            name='system',
        ),
        migrations.RemoveField(
            model_name='systemdevicerelation',
            name='updated_by',
        ),
        migrations.DeleteModel(
            name='LifecycleDevice',
        ),
        migrations.DeleteModel(
            name='LifecycleDeviceLocation',
        ),
        migrations.DeleteModel(
            name='LifecycleSystem',
        ),
        migrations.DeleteModel(
            name='SystemDeviceRelation',
        ),
        # 删除旧故障表（apps.fault 已移除，无状态操作，仅做 schema 清理）
        migrations.RunSQL(
            sql=[
                'DROP TABLE IF EXISTS `tdyw_fault_parts`;',
                'DROP TABLE IF EXISTS `tdyw_fault_records`;',
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

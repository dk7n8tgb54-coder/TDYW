# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期单系统简化（故障/工单/履历）。

业务结论：各系统相互独立，不建设系统之间的故障影响关系：
- 一张故障单只关联一个故障系统（primary_system → system，含快照与影响状态改名）；
- 一张工单只关联一个作业系统（target_system → system，含快照改名），
  新增 affects_system_operation（作业期间是否影响系统运行）；
- 一条系统履历只关联一个系统（删除跨系统角色字段 role）；
- 删除故障/工单受影响系统关联模型与表。

当前功能未启用、无正式业务数据需要迁移，因此：
- 不编写业务数据映射脚本（RenameField 保留列数据语义，MariaDB 原生改名）；
- 不保留受影响系统兼容读取，不建立旧字段兼容接口。

注意：autodetector 因 help_text/related_name 同步调整未能自动识别字段改名，
本迁移由 RenameField + AlterField 手工编排；执行 `makemigrations --check`
应无进一步变更。
"""
import django.db.models.deletion
from django.db import migrations, models

# 故障影响状态合法值（与 models.SystemFault.IMPACT_CHOICES 一致，内联保证迁移自包含）
FAULT_IMPACT_VALUES = ['degraded', 'fault', 'interrupted']


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0011_remove_system_type'),
    ]

    operations = [
        # ==================== 故障：主故障系统 → 故障系统 ====================
        migrations.RenameField(
            model_name='systemfault',
            old_name='primary_system',
            new_name='system',
        ),
        migrations.RenameField(
            model_name='systemfault',
            old_name='primary_impact_status',
            new_name='impact_status',
        ),
        migrations.RenameField(
            model_name='systemfault',
            old_name='primary_system_code',
            new_name='system_code',
        ),
        migrations.RenameField(
            model_name='systemfault',
            old_name='primary_system_name',
            new_name='system_name',
        ),
        migrations.RenameField(
            model_name='systemfault',
            old_name='primary_system_location',
            new_name='system_location',
        ),
        migrations.AlterField(
            model_name='systemfault',
            name='system',
            field=models.ForeignKey(
                help_text='故障系统（外键关联系统主数据，一个故障单只关联一个系统）',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='faults',
                to='equipment_lifecycle.lifecyclesystem'),
        ),
        migrations.AlterField(
            model_name='systemfault',
            name='impact_status',
            field=models.CharField(
                choices=[('degraded', '降级'), ('fault', '故障'), ('interrupted', '中断')],
                help_text='故障系统影响状态', max_length=20),
        ),
        migrations.AlterField(
            model_name='systemfault',
            name='system_code',
            field=models.CharField(help_text='故障系统编号快照', max_length=50),
        ),
        migrations.AlterField(
            model_name='systemfault',
            name='system_name',
            field=models.CharField(help_text='故障系统名称快照', max_length=100),
        ),
        migrations.AlterField(
            model_name='systemfault',
            name='system_location',
            field=models.CharField(help_text='故障系统安装地点快照', max_length=200),
        ),
        # 故障影响状态约束改名（列已随 RenameField 更新）
        migrations.RemoveConstraint(
            model_name='systemfault',
            name='el_fault_primary_impact_valid',
        ),
        migrations.AddConstraint(
            model_name='systemfault',
            constraint=models.CheckConstraint(
                check=models.Q(impact_status__in=FAULT_IMPACT_VALUES),
                name='el_fault_impact_valid',
            ),
        ),
        # 故障系统索引重建（原索引列 primary_system → system）
        migrations.RemoveIndex(
            model_name='systemfault',
            name='tdyw_el_fau_tenant__551e7a_idx',
        ),
        migrations.AddIndex(
            model_name='systemfault',
            index=models.Index(
                fields=['tenant_id', 'system', '-occurred_at', '-id'],
                name='tdyw_el_fau_tenant__2522d2_idx'),
        ),
        # ==================== 工单：目标系统 → 作业系统 ====================
        migrations.RenameField(
            model_name='systemworkorder',
            old_name='target_system',
            new_name='system',
        ),
        migrations.RenameField(
            model_name='systemworkorder',
            old_name='target_system_code',
            new_name='system_code',
        ),
        migrations.RenameField(
            model_name='systemworkorder',
            old_name='target_system_name',
            new_name='system_name',
        ),
        migrations.RenameField(
            model_name='systemworkorder',
            old_name='target_system_location',
            new_name='system_location',
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='system',
            field=models.ForeignKey(
                help_text='作业系统（本次作业对象系统，外键关联系统主数据，一张工单只关联一个系统）',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='work_orders',
                to='equipment_lifecycle.lifecyclesystem'),
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='system_code',
            field=models.CharField(help_text='作业系统编号快照', max_length=50),
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='system_name',
            field=models.CharField(help_text='作业系统名称快照', max_length=100),
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='system_location',
            field=models.CharField(help_text='作业系统安装地点快照', max_length=200),
        ),
        migrations.AddField(
            model_name='systemworkorder',
            name='affects_system_operation',
            field=models.BooleanField(
                default=False,
                help_text='作业期间是否影响系统运行（执行中且为真才参与"维修中"计算）'),
        ),
        # 工单作业系统索引重建（原索引列 target_system → system）
        migrations.RemoveIndex(
            model_name='systemworkorder',
            name='tdyw_el_wor_tenant__6db26e_idx',
        ),
        migrations.AddIndex(
            model_name='systemworkorder',
            index=models.Index(
                fields=['tenant_id', 'system', '-created_at', '-id'],
                name='tdyw_el_wor_tenant__9e5dd1_idx'),
        ),
        # ==================== 履历：一条事件只关联一个系统 ====================
        # 先删引用 role 列的 CHECK 约束，再删列（MariaDB 禁止删除被约束引用的列）
        migrations.RemoveConstraint(
            model_name='systemevent',
            name='el_system_event_role_valid',
        ),
        migrations.RemoveField(
            model_name='systemevent',
            name='role',
        ),
        migrations.AlterField(
            model_name='systemevent',
            name='system',
            field=models.ForeignKey(
                help_text='关联系统（正式系统 ID，一条事件只关联一个系统）',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='system_events',
                to='equipment_lifecycle.lifecyclesystem'),
        ),
        # ==================== 删除受影响系统关联模型与表 ====================
        migrations.DeleteModel(
            name='SystemFaultAffectedSystem',
        ),
        migrations.DeleteModel(
            name='SystemWorkOrderAffectedSystem',
        ),
    ]

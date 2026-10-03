# -*- coding: utf-8 -*-
"""故障"作废"改版为"撤销登记"（2026-10）：
- SystemFault 新增 cancelled_at / cancelled_by（撤销时间与撤销人）：撤销登记
  操作的独立留痕，与审计字段 updated_at/updated_by 语义分离；
- 历史已撤销数据回填：cancelled_at/cancelled_by 为空的 cancelled 记录，
  从 updated_at/updated_by 回填（撤销是已撤销记录的最后一次写操作，
  两个字段即当时的撤销操作人与时间）；
- status choices 展示文案 '已作废' → '已撤销'（仅元数据，数据库值不变，
  历史数据完全兼容）；cancel_reason help_text 同步为新语义（仅元数据）。

兼容性说明：
- cancelled 状态值保持不变（CHECK 约束 el_fault_status_valid 不动），
  历史已撤销记录无需转换；
- 新字段均可空，无 default 依赖，不影响既有写入路径；
- 可回滚：反向恢复 choices/help_text 并删除两列（回填数据随列删除）。
"""
from django.db import migrations, models
import django.db.models.deletion


def backfill_cancel_operator(apps, schema_editor):
    """历史已撤销记录回填撤销人/撤销时间（来自 updated 审计字段）。

    cancelled 记录此后不允许任何写操作（编辑/进展/恢复/重复撤销均被
    视图层拒绝），updated_at/updated_by 即撤销操作的时间与人。
    """
    SystemFault = apps.get_model('equipment_lifecycle', 'SystemFault')
    SystemFault.objects.filter(
        status='cancelled', cancelled_at__isnull=True).update(
        cancelled_at=models.F('updated_at'), cancelled_by=models.F('updated_by'))


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0052_fault_reason_unknown_progress_locate'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemfault',
            name='cancelled_at',
            field=models.DateTimeField(null=True, blank=True,
                                       help_text='撤销时间（撤销登记操作写入）'),
        ),
        migrations.AddField(
            model_name='systemfault',
            name='cancelled_by',
            field=models.ForeignKey(null=True, blank=True,
                                    on_delete=django.db.models.deletion.PROTECT,
                                    related_name='+', to='account.user',
                                    help_text='撤销人（执行撤销登记的登录账号，仅用于审计与展示）'),
        ),
        # 历史已撤销记录回填撤销人/撤销时间（updated 字段即最后一次撤销操作）
        migrations.RunPython(backfill_cancel_operator, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='systemfault',
            name='cancel_reason',
            field=models.CharField(blank=True, default='', max_length=200,
                                   help_text='撤销原因（撤销错误/重复的故障登记时必填，审计与履历留痕）'),
        ),
        migrations.AlterField(
            model_name='systemfault',
            name='status',
            field=models.CharField(choices=[
                ('handling', '处置中'), ('closed', '已关闭'), ('cancelled', '已撤销')],
                default='handling', max_length=20,
                help_text='当前状态（新建即处置中，恢复确认并结案后进入已关闭终态）'),
        ),
    ]

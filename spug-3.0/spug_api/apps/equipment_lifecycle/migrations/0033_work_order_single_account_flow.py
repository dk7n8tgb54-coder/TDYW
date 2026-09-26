"""工单单账号协同流程改造（2026-09）。

背景：系统由多人共用一个账号操作，派发/接单/开始执行/提交复核/复核通过/
复核退回环节没有实际业务意义，整体下线；新工单创建即执行中。

内容：
- SystemWorkOrder 新增 completed_by（外键 account.User，可空，PROTECT）
  与 completed_at（可空时间）：完成工单动作的操作账号与时间；
  历史工单两者为空，新完成工单必写（不把历史复核人伪装成完成操作人）；
- status 字段默认值改为 executing（新工单创建即执行中）；
- owner / dispatched_by / dispatched_at / accepted_by / accepted_at /
  reviewer / reviewed_at 的 help_text 调整为"历史流程字段"（仅元数据，
  历史数据保留展示，新流程不再写入）；
- actual_start / actual_end help_text 调整为创建/完成时记录（仅元数据）；
- 数据迁移：历史 pending_dispatch / pending_accept 工单受控归并为
  executing，并按 accepted_at → dispatched_at → created_at 优先级补写
  actual_start；pending_review 不做任何自动处理（不得猜测自动完成），
  由管理命令 complete_pending_review_work_orders 人工处理。

兼容性说明：
- 历史状态值全部保留在 STATUS_CHOICES 与 CHECK 约束中，历史数据照常展示；
- AddField 均可空，无破坏性 DDL；
- 数据迁移方向为两个历史状态单向归并，反向无法可靠还原原状态，
  reverse 为 no-op（不伪造历史）。
"""
from django.db import migrations, models


def migrate_legacy_pending_statuses(apps, schema_editor):
    """pending_dispatch / pending_accept → executing，并补 actual_start。

    actual_start 优先级：accepted_at → dispatched_at → created_at；
    pending_review 保持原状（不自动完成，由人工迁移命令处理）。
    """
    SystemWorkOrder = apps.get_model('equipment_lifecycle', 'SystemWorkOrder')
    legacy_qs = SystemWorkOrder.objects.filter(
        status__in=['pending_dispatch', 'pending_accept']).order_by('id')
    for order in legacy_qs.iterator():
        actual_start = order.accepted_at or order.dispatched_at or order.created_at
        order.status = 'executing'
        order.actual_start = actual_start
        order.save(update_fields=['status', 'actual_start'])


def revert_noop(apps, schema_editor):
    """单向归并无法可靠还原原状态，反向不回滚数据。"""


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0032_fault_registrar'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemworkorder',
            name='completed_by',
            field=models.ForeignKey(blank=True, help_text='完成操作账号（完成工单动作的实际登录账号，历史工单可为空）',
                                    null=True, on_delete=models.PROTECT, related_name='+',
                                    to='account.user'),
        ),
        migrations.AddField(
            model_name='systemworkorder',
            name='completed_at',
            field=models.DateTimeField(blank=True, help_text='完成操作时间（完成工单动作发生时间）',
                                       null=True),
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='owner',
            field=models.ForeignKey(blank=True, help_text='负责人（历史流程字段，新流程不再写入；历史工单保留展示）',
                                    null=True, on_delete=models.PROTECT,
                                    related_name='owned_work_orders', to='account.user'),
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='dispatched_by',
            field=models.ForeignKey(blank=True, help_text='派发人（历史流程字段，新流程不再写入）',
                                    null=True, on_delete=models.PROTECT, related_name='+',
                                    to='account.user'),
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='dispatched_at',
            field=models.DateTimeField(blank=True, help_text='派发时间（历史流程字段，新流程不再写入）',
                                       null=True),
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='accepted_by',
            field=models.ForeignKey(blank=True, help_text='接单人（历史流程字段，新流程不再写入）',
                                    null=True, on_delete=models.PROTECT, related_name='+',
                                    to='account.user'),
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='accepted_at',
            field=models.DateTimeField(blank=True, help_text='接单时间（历史流程字段，新流程不再写入）',
                                       null=True),
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='actual_start',
            field=models.DateTimeField(blank=True,
                                       help_text='实际开始时间（创建工单时自动记录；历史工单为开始执行时间）',
                                       null=True),
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='actual_end',
            field=models.DateTimeField(blank=True, help_text='实际完成时间（完成工单时记录）',
                                       null=True),
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='reviewer',
            field=models.ForeignKey(blank=True, help_text='复核人（历史流程字段，新流程不再写入）',
                                    null=True, on_delete=models.PROTECT, related_name='+',
                                    to='account.user'),
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='reviewed_at',
            field=models.DateTimeField(blank=True, help_text='复核时间（历史流程字段，新流程不再写入）',
                                       null=True),
        ),
        migrations.AlterField(
            model_name='systemworkorder',
            name='status',
            field=models.CharField(choices=[
                ('pending_dispatch', '待派发'),
                ('pending_accept', '待接单'),
                ('executing', '执行中'),
                ('pending_review', '待复核'),
                ('completed', '已完成'),
                ('closed', '已关闭'),
                ('cancelled', '已取消'),
            ], default='executing', help_text='当前状态（新工单创建即执行中）', max_length=20),
        ),
        # 历史待派发/待接单工单受控归并为执行中并补 actual_start；
        # pending_review 不自动处理
        migrations.RunPython(migrate_legacy_pending_statuses, revert_noop),
    ]

# Add target_action / event_seq / is_override to UpgradeStatusLog + backfill event_seq

from django.db import migrations, models


def backfill_event_seq(apps, schema_editor):
    """为已有日志按 (created_at, id) 正序回填 event_seq（同一 upgrade_id 内从 1 递增）。"""
    UpgradeStatusLog = apps.get_model('upgrade', 'UpgradeStatusLog')
    # 按 upgrade_id 分组，组内按 created_at, id 正序赋值 1, 2, 3...
    current_upgrade_id = None
    seq = 0
    for log in UpgradeStatusLog.objects.order_by('upgrade_id', 'created_at', 'id'):
        if log.upgrade_id != current_upgrade_id:
            current_upgrade_id = log.upgrade_id
            seq = 0
        seq += 1
        log.event_seq = seq
        log.save(update_fields=['event_seq'])


def clear_event_seq(apps, schema_editor):
    """反向操作：清零 event_seq（字段即将被删除，无需实际操作）。"""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('upgrade', '0007_step_phase'),
    ]

    operations = [
        # 1. 新增三个字段（带默认值，对已有数据安全）
        migrations.AddField(
            model_name='upgradestatuslog',
            name='target_action',
            field=models.CharField(blank=True, default='', max_length=20, verbose_name='回退目标动作'),
        ),
        migrations.AddField(
            model_name='upgradestatuslog',
            name='event_seq',
            field=models.IntegerField(default=0, verbose_name='事件序号'),
        ),
        migrations.AddField(
            model_name='upgradestatuslog',
            name='is_override',
            field=models.BooleanField(default=False, verbose_name='是否补录/跳步'),
        ),
        # 2. 回填 event_seq
        migrations.RunPython(backfill_event_seq, clear_event_seq),
        # 3. 更新 Meta ordering（从 created_at 改为 event_seq）
        migrations.AlterModelOptions(
            name='upgradestatuslog',
            options={
                'verbose_name': '升级状态日志',
                'verbose_name_plural': '升级状态日志',
                'db_table': 'tdyw_upgrade_status_logs',
                'ordering': ('-event_seq', '-id'),
            },
        ),
        # 4. 新增复合索引 (upgrade_id, event_seq) 用于排序
        migrations.AddIndex(
            model_name='upgradestatuslog',
            index=models.Index(fields=['upgrade_id', 'event_seq'], name='tdyw_upgrad_upgrade_seq_idx'),
        ),
    ]

"""新增 LicenseReminderAck 表（执照中心模型重构）

变更内容：
1. 创建 LicenseReminderAck 表，存储用户对执照提醒的"已处理"确认
2. 数据迁移：从 RadioLicenseReminder 中提取 is_handled=True 的记录，
   反推 ack_valid_to（remind_date + days_left），写入 ack 表

设计说明：
- ack_valid_to 记录确认时的执照截止日期
- 续期后 license.valid_to 变化，旧 ack 自动失效（ack_valid_to != license.valid_to）
- 无需手动作废旧提醒，靠数据本身区分周期
"""
from django.db import migrations, models
import django.db.models.deletion
import libs.tenant_base_model
import libs.utils


def migrate_handled_to_ack(apps, schema_editor):
    """将历史 is_handled=True 的提醒记录迁移到 ack 表

    反推逻辑：ack_valid_to = remind_date + timedelta(days=days_left)
    去重：同一 (license_id, receiver_user_id, ack_valid_to) 只保留一条
    """
    from datetime import timedelta
    RadioLicenseReminder = apps.get_model('radio_license', 'RadioLicenseReminder')
    LicenseReminderAck = apps.get_model('radio_license', 'LicenseReminderAck')

    handled = RadioLicenseReminder.objects.filter(is_handled=True).values_list(
        'tenant_id', 'license_id', 'receiver_user_id', 'receiver_user_name',
        'remind_date', 'days_left', 'created_at',
    )

    seen = set()
    to_create = []
    for (tenant_id, license_id, user_id, user_name,
         remind_date, days_left, created_at) in handled:
        if not remind_date or days_left is None:
            continue
        ack_valid_to = remind_date + timedelta(days=days_left)
        key = (tenant_id, license_id, user_id, ack_valid_to)
        if key in seen:
            continue
        seen.add(key)
        to_create.append(LicenseReminderAck(
            tenant_id=tenant_id,
            license_id=license_id,
            user_id=user_id,
            user_name=user_name or '',
            ack_valid_to=ack_valid_to,
            created_at=created_at,
        ))

    if to_create:
        LicenseReminderAck.objects.bulk_create(to_create)
        print(f'[radio_license] 迁移 {len(to_create)} 条已处理记录到 LicenseReminderAck')


def reverse_migration(apps, schema_editor):
    """回滚：删除 ack 表数据（reminder 表数据不动）"""
    LicenseReminderAck = apps.get_model('radio_license', 'LicenseReminderAck')
    LicenseReminderAck.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('radio_license', '0004_remove_is_deleted'),
    ]

    operations = [
        migrations.CreateModel(
            name='LicenseReminderAck',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(default='', help_text='租户标识', max_length=50)),
                ('user_id', models.IntegerField(help_text='确认处理的用户ID')),
                ('user_name', models.CharField(default='', help_text='确认处理的用户姓名', max_length=100)),
                ('ack_valid_to', models.DateField(help_text='确认时执照的截止日期（用于续期后自动失效）')),
                ('created_at', models.CharField(default=libs.utils.human_datetime, max_length=20)),
                ('license', models.ForeignKey(help_text='执照', on_delete=django.db.models.deletion.CASCADE, related_name='reminder_acks', to='radio_license.RadioLicense')),
            ],
            options={
                'verbose_name': '执照提醒确认',
                'verbose_name_plural': '执照提醒确认',
                'db_table': 'tdyw_radio_license_reminder_ack',
                'ordering': ('-created_at',),
            },
            bases=(models.Model, libs.tenant_base_model.TenantModelMixin),
        ),
        migrations.AddIndex(
            model_name='licensereminderack',
            index=models.Index(fields=['tenant_id', 'user_id', 'license'], name='tdyw_rlra_user_idx'),
        ),
        migrations.AddConstraint(
            model_name='licensereminderack',
            constraint=models.UniqueConstraint(
                fields=('tenant_id', 'license_id', 'user_id', 'ack_valid_to'),
                name='uniq_license_user_valid_to',
            ),
        ),
        # 数据迁移：历史 is_handled=True → ack 表
        migrations.RunPython(migrate_handled_to_ack, reverse_migration),
    ]

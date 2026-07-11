# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from datetime import date

from django.db import migrations, models


def migrate_status_to_three_state(apps, schema_editor):
    """将旧的两态 status (active/expired) 按 valid_end_date 重新计算为三态

    active 本质表示"未过期"，需根据截止日期重新判定为 normal/expiring/expired。
    """
    ContractAgreement = apps.get_model('contract_agreement', 'ContractAgreement')
    today = date.today()
    for agreement in ContractAgreement.objects.all():
        if agreement.valid_end_date is None:
            status = 'normal'
        else:
            days_left = (agreement.valid_end_date - today).days
            if days_left < 0:
                status = 'expired'
            elif days_left <= 60:
                status = 'expiring'
            else:
                status = 'normal'
        if agreement.status != status:
            agreement.status = status
            agreement.save(update_fields=['status'])


class Migration(migrations.Migration):

    dependencies = [
        ('contract_agreement', '0001_initial'),
    ]

    operations = [
        # 1. 新增责任人字段（仿 RadioLicense）
        migrations.AddField(
            model_name='contractagreement',
            name='responsible_user_id',
            field=models.IntegerField(help_text='责任人ID', null=True),
        ),
        migrations.AddField(
            model_name='contractagreement',
            name='responsible_user_name',
            field=models.CharField(default='', help_text='责任人姓名', max_length=100),
        ),
        # 2. status 由两态(choices)改为三态(help_text)，default 改为 normal
        migrations.AlterField(
            model_name='contractagreement',
            name='status',
            field=models.CharField(
                default='normal',
                help_text='状态: normal/expiring/expired',
                max_length=20,
            ),
        ),
        # 3. ack 字段改名 ack_valid_end_date -> ack_valid_to（先删旧唯一约束，再改名，再加回）
        migrations.RemoveConstraint(
            model_name='contractagreementreminderack',
            name='uniq_contract_user_valid_end',
        ),
        migrations.RenameField(
            model_name='contractagreementreminderack',
            old_name='ack_valid_end_date',
            new_name='ack_valid_to',
        ),
        migrations.AddConstraint(
            model_name='contractagreementreminderack',
            constraint=models.UniqueConstraint(
                fields=('tenant_id', 'agreement_id', 'user_id', 'ack_valid_to'),
                name='uniq_contract_user_valid_end',
            ),
        ),
        # 3.5 ack_valid_to 字段帮助文本与新模型保持一致（避免 makemigrations 再次提议 AlterField）
        migrations.AlterField(
            model_name='contractagreementreminderack',
            name='ack_valid_to',
            field=models.DateField(help_text='确认时合同的截止日期（用于续期后自动失效）'),
        ),
        # 4. 数据迁移：旧 active/expired 按 valid_end_date 重新计算为三态
        migrations.RunPython(migrate_status_to_three_state, migrations.RunPython.noop),
    ]

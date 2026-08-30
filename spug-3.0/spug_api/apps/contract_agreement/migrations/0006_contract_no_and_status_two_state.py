# Contract agreement: add contract_no field; simplify status to two states
# (normal / expired, displayed as 已关闭), washing historical 'expiring' rows
# before tightening the check constraint.

from datetime import date

from django.db import migrations, models


def wash_expiring_status(apps, schema_editor):
    """把历史 'expiring' 行按截止日期归入两态：已过截止日期 → expired，否则 → normal。"""
    Contract = apps.get_model('contract_agreement', 'ContractAgreement')
    using = schema_editor.connection.alias
    today = date.today()
    Contract.objects.using(using).filter(
        status='expiring', valid_end_date__lt=today).update(status='expired')
    Contract.objects.using(using).filter(status='expiring').update(status='normal')


class Migration(migrations.Migration):

    dependencies = [
        ('contract_agreement', '0005_alter_contractagreement_status_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='contractagreement',
            name='contract_no',
            field=models.CharField(blank=True, default='', help_text='合同编号', max_length=100),
        ),
        migrations.RunPython(wash_expiring_status, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='contractagreement',
            name='status',
            field=models.CharField(choices=[('normal', '正常'), ('expired', '已关闭')], default='normal', help_text='状态: normal/expired（expired 显示为已关闭）', max_length=20),
        ),
        migrations.RemoveConstraint(
            model_name='contractagreement',
            name='contract_status_valid',
        ),
        migrations.AddConstraint(
            model_name='contractagreement',
            constraint=models.CheckConstraint(check=models.Q(('status__in', ['normal', 'expired'])), name='contract_status_valid'),
        ),
    ]

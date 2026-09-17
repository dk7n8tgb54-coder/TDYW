# 合同协议长期有效（validity_type）迁移
#
# 设计要点（见任务规约三、数据库迁移）：
# 1. 新增 validity_type，默认 fixed；
# 2. 历史记录显式回填为 fixed，不改动任何截止日期；
# 3. valid_end_date 改为可空（长期有效合同为空）；
# 4. 日期顺序约束升级为「期限一致性」组合约束，状态约束纳入 long_term；
# 5. 回滚保护：回滚操作的第一步即检查是否存在 long_term 合同，
#    存在则抛错阻断（非空 valid_end_date 结构无法表示长期合同），
#    不自动转换为 2099-12-31 等虚拟日期。该 RunPython 是最后一个操作，
#    因此反向执行时最先运行，任何 DDL 之前即被阻断。
from django.db import migrations, models


def backfill_validity_type(apps, schema_editor):
    """历史数据明确回填为 fixed（新增字段默认值之外的双保险）。"""
    ContractAgreement = apps.get_model('contract_agreement', 'ContractAgreement')
    ContractAgreement.objects.all().update(validity_type='fixed')


def noop(apps, schema_editor):
    pass


def forbid_long_term_rollback(apps, schema_editor):
    """回滚保护：存在长期有效合同时阻断回滚。"""
    ContractAgreement = apps.get_model('contract_agreement', 'ContractAgreement')
    long_term_count = ContractAgreement.objects.filter(
        validity_type='long_term').count()
    if long_term_count:
        raise RuntimeError(
            '回滚被阻止：数据库存在 %d 条长期有效合同（validity_type=long_term），'
            '回滚到 valid_end_date 非空结构后这些数据将无法表示。'
            '请先将长期合同转换为固定期限（提供合法截止日期）后再执行回滚，'
            '系统不会自动将其转换为虚拟远期日期。' % long_term_count)


class Migration(migrations.Migration):

    dependencies = [
        ('contract_agreement', '0007_remove_contractagreement_contract_status_valid_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='contractagreement',
            name='validity_type',
            field=models.CharField(choices=[('fixed', '固定期限'), ('long_term', '长期有效')], default='fixed', help_text='期限类型: fixed=固定期限 long_term=长期有效（长期有效时截止日期为空）', max_length=20),
        ),
        migrations.RunPython(backfill_validity_type, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='contractagreement',
            name='valid_end_date',
            field=models.DateField(blank=True, help_text='截止日期（长期有效合同为空）', null=True),
        ),
        migrations.AlterField(
            model_name='contractagreement',
            name='status',
            field=models.CharField(choices=[('normal', '正常'), ('expiring', '即将到期'), ('expired', '已关闭'), ('long_term', '长期有效')], default='normal', help_text='状态: normal/expiring/expired（expired 显示为已关闭）/long_term（长期有效）', max_length=20),
        ),
        migrations.RemoveConstraint(
            model_name='contractagreement',
            name='contract_date_order_valid',
        ),
        migrations.AddConstraint(
            model_name='contractagreement',
            constraint=models.CheckConstraint(check=models.Q(('validity_type__in', ['fixed', 'long_term'])), name='contract_validity_type_valid'),
        ),
        migrations.AddConstraint(
            model_name='contractagreement',
            constraint=models.CheckConstraint(check=models.Q(models.Q(('validity_type', 'fixed'), ('valid_end_date__isnull', False), ('valid_end_date__gte', models.F('valid_start_date'))), models.Q(('validity_type', 'long_term'), ('valid_end_date__isnull', True)), _connector='OR'), name='contract_validity_consistent'),
        ),
        migrations.RemoveConstraint(
            model_name='contractagreement',
            name='contract_status_valid',
        ),
        migrations.AddConstraint(
            model_name='contractagreement',
            constraint=models.CheckConstraint(check=models.Q(('status__in', ['normal', 'expiring', 'expired', 'long_term'])), name='contract_status_valid'),
        ),
        # 必须保持为最后一个操作：反向迁移时最先执行回滚保护检查
        migrations.RunPython(noop, forbid_long_term_rollback),
    ]

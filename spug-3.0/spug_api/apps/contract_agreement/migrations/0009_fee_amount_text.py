# 合同协议费用字段文本化迁移（fee_amount: DecimalField → CharField）
#
# 设计要点（见任务规约 六、七）：
# 1. fee_amount 由 DECIMAL(12,2) 改为 varchar(200) NOT NULL，支持「12000元/年」
#    「按实际结算」「约30万元」等自由文本；API 字段名保持 fee_amount 不变；
# 2. fee_currency 固定「人民币」与自由文本费用语义冲突，随本次一并退役；
# 3. 操作顺序（面向 MariaDB ALTER，不依赖隐式转换）：
#    a. 数据预检在任何 DDL 之前执行（MySQL DDL 隐式提交，先做数据检查
#       可保证迁移被阻断时库结构未动、可安全重试）：has_fee=true 且
#       fee_amount 为 NULL 属异常数据，统计后直接阻断迁移（不静默伪造
#       费用内容）；has_fee=false 的 NULL 先回填 0 仅作类型转换占位，
#       转文本后再统一规范为 ''；
#    b. 再删依赖 Decimal 非负判断的旧约束 contract_fee_valid；
#    c. AlterField 为文本字段（MariaDB 将 DECIMAL 值转为普通十进制字符串，
#       不产生科学计数法/货币前缀）；
#    d. 文本化后规范化：无费用记录统一清空 fee_amount 与残留 fee_detail；
#    e. 添加新的文本费用检查约束（has_fee=false 或 fee_amount 非空串）；
# 4. 回滚保护（fail-closed）：最后一个 RunPython 的反向最先执行，逐一校验
#    has_fee=true 的 fee_amount 能否无损转回 Decimal；存在「按实际结算」等
#    非纯数字文本时阻断回滚，不静默改成 0/NULL/删除。has_fee=false 的空串
#    在回滚前回填 '0' 占位（等价旧结构无费用语义，再次前滚会重新规范为 ''）。
from decimal import Decimal, InvalidOperation

from django.db import migrations, models


def preflight_normalize_nulls(apps, schema_editor):
    """类型转换前置处理：统计并阻断异常 NULL，回填无费用 NULL 占位。"""
    ContractAgreement = apps.get_model('contract_agreement', 'ContractAgreement')
    anomaly = ContractAgreement.objects.filter(
        has_fee=True, fee_amount__isnull=True).count()
    if anomaly:
        raise RuntimeError(
            '迁移被阻止：发现 %d 条 has_fee=true 且 fee_amount 为 NULL 的异常合同。'
            '按规约不得静默生成虚假费用内容，请先人工核实并补齐这些记录的费用字段，'
            '再重新执行迁移。' % anomaly)
    # has_fee=false 的历史 NULL 回填 0 仅作类型转换占位，
    # 转为文本字段后由下一步统一规范为 ''，不改变「无费用」语义
    ContractAgreement.objects.filter(
        has_fee=False, fee_amount__isnull=True).update(fee_amount=0)


def normalize_text_fee(apps, schema_editor):
    """文本化后规范化：无费用记录统一清空费用内容与明细。"""
    ContractAgreement = apps.get_model('contract_agreement', 'ContractAgreement')
    ContractAgreement.objects.filter(has_fee=False).update(
        fee_amount='', fee_detail='')
    # 防御：has_fee=true 且费用为空串的记录会让新约束添加失败，显式报错
    empty_paid = ContractAgreement.objects.filter(
        has_fee=True, fee_amount='').count()
    if empty_paid:
        raise RuntimeError(
            '迁移被阻止：发现 %d 条 has_fee=true 且费用内容为空串的异常合同，'
            '请先人工补齐费用内容后再执行迁移。' % empty_paid)


def forbid_non_numeric_fee_rollback(apps, schema_editor):
    """回滚保护（fail-closed）：非纯数字费用文本无法无损恢复为 DECIMAL。"""
    ContractAgreement = apps.get_model('contract_agreement', 'ContractAgreement')
    blocked = 0
    sample = ''
    for fee_amount, in ContractAgreement.objects.filter(
            has_fee=True).values_list('fee_amount'):
        try:
            Decimal(fee_amount)
        except (InvalidOperation, ValueError, TypeError):
            blocked += 1
            if not sample:
                sample = fee_amount
    if blocked:
        raise RuntimeError(
            '回滚被阻止：%d 条有费用合同的费用内容无法无损转换为 DECIMAL（示例：%r）。'
            '回滚到 DecimalField 会丢失「12000元/年」「按实际结算」等文本费用，'
            '系统不会将其静默改为 0、NULL 或删除。请先人工导出并处理这些费用文本'
            '（转换为纯数字或明确放弃），再重新执行回滚。' % (blocked, sample))
    # 无费用记录的空串在旧 DECIMAL 结构中无法表达，回填 '0' 占位
    # （等价旧结构无费用语义；若再次前滚会被重新规范为 ''）
    ContractAgreement.objects.filter(has_fee=False).update(fee_amount='0')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('contract_agreement', '0008_long_term_validity'),
    ]

    operations = [
        # 1. 数据预检在任何 DDL 之前：阻断异常 NULL + 无费用 NULL 占位
        #    （被阻断时库结构未动，可直接修正数据后重试迁移）
        migrations.RunPython(preflight_normalize_nulls, migrations.RunPython.noop),
        # 2. 删依赖 Decimal 非负判断的旧约束，避免阻止字段类型 ALTER
        migrations.RemoveConstraint(
            model_name='contractagreement',
            name='contract_fee_valid',
        ),
        # 3. DecimalField → CharField（历史数值由 MariaDB 转为普通十进制字符串）
        migrations.AlterField(
            model_name='contractagreement',
            name='fee_amount',
            field=models.CharField(blank=True, default='', help_text='费用内容', max_length=200),
        ),
        # 4. 文本化后规范化无费用记录
        migrations.RunPython(normalize_text_fee, migrations.RunPython.noop),
        # 5. 退役固定币种字段（回滚时由 Django 以默认值「人民币」重建列）
        migrations.RemoveField(
            model_name='contractagreement',
            name='fee_currency',
        ),
        # 6. 新的文本费用检查约束：无费用，或费用内容非空串
        migrations.AddConstraint(
            model_name='contractagreement',
            constraint=models.CheckConstraint(
                check=models.Q(has_fee=False) | ~models.Q(fee_amount=''),
                name='contract_fee_content_valid',
            ),
        ),
        # 必须保持为最后一个操作：反向迁移时最先执行回滚保护检查
        migrations.RunPython(noop, forbid_non_numeric_fee_rollback),
    ]

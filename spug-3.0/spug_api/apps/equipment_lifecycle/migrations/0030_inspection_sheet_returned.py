# 巡检单"退回整改"改造（2026-09-25）。
"""巡检单新增"已退回"状态与退回留痕字段。

内容：
- InspectionDutySheet 新增 returned_at / returned_by / return_reason 三列
  （退回人/退回时间/退回原因，超级管理员退回整改留痕）；
- status 字段 choices 增加 returned（已退回）；
- 放宽状态 CHECK 约束 el_ins_sheet_status_valid：值列表新增 'returned'。

兼容性说明：
- 新列均可空或有默认值，历史 draft/submitted/void 数据无需回填；
- CHECK 约束为"放宽"（只增加合法值），存量行全部满足新约束；
- 可回滚：反向删除三列并恢复旧约束；若库中已存在 status='returned'
  的行，恢复旧 CHECK 时 MariaDB 校验存量行会直接报错中止（fail-closed，
  需先处理已退回数据再回滚）。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0029_narrow_ledger_type_constraints'),
    ]

    operations = [
        migrations.AddField(
            model_name='inspectiondutysheet',
            name='returned_at',
            field=models.DateTimeField(blank=True, null=True,
                                       help_text='退回时间'),
        ),
        migrations.AddField(
            model_name='inspectiondutysheet',
            name='returned_by',
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=models.PROTECT, related_name='+',
                                    to='account.user',
                                    help_text='退回人（超级管理员）'),
        ),
        migrations.AddField(
            model_name='inspectiondutysheet',
            name='return_reason',
            field=models.CharField(blank=True, default='', max_length=200,
                                   help_text='退回原因（超级管理员退回整改留痕）'),
        ),
        migrations.AlterField(
            model_name='inspectiondutysheet',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft', '草稿'),
                    ('submitted', '已提交'),
                    ('returned', '已退回'),
                    ('void', '已作废'),
                ],
                default='draft', help_text='当前状态', max_length=20),
        ),
        # Django 4.2 无 AlterConstraint：先删旧 CHECK 再加放宽后的新 CHECK
        # （只增加合法值，存量 draft/submitted/void 行全部满足新约束）
        migrations.RemoveConstraint(
            model_name='inspectiondutysheet',
            name='el_ins_sheet_status_valid',
        ),
        migrations.AddConstraint(
            model_name='inspectiondutysheet',
            constraint=models.CheckConstraint(
                check=models.Q(status__in=['draft', 'submitted', 'returned', 'void']),
                name='el_ins_sheet_status_valid',
            ),
        ),
    ]

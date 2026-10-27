# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""规律调查生命周期收敛：六状态退役为三态，新增 result/cancel_reason。

- 状态映射（保守）：draft/observing/measuring → investigating；
  concluded/closed → ended；cancelled 不变；
- 禁止从自由文本 conclusion 推断 result：历史行 result 一律置空串，
  「发现规律/未发现规律/暂无法确认」只能由用户通过结束调查动作提交；
- 操作顺序（MariaDB 语义）：先移除旧 CHECK inter_inv_status_valid，
  再映射数据，然后变更字段、新增列，最后按新三态重建同名 CHECK，
  顺序颠倒会撞旧 CHECK 拒写新值；
- 反向回滚有损：investigating → draft、ended → concluded、
  cancelled → cancelled。observing/measuring 与 draft 的区分、
  concluded 与 closed 的区分在正向映射时已被抹平，不可恢复。
"""

from django.db import migrations, models

# (旧状态, 新状态)；cancelled 保持不变，不在此列
FORWARD_STATUS_MAP = (
    ('draft', 'investigating'),
    ('observing', 'investigating'),
    ('measuring', 'investigating'),
    ('concluded', 'ended'),
    ('closed', 'ended'),
)


def forward_map_status(apps, schema_editor):
    # RunPython 历史模型 ORM 经全局路由选库（不受 --database 约束），
    # 显式 using 迁移连接，保证 migrate --database=xxx 时数据映射落在
    # 正在迁移的库上。
    alias = schema_editor.connection.alias
    Investigation = apps.get_model('interference', 'InterferenceInvestigation')
    for old_status, new_status in FORWARD_STATUS_MAP:
        Investigation.objects.using(alias).filter(status=old_status).update(
            status=new_status)


def backward_restore_status(apps, schema_editor):
    """反向回滚有损：只能给出保守近似值，不得伪称无损。

    - investigating → draft：正向迁移前 observing/measuring 行也被映射成
      investigating，回滚后无法区分它们与原 draft 行；
    - ended → concluded：正向迁移前 closed 行也被映射成 ended，回滚后
      无法区分它们与原 concluded 行；
    - cancelled → cancelled：无信息损失。
    """
    alias = schema_editor.connection.alias
    Investigation = apps.get_model('interference', 'InterferenceInvestigation')
    Investigation.objects.using(alias).filter(status='investigating').update(
        status='draft')
    Investigation.objects.using(alias).filter(status='ended').update(
        status='concluded')


class Migration(migrations.Migration):

    dependencies = [
        ('interference', '0020_interference_category_options_and_status_removal'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='interferenceinvestigation', name='inter_inv_status_valid'),
        migrations.RunPython(forward_map_status, backward_restore_status),
        migrations.AlterField(
            model_name='interferenceinvestigation',
            name='status',
            field=models.CharField(
                choices=[('investigating', '调查中'), ('ended', '已结束'),
                         ('cancelled', '已取消')],
                default='investigating', max_length=20),
        ),
        migrations.AddField(
            model_name='interferenceinvestigation',
            name='result',
            field=models.CharField(
                blank=True,
                choices=[('found', '发现规律'), ('not_found', '未发现规律'),
                         ('undetermined', '暂无法确认')],
                default='', max_length=20, verbose_name='调查结果'),
        ),
        migrations.AddField(
            model_name='interferenceinvestigation',
            name='cancel_reason',
            field=models.TextField(blank=True, default='', verbose_name='取消原因'),
        ),
        migrations.AddConstraint(
            model_name='interferenceinvestigation',
            constraint=models.CheckConstraint(
                check=models.Q(status__in=['investigating', 'ended', 'cancelled']),
                name='inter_inv_status_valid'),
        ),
    ]

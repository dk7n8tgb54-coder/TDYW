# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级记录编号回归（2026-10）。

0021 曾删除 upgrade_no 字段；本次按 2026-10 决策为升级记录恢复编号
（SJ+创建日期+当日四位序号，当日序号跨租户共享，规则对齐故障编号 GZ /
运行记录编号 YX）。四步走（先洗数据再加约束，见项目迁移纪律）：
1. AddField：带临时 default='' 加列（历史行先落空串）；
2. RunPython：按 created_at 当日、跨租户、创建先后顺序回填编号
   （含软删除记录，编号不回收复用）；
3. AlterField：去掉临时 default，模型层无默认值（创建入口必须显式分配编号）；
4. AddConstraint：(tenant_id, upgrade_no) 唯一约束作并发兜底。

回滚路径：反向时 AddConstraint/AlterField/AddField 由 Django 依次还原，
回填 RunPython 反向为 no-op（编号随第 1 步反向删列一并消失，数据丢失
是删列的固有语义，无需哨兵阻断）。
"""
import datetime

from django.db import migrations, models


def _backfill_upgrade_no(apps, schema_editor):
    """为存量升级记录回填升级编号。

    与 generate_upgrade_no 的规则保持一致：SJ{created_at 当日}-{当日序号:04d}。
    序列按 created_at 当日分组、跨租户、创建先后（created_at, id）连续分配，
    因此回填后的最大序号与正式创建路径的"当日最大有效后缀 +1"自然衔接。
    历史模型管理器为普通 Manager，天然包含软删除记录（is_deleted=True）。
    """
    UpgradeRecord = apps.get_model('upgrade', 'UpgradeRecord')
    fallback_day = datetime.date(2000, 1, 1)  # 防御：created_at 理论上不为空
    seq_by_day = {}
    for record in UpgradeRecord.objects.all().order_by('created_at', 'id').iterator():
        day = record.created_at.date() if record.created_at else fallback_day
        seq = seq_by_day.get(day, 0) + 1
        seq_by_day[day] = seq
        record.upgrade_no = 'SJ%s-%04d' % (day.strftime('%Y%m%d'), seq)
        record.save(update_fields=['upgrade_no'])


class Migration(migrations.Migration):

    dependencies = [
        ('upgrade', '0022_upgrade_record_template_link_lifecycle_system'),
    ]

    operations = [
        migrations.AddField(
            model_name='upgraderecord',
            name='upgrade_no',
            field=models.CharField(default='', help_text='升级编号（SJ+创建日期+当日四位序号，自动生成；当日序号跨租户共享）', max_length=50),
        ),
        migrations.RunPython(_backfill_upgrade_no, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='upgraderecord',
            name='upgrade_no',
            field=models.CharField(help_text='升级编号（SJ+创建日期+当日四位序号，自动生成；当日序号跨租户共享，'
                                             '由 RecordService.create_record 等创建入口在 upgrade_record_no '
                                             '全局锁内分配，存量历史数据由迁移 0023 按创建日期回填）', max_length=50),
        ),
        migrations.AddConstraint(
            model_name='upgraderecord',
            constraint=models.UniqueConstraint(fields=('tenant_id', 'upgrade_no'), name='uniq_upgrade_tenant_no'),
        ),
    ]

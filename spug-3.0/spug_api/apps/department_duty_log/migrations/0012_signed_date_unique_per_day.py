# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""同日唯一签署约束：nullable signed_date 载体 + 唯一索引 + 一致性 CHECK。

业务规则：
- 同一天允许多条 draft（草稿不限量）；
- 未删除记录中同一 duty_date 最多一条 status=signed；
- 原 signed 退回 draft 后释放该日期，其他草稿可再签署。

实现方式（MariaDB 10.8 兼容，不用 PostgreSQL partial unique index）：
- 新增可空列 signed_date：signed 时等于 duty_date，draft 时为 NULL；
- 唯一索引利用 MariaDB「唯一索引允许多个 NULL」的特性：草稿（含历史草稿）
  不占用日期，退回置 NULL 即释放日期；
- CHECK 约束 duty_log_signed_date_valid 锁定 signed_date 与 status/duty_date
  的一致性，防止直接 ORM 写入造成静默漂移；
- 并发兜底由唯一索引本身承担，服务层同时捕获 IntegrityError 转业务错误。

迁移顺序（不能把数据清洗藏在 AddConstraint 里）：
1. 加可空列（暂不带唯一索引，避免重复数据直接卡死在加列阶段）；
2. RunPython 只读预检查同日 signed 重复：发现重复即抛出详细报告并中止
   迁移（不擅自决定保留哪条，需人工决策后清洗再重试），无重复则回填
   signed_date = duty_date（draft 保持 NULL，软删除记录一并如实报告）；
3. 为 signed_date 加唯一索引；
4. 加一致性 CHECK 约束。

回滚路径：RemoveConstraint -> 去掉唯一索引 -> 列随迁移回滚删除；
回填无需逆向（列删除即数据消失），noop 即可。
"""
import logging

from django.db import migrations, models
from django.db.models import F

logger = logging.getLogger(__name__)


def report_and_backfill_signed_date(apps, schema_editor):
    """只读预检查同日 signed 重复 -> 回填 signed_date。

    任何一步发现数据问题都只报告、不清洗：是否保留哪条必须由人工决策。
    """
    DepartmentDutyLog = apps.get_model('department_duty_log', 'DepartmentDutyLog')

    # 1. 同日 signed 重复检查（含软删除记录：唯一索引覆盖全表）
    duplicates = (
        DepartmentDutyLog.objects
        .filter(status='signed')
        .values('duty_date')
        .annotate(record_count=models.Count('id'))
        .filter(record_count__gt=1)
        .order_by('duty_date')
    )
    if duplicates.exists():
        lines = []
        for dup in duplicates.order_by('duty_date'):
            rows = DepartmentDutyLog.objects.filter(
                status='signed', duty_date=dup['duty_date']).order_by('id')
            for row in rows:
                lines.append(
                    '  id=%s duty_date=%s status=%s deleted_at=%s duty_person_name=%s'
                    % (row.id, row.duty_date, row.status, row.deleted_at, row.duty_person_name))
        raise RuntimeError(
            '[department_duty_log 0012] 迁移中止：发现同一 duty_date 存在多条 signed 记录，'
            '无法添加同日唯一约束。请人工决策保留哪条并清洗后再重试迁移。重复明细：\n'
            + '\n'.join(lines)
        )

    # 2. 软删除的 signed 记录如实报告（服务层不允许删除已签记录，
    #    理论上不应存在；若存在则说明是历史遗留，其日期占用将保留）
    deleted_signed = DepartmentDutyLog.objects.filter(
        status='signed', deleted_at__isnull=False).order_by('id')
    if deleted_signed.exists():
        for row in deleted_signed:
            logger.warning(
                '[department_duty_log 0012] 发现软删除的 signed 记录（历史遗留，'
                '其 duty_date 将继续被占用）：id=%s duty_date=%s deleted_at=%s',
                row.id, row.duty_date, row.deleted_at,
            )

    # 3. 回填：signed -> signed_date = duty_date；draft 保持 NULL（默认值）
    DepartmentDutyLog.objects.filter(
        status='signed', signed_date__isnull=True,
    ).update(signed_date=F('duty_date'))


class Migration(migrations.Migration):

    dependencies = [
        ('department_duty_log', '0011_remove_departmentdutylog_duty_log_signature_fields_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='departmentdutylog',
            name='signed_date',
            field=models.DateField(
                blank=True, help_text='签署占用日期：signed 时等于 duty_date，draft 时为 NULL；同日唯一约束的载体',
                null=True),
        ),
        migrations.RunPython(
            report_and_backfill_signed_date,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='departmentdutylog',
            name='signed_date',
            field=models.DateField(
                blank=True, help_text='签署占用日期：signed 时等于 duty_date，draft 时为 NULL；同日唯一约束的载体',
                null=True, unique=True),
        ),
        migrations.AddConstraint(
            model_name='departmentdutylog',
            constraint=models.CheckConstraint(
                check=(
                    (
                        models.Q(status='draft') &
                        models.Q(signed_date__isnull=True)
                    ) | (
                        models.Q(status='signed') &
                        models.Q(signed_date__isnull=False) &
                        models.Q(signed_date=models.F('duty_date'))
                    )
                ),
                name='duty_log_signed_date_valid',
            ),
        ),
    ]

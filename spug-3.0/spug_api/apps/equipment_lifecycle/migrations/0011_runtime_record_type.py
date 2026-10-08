# 2026-10-07 运行记录模块扩展（第一步）：增加 record_type 记录类型字段。
#
# 取值：routine 日常运行 / abnormal 异常事件（choices + CHECK 约束见迁移 0012）。
# 历史数据回填：AddField 携带 default='abnormal'，DDL 直接以默认值回填全部
# 存量行为 abnormal——所有历史运行异常记录统一归入"异常事件"，不删除、不
# 改写任何业务/审计/附件数据；本迁移即回填迁移（一步完成加列 + 回填，
# Reverse 为 RemoveField 整列删除，幂等可回滚）。
#
# 兼容口径：旧请求未传 record_type 时视图层按 abnormal 处理（与回填口径
# 一致）；record_type 创建后不可修改。
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0010_runtime_record_triage_retirement'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemruntimerecord',
            name='record_type',
            field=models.CharField(
                choices=[
                    ('routine', '日常运行'),
                    ('abnormal', '异常事件'),
                ],
                default='abnormal',
                help_text='记录类型（routine日常运行/abnormal异常事件；历史数据已回填为'
                          'abnormal，旧请求未传时按abnormal兼容处理；创建后不可修改）',
                max_length=20,
            ),
        ),
    ]

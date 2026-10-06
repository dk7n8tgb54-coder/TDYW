# 2026-10-06 重复问题功能整体退役：删除运行异常记录重复关联表与
# is_repeated（是否重复发生）列。
#
# 功能已于 2026-10-05 下线（前端入口整体移除，新流程不再写入 is_repeated、
# 不再建立重复关联）；本迁移清理残留的结构：
# - SystemRuntimeRecordDuplicateLink（tdyw_el_runtime_record_link）：历史关联
#   行随表删除（下线时存量关联数据清零，属退役功能的关联标记，非业务审计
#   信息；正式记录本体不受影响）；
# - SystemRuntimeRecord.is_repeated：存量值全部为 False（0 行标记），删除后
#   无信息损失。
#
# 回滚（Reverse）：
# - RemoveField 反向补建 is_repeated 空列（default=False，与删除前取值一致）；
# - DeleteModel 反向重建空表与约束/索引，历史关联行不恢复。
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0007_runtime_record_status_backfill'),
    ]

    operations = [
        migrations.DeleteModel(
            name='systemruntimerecordduplicatelink',
        ),
        migrations.RemoveField(
            model_name='systemruntimerecord',
            name='is_repeated',
        ),
    ]

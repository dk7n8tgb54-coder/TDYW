# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""删除 tdyw_regulation_attachment 表的历史遗留 is_primary 列

背景：
- 当前 RegulationAttachment 模型没有 is_primary 字段（代码库 0 匹配）。
- 0001_initial.py 也未创建该列。
- 但实际数据库（spug 库）存在 is_primary tinyint(1) NOT NULL 无默认值，
  导致 RegulationAttachment.objects.create() 插入时报错：
  (1364, "Field 'is_primary' doesn't have a default value")
- 该列是早期手动 ALTER TABLE 添加的试验性遗留，从未被模型/接口使用。

处理：用 RunPython 检查列是否存在再安全删除，避免无该列的环境报错；
反向操作不恢复该垃圾列。
"""
from django.db import migrations


def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'tdyw_regulation_attachment' "
            "AND COLUMN_NAME = 'is_primary'"
        )
        if cur.fetchone()[0] > 0:
            cur.execute(
                "ALTER TABLE tdyw_regulation_attachment DROP COLUMN is_primary"
            )


def backwards(apps, schema_editor):
    # 反向不恢复历史遗留垃圾列
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('regulation', '0001_initial'),
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]

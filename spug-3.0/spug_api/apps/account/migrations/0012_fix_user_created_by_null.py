"""修复 users.created_by_id 列允许 NULL（迁移状态与数据库不一致）。

迁移状态已认为 created_by 是 null=True，但实际数据库列不允许 NULL。
AlterField 不会生成 SQL（因为状态没变化），所以用 RunSQL 强制修复。
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0011_remove_null_from_string_fields'),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE users MODIFY COLUMN created_by_id BIGINT NULL",
            reverse_sql="ALTER TABLE users MODIFY COLUMN created_by_id BIGINT NOT NULL",
        ),
    ]

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
文件夹唯一约束：从条件约束改为 unique_key 方案

原因：MariaDB 不支持部分唯一索引（WHERE 条件），
Django 的 UniqueConstraint(condition=...) 只在 PostgreSQL/SQLite 上创建数据库索引，
在 MariaDB 上静默跳过，不产生实际约束。

方案：添加 unique_key 字段（MD5 哈希）：
- 未删除记录：unique_key = MD5(组合键字符串)（参与唯一约束）
- 已删除记录：unique_key = NULL（MySQL 中 NULL 不参与唯一索引，不占位）

迁移拆分为 4 步（避免唯一约束与回填数据冲突）：
1. 删除 0004 的无效条件约束
2. 添加 unique_key 字段（不带 unique，仅 db_index）
3. 回填 unique_key 并检查重复
4. 将 unique_key 改为 unique=True
"""

import hashlib
from django.db import migrations, models, connection


def backfill_unique_key_private(apps, schema_editor):
    """回填私有文件夹 unique_key"""
    with connection.cursor() as cursor:
        # 回填
        cursor.execute("""
            UPDATE tdyw_document_folder_private
            SET unique_key = MD5(CONCAT(
                COALESCE(tenant_id, ''),
                ':',
                COALESCE(created_by_id, 0),
                ':',
                name,
                ':',
                COALESCE(parent_id, 'ROOT')
            ))
            WHERE is_deleted = 0 AND unique_key IS NULL
        """)
        updated = cursor.rowcount
        print(f'  [Private] backfill: {updated} rows updated')

        # 检查是否有重复的 unique_key（如有则中断迁移）
        cursor.execute("""
            SELECT unique_key, COUNT(*) as cnt
            FROM tdyw_document_folder_private
            WHERE is_deleted = 0 AND unique_key IS NOT NULL
            GROUP BY unique_key
            HAVING cnt > 1
        """)
        dupes = cursor.fetchall()
        if dupes:
            dup_detail = ', '.join(f'{key}: {cnt}条' for key, cnt in dupes[:10])
            raise RuntimeError(
                f'[Private] 发现 {len(dupes)} 组重复 unique_key，迁移中止！'
                f'请先清理重复数据后再重新迁移。重复项: {dup_detail}'
            )


def backfill_unique_key_public(apps, schema_editor):
    """回填公共文件夹 unique_key"""
    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE tdyw_document_folder_public
            SET unique_key = MD5(CONCAT(
                name,
                ':',
                COALESCE(parent_id, 'ROOT')
            ))
            WHERE is_deleted = 0 AND unique_key IS NULL
        """)
        updated = cursor.rowcount
        print(f'  [Public] backfill: {updated} rows updated')

        cursor.execute("""
            SELECT unique_key, COUNT(*) as cnt
            FROM tdyw_document_folder_public
            WHERE is_deleted = 0 AND unique_key IS NOT NULL
            GROUP BY unique_key
            HAVING cnt > 1
        """)
        dupes = cursor.fetchall()
        if dupes:
            dup_detail = ', '.join(f'{key}: {cnt}条' for key, cnt in dupes[:10])
            raise RuntimeError(
                f'[Public] 发现 {len(dupes)} 组重复 unique_key，迁移中止！'
                f'请先清理重复数据后再重新迁移。重复项: {dup_detail}'
            )


def reverse_backfill(apps, schema_editor):
    """回滚：清空 unique_key"""
    with connection.cursor() as cursor:
        cursor.execute("UPDATE tdyw_document_folder_private SET unique_key = NULL")
        cursor.execute("UPDATE tdyw_document_folder_public SET unique_key = NULL")


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0004_folder_unique_constraints'),
    ]

    operations = [
        # ===== 1. 删除 0004 添加的无效条件约束 =====
        migrations.RemoveConstraint(
            model_name='documentfolderprivate',
            name='unique_root_folder_private',
        ),
        migrations.RemoveConstraint(
            model_name='documentfolderprivate',
            name='unique_subfolder_private',
        ),
        migrations.RemoveConstraint(
            model_name='documentfolderpublic',
            name='unique_root_folder_public',
        ),
        migrations.RemoveConstraint(
            model_name='documentfolderpublic',
            name='unique_subfolder_public',
        ),

        # ===== 2. 添加 unique_key 字段（先不加 unique，避免回填时撞唯一索引）=====
        migrations.AddField(
            model_name='documentfolderprivate',
            name='unique_key',
            field=models.CharField(
                db_index=True,
                editable=False,
                help_text='唯一标识键（MD5哈希，仅未删除记录参与唯一约束）',
                max_length=32,
                null=True,
                blank=True,
                verbose_name='唯一标识键',
            ),
        ),
        migrations.AddField(
            model_name='documentfolderpublic',
            name='unique_key',
            field=models.CharField(
                db_index=True,
                editable=False,
                help_text='唯一标识键（MD5哈希，仅未删除记录参与唯一约束）',
                max_length=32,
                null=True,
                blank=True,
                verbose_name='唯一标识键',
            ),
        ),

        # ===== 3. 回填 unique_key 数据（如有重复则 raise 中止迁移）=====
        migrations.RunPython(backfill_unique_key_private, reverse_backfill),
        migrations.RunPython(backfill_unique_key_public, reverse_backfill),

        # ===== 4. 回填无误后，添加 unique 约束 =====
        migrations.AlterField(
            model_name='documentfolderprivate',
            name='unique_key',
            field=models.CharField(
                db_index=True,
                editable=False,
                help_text='唯一标识键（MD5哈希，仅未删除记录参与唯一约束）',
                max_length=32,
                null=True,
                unique=True,
                blank=True,
                verbose_name='唯一标识键',
            ),
        ),
        migrations.AlterField(
            model_name='documentfolderpublic',
            name='unique_key',
            field=models.CharField(
                db_index=True,
                editable=False,
                help_text='唯一标识键（MD5哈希，仅未删除记录参与唯一约束）',
                max_length=32,
                null=True,
                unique=True,
                blank=True,
                verbose_name='唯一标识键',
            ),
        ),
    ]

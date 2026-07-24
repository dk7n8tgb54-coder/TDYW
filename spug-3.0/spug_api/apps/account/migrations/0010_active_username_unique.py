"""Enforce case-insensitive uniqueness for active usernames only.

MariaDB cannot express Django's conditional unique constraint as a partial
index.  A generated column maps deleted users to NULL (which a unique index may
contain more than once) and active users to their username.  The table's
existing collation keeps Admin/admin comparisons case-insensitive.
"""
from django.db import migrations
from django.db.models import Count


INDEX_NAME = 'uniq_users_active_username'
COLUMN_NAME = 'active_username'


def add_active_username_unique(apps, schema_editor):
    User = apps.get_model('account', 'User')
    database = schema_editor.connection.alias
    duplicates = (
        User.objects.using(database)
        .filter(deleted_by_id__isnull=True)
        .values('username')
        .annotate(row_count=Count('id'))
        .filter(row_count__gt=1)
        .count()
    )
    if duplicates:
        raise RuntimeError(
            'Cannot enforce active username uniqueness: '
            f'{duplicates} duplicate active username group(s) exist.'
        )

    vendor = schema_editor.connection.vendor
    table = schema_editor.quote_name('users')
    index = schema_editor.quote_name(INDEX_NAME)
    column = schema_editor.quote_name(COLUMN_NAME)
    username = schema_editor.quote_name('username')
    deleted_by_id = schema_editor.quote_name('deleted_by_id')
    with schema_editor.connection.cursor() as cursor:
        if vendor == 'mysql':
            cursor.execute(
                f'ALTER TABLE {table} ADD COLUMN {column} varchar(100) '
                f'GENERATED ALWAYS AS (IF({deleted_by_id} IS NULL, {username}, NULL)) STORED'
            )
            cursor.execute(f'CREATE UNIQUE INDEX {index} ON {table} ({column})')
        elif vendor == 'sqlite':
            cursor.execute(
                f'CREATE UNIQUE INDEX {index} ON {table} ({username}) '
                f'WHERE {deleted_by_id} IS NULL'
            )
        else:
            raise RuntimeError(f'Unsupported database vendor for active username index: {vendor}')


def remove_active_username_unique(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    table = schema_editor.quote_name('users')
    index = schema_editor.quote_name(INDEX_NAME)
    column = schema_editor.quote_name(COLUMN_NAME)
    with schema_editor.connection.cursor() as cursor:
        if vendor == 'mysql':
            cursor.execute(f'DROP INDEX {index} ON {table}')
            cursor.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
        elif vendor == 'sqlite':
            cursor.execute(f'DROP INDEX {index}')
        else:
            raise RuntimeError(f'Unsupported database vendor for active username index: {vendor}')


class Migration(migrations.Migration):
    dependencies = [
        ('account', '0009_alter_history_created_at_alter_role_created_at_and_more'),
    ]

    operations = [
        migrations.RunPython(add_active_username_unique, remove_active_username_unique),
    ]

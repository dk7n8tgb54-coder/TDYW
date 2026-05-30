# Generated manually to fix MySQL default value issue

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('account', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE roles MODIFY is_global_admin tinyint(1) NOT NULL DEFAULT 0;",
            reverse_sql="ALTER TABLE roles MODIFY is_global_admin tinyint(1) NOT NULL;"
        ),
    ]

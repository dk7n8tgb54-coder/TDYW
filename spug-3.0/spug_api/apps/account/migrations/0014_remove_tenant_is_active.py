from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0013_alter_user_access_token_alter_role_unique_together'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='tenant',
            name='is_active',
        ),
    ]

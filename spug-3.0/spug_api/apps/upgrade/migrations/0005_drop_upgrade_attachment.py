# Generated for dropping upgrade attachment table (migrated to evidence)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('upgrade', '0004_merge_plan'),
    ]

    operations = [
        migrations.DeleteModel(
            name='UpgradeAttachment',
        ),
    ]

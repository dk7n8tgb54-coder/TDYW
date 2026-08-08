from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0010_delete_notice'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Navigation',
        ),
    ]

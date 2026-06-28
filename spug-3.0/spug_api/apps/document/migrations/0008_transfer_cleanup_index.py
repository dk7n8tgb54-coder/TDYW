from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0007_document_list_indexes'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='documenttransfer',
            index=models.Index(
                fields=['status', 'updated_at'],
                name='transfer_status_updated_idx',
            ),
        ),
    ]

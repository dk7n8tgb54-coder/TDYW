# Station frequency approval: drop tenant-level uniqueness on doc_no,
# duplicates are allowed per business requirement.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('radio_license', '0013_alter_radiolicense_status_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='stationfrequencyapproval',
            name='uniq_sfa_tenant_doc_no',
        ),
    ]

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('institution', '0006_revision_open'),
    ]

    operations = [
        migrations.AddField(
            model_name='manualeditsession',
            name='final_callback_allowed',
            field=models.BooleanField(
                default=False, verbose_name='撤销后保留收尾回调'),
        ),
    ]

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""Remove the old radio license reminder history table.

Popup reminders are queried in real time, and user acknowledgements are stored
in LicenseReminderAck. The historical reminder log is no longer part of the
radio license module.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('radio_license', '0008_remove_radiolicenseattachment'),
    ]

    operations = [
        migrations.DeleteModel(
            name='RadioLicenseReminder',
        ),
    ]

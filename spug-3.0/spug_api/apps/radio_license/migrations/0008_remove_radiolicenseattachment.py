# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""删除 RadioLicenseAttachment 独立附件表

附件功能已迁移到通用附件表（tdyw_evidence_attachments），
通过 module='radio_license' / object_type='license' / object_id=<license_id> 关联。
开发阶段无真实附件数据，直接删除旧表。
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('radio_license', '0007_evidence_attachment_version'),
    ]

    operations = [
        migrations.DeleteModel(
            name='RadioLicenseAttachment',
        ),
    ]

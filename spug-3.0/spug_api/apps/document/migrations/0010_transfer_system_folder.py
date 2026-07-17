# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import migrations, models


NEW_CODE = 'party_building_documents'
LEGACY_CODE = 'industry_rules'


def mark_existing_party_building_document_transfers(apps, schema_editor):
    DocumentSystemFolder = apps.get_model('document', 'DocumentSystemFolder')
    DocumentFolderPublic = apps.get_model('document', 'DocumentFolderPublic')
    DocumentTransfer = apps.get_model('document', 'DocumentTransfer')

    binding = (
        DocumentSystemFolder.objects
        .filter(code__in=[NEW_CODE, LEGACY_CODE])
        .order_by('-code')
        .first()
    )
    if not binding:
        return

    root_id = binding.folder_id
    folder_ids = {root_id}
    queue = [root_id]
    while queue:
        children = list(
            DocumentFolderPublic.objects
            .filter(parent_id__in=queue)
            .values_list('id', flat=True)
        )
        queue = [folder_id for folder_id in children if folder_id not in folder_ids]
        folder_ids.update(queue)

    if folder_ids:
        DocumentTransfer.objects.filter(
            is_public=True,
            folder_id__in=folder_ids,
            system_folder='',
        ).update(system_folder=NEW_CODE)


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0009_document_system_folder'),
    ]

    operations = [
        migrations.AddField(
            model_name='documenttransfer',
            name='system_folder',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='系统目录编码；普通文档为空，党建文档为 party_building_documents',
                max_length=64,
                verbose_name='系统目录编码',
            ),
        ),
        migrations.RunPython(
            mark_existing_party_building_document_transfers,
            migrations.RunPython.noop,
        ),
        migrations.AddIndex(
            model_name='documenttransfer',
            index=models.Index(
                fields=['user', 'is_public', 'system_folder'],
                name='idx_transfer_user_scope',
            ),
        ),
    ]

# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""Add unique constraint on DocumentSystemFolder.folder.

Prevents the same DocumentFolderPublic root from being bound by multiple
system-folder modules. If duplicate bindings already exist, this migration
fails explicitly rather than silently dropping data.
"""
from django.db import migrations, models
import django.db.models.deletion


def _check_duplicate_bindings(apps, schema_editor):
    """Pre-flight check: fail explicitly if duplicate folder bindings exist."""
    DocumentSystemFolder = apps.get_model('document', 'DocumentSystemFolder')
    dupes = (
        DocumentSystemFolder.objects
        .values('folder')
        .annotate(cnt=models.Count('id'))
        .filter(cnt__gt=1)
    )
    if dupes.exists():
        dupe_list = list(dupes.values_list('folder', 'cnt'))
        raise RuntimeError(
            f'Cannot apply unique constraint: duplicate DocumentSystemFolder.folder '
            f'bindings found: {dupe_list}. Please resolve manually before migrating.'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0011_rename_party_building_documents'),
    ]

    operations = [
        migrations.RunPython(_check_duplicate_bindings, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='documentsystemfolder',
            name='folder',
            field=models.ForeignKey(
                help_text='绑定的 DocumentFolderPublic 根目录（唯一，同一目录不可绑定多个系统模块）',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='system_bindings',
                to='document.documentfolderpublic',
                unique=True,
                verbose_name='绑定的公共目录',
            ),
        ),
    ]

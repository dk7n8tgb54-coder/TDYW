# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import json
import os
import shutil

from django.conf import settings
from django.db import migrations


NEW_CODE = 'party_building_documents'
LEGACY_CODE = 'industry_rules'
NEW_PAGE_KEY = 'party_building_document'
LEGACY_PAGE_KEY = 'industry_rule'
NEW_NAME = '党建文档'
LEGACY_NAMES = {'党务档案', '行业规章'}


def _rename_system_folder_binding(apps):
    DocumentSystemFolder = apps.get_model('document', 'DocumentSystemFolder')
    DocumentFolderPublic = apps.get_model('document', 'DocumentFolderPublic')

    legacy = DocumentSystemFolder.objects.filter(code=LEGACY_CODE).first()
    current = DocumentSystemFolder.objects.filter(code=NEW_CODE).first()

    binding = current or legacy
    if legacy and current and legacy.pk != current.pk:
        current.folder_id = legacy.folder_id
        current.is_public = True
        current.protected = True
        current.name = NEW_NAME
        current.description = '党建文档系统业务根目录，受保护不可删除/重命名/移动'
        current.save(update_fields=['folder', 'is_public', 'protected', 'name', 'description'])
        legacy.delete()
        binding = current
    elif legacy:
        legacy.code = NEW_CODE
        legacy.name = NEW_NAME
        legacy.is_public = True
        legacy.protected = True
        legacy.description = '党建文档系统业务根目录，受保护不可删除/重命名/移动'
        legacy.save(update_fields=['code', 'name', 'is_public', 'protected', 'description'])
        binding = legacy
    elif current:
        current.name = NEW_NAME
        current.is_public = True
        current.protected = True
        current.description = '党建文档系统业务根目录，受保护不可删除/重命名/移动'
        current.save(update_fields=['name', 'is_public', 'protected', 'description'])

    if binding and binding.folder_id:
        DocumentFolderPublic._base_manager.filter(pk=binding.folder_id).update(name=NEW_NAME)

    DocumentFolderPublic._base_manager.filter(
        parent__isnull=True,
        name__in=LEGACY_NAMES,
    ).update(name=NEW_NAME)


def _rename_transfer_scope(apps):
    DocumentTransfer = apps.get_model('document', 'DocumentTransfer')
    DocumentTransfer.objects.filter(system_folder=LEGACY_CODE).update(system_folder=NEW_CODE)


def _replace_path_value(value):
    if not value:
        return value
    return (
        value
        .replace(f'/documents/{LEGACY_CODE}/', f'/documents/{NEW_CODE}/')
        .replace(f'\\documents\\{LEGACY_CODE}\\', f'\\documents\\{NEW_CODE}\\')
        .replace(f'/documents/{LEGACY_CODE}', f'/documents/{NEW_CODE}')
        .replace(f'\\documents\\{LEGACY_CODE}', f'\\documents\\{NEW_CODE}')
    )


def _rename_stored_file_paths(apps):
    DocumentFilePublic = apps.get_model('document', 'DocumentFilePublic')
    DocumentTransfer = apps.get_model('document', 'DocumentTransfer')

    for model, fields in (
        (DocumentFilePublic, ('file_path', 'thumbnail_path')),
        (DocumentTransfer, ('file_path',)),
    ):
        queryset = model._base_manager.all()
        for obj in queryset.iterator():
            changed = []
            for field in fields:
                old_value = getattr(obj, field, None)
                new_value = _replace_path_value(old_value)
                if new_value != old_value:
                    setattr(obj, field, new_value)
                    changed.append(field)
            if changed:
                obj.save(update_fields=changed)


def _rename_physical_storage_folder():
    storage_root = os.path.join(settings.BASE_DIR, 'storage', 'documents')
    old_path = os.path.join(storage_root, LEGACY_CODE)
    new_path = os.path.join(storage_root, NEW_CODE)

    if not os.path.exists(old_path):
        return
    if not os.path.exists(new_path):
        os.rename(old_path, new_path)
        return

    for name in os.listdir(old_path):
        source = os.path.join(old_path, name)
        target = os.path.join(new_path, name)
        if os.path.exists(target):
            continue
        shutil.move(source, target)

    try:
        os.rmdir(old_path)
    except OSError:
        pass


def _rename_role_permissions(apps):
    Role = apps.get_model('account', 'Role')
    for role in Role.objects.exclude(page_perms__isnull=True).iterator():
        try:
            perms = json.loads(role.page_perms or '{}')
        except (TypeError, ValueError):
            continue

        document_perms = perms.get('document')
        if not isinstance(document_perms, dict) or LEGACY_PAGE_KEY not in document_perms:
            continue

        legacy_perms = document_perms.pop(LEGACY_PAGE_KEY) or []
        current_perms = document_perms.get(NEW_PAGE_KEY) or []
        merged = sorted(set(current_perms) | set(legacy_perms))
        document_perms[NEW_PAGE_KEY] = merged
        role.page_perms = json.dumps(perms, ensure_ascii=False)
        role.save(update_fields=['page_perms'])


def rename_party_building_documents(apps, schema_editor):
    _rename_system_folder_binding(apps)
    _rename_transfer_scope(apps)
    _rename_stored_file_paths(apps)
    _rename_physical_storage_folder()
    _rename_role_permissions(apps)


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0006_role_tenant_system'),
        ('document', '0010_transfer_system_folder'),
    ]

    operations = [
        migrations.RunPython(
            rename_party_building_documents,
            migrations.RunPython.noop,
        ),
    ]

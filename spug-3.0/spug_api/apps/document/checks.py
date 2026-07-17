# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""System checks for DocumentSystemFolder binding integrity.

Run via ``python manage.py check``. Reports (not enforces) integrity issues:
- canonical/legacy code conflicts
- binding folder missing or soft-deleted
- binding not protected
- duplicate folder bindings (post unique-constraint this is impossible, but
  the check remains as a safety net for pre-migration states)
"""
from django.core.checks import register, Warning as DjangoWarning


@register()
def check_system_folder_bindings(app_configs, **kwargs):
    errors = []
    try:
        from .models import DocumentSystemFolder
        from .services.system_folder_service import (
            PARTY_BUILDING_DOCUMENTS_CODE,
            LEGACY_PARTY_BUILDING_DOCUMENTS_CODE,
            SYSTEM_FOLDER_CODES,
        )

        # 1. legacy code should not coexist with canonical code pointing to a
        #    different folder (init command migrates legacy -> canonical).
        legacy = DocumentSystemFolder.objects.filter(
            code=LEGACY_PARTY_BUILDING_DOCUMENTS_CODE
        ).first()
        canonical = DocumentSystemFolder.objects.filter(
            code=PARTY_BUILDING_DOCUMENTS_CODE
        ).first()
        if legacy and canonical and legacy.folder_id != canonical.folder_id:
            errors.append(DjangoWarning(
                f'Legacy code {LEGACY_PARTY_BUILDING_DOCUMENTS_CODE} and canonical '
                f'{PARTY_BUILDING_DOCUMENTS_CODE} bind different folders '
                f'({legacy.folder_id} vs {canonical.folder_id}). '
                f'Run init_document_system_folders to reconcile.',
                id='document.W001',
            ))

        # 2. every binding must have a non-deleted protected folder.
        for sf in DocumentSystemFolder.objects.select_related('folder'):
            if sf.folder is None:
                errors.append(DjangoWarning(
                    f'DocumentSystemFolder({sf.code}) has no bound folder.',
                    id='document.W002',
                ))
                continue
            if getattr(sf.folder, 'is_deleted', False):
                errors.append(DjangoWarning(
                    f'DocumentSystemFolder({sf.code}) bound folder '
                    f'{sf.folder_id} is soft-deleted.',
                    id='document.W003',
                ))
            if not sf.protected:
                errors.append(DjangoWarning(
                    f'DocumentSystemFolder({sf.code}) protected=False; '
                    f'root protection disabled.',
                    id='document.W004',
                ))

        # 3. unsupported codes
        for sf in DocumentSystemFolder.objects.exclude(code__in=SYSTEM_FOLDER_CODES):
            errors.append(DjangoWarning(
                f'DocumentSystemFolder has unsupported code {sf.code!r}.',
                id='document.W005',
            ))

    except Exception:
        # Avoid breaking ``check`` during initial migrations when the table
        # does not yet exist.
        pass

    return errors

#!/usr/bin/env python3
"""Read-only audit for the pending data-integrity migrations.

Usage (from the repository root, inside the application environment):
    python3 database_maintenance/audit_integrity_migrations.py

Docker Compose / WSL example (does not apply migrations):
    cd docker
    docker compose run --rm --no-deps \
      -v /mnt/e/TDYW/spug-3.0:/workspace -w /workspace/spug_api \
      --entrypoint python3 tdyw \
      /workspace/database_maintenance/audit_integrity_migrations.py

The script performs SELECT queries only.  It exits nonzero when historical
rows would violate a pending constraint; it never repairs or deletes data.
"""
import importlib
import os
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPUG_API_ROOT = REPOSITORY_ROOT / 'spug_api'
sys.path.insert(0, str(SPUG_API_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.models import Count  # noqa: E402


AUDITS = (
    ('checksheet', 'apps.checksheet.migrations.0005_checksheetdailysummary_cs_summary_month_valid_and_more',
     'audit_checksheet_constraints'),
    ('contract agreement', 'apps.contract_agreement.migrations.0005_alter_contractagreement_status_and_more',
     'audit_contract_constraints'),
    ('department duty log', 'apps.department_duty_log.migrations.0005_departmentdutylog_duty_log_status_valid_and_more',
     'audit_duty_log_constraints'),
    ('device', 'apps.device.migrations.0009_deviceevent_device_event_type_valid_and_more',
     'audit_device_constraints'),
    ('document transfer', 'apps.document.migrations.0015_documenttransfer_doc_transfer_type_valid_and_more',
     'audit_document_transfer_constraints'),
    ('interference', 'apps.interference.migrations.0006_interference_interference_status_valid_and_more',
     'audit_interference_constraints'),
    ('radio license', 'apps.radio_license.migrations.0013_alter_radiolicense_status_and_more',
     'audit_radio_license_constraints'),
    ('run log', 'apps.runlog.migrations.0011_runlog_runlog_severity_valid_and_more',
     'audit_runlog_constraints'),
)


class ReadOnlySchemaEditor:
    """Minimal schema-editor interface required by the audit functions."""

    def __init__(self, database_connection):
        self.connection = database_connection


def audit_active_usernames():
    User = apps.get_model('account', 'User')
    duplicate_groups = (
        User.objects.using(connection.alias)
        .filter(deleted_by_id__isnull=True)
        .values('username')
        .annotate(row_count=Count('id'))
        .filter(row_count__gt=1)
        .count()
    )
    if duplicate_groups:
        raise RuntimeError(
            f'active username uniqueness failed: duplicate groups={duplicate_groups}'
        )


def main():
    failures = []
    checks = [('active usernames', audit_active_usernames)]
    schema_editor = ReadOnlySchemaEditor(connection)
    for label, module_name, function_name in AUDITS:
        audit = getattr(importlib.import_module(module_name), function_name)
        checks.append((label, lambda audit=audit: audit(apps, schema_editor)))

    for label, audit in checks:
        try:
            audit()
        except Exception as exc:  # Each audit must run so the report is complete.
            failures.append((label, str(exc)))
            print(f'FAIL {label}: {exc}')
        else:
            print(f'PASS {label}')

    if failures:
        print(f'Integrity audit failed: {len(failures)} check(s) require attention.')
        return 1
    print('Integrity audit passed: pending constraints can be applied to current data.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

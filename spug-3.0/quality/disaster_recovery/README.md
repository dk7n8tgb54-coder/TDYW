# Disaster Recovery Framework

## Purpose

This directory contains a **non-destructive** disaster recovery (DR) framework for the Spug project.
It provides tooling for backup inspection, restore drill orchestration, failure simulation,
post-restore validation, and RPO/RTO baseline tracking.

## Critical Safety Constraints

> **READ THIS BEFORE RUNNING ANYTHING.**

1. **`tdyw-test` connects to the DEV database (`spug`).** It is NOT a dedicated test database.
   Therefore, **no restore drills or destructive operations may target `tdyw-test` or the `spug` database.**
2. All restore/failure drill runners import `environment_guard` and will **refuse to execute**
   unless every safety check passes (fail-closed design).
3. Only `inspect_backups.py` may run without `ALLOW_RESTORE_DRILL=true` — it performs static
   analysis only.
4. Restore drills require a dedicated temp database (name containing `test`/`perf`/`drill`),
   a dedicated temp container (not `tdyw` or `tdyw-test`), and temp file directories.
5. Failure drills use mocks/proxies — they never disrupt real services.

## Directory Structure

```
quality/disaster_recovery/
  README.md                          This file
  disaster-recovery.example.env      Template env file (copy, fill in, chmod 600)
  backup_inventory.yml               Structured catalog of all backup objects
  recovery_policy.yml                Recovery policy definitions per component
  helpers/
    __init__.py
    environment_guard.py             Fail-closed environment protection (CRITICAL)
    manifest.py                      Backup manifest parser & validator
    timing.py                        RPO/RTO timing utilities
    redaction.py                     Secret redaction for logs
  runners/
    inspect_backups.py               Static analysis of existing backup setup
    run_restore_drill.py             Restore drill runner (guarded)
    run_failure_drill.py             Failure injection runner (non-destructive)
  validators/
    database_validator.py            Post-restore database validation
    file_validator.py                Post-restore file validation
    checksum_validator.py            SHA256 checksum verification
    application_validator.py         Application-level validation
    security_validator.py            Security validation
  scenarios/
    database_restore.yml             Database restore scenario
    file_restore.yml                 File restore scenario
    redis_loss.yml                   Redis loss scenario
    celery_interruption.yml          Celery interruption scenario
    kkfileview_unavailable.yml       kkFileView unavailable scenario
  baselines/
    rpo_rto_targets.yml              RPO/RTO target definitions
    README.md                        RPO/RTO baseline process
```

## How to Use

### 1. Inspect Existing Backups (read-only, safe anywhere)

```bash
python quality/disaster_recovery/runners/inspect_backups.py \
    --project-root /path/to/spug-3.0
```

### 2. Run a Restore Drill (requires isolated environment)

```bash
# Copy the example env, fill in values, chmod 600
cp quality/disaster_recovery/disaster-recovery.example.env .dr.env
# Edit .dr.env: set ALLOW_RESTORE_DRILL=true, temp DB, temp container, etc.

python quality/disaster_recovery/runners/run_restore_drill.py \
    --env-file .dr.env \
    --archive tdyw-20260808-030000
```

The environment guard will refuse if:
- `ALLOW_RESTORE_DRILL` is not `true`
- Database name is `spug` (dev/prod)
- Container is `tdyw` or `tdyw-test` (production or dev)
- File paths are not under a temp directory

### 3. Run a Failure Drill (non-destructive, uses mocks)

```bash
python quality/disaster_recovery/runners/run_failure_drill.py \
    --env-file .dr.env \
    --scenario redis_loss
```

### 4. Validate After Restore

```bash
python quality/disaster_recovery/validators/database_validator.py \
    --env-file .dr.env

python quality/disaster_recovery/validators/file_validator.py \
    --env-file .dr.env

python quality/disaster_recovery/validators/application_validator.py \
    --env-file .dr.env

python quality/disaster_recovery/validators/security_validator.py \
    --env-file .dr.env
```

## Existing Backup Infrastructure

The project has two backup systems:

### A. backup_set (tar-based, schema 5)

- **Create**: `backups/backup_set_create.sh` — full backup set (DB dump + documents/media archives + manifests + SHA256SUMS)
- **Restore**: `backups/backup_set_restore.sh` — restore from a backup set directory
- **Config**: `backups/tdyw_backup.cnf` (MariaDB client credentials, mode 0600)
- **Cron**: `backups/tdyw-backup.cron.example`

### B. BorgBackup (deduplicating, encrypted)

- **Create**: `borgbackup/borg_backup_set_create.sh` — app freeze → mariadb-dump → binlog archive → borg create (DB + documents + media + manifest + binlog)
- **Restore**: `borgbackup/borg_backup_set_restore.sh` — three modes: verify-only, drill (isolated), production
- **Config**: `borgbackup/borg.env` (BORG_REPO, BORG_PASSPHRASE, mode 0600)
- **Pruning**: GFS (keep 2 daily, 7 daily, 4 weekly, 6 monthly)

### Backup Contents

Each backup contains:
- `database.sql.gz` — MariaDB logical full dump (--single-transaction)
- `documents/` — document file storage volume
- `media/` — media file storage volume
- `manifest.json` — metadata (DB name, version, git commit, volume paths, timestamps, binlog position)
- `SHA256SUMS` (backup_set) or borg-internal integrity (borg)
- `binlog/` (borg only) — binary log files for PITR

## Design Principles

1. **Fail-closed**: When in doubt, refuse to run.
2. **No secrets in code**: All credentials come from env files or cnf files (mode 0600).
3. **Redaction everywhere**: All logs are passed through `redaction.py` before output.
4. **Incremental adoption**: Start with inspect_backups, add drills later.
5. **YAGNI**: Only simulate failures that are realistic for this deployment.

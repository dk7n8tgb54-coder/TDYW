# RPO/RTO Baseline Process

## What are RPO and RTO?

- **RPO (Recovery Point Objective)**: The maximum acceptable amount of data loss,
  measured in time. "How much data can we afford to lose?" For example, if backups
  run daily at 3 AM and a failure occurs at 2:55 AM, the RPO is ~24 hours.

- **RTO (Recovery Time Objective)**: The maximum acceptable downtime to recover
  from a failure. "How long can we be down?" This includes detection time,
  restore time, and validation time.

## Current Baselines

All current baselines are in `rpo_rto_targets.yml`. As of 2026-08-08, all values
are **estimated** (no drills have been run yet).

| Component | RPO | RTO | Status |
|---|---|---|---|
| Database | 24h | 4h | estimated |
| File Storage | 24h | 4h | estimated |
| Evidence Attachments | 24h | 8h | estimated |
| Regulation Storage | 24h | 8h | estimated |
| Redis | 0 (ephemeral) | 15m | estimated |
| Celery Queue | 0 (disposable) | 15m | estimated |
| System Config | 0 (git) | 1h | estimated |
| Audit Logs | 24h | 4h | estimated |

## How to Update Baselines

### Step 1: Run a Restore Drill

```bash
# Set up isolated environment (temp DB, temp container)
# Configure .dr.env with ALLOW_RESTORE_DRILL=true

python quality/disaster_recovery/runners/run_restore_drill.py \
    --env-file .dr.env \
    --archive tdyw-20260808-030000 \
    --output /tmp/dr-logs/restore_drill_report.json
```

### Step 2: Extract Timing Data

The drill report contains a `timing` section with:
- `total_duration_seconds`: Overall RTO measurement
- `rpo_measured_seconds`: Data loss window (backup timestamp vs drill time)
- Per-phase durations (database restore, file restore, validation)

### Step 3: Update rpo_rto_targets.yml

For each component measured:
1. Change `status` from `estimated` to `measured`
2. Update `current_rpo` and `current_rto` with measured values
3. Add an entry to `measurement_history` with date and values

### Step 4: Compare Against Targets

If `measured > target`:
- Investigate root cause (slow restore, large dump, etc.)
- Consider improving backup frequency or restore process
- Document the gap and remediation plan

## Key Considerations

### RPO Reduction Options

1. **Increase backup frequency**: Currently daily. Could go to twice-daily for
   reduced RPO (12 hours). Trade-off: more storage, more I/O.
2. **Binlog-based PITR**: BorgBackup archives binlog files. This enables
   point-in-time recovery to any timestamp, effectively reducing RPO to near-zero.
   Requires: binlog enabled, continuous binlog archiving.
3. **Replication**: Set up a replica database. RPO approaches zero (async replication
   lag). Trade-off: infrastructure complexity.

### RTO Reduction Options

1. **Parallel restore**: Restore database and files in parallel (already designed
   for in the drill runner).
2. **Faster storage**: NVMe/SSD for backup storage reduces I/O-bound restore time.
3. **Pre-staged restore**: Keep a warm standby database that's continuously restored.
4. **Selective restore**: For partial failures, restore only affected tables.

### Measurement Cadence

- **Initial baseline**: Run a full restore drill once to establish baseline.
- **Quarterly**: Re-run drills to verify RPO/RTO are still within targets.
- **After infrastructure changes**: Any change to backup system, storage, or
  database size should trigger a re-measurement.

## Gaps and Risks

1. **Env files not in automated backup**: BORG_PASSPHRASE, MYSQL_ROOT_PASSWORD,
   SECRET_KEY are stored in files (mode 0600) but not in the automated backup.
   If these are lost, recovery is blocked. **Mitigation**: Store copies in a
   password manager or physical safe.

2. **No offsite backup**: All backups are on the same host. If the host fails,
   both data and backups are lost. **Mitigation**: Configure BorgBackup to
   push to a remote repository.

3. **Single operator assumption**: RTO estimates assume a single operator who
   knows the system. If that person is unavailable, RTO will be longer.
   **Mitigation**: Document recovery procedures thoroughly (this framework).

4. **No restore drill has been run**: All values are estimates. Actual RTO
   may be significantly different. **Mitigation**: Run a drill and update
   baselines with measured values.

# Performance Baselines

## Overview

This directory contains approved performance baselines for the Spug platform.
Baselines are established by running performance tests in a controlled test
environment and recording the results.

## Baseline Approval Process

### 1. Run Tests

Run performance tests in a **dedicated test environment** (not dev/prod):

```bash
# Smoke test
locust -f locustfiles/smoke_load.py --headless -u 2 -r 1 --run-time 30s

# Normal load
locust -f locustfiles/read_workflows.py --headless -u 15 -r 2 --run-time 5m
```

### 2. Collect Results

The test output includes a metrics summary printed by `helpers/metrics.py`.
Record:
- Test date
- Environment details (CPU, RAM, DB version)
- User count and duration
- Per-endpoint P50/P90/P95/P99, RPS, error rate

### 3. Review Against Thresholds

Compare results against `thresholds.yml`:
- **baseline** - Current known performance
- **target** - Desired performance
- **blocking** - Must not exceed for release

### 4. Approve and Record

If results are acceptable:
1. Copy metrics into `approved_thresholds.yml`
2. Include date, environment, and test parameters
3. Commit with message: "perf: approve baseline for [scenario]"

### 5. Regression Detection

Future test runs compare against approved baselines:
- P95 regression > 20% = warning
- P95 regression > 50% = blocking
- Error rate increase > 2x = blocking

## Rules

1. **Never** fill in baselines from dev/production environments.
2. **Never** guess or estimate baseline values.
3. Baselines must be from a **controlled test environment** with known specs.
4. Re-establish baselines after major infrastructure changes.
5. Document any anomalies during baseline measurement.

## File Structure

```
baselines/
├── README.md                  # This file
└── approved_thresholds.yml    # Approved baselines (empty until tested)
```

## Environment Requirements for Baseline

- Dedicated test server (not shared with dev/prod)
- Test database (name contains test/perf/drill)
- Known hardware specs (CPU cores, RAM, disk type)
- MariaDB 10.8 (matching production)
- Redis configured (matching production)
- No other load during testing

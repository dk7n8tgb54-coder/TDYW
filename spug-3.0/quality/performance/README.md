# Performance Testing Framework

## Overview

This framework provides repeatable performance baseline testing for the Spug platform.

**CRITICAL**: The current test environment (`tdyw-test`) connects to the `spug` DEV database.
Therefore, only read-only tests and static analysis are permitted. No write load, no restore drills.

## Safety Requirements

All scripts enforce fail-closed environment protection:

| Level | Allowed Operations | Required Environment Variables |
|-------|-------------------|-------------------------------|
| STATIC_ONLY | File inspection, single GET probes | None |
| READ_ONLY | Read-only load tests | `BASE_URL`, `ALLOW_PERFORMANCE_TEST=true` |
| WRITE_ALLOWED | Write load tests, file upload tests | Above + `ALLOW_WRITE_LOAD=true`, `DB_NAME=test_*`, `TARGET_CONTAINER=test-*` |

### Forbidden Configurations

- `DB_NAME=spug` (dev database)
- `TARGET_CONTAINER=tdyw` (production container)
- `BASE_URL` pointing to production host

## Directory Structure

```
quality/performance/
├── README.md                 # This file
├── performance.example.env   # Environment template
├── thresholds.yml            # Threshold definitions
├── datasets.yml              # Test data set definitions
├── helpers/                  # Shared utilities
│   ├── safety.py             # Environment safety guard (fail-closed)
│   ├── auth.py               # Token-pool authentication
│   ├── test_data.py          # Test data generation (PERF_ prefix)
│   ├── metrics.py            # Metrics collection (P50/P95/P99)
│   └── cleanup.py            # Test data cleanup
├── locustfiles/              # Locust test scripts
│   ├── smoke_load.py         # Smoke test (1-3 users, 30s)
│   ├── read_workflows.py     # Read-only across all modules
│   ├── write_workflows.py    # Write tests (requires write access)
│   ├── file_workflows.py     # File upload/download tests
│   └── mixed_workflows.py    # Mixed read/write/file simulation
├── scenarios/                # Scenario configurations
│   ├── smoke.yml             # Smoke validation
│   ├── normal_load.yml       # Normal daily usage
│   ├── peak_load.yml         # Peak capacity
│   └── soak.yml              # Long-duration stability
├── tests/                    # Framework self-tests
│   ├── test_locustfiles.py
│   ├── test_scenarios.py
│   ├── test_thresholds.py
│   └── test_safety_guards.py
└── baselines/                # Approved baselines (filled after testing)
    ├── approved_thresholds.yml
    └── README.md
```

## How to Run

### 1. Set up environment

```bash
cp quality/performance/performance.example.env .env
# Edit .env: set BASE_URL, ALLOW_PERFORMANCE_TEST=true
```

### 2. Run smoke test

```bash
python -m locust -f quality/performance/locustfiles/smoke_load.py \
    -H http://localhost --headless -u 2 -r 1 -t 30s
```

### 3. Run read-only workflow

```bash
python -m locust -f quality/performance/locustfiles/read_workflows.py \
    -H http://localhost --headless -u 5 -r 1 -t 2m
```

### 4. Run mixed workflow (requires write access)

```bash
ALLOW_WRITE_LOAD=true DB_NAME=test_spug \
python -m locust -f quality/performance/locustfiles/mixed_workflows.py \
    -H http://localhost --headless -u 10 -r 2 -t 5m
```

## Metrics Recorded

- Request count, success, failure, error rate
- RPS (requests per second)
- Average, P50, P90, P95, P99, Max response time
- DB connections, Redis connections, Celery queue depth
- Container CPU, memory, disk usage

## Current Status

- **Test environment**: `tdyw-test` connects to `spug` (DEV database)
- **Allowed operations**: Read-only load tests only
- **Write tests**: NOT EXECUTED (dev database)
- **Restore drills**: NOT EXECUTED (no isolated test database)
- **Peak/Soak tests**: NOT EXECUTED (dev database, potential impact)

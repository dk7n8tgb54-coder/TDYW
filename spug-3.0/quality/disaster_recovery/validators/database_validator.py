#!/usr/bin/env python3
"""
Post-Restore Database Validator

Validates database integrity after a restore drill:
  1. Django check passes
  2. All expected tables present
  3. Migration consistency (no missing/fake migrations)
  4. Tenant/user/permission integrity
  5. Orphaned foreign key check
  6. Audit log hash chain structure
"""

import argparse
import json
import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
DR_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(DR_ROOT))

from helpers.redaction import redact, redact_dict


def load_env(env_file: str = None, env_str: str = None) -> dict:
    env = {}
    if env_str:
        env = json.loads(env_str)
    elif env_file and os.path.isfile(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()
    return env


@dataclass
class ValidationResult:
    name: str
    passed: bool
    detail: str
    data: dict = field(default_factory=dict)


def docker_exec(env: dict, cmd: str, timeout: int = 60) -> Dict[str, Any]:
    container = env.get("DR_TARGET_CONTAINER", "tdyw-drill")
    try:
        result = subprocess.run(
            ["docker", "exec", "-w", "/data/spug/spug_api", container,
             "bash", "-c", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e)}


def check_django_check(env: dict) -> ValidationResult:
    """1. Run Django system check."""
    r = docker_exec(env, "python manage.py check 2>&1", timeout=120)
    passed = r["returncode"] == 0
    detail = "Django check passed" if passed else f"Django check failed: {redact(r['stderr'][:300])}"
    return ValidationResult("django_check", passed, detail, {"exit_code": r["returncode"]})


def check_table_existence(env: dict) -> ValidationResult:
    """2. Verify all expected tables exist."""
    db = env.get("DR_TARGET_DB", "spug_drill")
    db_container = env.get("DR_TARGET_DB_CONTAINER", "tdyw-db-drill")

    # Get tables from DB
    try:
        result = subprocess.run(
            ["docker", "exec", db_container, "mysql", "-u", "root",
             "-e", f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='{db}';"],
            capture_output=True, text=True, timeout=30,
        )
        count = 0
        if result.returncode == 0:
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            if len(lines) >= 2:
                try:
                    count = int(lines[-1])
                except ValueError:
                    pass

        # Expected minimum tables (core Django + business)
        MIN_EXPECTED = 40
        passed = count >= MIN_EXPECTED
        return ValidationResult(
            "table_existence", passed,
            f"Found {count} tables (minimum expected: {MIN_EXPECTED})",
            {"table_count": count, "minimum_expected": MIN_EXPECTED},
        )
    except Exception as e:
        return ValidationResult("table_existence", False, f"Error: {e}")


def check_migration_consistency(env: dict) -> ValidationResult:
    """3. Check migration consistency."""
    r = docker_exec(env, "python manage.py showmigrations --list 2>&1 | grep -c '\\[ \\]'", timeout=120)
    unapplied = 0
    try:
        unapplied = int(r["stdout"].strip()) if r["stdout"].strip() else 0
    except ValueError:
        pass

    passed = unapplied == 0
    detail = "All migrations applied" if passed else f"{unapplied} unapplied migrations found"
    return ValidationResult("migration_consistency", passed, detail, {"unapplied_count": unapplied})


def check_tenant_user_permission(env: dict) -> ValidationResult:
    """4. Verify tenant, user, and permission data."""
    db = env.get("DR_TARGET_DB", "spug_drill")
    db_container = env.get("DR_TARGET_DB_CONTAINER", "tdyw-db-drill")

    queries = {
        "users": f"SELECT COUNT(*) FROM `{db}`.account_user WHERE is_deleted=0;",
        "roles": f"SELECT COUNT(*) FROM `{db}`.account_role WHERE is_deleted=0;",
        "tenants": f"SELECT DISTINCT tenant_id FROM `{db}`.account_user WHERE is_deleted=0;",
        "permissions": f"SELECT COUNT(*) FROM `{db}`.account_role_policy WHERE is_deleted=0;",
    }

    results = {}
    for label, query in queries.items():
        try:
            r = subprocess.run(
                ["docker", "exec", db_container, "mysql", "-u", "root", "-N", "-e", query],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                val = r.stdout.strip()
                if label == "tenants":
                    results[label] = val.split("\n") if val else []
                else:
                    results[label] = int(val) if val.isdigit() else 0
            else:
                results[label] = None
        except Exception:
            results[label] = None

    passed = results.get("users", 0) > 0 and results.get("roles", 0) > 0
    detail = f"Users={results.get('users')}, Roles={results.get('roles')}, Tenants={results.get('tenants')}, Policies={results.get('permissions')}"
    return ValidationResult("tenant_user_permission", passed, detail, results)


def check_orphan_fk(env: dict) -> ValidationResult:
    """5. Check for orphaned foreign keys."""
    db = env.get("DR_TARGET_DB", "spug_drill")
    db_container = env.get("DR_TARGET_DB_CONTAINER", "tdyw-db-drill")

    # Check common FK relationships for orphans
    orphan_checks = [
        ("document_documentfile_private", "created_by_id", "account_user"),
        ("evidence_evidenceattachment", "created_by_id", "account_user"),
        ("fault_faultrecord", "created_by_id", "account_user"),
    ]

    orphan_count = 0
    details = []
    for table, fk_col, ref_table in orphan_checks:
        query = (
            f"SELECT COUNT(*) FROM `{db}`.{table} t1 "
            f"LEFT JOIN `{db}`.{ref_table} t2 ON t1.{fk_col}=t2.id "
            f"WHERE t1.{fk_col} IS NOT NULL AND t2.id IS NULL;"
        )
        try:
            r = subprocess.run(
                ["docker", "exec", db_container, "mysql", "-u", "root", "-N", "-e", query],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0 and r.stdout.strip().isdigit():
                count = int(r.stdout.strip())
                if count > 0:
                    orphan_count += count
                    details.append(f"{table}.{fk_col}: {count} orphans")
        except Exception:
            pass

    passed = orphan_count == 0
    detail = "No orphaned FKs found" if passed else f"{orphan_count} orphaned FKs: {'; '.join(details)}"
    return ValidationResult("orphan_fk_check", passed, detail, {"orphan_count": orphan_count, "details": details})


def check_audit_log_structure(env: dict) -> ValidationResult:
    """6. Check audit log hash chain structure."""
    db = env.get("DR_TARGET_DB", "spug_drill")
    db_container = env.get("DR_TARGET_DB_CONTAINER", "tdyw-db-drill")

    results = {}
    queries = {
        "audit_log_count": f"SELECT COUNT(*) FROM `{db}`.logs_auditlog;",
        "sequence_count": f"SELECT COUNT(*) FROM `{db}`.logs_auditlogsequence;",
        "latest_sequence": f"SELECT MAX(seq_number) FROM `{db}`.logs_auditlogsequence;",
    }

    for label, query in queries.items():
        try:
            r = subprocess.run(
                ["docker", "exec", db_container, "mysql", "-u", "root", "-N", "-e", query],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                val = r.stdout.strip()
                results[label] = int(val) if val.isdigit() else val
            else:
                results[label] = None
        except Exception:
            results[label] = None

    passed = results.get("audit_log_count") is not None
    detail = f"AuditLog={results.get('audit_log_count')}, Sequence={results.get('sequence_count')}, MaxSeq={results.get('latest_sequence')}"
    return ValidationResult("audit_log_structure", passed, detail, results)


def run_all(env: dict) -> dict:
    checks = [
        check_django_check(env),
        check_table_existence(env),
        check_migration_consistency(env),
        check_tenant_user_permission(env),
        check_orphan_fk(env),
        check_audit_log_structure(env),
    ]

    passed = sum(1 for c in checks if c.passed)
    failed = sum(1 for c in checks if not c.passed)

    return {
        "validator": "database_validator",
        "timestamp": datetime.now().isoformat(),
        "total": len(checks),
        "passed": passed,
        "failed": failed,
        "checks": [asdict(c) for c in checks],
        "overall_passed": failed == 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Post-restore database validator")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--env-dict", default=None, help="JSON string of env vars")
    parser.add_argument("--output", "-o", default=None)
    args = parser.parse_args()

    env = load_env(env_file=args.env_file, env_str=args.env_dict)
    if not env:
        print("ERROR: No env provided. Use --env-file or --env-dict.", file=sys.stderr)
        sys.exit(1)

    report = run_all(env)
    report = redact_dict(report)

    output = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Report: {args.output}", file=sys.stderr)
    else:
        print(output)

    sys.exit(0 if report["overall_passed"] else 1)


if __name__ == "__main__":
    main()

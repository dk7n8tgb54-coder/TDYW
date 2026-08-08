"""
Environment Guard - Fail-Closed Environment Protection

This is the MOST CRITICAL safety module in the DR framework.
It enforces that restore drills and failure drills can ONLY run in a
dedicated temporary environment, never against dev or production.

Design principle: FAIL-CLOSED. If ANY check cannot be confirmed,
refuse ALL destructive operations.
"""

import os
import re
import sys
import subprocess
import json
from dataclasses import dataclass, field
from typing import List, Optional


# ---- Constants ----

# Database names that are FORBIDDEN (dev/prod)
FORBIDDEN_DB_NAMES = {"spug", "spug_prod", "spugdev"}

# Container names that are FORBIDDEN (prod/dev)
FORBIDDEN_CONTAINERS = {"tdyw", "tdyw-test", "tdyw-db", "tdyw-db-test", "tdyw-kkfileview", "tdyw-kkfileview-test"}

# Database names that are ALLOWED (must contain one of these)
ALLOWED_DB_NAME_PATTERNS = ["test", "perf", "drill", "dr_", "_dr", "recovery"]

# File paths that are FORBIDDEN for restore targets
FORBIDDEN_FILE_PATHS = ["/data/spug", "/data/spug/spug_api", "/data/spug/storage"]

# File paths that are ALLOWED (must be under one of these)
ALLOWED_FILE_PATH_PREFIXES = ["/tmp/", "/tmp/dr", "/dr/", "/var/tmp/dr", "/drill/"]


@dataclass
class CheckResult:
    """Result of a single safety check."""
    name: str
    passed: bool
    detail: str
    severity: str = "BLOCKER"  # BLOCKER or WARNING


@dataclass
class GuardReport:
    """Aggregate report of all environment checks."""
    checks: List[CheckResult] = field(default_factory=list)
    overall_passed: bool = False
    refusal_reasons: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = []
        lines.append("=" * 70)
        lines.append("ENVIRONMENT GUARD REPORT")
        lines.append("=" * 70)
        for c in self.checks:
            status = "PASS" if c.passed else "FAIL"
            lines.append(f"  [{status}] {c.name}: {c.detail}")
        lines.append("-" * 70)
        if self.overall_passed:
            lines.append("  OVERALL: PASSED - destructive operations permitted")
        else:
            lines.append("  OVERALL: REFUSED - destructive operations BLOCKED")
            lines.append("  Refusal reasons:")
            for r in self.refusal_reasons:
                lines.append(f"    - {r}")
        lines.append("=" * 70)
        return "\n".join(lines)


def _load_env(env_file: Optional[str] = None) -> dict:
    """Load environment variables from file or os.environ."""
    env = {}
    if env_file and os.path.isfile(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    # Also check os.environ (env file values take priority if both exist)
    for key in os.environ:
        if key not in env:
            env[key] = os.environ[key]
    return env


def check_allow_restore_drill(env: dict) -> CheckResult:
    """Check 1: ALLOW_RESTORE_DRILL must be explicitly 'true'."""
    value = env.get("ALLOW_RESTORE_DRILL", "").strip().lower()
    if value == "true":
        return CheckResult(
            name="ALLOW_RESTORE_DRILL",
            passed=True,
            detail="Set to 'true' - drills explicitly permitted",
        )
    return CheckResult(
        name="ALLOW_RESTORE_DRILL",
        passed=False,
        detail=f"Value is '{value}' (must be 'true' to permit drills)",
    )


def check_target_db_name(env: dict) -> CheckResult:
    """Check 2: Target database name must NOT be a dev/prod name."""
    db_name = env.get("DR_TARGET_DB", "").strip()
    if not db_name:
        return CheckResult(
            name="TARGET_DB_NAME",
            passed=False,
            detail="DR_TARGET_DB is not set",
        )
    if db_name.lower() in FORBIDDEN_DB_NAMES:
        return CheckResult(
            name="TARGET_DB_NAME",
            passed=False,
            detail=f"DR_TARGET_DB='{db_name}' is a FORBIDDEN dev/prod database name",
        )
    # Must contain an allowed pattern
    matched = any(p in db_name.lower() for p in ALLOWED_DB_NAME_PATTERNS)
    if not matched:
        return CheckResult(
            name="TARGET_DB_NAME",
            passed=False,
            detail=f"DR_TARGET_DB='{db_name}' does not contain any allowed pattern "
                   f"(must contain one of: {', '.join(ALLOWED_DB_NAME_PATTERNS)})",
        )
    return CheckResult(
        name="TARGET_DB_NAME",
        passed=True,
        detail=f"DR_TARGET_DB='{db_name}' is a dedicated drill database",
    )


def check_target_container(env: dict) -> CheckResult:
    """Check 3: Target container must NOT be a production/dev container."""
    container = env.get("DR_TARGET_CONTAINER", "").strip()
    if not container:
        return CheckResult(
            name="TARGET_CONTAINER",
            passed=False,
            detail="DR_TARGET_CONTAINER is not set",
        )
    if container in FORBIDDEN_CONTAINERS:
        return CheckResult(
            name="TARGET_CONTAINER",
            passed=False,
            detail=f"DR_TARGET_CONTAINER='{container}' is a FORBIDDEN production/dev container",
        )
    # Must contain an indicator that it's temporary
    temp_indicators = ["drill", "dr", "test-dr", "temp", "ephemeral"]
    matched = any(ind in container.lower() for ind in temp_indicators)
    if not matched:
        return CheckResult(
            name="TARGET_CONTAINER",
            passed=False,
            detail=f"DR_TARGET_CONTAINER='{container}' does not indicate a temporary/drill container "
                   f"(should contain one of: {', '.join(temp_indicators)})",
        )
    return CheckResult(
        name="TARGET_CONTAINER",
        passed=True,
        detail=f"DR_TARGET_CONTAINER='{container}' is a dedicated drill container",
    )


def check_target_db_container(env: dict) -> CheckResult:
    """Check 4: Target DB container must NOT be a production/dev DB container."""
    container = env.get("DR_TARGET_DB_CONTAINER", "").strip()
    if not container:
        return CheckResult(
            name="TARGET_DB_CONTAINER",
            passed=False,
            detail="DR_TARGET_DB_CONTAINER is not set",
        )
    if container in FORBIDDEN_CONTAINERS:
        return CheckResult(
            name="TARGET_DB_CONTAINER",
            passed=False,
            detail=f"DR_TARGET_DB_CONTAINER='{container}' is a FORBIDDEN production/dev DB container",
        )
    return CheckResult(
        name="TARGET_DB_CONTAINER",
        passed=True,
        detail=f"DR_TARGET_DB_CONTAINER='{container}' is a dedicated drill DB container",
    )


def check_file_restore_path(env: dict) -> CheckResult:
    """Check 5: File restore path must be under a temp directory."""
    path = env.get("DR_FILE_RESTORE_ROOT", "").strip()
    if not path:
        return CheckResult(
            name="FILE_RESTORE_PATH",
            passed=False,
            detail="DR_FILE_RESTORE_ROOT is not set",
        )
    # Check forbidden paths
    for forbidden in FORBIDDEN_FILE_PATHS:
        if path.startswith(forbidden):
            return CheckResult(
                name="FILE_RESTORE_PATH",
                passed=False,
                detail=f"DR_FILE_RESTORE_ROOT='{path}' is under a FORBIDDEN production path '{forbidden}'",
            )
    # Check allowed prefixes
    matched = any(path.startswith(prefix) for prefix in ALLOWED_FILE_PATH_PREFIXES)
    if not matched:
        return CheckResult(
            name="FILE_RESTORE_PATH",
            passed=False,
            detail=f"DR_FILE_RESTORE_ROOT='{path}' is not under an allowed temp directory "
                   f"(must start with one of: {', '.join(ALLOWED_FILE_PATH_PREFIXES)})",
        )
    return CheckResult(
        name="FILE_RESTORE_PATH",
        passed=True,
        detail=f"DR_FILE_RESTORE_ROOT='{path}' is under a temp directory",
    )


def check_container_exists(env: dict) -> CheckResult:
    """Check 6: Verify the target container actually exists and is running."""
    container = env.get("DR_TARGET_CONTAINER", "").strip()
    if not container:
        return CheckResult(
            name="CONTAINER_EXISTS",
            passed=False,
            detail="DR_TARGET_CONTAINER is not set",
        )
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip() == "true":
            return CheckResult(
                name="CONTAINER_EXISTS",
                passed=True,
                detail=f"Container '{container}' exists and is running",
            )
        return CheckResult(
            name="CONTAINER_EXISTS",
            passed=False,
            detail=f"Container '{container}' does not exist or is not running",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return CheckResult(
            name="CONTAINER_EXISTS",
            passed=False,
            detail=f"Cannot verify container (docker not available or timeout): {e}",
        )


def check_db_name_in_container(env: dict) -> CheckResult:
    """
    Check 7: Verify that the actual database in the target DB container
    matches DR_TARGET_DB (not 'spug').
    """
    db_container = env.get("DR_TARGET_DB_CONTAINER", "").strip()
    target_db = env.get("DR_TARGET_DB", "").strip()
    if not db_container or not target_db:
        return CheckResult(
            name="DB_NAME_IN_CONTAINER",
            passed=False,
            detail="DR_TARGET_DB_CONTAINER or DR_TARGET_DB not set",
        )
    try:
        result = subprocess.run(
            ["docker", "exec", db_container, "mysql", "-u", "root",
             "-e", f"SHOW DATABASES LIKE '{target_db}';"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "MYSQL_PWD": env.get("MYSQL_ROOT_PASSWORD", "")},
        )
        if result.returncode == 0 and target_db in result.stdout:
            return CheckResult(
                name="DB_NAME_IN_CONTAINER",
                passed=True,
                detail=f"Database '{target_db}' exists in container '{db_container}'",
            )
        return CheckResult(
            name="DB_NAME_IN_CONTAINER",
            passed=False,
            detail=f"Database '{target_db}' not found in container '{db_container}'",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return CheckResult(
            name="DB_NAME_IN_CONTAINER",
            passed=False,
            detail=f"Cannot verify database (docker/mysql not available): {e}",
        )


def check_no_spug_db_in_target_container(env: dict) -> CheckResult:
    """
    Check 8: Verify the target container does NOT have access to the 'spug' database.
    This is a critical check to prevent accidental writes to dev/prod.
    """
    db_container = env.get("DR_TARGET_DB_CONTAINER", "").strip()
    if not db_container:
        return CheckResult(
            name="NO_SPUG_DB_ACCESS",
            passed=False,
            detail="DR_TARGET_DB_CONTAINER not set",
        )
    try:
        result = subprocess.run(
            ["docker", "exec", db_container, "mysql", "-u", "root",
             "-e", "SHOW DATABASES;"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "MYSQL_PWD": env.get("MYSQL_ROOT_PASSWORD", "")},
        )
        if result.returncode == 0:
            databases = [d.strip() for d in result.stdout.split("\n") if d.strip()]
            # Filter out system databases
            user_dbs = [d for d in databases if d not in ("Database", "information_schema", "mysql", "performance_schema", "sys")]
            if "spug" in user_dbs:
                return CheckResult(
                    name="NO_SPUG_DB_ACCESS",
                    passed=False,
                    detail=f"Target DB container '{db_container}' has 'spug' database - DANGER: this is a dev/prod container!",
                )
            return CheckResult(
                name="NO_SPUG_DB_ACCESS",
                passed=True,
                detail=f"Target DB container '{db_container}' does not have 'spug' database",
            )
        return CheckResult(
            name="NO_SPUG_DB_ACCESS",
            passed=False,
            detail=f"Cannot list databases in '{db_container}' (exit code {result.returncode})",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return CheckResult(
            name="NO_SPUG_DB_ACCESS",
            passed=False,
            detail=f"Cannot verify (docker/mysql not available): {e}",
        )


def check_log_dir_is_temp(env: dict) -> CheckResult:
    """Check 9: Log directory must be under a temp path."""
    log_dir = env.get("DR_LOG_DIR", "").strip()
    if not log_dir:
        return CheckResult(
            name="LOG_DIR_TEMP",
            passed=False,
            detail="DR_LOG_DIR is not set",
            severity="WARNING",
        )
    matched = any(log_dir.startswith(prefix) for prefix in ALLOWED_FILE_PATH_PREFIXES)
    if not matched:
        return CheckResult(
            name="LOG_DIR_TEMP",
            passed=False,
            detail=f"DR_LOG_DIR='{log_dir}' is not under a temp directory",
            severity="WARNING",
        )
    return CheckResult(
        name="LOG_DIR_TEMP",
        passed=True,
        detail=f"DR_LOG_DIR='{log_dir}' is under a temp directory",
        severity="WARNING",
    )


def run_all_checks(env_file: Optional[str] = None, env_dict: Optional[dict] = None) -> GuardReport:
    """
    Run all environment guard checks.
    Returns a GuardReport with overall_passed=False if ANY BLOCKER check fails.
    """
    if env_dict:
        env = env_dict
    else:
        env = _load_env(env_file)

    report = GuardReport()
    report.checks = [
        check_allow_restore_drill(env),
        check_target_db_name(env),
        check_target_container(env),
        check_target_db_container(env),
        check_file_restore_path(env),
        check_container_exists(env),
        check_db_name_in_container(env),
        check_no_spug_db_in_target_container(env),
        check_log_dir_is_temp(env),
    ]

    # Overall pass: all BLOCKER checks must pass
    blocker_checks = [c for c in report.checks if c.severity == "BLOCKER"]
    report.overall_passed = all(c.passed for c in blocker_checks)

    if not report.overall_passed:
        for c in report.checks:
            if not c.passed and c.severity == "BLOCKER":
                report.refusal_reasons.append(f"{c.name}: {c.detail}")

    return report


def assert_safe_for_drill(env_file: Optional[str] = None, env_dict: Optional[dict] = None) -> GuardReport:
    """
    Run all checks and EXIT if any BLOCKER fails.
    This is the main entry point for runners.
    """
    report = run_all_checks(env_file=env_file, env_dict=env_dict)
    print(report.summary(), file=sys.stderr)

    if not report.overall_passed:
        print("\nFATAL: Environment guard refused to proceed.", file=sys.stderr)
        print("All destructive operations are BLOCKED.", file=sys.stderr)
        print("To fix:", file=sys.stderr)
        for reason in report.refusal_reasons:
            print(f"  - {reason}", file=sys.stderr)
        sys.exit(2)

    return report


def is_inspection_only(env_file: Optional[str] = None) -> bool:
    """
    Check if we're in inspection-only mode (ALLOW_RESTORE_DRILL not true).
    inspect_backups.py can run in this mode.
    """
    env = _load_env(env_file)
    return env.get("ALLOW_RESTORE_DRILL", "").strip().lower() != "true"

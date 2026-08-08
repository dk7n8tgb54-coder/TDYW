#!/usr/bin/env python3
"""
Security Validator

Validates security posture after a restore drill:
  1. No plaintext passwords in restored database
  2. Backup file permissions are restrictive (0600 for cnf/env files)
  3. No sensitive data in restore logs
  4. Django SECRET_KEY is not default/empty
  5. Debug mode is not enabled in restored app
  6. No hardcoded credentials in restored config files
"""

import argparse
import json
import os
import sys
import subprocess
import re
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
DR_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(DR_ROOT))

from helpers.redaction import redact, redact_dict, REDACTION_PATTERNS


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
class CheckResult:
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
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e)}


def check_no_plaintext_passwords(env: dict) -> CheckResult:
    """1. Verify no plaintext passwords in database."""
    db = env.get("DR_TARGET_DB", "spug_drill")
    db_container = env.get("DR_TARGET_DB_CONTAINER", "tdyw-db-drill")

    # Check that password fields look hashed (not plaintext)
    query = (
        f"SELECT password FROM `{db}`.account_user LIMIT 5;"
    )

    try:
        result = subprocess.run(
            ["docker", "exec", db_container, "mysql", "-u", "root", "-N", "-e", query],
            capture_output=True, text=True, timeout=15,
        )

        if result.returncode != 0:
            return CheckResult("no_plaintext_passwords", False, f"Query failed: {redact(result.stderr[:200])}")

        passwords = [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
        if not passwords:
            return CheckResult("no_plaintext_passwords", True, "No user passwords found (empty DB)")

        # Django passwords start with algorithm prefix like pbkdf2_sha256$, argon2$, etc.
        hashed = sum(1 for p in passwords if p.startswith(("pbkdf2_", "argon2", "bcrypt", "!")))
        plaintext = len(passwords) - hashed

        passed = plaintext == 0
        detail = f"Checked {len(passwords)} passwords, hashed={hashed}, plaintext={plaintext}"

        return CheckResult("no_plaintext_passwords", passed, detail, {
            "total_checked": len(passwords),
            "hashed": hashed,
            "plaintext": plaintext,
        })
    except Exception as e:
        return CheckResult("no_plaintext_passwords", False, f"Error: {e}")


def check_backup_file_permissions(env: dict) -> CheckResult:
    """2. Check that backup config files have restrictive permissions."""
    restore_root = env.get("DR_FILE_RESTORE_ROOT", "/tmp/dr-restore-drill")

    # Check for cnf and env files in restore root
    sensitive_files = []
    for root, dirs, files in os.walk(restore_root):
        for f in files:
            if f.endswith((".cnf", ".env", ".key", ".pem")):
                fp = os.path.join(root, f)
                try:
                    stat = os.stat(fp)
                    mode = stat.st_mode & 0o777
                    sensitive_files.append({
                        "path": os.path.relpath(fp, restore_root),
                        "mode": oct(mode),
                        "secure": (mode & 0o077) == 0,
                    })
                except OSError:
                    pass

    insecure = [f for f in sensitive_files if not f["secure"]]
    passed = len(insecure) == 0
    detail = f"Found {len(sensitive_files)} sensitive files, {len(insecure)} insecure"

    return CheckResult("backup_file_permissions", passed, detail, {
        "sensitive_files": sensitive_files[:20],
        "insecure_count": len(insecure),
    })


def check_no_sensitive_in_logs(env: dict) -> CheckResult:
    """3. Check that restore logs don't contain sensitive data."""
    log_dir = env.get("DR_LOG_DIR", "/tmp/dr-logs")

    if not os.path.isdir(log_dir):
        return CheckResult("no_sensitive_in_logs", True, "Log directory not found (no logs to check)")

    leaked = []
    files_checked = 0

    for root, dirs, files in os.walk(log_dir):
        for f in files:
            if f.endswith((".log", ".txt", ".json")):
                fp = os.path.join(root, f)
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    files_checked += 1

                    # Check for common secret patterns that should have been redacted
                    secret_patterns = [
                        (r"password\s*[=:]\s*[^\sRED]", "password"),
                        (r"BORG_PASSPHRASE\s*=\s*[^\sRED]", "borg_passphrase"),
                        (r"SECRET_KEY\s*=\s*[^\sRED]", "secret_key"),
                        (r"mysql://[^:]+:[^R][^E][^D]", "mysql_url"),
                    ]

                    for pattern, label in secret_patterns:
                        matches = re.findall(pattern, content, re.IGNORECASE)
                        if matches:
                            leaked.append(f"{os.path.relpath(fp, log_dir)}: {label} ({len(matches)} occurrences)")
                except Exception:
                    pass

    passed = len(leaked) == 0
    detail = f"Checked {files_checked} log files, {len(leaked)} with sensitive data"

    return CheckResult("no_sensitive_in_logs", passed, detail, {
        "files_checked": files_checked,
        "leaked": leaked[:10],
    })


def check_secret_key(env: dict) -> CheckResult:
    """4. Verify Django SECRET_KEY is not default or empty."""
    r = docker_exec(env, "python -c \"from django.conf import settings; print('SET' if settings.SECRET_KEY and len(settings.SECRET_KEY) > 10 else 'WEAK')\" 2>&1")

    # Don't print the actual key
    output = r["stdout"].strip()
    passed = output == "SET"
    detail = f"SECRET_KEY status: {output}" if output else f"Check failed: {redact(r['stderr'][:200])}"

    return CheckResult("secret_key", passed, detail, {"status": output})


def check_debug_mode(env: dict) -> CheckResult:
    """5. Verify DEBUG is not enabled in restored app."""
    r = docker_exec(env, "python -c \"from django.conf import settings; print('DEBUG_ON' if settings.DEBUG else 'DEBUG_OFF')\" 2>&1")

    output = r["stdout"].strip()
    passed = output == "DEBUG_OFF"
    detail = f"Debug mode: {output}" if output else f"Check failed: {redact(r['stderr'][:200])}"

    return CheckResult("debug_mode", passed, detail, {"status": output})


def check_no_hardcoded_credentials(env: dict) -> CheckResult:
    """6. Check for hardcoded credentials in config files."""
    restore_root = env.get("DR_FILE_RESTORE_ROOT", "/tmp/dr-restore-drill")

    if not os.path.isdir(restore_root):
        return CheckResult("no_hardcoded_credentials", True, "Restore root not found")

    # Scan config files for hardcoded credentials
    config_extensions = [".yml", ".yaml", ".conf", ".ini", ".env", ".json"]
    hardcoded = []
    files_scanned = 0

    for root, dirs, files in os.walk(restore_root):
        for f in files:
            if any(f.endswith(ext) for ext in config_extensions):
                fp = os.path.join(root, f)
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    files_scanned += 1

                    # Look for actual password values (not redacted)
                    if re.search(r"password\s*[=:]\s*\S+", content, re.IGNORECASE):
                        # Check it's not already redacted
                        if not re.search(r"password\s*[=:]\s*REDACTED", content, re.IGNORECASE):
                            hardcoded.append(f"{os.path.relpath(fp, restore_root)}: password field")
                except Exception:
                    pass

    passed = len(hardcoded) == 0
    detail = f"Scanned {files_scanned} config files, {len(hardcoded)} with hardcoded credentials"

    return CheckResult("no_hardcoded_credentials", passed, detail, {
        "files_scanned": files_scanned,
        "hardcoded": hardcoded[:10],
    })


def run_all(env: dict) -> dict:
    checks = [
        check_no_plaintext_passwords(env),
        check_backup_file_permissions(env),
        check_no_sensitive_in_logs(env),
        check_secret_key(env),
        check_debug_mode(env),
        check_no_hardcoded_credentials(env),
    ]

    passed = sum(1 for c in checks if c.passed)
    failed = sum(1 for c in checks if not c.passed)

    return {
        "validator": "security_validator",
        "timestamp": datetime.now().isoformat(),
        "total": len(checks),
        "passed": passed,
        "failed": failed,
        "checks": [asdict(c) for c in checks],
        "overall_passed": failed == 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Security post-restore validator")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--env-dict", default=None)
    parser.add_argument("--output", "-o", default=None)
    args = parser.parse_args()

    env = load_env(env_file=args.env_file, env_str=args.env_dict)
    if not env:
        print("ERROR: No env provided.", file=sys.stderr)
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

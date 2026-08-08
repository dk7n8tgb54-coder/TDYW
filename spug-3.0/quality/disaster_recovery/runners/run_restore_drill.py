#!/usr/bin/env python3
"""
Restore Drill Runner

Orchestrates a full restore drill in an ISOLATED TEMP environment.
REFUSES to run if the environment guard fails (fail-closed).

Prerequisites:
  - ALLOW_RESTORE_DRILL=true in env file
  - DR_TARGET_DB must be a temp database (not 'spug')
  - DR_TARGET_CONTAINER must be a temp container (not 'tdyw' or 'tdyw-test')
  - DR_FILE_RESTORE_ROOT must be under /tmp/ or /dr/

Steps:
  1. Run environment guard checks (CRITICAL)
  2. Locate and verify the backup archive
  3. Restore database from dump
  4. Restore file volumes
  5. Run all validators
  6. Generate timing report (RPO/RTO)
  7. Cleanup (optional)
"""

import argparse
import json
import os
import sys
import subprocess
import time
from pathlib import Path
from typing import Optional

# Add parent dirs to path for imports
SCRIPT_DIR = Path(__file__).resolve().parent
DR_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(DR_ROOT))

from helpers.environment_guard import assert_safe_for_drill, run_all_checks
from helpers.timing import RecoveryTimingReport, Stopwatch
from helpers.redaction import redact, redact_dict
from helpers.manifest import parse_backup_manifest, validate_backup_manifest


def find_project_root() -> str:
    """Find the project root by looking for AGENTS.md."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "AGENTS.md").exists():
            return str(current)
        current = current.parent
    return str(Path(__file__).resolve().parents[3])


def load_env_file(env_file: str) -> dict:
    """Load environment variables from a file."""
    env = {}
    if not os.path.isfile(env_file):
        return env
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def locate_backup_archive(env: dict, project_root: str) -> Optional[dict]:
    """
    Locate the backup archive to restore from.
    Checks both backup_set directories and Borg archives.
    """
    archive_name = env.get("DR_BACKUP_ARCHIVE", "")
    if not archive_name:
        print("ERROR: DR_BACKUP_ARCHIVE not set in env file", file=sys.stderr)
        return None

    # Check backup_set directory
    backup_set_dir = os.path.join(project_root, "backups", archive_name)
    if os.path.isdir(backup_set_dir):
        manifest_path = os.path.join(backup_set_dir, "manifest.json")
        if os.path.isfile(manifest_path):
            try:
                manifest = parse_backup_manifest(manifest_path)
                validation = validate_backup_manifest(manifest)
                if validation.valid:
                    return {
                        "type": "backup_set",
                        "path": backup_set_dir,
                        "manifest": manifest,
                    }
                else:
                    print(f"WARNING: Manifest validation errors: {validation.errors}", file=sys.stderr)
                    return {
                        "type": "backup_set",
                        "path": backup_set_dir,
                        "manifest": manifest,
                        "validation_errors": validation.errors,
                    }
            except Exception as e:
                print(f"ERROR: Cannot parse manifest.json: {e}", file=sys.stderr)
                return None
        else:
            print(f"WARNING: No manifest.json in {backup_set_dir}", file=sys.stderr)

    # Check Borg archive
    borg_env_file = env.get("BORG_ENV_FILE", "")
    if borg_env_file and os.path.isfile(borg_env_file):
        try:
            result = subprocess.run(
                ["bash", "-c", f"source {borg_env_file} && borg list --json"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for archive in data.get("archives", []):
                    if archive.get("name") == archive_name:
                        return {
                            "type": "borg",
                            "archive_name": archive_name,
                            "borg_env_file": borg_env_file,
                            "archive_info": archive,
                        }
        except Exception as e:
            print(f"ERROR: Cannot list Borg archives: {e}", file=sys.stderr)

    print(f"ERROR: Backup archive '{archive_name}' not found", file=sys.stderr)
    return None


def restore_database(env: dict, backup_info: dict, timing: RecoveryTimingReport) -> bool:
    """
    Restore database from backup dump to the target temp database.
    """
    phase = timing.add_phase("database_restore")
    phase.start()

    target_db = env["DR_TARGET_DB"]
    target_db_container = env["DR_TARGET_DB_CONTAINER"]
    restore_cnf = env.get("RESTORE_CLIENT_CNF", "")

    try:
        if backup_info["type"] == "backup_set":
            dump_file = os.path.join(backup_info["path"], "database.sql.gz")
            if not os.path.isfile(dump_file):
                phase.finish("failed", f"Database dump not found: {dump_file}")
                return False

            # Restore: gunzip | mysql
            if restore_cnf:
                cmd = (
                    f"docker exec -i {target_db_container} "
                    f"bash -c 'gunzip -c | mysql --defaults-extra-file={restore_cnf} {target_db}'"
                )
            else:
                cmd = (
                    f"docker exec -i {target_db_container} "
                    f"bash -c 'gunzip -c | mysql -u root {target_db}'"
                )

            with open(dump_file, "rb") as f:
                result = subprocess.run(
                    ["docker", "exec", "-i", target_db_container,
                     "bash", "-c", f"gunzip -c | mysql -u root {target_db}"],
                    stdin=f, capture_output=True, timeout=600,
                )

            if result.returncode == 0:
                phase.finish("completed", f"Restored to {target_db}")
                return True
            else:
                err = redact(result.stderr.decode("utf-8", errors="replace")[:500])
                phase.finish("failed", f"mysql restore failed: {err}")
                return False

        elif backup_info["type"] == "borg":
            borg_env = backup_info.get("borg_env_file", env.get("BORG_ENV_FILE", ""))
            archive_name = backup_info["archive_name"]

            # Extract DB dump from Borg and pipe to mysql
            extract_cmd = f"source {borg_env} && borg extract --stdout {archive_name} database.sql.gz"
            restore_cmd = f"docker exec -i {target_db_container} bash -c 'gunzip -c | mysql -u root {target_db}'"

            result = subprocess.run(
                ["bash", "-c", f"{extract_cmd} | {restore_cmd}"],
                capture_output=True, text=True, timeout=600,
            )

            if result.returncode == 0:
                phase.finish("completed", f"Restored from Borg archive to {target_db}")
                return True
            else:
                err = redact(result.stderr[:500])
                phase.finish("failed", f"Borg DB restore failed: {err}")
                return False

    except subprocess.TimeoutExpired:
        phase.finish("failed", "Database restore timed out (600s)")
        return False
    except Exception as e:
        phase.finish("failed", f"Exception: {e}")
        return False


def restore_files(env: dict, backup_info: dict, timing: RecoveryTimingReport) -> bool:
    """
    Restore file volumes to the target temp directory.
    """
    phase = timing.add_phase("file_restore")
    phase.start()

    restore_root = env["DR_FILE_RESTORE_ROOT"]
    os.makedirs(restore_root, exist_ok=True)

    try:
        if backup_info["type"] == "backup_set":
            backup_path = backup_info["path"]

            # Restore documents
            docs_archive = os.path.join(backup_path, "documents.tar.gz")
            if os.path.isfile(docs_archive):
                result = subprocess.run(
                    ["tar", "xzf", docs_archive, "-C", restore_root],
                    capture_output=True, text=True, timeout=900,
                )
                if result.returncode != 0:
                    phase.finish("failed", f"documents restore failed: {result.stderr[:200]}")
                    return False

            # Restore media
            media_archive = os.path.join(backup_path, "media.tar.gz")
            if os.path.isfile(media_archive):
                result = subprocess.run(
                    ["tar", "xzf", media_archive, "-C", restore_root],
                    capture_output=True, text=True, timeout=900,
                )
                if result.returncode != 0:
                    phase.finish("failed", f"media restore failed: {result.stderr[:200]}")
                    return False

            phase.finish("completed", f"Files restored to {restore_root}")
            return True

        elif backup_info["type"] == "borg":
            borg_env = backup_info.get("borg_env_file", env.get("BORG_ENV_FILE", ""))
            archive_name = backup_info["archive_name"]

            # Extract documents volume
            for vol_name in ["documents", "media"]:
                result = subprocess.run(
                    ["bash", "-c",
                     f"source {borg_env} && borg extract {archive_name} --path {vol_name}"],
                    capture_output=True, text=True, timeout=900,
                    cwd=restore_root,
                )
                if result.returncode != 0:
                    phase.finish("failed", f"Borg {vol_name} extract failed: {result.stderr[:200]}")
                    return False

            phase.finish("completed", f"Files restored from Borg to {restore_root}")
            return True

    except subprocess.TimeoutExpired:
        phase.finish("failed", "File restore timed out (900s)")
        return False
    except Exception as e:
        phase.finish("failed", f"Exception: {e}")
        return False


def run_validators(env: dict, timing: RecoveryTimingReport) -> dict:
    """Run all post-restore validators."""
    results = {}

    validators = [
        ("database_validator", "database"),
        ("file_validator", "files"),
        ("checksum_validator", "checksums"),
        ("application_validator", "application"),
        ("security_validator", "security"),
    ]

    for validator_name, phase_name in validators:
        phase = timing.add_phase(f"validate_{phase_name}")
        phase.start()

        validator_path = DR_ROOT / "validators" / f"{validator_name}.py"
        if not validator_path.exists():
            phase.finish("skipped", f"Validator not found: {validator_name}")
            results[validator_name] = {"status": "skipped", "reason": "not found"}
            continue

        try:
            result = subprocess.run(
                [sys.executable, str(validator_path), "--env-dict", json.dumps(env)],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                phase.finish("completed", "Validator passed")
                results[validator_name] = {"status": "passed", "output": result.stdout[:1000]}
            else:
                phase.finish("failed", f"Validator failed: {result.stderr[:200]}")
                results[validator_name] = {"status": "failed", "stderr": result.stderr[:500]}
        except subprocess.TimeoutExpired:
            phase.finish("failed", "Validator timed out (300s)")
            results[validator_name] = {"status": "timeout"}
        except Exception as e:
            phase.finish("failed", f"Exception: {e}")
            results[validator_name] = {"status": "error", "error": str(e)}

    return results


def run_restore_drill(env_file: str, project_root: str, skip_validators: bool = False) -> dict:
    """Run the full restore drill."""

    # STEP 1: Environment Guard (CRITICAL)
    print("=" * 70, file=sys.stderr)
    print("STEP 1: Environment Guard Check", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    guard_report = assert_safe_for_drill(env_file=env_file)
    print("Environment guard PASSED.", file=sys.stderr)

    env = load_env_file(env_file)

    # Initialize timing report
    timing = RecoveryTimingReport(operation="restore_drill")

    # STEP 2: Locate backup
    print("\nSTEP 2: Locating backup archive", file=sys.stderr)
    backup_info = locate_backup_archive(env, project_root)
    if not backup_info:
        return {"status": "failed", "error": "Backup archive not found", "timing": timing.to_dict()}

    print(f"Found backup: {backup_info['type']} - {redact(str(backup_info.get('path', backup_info.get('archive_name', ''))))}", file=sys.stderr)

    # STEP 3: Restore database
    print("\nSTEP 3: Restoring database", file=sys.stderr)
    db_ok = restore_database(env, backup_info, timing)
    if not db_ok:
        timing.finalize()
        return {"status": "failed", "error": "Database restore failed", "timing": timing.to_dict()}

    # STEP 4: Restore files
    print("\nSTEP 4: Restoring files", file=sys.stderr)
    files_ok = restore_files(env, backup_info, timing)
    if not files_ok:
        timing.finalize()
        return {"status": "failed", "error": "File restore failed", "timing": timing.to_dict()}

    # STEP 5: Run validators
    validator_results = {}
    if not skip_validators:
        print("\nSTEP 5: Running validators", file=sys.stderr)
        validator_results = run_validators(env, timing)

    # Finalize timing
    timing.finalize()

    # Generate report
    report = {
        "status": "completed",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "environment_guard": "passed",
        "backup_info": {
            "type": backup_info["type"],
            "archive": redact(str(backup_info.get("archive_name", backup_info.get("path", "")))),
        },
        "timing": timing.to_dict(),
        "validators": validator_results,
    }

    return redact_dict(report)


def main():
    parser = argparse.ArgumentParser(
        description="Restore drill runner (REFUSES to run if environment guard fails)"
    )
    parser.add_argument(
        "--env-file", required=True,
        help="Path to environment file (must contain ALLOW_RESTORE_DRILL=true)",
    )
    parser.add_argument(
        "--project-root", default=None,
        help="Project root directory (default: auto-detect)",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output file path for JSON report (default: stdout)",
    )
    parser.add_argument(
        "--skip-validators", action="store_true",
        help="Skip post-restore validators",
    )

    args = parser.parse_args()
    project_root = args.project_root or find_project_root()

    print("RESTORE DRILL RUNNER", file=sys.stderr)
    print(f"Project: {project_root}", file=sys.stderr)
    print(f"Env file: {args.env_file}", file=sys.stderr)
    print("WARNING: This will attempt to RESTORE data to a temp environment.", file=sys.stderr)
    print("", file=sys.stderr)

    report = run_restore_drill(args.env_file, project_root, skip_validators=args.skip_validators)

    output = json.dumps(report, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\nReport written to: {args.output}", file=sys.stderr)
    else:
        print(output)

    # Print timing summary
    if "timing" in report:
        timing_data = report["timing"]
        print(f"\nTotal duration: {timing_data.get('total_duration_seconds', 0):.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()

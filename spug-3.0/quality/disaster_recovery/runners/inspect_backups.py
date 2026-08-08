#!/usr/bin/env python3
"""
Inspect Existing Backup Setup (Static Analysis Only)

This is the ONLY runner that can run WITHOUT ALLOW_RESTORE_DRILL=true.
It performs read-only static analysis of the backup configuration.

Scans:
  - backups/ directory (backup_set scripts, config, cron)
  - borgbackup/ directory (borg scripts, env file)
  - docker/docker-compose.yml (volume definitions, services)
  - Project root for any backup-related files

Output: JSON report with findings, warnings, and recommendations.
"""

import argparse
import json
import os
import sys
import subprocess
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add parent dirs to path for imports
SCRIPT_DIR = Path(__file__).resolve().parent
DR_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(DR_ROOT))

from helpers.redaction import redact
from helpers.manifest import (
    load_inventory, validate_inventory,
    BackupInventory, ValidationResult,
)


def find_project_root() -> str:
    """Find the project root by looking for AGENTS.md."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "AGENTS.md").exists():
            return str(current)
        current = current.parent
    return str(Path(__file__).resolve().parents[3])


def scan_backup_set_dir(project_root: str) -> Dict[str, Any]:
    """Scan backups/ directory for backup_set configuration."""
    backups_dir = os.path.join(project_root, "backups")
    findings = {
        "directory": backups_dir,
        "exists": os.path.isdir(backups_dir),
        "files": [],
        "scripts": {},
        "config_files": [],
        "warnings": [],
    }

    if not findings["exists"]:
        findings["warnings"].append("backups/ directory does not exist")
        return findings

    for entry in sorted(os.listdir(backups_dir)):
        entry_path = os.path.join(backups_dir, entry)
        findings["files"].append(entry)

        if entry.endswith(".sh") and os.access(entry_path, os.X_OK):
            findings["scripts"][entry] = {
                "path": entry_path,
                "executable": True,
            }
            # Read first line for shebang
            try:
                with open(entry_path, "r", encoding="utf-8", errors="replace") as f:
                    first_line = f.readline().strip()
                    findings["scripts"][entry]["shebang"] = first_line
            except Exception:
                pass

        if entry.endswith(".cnf"):
            stat_info = os.stat(entry_path)
            mode = oct(stat_info.st_mode & 0o777)
            findings["config_files"].append({
                "name": entry,
                "path": entry_path,
                "permissions": mode,
                "secure": (stat_info.st_mode & 0o077) == 0,
            })
            if (stat_info.st_mode & 0o077) != 0:
                findings["warnings"].append(
                    f"Config file {entry} has insecure permissions ({mode}), should be 0600"
                )

        if entry.endswith(".cron") or entry.endswith(".cron.example"):
            findings["cron_file"] = entry_path

    return findings


def scan_borgbackup_dir(project_root: str) -> Dict[str, Any]:
    """Scan borgbackup/ directory for Borg configuration."""
    borg_dir = os.path.join(project_root, "borgbackup")
    findings = {
        "directory": borg_dir,
        "exists": os.path.isdir(borg_dir),
        "files": [],
        "scripts": {},
        "env_file": {},
        "warnings": [],
    }

    if not findings["exists"]:
        findings["warnings"].append("borgbackup/ directory does not exist")
        return findings

    for entry in sorted(os.listdir(borg_dir)):
        entry_path = os.path.join(borg_dir, entry)
        findings["files"].append(entry)

        if entry.endswith(".sh"):
            findings["scripts"][entry] = {
                "path": entry_path,
                "executable": os.access(entry_path, os.X_OK),
            }

        if entry.endswith(".env"):
            stat_info = os.stat(entry_path)
            mode = oct(stat_info.st_mode & 0o777)
            findings["env_file"] = {
                "name": entry,
                "path": entry_path,
                "permissions": mode,
                "secure": (stat_info.st_mode & 0o077) == 0,
            }
            if (stat_info.st_mode & 0o077) != 0:
                findings["warnings"].append(
                    f"Env file {entry} has insecure permissions ({mode}), should be 0600"
                )

            # Read env file (redacted)
            try:
                with open(entry_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    findings["env_file"]["content_redacted"] = redact(content)
                    # Check for required keys
                    has_repo = "BORG_REPO" in content
                    has_passphrase = "BORG_PASSPHRASE" in content
                    findings["env_file"]["has_borg_repo"] = has_repo
                    findings["env_file"]["has_passphrase"] = has_passphrase
                    if not has_repo:
                        findings["warnings"].append("borg.env missing BORG_REPO")
                    if not has_passphrase:
                        findings["warnings"].append("borg.env missing BORG_PASSPHRASE")
            except Exception as e:
                findings["warnings"].append(f"Cannot read {entry}: {e}")

    return findings


def scan_docker_compose(project_root: str) -> Dict[str, Any]:
    """Scan docker-compose.yml for backup-relevant configuration."""
    compose_path = os.path.join(project_root, "docker", "docker-compose.yml")
    findings = {
        "file": compose_path,
        "exists": os.path.isfile(compose_path),
        "volumes": [],
        "services": [],
        "warnings": [],
    }

    if not findings["exists"]:
        findings["warnings"].append("docker-compose.yml not found")
        return findings

    try:
        with open(compose_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find volume definitions
        volume_pattern = re.compile(r"^  (\S+):\s*$", re.MULTILINE)
        # Find named volumes
        if "volumes:" in content:
            vol_section = content.split("volumes:")[1] if "volumes:" in content else ""
            for match in re.finditer(r"^  ([a-zA-Z0-9_-]+):\s*$", vol_section, re.MULTILINE):
                vol_name = match.group(1)
                if not vol_name.startswith(("driver", "name")):
                    findings["volumes"].append(vol_name)

        # Find service names
        services_section = content.split("services:")[1] if "services:" in content else ""
        for match in re.finditer(r"^  ([a-zA-Z0-9_-]+):\s*$", services_section, re.MULTILINE):
            findings["services"].append(match.group(1))

    except Exception as e:
        findings["warnings"].append(f"Cannot parse docker-compose.yml: {e}")

    return findings


def scan_for_backup_cron(project_root: str) -> Dict[str, Any]:
    """Check if backup cron is installed."""
    findings = {
        "cron_installed": False,
        "cron_entries": [],
        "warnings": [],
    }

    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "backup" in line.lower() or "borg" in line.lower():
                    findings["cron_entries"].append(redact(line))
                    findings["cron_installed"] = True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        findings["warnings"].append("Cannot check crontab (not available or timeout)")

    return findings


def check_docker_volumes(project_root: str) -> Dict[str, Any]:
    """List Docker volumes to check for backup-related volumes."""
    findings = {
        "volumes": [],
        "warnings": [],
    }

    try:
        result = subprocess.run(
            ["docker", "volume", "ls", "--format", "{{.Name}}\t{{.Driver}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split("\t")
                    vol_name = parts[0] if parts else line
                    driver = parts[1] if len(parts) > 1 else ""
                    findings["volumes"].append({
                        "name": vol_name,
                        "driver": driver,
                    })
    except (subprocess.TimeoutExpired, FileNotFoundError):
        findings["warnings"].append("Cannot list Docker volumes")

    return findings


def check_borg_repo(borg_env_path: str) -> Dict[str, Any]:
    """Check Borg repository status (read-only)."""
    findings = {
        "repo_accessible": False,
        "archives": [],
        "warnings": [],
    }

    if not os.path.isfile(borg_env_path):
        findings["warnings"].append(f"Borg env file not found: {borg_env_path}")
        return findings

    try:
        # Source borg env and list archives
        cmd = f"source {borg_env_path} && borg list --json 2>/dev/null"
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            findings["repo_accessible"] = True
            for archive in data.get("archives", []):
                findings["archives"].append({
                    "name": archive.get("name", ""),
                    "time": archive.get("time", ""),
                    "id": archive.get("id", "")[:12],  # truncated for safety
                })
        else:
            findings["warnings"].append(f"borg list failed: {redact(result.stderr[:200])}")
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        findings["warnings"].append(f"Cannot check Borg repo: {e}")

    return findings


def validate_backup_inventory(project_root: str) -> Dict[str, Any]:
    """Validate the backup_inventory.yml file."""
    inventory_path = os.path.join(
        project_root, "quality", "disaster_recovery", "backup_inventory.yml"
    )
    findings = {
        "inventory_path": inventory_path,
        "exists": os.path.isfile(inventory_path),
        "validation": None,
        "warnings": [],
    }

    if not findings["exists"]:
        findings["warnings"].append("backup_inventory.yml not found")
        return findings

    try:
        inventory = load_inventory(inventory_path)
        result = validate_inventory(inventory)
        findings["validation"] = {
            "valid": result.valid,
            "errors": result.errors,
            "warnings": result.warnings,
            "object_count": result.object_count,
            "system_count": result.system_count,
        }
    except Exception as e:
        findings["warnings"].append(f"Cannot parse backup_inventory.yml: {e}")

    return findings


def run_inspection(project_root: str, check_borg: bool = False) -> dict:
    """Run full static inspection and return a report."""
    report = {
        "inspection_type": "static_analysis",
        "destructive": False,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "project_root": project_root,
        "sections": {},
    }

    # 1. Backup set directory
    report["sections"]["backup_set"] = scan_backup_set_dir(project_root)

    # 2. Borgbackup directory
    report["sections"]["borgbackup"] = scan_borgbackup_dir(project_root)

    # 3. Docker compose
    report["sections"]["docker_compose"] = scan_docker_compose(project_root)

    # 4. Cron status
    report["sections"]["cron"] = scan_for_backup_cron(project_root)

    # 5. Docker volumes
    report["sections"]["docker_volumes"] = check_docker_volumes(project_root)

    # 6. Backup inventory validation
    report["sections"]["inventory"] = validate_backup_inventory(project_root)

    # 7. Borg repo (optional, requires borg installed)
    if check_borg:
        borg_env = os.path.join(project_root, "borgbackup", "borg.env")
        report["sections"]["borg_repo"] = check_borg_repo(borg_env)

    # Collect all warnings
    all_warnings = []
    for section_name, section_data in report["sections"].items():
        for warning in section_data.get("warnings", []):
            all_warnings.append(f"[{section_name}] {warning}")
    report["total_warnings"] = len(all_warnings)
    report["warnings"] = all_warnings

    # Redact the entire report
    from helpers.redaction import redact_dict
    report = redact_dict(report)

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Inspect existing backup setup (static analysis only, no destructive ops)"
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Project root directory (default: auto-detect)",
    )
    parser.add_argument(
        "--check-borg",
        action="store_true",
        help="Also check Borg repository status (requires borg installed)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json)",
    )

    args = parser.parse_args()

    project_root = args.project_root or find_project_root()
    print(f"Inspecting backup setup in: {project_root}", file=sys.stderr)
    print(f"Destructive operations: NO (static analysis only)", file=sys.stderr)
    print("", file=sys.stderr)

    report = run_inspection(project_root, check_borg=args.check_borg)

    if args.format == "json":
        output = json.dumps(report, indent=2, ensure_ascii=False)
    else:
        # Text format
        lines = []
        lines.append("=" * 70)
        lines.append("BACKUP INSPECTION REPORT (Static Analysis)")
        lines.append("=" * 70)
        lines.append(f"Project: {report['project_root']}")
        lines.append(f"Timestamp: {report['timestamp']}")
        lines.append(f"Warnings: {report['total_warnings']}")
        lines.append("")
        for section_name, section_data in report["sections"].items():
            lines.append(f"--- {section_name.upper()} ---")
            lines.append(json.dumps(section_data, indent=2, ensure_ascii=False))
            lines.append("")
        output = "\n".join(lines)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Report written to: {args.output}", file=sys.stderr)
    else:
        print(output)

    # Exit with warning count as info (not error)
    if report["total_warnings"] > 0:
        print(f"\n{report['total_warnings']} warning(s) found.", file=sys.stderr)


if __name__ == "__main__":
    main()

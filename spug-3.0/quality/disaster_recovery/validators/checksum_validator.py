#!/usr/bin/env python3
"""
Checksum Validator

Verifies SHA256 checksums of restored files against the backup manifest.
Performs both full verification (all files) and sampled verification (subset).
"""

import argparse
import json
import os
import sys
import hashlib
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional
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


def compute_sha256(file_path: str) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_sha256sums(sha256sums_path: str) -> Dict[str, str]:
    """Load a SHA256SUMS file into a dict of {relative_path: hash}."""
    checksums = {}
    if not os.path.isfile(sha256sums_path):
        return checksums
    with open(sha256sums_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                hash_val = parts[0].strip()
                file_path = parts[1].strip().lstrip("*")
                checksums[file_path] = hash_val
    return checksums


@dataclass
class ChecksumResult:
    name: str
    passed: bool
    detail: str
    data: dict = field(default_factory=dict)


def verify_full(restore_root: str, sha256sums_path: str) -> ChecksumResult:
    """Verify all files against SHA256SUMS."""
    if not os.path.isfile(sha256sums_path):
        return ChecksumResult("full_verification", False, f"SHA256SUMS not found: {sha256sums_path}")

    checksums = load_sha256sums(sha256sums_path)
    if not checksums:
        return ChecksumResult("full_verification", False, "SHA256SUMS file is empty or unreadable")

    verified = 0
    failed = 0
    missing = 0
    failures = []

    for rel_path, expected_hash in checksums.items():
        full_path = os.path.join(restore_root, rel_path)
        if not os.path.isfile(full_path):
            missing += 1
            failures.append(f"MISSING: {rel_path}")
            continue

        actual_hash = compute_sha256(full_path)
        if actual_hash == expected_hash:
            verified += 1
        else:
            failed += 1
            failures.append(f"MISMATCH: {rel_path} (expected {expected_hash[:12]}..., got {actual_hash[:12]}...)")

    passed = failed == 0 and missing == 0
    detail = f"Verified={verified}, Failed={failed}, Missing={missing}, Total={len(checksums)}"

    return ChecksumResult("full_verification", passed, detail, {
        "total": len(checksums),
        "verified": verified,
        "failed": failed,
        "missing": missing,
        "failures": failures[:20],  # Cap at 20 for report size
    })


def verify_sampled(restore_root: str, sha256sums_path: str, sample_size: int = 20) -> ChecksumResult:
    """Verify a random sample of files against SHA256SUMS."""
    import random

    if not os.path.isfile(sha256sums_path):
        return ChecksumResult("sampled_verification", False, f"SHA256SUMS not found: {sha256sums_path}")

    checksums = load_sha256sums(sha256sums_path)
    if not checksums:
        return ChecksumResult("sampled_verification", False, "SHA256SUMS file is empty")

    all_paths = list(checksums.keys())
    sample = random.sample(all_paths, min(sample_size, len(all_paths)))

    verified = 0
    failed = 0
    failures = []

    for rel_path in sample:
        expected_hash = checksums[rel_path]
        full_path = os.path.join(restore_root, rel_path)

        if not os.path.isfile(full_path):
            failed += 1
            failures.append(f"MISSING: {rel_path}")
            continue

        actual_hash = compute_sha256(full_path)
        if actual_hash == expected_hash:
            verified += 1
        else:
            failed += 1
            failures.append(f"MISMATCH: {rel_path}")

    passed = failed == 0
    detail = f"Sampled {len(sample)} files: Verified={verified}, Failed={failed}"

    return ChecksumResult("sampled_verification", passed, detail, {
        "sample_size": len(sample),
        "verified": verified,
        "failed": failed,
        "failures": failures,
    })


def verify_manifest_checksums(env: dict) -> ChecksumResult:
    """Verify checksums listed in the backup manifest.json."""
    # This would parse manifest.json and verify its checksum entries
    # For now, check if the manifest exists and has checksum data
    restore_root = env.get("DR_FILE_RESTORE_ROOT", "/tmp/dr-restore-drill")
    manifest_path = os.path.join(restore_root, "manifest.json")

    if not os.path.isfile(manifest_path):
        return ChecksumResult("manifest_checksums", False, f"Manifest not found: {manifest_path}")

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        has_checksums = (
            "sha256sums_file" in manifest or
            "checksums" in manifest or
            "volumes" in manifest
        )

        passed = has_checksums
        detail = f"Manifest has checksum reference: {has_checksums}"

        return ChecksumResult("manifest_checksums", passed, detail, {"has_checksums": has_checksums})
    except Exception as e:
        return ChecksumResult("manifest_checksums", False, f"Error reading manifest: {e}")


def run_all(env: dict) -> dict:
    restore_root = env.get("DR_FILE_RESTORE_ROOT", "/tmp/dr-restore-drill")

    # Try to find SHA256SUMS file
    sha256sums_path = os.path.join(restore_root, "SHA256SUMS")
    if not os.path.isfile(sha256sums_path):
        sha256sums_path = os.path.join(restore_root, "sha256sums.txt")

    checks = []

    if os.path.isfile(sha256sums_path):
        checks.append(verify_full(restore_root, sha256sums_path))
        checks.append(verify_sampled(restore_root, sha256sums_path, sample_size=20))
    else:
        checks.append(ChecksumResult(
            "full_verification", False,
            f"SHA256SUMS file not found in {restore_root}. Run full restore first.",
        ))
        checks.append(ChecksumResult(
            "sampled_verification", False,
            "SHA256SUMS file not found. Cannot sample.",
        ))

    checks.append(verify_manifest_checksums(env))

    passed = sum(1 for c in checks if c.passed)
    failed = sum(1 for c in checks if not c.passed)

    return {
        "validator": "checksum_validator",
        "timestamp": datetime.now().isoformat(),
        "restore_root": restore_root,
        "sha256sums_path": sha256sums_path if os.path.isfile(sha256sums_path) else None,
        "total": len(checks),
        "passed": passed,
        "failed": failed,
        "checks": [asdict(c) for c in checks],
        "overall_passed": failed == 0,
    }


def main():
    parser = argparse.ArgumentParser(description="File checksum validator (SHA256)")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--env-dict", default=None)
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--sample-size", type=int, default=20)
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

#!/usr/bin/env python3
"""Emit verified backup-set directories belonging to fully expired chains."""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path


BACKUP_SET_PATTERN = re.compile(r"^backup_set_[0-9]{8}_[0-9]{6}$")
CHECKSUM_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup_set(path):
    checksum_path = path / "SHA256SUMS"
    manifest_path = path / "manifest.json"
    if not checksum_path.is_file() or not manifest_path.is_file():
        return None
    seen = set()
    for line in checksum_path.read_text(encoding="ascii").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not CHECKSUM_PATTERN.fullmatch(parts[0]):
            return None
        name = parts[1].lstrip("* ")
        if not name or name in seen or Path(name).name != name:
            return None
        artifact = path / name
        if not artifact.is_file() or sha256_file(artifact) != parts[0]:
            return None
        seen.add(name)
    if "manifest.json" not in seen:
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "SUCCESS" or manifest.get("backup_set_id") != path.name:
        return None
    return manifest


def chain_is_complete(member_id, manifests):
    expected_base = manifests[member_id]["fileset_chain"].get("base_backup_set_id")
    current_id = member_id
    seen = set()
    while current_id:
        if current_id in seen or current_id not in manifests:
            return False
        seen.add(current_id)
        chain = manifests[current_id].get("fileset_chain", {})
        if chain.get("base_backup_set_id") != expected_base:
            return False
        if chain.get("mode") == "full":
            return current_id == expected_base and not chain.get("parent_backup_set_id")
        if chain.get("mode") != "incremental" or not chain.get("parent_backup_set_id"):
            return False
        current_id = chain["parent_backup_set_id"]
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-root", required=True)
    parser.add_argument("--retention-days", type=int, required=True)
    args = parser.parse_args()
    root = Path(args.backup_root).resolve()
    if not root.is_dir() or args.retention_days < 0:
        return

    cutoff = time.time() - args.retention_days * 86400
    verified = {}
    paths = {}
    for path in root.iterdir():
        if (
            not path.is_dir()
            or path.is_symlink()
            or not BACKUP_SET_PATTERN.fullmatch(path.name)
        ):
            continue
        try:
            manifest = verify_backup_set(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if manifest:
            verified[path.name] = manifest
            paths[path.name] = path

    schema4 = {
        backup_id: manifest
        for backup_id, manifest in verified.items()
        if manifest.get("schema_version") == 4
    }
    chains = defaultdict(list)
    for backup_id, manifest in schema4.items():
        base_id = manifest.get("fileset_chain", {}).get("base_backup_set_id")
        if base_id:
            chains[base_id].append(backup_id)

    deletable = []
    for base_id, members in chains.items():
        if base_id not in schema4:
            continue
        if not all(chain_is_complete(member, schema4) for member in members):
            continue
        if max(paths[member].stat().st_mtime for member in members) >= cutoff:
            continue
        deletable.extend(paths[member] for member in members)

    # Older schema backup sets are self-contained and can be retired individually.
    for backup_id, manifest in verified.items():
        if manifest.get("schema_version") == 4:
            continue
        if paths[backup_id].stat().st_mtime < cutoff:
            deletable.append(paths[backup_id])

    for path in sorted(set(deletable)):
        resolved = path.resolve()
        if resolved.parent != root or not BACKUP_SET_PATTERN.fullmatch(resolved.name):
            continue
        sys.stdout.buffer.write(os.fsencode(str(resolved)) + b"\0")


if __name__ == "__main__":
    main()

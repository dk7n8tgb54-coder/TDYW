#!/usr/bin/env python3
"""Select the newest complete fileset backup chain for an incremental parent."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


BACKUP_SET_PATTERN = re.compile(r"^backup_set_[0-9]{8}_[0-9]{6}$")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_candidate(path):
    manifest_path = path / "manifest.json"
    checksum_path = path / "SHA256SUMS"
    documents_path = path / "documents.manifest.json"
    media_path = path / "media.manifest.json"
    if not all(item.is_file() for item in (manifest_path, checksum_path, documents_path, media_path)):
        return None

    checksums = {}
    for line in checksum_path.read_text(encoding="ascii").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            return None
        checksums[parts[1].lstrip("* ")] = parts[0]
    for name in ("manifest.json", "documents.manifest.json", "media.manifest.json"):
        if checksums.get(name) != sha256_file(path / name):
            return None

    root = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = json.loads(documents_path.read_text(encoding="utf-8"))
    media = json.loads(media_path.read_text(encoding="utf-8"))
    if root.get("schema_version") != 4 or root.get("status") != "SUCCESS":
        return None
    if root.get("backup_set_id") != path.name:
        return None
    if documents.get("schema_version") != 2 or media.get("schema_version") != 2:
        return None
    if documents != root.get("filesets", {}).get("documents"):
        return None
    if media != root.get("filesets", {}).get("media"):
        return None
    if documents.get("backup_set_id") != path.name or media.get("backup_set_id") != path.name:
        return None
    return root


def chain_is_complete(backup_set_id, candidates):
    seen = set()
    current_id = backup_set_id
    expected_base = candidates[backup_set_id]["fileset_chain"]["base_backup_set_id"]
    while current_id:
        if current_id in seen or current_id not in candidates:
            return False
        seen.add(current_id)
        manifest = candidates[current_id]
        chain = manifest.get("fileset_chain", {})
        if chain.get("base_backup_set_id") != expected_base:
            return False
        mode = chain.get("mode")
        parent_id = chain.get("parent_backup_set_id")
        if mode == "full":
            return current_id == expected_base and not parent_id
        if mode != "incremental" or not parent_id:
            return False
        current_id = parent_id
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-root", required=True)
    args = parser.parse_args()
    root = Path(args.backup_root).resolve()
    try:
        if not root.is_dir():
            return
    except PermissionError:
        print(f"ERROR: cannot read backup root: {root}", file=sys.stderr)
        raise SystemExit(1)

    candidates = {}
    paths = {}
    for path in root.iterdir():
        if not path.is_dir() or not BACKUP_SET_PATTERN.fullmatch(path.name):
            continue
        try:
            manifest = load_candidate(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if manifest:
            candidates[path.name] = manifest
            paths[path.name] = path

    for backup_set_id in sorted(candidates, reverse=True):
        if chain_is_complete(backup_set_id, candidates):
            chain = candidates[backup_set_id]["fileset_chain"]
            print(
                "\t".join(
                    (
                        backup_set_id,
                        chain["base_backup_set_id"],
                        str(paths[backup_set_id]),
                    )
                )
            )
            return


if __name__ == "__main__":
    main()

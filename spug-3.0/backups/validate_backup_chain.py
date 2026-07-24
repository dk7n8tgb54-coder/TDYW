#!/usr/bin/env python3
"""Validate a schema-v4 backup chain and write a machine-readable restore plan."""

import argparse
import json
import os
import tempfile
from pathlib import Path

from backup_chain import resolve_chain


def write_atomic(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-set-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    chain = resolve_chain(args.backup_set_dir)
    target_path, target_manifest = chain[-1]
    artifacts = target_manifest["database"]["artifacts"]
    logical = next(item for item in artifacts if item["type"] == "logical")
    physical = next((item for item in artifacts if item["type"] == "physical"), None)
    payload = {
        "schema_version": 1,
        "target_backup_set_id": target_path.name,
        "backup_root": str(target_path.parent),
        "chain": [path.name for path, _ in chain],
        "source_database_name": target_manifest["database"]["name"],
        "database_image": target_manifest["database"]["image"],
        "logical_database_artifact": str(target_path / logical["artifact"]),
        "physical_database_artifact": (
            str(target_path / physical["artifact"]) if physical else None
        ),
        "fileset_mode": target_manifest["fileset_chain"]["mode"],
        "fileset_base_backup_set_id": target_manifest["fileset_chain"][
            "base_backup_set_id"
        ],
    }
    write_atomic(args.output, payload)


if __name__ == "__main__":
    main()

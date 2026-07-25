#!/usr/bin/env python3
"""Create one self-contained full fileset snapshot."""

import argparse
import os
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from create_fileset_archive import sha256_file, snapshot, stable_entries, write_json_atomic


def create_snapshot(
    source,
    archive,
    manifest,
    fileset,
    backup_set_id,
):
    source_path = os.path.abspath(source)
    source_real = os.path.realpath(source_path)
    if source_path != source_real or not os.path.isdir(source_real):
        raise RuntimeError("source must be an existing, non-symlink directory")
    archive_path = os.path.abspath(archive)
    manifest_path = os.path.abspath(manifest)
    for output in (archive_path, manifest_path):
        if os.path.commonpath((source_real, output)) == source_real:
            raise RuntimeError("snapshot output must not be inside the source directory")
    os.makedirs(os.path.dirname(archive_path), exist_ok=True)

    before = stable_entries(source_real)
    current_directories = {
        relative.as_posix() for _, relative, _, kind in before if kind == "directory"
    }
    current_file_entries = {
        relative.as_posix(): (absolute, original)
        for absolute, relative, original, kind in before
        if kind == "file"
    }

    added_directories = sorted(current_directories)

    records = []
    changed_files = []
    for relative in sorted(current_file_entries):
        absolute, original = current_file_entries[relative]
        digest = sha256_file(absolute)
        current = os.stat(absolute, follow_symlinks=False)
        if snapshot(original) != snapshot(current):
            raise RuntimeError(f"file changed while being inspected: {relative}")
        changed_files.append(relative)
        records.append(
            {
                "relative_path": relative,
                "size": original.st_size,
                "mtime_ns": original.st_mtime_ns,
                "ctime_ns": original.st_ctime_ns,
                "sha256": digest,
            }
        )

    fd, temporary_archive = tempfile.mkstemp(
        prefix=f".{os.path.basename(archive_path)}.", dir=os.path.dirname(archive_path)
    )
    os.close(fd)
    try:
        with tarfile.open(temporary_archive, "w:gz", format=tarfile.PAX_FORMAT) as tar:
            for relative in added_directories:
                absolute = os.path.join(source_real, *Path(relative).parts)
                tar.add(absolute, arcname=relative, recursive=False)
            for relative in changed_files:
                absolute, original = current_file_entries[relative]
                tar.add(absolute, arcname=relative, recursive=False)
                current = os.stat(absolute, follow_symlinks=False)
                if snapshot(original) != snapshot(current):
                    raise RuntimeError(f"file changed while being archived: {relative}")

        after = stable_entries(source_real)
        before_state = [
            (entry[1].as_posix(), entry[3], snapshot(entry[2])) for entry in before
        ]
        after_state = [
            (entry[1].as_posix(), entry[3], snapshot(entry[2])) for entry in after
        ]
        if before_state != after_state:
            raise RuntimeError("fileset changed while being archived")
        with tarfile.open(temporary_archive, "r:gz") as tar:
            tar.getmembers()
        os.replace(temporary_archive, archive_path)
    except Exception:
        try:
            os.unlink(temporary_archive)
        except FileNotFoundError:
            pass
        raise

    created_at = datetime.now(timezone.utc).isoformat()
    archive_digest = sha256_file(archive_path)
    payload = {
        "schema_version": 3,
        "fileset": fileset,
        "backup_mode": "full",
        "backup_set_id": backup_set_id,
        "source_path": source_real,
        "created_at": created_at,
        "file_count": len(records),
        "directory_count": len(current_directories),
        "total_bytes": sum(item["size"] for item in records),
        "archive": os.path.basename(archive_path),
        "archive_size": os.path.getsize(archive_path),
        "archive_sha256": archive_digest,
        "directories": sorted(current_directories),
        "files": records,
    }
    write_json_atomic(manifest_path, payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--backup-set-id", required=True)
    args = parser.parse_args()
    create_snapshot(
        args.source,
        args.archive,
        args.manifest,
        args.name,
        args.backup_set_id,
    )


if __name__ == "__main__":
    main()

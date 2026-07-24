#!/usr/bin/env python3
"""Create a full or incremental fileset snapshot for a consistent backup set."""

import argparse
import json
import os
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from create_fileset_archive import sha256_file, snapshot, stable_entries, write_json_atomic


def load_previous_manifest(path, fileset):
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema_version") != 2:
        raise RuntimeError("incremental parent must use fileset manifest schema_version 2")
    if payload.get("fileset") != fileset:
        raise RuntimeError("incremental parent fileset name does not match")
    if not isinstance(payload.get("files"), list) or not isinstance(
        payload.get("directories"), list
    ):
        raise RuntimeError("incremental parent manifest is incomplete")
    return payload


def file_map(payload):
    if not payload:
        return {}
    records = {}
    for item in payload["files"]:
        relative = item.get("relative_path")
        if not relative or relative in records:
            raise RuntimeError("incremental parent contains invalid or duplicate paths")
        records[relative] = item
    return records


def metadata_matches(previous, current):
    return all(
        previous.get(key) == current
        for key, current in (
            ("size", current.st_size),
            ("mtime_ns", current.st_mtime_ns),
            ("ctime_ns", current.st_ctime_ns),
        )
    ) and bool(previous.get("sha256"))


def create_snapshot(
    source,
    archive,
    manifest,
    delta_manifest,
    fileset,
    mode,
    backup_set_id,
    base_backup_set_id,
    parent_backup_set_id="",
    previous_manifest_path="",
):
    if mode not in ("full", "incremental"):
        raise RuntimeError("fileset mode must be full or incremental")
    if mode == "incremental" and not previous_manifest_path:
        raise RuntimeError("incremental mode requires a previous manifest")

    previous = load_previous_manifest(previous_manifest_path, fileset)
    previous_files = file_map(previous)
    previous_directories = set(previous.get("directories", [])) if previous else set()

    source_real = os.path.realpath(source)
    archive_path = os.path.abspath(archive)
    manifest_path = os.path.abspath(manifest)
    delta_path = os.path.abspath(delta_manifest)
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

    added_directories = sorted(current_directories - previous_directories)
    deleted_directories = sorted(
        previous_directories - current_directories,
        key=lambda value: (value.count("/"), value),
        reverse=True,
    )
    deleted_files = sorted(set(previous_files) - set(current_file_entries))

    records = []
    changed_files = []
    for relative in sorted(current_file_entries):
        absolute, original = current_file_entries[relative]
        old = previous_files.get(relative)
        if mode == "incremental" and old and metadata_matches(old, original):
            digest = old["sha256"]
        else:
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
    delta = {
        "schema_version": 1,
        "fileset": fileset,
        "backup_mode": mode,
        "backup_set_id": backup_set_id,
        "base_backup_set_id": base_backup_set_id,
        "parent_backup_set_id": parent_backup_set_id or None,
        "created_at": created_at,
        "archive": os.path.basename(archive_path),
        "archive_size": os.path.getsize(archive_path),
        "archive_sha256": archive_digest,
        "added_or_changed_files": changed_files,
        "added_directories": added_directories,
        "deleted_files": deleted_files,
        "deleted_directories": deleted_directories,
    }
    payload = {
        "schema_version": 2,
        "fileset": fileset,
        "backup_mode": mode,
        "backup_set_id": backup_set_id,
        "base_backup_set_id": base_backup_set_id,
        "parent_backup_set_id": parent_backup_set_id or None,
        "source_path": source_real,
        "created_at": created_at,
        "file_count": len(records),
        "directory_count": len(current_directories),
        "total_bytes": sum(item["size"] for item in records),
        "archive": os.path.basename(archive_path),
        "archive_size": os.path.getsize(archive_path),
        "archive_sha256": archive_digest,
        "delta_manifest": os.path.basename(delta_path),
        "directories": sorted(current_directories),
        "files": records,
    }
    write_json_atomic(delta_path, delta)
    write_json_atomic(manifest_path, payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--delta-manifest", required=True)
    parser.add_argument("--mode", choices=("full", "incremental"), required=True)
    parser.add_argument("--backup-set-id", required=True)
    parser.add_argument("--base-backup-set-id", required=True)
    parser.add_argument("--parent-backup-set-id", default="")
    parser.add_argument("--previous-manifest", default="")
    args = parser.parse_args()
    create_snapshot(
        args.source,
        args.archive,
        args.manifest,
        args.delta_manifest,
        args.name,
        args.mode,
        args.backup_set_id,
        args.base_backup_set_id,
        args.parent_backup_set_id,
        args.previous_manifest,
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Create a verified tar.gz and JSON manifest from a stopped data volume."""

import argparse
import hashlib
import json
import os
import stat
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_entries(source):
    entries = []

    def visit(directory, relative):
        with os.scandir(directory) as iterator:
            children = sorted(iterator, key=lambda item: os.fsencode(item.name))
        for child in children:
            child_relative = relative / child.name
            child_path = os.path.join(directory, child.name)
            info = child.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise RuntimeError(f"symbolic links are not allowed: {child_relative.as_posix()}")
            if stat.S_ISDIR(info.st_mode):
                entries.append((child_path, child_relative, info, "directory"))
                visit(child_path, child_relative)
            elif stat.S_ISREG(info.st_mode):
                entries.append((child_path, child_relative, info, "file"))
            else:
                raise RuntimeError(f"unsupported filesystem entry: {child_relative.as_posix()}")

    visit(source, PurePosixPath())
    return entries


def snapshot(info):
    # Windows DirEntry.stat() may report zero device/inode values while os.stat()
    # reports real values, and ctime semantics differ from Linux. Production runs
    # on Linux and compare the full identity plus mtime/ctime.
    if os.name == "nt":
        return (info.st_size, info.st_mtime_ns)
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def write_json_atomic(path, payload):
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


def create_archive(source, archive, manifest, name):
    source_path = os.path.abspath(source)
    source_real = os.path.realpath(source_path)
    if source_path != source_real or not os.path.isdir(source_real):
        raise RuntimeError("source must be an existing, non-symlink directory")

    archive_path = os.path.abspath(archive)
    manifest_path = os.path.abspath(manifest)
    for output in (archive_path, manifest_path):
        if os.path.commonpath((source_real, output)) == source_real:
            raise RuntimeError("output must not be inside the source directory")

    os.makedirs(os.path.dirname(archive_path), exist_ok=True)
    before = stable_entries(source_real)
    files = []
    total_bytes = 0

    temporary_archive = f"{archive_path}.tmp"
    try:
        with tarfile.open(temporary_archive, "w:gz", format=tarfile.PAX_FORMAT) as tar:
            for absolute, relative, original, kind in before:
                relative_text = relative.as_posix()
                if kind == "directory":
                    tar.add(absolute, arcname=relative_text, recursive=False)
                    continue

                digest = sha256_file(absolute)
                tar.add(absolute, arcname=relative_text, recursive=False)
                current = os.stat(absolute, follow_symlinks=False)
                if snapshot(original) != snapshot(current):
                    raise RuntimeError(f"file changed while being archived: {relative_text}")
                files.append({
                    "relative_path": relative_text,
                    "size": original.st_size,
                    "mtime_ns": original.st_mtime_ns,
                    "ctime_ns": original.st_ctime_ns,
                    "sha256": digest,
                })
                total_bytes += original.st_size

        after = stable_entries(source_real)
        before_state = [(entry[1].as_posix(), entry[3], snapshot(entry[2])) for entry in before]
        after_state = [(entry[1].as_posix(), entry[3], snapshot(entry[2])) for entry in after]
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

    payload = {
        "schema_version": 1,
        "fileset": name,
        "source_path": source_real,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files),
        "directory_count": sum(1 for entry in before if entry[3] == "directory"),
        "total_bytes": total_bytes,
        "archive": os.path.basename(archive_path),
        "archive_size": os.path.getsize(archive_path),
        "archive_sha256": sha256_file(archive_path),
        "files": files,
    }
    write_json_atomic(manifest_path, payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    create_archive(args.source, args.archive, args.manifest, args.name)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Replay a validated full/incremental fileset chain into an empty target."""

import argparse
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from create_fileset_archive import sha256_file, stable_entries


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def safe_relative(value):
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts or any(
        part in ("", ".", "..") for part in relative.parts
    ):
        raise RuntimeError(f"unsafe fileset path: {value!r}")
    return relative


def target_path(root, relative):
    candidate = root.joinpath(*safe_relative(relative).parts)
    if candidate == root or root not in candidate.parents:
        raise RuntimeError(f"fileset path escaped restore target: {relative!r}")
    return candidate


def clear_target(root):
    resolved = root.resolve()
    if resolved == Path(resolved.anchor) or len(resolved.parts) < 3:
        raise RuntimeError(f"refusing to clear unsafe restore target: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    for child in resolved.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def apply_deletions(root, delta):
    for relative in delta.get("deleted_files", []):
        path = target_path(root, relative)
        if path.is_dir() and not path.is_symlink():
            raise RuntimeError(f"expected deleted file is a directory: {relative}")
        if path.exists() or path.is_symlink():
            path.unlink()
    for relative in delta.get("deleted_directories", []):
        path = target_path(root, relative)
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise RuntimeError(f"expected deleted directory has another type: {relative}")
        if path.is_dir():
            shutil.rmtree(path)


def extract_delta(root, archive_path, delta):
    expected_files = set(delta.get("added_or_changed_files", []))
    expected_directories = set(delta.get("added_directories", []))
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        actual_files = {member.name.rstrip("/") for member in members if member.isreg()}
        actual_directories = {
            member.name.rstrip("/") for member in members if member.isdir()
        }
        if any(not (member.isreg() or member.isdir()) for member in members):
            raise RuntimeError(f"archive contains a link or special file: {archive_path}")
        if actual_files != expected_files or actual_directories != expected_directories:
            raise RuntimeError(f"archive members do not match delta manifest: {archive_path}")

        for relative in sorted(actual_directories):
            target_path(root, relative).mkdir(parents=True, exist_ok=True)
        for member in members:
            if not member.isreg():
                continue
            destination = target_path(root, member.name.rstrip("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(f"unable to read archive member: {member.name}")
            fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
            try:
                with os.fdopen(fd, "wb") as output:
                    shutil.copyfileobj(source, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temporary, member.mode & 0o777)
                os.replace(temporary, destination)
            except Exception:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
                raise


def verify_target(root, final_manifest):
    expected_files = {
        item["relative_path"]: item for item in final_manifest.get("files", [])
    }
    expected_directories = set(final_manifest.get("directories", []))
    actual = stable_entries(root)
    actual_directories = {
        relative.as_posix() for _, relative, _, kind in actual if kind == "directory"
    }
    actual_files = {
        relative.as_posix(): (absolute, stat_result)
        for absolute, relative, stat_result, kind in actual
        if kind == "file"
    }
    if actual_directories != expected_directories:
        raise RuntimeError("restored directory set does not match target manifest")
    if set(actual_files) != set(expected_files):
        raise RuntimeError("restored file set does not match target manifest")
    for relative, expected in expected_files.items():
        absolute, stat_result = actual_files[relative]
        if stat_result.st_size != expected["size"]:
            raise RuntimeError(f"restored file size mismatch: {relative}")
        if sha256_file(absolute) != expected["sha256"]:
            raise RuntimeError(f"restored file SHA-256 mismatch: {relative}")
        os.utime(
            absolute,
            ns=(expected["mtime_ns"], expected["mtime_ns"]),
            follow_symlinks=False,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-root", required=True)
    parser.add_argument("--chain", nargs="+", required=True)
    parser.add_argument("--fileset", choices=("documents", "media"), required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--clear-target", action="store_true")
    args = parser.parse_args()

    backup_root = Path(args.backup_root).resolve()
    target = Path(args.target).resolve()
    if not args.clear_target:
        raise RuntimeError("--clear-target is required for deterministic fileset restore")
    clear_target(target)

    final_manifest = None
    for backup_set_id in args.chain:
        backup_set = backup_root / backup_set_id
        if backup_set.parent != backup_root or not backup_set.is_dir():
            raise RuntimeError(f"invalid backup chain member: {backup_set_id}")
        delta = load_json(backup_set / f"{args.fileset}.delta.json")
        if delta.get("backup_set_id") != backup_set_id:
            raise RuntimeError("delta manifest backup_set_id does not match chain")
        apply_deletions(target, delta)
        extract_delta(target, backup_set / f"{args.fileset}.tar.gz", delta)
        final_manifest = load_json(backup_set / f"{args.fileset}.manifest.json")

    if final_manifest is None:
        raise RuntimeError("restore chain is empty")
    verify_target(target, final_manifest)


if __name__ == "__main__":
    main()

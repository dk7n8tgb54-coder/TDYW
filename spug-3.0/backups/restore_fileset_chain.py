#!/usr/bin/env python3
"""Validate and restore one independent full fileset archive."""

import argparse
import os
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from backup_chain import load_json, validate_member
from create_fileset_archive import sha256_file, stable_entries


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


def inspect_archive(archive_path, snapshot):
    expected_files = [item.get("relative_path") for item in snapshot.get("files", [])]
    expected_directories = snapshot.get("directories")
    if not isinstance(expected_files, list) or not isinstance(expected_directories, list):
        raise RuntimeError("fileset archive member lists are invalid")
    if len(expected_files) != len(set(expected_files)) or len(expected_directories) != len(
        set(expected_directories)
    ):
        raise RuntimeError("fileset archive member lists contain duplicates")
    for value in expected_files + expected_directories:
        safe_relative(value)

    with tarfile.open(archive_path, "r|gz") as archive:
        actual_files = []
        actual_directories = []
        seen = set()
        for member in archive:
            name = member.name.rstrip("/")
            safe_relative(name)
            if name in seen:
                raise RuntimeError(f"archive contains a duplicate member: {name}")
            seen.add(name)
            if member.isreg():
                actual_files.append(name)
            elif member.isdir():
                actual_directories.append(name)
            else:
                raise RuntimeError(f"archive contains a link or special file: {name}")

    if set(actual_files) != set(expected_files) or set(actual_directories) != set(
        expected_directories
    ):
        raise RuntimeError(f"archive members do not match full manifest: {archive_path}")


def validate_restore_inputs(
    backup_root, backup_set_id, fileset, prevalidated=False, inspect=False
):
    backup_set = (backup_root / backup_set_id).resolve()
    if backup_set.parent != backup_root or not backup_set.is_dir():
        raise RuntimeError(f"invalid backup set: {backup_set_id}")
    if prevalidated:
        manifest = load_json(backup_set / "manifest.json")
        if (
            manifest.get("schema_version") != 5
            or manifest.get("status") != "SUCCESS"
            or manifest.get("backup_set_id") != backup_set_id
            or manifest.get("fileset_mode") != "full"
        ):
            raise RuntimeError("prevalidated restore plan no longer matches backup set")
    else:
        manifest = validate_member(backup_set)
    if manifest["backup_set_id"] != backup_set_id:
        raise RuntimeError("backup set identity does not match restore plan")
    snapshot = load_json(backup_set / f"{fileset}.manifest.json")
    if snapshot != manifest.get("filesets", {}).get(fileset):
        raise RuntimeError("fileset sidecar no longer matches root manifest")
    archive_path = backup_set / f"{fileset}.tar.gz"
    if inspect:
        inspect_archive(archive_path, snapshot)
    return archive_path, snapshot


def extract_full(root, archive_path, snapshot):
    expected_files = {item["relative_path"] for item in snapshot["files"]}
    expected_directories = set(snapshot["directories"])
    actual_files = set()
    actual_directories = set()
    seen = set()
    with tarfile.open(archive_path, "r|gz") as archive:
        for member in archive:
            relative = member.name.rstrip("/")
            safe_relative(relative)
            if relative in seen:
                raise RuntimeError(f"archive contains a duplicate member: {relative}")
            seen.add(relative)
            if member.isdir():
                if relative not in expected_directories:
                    raise RuntimeError(
                        f"archive contains an unexpected directory: {relative}"
                    )
                target_path(root, relative).mkdir(parents=True, exist_ok=True)
                actual_directories.add(relative)
                continue
            if not member.isreg():
                raise RuntimeError(f"archive contains a link or special file: {relative}")
            if relative not in expected_files:
                raise RuntimeError(f"archive contains an unexpected file: {relative}")
            actual_files.add(relative)
            destination = target_path(root, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(f"unable to read archive member: {member.name}")
            fd, temporary = tempfile.mkstemp(
                prefix=f".{destination.name}.", dir=destination.parent
            )
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
    if actual_files != expected_files or actual_directories != expected_directories:
        raise RuntimeError("archive members do not match the full manifest")


def verify_target(root, manifest, ignored_top_level=()):
    expected_files = {
        item["relative_path"]: item for item in manifest.get("files", [])
    }
    expected_directories = set(manifest.get("directories", []))
    ignored = set(ignored_top_level)
    actual = [
        entry
        for entry in stable_entries(root)
        if not entry[1].parts or entry[1].parts[0] not in ignored
    ]
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


def restore_full(target, archive_path, snapshot):
    if Path(os.path.abspath(target)) != target.resolve():
        raise RuntimeError("restore target and its parents must not be symbolic links")
    target.mkdir(parents=True, exist_ok=True)
    resolved = target.resolve()
    if resolved == Path(resolved.anchor) or len(resolved.parts) < 3:
        raise RuntimeError(f"refusing to restore into unsafe target: {resolved}")

    stage = Path(tempfile.mkdtemp(prefix=".tdyw-restore-stage-", dir=resolved))
    rollback = None
    installed = []
    try:
        extract_full(stage, archive_path, snapshot)
        verify_target(stage, snapshot)

        rollback = Path(
            tempfile.mkdtemp(prefix=".tdyw-restore-rollback-", dir=resolved)
        )
        for child in list(resolved.iterdir()):
            if child in (stage, rollback):
                continue
            os.replace(child, rollback / child.name)
        for child in list(stage.iterdir()):
            os.replace(child, resolved / child.name)
            installed.append(child.name)
        verify_target(resolved, snapshot, ignored_top_level=(stage.name, rollback.name))
        shutil.rmtree(stage)
        stage = None
        completed_rollback = rollback
        rollback = None
        shutil.rmtree(completed_rollback)
    except Exception:
        if rollback is not None and rollback.exists():
            for name in installed:
                installed_path = resolved / name
                if installed_path.is_dir() and not installed_path.is_symlink():
                    shutil.rmtree(installed_path)
                elif installed_path.exists() or installed_path.is_symlink():
                    installed_path.unlink()
            for child in list(rollback.iterdir()):
                os.replace(child, resolved / child.name)
            shutil.rmtree(rollback, ignore_errors=True)
        raise
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-root", required=True)
    parser.add_argument("--backup-set-id", required=True)
    parser.add_argument("--fileset", choices=("documents", "media"), required=True)
    parser.add_argument("--target")
    parser.add_argument("--clear-target", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--prevalidated", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    backup_root = Path(args.backup_root).resolve()
    archive_path, snapshot = validate_restore_inputs(
        backup_root,
        args.backup_set_id,
        args.fileset,
        prevalidated=args.prevalidated,
        inspect=args.verify_only,
    )
    if args.verify_only:
        return
    if not args.target or not args.clear_target:
        raise RuntimeError("--target and --clear-target are required for restore")
    restore_full(Path(args.target), archive_path, snapshot)


if __name__ == "__main__":
    main()

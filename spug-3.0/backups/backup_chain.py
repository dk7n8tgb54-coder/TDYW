"""Validation helpers for independent full backup sets."""

import hashlib
import json
import re
from pathlib import Path


BACKUP_SET_PATTERN = re.compile(r"^backup_set_[0-9]{8}_[0-9]{6}$")
CHECKSUM_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def verify_checksums(backup_set_dir):
    checksum_path = backup_set_dir / "SHA256SUMS"
    if not checksum_path.is_file():
        raise RuntimeError(f"SHA256SUMS is missing: {backup_set_dir}")
    verified = {}
    for line in checksum_path.read_text(encoding="ascii").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not CHECKSUM_PATTERN.fullmatch(parts[0]):
            raise RuntimeError(f"invalid SHA256SUMS line in {backup_set_dir}")
        name = parts[1].lstrip("* ")
        if not name or name in verified or Path(name).name != name:
            raise RuntimeError(f"unsafe or duplicate checksum artifact: {name!r}")
        artifact = backup_set_dir / name
        if not artifact.is_file():
            raise RuntimeError(f"checksummed artifact is missing: {artifact}")
        if sha256_file(artifact) != parts[0]:
            raise RuntimeError(f"SHA-256 mismatch: {artifact}")
        verified[name] = parts[0]
    return verified


def validate_member(path):
    """Validate one self-contained schema-v5 full backup set."""
    path = Path(path).resolve()
    if not BACKUP_SET_PATTERN.fullmatch(path.name):
        raise RuntimeError("backup set directory name is invalid")

    verified = verify_checksums(path)
    required = {
        "database.sql.gz",
        "documents.tar.gz",
        "documents.manifest.json",
        "media.tar.gz",
        "media.manifest.json",
        "manifest.json",
    }
    if not required.issubset(verified):
        missing = ", ".join(sorted(required - verified))
        raise RuntimeError(f"backup set checksum coverage is incomplete: {missing}")

    manifest = load_json(path / "manifest.json")
    if manifest.get("schema_version") != 5 or manifest.get("status") != "SUCCESS":
        raise RuntimeError(f"backup set is not a successful schema-v5 set: {path}")
    if manifest.get("backup_set_id") != path.name:
        raise RuntimeError(f"backup_set_id does not match directory: {path}")
    if manifest.get("fileset_mode") != "full":
        raise RuntimeError("only independent full fileset backup sets are supported")

    database = manifest.get("database", {})
    if database.get("backup_mode") not in ("logical", "both"):
        raise RuntimeError("database backup mode must be logical or both")
    artifacts = database.get("artifacts", [])
    if any(item.get("type") not in ("logical", "physical") for item in artifacts):
        raise RuntimeError("database manifest contains an unsupported artifact")
    logical = [item for item in artifacts if item.get("type") == "logical"]
    physical = [item for item in artifacts if item.get("type") == "physical"]
    if len(logical) != 1 or logical[0].get("format") != "mariadb-dump-gzip":
        raise RuntimeError(f"exactly one logical mariadb-dump artifact is required: {path}")
    expected_physical = 1 if database.get("backup_mode") == "both" else 0
    if len(physical) != expected_physical:
        raise RuntimeError("physical database artifact does not match database backup mode")
    if physical and physical[0].get("format") != "mariabackup-tar-gzip":
        raise RuntimeError(f"unsupported physical database format: {path}")
    for artifact in logical + physical:
        name = artifact.get("artifact", "")
        if Path(name).name != name or name not in verified:
            raise RuntimeError(f"database artifact is unsafe or not checksummed: {name!r}")
        if artifact.get("sha256") != verified[name]:
            raise RuntimeError(f"manifest database hash mismatch: {path / name}")
        if artifact.get("size") != (path / name).stat().st_size:
            raise RuntimeError(f"manifest database size mismatch: {path / name}")

    for name in ("documents", "media"):
        snapshot = load_json(path / f"{name}.manifest.json")
        if snapshot != manifest.get("filesets", {}).get(name):
            raise RuntimeError(f"root manifest {name} snapshot does not match sidecar")
        if snapshot.get("schema_version") != 3:
            raise RuntimeError(f"unsupported {name} manifest schema")
        if snapshot.get("backup_set_id") != path.name or snapshot.get("fileset") != name:
            raise RuntimeError(f"{name} manifest identity does not match")
        if snapshot.get("backup_mode") != "full":
            raise RuntimeError(f"{name} must be an independent full backup")
        if snapshot.get("archive_sha256") != verified[f"{name}.tar.gz"]:
            raise RuntimeError(f"{name} archive hash does not match snapshot manifest")
        if snapshot.get("archive_size") != (path / f"{name}.tar.gz").stat().st_size:
            raise RuntimeError(f"{name} archive size does not match snapshot manifest")
        expected_files = [item.get("relative_path") for item in snapshot.get("files", [])]
        if len(expected_files) != len(set(expected_files)) or any(
            not item for item in expected_files
        ):
            raise RuntimeError(f"{name} full manifest contains invalid file paths")
    return manifest
